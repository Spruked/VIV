"""Cali Personal Assistant API routes."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from cali_skg.core.cali_personal_skg import get_cali_skg
from cali_skg.api.unified_migration import run_unified_migration
from cali_skg.api.phase1c_import import ensure_phase1c_dirs, run_phase1c_import

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    redis = None

router = APIRouter(prefix="/cali", tags=["cali-personal"])
security = HTTPBearer(auto_error=False)
_REDIS_CLIENT: Any | None = None
_REDIS_ERROR: Optional[str] = None
_REDIS_LOCK = threading.Lock()


def _admin_token_value() -> str:
    return str(os.getenv("CALI_ADMIN_TOKEN") or os.getenv("ADMIN_ACCESS_TOKEN") or "").strip()


def verify_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials if credentials else ""
    allowed = _admin_token_value()
    if not allowed:
        raise HTTPException(status_code=503, detail="Admin token is not configured")
    if token != allowed:
        raise HTTPException(status_code=403, detail="Admin access required")
    return token


def _strict_mode() -> bool:
    return str(os.getenv("CALI_HYBRID_STRICT", "0")).strip() == "1"


def _doctrine_enforce() -> bool:
    return str(os.getenv("CALI_DOCTRINE_ENFORCE", "1")).strip() != "0"


def _doctrine_require_decision_envelope() -> bool:
    return str(os.getenv("CALI_DOCTRINE_REQUIRE_ENVELOPE", "0")).strip() == "1"


def _use_qwen_for_unknown() -> bool:
    return str(os.getenv("CALI_HYBRID_USE_QWEN", "1")).strip() == "1"


def _crm_db_path() -> str:
    cali = get_cali_skg()
    return str(cali.db_path)


def _extract_domain(email: Optional[str]) -> Optional[str]:
    email_value = str(email or "").strip().lower()
    if "@" not in email_value:
        return None
    domain = email_value.split("@")[-1].strip()
    common_providers = {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "icloud.com",
        "aol.com",
        "msn.com",
    }
    if not domain or domain in common_providers:
        return None
    return domain


_SOS_PORTALS = {
    "CA": "https://bizfileonline.sos.ca.gov/search/business",
    "DE": "https://icis.corp.delaware.gov/ecorp/entitysearch/namesearch.aspx",
    "FL": "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
    "NY": "https://apps.dos.ny.gov/publicInquiry/",
    "TX": "https://mycpa.cpa.state.tx.us/coa/",
}


def _normalized_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\b(?:mr|mrs|ms|dr|prof)\.?\s+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text


def _name_variants(primary: str, aliases: List[str]) -> List[str]:
    values = [_normalized_name(primary), *[_normalized_name(alias) for alias in aliases]]
    return list(dict.fromkeys(value for value in values if value))


def _state_code(address: str, jurisdiction: Optional[str]) -> str:
    candidate = str(jurisdiction or "").strip().upper()
    if candidate in _SOS_PORTALS:
        return candidate
    match = re.search(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b", str(address or "").upper())
    return match.group(1) if match else ""


def classify_external_link(platform: str, url: str, link_type: str) -> Dict[str, Any]:
    """Deterministic governance classification; generated links are never findings."""
    structured = {"sec_edgar", "patent_uspto", "trademark_uspto", "state_sos"}
    record_type = {
        "state_sos": "corporate", "sec_edgar": "regulatory", "court_records": "litigation",
        "patent_uspto": "ip", "trademark_uspto": "ip", "professional_license": "licensing",
    }.get(platform, "public_reference")
    if platform in structured and "google.com" not in url:
        return {"risk_level": "low", "record_type": record_type, "query_mode": "structured_registry", "confidence_score": 0.95, "requires_review": False}
    if "google.com" in url:
        return {"risk_level": "medium", "record_type": record_type, "query_mode": "google_proxy", "confidence_score": 0.70, "requires_review": platform in {"court_records", "associate_public"}}
    return {"risk_level": "medium", "record_type": record_type, "query_mode": "direct", "confidence_score": 0.50, "requires_review": True}


def _record_link_governance(conn: sqlite3.Connection, contact_id: str, platform: str, url: str, link_type: str) -> None:
    classification = classify_external_link(platform, url, link_type)
    now = datetime.utcnow().isoformat()
    node_key = hashlib.sha256(f"{contact_id}|{platform}|{url}".encode("utf-8")).hexdigest()
    conn.execute("""INSERT INTO contact_external_link_governance(node_key, contact_id, platform, url, risk_level, record_type, query_mode, confidence_score, requires_review, classifier_version, generated_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'viv-link-governor:v1', ?, ?) ON CONFLICT(node_key) DO UPDATE SET risk_level=excluded.risk_level, record_type=excluded.record_type, query_mode=excluded.query_mode, confidence_score=excluded.confidence_score, requires_review=excluded.requires_review, updated_at=excluded.updated_at""", (node_key, contact_id, platform, url, classification["risk_level"], classification["record_type"], classification["query_mode"], classification["confidence_score"], int(classification["requires_review"]), now, now))
    previous = conn.execute("SELECT row_hash FROM audit_event ORDER BY created_at DESC LIMIT 1").fetchone()
    prev_hash = str(previous[0]) if previous else ""
    state = json.dumps({"node_key": node_key, **classification}, sort_keys=True)
    row_hash = hashlib.sha256(f"{prev_hash}|{contact_id}|{state}|{now}".encode("utf-8")).hexdigest()
    conn.execute("INSERT INTO audit_event(audit_id, actor, action, target_ids, new_state, reason, prev_hash, row_hash, created_at) VALUES (?, 'viv_link_governor', 'classify_external_link', ?, ?, 'public_record_only', ?, ?, ?)", (f"audit:link:{node_key}:{row_hash[:12]}", json.dumps([contact_id]), state, prev_hash or None, row_hash, now))




def _kaygee_api_base() -> str:
    return str(os.getenv("KAYGEE_API_BASE", "http://127.0.0.1:8011")).strip().rstrip("/")


def _kaygee_voice_enabled() -> bool:
    return str(os.getenv("KAYGEE_VOICE_ENABLED", "1")).strip() == "1"


def _kaygee_voice() -> str:
    return str(os.getenv("KAYGEE_VOICE", "af_bella")).strip() or "af_bella"


def _local_kokoro_tts_url() -> str:
    return str(os.getenv("CALI_LOCAL_KOKORO_URL", "http://127.0.0.1:12000/api/kokoro/tts")).strip()


def _local_kokoro_speed() -> float:
    raw = str(os.getenv("CALI_KOKORO_SPEED", "1.0")).strip()
    try:
        return min(2.0, max(0.5, float(raw)))
    except ValueError:
        return 1.0


def _timeout_seconds() -> float:
    raw = str(os.getenv("SPRUKED_ORB_PROVIDER_TIMEOUT_MS", "18000")).strip()
    try:
        ms = max(2000, int(raw))
    except ValueError:
        ms = 18000
    return min(60.0, max(2.0, ms / 1000.0))


def _llm_max_tokens() -> int:
    raw = str(os.getenv("CALI_OLLAMA_MAX_TOKENS", "140")).strip()
    try:
        return min(800, max(50, int(raw)))
    except ValueError:
        return 140


def _llm_temperature() -> float:
    raw = str(os.getenv("CALI_OLLAMA_TEMPERATURE", "0.45")).strip()
    try:
        return min(1.2, max(0.0, float(raw)))
    except ValueError:
        return 0.45


def _llm_threads() -> int:
    raw = str(os.getenv("CALI_OLLAMA_THREADS", "")).strip()
    if raw:
        try:
            return min(64, max(1, int(raw)))
        except ValueError:
            pass
    cpu_count = os.cpu_count() or 4
    return min(16, max(2, cpu_count))


def _llm_device() -> Optional[str]:
    raw = str(os.getenv("CALI_OLLAMA_DEVICE", "")).strip().lower()
    if not raw:
        return None
    return raw


def _llm_num_gpu() -> Optional[int]:
    raw = str(os.getenv("CALI_OLLAMA_NUM_GPU", "")).strip()
    if not raw:
        if _llm_device() in {"cuda", "gpu", "nvidia"}:
            return 999
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _ollama_model_name() -> str:
    return str(os.getenv("CALI_OLLAMA_MODEL_NAME", "qwen3.5:4b")).strip()  # Qwen 3.5 4B model


def _substrate_redis_enabled() -> bool:
    return str(os.getenv("CALI_SUBSTRATE_REDIS_ENABLED", "1")).strip() != "0"


def _substrate_redis_url() -> str:
    direct = str(os.getenv("CALI_SUBSTRATE_REDIS_URL", "")).strip()
    if direct:
        return direct
    return str(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")).strip()


def _substrate_redis_patterns() -> List[str]:
    raw = str(
        os.getenv(
            "CALI_SUBSTRATE_REDIS_PATTERNS",
            "substrate:*,orb:*,mesh:*,cali:*,skg:*",
        )
    ).strip()
    patterns = [item.strip() for item in raw.split(",") if item.strip()]
    return patterns or ["substrate:*", "orb:*", "mesh:*", "cali:*", "skg:*"]


def _substrate_redis_key_limit() -> int:
    raw = str(os.getenv("CALI_SUBSTRATE_REDIS_KEY_LIMIT", "12")).strip()
    try:
        return min(64, max(1, int(raw)))
    except ValueError:
        return 12


def _spruk_email_api_base() -> str:
    direct_prime = str(os.getenv("PRIME_MAIL_API_URL", "")).strip()
    if direct_prime:
        return direct_prime.rstrip("/")
    return str(os.getenv("SPRUK_EMAIL_API_URL", "http://127.0.0.1:19000/api")).strip().rstrip("/")


def _crm_port() -> int:
    raw = str(os.getenv("PORT") or os.getenv("CALI_CRM_PORT") or "21000").strip()
    try:
        return max(1, min(65535, int(raw)))
    except ValueError:
        return 21000


def _crm_activity_exists_for_external_email(conn: sqlite3.Connection, contact_id: str, external_email_id: str) -> bool:
    ext = str(external_email_id or "").strip()
    if not ext:
        return False
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, metadata
        FROM crm_activities
        WHERE contact_id = ? AND activity_type = 'external_email_inbound'
        ORDER BY created_at DESC
        LIMIT 300
        """,
        (contact_id,),
    )
    for row in cur.fetchall():
        try:
            meta = json.loads(str(row["metadata"] or "{}"))
            if str(meta.get("external_email_id") or "").strip() == ext:
                return True
        except Exception:
            continue
    return False


