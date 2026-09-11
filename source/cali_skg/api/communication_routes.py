from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import _db_path, _ensure_schema, verify_admin
from cali_skg.core.communication_store import ingest_message, party_timeline, resolve_party_by_email
from cali_skg.core.dossier_store import party_dossier

router = APIRouter(prefix="/cali/intelligence", tags=["cali-communications"])


class CommunicationMessageIngest(BaseModel):
    channel: str = "email"
    provider: str = "prime_mail"
    account_identity: str
    business_scope: str = "all"
    external_id: str
    mailbox_id: Optional[str] = None
    direction: str
    occurred_at: str
    raw_locator: str
    content_hash: str
    thread_external_id: Optional[str] = None
    subject: str = ""
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    recipient_emails: List[str] = Field(default_factory=list)


@router.get("/parties/resolve")
def resolve_party(
    email: str,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    match = resolve_party_by_email(_db_path(), email)
    return {"found": bool(match), "party": match}


@router.get("/parties/{party_id:path}/dossier")
def get_party_dossier(
    party_id: str,
    business_scope: str = "all",
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    dossier = party_dossier(_db_path(), party_id, business_scope=business_scope)
    if not dossier:
        raise HTTPException(status_code=404, detail="Party not found")
    return dossier


@router.post("/messages/ingest")
def ingest_communication_message(
    payload: CommunicationMessageIngest,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    try:
        result = ingest_message(_db_path(), payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Communication ingest failed: {exc}") from exc
    return {"status": "recorded", **result}


@router.get("/parties/{party_id:path}/timeline")
def get_party_timeline(
    party_id: str,
    business_scope: str = "all",
    channel: str = "all",
    limit: int = Query(default=100, ge=1, le=500),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    items = party_timeline(
        _db_path(),
        party_id,
        business_scope=business_scope,
        channel=channel,
        limit=limit,
    )
    return {
        "party_id": party_id,
        "business_scope": business_scope,
        "channel": channel,
        "count": len(items),
        "events": items,
    }
