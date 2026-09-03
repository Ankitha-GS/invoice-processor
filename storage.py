"""
storage.py
----------
Tiny SQLite persistence layer. Two tables:
  runs             - one row per invoice processed (for the dashboard)
  po_balances      - remaining balance per PO (so split invoices work across runs)

Kept deliberately simple (no ORM) since the case study cares about the
process logic, not the persistence layer.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "app.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(po_dataset: dict = None):
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            vendor_name TEXT,
            invoice_number TEXT,
            total REAL,
            status TEXT,
            reason_code TEXT,
            po_number TEXT,
            extracted_json TEXT,
            stages_json TEXT,
            processed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS po_balances (
            po_number TEXT PRIMARY KEY,
            remaining_balance REAL
        )
    """)
    conn.commit()

    if po_dataset:
        for pno, po in po_dataset.items():
            conn.execute(
                "INSERT OR IGNORE INTO po_balances (po_number, remaining_balance) VALUES (?, ?)",
                (pno, po["po_amount"])
            )
    conn.commit()
    conn.close()


def get_remaining_balances() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT po_number, remaining_balance FROM po_balances").fetchall()
    conn.close()
    return {r["po_number"]: r["remaining_balance"] for r in rows}


def update_po_balance(po_number: str, new_balance: float):
    conn = get_conn()
    conn.execute(
        "UPDATE po_balances SET remaining_balance = ? WHERE po_number = ?",
        (new_balance, po_number)
    )
    conn.commit()
    conn.close()


def find_duplicate(vendor_name: str, invoice_number: str):
    if not vendor_name or not invoice_number:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM runs WHERE vendor_name = ? AND invoice_number = ? ORDER BY id LIMIT 1",
        (vendor_name, invoice_number)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_run(filename, extracted, stages, final_status, reason_code, po_number):
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO runs (filename, vendor_name, invoice_number, total, status,
                           reason_code, po_number, extracted_json, stages_json, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        filename,
        extracted.get("vendor_name"),
        extracted.get("invoice_number"),
        extracted.get("total"),
        final_status,
        reason_code,
        po_number,
        json.dumps(extracted),
        json.dumps(stages),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def list_runs():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run(run_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def reset_all():
    """Wipes runs + resets PO balances to original amounts. Useful for demo prep."""
    conn = get_conn()
    conn.execute("DELETE FROM runs")
    conn.commit()
    conn.close()