def _spruk_email_enabled() -> bool:
    return str(os.getenv("SPRUK_EMAIL_ENABLED", "1")).strip() != "0"


def _spruk_email_timeout_seconds() -> float:
    raw = str(os.getenv("SPRUK_EMAIL_TIMEOUT_MS", "12000")).strip()
    try:
        ms = max(1000, int(raw))
    except ValueError:
        ms = 12000
    return min(45.0, max(1.0, ms / 1000.0))


async def _spruk_email_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    if not _spruk_email_enabled():
        raise HTTPException(status_code=503, detail="Prime Mail integration disabled")

    base = _spruk_email_api_base()
    if not base:
        raise HTTPException(status_code=503, detail="Prime Mail API URL is not configured")
    url = f"{base}/{str(path or '').lstrip('/')}"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds or _spruk_email_timeout_seconds()) as client:
            response = await client.request(method=method.upper(), url=url, params=params, json=json_body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Prime Mail request failed: {exc}") from exc

    payload: Dict[str, Any]
    try:
        decoded = response.json()
        if isinstance(decoded, dict):
            payload = decoded
        else:
            payload = {"data": decoded}
    except Exception:
        payload = {"raw": response.text}

    if response.status_code >= 400:
        detail = payload.get("detail") or payload.get("message") or payload.get("error") or response.text
        status_code = response.status_code if 400 <= response.status_code < 600 else 502
        raise HTTPException(status_code=status_code, detail=f"Prime Mail error: {detail}")

    return payload


def _is_substrate_query(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    return bool(
        re.search(
            r"\b(epistemic|substrate|geometry|geometric|skg|cognition stack|hybrid pipeline|provider_used|governance|doctrine)\b",
            lowered,
        )
    )


def _is_research_testing_query(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    return bool(re.search(r"\b(research|tested|testing|experiment|experiments|validation|metrics)\b", lowered))


def _redis_value_to_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return str(value)
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    text = str(value).strip()
    if not text:
        return ""
    if text[0] in "{[":
        try:
            return json.loads(text)
        except Exception:
            return text[:400]
    return text[:400]


def _get_redis_client() -> Any | None:
    global _REDIS_CLIENT, _REDIS_ERROR
    if not _substrate_redis_enabled():
        return None
    if redis is None:
        _REDIS_ERROR = "python redis package unavailable"
        return None
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT

    with _REDIS_LOCK:
        if _REDIS_CLIENT is not None:
            return _REDIS_CLIENT
        try:
            client = redis.Redis.from_url(  # type: ignore[attr-defined]
                _substrate_redis_url(),
                decode_responses=True,
                socket_connect_timeout=0.4,
                socket_timeout=0.4,
            )
            client.ping()
            _REDIS_CLIENT = client
            _REDIS_ERROR = None
            return _REDIS_CLIENT
        except Exception as exc:
            _REDIS_ERROR = str(exc)
            _REDIS_CLIENT = None
            return None


def _collect_substrate_redis_snapshot() -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "redis_enabled": _substrate_redis_enabled(),
        "redis_connected": False,
        "redis_url": _substrate_redis_url(),
        "key_patterns": _substrate_redis_patterns(),
        "sample_limit": _substrate_redis_key_limit(),
        "samples": [],
        "errors": [],
    }
    client = _get_redis_client()
    if client is None:
        if _REDIS_ERROR:
            snapshot["errors"].append(_REDIS_ERROR)
        return snapshot

    snapshot["redis_connected"] = True
    limit = _substrate_redis_key_limit()
    samples: List[Dict[str, Any]] = []

    for pattern in _substrate_redis_patterns():
        cursor = 0
        loops = 0
        while True:
            loops += 1
            if loops > 25 or len(samples) >= limit:
                break
            try:
                cursor, keys = client.scan(cursor=cursor, match=pattern, count=32)
            except Exception as exc:
                snapshot["errors"].append(f"scan:{pattern}:{exc}")
                break

            for key in keys:
                if len(samples) >= limit:
                    break
                try:
                    key_type = client.type(key)
                    value: Any
                    if key_type == "string":
                        value = _redis_value_to_json_safe(client.get(key))
                    elif key_type == "hash":
                        value = _redis_value_to_json_safe(client.hgetall(key))
                    elif key_type == "list":
                        value = _redis_value_to_json_safe(client.lrange(key, 0, 10))
                    elif key_type == "set":
                        value = _redis_value_to_json_safe(client.smembers(key))
                    elif key_type == "zset":
                        value = _redis_value_to_json_safe(client.zrange(key, 0, 10, withscores=True))
                    else:
                        value = None
                    samples.append({"key": str(key), "type": str(key_type), "value": value})
                except Exception as exc:
                    samples.append({"key": str(key), "error": str(exc)})

            if cursor == 0:
                break

    snapshot["samples"] = samples
    return snapshot


def _substrate_response(prompt: str, snapshot: Dict[str, Any]) -> str:
    research_mode = _is_research_testing_query(prompt)
    sample_keys = [str(item.get("key")) for item in snapshot.get("samples", []) if item.get("key")]
    key_preview = ", ".join(sample_keys[:5]) if sample_keys else "none sampled yet"
    redis_state = "connected" if snapshot.get("redis_connected") else "unavailable"

    lines: List[str] = [
        "Epistemic geometry here is the governance-routed cognition state-space over the substrate.",
        "Live path: /api/orb -> kaygee_hybrid -> /cali/orb/respond -> qwen-core + doctrine governance -> kokoro voice.",
        f"Substrate Redis state: {redis_state}; sampled keys: {key_preview}.",
    ]
    if research_mode:
        lines.extend(
            [
                "Currently being researched/tested: hybrid provider stability, doctrine DDR enforcement, Redis substrate signal fidelity, and voice path reliability (KayGee TTS with local Kokoro fallback).",
                "Validation surfaces: web insight artifact export, cognition metadata traces (provider_used/llm_core/doctrine_state), and ACP/voice fallback metrics in Orb_Assistant modules.",
            ]
        )
    else:
        lines.append(
            "Ask for \"current research and tests\" and I will return active experiment lanes and validation checkpoints."
        )
    return " ".join(lines)


def _normalize_companion_text(raw_text: str, prompt: str) -> str:
    prompt_lower = str(prompt or "").lower()
    text = str(raw_text or "").strip()
    if not text:
        return ""

    # Remove thinking process sections
    text = re.sub(r"Thinking Process:\s*\d+\.\s*\*\*.*?\*\*.*?(?=\n\n|\n[A-Z]|$)", "", text, flags=re.DOTALL | re.MULTILINE)
    text = re.sub(r"^\d+\.\s*\*\*.*?\*\*.*?(?=\n\n|\n\d+|\n[A-Z]|$)", "", text, flags=re.DOTALL | re.MULTILINE)

    # Remove diagnostic fields
    text = re.sub(r"\b(CONF|MIND)\s+\d+\.\d+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(MIND|CONF)\s*:.*$", "", text, flags=re.MULTILINE | re.IGNORECASE)

    # Remove "Heard" messages and other status indicators
    text = re.sub(r"\bHeard\b", "", text, flags=re.IGNORECASE)

    # Remove "TWICE CALI" and similar duplicates
    text = re.sub(r"TWICE\s+CALI", "", text, flags=re.IGNORECASE)

    # Clean up extra whitespace and empty lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = " ".join(lines).strip()

    # Remove offers frame text
    if re.search(r"offers the strongest frame for", text, flags=re.IGNORECASE):
        text = ""

    # Handle specific prompts
    if re.search(r"\b(what(?:'s| is)? your name|who are you)\b", prompt_lower):
        return "I'm Cali. I'm here with you."
    if re.search(r"\b(primary function|primary role|your role|your purpose|what do you do)\b", prompt_lower):
        return (
            "My primary function is to assist you as Cali with clear guidance, onboarding, "
            "mint support, and execution help."
        )
    if re.search(r"\b(can you hear me|do you hear me)\b", prompt_lower):
        return "I hear you clearly."
    if re.match(r"^(hi|hello|hey)\b", prompt_lower):
        return "Hey. I'm here."

    # Final cleanup
    text = re.sub(r"\s{2,}", " ", text).strip()
    if not text:
        return ""
    if text[-1] not in ".!?":
        text = f"{text}."
    return text


def _fast_path_response(prompt: str) -> str:
    prompt_lower = str(prompt or "").strip().lower()
    if re.search(r"\b(what(?:'s| is)? your name|who are you)\b", prompt_lower):
        return "I'm Cali. I'm here with you."
    if re.search(r"\b(primary function|primary role|your role|your purpose|what do you do)\b", prompt_lower):
        return (
            "My primary function is to assist you as Cali with clear guidance, onboarding, "
            "mint support, and execution help."
        )
    if re.search(r"\b(can you hear me|do you hear me)\b", prompt_lower):
        return "I hear you clearly."
    if re.match(r"^(hi|hello|hey)\b", prompt_lower):
        return "Hey. I'm here."
    return ""


def _generate_llm_response(prompt: str, context: Dict[str, Any], emotion: str) -> str:
    model = _ollama_model_name()
    system_prompt = (
        "You are Cali, a female executive assistant for Bryan on spruked.com. "
        "Follow KayGee governance style: concise, calm, practical, and safe. "
        "Never output diagnostic fields like MIND or CONF."
    )
    context_hint = ""
    if context:
        context_hint = f"\nContext: {context}"
    full_prompt = f"Emotion: {emotion}\nUser: {prompt}{context_hint}"
    options: Dict[str, Any] = {
        "num_predict": _llm_max_tokens(),
        "temperature": _llm_temperature(),
        "top_p": 0.9,
    }
    num_gpu = _llm_num_gpu()
    if num_gpu is not None:
        options["num_gpu"] = num_gpu

    try:
        response = httpx.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": model,
                "prompt": f"{system_prompt}\n\n{full_prompt}",
                "stream": False,
                "options": options,
                "keep_alive": str(os.getenv("CALI_OLLAMA_KEEP_ALIVE", "15m")).strip() or "15m",
            },
            timeout=60.0
        )
        response.raise_for_status()
        result = response.json()
        # For Qwen models, the response might be in 'thinking' field instead of 'response'
        response_text = result.get("response") or result.get("thinking", "")
        return str(response_text or "").strip()
    except Exception as exc:
        raise RuntimeError(f"Ollama API call failed: {exc}") from exc


