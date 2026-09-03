"""
generate_test_invoices.py
--------------------------
Generates realistic-looking invoice PDFs into test_data/invoices/ so the
process has real inputs to run against. Covers the happy path plus 5
deliberately chosen edge cases (guide asks for 2-4; the vendor-approval
case is a bonus beyond the minimum).

Run: python3 generate_test_invoices.py
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(os.path.dirname(__file__), "test_data", "invoices")
os.makedirs(OUT_DIR, exist_ok=True)


def make_invoice(filename, vendor_name, invoice_number, invoice_date, po_number,
                  line_items, subtotal, tax, total, omit_fields=None):
    """line_items: list of (description, amount). omit_fields: list of field
    names to leave off the PDF entirely, to simulate missing-data invoices."""
    omit_fields = omit_fields or []
    path = os.path.join(OUT_DIR, filename)
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    y = height - 60

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, vendor_name)
    y -= 30

    c.setFont("Helvetica", 10)
    if "invoice_number" not in omit_fields:
        c.drawString(50, y, f"Invoice Number: {invoice_number}")
        y -= 16
    if "invoice_date" not in omit_fields:
        c.drawString(50, y, f"Invoice Date: {invoice_date}")
        y -= 16
    if "po_number" not in omit_fields and po_number:
        c.drawString(50, y, f"PO Number: {po_number}")
        y -= 16

    y -= 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Description")
    c.drawString(400, y, "Amount")
    y -= 6
    c.line(50, y, 500, y)
    y -= 16

    c.setFont("Helvetica", 10)
    for desc, amt in line_items:
        c.drawString(50, y, desc)
        c.drawString(400, y, f"${amt:,.2f}")
        y -= 16

    y -= 10
    c.line(300, y, 500, y)
    y -= 16
    if subtotal is not None:
        c.drawString(300, y, f"Subtotal: ${subtotal:,.2f}")
        y -= 16
    if tax is not None:
        c.drawString(300, y, f"Tax: ${tax:,.2f}")
        y -= 16
    c.setFont("Helvetica-Bold", 11)
    c.drawString(300, y, f"Total Due: ${total:,.2f}")

    c.save()
    print(f"  wrote {filename}")


print("Generating test invoices into test_data/invoices/ ...")

# 1. HAPPY PATH — clean invoice, matches PO-1001 exactly within tolerance
make_invoice(
    "01_happy_path_acme.pdf",
    vendor_name="Acme Office Supplies",
    invoice_number="ACM-9001",
    invoice_date="2026-08-01",
    po_number="PO-1001",
    line_items=[("Printer paper (50 reams)", 350.00),
                ("Desk organizers (30 units)", 450.00),
                ("Office chairs (2 units)", 400.00)],
    subtotal=1200.00, tax=0.00, total=1200.00,
)

# 2. EDGE CASE — amount mismatch beyond tolerance
make_invoice(
    "02_edge_amount_mismatch_northwind.pdf",
    vendor_name="Northwind Logistics",
    invoice_number="NW-4471",
    invoice_date="2026-08-03",
    po_number="PO-1002",
    line_items=[("Freight - August shipments", 5000.00),
                ("Fuel surcharge", 1200.00)],
    subtotal=6200.00, tax=0.00, total=6200.00,  # PO-1002 is only $4800
)

# 3. EDGE CASE — missing critical fields (no invoice number, no date)
make_invoice(
    "03_edge_missing_fields_bluepeak.pdf",
    vendor_name="Bluepeak Consulting",
    invoice_number="[MISSING]",
    invoice_date="[MISSING]",
    po_number="PO-1003",
    line_items=[("Q3 strategy engagement - phase 1", 15000.00)],
    subtotal=15000.00, tax=0.00, total=15000.00,
    omit_fields=["invoice_number", "invoice_date"],
)

# 4. EDGE CASE — duplicate submission (same vendor + invoice number as #1)
make_invoice(
    "04_edge_duplicate_acme.pdf",
    vendor_name="Acme Office Supplies",
    invoice_number="ACM-9001",   # same as happy path -> triggers duplicate check
    invoice_date="2026-08-01",
    po_number="PO-1001",
    line_items=[("Printer paper (50 reams)", 350.00),
                ("Desk organizers (30 units)", 450.00),
                ("Office chairs (2 units)", 400.00)],
    subtotal=1200.00, tax=0.00, total=1200.00,
)

# 5a/5b. EDGE CASE — PO split across two invoices (Ridgeline, PO-1006, $6000 total)
make_invoice(
    "05a_edge_split_po_ridgeline_part1.pdf",
    vendor_name="Ridgeline IT Services",
    invoice_number="RIS-2201",
    invoice_date="2026-08-05",
    po_number="PO-1006",
    line_items=[("Managed IT support - August (weeks 1-2)", 3000.00)],
    subtotal=3000.00, tax=0.00, total=3000.00,
)
make_invoice(
    "05b_edge_split_po_ridgeline_part2.pdf",
    vendor_name="Ridgeline IT Services",
    invoice_number="RIS-2202",
    invoice_date="2026-08-19",
    po_number="PO-1006",
    line_items=[("Managed IT support - August (weeks 3-4)", 3000.00)],
    subtotal=3000.00, tax=0.00, total=3000.00,
)

# 6. EDGE CASE (bonus) — unapproved vendor
make_invoice(
    "06_edge_unapproved_vendor_fenwick.pdf",
    vendor_name="Fenwick Marketing Group",
    invoice_number="FMG-0099",
    invoice_date="2026-08-10",
    po_number="PO-1007",
    line_items=[("Q3 campaign creative", 2500.00)],
    subtotal=2500.00, tax=0.00, total=2500.00,
)

print("Done. See test_data/invoices/")
