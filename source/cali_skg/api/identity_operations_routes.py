from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cali_skg.api.operations_routes import append_audit
from cali_skg.api.relationship_routes import _db_path, _ensure_schema, _stable_id, verify_admin

router = APIRouter(prefix="/cali/intelligence/identity", tags=["cali-identity-operations"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def _party_or_404(conn: sqlite3.Connection, party_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM party WHERE party_id=?", (party_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Party not found: {party_id}")
    return row


def _ensure_legacy_status_column(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    if "identity_status" not in columns:
        conn.execute("ALTER TABLE contacts ADD COLUMN identity_status TEXT DEFAULT 'active'")


def _legacy_contact_id(party_id: str) -> Optional[str]:
    prefix = "legacy-contact:"
    return party_id[len(prefix):] if party_id.startswith(prefix) else None


class MergeRequest(BaseModel):
    surviving_party_id: str = Field(min_length=1)
    merged_party_id: str = Field(min_length=1)
    reviewer: str = "user"
    reason: Optional[str] = None
    matching_identifiers: List[Dict[str, Any]] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    score_components: Dict[str, Any] = Field(default_factory=dict)
    model_version: Optional[str] = None


class SplitRequest(BaseModel):
    reviewer: str = "user"
    reason: Optional[str] = None


def _move_claims(
    conn: sqlite3.Connection,
    survivor: str,
    merged: str,
    snapshot: List[Dict[str, Any]],
) -> None:
    claims = conn.execute("SELECT * FROM identity_claim WHERE party_id=? ORDER BY created_at", (merged,)).fetchall()
    for claim in claims:
        claim_data = dict(claim)
        duplicate = conn.execute(
            """
            SELECT claim_id FROM identity_claim
            WHERE party_id=? AND claim_type=? AND value_hash=?
              AND superseded_by IS NULL AND valid_to IS NULL
            LIMIT 1
            """,
            (survivor, claim["claim_type"], claim["value_hash"]),
        ).fetchone()
        if duplicate:
            snapshot.append(
                {
                    "kind": "claim_superseded",
                    "claim_id": claim["claim_id"],
                    "prior": claim_data,
                    "superseded_by": duplicate["claim_id"],
                }
            )
            conn.execute(
                """
                UPDATE identity_claim
                SET verification_state='superseded', superseded_by=?, valid_to=?
                WHERE claim_id=?
                """,
                (duplicate["claim_id"], _utc_now(), claim["claim_id"]),
            )
        else:
            snapshot.append({"kind": "claim_move", "claim_id": claim["claim_id"], "from": merged, "to": survivor})
            conn.execute("UPDATE identity_claim SET party_id=? WHERE claim_id=?", (survivor, claim["claim_id"]))


def _merge_roles(
    conn: sqlite3.Connection,
    survivor: str,
    merged: str,
    snapshot: List[Dict[str, Any]],
) -> None:
    now = _utc_now()
    roles = conn.execute(
        "SELECT * FROM party_business_role WHERE party_id=? AND valid_to IS NULL ORDER BY business_id",
        (merged,),
    ).fetchall()
    for role in roles:
        role_data = dict(role)
        existing = conn.execute(
            "SELECT * FROM party_business_role WHERE party_id=? AND business_id=? AND valid_to IS NULL LIMIT 1",
            (survivor, role["business_id"]),
        ).fetchone()
        if not existing:
            snapshot.append({"kind": "role_move", "role_id": role["role_id"], "from": merged, "to": survivor})
            conn.execute("UPDATE party_business_role SET party_id=? WHERE role_id=?", (survivor, role["role_id"]))
            continue

        existing_tags = set(json.loads(str(existing["segment_tags"] or "[]")))
        merged_tags = set(json.loads(str(role["segment_tags"] or "[]")))
        combined_tags = sorted(str(tag) for tag in existing_tags | merged_tags if str(tag).strip())
        snapshot.append(
            {
                "kind": "role_fold",
                "folded_role": role_data,
                "survivor_role_prior": dict(existing),
            }
        )
        conn.execute(
            """
            UPDATE party_business_role
            SET segment_tags=?, role=COALESCE(role, ?)
            WHERE role_id=?
            """,
            (json.dumps(combined_tags), role["role"], existing["role_id"]),
        )
        conn.execute("UPDATE party_business_role SET valid_to=? WHERE role_id=?", (now, role["role_id"]))


def _move_thread_participants(
    conn: sqlite3.Connection,
    survivor: str,
    merged: str,
    snapshot: List[Dict[str, Any]],
) -> None:
    rows = conn.execute("SELECT * FROM conversation_participant WHERE party_id=?", (merged,)).fetchall()
    for row in rows:
        existing = conn.execute(
            "SELECT 1 FROM conversation_participant WHERE thread_id=? AND party_id=? AND role=?",
            (row["thread_id"], survivor, row["role"]),
        ).fetchone()
        prior = dict(row)
        if existing:
            snapshot.append({"kind": "participant_fold", "prior": prior})
            conn.execute(
                "DELETE FROM conversation_participant WHERE thread_id=? AND party_id=? AND role=?",
                (row["thread_id"], merged, row["role"]),
            )
        else:
            snapshot.append({"kind": "participant_move", "prior": prior})
            conn.execute(
                """
                UPDATE conversation_participant SET party_id=?
                WHERE thread_id=? AND party_id=? AND role=?
                """,
                (survivor, row["thread_id"], merged, row["role"]),
            )


def _move_simple_party_refs(
    conn: sqlite3.Connection,
    survivor: str,
    merged: str,
    snapshot: List[Dict[str, Any]],
) -> None:
    mappings: List[Tuple[str, str, str]] = [
        ("conversation_thread", "thread_id", "primary_party_id"),
        ("relevance_assessment", "assessment_id", "party_id"),
        ("escalation_event", "escalation_id", "party_id"),
        ("import_tombstone", "tombstone_id", "party_id"),
    ]
    for table, key_column, party_column in mappings:
        rows = conn.execute(f"SELECT {key_column} FROM {table} WHERE {party_column}=?", (merged,)).fetchall()
        for row in rows:
            key = str(row[key_column])
            snapshot.append(
                {
                    "kind": "simple_ref_move",
                    "table": table,
                    "key_column": key_column,
                    "party_column": party_column,
                    "key": key,
                    "from": merged,
                    "to": survivor,
                }
            )
            conn.execute(f"UPDATE {table} SET {party_column}=? WHERE {key_column}=?", (survivor, key))


def _move_graph_rows(
    conn: sqlite3.Connection,
    survivor: str,
    merged: str,
    snapshot: List[Dict[str, Any]],
) -> None:
    # Verified/asserted edges.
    edges = conn.execute(
        "SELECT * FROM relationship_edge WHERE from_party=? OR to_party=?",
        (merged, merged),
    ).fetchall()
    for edge in edges:
        prior = dict(edge)
        new_from = survivor if edge["from_party"] == merged else str(edge["from_party"])
        new_to = survivor if edge["to_party"] == merged else str(edge["to_party"])
        if new_from == new_to:
            snapshot.append({"kind": "edge_retire", "prior": prior})
            conn.execute("UPDATE relationship_edge SET state='retired', valid_to=? WHERE edge_id=?", (_utc_now(), edge["edge_id"]))
            continue
        duplicate = conn.execute(
            """
            SELECT edge_id FROM relationship_edge
            WHERE from_party=? AND to_party=? AND predicate=?
              AND state IN ('asserted','verified') AND edge_id<>?
            LIMIT 1
            """,
            (new_from, new_to, edge["predicate"], edge["edge_id"]),
        ).fetchone()
        if duplicate:
            snapshot.append({"kind": "edge_retire", "prior": prior})
            conn.execute("UPDATE relationship_edge SET state='retired', valid_to=? WHERE edge_id=?", (_utc_now(), edge["edge_id"]))
        else:
            snapshot.append({"kind": "edge_move", "prior": prior})
            conn.execute(
                "UPDATE relationship_edge SET from_party=?, to_party=? WHERE edge_id=?",
                (new_from, new_to, edge["edge_id"]),
            )

    candidates = conn.execute(
        "SELECT * FROM relationship_candidate WHERE from_party=? OR to_party=?",
        (merged, merged),
    ).fetchall()
    for candidate in candidates:
        prior = dict(candidate)
        new_from = survivor if candidate["from_party"] == merged else str(candidate["from_party"])
        new_to = survivor if candidate["to_party"] == merged else str(candidate["to_party"])
        if new_from == new_to:
            snapshot.append({"kind": "candidate_expire", "prior": prior})
            conn.execute("UPDATE relationship_candidate SET review_state='expired' WHERE candidate_id=?", (candidate["candidate_id"],))
        else:
            snapshot.append({"kind": "candidate_move", "prior": prior})
            conn.execute(
                "UPDATE relationship_candidate SET from_party=?, to_party=? WHERE candidate_id=?",
                (new_from, new_to, candidate["candidate_id"]),
            )

    rejections = conn.execute(
        "SELECT * FROM relationship_rejection WHERE from_party=? OR to_party=?",
        (merged, merged),
    ).fetchall()
    for rejection in rejections:
        prior = dict(rejection)
        new_from = survivor if rejection["from_party"] == merged else str(rejection["from_party"])
        new_to = survivor if rejection["to_party"] == merged else str(rejection["to_party"])
        snapshot.append({"kind": "rejection_move", "prior": prior})
        conn.execute(
            "UPDATE relationship_rejection SET from_party=?, to_party=? WHERE rejection_id=?",
            (new_from, new_to, rejection["rejection_id"]),
        )


def _restore_row(conn: sqlite3.Connection, table: str, prior: Dict[str, Any], key_column: str) -> None:
    key = prior[key_column]
    columns = list(prior.keys())
    assignments = ", ".join(f"{column}=?" for column in columns if column != key_column)
    values = [prior[column] for column in columns if column != key_column]
    values.append(key)
    conn.execute(f"UPDATE {table} SET {assignments} WHERE {key_column}=?", tuple(values))


@router.post("/merge")
def merge_parties(payload: MergeRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    if payload.surviving_party_id == payload.merged_party_id:
        raise HTTPException(status_code=400, detail="A party cannot be merged into itself")

    with _connect() as conn:
        _ensure_legacy_status_column(conn)
        survivor_row = _party_or_404(conn, payload.surviving_party_id)
        merged_row = _party_or_404(conn, payload.merged_party_id)
        if survivor_row["status"] == "deleted" or merged_row["status"] == "deleted":
            raise HTTPException(status_code=409, detail="Deleted parties cannot be merged")
        if merged_row["status"] == "merged":
            raise HTTPException(status_code=409, detail="Party is already merged")

        snapshot: List[Dict[str, Any]] = []
        _move_claims(conn, payload.surviving_party_id, payload.merged_party_id, snapshot)
        _merge_roles(conn, payload.surviving_party_id, payload.merged_party_id, snapshot)
        _move_graph_rows(conn, payload.surviving_party_id, payload.merged_party_id, snapshot)
        _move_thread_participants(conn, payload.surviving_party_id, payload.merged_party_id, snapshot)
        _move_simple_party_refs(conn, payload.surviving_party_id, payload.merged_party_id, snapshot)

        now = _utc_now()
        snapshot.append({"kind": "merged_party_state", "prior": dict(merged_row)})
        conn.execute(
            "UPDATE party SET status='merged', merged_into=?, updated_at=? WHERE party_id=?",
            (payload.surviving_party_id, now, payload.merged_party_id),
        )
        merged_contact_id = _legacy_contact_id(payload.merged_party_id)
        if merged_contact_id:
            conn.execute("UPDATE contacts SET identity_status='merged' WHERE id=?", (merged_contact_id,))

        merge_id = _stable_id("merge", payload.surviving_party_id, payload.merged_party_id, now)
        conn.execute(
            """
            INSERT INTO merge_event(
              merge_id, surviving_party_id, merged_party_id, matching_identifiers,
              contradictions, score_components, model_version, reviewer, decision,
              reassignment_snapshot, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'merged', ?, ?)
            """,
            (
                merge_id,
                payload.surviving_party_id,
                payload.merged_party_id,
                json.dumps(payload.matching_identifiers),
                json.dumps(payload.contradictions),
                json.dumps(payload.score_components),
                payload.model_version,
                payload.reviewer,
                json.dumps(snapshot),
                now,
            ),
        )
        audit = append_audit(
            conn,
            actor=payload.reviewer,
            action="merge",
            target_ids=[payload.surviving_party_id, payload.merged_party_id, merge_id],
            prior_state={"survivor": dict(survivor_row), "merged": dict(merged_row)},
            new_state={"surviving_party_id": payload.surviving_party_id, "merged_party_id": payload.merged_party_id},
            reason=payload.reason,
            correlation_id=merge_id,
        )
        conn.commit()

    return {
        "merge_id": merge_id,
        "surviving_party_id": payload.surviving_party_id,
        "merged_party_id": payload.merged_party_id,
        "operations": len(snapshot),
        "reversible": True,
        "audit": audit,
    }


@router.post("/merge/{merge_id}/split")
def split_merge(merge_id: str, payload: SplitRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        _ensure_legacy_status_column(conn)
        merge_row = conn.execute("SELECT * FROM merge_event WHERE merge_id=?", (merge_id,)).fetchone()
        if not merge_row:
            raise HTTPException(status_code=404, detail="Merge event not found")
        if merge_row["reversed_at"]:
            raise HTTPException(status_code=409, detail="Merge is already split")

        survivor = str(merge_row["surviving_party_id"])
        merged = str(merge_row["merged_party_id"])
        snapshot = json.loads(str(merge_row["reassignment_snapshot"] or "[]"))

        for operation in reversed(snapshot):
            kind = operation.get("kind")
            if kind == "claim_move":
                conn.execute("UPDATE identity_claim SET party_id=? WHERE claim_id=?", (operation["from"], operation["claim_id"]))
            elif kind == "claim_superseded":
                _restore_row(conn, "identity_claim", operation["prior"], "claim_id")
            elif kind == "role_move":
                conn.execute("UPDATE party_business_role SET party_id=? WHERE role_id=?", (operation["from"], operation["role_id"]))
            elif kind == "role_fold":
                folded = operation["folded_role"]
                survivor_prior = operation["survivor_role_prior"]
                _restore_row(conn, "party_business_role", survivor_prior, "role_id")
                _restore_row(conn, "party_business_role", folded, "role_id")
            elif kind == "participant_move":
                prior = operation["prior"]
                conn.execute(
                    """
                    UPDATE conversation_participant SET party_id=?
                    WHERE thread_id=? AND party_id=? AND role=?
                    """,
                    (prior["party_id"], prior["thread_id"], survivor, prior["role"]),
                )
            elif kind == "participant_fold":
                prior = operation["prior"]
                conn.execute(
                    "INSERT OR IGNORE INTO conversation_participant(thread_id, party_id, role) VALUES (?, ?, ?)",
                    (prior["thread_id"], prior["party_id"], prior["role"]),
                )
            elif kind == "simple_ref_move":
                conn.execute(
                    f"UPDATE {operation['table']} SET {operation['party_column']}=? WHERE {operation['key_column']}=?",
                    (operation["from"], operation["key"]),
                )
            elif kind == "edge_move" or kind == "edge_retire":
                _restore_row(conn, "relationship_edge", operation["prior"], "edge_id")
            elif kind == "candidate_move" or kind == "candidate_expire":
                _restore_row(conn, "relationship_candidate", operation["prior"], "candidate_id")
            elif kind == "rejection_move":
                _restore_row(conn, "relationship_rejection", operation["prior"], "rejection_id")
            elif kind == "merged_party_state":
                _restore_row(conn, "party", operation["prior"], "party_id")

        merged_contact_id = _legacy_contact_id(merged)
        if merged_contact_id:
            conn.execute("UPDATE contacts SET identity_status='active' WHERE id=?", (merged_contact_id,))
        now = _utc_now()
        conn.execute("UPDATE merge_event SET reversed_at=?, decision='split' WHERE merge_id=?", (now, merge_id))
        audit = append_audit(
            conn,
            actor=payload.reviewer,
            action="split",
            target_ids=[survivor, merged, merge_id],
            prior_state={"merge_id": merge_id, "decision": merge_row["decision"]},
            new_state={"merge_id": merge_id, "decision": "split"},
            reason=payload.reason,
            correlation_id=merge_id,
        )
        conn.commit()

    return {
        "merge_id": merge_id,
        "surviving_party_id": survivor,
        "restored_party_id": merged,
        "state": "split",
        "audit": audit,
    }


@router.delete("/parties/{party_id}")
def tombstone_party(party_id: str, reason: Optional[str] = None, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        _ensure_legacy_status_column(conn)
        party = _party_or_404(conn, party_id)
        if party["status"] == "merged":
            raise HTTPException(status_code=409, detail="Split a merged identity before deleting it")
        if party["status"] == "deleted":
            return {"party_id": party_id, "status": "deleted", "tombstones_created": 0, "idempotent": True}

        claims = conn.execute(
            """
            SELECT claim_id, claim_type, value_hash, business_scope
            FROM identity_claim
            WHERE party_id=? AND verification_state<>'rejected'
            """,
            (party_id,),
        ).fetchall()
        created = 0
        now = _utc_now()
        for claim in claims:
            tombstone_id = _stable_id("tombstone", party_id, claim["claim_type"], claim["value_hash"], claim["business_scope"] or "")
            conn.execute(
                """
                INSERT OR IGNORE INTO import_tombstone(
                  tombstone_id, source_type, claim_type, value_hash, party_id,
                  business_scope, deleted_at, reason
                ) VALUES (?, 'contact_delete', ?, ?, ?, ?, ?, ?)
                """,
                (
                    tombstone_id,
                    claim["claim_type"],
                    claim["value_hash"],
                    party_id,
                    claim["business_scope"],
                    now,
                    reason,
                ),
            )
            created += 1

        conn.execute("UPDATE party SET status='deleted', updated_at=? WHERE party_id=?", (now, party_id))
        contact_id = _legacy_contact_id(party_id)
        if contact_id:
            conn.execute("UPDATE contacts SET identity_status='deleted' WHERE id=?", (contact_id,))
        audit = append_audit(
            conn,
            actor="user",
            action="tombstone_contact",
            target_ids=[party_id],
            prior_state=dict(party),
            new_state={"status": "deleted", "tombstones": created},
            reason=reason,
        )
        conn.commit()

    return {"party_id": party_id, "status": "deleted", "tombstones_created": created, "audit": audit}


@router.get("/merges")
def list_merges(active_only: bool = True, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        if active_only:
            rows = conn.execute("SELECT * FROM merge_event WHERE reversed_at IS NULL ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM merge_event ORDER BY created_at DESC").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["matching_identifiers"] = json.loads(str(item.get("matching_identifiers") or "[]"))
        item["contradictions"] = json.loads(str(item.get("contradictions") or "[]"))
        item["score_components"] = json.loads(str(item.get("score_components") or "{}"))
        result.append(item)
    return {"merges": result, "count": len(result)}