async def _synthesize_voice(text: str) -> Dict[str, Optional[str]]:
    if not _kaygee_voice_enabled() or not text:
        return {"audio_url": None, "audio_engine": None}

    audio_url: Optional[str] = None
    audio_engine: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
            response = await client.post(
                f"{_kaygee_api_base()}/plugin/tts",
                json={"text": text, "voice": _kaygee_voice()},
            )
        if response.status_code == 200:
            data = response.json()
            raw_audio_url = str(data.get("audio_url") or "").strip()
            if raw_audio_url:
                if not raw_audio_url.startswith("http://") and not raw_audio_url.startswith("https://"):
                    raw_audio_url = f"{_kaygee_api_base()}{raw_audio_url if raw_audio_url.startswith('/') else '/' + raw_audio_url}"
                audio_url = raw_audio_url
            audio_engine = str(data.get("engine") or data.get("audio_engine") or "").strip() or None
    except Exception:
        audio_url = None
        audio_engine = None

    if not audio_url:
        try:
            async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
                fallback = await client.post(
                    f"{_kaygee_api_base()}/api/interact",
                    json={
                        "text": text,
                        "voice_enabled": True,
                        "voice_response": True,
                        "voice": _kaygee_voice(),
                    },
                )
            if fallback.status_code == 200:
                data = fallback.json()
                raw_audio_url = str(data.get("audio_url") or "").strip()
                if raw_audio_url:
                    if not raw_audio_url.startswith("http://") and not raw_audio_url.startswith("https://"):
                        raw_audio_url = f"{_kaygee_api_base()}{raw_audio_url if raw_audio_url.startswith('/') else '/' + raw_audio_url}"
                    audio_url = raw_audio_url
                audio_engine = str(data.get("audio_engine") or data.get("engine") or audio_engine or "").strip() or audio_engine
        except Exception:
            pass

    if not audio_url:
        local_tts_url = _local_kokoro_tts_url()
        if local_tts_url:
            try:
                async with httpx.AsyncClient(timeout=max(5.0, _timeout_seconds())) as client:
                    fallback = await client.post(
                        local_tts_url,
                        json={
                            "text": text,
                            "voice": _kaygee_voice(),
                        },
                    )
                    if fallback.status_code == 422:
                        fallback = await client.post(
                            local_tts_url,
                            json={"text": text},
                        )
                if fallback.status_code == 200:
                    data = fallback.json()
                    wav_b64 = str(data.get("audio_wav_base64") or "").strip()
                    raw_audio_url = str(data.get("audio_url") or "").strip()
                    if wav_b64:
                        audio_url = f"data:audio/wav;base64,{wav_b64}"
                    elif raw_audio_url:
                        if not raw_audio_url.startswith("http://") and not raw_audio_url.startswith("https://"):
                            raw_audio_url = (
                                f"{local_tts_url.rsplit('/', 3)[0]}{raw_audio_url if raw_audio_url.startswith('/') else '/' + raw_audio_url}"
                            )
                        audio_url = raw_audio_url
                    if audio_url:
                        audio_engine = "kokoro_local_api"
            except Exception:
                pass

    return {
        "audio_url": audio_url or None,
        "audio_engine": audio_engine,
    }


