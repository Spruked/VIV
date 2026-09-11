from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, Query

from cali_skg.api.relationship_routes import (
    CANDIDATE_SIGNAL_WEIGHT,
    _candidate_groups,
    _connect,
    _ensure_schema,
    _pair_key,
    _stable_id,
    verify_admin,
)

router = APIRouter(prefix="/cali/intelligence", tags=["cali-relationship-intelligence"])


@router.post("/scan")
def scan_relationship_candidates_bounded(
    business_scope: str = "all",
    max_new: int = Query(default=250, ge=1, le=2500),
    max_pairs: int = Query(default=5000, ge=100, le=100000),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    """Bounded incremental relationship discovery for the Dossier Vault.

    This deliberately keeps local coincidence evidence in candidate state only.
    It also caps total pair examination independently from candidate writes so a
    large or previously-scanned contact set cannot monopolize the VIV API.
    """

    _ensure_schema()
    now_dt = datetime.now(timezone.utc)
    expires = (now_dt + timedelta(days=90)).isoformat()
    inference_run = f"local-association-scan:v2:{now_dt.isoformat()}"
    written = 0
    pairs_examined = 0
    groups_examined = 0
    groups_skipped = 0
    stopped_reason = "complete"
    seen_pairs: set[Tuple[str, str, str]] = set()

    # Weak geographic/domain signals can create enormous combinatoric groups.
    # Shared organization is not hard-capped because it is materially stronger;
    # the independent global pair budget still protects the runtime.
    weak_group_caps = {
        "same_area_code": 40,
        "same_city": 80,
        "same_zip": 120,
        "same_email_domain": 120,
    }

    with _connect() as conn:
        groups = _candidate_groups(conn)
        stop = False
        for (predicate, signal_value), parties in groups.items():
            unique_parties = sorted(set(parties))
            if len(unique_parties) < 2:
                continue

            cap = weak_group_caps.get(predicate)
            if cap is not None and len(unique_parties) > cap:
                groups_skipped += 1
                continue

            groups_examined += 1
            for left, right in combinations(unique_parties, 2):
                pair = (*_pair_key(left, right), predicate)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                pairs_examined += 1

                if conn.execute(
                    """
                    SELECT 1 FROM relationship_rejection
                    WHERE ((from_party=? AND to_party=?) OR (from_party=? AND to_party=?))
                      AND (predicate=? OR predicate IS NULL)
                    LIMIT 1
                    """,
                    (left, right, right, left, predicate),
                ).fetchone():
                    if pairs_examined >= max_pairs:
                        stopped_reason = "max_pairs"
                        stop = True
                        break
                    continue

                if conn.execute(
                    """
                    SELECT 1 FROM relationship_edge
                    WHERE ((from_party=? AND to_party=?) OR (from_party=? AND to_party=?))
                      AND predicate=? AND state IN ('asserted','verified')
                    LIMIT 1
                    """,
                    (left, right, right, left, predicate),
                ).fetchone():
                    if pairs_examined >= max_pairs:
                        stopped_reason = "max_pairs"
                        stop = True
                        break
                    continue

                confidence = CANDIDATE_SIGNAL_WEIGHT[predicate]
                candidate_id = _stable_id("candidate", left, right, predicate, business_scope)
                rationale = (
                    f"Possible association detected from {predicate.replace('_', ' ')}: "
                    f"{signal_value}. This is not a verified relationship."
                )
                conn.execute(
                    """
                    INSERT INTO relationship_candidate(
                      candidate_id, from_party, to_party, predicate, confidence, rationale,
                      inference_run, review_state, business_scope, discovered_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                      confidence=MAX(relationship_candidate.confidence, excluded.confidence),
                      rationale=excluded.rationale,
                      inference_run=excluded.inference_run,
                      discovered_at=excluded.discovered_at,
                      expires_at=excluded.expires_at,
                      review_state=CASE WHEN relationship_candidate.review_state='rejected' THEN 'rejected' ELSE 'pending' END
                    """,
                    (
                        candidate_id,
                        left,
                        right,
                        predicate,
                        confidence,
                        rationale,
                        inference_run,
                        None if business_scope == "all" else business_scope,
                        now_dt.isoformat(),
                        expires,
                    ),
                )
                evidence_id = _stable_id("evidence", candidate_id, predicate, signal_value)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO evidence(
                      evidence_id, source_type, source_ref, business_scope, captured_at, details
                    ) VALUES (?, 'local_scan', ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        f"signal:{predicate}",
                        None if business_scope == "all" else business_scope,
                        now_dt.isoformat(),
                        json.dumps({"predicate": predicate, "signal": signal_value}),
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO relationship_candidate_evidence(candidate_id, evidence_id) VALUES (?, ?)",
                    (candidate_id, evidence_id),
                )
                written += 1

                if written >= max_new:
                    stopped_reason = "max_new"
                    stop = True
                    break
                if pairs_examined >= max_pairs:
                    stopped_reason = "max_pairs"
                    stop = True
                    break

            if stop:
                break

        conn.commit()

    return {
        "status": "success",
        "candidates_scanned": pairs_examined,
        "candidates_written": written,
        "groups_examined": groups_examined,
        "groups_skipped": groups_skipped,
        "max_new": max_new,
        "max_pairs": max_pairs,
        "stopped_reason": stopped_reason,
        "inference_run": inference_run,
        "note": "Candidate evidence is never promoted to a verified relationship without review.",
    }
