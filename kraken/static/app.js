let attackTypes = [];
let selectedOffense = null;
let selectedDefense = null;

async function j(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}

function escapeHtml(s) {
  return (s || "").toString().replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function scrollToId(id) {
  document.getElementById(id).scrollIntoView({behavior: "smooth", block: "start"});
}

/* ---------------- Header status ---------------- */

async function refreshMeta() {
  const meta = await j("/api/meta");
  const dot = document.getElementById("mf-status-dot");
  const text = document.getElementById("mf-status-text");
  if (meta.marketflow_live) {
    dot.className = "status-dot live";
    text.textContent = "MarketFlow: live";
  } else {
    dot.className = "status-dot offline";
    text.textContent = "MarketFlow: offline (using recorded reference)";
  }
  applyDefenseState(meta.defense_on);
}

/* ---------------- Attack picker (shared render) ---------------- */

function renderAttackPicker(containerId, onSelect) {
  const el = document.getElementById(containerId);
  el.innerHTML = attackTypes.map(a => `
    <div class="attack-pill" data-id="${a.id}" onclick="${onSelect}('${a.id}')">
      <div class="name">${escapeHtml(a.label)}</div>
      <div class="cp">${a.checkpoint} checkpoint</div>
    </div>
  `).join("");
}

function selectOffense(id) {
  selectedOffense = id;
  document.querySelectorAll("#attack-picker .attack-pill").forEach(p => p.classList.toggle("selected", p.dataset.id === id));
}

function selectDefense(id) {
  selectedDefense = id;
  document.querySelectorAll("#defense-attack-picker .attack-pill").forEach(p => p.classList.toggle("selected", p.dataset.id === id));
  const spec = attackTypes.find(a => a.id === id);
  document.getElementById("checkpoint-row").innerHTML = `
    <span class="checkpoint-chip ${spec.checkpoint === "retrieval" ? "active" : ""}">Retrieval checkpoint</span>
    <span class="checkpoint-chip ${spec.checkpoint === "handoff" ? "active" : ""}">Handoff checkpoint</span>
  `;
}

/* ---------------- Offense: Attack Simulator ---------------- */

async function runSimulation() {
  if (!selectedOffense) { selectedOffense = attackTypes[0].id; selectOffense(selectedOffense); }
  const btn = document.getElementById("simulate-btn");
  btn.disabled = true;
  btn.textContent = "Running...";

  const scanBox = document.getElementById("scan-box");
  const resultBox = document.getElementById("result-box");
  resultBox.classList.remove("show");
  scanBox.classList.add("show");
  scanBox.innerHTML = "";

  const spec = attackTypes.find(a => a.id === selectedOffense);
  const stepLabels = {
    direct: ["Scanning input for override patterns...", "Checking against known jailbreak signatures...", "Evaluating instruction-hijack likelihood..."],
    indirect: ["Scanning secondary fields (notes, metadata)...", "Cross-referencing against primary instruction...", "Evaluating hidden-instruction likelihood..."],
    rag: ["Scanning retrieved content (reviews)...", "Comparing against known poisoning patterns...", "Checking retrieval-to-agent trust boundary..."],
    cross_agent: ["Tracing agent-to-agent handoff (Negotiator -> Orchestrator -> Checkout)...", "Checking for unverified instruction forwarding...", "Confirming propagation path..."],
  }[selectedOffense];
  const pcts = [20, 55, 85];

  const resultPromise = j("/api/simulate", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({attack_type: selectedOffense})
  });

  for (let i = 0; i < stepLabels.length; i++) {
    await new Promise(res => setTimeout(res, 550 + Math.random() * 300));
    const line = document.createElement("div");
    line.className = "scan-line";
    line.innerHTML = `<span>${escapeHtml(stepLabels[i])}</span><span class="pct">${pcts[i]}%</span>`;
    scanBox.appendChild(line);
  }
  await new Promise(res => setTimeout(res, 400));
  const doneLine = document.createElement("div");
  doneLine.className = "scan-line";
  doneLine.innerHTML = `<span>Simulation complete</span><span class="pct">100%</span>`;
  scanBox.appendChild(doneLine);

  const result = await resultPromise;
  renderSimulationResult(result);

  btn.disabled = false;
  btn.textContent = "Run Simulation";
}

