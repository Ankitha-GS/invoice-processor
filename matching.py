"""
matching.py
-----------
Matches an extracted invoice to a purchase order from the PO dataset (CSV).

Matching strategy (in priority order):
  1. Explicit PO number on the invoice -> direct lookup.
  2. No PO number given -> fall back to vendor-name + amount proximity
     matching against that vendor's open POs (handles vendors who forget to
     reference the PO, or reference it ambiguously in free text).

Also tracks running "remaining balance" per PO in-memory via the caller
(storage.py persists it), so that a PO can be legitimately split across
multiple invoices (edge case: split billing).
"""

import csv


def load_po_dataset(csv_path: str) -> dict:
    """Returns {po_number: {vendor_name, po_amount, ...}}"""
    pos = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pos[row["po_number"]] = {
                "po_number": row["po_number"],
                "vendor_name": row["vendor_name"],
                "po_amount": float(row["po_amount"]),
                "approved_vendor": row["approved_vendor"].strip().lower() == "true",
            }
    return pos


def find_match(extracted: dict, po_dataset: dict, remaining_balances: dict) -> dict:
    """
    remaining_balances: {po_number: float} - current remaining balance,
    maintained by storage.py across runs (starts equal to po_amount).
    Returns a match_result dict or None.
    """
    po_number = (extracted.get("po_number") or "").strip()

    # Strategy 1: explicit PO number
    if po_number and po_number in po_dataset:
        po = po_dataset[po_number]
        return {
            "po_number": po_number,
            "po_amount": po["po_amount"],
            "po_remaining_balance": remaining_balances.get(po_number, po["po_amount"]),
            "match_method": "explicit_po_number",
            "confidence": "high",
        }

    # Strategy 2: vendor + amount proximity (no/garbled PO reference)
    vendor = (extracted.get("vendor_name") or "").strip().lower()
    invoice_total = extracted.get("total")
    candidates = []
    for pno, po in po_dataset.items():
        if vendor and vendor in po["vendor_name"].strip().lower():
            remaining = remaining_balances.get(pno, po["po_amount"])
            if remaining <= 0:
                continue
            if invoice_total:
                closeness = abs(remaining - invoice_total)
                candidates.append((closeness, pno, po, remaining))

    if candidates:
        candidates.sort(key=lambda c: c[0])
        _, pno, po, remaining = candidates[0]
        return {
            "po_number": pno,
            "po_amount": po["po_amount"],
            "po_remaining_balance": remaining,
            "match_method": "vendor_and_amount_proximity",
            "confidence": "medium",
        }

    return None


def is_vendor_approved(vendor_name: str, po_dataset: dict) -> bool:
    if not vendor_name:
        return False
    vendor_lower = vendor_name.strip().lower()
    for po in po_dataset.values():
        if vendor_lower in po["vendor_name"].strip().lower():
            return po["approved_vendor"]
    return False
