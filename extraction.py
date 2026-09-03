"""
extraction.py
-------------
Turns a raw invoice PDF into a structured dict.

Two extraction backends, chosen automatically:
  1. LLM extraction (Claude) if ANTHROPIC_API_KEY is set in the environment.
     This handles messy/inconsistent vendor formatting far better than regex.
  2. Deterministic regex/heuristic extraction as a fallback (and so the whole
     process still runs end-to-end with zero API keys / zero cost for the demo).

This mirrors a real design decision you'd have to defend in the interview:
LLM extraction is more robust to vendor formatting variance, but regex is
free, fast, and has no external dependency risk during a live demo. Shipping
both, with automatic fallback, is deliberately the "grown-up" answer.
"""

import os
import re
import json
import pdfplumber

REQUIRED_KEYS = [
    "vendor_name", "invoice_number", "invoice_date", "po_number",
    "subtotal", "tax", "total", "line_items"
]


def extract_text(pdf_path: str) -> str:
    text_chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_chunks.append(t)
    return "\n".join(text_chunks)


def _empty_result():
    return {k: None for k in REQUIRED_KEYS}


def extract_with_regex(text: str) -> dict:
    """Deterministic fallback extractor. Good enough for structured/semi-structured
    invoices; deliberately conservative — returns None rather than guessing wrong."""
    result = _empty_result()

    def find(pattern, group=1, flags=re.IGNORECASE):
        m = re.search(pattern, text, flags)
        return m.group(group).strip() if m else None

    result["invoice_number"] = find(r"invoice\s*(?:#|no\.?|number)?\s*[:\-]?\s*([A-Z0-9\-]+)")
    result["po_number"] = find(r"\bP\.?O\.?\s*(?:#|no\.?|number)?\s*[:\-]?\s*([A-Z0-9\-]+)")
    result["invoice_date"] = find(r"(?:invoice\s*date|date)\s*[:\-]?\s*([A-Za-z0-9,\/\- ]{6,20})")

    vendor_match = re.search(r"^(.*?)\n", text.strip())
    result["vendor_name"] = vendor_match.group(1).strip() if vendor_match else None

    def money(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return None
        val = m.group(1).replace(",", "").replace("$", "")
        try:
            return float(val)
        except ValueError:
            return None

    result["subtotal"] = money(r"subtotal\s*[:\-]?\s*\$?([\d,]+\.\d{2})")
    result["tax"] = money(r"tax\s*[:\-]?\s*\$?([\d,]+\.\d{2})")
    result["total"] = money(r"total\s*(?:due|amount)?\s*[:\-]?\s*\$?([\d,]+\.\d{2})")

    # crude line item capture: "description ... $amount" lines
    line_items = []
    for line in text.split("\n"):
        m = re.match(r"^(.{5,60}?)\s+\$?([\d,]+\.\d{2})\s*$", line.strip())
        if m and "total" not in m.group(1).lower() and "tax" not in m.group(1).lower():
            line_items.append({"description": m.group(1).strip(),
                                "amount": float(m.group(2).replace(",", ""))})
    result["line_items"] = line_items
    return result


def extract_with_llm(text: str) -> dict:
    """Uses Claude to extract structured fields from messy invoice text.
    Only called if ANTHROPIC_API_KEY is present."""
    import anthropic
    client = anthropic.Anthropic()

    prompt = f"""Extract the following fields from this invoice text as JSON only
(no markdown, no preamble). Use null for anything not present/unclear.

Fields: vendor_name (string), invoice_number (string), invoice_date (string),
po_number (string or null), subtotal (number or null), tax (number or null),
total (number), line_items (array of {{description, amount}}).

Invoice text:
---
{text}
---

Return ONLY the JSON object."""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    raw = raw.strip().strip("`")
    if raw.startswith("json"):
        raw = raw[4:].strip()
    return json.loads(raw)


def extract_invoice(pdf_path: str) -> dict:
    text = extract_text(pdf_path)
    backend = "regex"
    data = extract_with_regex(text)

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            llm_data = extract_with_llm(text)
            # only trust LLM output if it found a total; else keep regex result
            if llm_data.get("total"):
                data = {**_empty_result(), **llm_data}
                backend = "llm"
        except Exception:
            pass  # silently fall back to regex result — demo must not crash

    data["_extraction_backend"] = backend
    data["_raw_text_preview"] = text[:400]
    return data
