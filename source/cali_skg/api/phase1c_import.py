from __future__ import annotations

import csv
import io
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cali_skg.api.unified_migration import run_unified_migration


@dataclass
class ImportPaths:
    root: Path
    db_path: Path
    backups: Path
    migrations: Path
    imports_pending: Path
    imports_processed: Path
    imports_rejected: Path
    imports_reports: Path
    contacts_attachments: Path
    contacts_exports: Path
    audit_import_logs: Path
    audit_merge_logs: Path
    indexes_search: Path


def now_utc() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")


def _canonical_root_from_db(db_path: str) -> Path:
    return Path(db_path).parent.parent


def ensure_phase1c_dirs(db_path: str) -> ImportPaths:
    root = _canonical_root_from_db(db_path)
    memory = root / "memory"
    paths = ImportPaths(
        root=root,
        db_path=Path(db_path),
        backups=memory / "backups",
        migrations=memory / "migrations",
        imports_pending=root / "imports" / "pending",
        imports_processed=root / "imports" / "processed",
        imports_rejected=root / "imports" / "rejected",
        imports_reports=root / "imports" / "reports",
        contacts_attachments=root / "contacts" / "attachments",
        contacts_exports=root / "contacts" / "exports",
        audit_import_logs=root / "audit" / "import_logs",
        audit_merge_logs=root / "audit" / "merge_logs",
        indexes_search=root / "indexes" / "search",
    )
    for p in [
        root,
        memory,
        paths.backups,
        paths.migrations,
        paths.imports_pending,
        paths.imports_processed,
        paths.imports_rejected,
        paths.imports_reports,
        paths.contacts_attachments,
        paths.contacts_exports,
        paths.audit_import_logs,
        paths.audit_merge_logs,
        paths.indexes_search,
    ]:
        p.mkdir(parents=True, exist_ok=True)
    return paths


def backup_db(db_path: str, backup_dir: Path) -> Path:
    src = Path(db_path)
    stamp = now_utc()
    out = backup_dir / f"cali_personal-{stamp}.db"
    shutil.copy2(src, out)
    return out


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def normalize_name(value: str) -> str:
    v = re.sub(r"\s+", " ", str(value or "").strip())
    return v


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _safe_value(row: Dict[str, Any], *keys: str) -> str:
    lowered = {str(k or "").strip().lower(): v for k, v in dict(row or {}).items()}
    for key in keys:
        key_raw = str(key or "")
        val = row.get(key_raw)
        if val is None:
            val = row.get(key_raw.lower())
        if val is None:
            val = lowered.get(key_raw.strip().lower())
        if val is None:
            continue
        txt = str(val).strip()
        if txt:
            return txt
    return ""


def _decode_csv_bytes(csv_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "utf-16le", "utf-16be", "cp1252", "latin-1"):
        try:
            return csv_bytes.decode(enc)
        except Exception:
            continue
    return csv_bytes.decode("utf-8", errors="replace")


