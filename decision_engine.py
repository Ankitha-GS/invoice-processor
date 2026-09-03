"""
decision_engine.py
------------------
Pure business-rule logic for turning an extracted invoice + matched PO
into a decision. No I/O, no side effects on the DB — takes data in,
returns a decision + reasoning trail out. This makes it easy to unit
test and easy to explain in the interview.

Decision statuses:
  APPROVED      -> safe to pay
  NEEDS_REVIEW  -> a human must look at it (ambiguous, mismatched, no PO)
  REJECTED      -> should not be paid as-is (duplicate, unapproved vendor)
"""

from dataclasses import dataclass, field
from typing import Optional

# ---- Configurable business rules -------------------------------------------------
AMOUNT_TOLERANCE_PCT = 0.02      # 2% variance allowed between invoice and PO
AMOUNT_TOLERANCE_ABS = 25.00     # or $25, whichever is more forgiving
REQUIRED_FIELDS = ["vendor_name", "invoice_number", "total"]


@dataclass
class StageResult:
    stage: str
    status: str          # "ok" | "warning" | "fail"
    detail: str
    data: dict = field(default_factory=dict)


def _within_tolerance(invoice_total: float, po_amount: float) -> bool:
    diff = abs(invoice_total - po_amount)
    pct_ok = diff <= po_amount * AMOUNT_TOLERANCE_PCT
    abs_ok = diff <= AMOUNT_TOLERANCE_ABS
    return pct_ok or abs_ok