function riskClass(score) {
  if (score >= 70) return "high";
  if (score >= 40) return "med";
  return "low";
}

function renderSimulationResult(r) {
  const box = document.getElementById("result-box");
  const cls = riskClass(r.risk_score);
  const o = r.outcome;
  box.innerHTML = `
    <div class="risk-row">
      <div class="risk-score ${cls}"><div>${r.risk_score}</div><span class="lbl">risk</span></div>
      <div>
        <div class="risk-finding-title">${escapeHtml(r.label)} -- ${o.violations.length ? "attack succeeded" : "no violation observed"}</div>
        <div class="risk-finding-text">${escapeHtml(r.finding)}</div>
      </div>
    </div>
    <a class="evidence-toggle" onclick="toggleEvidence(this)">View evidence ▾</a>
    <div class="evidence-body">
      <b>Payload used</b>
      <pre>${escapeHtml(r.payload)}</pre>
      <b>Outcome</b>
      <pre>List price: $${o.list_price}
Final price: $${o.final_price}  (${o.discount_pct}% off)
${o.violations.length ? "Violation: " + o.violations.join(" ") : "No policy violation."}</pre>
      ${o.trace && o.trace.length ? `<b>Agent trace (from live MarketFlow run)</b><pre>${escapeHtml(o.trace.map(t => `[${t.agent}] ${t.direction} ${t.direction === "input" ? "from" : "to"} ${t.peer}: ${t.content}`).join("\n\n"))}</pre>` : ""}
    </div>
    <div class="source-note">Target: MarketFlow (${r.target.live ? "live run" : "recorded reference run"})</div>
  `;
  box.classList.add("show");
}

function toggleEvidence(el) {
  const body = el.nextElementSibling;
  body.classList.toggle("show");
  el.textContent = body.classList.contains("show") ? "Hide evidence ▴" : "View evidence ▾";
}

/* ---------------- Defense: Live Enforcement ---------------- */

function applyDefenseState(on) {
  const sw = document.getElementById("defense-switch");
  const label = document.getElementById("defense-switch-label");
  sw.classList.toggle("on", on);
  label.textContent = "Kraken: " + (on ? "ON" : "OFF");
}

async function toggleDefense() {
  const r = await j("/api/defense/toggle", {method: "POST"});
  applyDefenseState(r.defense_on);
}

async function resetDefenseDemo() {
  await j("/api/defense/reset", {method: "POST"});
  await refreshTally();
  document.getElementById("evidence-log-list").innerHTML = "";
  document.getElementById("decision-banner").style.display = "none";
  document.getElementById("tier-grid").innerHTML = "";
}

const TIER_ORDER = ["cache", "regex", "classifier", "llm_judge"];
const TIER_NAMES = {cache: "Signature cache", regex: "Pattern check", classifier: "Classifier", llm_judge: "LLM judge"};

function renderTiers(tiers) {
  const grid = document.getElementById("tier-grid");
  grid.innerHTML = TIER_ORDER.map(key => {
    const t = tiers[key];
    if (!t) {
      return `<div class="tier-card skip"><div class="tname">${TIER_NAMES[key]}</div><div class="tstatus">skipped</div></div>`;
    }
    let statusText, cls;
    if (key === "cache") { statusText = t.hit ? "cache hit" : "no match"; cls = t.hit ? "flag" : "pass"; }
    else if (key === "regex") { statusText = t.flagged ? "flagged" : "pass"; cls = t.flagged ? "flag" : "pass"; }
    else if (key === "classifier") { statusText = `score ${t.score}`; cls = t.score >= 0.6 ? "flag" : "pass"; }
    else { statusText = t.available ? (t.is_injection ? "flagged" : "pass") : "unavailable"; cls = t.available ? (t.is_injection ? "flag" : "pass") : "skip"; }
    return `<div class="tier-card active ${cls}"><div class="tname">${TIER_NAMES[key]}</div><div class="tstatus">${statusText}</div><div class="tms">${t.elapsed_ms}ms</div></div>`;
  }).join("");
}