def _build_reader(text: str) -> Tuple[csv.DictReader, List[str]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [str(h or "") for h in (reader.fieldnames or [])]
    return reader, headers


def detect_source(fieldnames: List[str], explicit_source: Optional[str]) -> str:
    if explicit_source:
        return explicit_source
    keys = {str(k or "").strip().lower() for k in fieldnames}
    if {"given name", "family name", "e-mail 1 - value"} & keys:
        return "outlook_csv"
    if {"name", "e-mail 1 - value", "phone 1 - value"} & keys:
        return "gmail_csv"
    return "generic_csv"


def parse_row(row: Dict[str, Any], source_type: str) -> Dict[str, Any]:
    if source_type == "gmail_csv":
        first = _safe_value(row, "given name", "first name")
        last = _safe_value(row, "family name", "last name")
        full = normalize_name(f"{first} {last}".strip()) or _safe_value(row, "name", "full name")
        return {
            "name": full,
            "email": _safe_value(row, "e-mail 1 - value", "email", "email 1 - value"),
            "phone": _safe_value(row, "phone 1 - value", "phone", "phone 1 - value"),
            "address": _safe_value(row, "address 1 - formatted", "address", "location"),
            "company": _safe_value(row, "organization 1 - name", "company"),
            "company_role": _safe_value(row, "organization 1 - title", "job title", "title"),
            "notes": _safe_value(row, "notes", "note"),
        }
    if source_type == "outlook_csv":
        first = _safe_value(row, "first name", "given name")
        last = _safe_value(row, "last name", "surname")
        full = normalize_name(f"{first} {last}".strip()) or _safe_value(row, "name", "full name")
        return {
            "name": full,
            "email": _safe_value(row, "e-mail address", "e-mail 1 - value", "email"),
            "phone": _safe_value(row, "mobile phone", "business phone", "home phone", "phone"),
            "address": _safe_value(row, "business street", "home street", "address"),
            "company": _safe_value(row, "company", "organization"),
            "company_role": _safe_value(row, "job title", "title"),
            "notes": _safe_value(row, "notes", "note"),
        }
    return {
        "name": _safe_value(row, "name", "full_name", "display_name", "contact_name"),
        "email": _safe_value(row, "email", "email_address", "e-mail"),
        "phone": _safe_value(row, "phone", "phone_number", "mobile", "telephone"),
        "address": _safe_value(row, "address", "location"),
        "company": _safe_value(row, "company", "organization"),
        "company_role": _safe_value(row, "title", "job_title", "role"),
        "notes": _safe_value(row, "notes", "note", "description"),
    }


def _load_metadata(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def _load_aliases(raw: Any) -> List[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [normalize_name(str(x)) for x in parsed if str(x).strip()]
    except Exception:
        pass
    return [normalize_name(text)]


def _save_aliases(aliases: List[str]) -> str:
    uniq: List[str] = []
    seen = set()
    for a in aliases:
        n = normalize_name(a)
        if not n or n.lower() in seen:
            continue
        seen.add(n.lower())
        uniq.append(n)
    return json.dumps(uniq, ensure_ascii=True)


def _find_duplicate(conn: sqlite3.Connection, incoming: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    cur = conn.cursor()
    email = normalize_email(incoming.get("email", ""))
    phone_norm = normalize_phone(incoming.get("phone", ""))
    name_norm = normalize_name(incoming.get("name", "")).lower()
    company_norm = normalize_text(incoming.get("company", "")).lower()
    address_norm = normalize_text(incoming.get("address", "")).lower()

    if email:
        cur.execute("SELECT * FROM contacts WHERE lower(email) = ? LIMIT 1", (email,))
        row = cur.fetchone()
        if row:
            return dict(row), "email"

    if phone_norm:
        cur.execute("SELECT * FROM contacts WHERE phone IS NOT NULL AND phone != ''")
        for row in cur.fetchall():
            rec = dict(row)
            if normalize_phone(str(rec.get("phone") or "")) == phone_norm:
                return rec, "phone"

    if name_norm and company_norm:
        cur.execute("SELECT * FROM contacts")
        for row in cur.fetchall():
            rec = dict(row)
            rec_name = normalize_name(str(rec.get("name") or "")).lower()
            meta = _load_metadata(rec.get("metadata_payload"))
            rec_company = normalize_text(str(rec.get("company_role") or meta.get("company") or "")).lower()
            if rec_name == name_norm and rec_company and rec_company == company_norm:
                return rec, "name_company"

    if name_norm and address_norm:
        cur.execute("SELECT * FROM contacts")
        for row in cur.fetchall():
            rec = dict(row)
            rec_name = normalize_name(str(rec.get("name") or "")).lower()
            rec_addr = normalize_text(str(rec.get("address") or "")).lower()
            if rec_name == name_norm and rec_addr and rec_addr == address_norm:
                return rec, "name_address"

    # Fuzzy candidate only (review); no auto merge.
    if name_norm:
        cur.execute("SELECT * FROM contacts")
        for row in cur.fetchall():
            rec = dict(row)
            rec_name = normalize_name(str(rec.get("name") or "")).lower()
            if rec_name and (rec_name in name_norm or name_norm in rec_name):
                return rec, "fuzzy_candidate"
    return None, "none"


def _merge_contact(
    conn: sqlite3.Connection,
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
    source_type: str,
    row_index: int,
) -> Dict[str, Any]:
    now = datetime.utcnow().isoformat()
    updates: Dict[str, Any] = {}
    conflicts: Dict[str, Any] = {}

    # Preserve CRM owned values. Fill only empty fields.
    for field in ["phone", "email", "address", "notes", "owner", "crm_stage", "lead_source"]:
        ex = str(existing.get(field) or "").strip()
        inc = str(incoming.get(field) or "").strip()
        if not ex and inc:
            updates[field] = inc
        elif ex and inc and ex != inc:
            conflicts[field] = {"existing": ex, "imported": inc}

    # Company role can be filled if empty.
    ex_role = str(existing.get("company_role") or "").strip()
    inc_role = str(incoming.get("company_role") or "").strip()
    if not ex_role and inc_role:
        updates["company_role"] = inc_role
    elif ex_role and inc_role and ex_role != inc_role:
        conflicts["company_role"] = {"existing": ex_role, "imported": inc_role}

    # Name conflict stored as alias, not overwrite.
    aliases = _load_aliases(existing.get("alias_names"))
    ex_name = normalize_name(str(existing.get("name") or ""))
    in_name = normalize_name(str(incoming.get("name") or ""))
    if in_name and ex_name and in_name.lower() != ex_name.lower():
        aliases.append(in_name)

    # Metadata lineage and conflicts.
    meta = _load_metadata(existing.get("metadata_payload"))
    lineage = list(meta.get("import_lineage") or [])
    lineage.append(
        {
            "source": source_type,
            "row": row_index,
            "timestamp": now,
            "incoming_email": normalize_email(incoming.get("email", "")),
            "incoming_phone_norm": normalize_phone(incoming.get("phone", "")),
        }
    )
    meta["import_lineage"] = lineage[-200:]
    if conflicts:
        conflict_items = list(meta.get("import_conflicts") or [])
        conflict_items.append({"timestamp": now, "source": source_type, "row": row_index, "fields": conflicts})
        meta["import_conflicts"] = conflict_items[-200:]
    company = normalize_text(incoming.get("company", ""))
    if company:
        meta["company"] = meta.get("company") or company

    updates["alias_names"] = _save_aliases(aliases)
    updates["metadata_payload"] = json.dumps(meta, ensure_ascii=True)
    updates["updated_at"] = now

    set_clause = ", ".join(f"{k}=?" for k in updates.keys())
    values = list(updates.values()) + [existing["id"]]
    conn.execute(f"UPDATE contacts SET {set_clause} WHERE id = ?", values)
    return {"contact_id": existing["id"], "updated_fields": list(updates.keys()), "conflicts": conflicts}


def _insert_contact(conn: sqlite3.Connection, incoming: Dict[str, Any], source_type: str) -> str:
    now = datetime.utcnow().isoformat()
    name = normalize_name(incoming.get("name", "")) or normalize_email(incoming.get("email", "")) or "Imported Contact"
    contact_id = f"contact_import_{now_utc()}_{abs(hash((name, incoming.get('email', ''), incoming.get('phone', '')))) % 10_000_000}"
    hash_id = f"imp_{abs(hash((name.lower(), normalize_email(incoming.get('email', '')), normalize_phone(incoming.get('phone', ''))))) % 1_000_000_000:09d}"
    alias_names = "[]"
    metadata = {
        "source": source_type,
        "import_lineage": [{"timestamp": now, "source": source_type}],
        "company": normalize_text(incoming.get("company", "")) or None,
    }
    conn.execute(
        """
        INSERT INTO contacts (
            id, hash_id, name, type, phone, email, address, notes, priority,
            crm_stage, lead_source, owner, alias_names, company_role, metadata_payload,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            hash_id,
            name,
            str(incoming.get("contact_type") or "business"),
            str(incoming.get("phone") or "").strip() or None,
            normalize_email(incoming.get("email", "")) or None,
            str(incoming.get("address") or "").strip() or None,
            str(incoming.get("notes") or "").strip() or None,
            1,
            str(incoming.get("crm_stage") or "prospect"),
            str(incoming.get("lead_source") or "csv_import"),
            str(incoming.get("owner") or "").strip() or None,
            alias_names,
            str(incoming.get("company_role") or "").strip() or None,
            json.dumps(metadata, ensure_ascii=True),
            now,
            now,
        ),
    )
    return contact_id


def _generate_links_for_contact(conn: sqlite3.Connection, contact_id: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, address FROM contacts WHERE id = ? LIMIT 1", (contact_id,))
    row = cur.fetchone()
    if not row:
        return 0
    record = dict(row)
    name = normalize_name(record.get("name", ""))
    if not name:
        return 0
    encoded_name = re.sub(r"\s+", "+", name.strip())
    generated: List[Tuple[str, str, str, str]] = [
        ("google_search", "Google Search", f"https://www.google.com/search?q={encoded_name}", "search_fallback"),
        ("facebook", "Facebook Search", f"https://www.facebook.com/search/top/?q={encoded_name}", "search_fallback"),
        ("linkedin", "LinkedIn Search", f"https://www.linkedin.com/search/results/all/?keywords={encoded_name}", "search_fallback"),
        ("github", "GitHub Search", f"https://github.com/search?q={encoded_name}&type=users", "search_fallback"),
    ]
    address = normalize_text(record.get("address", ""))
    if address:
        addr = re.sub(r"\s+", "+", address)
        generated.append(("google_maps", "Google Maps", f"https://www.google.com/maps/search/?api=1&query={encoded_name}+{addr}", "search_fallback"))
    else:
        generated.append(("google_maps", "Google Maps Search", f"https://www.google.com/maps/search/?api=1&query={encoded_name}", "search_fallback"))
    email = normalize_email(record.get("email", ""))
    if "@" in email:
        domain = email.split("@")[-1]
        if domain and domain not in {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "msn.com"}:
            generated.append(("domain_lookup", "Domain Intelligence", f"https://who.is/whois/{domain}", "direct_profile"))
            generated.append(("company_website", "Corporate Domain", f"https://{domain}", "direct_profile"))

    written = 0
    now = datetime.utcnow().isoformat()
    for platform, label, url, link_type in generated:
        cur.execute(
            """
            INSERT OR IGNORE INTO contact_external_links
            (contact_id, platform, label, url, link_type, verified_status, source, confidence_score, last_checked_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'generated_search', 'deterministic_generator', 0.3, ?, ?, ?)
            """,
            (contact_id, platform, label, url, link_type, now, now, now),
        )
        if cur.rowcount > 0:
            written += 1
    return written


def run_phase1c_import(
    db_path: str,
    original_filename: str,
    csv_bytes: bytes,
    explicit_source: Optional[str],
    default_contact_type: str,
    default_stage: str,
    owner: Optional[str],
) -> Dict[str, Any]:
    paths = ensure_phase1c_dirs(db_path)
    run_unified_migration(db_path)
    backup_path = backup_db(db_path, paths.backups)

    stamp = now_utc()
    pending_name = f"{stamp}-{Path(original_filename or 'import.csv').name}"
    pending_file = paths.imports_pending / pending_name
    pending_file.write_bytes(csv_bytes)

    text = _decode_csv_bytes(csv_bytes)
    reader, headers = _build_reader(text)
    source_type = detect_source(headers, explicit_source)

    report: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(),
        "source_type": source_type,
        "file": original_filename,
        "paths": {"pending": str(pending_file), "backup": str(backup_path), "db": db_path},
        "counts": {"created": 0, "updated": 0, "merged": 0, "skipped": 0, "rejected": 0, "review_candidates": 0, "errors": 0},
        "merge_audit": [],
        "errors": [],
        "headers": headers,
    }

    merge_log_entries: List[Dict[str, Any]] = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for row_index, raw in enumerate(reader, start=2):
            parsed = parse_row(raw, source_type)
            parsed["contact_type"] = parsed.get("contact_type") or default_contact_type
            parsed["crm_stage"] = parsed.get("crm_stage") or default_stage
            parsed["owner"] = parsed.get("owner") or owner
            parsed["lead_source"] = "csv_import"
            parsed["name"] = normalize_name(parsed.get("name", ""))
            parsed["email"] = normalize_email(parsed.get("email", ""))
            parsed["phone"] = normalize_text(parsed.get("phone", ""))
            parsed["address"] = normalize_text(parsed.get("address", ""))

            if not parsed["name"] and not parsed["email"] and not parsed["phone"]:
                report["counts"]["skipped"] += 1
                continue

            existing, reason = _find_duplicate(conn, parsed)
            if reason == "fuzzy_candidate":
                report["counts"]["review_candidates"] += 1
                report["counts"]["rejected"] += 1
                merge_log_entries.append({"row": row_index, "decision": "review_required", "reason": reason, "incoming": parsed})
                continue

            if existing:
                merged = _merge_contact(conn, existing, parsed, source_type, row_index)
                report["counts"]["updated"] += 1
                report["counts"]["merged"] += 1
                new_links = _generate_links_for_contact(conn, merged["contact_id"])
                merge_log_entries.append(
                    {
                        "row": row_index,
                        "decision": "merged",
                        "reason": reason,
                        "contact_id": merged["contact_id"],
                        "updated_fields": merged["updated_fields"],
                        "conflicts": merged["conflicts"],
                        "generated_links": new_links,
                    }
                )
                continue

            try:
                contact_id = _insert_contact(conn, parsed, source_type)
                report["counts"]["created"] += 1
                new_links = _generate_links_for_contact(conn, contact_id)
                merge_log_entries.append(
                    {
                        "row": row_index,
                        "decision": "created",
                        "reason": "no_duplicate_match",
                        "contact_id": contact_id,
                        "generated_links": new_links,
                    }
                )
            except Exception as exc:
                report["counts"]["errors"] += 1
                report["errors"].append(f"row {row_index}: {exc}")
                merge_log_entries.append({"row": row_index, "decision": "error", "error": str(exc)})

        conn.commit()
    finally:
        conn.close()

    report["merge_audit"] = merge_log_entries
    if report["counts"]["errors"] == 0:
        processed_path = paths.imports_processed / pending_name
        shutil.move(str(pending_file), str(processed_path))
        report["paths"]["processed"] = str(processed_path)
    else:
        rejected_path = paths.imports_rejected / pending_name
        shutil.move(str(pending_file), str(rejected_path))
        report["paths"]["rejected"] = str(rejected_path)

    report_file = paths.imports_reports / f"import-report-{stamp}.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["paths"]["report"] = str(report_file)

    import_log_file = paths.audit_import_logs / f"import-log-{stamp}.jsonl"
    import_log_file.write_text(json.dumps(report) + "\n", encoding="utf-8")
    report["paths"]["import_log"] = str(import_log_file)

    merge_log_file = paths.audit_merge_logs / f"merge-log-{stamp}.jsonl"
    with merge_log_file.open("w", encoding="utf-8") as handle:
        for entry in merge_log_entries:
            handle.write(json.dumps(entry) + "\n")
    report["paths"]["merge_log"] = str(merge_log_file)

    return report
