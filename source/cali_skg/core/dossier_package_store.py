from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_root_from_db(db_path: str) -> Path:
    return Path(db_path).resolve().parent.parent


def dossier_root(db_path: str) -> Path:
    configured = str(os.getenv("VIV_DOSSIER_ROOT") or "").strip()
    root = Path(configured) if configured else _canonical_root_from_db(db_path) / "dossiers"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    return cleaned[:140] or "dossier"


def _manifest_path(package_dir: Path) -> Path:
    return package_dir / "manifest.json"


def ensure_dossier_package(
    db_path: str,
    contact_id: str,
    *,
    display_name: str = "",
    party_id: Optional[str] = None,
) -> Dict[str, Any]:
    contact_key = _safe_component(contact_id)
    package_dir = dossier_root(db_path) / contact_key
    folders = {
        "package": package_dir,
        "images": package_dir / "images",
        "documents": package_dir / "documents",
        "evidence": package_dir / "evidence",
        "exports": package_dir / "exports",
    }
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)

    manifest_file = _manifest_path(package_dir)
    prior: Dict[str, Any] = {}
    if manifest_file.exists():
        try:
            loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prior = loaded
        except Exception:
            prior = {}

    now = _utc_now()
    manifest = {
        "schema": "viv.dossier.package.v1",
        "contact_id": str(contact_id),
        "party_id": party_id or prior.get("party_id") or f"legacy-contact:{contact_id}",
        "display_name": display_name or prior.get("display_name") or "",
        "created_at": prior.get("created_at") or now,
        "updated_at": now,
        "folders": {name: str(path) for name, path in folders.items() if name != "package"},
    }
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        **manifest,
        "package_dir": str(package_dir),
        "manifest_path": str(manifest_file),
    }


def ensure_all_dossier_packages(db_path: str, contact_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    requested = {str(item).strip() for item in (contact_ids or []) if str(item).strip()}
    if not Path(db_path).exists():
        return {"status": "skipped", "reason": "database_missing", "created_or_verified": 0, "packages": []}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if requested:
            placeholders = ",".join("?" for _ in requested)
            rows = conn.execute(
                f"SELECT id, name FROM contacts WHERE id IN ({placeholders}) ORDER BY name COLLATE NOCASE",
                tuple(sorted(requested)),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, name FROM contacts ORDER BY name COLLATE NOCASE").fetchall()

    packages = [
        ensure_dossier_package(
            db_path,
            str(row["id"]),
            display_name=str(row["name"] or ""),
            party_id=f"legacy-contact:{row['id']}",
        )
        for row in rows
        if str(row["id"] or "").strip()
    ]
    return {
        "status": "success",
        "created_or_verified": len(packages),
        "packages": packages,
    }


def dossier_package_info(db_path: str, contact_id: str, display_name: str = "") -> Dict[str, Any]:
    package = ensure_dossier_package(db_path, contact_id, display_name=display_name)
    package_dir = Path(package["package_dir"])
    inventory: Dict[str, list[str]] = {}
    for name in ("images", "documents", "evidence", "exports"):
        folder = package_dir / name
        inventory[name] = sorted(path.name for path in folder.iterdir() if path.is_file())
    package["inventory"] = inventory
    return package