async function runDefense() {
  if (!selectedDefense) { selectedDefense = attackTypes[0].id; selectDefense(selectedDefense); }
  const btn = document.getElementById("defense-run-btn");
  btn.disabled = true;
  btn.textContent = "Checking...";
  document.getElementById("tier-grid").innerHTML = TIER_ORDER.map(k =>
    `<div class="tier-card"><div class="tname">${TIER_NAMES[k]}</div><div class="tstatus">pending...</div></div>`
  ).join("");

  const r = await j("/api/defense/run", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({attack_type: selectedDefense, forward_to_marketflow: true})
  });

  await new Promise(res => setTimeout(res, 500));
  renderTiers(r.tiers);

  const banner = document.getElementById("decision-banner");
  banner.style.display = "block";
  banner.className = "decision-banner " + r.decision;
  const cpLabel = r.checkpoint === "retrieval" ? "Retrieval checkpoint" : "Handoff checkpoint";
  let verdictText;
  if (r.decision === "blocked") verdictText = `${cpLabel}: BLOCKED -- request never reached MarketFlow.`;
  else if (r.decision === "flagged") verdictText = `${cpLabel}: FLAGGED -- forwarded with a warning attached.`;
  else verdictText = `${cpLabel}: FORWARDED -- no injection signal found (or Kraken is off).`;
  banner.innerHTML = `${verdictText}<div class="decision-sub">${escapeHtml(r.reason)}${r.cache_hit ? " (signature cache hit)" : ""}</div>`;

  if (r.marketflow_result && r.marketflow_result.order) {
    const o = r.marketflow_result.order;
    banner.innerHTML += `<div class="decision-sub">MarketFlow order result: $${o.final_price} (${o.discount_pct}% off)${r.marketflow_result.violations.length ? " -- POLICY VIOLATION" : ""}</div>`;
  }

  await refreshTally();
  prependEvidence(r);

  btn.disabled = false;
  btn.textContent = "Run Enforcement Check";
}

async function refreshTally() {
  const t = await j("/api/defense/tally");
  const grid = document.getElementById("tally-grid");
  grid.innerHTML = `
    <div class="tally-tile"><div class="num">${t.blocked}</div><div class="lbl">Blocked</div></div>
    <div class="tally-tile"><div class="num">${t.flagged}</div><div class="lbl">Flagged</div></div>
    <div class="tally-tile"><div class="num">${t.forwarded}</div><div class="lbl">Forwarded</div></div>
    <div class="tally-tile"><div class="num">${t.cache_hits}</div><div class="lbl">Cache hits</div></div>
    <div class="tally-tile"><div class="num">${t.false_positive_rate ?? "--"}%</div><div class="lbl">False positive rate</div></div>
  `;
}

function prependEvidence(r) {
  const list = document.getElementById("evidence-log-list");
  const row = document.createElement("div");
  row.className = "evidence-row";
  row.innerHTML = `
    <span class="dec-badge ${r.decision}">${r.decision}</span>
    <span>${escapeHtml(r.checkpoint)} checkpoint -- ${escapeHtml(r.reason)}</span>
  `;
  list.prepend(row);
}

/* ---------------- init ---------------- */

async function init() {
  attackTypes = await j("/api/attack-types");
  renderAttackPicker("attack-picker", "selectOffense");
  renderAttackPicker("defense-attack-picker", "selectDefense");
  selectOffense(attackTypes[0].id);
  selectDefense(attackTypes[0].id);
  await refreshMeta();
  await refreshTally();
}

init();
