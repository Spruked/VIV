from __future__ import annotations

import csv
import io
from typing import Any, Dict

from fastapi import APIRouter, Depends, Response

from cali_skg.api.csv_contact_io_routes import CsvImportRequest, import_csv_contacts
from cali_skg.api.relationship_routes import verify_admin

router = APIRouter(prefix="/cali/intelligence/dossiers", tags=["cali-dossier-templates"])

CSV_TEMPLATE_FIELDS = [
    "Name",
    "Relationship Type",
    "Email",
    "Email 2",
    "Phone",
    "Phone 2",
    "Address",
    "Organization",
    "Role or Job Title",
    "Notes",
    "Priority",
    "Lifecycle ID",
    "Source",
    "Owner",
    "Next Follow Up At",
    "VIV Business Context",
    "VIV Relationship",
    "Group or Segment",
]

CSV_HEADER_MAP = {
    "Relationship Type": "Type",
    "Role or Job Title": "Job Title",
    "Lifecycle ID": "CRM Stage",
    "VIV Business Context": "VIV Business Scope",
    "Group or Segment": "Segment Tags",
}

LIFECYCLE_LABEL_TO_ID = {
    "horizon": "prospect",
    "evaluating": "qualified",
    "engaged": "contacted",
    "active": "meeting_scheduled",
    "advancing": "proposal",
    "established": "won",
    "archive": "lost",
}


def _normalize_viv_csv(content: str) -> str:
    source = str(content or "").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(source))
    if not reader.fieldnames:
        return source

    fieldnames = [CSV_HEADER_MAP.get(str(name or "").strip(), str(name or "").strip()) for name in reader.fieldnames]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()

    for raw in reader:
        mapped: Dict[str, Any] = {}
        for key, value in raw.items():
            normalized_key = CSV_HEADER_MAP.get(str(key or "").strip(), str(key or "").strip())
            mapped[normalized_key] = value

        lifecycle = str(mapped.get("CRM Stage") or "").strip()
        if lifecycle:
            mapped["CRM Stage"] = LIFECYCLE_LABEL_TO_ID.get(lifecycle.lower(), lifecycle)
        else:
            mapped["CRM Stage"] = "prospect"
        writer.writerow(mapped)

    return output.getvalue()


@router.post("/import/csv")
def import_viv_csv(payload: CsvImportRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    normalized = _normalize_viv_csv(payload.content)
    return import_csv_contacts(
        CsvImportRequest(
            content=normalized,
            business_scope=payload.business_scope,
            run_relationship_scan=payload.run_relationship_scan,
        ),
        _="internal-viv-dossier-import",
    )


@router.get("/templates/csv")
def csv_template(_: str = Depends(verify_admin)) -> Response:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(CSV_TEMPLATE_FIELDS)
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="viv-dossier-template.csv"'},
    )


@router.get("/templates/vcf")
def vcf_template(_: str = Depends(verify_admin)) -> Response:
    content = "\r\n".join(
        [
            "BEGIN:VCARD",
            "VERSION:4.0",
            "UID:replace-with-stable-id",
            "FN:Replace With Full Name",
            "EMAIL;TYPE=work:person@example.com",
            "TEL;TYPE=cell:+1-555-555-0100",
            "ADR;TYPE=home:;;Street Address;City;State;Postal Code;Country",
            "ORG:Organization Name",
            "TITLE:Role or Job Title",
            "NOTE:Notes and verified context belong here.",
            "X-VIV-BUSINESS-CONTEXT:personal",
            "X-VIV-RELATIONSHIP:professional",
            "X-VIV-SEGMENT:example-group",
            "REV:20260825T000000Z",
            "END:VCARD",
            "",
        ]
    )
    return Response(
        content=content,
        media_type="text/vcard; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="viv-dossier-template.vcf"'},
    )


@router.get("/templates/schema")
def template_schema(_: str = Depends(verify_admin)) -> Dict[str, object]:
    return {
        "csv_fields": CSV_TEMPLATE_FIELDS,
        "vcf_extensions": [
            "X-VIV-BUSINESS-CONTEXT",
            "X-VIV-RELATIONSHIP",
            "X-VIV-SEGMENT",
        ],
        "lifecycle_ids": {
            "prospect": "Horizon",
            "qualified": "Evaluating",
            "contacted": "Engaged",
            "meeting_scheduled": "Active",
            "proposal": "Advancing",
            "won": "Established",
            "lost": "Archive",
        },
        "notes": [
            "Lifecycle ID accepts either the stable transport ID or the VIV display label. Blank lifecycle values default to Horizon.",
            "Messages remain communications. Signal is reserved for information promoted as relevant intelligence.",
        ],
    }
