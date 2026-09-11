from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import _db_path, _ensure_schema, verify_admin
from cali_skg.core.dossier_package_store import (
    dossier_package_info,
    ensure_all_dossier_packages,
    ensure_dossier_package,
)

router = APIRouter(prefix="/cali/intelligence", tags=["cali-dossier-packages"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_media_id(contact_id: str, digest: str) -> str:
    return f"media:{hashlib.sha256(f'{contact_id}|{digest}'.encode('utf-8')).hexdigest()[:32]}"


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "image").strip()).strip("._-")
    return stem[:80] or "image"


def _contact_or_404(conn: sqlite3.Connection, contact_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, name FROM contacts WHERE id=?", (contact_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return row


class PackageEnsureRequest(BaseModel):
    contact_ids: List[str] = Field(default_factory=list)


@router.post("/dossiers/packages/ensure")
def ensure_packages(payload: PackageEnsureRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    return ensure_all_dossier_packages(_db_path(), payload.contact_ids or None)


@router.get("/contacts/{contact_id}/package")
def get_package(contact_id: str, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    db_path = _db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = _contact_or_404(conn, contact_id)
    return dossier_package_info(db_path, contact_id, str(row["name"] or ""))


@router.post("/contacts/{contact_id}/images")
async def upload_dossier_image(
    contact_id: str,
    file: UploadFile = File(...),
    media_kind: str = Form("person"),
    label: str = Form(""),
    notes: str = Form(""),
    is_primary: bool = Form(False),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    db_path = _db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = _contact_or_404(conn, contact_id)

    content_type = str(file.content_type or "").lower().strip()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Use JPG, PNG, WebP, or GIF images")
    payload = await file.read(MAX_IMAGE_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=400, detail="Image file is empty")
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 10 MB dossier limit")

    package = ensure_dossier_package(
        db_path,
        contact_id,
        display_name=str(row["name"] or ""),
        party_id=f"legacy-contact:{contact_id}",
    )
    digest = hashlib.sha256(payload).hexdigest()
    extension = EXTENSIONS[content_type]
    original_stem = Path(file.filename or "image").stem
    filename = f"{_safe_stem(original_stem)}-{digest[:12]}{extension}"
    image_path = Path(package["package_dir"]) / "images" / filename
    image_path.write_bytes(payload)

    normalized_kind = str(media_kind or "person").strip().lower()
    if normalized_kind not in {"person", "place", "building", "other"}:
        normalized_kind = "other"
    media_id = _stable_media_id(contact_id, digest)
    now = _utc_now()
    data_url = f"data:{content_type};base64,{base64.b64encode(payload).decode('ascii')}"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if is_primary:
            conn.execute("UPDATE dossier_media SET is_primary=0, updated_at=? WHERE contact_id=?", (now, contact_id))
        conn.execute(
            """
            INSERT INTO dossier_media(
                media_id, contact_id, party_id, media_kind, label, image_url,
                notes, is_primary, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_id) DO UPDATE SET
                media_kind=excluded.media_kind,
                label=excluded.label,
                image_url=excluded.image_url,
                notes=excluded.notes,
                is_primary=excluded.is_primary,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (
                media_id,
                contact_id,
                f"legacy-contact:{contact_id}",
                normalized_kind,
                label.strip() or file.filename or filename,
                data_url,
                notes.strip() or None,
                1 if is_primary else 0,
                f"dossier_package:images/{filename}",
                now,
                now,
            ),
        )
        conn.commit()
        saved = conn.execute("SELECT * FROM dossier_media WHERE media_id=?", (media_id,)).fetchone()

    return {
        "status": "success",
        "package": package,
        "image_file": str(image_path),
        "media": dict(saved) if saved else None,
    }


@router.delete("/contacts/{contact_id}/images/{media_id}")
def delete_dossier_image(contact_id: str, media_id: str, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    db_path = _db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _contact_or_404(conn, contact_id)
        row = conn.execute(
            "SELECT media_id, source, is_primary FROM dossier_media WHERE contact_id=? AND media_id=?",
            (contact_id, media_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Dossier image not found")

        source = str(row["source"] or "")
        deleted_file = False
        if source.startswith("dossier_package:images/"):
            filename = Path(source.split("dossier_package:images/", 1)[1]).name
            package = ensure_dossier_package(db_path, contact_id)
            image_path = Path(package["package_dir"]) / "images" / filename
            if image_path.exists() and image_path.is_file():
                image_path.unlink()
                deleted_file = True

        was_primary = bool(row["is_primary"])
        conn.execute("DELETE FROM dossier_media WHERE contact_id=? AND media_id=?", (contact_id, media_id))
        if was_primary:
            replacement = conn.execute(
                "SELECT media_id FROM dossier_media WHERE contact_id=? ORDER BY created_at DESC LIMIT 1",
                (contact_id,),
            ).fetchone()
            if replacement:
                conn.execute(
                    "UPDATE dossier_media SET is_primary=1, updated_at=? WHERE media_id=?",
                    (_utc_now(), replacement["media_id"]),
                )
        conn.commit()

    return {"deleted": True, "media_id": media_id, "file_deleted": deleted_file}
