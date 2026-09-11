from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import verify_admin
from cali_skg.api.unified_migration import run_unified_migration
from cali_skg.core.cali_personal_skg import get_cali_skg

router = APIRouter(prefix="/cali/intelligence", tags=["cali-dossier-research"])


class ResearchRequest(BaseModel):
    mode: str = Field(default="full", pattern="^(full|web|news|events|background)$")
    timespan: str = Field(default="30d", min_length=2, max_length=16)
    max_results: int = Field(default=18, ge=1, le=50)
    query_hint: Optional[str] = Field(default=None, max_length=240)
    business_scope: str = Field(default="all", max_length=80)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> str:
    return str(get_cali_skg().db_path)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _hash(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{_hash(*parts)[:32]}"


def _ensure_schema() -> None:
    run_unified_migration(_db_path())
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_run (
              run_id TEXT PRIMARY KEY,
              contact_id TEXT NOT NULL,
              party_id TEXT,
              query TEXT NOT NULL,
              mode TEXT NOT NULL,
              timespan TEXT,
              business_scope TEXT,
              providers TEXT NOT NULL,
              status TEXT NOT NULL,
              result_count INTEGER NOT NULL DEFAULT 0,
              errors TEXT,
              started_at TEXT NOT NULL,
              completed_at TEXT,
              FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS contact_research_item (
              research_id TEXT PRIMARY KEY,
              contact_id TEXT NOT NULL,
              party_id TEXT,
              category TEXT NOT NULL,
              title TEXT NOT NULL,
              url TEXT NOT NULL,
              snippet TEXT,
              source_name TEXT,
              provider TEXT NOT NULL,
              published_at TEXT,
              query TEXT NOT NULL,
              confidence REAL NOT NULL DEFAULT 0.5,
              business_scope TEXT,
              captured_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              metadata TEXT,
              FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
              UNIQUE(contact_id, url, category)
            );

            CREATE INDEX IF NOT EXISTS ix_research_contact
              ON contact_research_item(contact_id, captured_at DESC);
            CREATE INDEX IF NOT EXISTS ix_research_category
              ON contact_research_item(contact_id, category, published_at DESC);
            CREATE INDEX IF NOT EXISTS ix_research_run_contact
              ON research_run(contact_id, started_at DESC);
            """
        )
        conn.commit()


def _candidate_config_paths() -> List[Path]:
    paths: List[Path] = []
    explicit = str(os.getenv("CALI_RESEARCH_CONFIG") or "").strip()
    if explicit:
        paths.append(Path(explicit))

    base_raw = str(os.getenv("CALI_DATA_ROOT") or "").strip()
    if not base_raw:
        try:
            base_raw = str(get_cali_skg().base_path)
        except Exception:
            base_raw = ""
    if base_raw:
        base = Path(base_raw)
        paths.extend(
            [
                base / "config" / "research_providers.json",
                base / "vault" / "config" / "research_providers.json",
                base / "research" / "research_providers.json",
            ]
        )
    return paths


def _load_config() -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    for path in _candidate_config_paths():
        try:
            if path.exists():
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config = loaded
                    config["_loaded_from"] = str(path)
                    break
        except Exception:
            continue
    return config


def _provider_settings(config: Dict[str, Any], name: str) -> Dict[str, Any]:
    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    item = providers.get(name) if isinstance(providers, dict) else None
    return item if isinstance(item, dict) else {}


def _tavily_key(config: Dict[str, Any]) -> str:
    provider = _provider_settings(config, "tavily")
    return str(os.getenv("TAVILY_API_KEY") or provider.get("api_key") or config.get("tavily_api_key") or "").strip()


def _provider_enabled(config: Dict[str, Any], name: str, default: bool = True) -> bool:
    provider = _provider_settings(config, name)
    if "enabled" not in provider:
        return default
    return bool(provider.get("enabled"))


def _timeout_seconds(config: Dict[str, Any]) -> float:
    raw = config.get("timeout_seconds", os.getenv("CALI_RESEARCH_TIMEOUT_SECONDS", "10"))
    try:
        return min(30.0, max(3.0, float(raw)))
    except Exception:
        return 10.0


def _clean_snippet(value: Any) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()[:1200]


def _contact_query(contact: sqlite3.Row, hint: Optional[str]) -> str:
    name = str(contact["name"] or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Dossier has no subject name to research")

    components = [f'"{name}"']
    company_role = str(contact["company_role"] or "").strip() if "company_role" in contact.keys() else ""
    organization = str(contact["organization_id"] or "").strip() if "organization_id" in contact.keys() else ""
    address = str(contact["address"] or "").strip()

    if company_role:
        components.append(company_role)
    if organization:
        components.append(organization)
    if address:
        city_parts = [part.strip() for part in address.split(",") if part.strip()]
        if len(city_parts) >= 2:
            components.append(city_parts[-2])
    if hint and hint.strip():
        components.append(hint.strip())

    return " ".join(components)


def _gdelt_timespan(value: str) -> str:
    raw = str(value or "30d").strip().lower()
    if re.fullmatch(r"\d+(min|h|hours|d|days|w|weeks|m|months)", raw):
        return raw
    aliases = {"day": "1d", "week": "1w", "month": "1m", "year": "3m"}
    return aliases.get(raw, "30d")


def _tavily_time_range(value: str) -> Optional[str]:
    raw = str(value or "").lower()
    match = re.match(r"^(\d+)([dhwmy])", raw)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d" and amount <= 1:
        return "day"
    if unit in {"d", "w"} and amount <= 7:
        return "week"
    if unit in {"d", "w", "m"} and amount <= 31:
        return "month"
    return "year"


async def _gdelt_search(client: httpx.AsyncClient, query: str, timespan: str, limit: int, category: str) -> List[Dict[str, Any]]:
    search_query = query
    if category == "events":
        search_query = f"{query} (event OR conference OR meeting OR appearance OR announcement OR launch)"
    response = await client.get(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query": search_query,
            "mode": "artlist",
            "maxrecords": min(50, max(1, limit)),
            "timespan": _gdelt_timespan(timespan),
            "sort": "datedesc",
            "format": "json",
        },
    )
    response.raise_for_status()
    payload = response.json()
    articles = payload.get("articles") if isinstance(payload, dict) else []
    results: List[Dict[str, Any]] = []
    for article in articles or []:
        if not isinstance(article, dict):
            continue
        url = str(article.get("url") or "").strip()
        title = str(article.get("title") or url).strip()
        if not url or not title:
            continue
        results.append(
            {
                "category": category,
                "title": title[:500],
                "url": url,
                "snippet": "",
                "source_name": str(article.get("domain") or "GDELT"),
                "provider": "gdelt",
                "published_at": article.get("seendate"),
                "confidence": 0.62,
                "metadata": {
                    "language": article.get("language"),
                    "source_country": article.get("sourcecountry"),
                    "social_image": article.get("socialimage"),
                },
            }
        )
    return results


async def _wikipedia_search(client: httpx.AsyncClient, query: str, limit: int) -> List[Dict[str, Any]]:
    response = await client.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "utf8": 1,
            "srlimit": min(10, max(1, limit)),
        },
    )
    response.raise_for_status()
    payload = response.json()
    rows = (((payload or {}).get("query") or {}).get("search") or []) if isinstance(payload, dict) else []
    results: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pageid = row.get("pageid")
        title = str(row.get("title") or "").strip()
        if not pageid or not title:
            continue
        results.append(
            {
                "category": "background",
                "title": title[:500],
                "url": f"https://en.wikipedia.org/?curid={pageid}",
                "snippet": _clean_snippet(row.get("snippet")),
                "source_name": "Wikipedia",
                "provider": "wikipedia",
                "published_at": None,
                "confidence": 0.50,
                "metadata": {"pageid": pageid},
            }
        )
    return results


async def _tavily_search(
    client: httpx.AsyncClient,
    api_key: str,
    query: str,
    limit: int,
    category: str,
    timespan: str,
) -> List[Dict[str, Any]]:
    topic = "news" if category in {"news", "events"} else "general"
    search_query = query
    if category == "events":
        search_query = f"{query} event conference meeting appearance announcement launch"
    body: Dict[str, Any] = {
        "query": search_query,
        "search_depth": "basic",
        "topic": topic,
        "max_results": min(20, max(1, limit)),
        "include_answer": False,
        "include_raw_content": False,
    }
    time_range = _tavily_time_range(timespan)
    if time_range and topic == "news":
        body["time_range"] = time_range
    response = await client.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
    )
    response.raise_for_status()
    payload = response.json()
    results: List[Dict[str, Any]] = []
    for row in (payload.get("results") or []) if isinstance(payload, dict) else []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or url).strip()
        if not url or not title:
            continue
        try:
            score = float(row.get("score") or 0.0)
        except Exception:
            score = 0.0
        results.append(
            {
                "category": category,
                "title": title[:500],
                "url": url,
                "snippet": _clean_snippet(row.get("content")),
                "source_name": str(row.get("source") or row.get("favicon") or "Tavily"),
                "provider": "tavily",
                "published_at": row.get("published_date"),
                "confidence": min(0.90, max(0.45, score if score else 0.68)),
                "metadata": {"score": row.get("score")},
            }
        )
    return results


def _dedupe_results(items: List[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    output: List[Dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= max_results:
            break
    return output


def _persist_results(
    contact_id: str,
    party_id: str,
    query: str,
    business_scope: str,
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    now = _utc_now()
    persisted: List[Dict[str, Any]] = []
    with _connect() as conn:
        for item in items:
            category = str(item.get("category") or "web")
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or url).strip()
            if not url or not title:
                continue
            snippet = str(item.get("snippet") or "")
            provider = str(item.get("provider") or "unknown")
            content_hash = _hash(title, url, snippet)
            research_id = _stable_id("research", contact_id, category, url)
            confidence = float(item.get("confidence") or 0.5)
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            conn.execute(
                """
                INSERT INTO contact_research_item(
                  research_id, contact_id, party_id, category, title, url, snippet,
                  source_name, provider, published_at, query, confidence, business_scope,
                  captured_at, last_seen_at, content_hash, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contact_id, url, category) DO UPDATE SET
                  title=excluded.title,
                  snippet=excluded.snippet,
                  source_name=excluded.source_name,
                  provider=excluded.provider,
                  published_at=COALESCE(excluded.published_at, contact_research_item.published_at),
                  query=excluded.query,
                  confidence=MAX(contact_research_item.confidence, excluded.confidence),
                  business_scope=excluded.business_scope,
                  last_seen_at=excluded.last_seen_at,
                  content_hash=excluded.content_hash,
                  metadata=excluded.metadata
                """,
                (
                    research_id,
                    contact_id,
                    party_id,
                    category,
                    title[:500],
                    url,
                    snippet[:4000] or None,
                    str(item.get("source_name") or "")[:300] or None,
                    provider,
                    item.get("published_at"),
                    query,
                    max(0.0, min(1.0, confidence)),
                    None if business_scope == "all" else business_scope,
                    now,
                    now,
                    content_hash,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )

            evidence_id = _stable_id("evidence", "web_research", contact_id, category, url)
            details = {
                "contact_id": contact_id,
                "party_id": party_id,
                "category": category,
                "title": title[:500],
                "url": url,
                "snippet": snippet[:1200],
                "provider": provider,
                "published_at": item.get("published_at"),
                "confidence": max(0.0, min(1.0, confidence)),
                "verification_state": "unverified_public_source",
            }
            conn.execute(
                """
                INSERT INTO evidence(
                  evidence_id, source_type, source_ref, business_scope, captured_at, content_hash, details
                ) VALUES (?, 'web_research', ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                  captured_at=excluded.captured_at,
                  content_hash=excluded.content_hash,
                  details=excluded.details
                """,
                (
                    evidence_id,
                    url,
                    None if business_scope == "all" else business_scope,
                    now,
                    content_hash,
                    json.dumps(details, ensure_ascii=False),
                ),
            )

            persisted.append(
                {
                    "research_id": research_id,
                    **item,
                    "captured_at": now,
                    "verification_state": "unverified_public_source",
                }
            )
        conn.commit()
    return persisted


@router.get("/research/providers")
def research_provider_status(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    config = _load_config()
    tavily_key = _tavily_key(config)
    return {
        "providers": {
            "gdelt": {"enabled": _provider_enabled(config, "gdelt", True), "configured": True},
            "wikipedia": {"enabled": _provider_enabled(config, "wikipedia", True), "configured": True},
            "tavily": {"enabled": _provider_enabled(config, "tavily", True), "configured": bool(tavily_key)},
        },
        "config_loaded": bool(config.get("_loaded_from")),
        "config_location": config.get("_loaded_from"),
        "note": "Provider secrets are never returned by this endpoint.",
    }


@router.get("/contacts/{contact_id}/research")
def list_contact_research(
    contact_id: str,
    limit: int = Query(default=24, ge=1, le=100),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        contact = conn.execute("SELECT id, name FROM contacts WHERE id=?", (contact_id,)).fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Dossier not found")
        rows = conn.execute(
            """
            SELECT research_id, contact_id, party_id, category, title, url, snippet,
                   source_name, provider, published_at, query, confidence,
                   business_scope, captured_at, last_seen_at, metadata
            FROM contact_research_item
            WHERE contact_id=?
            ORDER BY COALESCE(published_at, last_seen_at) DESC, last_seen_at DESC
            LIMIT ?
            """,
            (contact_id, limit),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(str(item.get("metadata") or "{}"))
        except Exception:
            item["metadata"] = {}
        item["verification_state"] = "unverified_public_source"
        items.append(item)
    return {"contact_id": contact_id, "items": items, "count": len(items)}


@router.post("/contacts/{contact_id}/research")
async def research_contact(
    contact_id: str,
    payload: ResearchRequest,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        contact = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Dossier not found")

    party_id = f"legacy-contact:{contact_id}"
    query = _contact_query(contact, payload.query_hint)
    config = _load_config()
    timeout = _timeout_seconds(config)
    tavily_key = _tavily_key(config)

    categories: List[str]
    if payload.mode == "full":
        categories = ["web", "news", "events", "background"]
    elif payload.mode == "background":
        categories = ["background"]
    else:
        categories = [payload.mode]

    run_id = _stable_id("research-run", contact_id, query, _utc_now())
    started_at = _utc_now()
    providers_used: List[str] = []
    errors: List[str] = []
    results: List[Dict[str, Any]] = []

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO research_run(
              run_id, contact_id, party_id, query, mode, timespan, business_scope,
              providers, status, result_count, errors, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 'running', 0, '[]', ?)
            """,
            (
                run_id,
                contact_id,
                party_id,
                query,
                payload.mode,
                payload.timespan,
                None if payload.business_scope == "all" else payload.business_scope,
                started_at,
            ),
        )
        conn.commit()

    headers = {"User-Agent": "VIV-Dossier-Research/1.0 (+local-owner-runtime)"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        if _provider_enabled(config, "tavily", True) and tavily_key:
            for category in [item for item in categories if item in {"web", "news", "events"}]:
                try:
                    batch = await _tavily_search(
                        client,
                        tavily_key,
                        query,
                        payload.max_results,
                        category,
                        payload.timespan,
                    )
                    results.extend(batch)
                    if batch and "tavily" not in providers_used:
                        providers_used.append("tavily")
                except Exception as exc:
                    errors.append(f"tavily:{category}:{exc}")

        if _provider_enabled(config, "gdelt", True):
            for category in [item for item in categories if item in {"news", "events"}]:
                try:
                    batch = await _gdelt_search(client, query, payload.timespan, payload.max_results, category)
                    results.extend(batch)
                    if batch and "gdelt" not in providers_used:
                        providers_used.append("gdelt")
                except Exception as exc:
                    errors.append(f"gdelt:{category}:{exc}")

        if "background" in categories and _provider_enabled(config, "wikipedia", True):
            try:
                batch = await _wikipedia_search(client, query, min(payload.max_results, 8))
                results.extend(batch)
                if batch and "wikipedia" not in providers_used:
                    providers_used.append("wikipedia")
            except Exception as exc:
                errors.append(f"wikipedia:{exc}")

    # Without a configured Tavily key, full/web mode still returns keyless news,
    # event, and background evidence. The provider-status endpoint makes the gap
    # explicit instead of silently pretending broad web search occurred.
    if "web" in categories and not tavily_key:
        errors.append("web: broad web search provider not configured; add Tavily to the R-drive research provider config or TAVILY_API_KEY")

    deduped = _dedupe_results(results, payload.max_results)
    persisted = _persist_results(contact_id, party_id, query, payload.business_scope, deduped)
    completed_at = _utc_now()
    status = "success" if persisted else ("partial" if providers_used else "error")

    with _connect() as conn:
        conn.execute(
            """
            UPDATE research_run
            SET providers=?, status=?, result_count=?, errors=?, completed_at=?
            WHERE run_id=?
            """,
            (
                json.dumps(providers_used),
                status,
                len(persisted),
                json.dumps(errors),
                completed_at,
                run_id,
            ),
        )
        conn.commit()

    return {
        "run_id": run_id,
        "contact_id": contact_id,
        "party_id": party_id,
        "query": query,
        "mode": payload.mode,
        "timespan": payload.timespan,
        "providers": providers_used,
        "items": persisted,
        "count": len(persisted),
        "errors": errors,
        "status": status,
        "verification_policy": "Public-source research is evidence only. It is not promoted to verified identity or relationship state automatically.",
    }