async def _query_kaygee_interact(prompt: str, context: Dict[str, Any], emotion: str) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
            response = await client.post(
                f"{_kaygee_api_base()}/api/interact",
                json={
                    "text": prompt,
                    "context": context,
                    "emotion": emotion,
                    "voice_enabled": _kaygee_voice_enabled(),
                    "voice_response": _kaygee_voice_enabled(),
                    "voice": _kaygee_voice(),
                },
            )
        data = response.json() if response.status_code == 200 else {}
    except Exception:
        return {"response": "", "audio_url": None, "audio_engine": None}

    if response.status_code != 200:
        return {"response": "", "audio_url": None, "audio_engine": None}

    audio_url = str(data.get("audio_url") or "").strip()
    if audio_url and not audio_url.startswith("http://") and not audio_url.startswith("https://"):
        audio_url = f"{_kaygee_api_base()}{audio_url if audio_url.startswith('/') else '/' + audio_url}"

    return {
        "response": str(data.get("response") or data.get("text") or "").strip(),
        "audio_url": audio_url or None,
        "audio_engine": str(data.get("audio_engine") or "").strip() or None,
    }


class ContactCreate(BaseModel):
    name: str
    contact_type: str = "personal"
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    priority: int = 0
    crm_stage: Optional[str] = None
    lead_source: Optional[str] = None
    owner: Optional[str] = None
    next_follow_up_at: Optional[str] = None


class CRMStageUpdate(BaseModel):
    contact_id: str
    stage: str
    next_follow_up_at: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None


class CRMActivityCreate(BaseModel):
    contact_id: str
    activity_type: str
    summary: str
    metadata: Optional[Dict[str, Any]] = None


class ExternalLinkSchema(BaseModel):
    id: int
    contact_id: str
    platform: str
    label: str
    url: str
    link_type: str
    verified_status: str
    source: str
    confidence_score: float
    last_checked_at: str
    created_at: str
    updated_at: str


class CreateExternalLink(BaseModel):
    platform: str
    label: str
    url: str
    link_type: str = "direct_profile"
    verified_status: str = "manual"
    source: str = "manual_input"


class UpdateExternalLink(BaseModel):
    label: Optional[str] = None
    url: Optional[str] = None
    verified_status: Optional[str] = None


class GenerateExternalLinksRequest(BaseModel):
    aliases: List[str] = []
    jurisdiction: Optional[str] = None
    include_courts: bool = True
    include_ip: bool = True


class DossierExpandRequest(BaseModel):
    aliases: List[str] = Field(default_factory=list)
    extra_phones: List[str] = Field(default_factory=list)
    extra_addresses: List[str] = Field(default_factory=list)
    include_associates: bool = True
    include_images: bool = True
    jurisdiction: Optional[str] = None


class CRMAppointmentCreate(BaseModel):
    contact_id: str
    title: str
    start_time: str
    end_time: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class EmailConnectorCreate(BaseModel):
    provider: str = "imap_smtp"
    email: str
    imap_host: Optional[str] = None
    imap_port: int = 993
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    calendar_provider: str = "local"
    notes: Optional[str] = None


class EmailPollRequest(BaseModel):
    mailbox: str = "INBOX"
    limit: int = 25
    since_hours: int = 72
    unseen_only: bool = True


class ExternalEmailSendRequest(BaseModel):
    to: str
    subject: str
    text: Optional[str] = None
    html: Optional[str] = None
    from_name: Optional[str] = "Cali CRM"


class ExternalEmailSyncRequest(BaseModel):
    folder: str = "inbox"
    limit: int = 50
    offset: int = 0
    search: Optional[str] = None
    unread_only: bool = False


class FinancialAccountCreate(BaseModel):
    institution: str
    account_type: str
    account_number: str
    balance: float = 0.0
    alert_threshold: Optional[float] = None
    notes: Optional[str] = None


class EventCreate(BaseModel):
    title: str
    event_type: str = "meeting"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[List[str]] = None
    notes: Optional[str] = None
    attendee_notes: Optional[Dict[str, str]] = None
    priority: int = 0


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: int = 1
    category: str = "personal"


class VerificationCall(BaseModel):
    caller_number: str
    caller_name: Optional[str] = None
    claimed_identity: Optional[str] = None


class CaliQuery(BaseModel):
    query: str
    current_path: Optional[str] = "/admin"
    context: Optional[Dict[str, Any]] = None


class OrbRespondRequest(BaseModel):
    prompt: str
    context: Optional[Dict[str, Any]] = None
    emotion: Optional[str] = "thoughtful_warm"
    session_id: Optional[str] = None


