# Ledger — Invoice Processing (PS-1)

An automated process that takes a vendor invoice PDF, extracts the relevant
fields, matches it against a purchase order, applies AP business rules, and
produces a clear APPROVED / NEEDS_REVIEW / REJECTED decision with a full
reasoning trail — visible in a live run view and a persistent dashboard.

## 1. Setup

Requires Python 3.10+.

```bash
cd invoice-processor
pip install -r requirements.txt --break-system-packages   # or use a venv
python3 generate_test_invoices.py                          # builds the 7 test PDFs
python3 app.py                                              # starts the server
```

Open **http://localhost:5000**.

Optional: to enable LLM-based extraction (more robust to messy vendor
formatting than the regex fallback), set an API key before starting:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 app.py
```

Without a key, the process still runs completely — it falls back to a
deterministic regex extractor. This was a deliberate design choice (see
"Design decisions" below).

## 2. How to use it

- **Intake tab** — drop any invoice PDF, or click one of the 7 prepared test
  cases to run it instantly. Each run streams a stage-by-stage log (Ingest →
  Extraction → Duplicate Detection → Vendor Approval → PO Match → Amount
  Validation → Decision) and ends with a clear decision banner.
- **Ledger book tab** — every run ever processed, most recent first. Click a
  row to see the full extracted data and reasoning trail for that run. Also
  shows live PO remaining-balance tracking.
- **Reset history** button on the dashboard wipes runs and restores PO
  balances to their original amounts — use this right before a live demo so
  you start from a clean slate.

## 3. Architecture

```
PDF invoice
    │
    ▼
extraction.py     -> pulls vendor, invoice #, date, PO #, totals, line items
                      (LLM extraction if ANTHROPIC_API_KEY set, else regex)
    │
    ▼
matching.py        -> finds the PO: explicit PO # first, then vendor + amount
                       proximity if no PO # was given or it doesn't exist
    │
    ▼
decision_engine.py -> pure business-rule pipeline:
                       field completeness -> duplicate check -> vendor
                       approval -> PO match -> amount tolerance check
    │
    ▼
storage.py          -> SQLite: run history + per-PO remaining balance
    │
    ▼
app.py               -> Flask orchestration + REST API
    │
    ▼
templates/ + static/ -> single-page frontend, live run view + dashboard
```

Each layer only does one job and takes plain data in/out — `decision_engine.py`
has no I/O at all, which made it easy to test each rule (see "Testing" below)
without spinning up the server or touching a file.

## 4. Business rules (what "the process" actually decides)

1. **Field completeness** — vendor name, invoice number, and total must be
   present. Missing any of them routes to `NEEDS_REVIEW` immediately; nothing
   downstream can be trusted without these.
2. **Duplicate detection** — same vendor + same invoice number already
   processed → `REJECTED`. Prevents double payment.
3. **Vendor approval** — invoice must be from a vendor on the approved list →
   otherwise `REJECTED` and routed toward vendor onboarding.
4. **PO match** — explicit PO number on the invoice is tried first; if
   missing or invalid, falls back to matching by vendor name + closest
   remaining PO balance. No match → `NEEDS_REVIEW`.
5. **Amount validation** — invoice total is compared to the PO's *remaining*
   balance (not the original PO amount — see split-PO handling below), with
   a tolerance of 2% or $25, whichever is more forgiving:
   - Within tolerance → `APPROVED`
   - Meaningfully under the remaining balance → `APPROVED` as a **partial
     invoice**, and the PO's remaining balance is reduced accordingly (this
     is what makes split billing across multiple invoices work correctly)
   - Over the remaining balance beyond tolerance → `NEEDS_REVIEW`

## 5. Edge cases (5 built, guide asked for 2–4)

| # | Test file | What it exercises | Expected result |
|---|---|---|---|
| 1 | `02_edge_amount_mismatch_northwind.pdf` | Invoice total far exceeds the PO | `NEEDS_REVIEW` — `AMOUNT_MISMATCH` |
| 2 | `03_edge_missing_fields_bluepeak.pdf` | Invoice # and date missing from the PDF | `NEEDS_REVIEW` — `MISSING_FIELDS` |
| 3 | `04_edge_duplicate_acme.pdf` | Identical invoice # to a previously processed invoice | `REJECTED` — `DUPLICATE_INVOICE` |
| 4 | `05a` + `05b` (Ridgeline, PO-1006) | A single PO legitimately split across two invoices | Both `APPROVED`; PO balance drains $6000 → $3000 → $0 |
| 5 (bonus) | `06_edge_unapproved_vendor_fenwick.pdf` | Invoice from a vendor not on the approved list | `REJECTED` — `UNAPPROVED_VENDOR` |

Run `04` *after* `01` (the happy path) for the duplicate check to trigger —
the dashboard needs to see the first one in history first. The Intake tab's
sample buttons are in the right order for this already.

## 6. Design decisions worth explaining in the interview

- **Regex fallback + optional LLM extraction, not LLM-only.** A live demo
  can't depend on an external API being up or a key being configured
  correctly in the moment. The regex extractor is deliberately conservative
  — it returns `None` rather than guessing wrong, which is what feeds the
  "missing fields" edge case. LLM extraction is available as a strict
  upgrade when a key is present, since it should handle vendor formatting
  variance far better in production.
- **Remaining-balance PO matching instead of one-shot PO consumption.** Real
  vendors split billing across a PO. Tracking remaining balance in
  `po_balances` (rather than marking a PO "used" after one invoice) is what
  makes the split-PO edge case behave correctly instead of falsely flagging
  the second invoice as a mismatch.
- **Decision pipeline stops early on duplicates/unapproved vendors** rather
  than running the (irrelevant) PO-matching and amount-checking stages
  afterward — cheaper, and the reasoning trail reads cleaner because it
  doesn't show irrelevant checks after a hard stop.
- **Flask + vanilla JS instead of a React build**, even though React was on
  the table. For a process that has to run live and reliably during an
  interview, removing a build step (npm install / webpack) removes a
  failure mode. The frontend still gets the required live run view and
  dashboard; it just doesn't need a bundler to do it.

## 7. What I'd build next with more time

- OCR fallback (`pytesseract`) for scanned/image invoices — right now the
  extractor assumes a text-layer PDF.
- Confidence scoring surfaced per extracted field, not just per PO match, so
  a human reviewer knows exactly which field to double-check.
- A "resolve" action in the dashboard so a human can act on a
  `NEEDS_REVIEW` invoice (approve/reject with a note) rather than just view it.

## 8. Testing

```bash
# quick sanity check of extraction against the generated PDFs
python3 -c "
import extraction
d = extraction.extract_invoice('test_data/invoices/01_happy_path_acme.pdf')
print(d)
"

# full pipeline test via the API once the server is running
curl -X POST http://localhost:5000/api/process-sample \
  -H "Content-Type: application/json" \
  -d '{"filename": "01_happy_path_acme.pdf"}'
```

## 9. Demo video script (5 minutes)

1. **(30s)** One-sentence framing: what the process does and why it matters
   (AP team drowning in manual PDF-to-decision work).
2. **(90s)** Happy path: run `01_happy_path_acme.pdf` live, narrate each
   stage as it appears, land on `APPROVED`.
3. **(2 min)** Run 2–3 edge cases back to back: amount mismatch, missing
   fields, duplicate. For each, say in one sentence *why* it's a real
   scenario and what the process did differently.
4. **(45s)** Split-PO case: show the PO balance draining across two
   invoices in the Ledger book tab — this is the one that best shows
   deliberate design, not just "PDF parsing."
5. **(15s)** Close: what you'd build next, in one sentence.
