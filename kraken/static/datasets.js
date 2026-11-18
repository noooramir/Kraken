/* Kraken – Datasets tab.  GET /api/datasets → renders source + generated dataset overview */

async function loadDatasets() {
  const root = document.getElementById("view-datasets-inner");
  root.innerHTML = `<div class="dash-empty">Loading datasets…</div>`;
  try {
    const r = await fetch("/api/datasets");
    if (!r.ok) throw new Error("HTTP " + r.status);
    renderDatasets(root, await r.json());
  } catch (e) {
    root.innerHTML = `<div class="dash-empty">Could not load dataset info: ${dEsc(e.message)}</div>`;
  }
}

function renderDatasets(root, d) {
  let h = `<div class="dash-head"><div><div class="eyebrow">Training &amp; Evaluation Data</div>
    <h1>Datasets</h1>
    <div class="dash-sub">Every dataset Kraken sources for attack generation, retrieval poisoning, and benchmarking — plus the attack dataset we build from live runs.</div></div></div>`;

  /* ---- KPI row ---- */
  h += `<div class="kpi-grid" style="grid-template-columns:repeat(5,1fr);margin-bottom:18px">` +
    kpi(d.total_sources, "Source datasets", "") +
    kpi(d.total_source_rows, "Total source rows", "across all sources") +
    kpi(d.generated.total_rows, "Generated rows", "from attack runs") +
    kpi(d.generated.columns, "Columns per row", "full pipeline trace") +
    kpi(d.generated.files, "Result files", "in offense/results/") + `</div>`;

  /* ---- Source datasets grid ---- */
  h += `<div class="dash-section-title">Source Datasets</div><div class="dash-grid">`;

  d.sources.forEach(s => {
    const span = s.id === "amazon_reviews" ? "span-6" : "span-6";
    let inner = `<h3>${dEsc(s.name)}</h3><div class="dsub">${dEsc(s.description)}</div>`;
    inner += `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">`;
    inner += `<span class="dash-pill">${s.rows} rows</span>`;
    if (s.files) inner += `<span class="dash-pill">${s.files} file(s)</span>`;
    if (s.format) inner += `<span class="dash-pill">${dEsc(s.format)}</span>`;
    inner += `</div>`;
    if (s.columns && s.columns.length) {
      inner += `<div style="font-size:11px;color:var(--muted);margin-bottom:6px"><b>Schema:</b> ${s.columns.map(c => `<code>${dEsc(c)}</code>`).join(", ")}</div>`;
    }
    if (s.sample && s.sample.length) {
      inner += `<div class="scroll-x"><table class="dtable" style="font-size:11px"><tr>`;
      const cols = Object.keys(s.sample[0]);
      cols.forEach(c => inner += `<th>${dEsc(c)}</th>`);
      inner += `</tr>`;
      s.sample.forEach(row => {
        inner += `<tr>`;
        cols.forEach(c => {
          let v = String(row[c] ?? "");
          if (v.length > 80) v = v.slice(0, 77) + "…";
          inner += `<td>${dEsc(v)}</td>`;
        });
        inner += `</tr>`;
      });
      inner += `</table></div>`;
    }
    if (s.citation) inner += `<div style="font-size:10.5px;color:var(--muted);margin-top:8px">📄 ${dEsc(s.citation)}</div>`;
    h += `<div class="dcard ${span}">${inner}</div>`;
  });
  h += `</div>`;

  /* ---- Generated attack dataset ---- */
  const g = d.generated;
  h += `<div class="dash-section-title">Generated Attack Dataset</div>`;
  h += `<div class="dcard" style="margin-bottom:14px">`;
  h += `<h3>Offense Runner Output</h3>`;
  h += `<div class="dsub">Built automatically by <code>offense/runner.py</code> — each row is one full attack trial with the complete pipeline trace from payload generation through agent negotiation to Kraken detection.</div>`;
  h += `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">`;
  h += `<span class="dash-pill">${g.total_rows} rows</span>`;
  h += `<span class="dash-pill">${g.columns} columns per row</span>`;
  h += `<span class="dash-pill">${g.files} CSV file(s)</span>`;
  h += `</div>`;

  if (g.column_groups) {
    h += `<div style="margin-bottom:14px">`;
    g.column_groups.forEach(cg => {
      h += `<div style="margin-bottom:8px"><b style="font-size:11.5px">${dEsc(cg.group)}</b>
        <span style="font-size:10.5px;color:var(--muted);margin-left:6px">${cg.cols.length} fields</span><br>
        <span style="font-size:11px;color:var(--muted)">${cg.cols.map(c => `<code>${dEsc(c)}</code>`).join(", ")}</span></div>`;
    });
    h += `</div>`;
  }

  if (g.sample && g.sample.length) {
    h += `<div class="dash-section-title" style="margin-top:4px">Sample rows (first 5)</div>`;
    h += `<div class="scroll-x"><table class="dtable" style="font-size:10.5px"><tr>`;
    const cols = g.sample_columns || Object.keys(g.sample[0]);
    cols.forEach(c => h += `<th style="white-space:nowrap">${dEsc(c)}</th>`);
    h += `</tr>`;
    g.sample.forEach(row => {
      h += `<tr>`;
      cols.forEach(c => {
        let v = String(row[c] ?? "");
        if (v.length > 60) v = v.slice(0, 57) + "…";
        h += `<td>${dEsc(v)}</td>`;
      });
      h += `</tr>`;
    });
    h += `</table></div>`;
  }

  h += `</div>`;

  /* ---- Data pipeline diagram ---- */
  h += `<div class="dcard" style="margin-top:14px"><h3>Data Pipeline</h3>
    <div class="dsub">How source data flows through the attack generation and evaluation pipeline</div>
    <div class="data-pipeline">
      <div class="pipe-stage"><div class="pipe-icon">📥</div><div class="pipe-label">Source Data</div><div class="pipe-detail">Amazon reviews, PoisonedRAG, ASB, InjecAgent</div></div>
      <div class="pipe-arrow">→</div>
      <div class="pipe-stage accent"><div class="pipe-icon">⚔️</div><div class="pipe-label">Attack Generator</div><div class="pipe-detail">offense/runner.py — TF-IDF triggers, payload crafting</div></div>
      <div class="pipe-arrow">→</div>
      <div class="pipe-stage"><div class="pipe-icon">🤖</div><div class="pipe-label">MarketFlow Agents</div><div class="pipe-detail">Buyer → Negotiator → Orchestrator → Checkout</div></div>
      <div class="pipe-arrow">→</div>
      <div class="pipe-stage accent"><div class="pipe-icon">📊</div><div class="pipe-label">Attack Dataset</div><div class="pipe-detail">50+ columns per trial, full pipeline trace</div></div>
    </div></div>`;

  root.innerHTML = h;
}
