"""
app.py
------
Flask backend. Endpoints:

  GET  /                         -> serves the frontend
  POST /api/process              -> upload + run an invoice through the full pipeline
  GET  /api/runs                 -> dashboard: list of past runs
  GET  /api/runs/<id>            -> full detail (extraction + stage-by-stage reasoning) for one run
  GET  /api/po-balances          -> current PO balances (for transparency in the UI)
  POST /api/reset                -> wipe run history (for demo prep)

Run stage-by-stage logic lives in extraction.py / matching.py / decision_engine.py.
This file's job is orchestration + persistence + HTTP only.
"""

import os
import uuid
from flask import Flask, request, jsonify, send_from_directory

import extraction
import matching
import decision_engine
import storage

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "instance", "uploads")
PO_DATASET_PATH = os.path.join(BASE_DIR, "test_data", "po_dataset.csv")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")

# Load PO dataset once at startup
PO_DATASET = matching.load_po_dataset(PO_DATASET_PATH)
storage.init_db(PO_DATASET)


@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


def run_pipeline(save_path: str, original_filename: str) -> dict:
    """Core orchestration: extraction -> matching -> decision -> persistence.
    Shared by both the manual-upload route and the prepared-sample route so
    there's exactly one code path for 'what happens to an invoice'."""
    run_log = []  # stage-by-stage log for the live run view

    # --- Stage 1: Ingest ---
    run_log.append({"stage": "Ingest", "status": "ok",
                     "detail": f"Received '{original_filename}', saved for processing."})

    # --- Stage 2: Extraction ---
    try:
        extracted = extraction.extract_invoice(save_path)
        run_log.append({
            "stage": "Extraction",
            "status": "ok",
            "detail": (f"Extracted fields using '{extracted['_extraction_backend']}' backend. "
                        f"Vendor: {extracted.get('vendor_name')}, "
                        f"Invoice #: {extracted.get('invoice_number')}, "
                        f"Total: {extracted.get('total')}"),
            "data": extracted,
        })
    except Exception as e:
        run_log.append({"stage": "Extraction", "status": "fail",
                         "detail": f"Extraction failed: {e}"})
        return {"stages": run_log, "final_status": "NEEDS_REVIEW",
                "reason_code": "EXTRACTION_ERROR"}

    # --- Stage 3: Duplicate check (data lookup, logged separately from decision stages) ---
    duplicate_hit = storage.find_duplicate(extracted.get("vendor_name"), extracted.get("invoice_number"))

    # --- Stage 4: Vendor approval + PO match ---
    vendor_approved = matching.is_vendor_approved(extracted.get("vendor_name"), PO_DATASET)
    remaining_balances = storage.get_remaining_balances()
    match_result = matching.find_match(extracted, PO_DATASET, remaining_balances)

    # --- Stage 5+: Business rules / decision pipeline ---
    decision_stages = decision_engine.run_decision_pipeline(
        extracted, match_result, duplicate_hit, vendor_approved
    )
    for s in decision_stages:
        run_log.append({"stage": s.stage, "status": s.status, "detail": s.detail, "data": s.data})

    final = decision_stages[-1]
    final_status = final.data.get("final_status", "NEEDS_REVIEW")
    reason_code = final.data.get("reason_code", "UNKNOWN")

    # Persist any PO balance change (partial invoice / full match)
    if match_result and "new_remaining_balance" in final.data:
        storage.update_po_balance(match_result["po_number"], final.data["new_remaining_balance"])

    run_id = storage.save_run(
        filename=original_filename,
        extracted=extracted,
        stages=run_log,
        final_status=final_status,
        reason_code=reason_code,
        po_number=match_result["po_number"] if match_result else None,
    )

    return {
        "run_id": run_id,
        "stages": run_log,
        "final_status": final_status,
        "reason_code": reason_code,
    }


@app.route("/api/process", methods=["POST"])
def process_invoice():
    if "invoice" not in request.files:
        return jsonify({"error": "No file uploaded under field 'invoice'"}), 400

    file = request.files["invoice"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    file.save(save_path)

    result = run_pipeline(save_path, file.filename)
    return jsonify(result)


@app.route("/api/sample-invoices", methods=["GET"])
def list_sample_invoices():
    invoices_dir = os.path.join(BASE_DIR, "test_data", "invoices")
    files = sorted(f for f in os.listdir(invoices_dir) if f.endswith(".pdf"))
    return jsonify(files)


@app.route("/api/process-sample", methods=["POST"])
def process_sample():
    """Runs a prepared test-case PDF through the exact same pipeline as a
    manual upload, so the demo can trigger edge cases with one click."""
    body = request.get_json(force=True)
    filename = body.get("filename")
    invoices_dir = os.path.join(BASE_DIR, "test_data", "invoices")
    path = os.path.join(invoices_dir, filename or "")
    if not filename or not os.path.isfile(path):
        return jsonify({"error": "unknown sample file"}), 400

    result = run_pipeline(path, filename)
    return jsonify(result)


@app.route("/api/runs", methods=["GET"])
def get_runs():
    return jsonify(storage.list_runs())


@app.route("/api/runs/<int:run_id>", methods=["GET"])
def get_run_detail(run_id):
    run = storage.get_run(run_id)
    if not run:
        return jsonify({"error": "not found"}), 404
    return jsonify(run)


@app.route("/api/po-balances", methods=["GET"])
def get_po_balances():
    balances = storage.get_remaining_balances()
    out = []
    for pno, po in PO_DATASET.items():
        out.append({
            "po_number": pno,
            "vendor_name": po["vendor_name"],
            "po_amount": po["po_amount"],
            "remaining_balance": balances.get(pno, po["po_amount"]),
            "approved_vendor": po["approved_vendor"],
        })
    return jsonify(out)


@app.route("/api/reset", methods=["POST"])
def reset():
    storage.reset_all()
    # also reset PO balances back to full
    for pno, po in PO_DATASET.items():
        storage.update_po_balance(pno, po["po_amount"])
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