@router.get("/status")
def cali_status(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return {"status": "active", "identity": cali.identity, "stats": cali.get_stats()}


@router.post("/admin/migrate-unified")
def migrate_unified_schema(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    return run_unified_migration(_crm_db_path())


@router.post("/admin/bootstrap-substrate")
def bootstrap_substrate(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    paths = ensure_phase1c_dirs(_crm_db_path())
    return {
        "status": "success",
        "root": str(paths.root),
        "db_path": str(paths.db_path),
        "folders": {
            "backups": str(paths.backups),
            "migrations": str(paths.migrations),
            "imports_pending": str(paths.imports_pending),
            "imports_processed": str(paths.imports_processed),
            "imports_rejected": str(paths.imports_rejected),
            "imports_reports": str(paths.imports_reports),
            "contacts_attachments": str(paths.contacts_attachments),
            "contacts_exports": str(paths.contacts_exports),
            "audit_import_logs": str(paths.audit_import_logs),
            "audit_merge_logs": str(paths.audit_merge_logs),
            "indexes_search": str(paths.indexes_search),
        },
    }


async def _run_import(
    file: UploadFile,
    source_type: str,
    default_contact_type: str,
    default_stage: str,
    owner: Optional[str],
) -> Dict[str, Any]:
    filename = str(file.filename or "").lower()
    if not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    payload = await file.read()
    return run_phase1c_import(
        db_path=_crm_db_path(),
        original_filename=str(file.filename or "import.csv"),
        csv_bytes=payload,
        explicit_source=source_type,
        default_contact_type=default_contact_type,
        default_stage=default_stage,
        owner=owner,
    )


@router.post("/contacts/import/csv/gmail")
async def import_contacts_csv_gmail(
    file: UploadFile = File(...),
    default_contact_type: str = "business",
    default_stage: str = "prospect",
    owner: Optional[str] = None,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    return await _run_import(file, "gmail_csv", default_contact_type, default_stage, owner)


@router.post("/contacts/import/csv/outlook")
async def import_contacts_csv_outlook(
    file: UploadFile = File(...),
    default_contact_type: str = "business",
    default_stage: str = "prospect",
    owner: Optional[str] = None,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    return await _run_import(file, "outlook_csv", default_contact_type, default_stage, owner)


@router.post("/contacts/import/csv/generic")
async def import_contacts_csv_generic(
    file: UploadFile = File(...),
    default_contact_type: str = "business",
    default_stage: str = "prospect",
    owner: Optional[str] = None,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    return await _run_import(file, "generic_csv", default_contact_type, default_stage, owner)


@router.post("/contacts")
def add_contact(payload: ContactCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.add_contact(
        name=payload.name,
        contact_type=payload.contact_type,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        notes=payload.notes,
        priority=payload.priority,
        crm_stage=payload.crm_stage,
        lead_source=payload.lead_source,
        owner=payload.owner,
        next_follow_up_at=payload.next_follow_up_at,
    )


@router.get("/contacts")
def search_contacts(
    query: Optional[str] = None,
    contact_type: Optional[str] = None,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    cali = get_cali_skg()
    contacts = cali.search_contacts(query=query, contact_type=contact_type)
    return {"contacts": contacts, "count": len(contacts)}


@router.get("/contacts/financial")
def get_financial_contacts(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    contacts = cali.get_financial_contacts()
    return {"contacts": contacts, "count": len(contacts)}


@router.get("/contacts/{contact_id}/external-links", response_model=List[ExternalLinkSchema])
def get_external_links(contact_id: str, _: str = Depends(verify_admin)) -> List[ExternalLinkSchema]:
    with sqlite3.connect(_crm_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM contact_external_links WHERE contact_id = ? ORDER BY created_at DESC",
            (contact_id,),
        )
        rows = [dict(row) for row in cur.fetchall()]
    return rows


@router.post("/contacts/{contact_id}/external-links", response_model=ExternalLinkSchema, status_code=201)
def add_external_link(contact_id: str, payload: CreateExternalLink, _: str = Depends(verify_admin)) -> ExternalLinkSchema:
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(_crm_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id FROM contacts WHERE id = ? OR hash_id = ?", (contact_id, contact_id))
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Target contact dossier not found")
        resolved_id = str(contact["id"])
        try:
            cur.execute(
                """
                INSERT INTO contact_external_links (
                    contact_id, platform, label, url, link_type, verified_status, source,
                    confidence_score, last_checked_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)
                """,
                (
                    resolved_id,
                    payload.platform,
                    payload.label,
                    payload.url,
                    payload.link_type,
                    payload.verified_status,
                    payload.source,
                    now,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=400, detail="This specific link entity already exists for this contact") from exc
        conn.commit()
        link_id = int(cur.lastrowid)
        cur.execute("SELECT * FROM contact_external_links WHERE id = ?", (link_id,))
        created = cur.fetchone()
        if not created:
            raise HTTPException(status_code=500, detail="Failed to retrieve created external link")
        return dict(created)


@router.post("/contacts/{contact_id}/external-links/generate")
def generate_external_links(
    contact_id: str,
    payload: Optional[GenerateExternalLinksRequest] = None,
    dry_run: bool = False,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    payload = payload or GenerateExternalLinksRequest()
    run_unified_migration(_crm_db_path())
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(_crm_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, email, address, company_role, organization_id, alias_names FROM contacts WHERE id = ? OR hash_id = ?",
            (contact_id, contact_id),
        )
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Target contact dossier not found")

        resolved_id = str(contact["id"])
        name = _normalized_name(str(contact["name"] or ""))
        email = str(contact["email"] or "").strip()
        address = str(contact["address"] or "").strip()
        organization = str(contact["organization_id"] or contact["company_role"] or "").strip()

        aliases = list(payload.aliases)
        try:
            aliases.extend(json.loads(str(contact["alias_names"] or "[]")))
        except (TypeError, json.JSONDecodeError):
            pass
        names = _name_variants(name, [str(alias) for alias in aliases])
        if not names:
            raise HTTPException(status_code=400, detail="Cannot generate deterministic paths without a contact name token")

        encoded_name = quote_plus(name)
        generated: List[tuple[str, str, str, str]] = [
            ("google_search", "Google Search", f"https://www.google.com/search?q={encoded_name}", "search_fallback"),
            ("facebook", "Facebook Search", f"https://www.facebook.com/search/top/?q={encoded_name}", "search_fallback"),
            ("linkedin", "LinkedIn Search", f"https://www.linkedin.com/search/results/all/?keywords={encoded_name}", "search_fallback"),
            ("github", "GitHub Search", f"https://github.com/search?q={encoded_name}&type=users", "search_fallback"),
        ]

        if address:
            encoded_address = quote_plus(address)
            generated.append(
                (
                    "google_maps",
                    "Google Maps",
                    f"https://www.google.com/maps/search/?api=1&query={encoded_name}+{encoded_address}",
                    "search_fallback",
                )
            )
        else:
            generated.append(
                ("google_maps", "Google Maps Search", f"https://www.google.com/maps/search/?api=1&query={encoded_name}", "search_fallback")
            )

        domain = _extract_domain(email)
        if domain:
            generated.append(("domain_lookup", "Domain Intelligence", f"https://who.is/whois/{domain}", "direct_profile"))
            generated.append(("company_website", "Corporate Domain", f"https://{domain}", "direct_profile"))

        # These are public-record search paths, not assertions about the subject.
        # The unique contact/platform/url constraint preserves deterministic
        # deduplication across repeated daily dossier runs.
        legal_subject = organization or name
        encoded_legal_subject = quote_plus(f'"{legal_subject}"')
        encoded_exact_name = quote_plus(f'"{name}"')
        encoded_location = quote_plus(address or "United States")
        generated.extend(
            [
                (
                    "state_sos",
                    f"Secretary of State Search: {legal_subject}",
                    f"https://www.google.com/search?q=site%3A.gov+%22secretary+of+state%22+{encoded_legal_subject}",
                    "corporate_registry",
                ),
                (
                    "sec_edgar",
                    f"SEC EDGAR Search: {legal_subject}",
                    f"https://www.sec.gov/edgar/search/#/q={encoded_legal_subject}",
                    "regulatory_filing",
                ),
                (
                    "court_records",
                    f"Public Docket Search: {name}",
                    f"https://www.google.com/search?q={encoded_exact_name}+%28court+OR+docket+OR+litigation+OR+plaintiff+OR+defendant%29",
                    "legal_docket",
                ),
                (
                    "patent_uspto",
                    f"Patent Search: {name}",
                    f"https://patents.google.com/?inventor={quote_plus(name)}",
                    "intellectual_property",
                ),
                (
                    "professional_license",
                    f"Professional License Search: {name}",
                    f"https://www.google.com/search?q={encoded_exact_name}+%28license+OR+board+OR+registry+OR+certification%29+{encoded_location}",
                    "licensing_check",
                ),
            ]
        )

        state = _state_code(address, payload.jurisdiction)
        if state in _SOS_PORTALS:
            generated.append(("state_sos", f"{state} Secretary of State: {legal_subject}", _SOS_PORTALS[state], "corporate_registry"))
        for alias in names[1:]:
            encoded_alias = quote_plus(f'"{alias}"')
            generated.append(("google_search", f"Google Search: {alias}", f"https://www.google.com/search?q={encoded_alias}", "alias_search"))
            if payload.include_courts:
                generated.append(("court_records", f"Public Docket Search: {alias}", f"https://www.google.com/search?q={encoded_alias}+%28court+OR+docket+OR+litigation%29", "legal_docket"))

        if not payload.include_courts:
            generated = [node for node in generated if node[0] != "court_records"]
        if not payload.include_ip:
            generated = [node for node in generated if node[0] != "patent_uspto"]
        if dry_run:
            return {"status": "dry_run", "contact_id": resolved_id, "generated_links": len(generated), "nodes": [dict(platform=p, label=l, url=u, link_type=t) for p, l, u, t in generated]}

        inserted_count = 0
        for platform, label, url, link_type in generated:
            cur.execute(
                """
                INSERT OR IGNORE INTO contact_external_links (
                    contact_id, platform, label, url, link_type, verified_status, source,
                    confidence_score, last_checked_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'generated_search', 'deterministic_generator:v2', 0.3, ?, ?, ?)
                """,
                (resolved_id, platform, label, url, link_type, now, now, now),
            )
            if cur.rowcount > 0:
                inserted_count += 1
            _record_link_governance(conn, resolved_id, platform, url, link_type)

        conn.commit()
    return {"status": "success", "generated_links": len(generated), "new_links_written": inserted_count}


@router.post("/contacts/{contact_id}/dossier/expand")
def expand_dossier(
    contact_id: str,
    payload: Optional[DossierExpandRequest] = None,
    dry_run: bool = False,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    """Add deterministic public-record paths from the current VIV dossier.

    Associates come only from accepted/verified local relationship edges. Search
    paths are references, not claims or fetched public-record content.
    """
    payload = payload or DossierExpandRequest()
    run_unified_migration(_crm_db_path())
    base = generate_external_links(
        contact_id,
        GenerateExternalLinksRequest(aliases=payload.aliases, jurisdiction=payload.jurisdiction),
        dry_run,
        "owner",
    )
    if dry_run:
        return {**base, "expansion": "dry_run"}

    now = datetime.utcnow().isoformat()
    inserted = int(base.get("new_links_written") or 0)
    generated = int(base.get("generated_links") or 0)
    with sqlite3.connect(_crm_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        contact = cur.execute("SELECT id, name, phone, address FROM contacts WHERE id=? OR hash_id=?", (contact_id, contact_id)).fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Target contact dossier not found")
        resolved_id, name = str(contact["id"]), _normalized_name(str(contact["name"] or ""))
        phones = list(dict.fromkeys([str(contact["phone"] or ""), *payload.extra_phones]))
        addresses = list(dict.fromkeys([str(contact["address"] or ""), *payload.extra_addresses]))
        extra: List[tuple[str, str, str, str]] = []
        for phone in (value for value in phones if value.strip()):
            digits = "".join(ch for ch in phone if ch.isdigit())
            if digits:
                extra.append(("phone_public", f"Public directory search: {phone}", f"https://www.google.com/search?q={quote_plus(phone)}+%28%22reverse+lookup%22+OR+%22public+records%22%29", "phone_directory"))
        for address in (value for value in addresses if value.strip()):
            extra.append(("property_records", f"Property / assessor search: {address}", f"https://www.google.com/search?q={quote_plus('"' + address + '"')}+%28assessor+OR+property+OR+deed+OR+recorder%29+site%3A.gov", "property_record"))
        if payload.include_images and name:
            extra.append(("public_images", f"Public image search: {name}", f"https://www.google.com/search?tbm=isch&q={quote_plus('"' + name + '"')}+%28site%3A.gov+OR+site%3Asec.gov+OR+site%3Auspto.gov%29", "public_image"))
        if payload.include_associates:
            party_id = f"legacy-contact:{resolved_id}"
            rows = cur.execute(
                """SELECT c.name, e.predicate FROM relationship_edge e
                   JOIN contacts c ON ('legacy-contact:' || c.id)=CASE WHEN e.from_party=? THEN e.to_party ELSE e.from_party END
                   WHERE (e.from_party=? OR e.to_party=?) AND e.state IN ('asserted','verified') AND e.valid_to IS NULL""",
                (party_id, party_id, party_id),
            ).fetchall()
            for row in rows:
                associate, relation = _normalized_name(str(row["name"] or "")), str(row["predicate"] or "associate")
                if associate:
                    extra.append(("associate_public", f"Associate public-record search: {associate} ({relation})", f"https://www.google.com/search?q={quote_plus('"' + associate + '"')}+%28court+OR+docket+OR+officer+OR+director%29+site%3A.gov", "associate_public_record"))
        for platform, label, url, link_type in extra:
            generated += 1
            cur.execute("""INSERT OR IGNORE INTO contact_external_links (contact_id, platform, label, url, link_type, verified_status, source, confidence_score, last_checked_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'generated_search', 'dossier_expander:v1', 0.3, ?, ?, ?)""", (resolved_id, platform, label, url, link_type, now, now, now))
            inserted += max(0, cur.rowcount)
            _record_link_governance(conn, resolved_id, platform, url, link_type)
        conn.commit()
    return {"status": "success", "contact_id": resolved_id, "generated_links": generated, "new_links_written": inserted, "deduplicated": generated - inserted, "public_images_referenced": sum(1 for item in extra if item[3] == "public_image")}


@router.patch("/contacts/{contact_id}/external-links/{link_id}", response_model=ExternalLinkSchema)
def update_external_link(
    contact_id: str,
    link_id: int,
    payload: UpdateExternalLink,
    _: str = Depends(verify_admin),
) -> ExternalLinkSchema:
    update_data: Dict[str, Any] = {}
    if payload.label is not None:
        update_data["label"] = payload.label
    if payload.url is not None:
        update_data["url"] = payload.url
    if payload.verified_status is not None:
        update_data["verified_status"] = payload.verified_status
    if not update_data:
        raise HTTPException(status_code=400, detail="Empty payload parameters specified")
    update_data["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{key} = ?" for key in update_data.keys())

    with sqlite3.connect(_crm_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id FROM contacts WHERE id = ? OR hash_id = ? LIMIT 1", (contact_id, contact_id))
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Target contact dossier not found")
        resolved_id = str(contact["id"])
        values = list(update_data.values()) + [link_id, resolved_id]
        cur.execute(f"UPDATE contact_external_links SET {set_clause} WHERE id = ? AND contact_id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Target link mapping entity not found")
        cur.execute("SELECT * FROM contact_external_links WHERE id = ?", (link_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Target link mapping entity not found")
    return dict(row)


@router.delete("/contacts/{contact_id}/external-links/{link_id}")
def delete_external_link(contact_id: str, link_id: int, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    with sqlite3.connect(_crm_db_path()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM contacts WHERE id = ? OR hash_id = ? LIMIT 1", (contact_id, contact_id))
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Target contact dossier not found")
        resolved_id = str(contact["id"])
        cur.execute("DELETE FROM contact_external_links WHERE id = ? AND contact_id = ?", (link_id, resolved_id))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Target link mapping entity not found")
    return {"status": "success", "message": f"Link node {link_id} decoupled from dossier."}


@router.post("/financial/accounts")
def add_financial_account(payload: FinancialAccountCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.add_financial_account(
        institution=payload.institution,
        account_type=payload.account_type,
        account_number=payload.account_number,
        balance=payload.balance,
        alert_threshold=payload.alert_threshold,
        notes=payload.notes,
    )


@router.get("/financial/summary")
def get_financial_summary(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.get_financial_summary()


@router.post("/calendar/events")
def add_event(payload: EventCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.add_event(
        title=payload.title,
        event_type=payload.event_type,
        start_time=payload.start_time,
        end_time=payload.end_time,
        location=payload.location,
        attendees=payload.attendees,
        notes=payload.notes,
        attendee_notes=payload.attendee_notes,
        priority=payload.priority,
    )


@router.get("/calendar/upcoming")
def get_upcoming_events(days: int = 7, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return {"events": cali.get_upcoming_events(days=days)}


@router.get("/calendar/today")
def get_today_briefing(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.get_today_briefing()

@router.post("/verification/call")
def log_verification_call(payload: VerificationCall, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.log_verification_call(
        caller_number=payload.caller_number,
        caller_name=payload.caller_name,
        claimed_identity=payload.claimed_identity,
    )


@router.get("/verification/queue")
def get_verification_queue(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return {"calls": cali.get_verification_queue()}


@router.post("/tasks")
def add_task(payload: TaskCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.add_task(
        title=payload.title,
        description=payload.description,
        due_date=payload.due_date,
        priority=payload.priority,
        category=payload.category,
    )


@router.get("/tasks")
def get_tasks(category: Optional[str] = None, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return {"tasks": cali.get_active_tasks(category=category)}


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.complete_task(task_id)


@router.get("/crm/pipeline")
def crm_pipeline(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.get_crm_pipeline()


@router.patch("/crm/leads/stage")
def crm_update_stage(payload: CRMStageUpdate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    result = cali.update_contact_stage(
        contact_id=payload.contact_id,
        stage=payload.stage,
        next_follow_up_at=payload.next_follow_up_at,
        owner=payload.owner,
        notes=payload.notes,
    )
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Lead not found."))
    return result


@router.post("/crm/activities")
def crm_log_activity(payload: CRMActivityCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.log_crm_activity(
        contact_id=payload.contact_id,
        activity_type=payload.activity_type,
        summary=payload.summary,
        metadata=payload.metadata,
    )


@router.get("/crm/activities/{contact_id}")
def crm_contact_activities(contact_id: str, limit: int = 40, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    activities = cali.get_contact_activities(contact_id=contact_id, limit=limit)
    return {"activities": activities, "count": len(activities)}


@router.post("/crm/appointments")
def crm_schedule_appointment(payload: CRMAppointmentCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    result = cali.schedule_contact_appointment(
        contact_id=payload.contact_id,
        title=payload.title,
        start_time=payload.start_time,
        end_time=payload.end_time,
        location=payload.location,
        notes=payload.notes,
    )
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Contact not found."))
    return result


@router.post("/crm/email/connect")
def crm_email_connect(payload: EmailConnectorCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.configure_email_connector(
        provider=payload.provider,
        email=payload.email,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        calendar_provider=payload.calendar_provider,
        notes=payload.notes,
    )


@router.get("/crm/email/status")
def crm_email_status(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.get_email_connector_status()


@router.post("/crm/email/poll")
def crm_email_poll(payload: EmailPollRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    result = cali.poll_inbound_mailbox(
        mailbox=payload.mailbox,
        limit=payload.limit,
        since_hours=payload.since_hours,
        unseen_only=payload.unseen_only,
    )
    if not result.get("success"):
        status = str(result.get("status") or "error")
        if status in {"not_configured", "connector_incomplete", "password_missing"}:
            raise HTTPException(status_code=400, detail=result.get("message", status))
        raise HTTPException(status_code=502, detail=result.get("message", status))
    return result


@router.get("/crm/external-email/health")
async def crm_external_email_health(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    health = await _spruk_email_request("GET", "health")
    return {
        "integration": "prime_mail",
        "api_base": _spruk_email_api_base(),
        "enabled": _spruk_email_enabled(),
        "health": health,
    }


@router.get("/crm/external-email/stats")
async def crm_external_email_stats(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    stats = await _spruk_email_request("GET", "stats")
    return {
        "integration": "prime_mail",
        "stats": stats,
    }


@router.get("/crm/external-email/messages")
async def crm_external_email_messages(
    folder: str = "inbox",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    unread_only: bool = False,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "folder": folder,
        "limit": min(200, max(1, int(limit or 50))),
        "offset": max(0, int(offset or 0)),
        "unread_only": bool(unread_only),
    }
    if search:
        params["search"] = search
    data = await _spruk_email_request("GET", "emails", params=params)
    return {
        "integration": "prime_mail",
        **data,
    }


@router.get("/crm/external-email/messages/{email_id}")
async def crm_external_email_message(email_id: int, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    data = await _spruk_email_request("GET", f"emails/{int(email_id)}")
    return {
        "integration": "prime_mail",
        **data,
    }


@router.patch("/crm/external-email/messages/{email_id}")
async def crm_external_email_message_update(
    email_id: int,
    payload: Dict[str, Any],
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    allowed = {"read", "starred", "archived", "folder"}
    updates = {k: v for k, v in dict(payload or {}).items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid update fields supplied")
    data = await _spruk_email_request("PATCH", f"emails/{int(email_id)}", json_body=updates)
    return {
        "integration": "prime_mail",
        **data,
    }


@router.delete("/crm/external-email/messages/{email_id}")
async def crm_external_email_message_delete(email_id: int, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    data = await _spruk_email_request("DELETE", f"emails/{int(email_id)}")
    return {
        "integration": "prime_mail",
        **data,
    }


@router.post("/crm/external-email/send")
async def crm_external_email_send(payload: ExternalEmailSendRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    req = {
        "to": payload.to,
        "subject": payload.subject,
        "text": payload.text,
        "html": payload.html,
        "from_name": payload.from_name,
    }
    data = await _spruk_email_request("POST", "emails/send", json_body=req)
    return {
        "integration": "prime_mail",
        **data,
    }


@router.post("/crm/external-email/sync")
async def crm_external_email_sync(payload: ExternalEmailSyncRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    email_data = await _spruk_email_request(
        "GET",
        "emails",
        params={
            "folder": payload.folder,
            "limit": min(200, max(1, int(payload.limit or 50))),
            "offset": max(0, int(payload.offset or 0)),
            "search": payload.search,
            "unread_only": bool(payload.unread_only),
        },
    )
    emails = list(email_data.get("emails") or [])

    processed = 0
    linked = 0
    created_contacts = 0
    skipped = 0
    errors: List[str] = []

    find_contact = getattr(cali, "_find_contact_by_email", None)

    with sqlite3.connect(_crm_db_path()) as _sync_conn:
        _sync_conn.row_factory = sqlite3.Row
        for item in emails:
            processed += 1
            sender = str(item.get("sender") or "").strip().lower()
            subject = str(item.get("subject") or "(no subject)").strip()[:320]
            external_id = str(item.get("message_id") or item.get("id") or "").strip()
            if not sender:
                skipped += 1
                continue

            contact: Dict[str, Any] = {}
            if callable(find_contact):
                try:
                    contact = dict(find_contact(sender) or {})
                except Exception:
                    contact = {}

            contact_id = str(contact.get("id") or "").strip()
            if not contact_id:
                created = cali.add_contact(
                    name=f"Email Lead: {sender.split('@')[0]}",
                    contact_type="marketing",
                    email=sender,
                    notes="Imported via Prime Mail CRM sync.",
                    priority=1,
                    crm_stage="prospect",
                    lead_source="prime_mail_sync",
                    owner="bryan@spruked.com",
                )
                contact_id = str(created.get("contact_id") or "").strip()
                if contact_id:
                    created_contacts += 1

            if not contact_id:
                skipped += 1
                errors.append(f"contact_missing:{sender}")
                continue

            try:
                if _crm_activity_exists_for_external_email(_sync_conn, contact_id, external_id):
                    skipped += 1
                    continue
                cali.log_crm_activity(
                    contact_id,
                    "external_email_inbound",
                    f"Prime Mail inbound: {subject}",
                    metadata={
                        "external_email_id": external_id,
                        "sender": sender,
                        "recipient": item.get("recipient"),
                        "date": item.get("date"),
                        "folder": item.get("folder"),
                        "source": "prime_mail",
                    },
                )
                linked += 1
            except Exception as exc:
                errors.append(f"activity_failed:{contact_id}:{exc}")

    return {
        "integration": "prime_mail",
        "processed": processed,
        "linked": linked,
        "created_contacts": created_contacts,
        "skipped": skipped,
        "errors": errors,
    }


@router.get("/crm/unified/status")
async def crm_unified_status(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    pipeline = cali.get_crm_pipeline()
    connector = cali.get_email_connector_status()
    external_enabled = _spruk_email_enabled()
    try:
        external_health = await _spruk_email_request("GET", "health", timeout_seconds=1.5)
    except HTTPException as exc:
        external_health = {"status": "error", "detail": exc.detail}
    external_health_status = str(external_health.get("status") or "").lower()
    external_status = "online" if external_enabled and external_health_status == "ok" else "degraded" if external_enabled else "disabled"

    return {
        "crm_pipeline": pipeline,
        "crm_email_connector": connector,
        "external_email": {
            "enabled": external_enabled,
            "status": external_status,
            "api_base": _spruk_email_api_base(),
            "health": external_health,
            "detail": external_health.get("detail") if isinstance(external_health, dict) else None,
        },
    }


@router.post("/query")
def cali_query(payload: CaliQuery, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    context: Dict[str, Any] = {"current_path": payload.current_path or "/admin"}
    if payload.context:
        context.update(payload.context)
    return cali.process_query(query=payload.query, context=context)


@router.post("/orb/respond")
async def cali_orb_respond(payload: OrbRespondRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    prompt = str(payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    context = dict(payload.context or {})
    if _is_substrate_query(prompt):
        substrate_snapshot = _collect_substrate_redis_snapshot()
        substrate_text = _substrate_response(prompt, substrate_snapshot)
        voice_payload = await _synthesize_voice(substrate_text)
        return {
            "status": "success",
            "response": substrate_text,
            "response_text": substrate_text,
            "data": {"substrate_snapshot": substrate_snapshot},
            "intent": {"type": "substrate_explain"},
            "audio_url": voice_payload.get("audio_url"),
            "audio_engine": voice_payload.get("audio_engine"),
            "metadata": {
                "provider": "kaygee_hybrid",
                "cognition": "qwen-core + cali-skg-articulation",
                "llm_core": "substrate-redis-brief",
                "leading_mind": "cali",
                "confidence": 0.9,
                "truth_likelihood": 0.9,
            },
        }

    quick_response = _fast_path_response(prompt)
    if quick_response:
        voice_payload = await _synthesize_voice(quick_response)
        return {
            "status": "success",
            "response": quick_response,
            "response_text": quick_response,
            "data": None,
            "intent": {"type": "fast_path"},
            "audio_url": voice_payload.get("audio_url"),
            "audio_engine": voice_payload.get("audio_engine"),
            "metadata": {
                "provider": "kaygee_hybrid",
                "cognition": "qwen-core + cali-skg-articulation",
                "llm_core": "fast-path",
                "leading_mind": "cali",
                "confidence": 0.96,
                "truth_likelihood": 0.96,
            },
        }

    cali = get_cali_skg()
    current_path = str(context.get("current_path") or context.get("currentPath") or "/")
    skg_context: Dict[str, Any] = {"current_path": current_path}
    skg_context.update(context)
    skg_result = cali.process_query(query=prompt, context=skg_context)
    intent_type = str((skg_result.get("intent") or {}).get("type") or "")

    llm_core = "cali-skg-action"
    response_text = str(skg_result.get("response") or "").strip()
    audio_url: Optional[str] = None
    audio_engine: Optional[str] = None

    if intent_type in {"unknown", ""} or not response_text:
        if _use_qwen_for_unknown():
            try:
                llm_core = f"ollama:{_ollama_model_name()}"
                response_text = _generate_llm_response(prompt, context=context, emotion=str(payload.emotion or "thoughtful_warm"))
            except Exception as exc:
                if _strict_mode():
                    raise HTTPException(status_code=503, detail=f"Hybrid cognition unavailable: {exc}") from exc
                llm_core = "kaygee-fallback"

        if not response_text:
            kaygee_response = await _query_kaygee_interact(
                prompt=prompt,
                context=context,
                emotion=str(payload.emotion or "thoughtful_warm"),
            )
            if kaygee_response.get("response"):
                response_text = str(kaygee_response["response"])
                audio_url = kaygee_response.get("audio_url")
                audio_engine = kaygee_response.get("audio_engine")
                llm_core = "kaygee-fallback"

    governed = _normalize_companion_text(response_text, prompt)
    if not governed:
        governed = "I'm here with you. Tell me what you need next."

    voice_payload = {"audio_url": audio_url, "audio_engine": audio_engine}
    if not voice_payload.get("audio_url"):
        voice_payload = await _synthesize_voice(governed)

    return {
        "status": "success",
        "response": governed,
        "response_text": governed,
        "data": skg_result.get("data"),
        "intent": skg_result.get("intent"),
        "audio_url": voice_payload.get("audio_url"),
        "audio_engine": voice_payload.get("audio_engine"),
        "metadata": {
            "provider": "kaygee_hybrid",
            "cognition": "qwen-core + cali-skg-articulation",
            "llm_core": llm_core,
            "leading_mind": "cali",
            "confidence": 0.86 if llm_core != "fallback" else 0.65,
            "truth_likelihood": 0.86 if llm_core != "fallback" else 0.65,
        },
    }


@router.get("/site/context")
def site_context(current_path: str = "/", _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    return cali.get_site_context(current_path)


@router.post("/maintenance/prune")
def prune(retention_days: int = 90, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    cali = get_cali_skg()
    cali.prune_knowledge_graph(retention_days=retention_days)
    return {"success": True, "message": "Knowledge graph pruned."}


app = FastAPI(title="Cali Personal Assistant API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "cali-personal-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=_crm_port())