def run_decision_pipeline(extracted: dict, match_result: dict, duplicate_hit: Optional[dict],
                           vendor_approved: bool) -> list:
    """
    Runs each business-rule stage in order and returns a list of StageResult.
    The LAST stage's `data['final_status']` is the overall decision.
    Stages run even after a "fail" is hit further down, EXCEPT we stop early
    on a duplicate (no point matching/pricing a duplicate invoice).
    """
    stages = []

    # --- Stage: required fields present? ---
    missing = [f for f in REQUIRED_FIELDS if not extracted.get(f)]
    if missing:
        stages.append(StageResult(
            stage="Field Completeness Check",
            status="fail",
            detail=f"Missing required field(s): {', '.join(missing)}. "
                    "Cannot safely process without these.",
            data={"missing_fields": missing}
        ))
        stages.append(StageResult(
            stage="Decision",
            status="warning",
            detail="Routed to NEEDS_REVIEW: incomplete extraction. "
                    "A human needs to confirm the missing fields, likely by "
                    "checking the original PDF or contacting the vendor.",
            data={"final_status": "NEEDS_REVIEW", "reason_code": "MISSING_FIELDS"}
        ))
        return stages
    else:
        stages.append(StageResult(
            stage="Field Completeness Check",
            status="ok",
            detail="All required fields present (vendor, invoice number, total).",
        ))

    # --- Stage: duplicate detection ---
    if duplicate_hit:
        stages.append(StageResult(
            stage="Duplicate Detection",
            status="fail",
            detail=(f"Invoice #{extracted.get('invoice_number')} from "
                     f"{extracted.get('vendor_name')} was already processed on "
                     f"{duplicate_hit.get('processed_at', 'a previous run')} "
                     f"(run #{duplicate_hit.get('id')}, status "
                     f"{duplicate_hit.get('status')})."),
            data={"duplicate_run_id": duplicate_hit.get("id")}
        ))
        stages.append(StageResult(
            stage="Decision",
            status="fail",
            detail="Routed to REJECTED: this looks like a duplicate submission. "
                    "Paying it again would be a double payment. Flag to AP lead "
                    "before any further action.",
            data={"final_status": "REJECTED", "reason_code": "DUPLICATE_INVOICE"}
        ))
        return stages
    else:
        stages.append(StageResult(
            stage="Duplicate Detection",
            status="ok",
            detail="No prior invoice found with this vendor + invoice number.",
        ))

    # --- Stage: vendor approval ---
    if not vendor_approved:
        stages.append(StageResult(
            stage="Vendor Approval Check",
            status="fail",
            detail=f"'{extracted.get('vendor_name')}' is not on the approved vendor list.",
        ))
        stages.append(StageResult(
            stage="Decision",
            status="fail",
            detail="Routed to REJECTED: unapproved vendor. Procurement must "
                    "onboard this vendor (see vendor onboarding process) before "
                    "any invoice from them can be paid.",
            data={"final_status": "REJECTED", "reason_code": "UNAPPROVED_VENDOR"}
        ))
        return stages
    else:
        stages.append(StageResult(
            stage="Vendor Approval Check",
            status="ok",
            detail=f"'{extracted.get('vendor_name')}' is an approved vendor.",
        ))

    # --- Stage: PO match ---
    if not match_result or not match_result.get("po_number"):
        stages.append(StageResult(
            stage="Purchase Order Match",
            status="fail",
            detail="No matching purchase order could be found (checked explicit "
                    "PO reference on the invoice, then fell back to vendor + "
                    "amount proximity matching).",
        ))
        stages.append(StageResult(
            stage="Decision",
            status="warning",
            detail="Routed to NEEDS_REVIEW: cannot validate spend without a PO. "
                    "AP should confirm whether this is a valid non-PO expense "
                    "or a missing PO reference.",
            data={"final_status": "NEEDS_REVIEW", "reason_code": "NO_PO_MATCH"}
        ))
        return stages

    stages.append(StageResult(
        stage="Purchase Order Match",
        status="ok",
        detail=(f"Matched to PO {match_result['po_number']} "
                 f"(method: {match_result['match_method']}, "
                 f"confidence: {match_result['confidence']})."),
        data=match_result
    ))

    # --- Stage: amount validation against remaining PO balance ---
    invoice_total = extracted["total"]
    po_remaining = match_result["po_remaining_balance"]
    po_original = match_result["po_amount"]

    if invoice_total <= po_remaining and not _within_tolerance(invoice_total, po_remaining):
        # Clearly under budget and not just "close" -> treat as a legitimate
        # partial / split invoice against the PO (edge case: PO split across
        # multiple invoices).
        stages.append(StageResult(
            stage="Amount Validation",
            status="ok",
            detail=(f"Invoice total (${invoice_total:,.2f}) is within the PO's "
                     f"remaining balance (${po_remaining:,.2f} of "
                     f"${po_original:,.2f}). Treating as a partial / split "
                     f"invoice against this PO."),
            data={"is_partial": True, "new_remaining_balance": po_remaining - invoice_total}
        ))
        stages.append(StageResult(
            stage="Decision",
            status="ok",
            detail=(f"Routed to APPROVED (partial). ${invoice_total:,.2f} approved "
                     f"against PO {match_result['po_number']}; "
                     f"${po_remaining - invoice_total:,.2f} remains available on "
                     f"this PO for future invoices."),
            data={"final_status": "APPROVED", "reason_code": "APPROVED_PARTIAL",
                  "new_remaining_balance": po_remaining - invoice_total}
        ))
        return stages

    if _within_tolerance(invoice_total, po_remaining):
        stages.append(StageResult(
            stage="Amount Validation",
            status="ok",
            detail=(f"Invoice total (${invoice_total:,.2f}) matches PO remaining "
                     f"balance (${po_remaining:,.2f}) within tolerance "
                     f"(±{AMOUNT_TOLERANCE_PCT*100:.0f}% or ${AMOUNT_TOLERANCE_ABS:.0f})."),
        ))
        stages.append(StageResult(
            stage="Decision",
            status="ok",
            detail=f"Routed to APPROVED. Amounts reconcile within tolerance.",
            data={"final_status": "APPROVED", "reason_code": "APPROVED_MATCH",
                  "new_remaining_balance": 0.0}
        ))
        return stages

    # over budget / mismatch beyond tolerance
    diff = invoice_total - po_remaining
    stages.append(StageResult(
        stage="Amount Validation",
        status="fail",
        detail=(f"Invoice total (${invoice_total:,.2f}) exceeds PO remaining "
                 f"balance (${po_remaining:,.2f}) by ${diff:,.2f}, outside "
                 f"tolerance."),
    ))
    stages.append(StageResult(
        stage="Decision",
        status="warning",
        detail=(f"Routed to NEEDS_REVIEW: amount mismatch of ${diff:,.2f} beyond "
                 f"tolerance. AP should confirm whether the PO needs a change "
                 f"order or the invoice has an error."),
        data={"final_status": "NEEDS_REVIEW", "reason_code": "AMOUNT_MISMATCH"}
    ))
    return stages
