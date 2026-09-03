// ---- tab switching ----
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.tab).classList.add("active");
    if (tab.dataset.tab === "dashboard") loadDashboard();
  });
});

// ---- sample invoices ----
const SAMPLE_LABELS = {
  "01_happy_path_acme.pdf": ["Happy path", "Acme Office Supplies — matches PO exactly"],
  "02_edge_amount_mismatch_northwind.pdf": ["Edge case", "Northwind — invoice exceeds PO by a lot"],
  "03_edge_missing_fields_bluepeak.pdf": ["Edge case", "Bluepeak — missing invoice # and date"],
  "04_edge_duplicate_acme.pdf": ["Edge case", "Acme — duplicate of the happy-path invoice"],
  "05a_edge_split_po_ridgeline_part1.pdf": ["Edge case", "Ridgeline — first half of a split PO"],
  "05b_edge_split_po_ridgeline_part2.pdf": ["Edge case", "Ridgeline — second half of a split PO"],
  "06_edge_unapproved_vendor_fenwick.pdf": ["Edge case", "Fenwick — vendor not yet approved"],
};

async function loadSamples() {
  const res = await fetch("/api/sample-invoices");
  const files = await res.json();
  const list = document.getElementById("sampleList");
  list.innerHTML = "";
  files.forEach(f => {
    const [tag, label] = SAMPLE_LABELS[f] || ["Sample", f];
    const el = document.createElement("div");
    el.className = "sample-item";
    el.innerHTML = `<span>${label}</span><span class="sample-tag">${tag}</span>`;
    el.addEventListener("click", () => runSample(f));
    list.appendChild(el);
  });
}

async function runSample(filename) {
  resetRunPanel(`Running ${filename} ...`);
  const res = await fetch("/api/process-sample", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename }),
  });
  const data = await res.json();
  animateStages(data);
}

// ---- manual upload ----
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const dzLabel = document.getElementById("dzLabel");

dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", e => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) uploadFile(fileInput.files[0]);
});

async function uploadFile(file) {
  dzLabel.textContent = `Uploading ${file.name} ...`;
  resetRunPanel(`Processing ${file.name} ...`);
  const form = new FormData();
  form.append("invoice", file);
  const res = await fetch("/api/process", { method: "POST", body: form });
  const data = await res.json();
  dzLabel.textContent = "Drop a PDF here, or click to choose one";
  animateStages(data);
}

// ---- live run view ----
function resetRunPanel(ledeText) {
  document.getElementById("runLede").textContent = ledeText;
  document.getElementById("stageList").innerHTML = "";
  const banner = document.getElementById("decisionBanner");
  banner.hidden = true;
}

function animateStages(data) {
  const stageList = document.getElementById("stageList");
  const stages = data.stages || [];
  stages.forEach((s, i) => {
    setTimeout(() => {
      const li = document.createElement("li");
      li.className = `stage-item ${s.status}`;
      li.innerHTML = `
        <span class="stage-num">${String(i + 1).padStart(2, "0")}</span>
        <div class="stage-body">
          <div class="stage-name">${s.stage}</div>
          <div class="stage-detail">${s.detail}</div>
        </div>`;
      stageList.appendChild(li);

      if (i === stages.length - 1) {
        document.getElementById("runLede").textContent = "Run complete.";
        const banner = document.getElementById("decisionBanner");
        const status = data.final_status || "NEEDS_REVIEW";
        banner.hidden = false;
        banner.className = `decision-banner ${status}`;
        banner.textContent = `Decision: ${status.replace("_", " ")} (${data.reason_code || ""})`;
      }
    }, i * 380);
  });
}

// ---- dashboard ----
async function loadDashboard() {
  const [runsRes, poRes] = await Promise.all([
    fetch("/api/runs"), fetch("/api/po-balances")
  ]);
  const runs = await runsRes.json();
  const pos = await poRes.json();

  const body = document.getElementById("runsBody");
  body.innerHTML = "";
  if (runs.length === 0) {
    body.innerHTML = `<tr class="empty-row"><td colspan="6">No runs yet — process an invoice from the Intake tab.</td></tr>`;
  } else {
    runs.forEach(r => {
      const tr = document.createElement("tr");
      tr.className = "clickable";
      tr.innerHTML = `
        <td>#${r.id}</td>
        <td>${r.vendor_name || "—"}</td>
        <td>${r.invoice_number || "—"}</td>
        <td>${r.po_number || "—"}</td>
        <td class="num">${r.total != null ? "$" + Number(r.total).toLocaleString(undefined, {minimumFractionDigits:2}) : "—"}</td>
        <td><span class="status-pill ${r.status}">${(r.status || "").replace("_"," ")}</span></td>
      `;
      tr.addEventListener("click", () => showRunDetail(r.id));
      body.appendChild(tr);
    });
  }

  const poBody = document.getElementById("poBody");
  poBody.innerHTML = "";
  pos.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.po_number}</td>
      <td>${p.vendor_name}${p.approved_vendor ? "" : " (unapproved)"}</td>
      <td class="num">$${p.po_amount.toLocaleString(undefined, {minimumFractionDigits:2})}</td>
      <td class="num">$${p.remaining_balance.toLocaleString(undefined, {minimumFractionDigits:2})}</td>
    `;
    poBody.appendChild(tr);
  });
}

async function showRunDetail(id) {
  const res = await fetch(`/api/runs/${id}`);
  const run = await res.json();
  const stages = JSON.parse(run.stages_json || "[]");
  const extracted = JSON.parse(run.extracted_json || "{}");

  const content = document.getElementById("detailContent");
  content.innerHTML = `
    <h2>Run #${run.id} — ${run.vendor_name || "Unknown vendor"}</h2>
    <p class="lede">${run.filename} · processed ${new Date(run.processed_at).toLocaleString()}</p>
    <div class="decision-banner ${run.status}" style="display:inline-block; margin-bottom:20px;">
      Decision: ${(run.status || "").replace("_"," ")} (${run.reason_code || ""})
    </div>
    <h2 style="font-size:15px; margin-bottom:10px;">Extracted fields</h2>
    <pre style="background:var(--accent-soft); padding:14px; border-radius:3px; font-size:12px; overflow-x:auto;">${JSON.stringify(extracted, null, 2)}</pre>
    <h2 style="font-size:15px; margin:20px 0 10px;">Reasoning trail</h2>
    <ol class="stage-list" style="animation:none;">
      ${stages.map((s, i) => `
        <li class="stage-item ${s.status}" style="opacity:1; transform:none; animation:none;">
          <span class="stage-num">${String(i+1).padStart(2,"0")}</span>
          <div class="stage-body">
            <div class="stage-name">${s.stage}</div>
            <div class="stage-detail">${s.detail}</div>
          </div>
        </li>`).join("")}
    </ol>
  `;
  document.getElementById("detailOverlay").hidden = false;
}

document.getElementById("closeDetail").addEventListener("click", () => {
  document.getElementById("detailOverlay").hidden = true;
});

document.getElementById("resetBtn").addEventListener("click", async () => {
  if (!confirm("Reset all run history and PO balances?")) return;
  await fetch("/api/reset", { method: "POST" });
  loadDashboard();
});

// ---- init ----
loadSamples();
