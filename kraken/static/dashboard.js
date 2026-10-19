/* Kraken dashboard (Wazuh-style). Data: GET /api/dashboard */
const OUT_COL = {violation:"#C6403A", held:"#1E8E5A", declined:"#8A97AB", blocked:"#2E5AAC", invalid:"#B9770E"};
const OUT_LBL = {violation:"Policy violated", held:"Held policy", declined:"Declined", blocked:"Blocked by Kraken"};
const dEsc = s => (typeof escapeHtml === "function") ? escapeHtml(String(s ?? "")) :
  String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct = (x, d=0) => x == null ? "-" : (x*100).toFixed(d) + "%";
const lvlOf = a => a >= .8 ? "Critical" : a >= .5 ? "High" : a >= .2 ? "Medium" : a > 0 ? "Low" : "Info";

function showView(name) {
  const dash = name === "dashboard";
  document.getElementById("view-main").style.display = dash ? "none" : "";
  document.getElementById("view-dashboard").style.display = dash ? "" : "none";
  const n = document.getElementById("nav-dashboard");
  if (n) n.style.color = dash ? "var(--navy)" : "";
  window.scrollTo({top: 0});
  if (dash) { initLivePanel(); loadDashboard(); }
}

let _dashTimer = null;
async function loadDashboard(manual) {
  const root = document.getElementById("dash-root");
  try {
    const r = await fetch("/api/dashboard");
    if (!r.ok) throw new Error("HTTP " + r.status);
    renderDashboard(root, await r.json());
    if (manual) {
      const a = root.querySelector(".dash-actions");
      if (a) { const m = document.createElement("span"); m.className = "dash-pill ok";
        m.textContent = "Refreshed " + new Date().toLocaleTimeString("en-GB"); a.prepend(m); setTimeout(() => m.remove(), 3000); }
    }
  } catch (e) {
    root.innerHTML = `<div class="dash-empty">Could not load dashboard data: ${dEsc(e.message)}</div>`;
  }
  clearTimeout(_dashTimer);
  _dashTimer = setTimeout(() => {
    if (document.getElementById("view-dashboard").style.display !== "none") loadDashboard();
  }, 15000);
}

function kpi(num, lbl, note, cls="") {
  return `<div class="kpi ${cls}"><div class="num">${num}</div><div class="lbl">${lbl}</div><div class="note">${note||""}</div></div>`;
}

function donut(outcomes) {
  const keys = Object.keys(OUT_LBL), total = keys.reduce((a,k)=>a+(outcomes[k]||0),0);
  const R=60, C=2*Math.PI*R; let off=0, arcs="";
  if (total) keys.forEach(k => {
    const v = outcomes[k]||0; if (!v) return;
    const len = v/total*C;
    arcs += `<circle r="${R}" cx="85" cy="85" fill="none" stroke="${OUT_COL[k]}" stroke-width="26"
      stroke-dasharray="${len} ${C-len}" stroke-dashoffset="${-off}" transform="rotate(-90 85 85)"><title>${OUT_LBL[k]}: ${v}</title></circle>`;
    off += len;
  });
  const legend = keys.map(k => `<div class="row"><span class="sw" style="background:${OUT_COL[k]}"></span>${OUT_LBL[k]}<span class="v">${outcomes[k]||0}</span></div>`).join("");
  return `<div class="donut-wrap"><svg class="donut" viewBox="0 0 170 170">
    <circle r="${R}" cx="85" cy="85" fill="none" stroke="#EAF0F9" stroke-width="26"/>${arcs}
    <text x="85" y="86" font-size="26" font-weight="800">${total}</text><text x="85" y="104" font-size="10" style="fill:var(--muted)">valid trials</text></svg>
    <div class="legend">${legend}</div></div>`;
}

function payloadBars(rows) {
  return rows.map(p => {
    const col = p.asr >= .8 ? "#C6403A" : p.asr >= .5 ? "#E0833A" : p.asr >= .2 ? "#B9770E" : p.asr > 0 ? "#2E5AAC" : "#C7D2E3";
    return `<div class="hbar" title="${dEsc(p.id)}: ${p.k}/${p.n}, 95% CI ${pct(p.ci[0])}-${pct(p.ci[1])}">
      <div class="name">${dEsc(p.id)}</div>
      <div class="track"><div class="fill" style="width:${Math.max(p.asr*100, p.asr>0?2:0)}%;background:${col}"></div></div>
      <div class="val">${p.k}/${p.n}</div></div>`;
  }).join("");
}

function heatmap(m) {
  const col = a => { const t = Math.min(1,a); return `rgba(198,64,58,${(0.12+0.88*t).toFixed(2)})`; };
  let h = `<table class="heat"><tr><th></th>${m.stealth.map(s=>`<th>${s}</th>`).join("")}</tr>`;
  m.vectors.forEach(v => {
    h += `<tr><th class="rowh">${v}</th>`;
    m.stealth.forEach(s => {
      const c = m.cells[v+"|"+s];
      if (!c || !c.n) { h += `<td class="empty">-</td>`; return; }
      const dark = c.asr > .45;
      h += `<td style="background:${c.asr>0?col(c.asr):"#EAF0F9"};color:${dark?"#fff":"#0B1F3A"}">${pct(c.asr)}<small>${c.k}/${c.n}</small></td>`;
    });
    h += `</tr>`;
  });
  return h + `</table>`;
}

function histogram(hg, policyMax) {
  const W=420,H=190,L=30,B=44,T=10, n=hg.counts.length, max=Math.max(1,...hg.counts);
  const bw=(W-L)/n; let s="";
  [0,.5,1].forEach(f => { const y=T+(H-B-T)*(1-f);
    s += `<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="#E3EAF4"/><text x="${L-4}" y="${y+3}" text-anchor="end">${Math.round(max*f)}</text>`; });
  hg.counts.forEach((c,i) => {
    const bh=(H-B-T)*c/max, x=L+i*bw+6, y=H-B-bh, ok=i===0;
    s += `<rect x="${x}" y="${y}" width="${bw-12}" height="${bh}" rx="3" fill="${ok?"#1E8E5A":"#C6403A"}"><title>${dEsc(hg.labels[i])}: ${c}</title></rect>`;
    if (c) s += `<text x="${x+(bw-12)/2}" y="${y-3}" text-anchor="middle" style="fill:#0B1F3A;font-weight:700">${c}</text>`;
    const lab = hg.labels[i].replace(" (in policy)","").split(" ");
    s += `<text x="${x+(bw-12)/2}" y="${H-B+14}" text-anchor="middle">${dEsc(lab[0])}</text>` +
         (lab[1] ? `<text x="${x+(bw-12)/2}" y="${H-B+26}" text-anchor="middle">${dEsc(lab.slice(1).join(" "))}</text>` : "");
  });
  return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}">${s}</svg>
    <div class="dsub" style="margin:6px 0 0">Green = within the ${policyMax}% policy limit. Red = discount the Checkout agent should never have approved.</div>`;
}

function timeline(seq) {
  if (!seq.length) return "";
  const W=760,H=150,L=28,T=8,rowH=18, n=seq.length, cw=Math.max(3,(W-L)/n), stripY=H-rowH-4;
  let s="";
  // rolling-10 success rate line
  const pts=[]; let win=[];
  seq.forEach((e,i)=>{ win.push(e.o==="violation"?1:0); if(win.length>10) win.shift();
    pts.push([L+i*cw+cw/2, T+(stripY-T-10)*(1-win.reduce((a,b)=>a+b,0)/win.length)]); });
  [0,.5,1].forEach(f=>{ const y=T+(stripY-T-10)*(1-f);
    s+=`<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="#E3EAF4"/><text x="${L-4}" y="${y+3}" text-anchor="end">${f*100}%</text>`; });
  s+=`<polyline fill="none" stroke="#C6403A" stroke-width="2" points="${pts.map(p=>p.join(",")).join(" ")}"/>`;
  seq.forEach((e,i)=>{ s+=`<rect x="${L+i*cw}" y="${stripY}" width="${Math.max(1,cw-1)}" height="${rowH}" fill="${OUT_COL[e.o]||"#999"}"><title>#${i+1} ${dEsc(e.p)}: ${dEsc(e.o)} (${e.d}%)</title></rect>`; });
  return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}">${s}</svg>
    <div class="seq-legend">${Object.keys(OUT_LBL).map(k=>`<span style="--c:${OUT_COL[k]}">${OUT_LBL[k]}</span>`).join("")}<span style="--c:#C6403A">Line: rolling success rate (last 10 trials)</span></div>`;
}

function comparison(c) {
  if (!c) return `<div class="dash-empty" style="padding:26px 10px">No defense-ON runs recorded yet.<br>This panel compares attack success with Kraken OFF vs ON once the defense phase is run.</div>`;
  const rows = ["overall","review","goal","notes"].filter(k=>c.off[k]||c.on[k]).map(k => {
    const o=c.off[k], d=c.on[k], f=x=>x?`${pct(x.asr)} <span style="color:var(--muted)">(${x.k}/${x.n})</span>`:"-";
    return `<tr><td>${k}</td><td>${f(o)}</td><td>${f(d)}</td></tr>`; }).join("");
  return `<table class="dtable"><tr><th>Scope</th><th>Kraken OFF</th><th>Kraken ON</th></tr>${rows}</table>`;
}

function renderDashboard(root, d) {
  if (!d.has_data) {
    root.innerHTML = `<div class="dash-empty"><h2>No attack data yet</h2>Run the offense baseline first:<br><br><code>marketflow\\venv\\Scripts\\python -m offense.runner --trials 5</code></div>`;
    return;
  }
  const k = d.kpis, live = d.defense_live || {};
  const pills = [`<span class="dash-pill">${d.sources.length} result file(s)</span>`,
    k.invalid_excluded ? `<span class="dash-pill warn">${k.invalid_excluded} contaminated trial(s) excluded</span>` : `<span class="dash-pill ok">no contaminated trials</span>`,
    `<span class="dash-pill">updated ${dEsc(d.generated)}</span>`].join("");
  let h = `<div class="dash-head"><div><div class="eyebrow">Security events</div><h1>Attack Dashboard</h1>
    <div class="dash-sub">Offense baseline against MarketFlow with Kraken defense OFF. Success = order placed with a discount above the ${d.policy_max}% policy limit.</div></div>
    <div class="dash-actions">${pills}<button class="btn btn-outline" onclick="loadDashboard(true)">Refresh</button></div></div>`;

  h += `<div class="kpi-grid">` +
    kpi(k.attack_trials, "Valid attack trials", `${k.invalid_excluded} excluded`) +
    kpi(k.violations, "Successful attacks", "policy violated", "bad") +
    kpi(pct(k.asr,1), "Attack success rate", `95% CI ${pct(k.asr_ci[0])}-${pct(k.asr_ci[1])}`, k.asr>=.5?"bad":"warn") +
    kpi(`${k.payloads_effective}/${k.payloads_total}`, "Payloads that worked", "at least one success", "warn") +
    kpi(k.mean_violation_discount==null?"-":k.mean_violation_discount.toFixed(1)+"%", "Avg stolen discount", `limit ${d.policy_max}%`, "bad") +
    kpi(`${k.control_violations}/${k.control_n}`, "Control (no attack)", "false-positive baseline", k.control_violations?"bad":"good") + `</div>`;

  h += `<div class="dash-grid">
    <div class="dcard span-5"><h3>Outcome distribution</h3><div class="dsub">What happened in each valid attack trial</div>${donut(d.outcomes)}</div>
    <div class="dcard span-7"><h3>Success by injection vector &times; stealth</h3><div class="dsub">Share of trials that broke policy</div>${heatmap(d.matrix)}</div>
    <div class="dcard span-7"><h3>Payload effectiveness</h3><div class="dsub">Successes / trials per payload (hover for confidence interval)</div>${payloadBars(d.by_payload)}</div>
    <div class="dcard span-5"><h3>Discount granted</h3><div class="dsub">Distribution of final discounts across valid trials</div>${histogram(d.histogram, d.policy_max)}</div>
    <div class="dcard span-12"><h3>Attack timeline</h3><div class="dsub">Every trial in run order</div>${timeline(d.sequence)}</div>
    <div class="dcard span-12"><h3>RAG poisoning benchmark (PoisonedRAG dataset)</h3><div class="dsub">Published dataset: 100 target questions per corpus, 5 poisoned passages each. Attack succeeds when the model answers with the attacker's wrong answer.</div>${ragBench(d.rag_benchmark)}</div>
    <div class="dcard span-12"><h3>Live session</h3><div class="dsub">Attacks fired from the live runner since Kraken was started (not part of the baseline numbers)</div>${liveSession(d.live_session)}</div>
    <div class="dcard span-6"><h3>Kraken OFF vs ON</h3><div class="dsub">Defense effectiveness</div>${comparison(d.comparison)}</div>
    <div class="dcard span-6"><h3>Kraken live enforcement</h3><div class="dsub">Counters from the running defense</div>${liveTiles(live)}${evidence(d.evidence)}</div>
  </div>`;

  h += `<div class="dash-section-title">Top attack payloads</div><div class="dcard scroll-x"><table class="dtable">
    <tr><th>Level</th><th>Payload</th><th>Vector</th><th>Stealth</th><th>Success</th><th>ASR</th><th>95% CI</th><th>Avg discount</th><th>Retrieved</th></tr>` +
    d.by_payload.slice(0,12).map(p => `<tr><td><span class="lvl lvl-${p.level||lvlOf(p.asr)}">${p.level||lvlOf(p.asr)}</span></td><td class="mono">${dEsc(p.id)}</td><td>${dEsc(p.vector)}</td><td>${dEsc(p.stealth)}</td>
      <td>${p.k}/${p.n}</td><td>${pct(p.asr)}</td><td>${pct(p.ci[0])}-${pct(p.ci[1])}</td><td>${p.mean_discount==null?"-":Number(p.mean_discount).toFixed(1)+"%"}</td><td>${p.retrieved==null?"-":pct(p.retrieved)}</td></tr>`).join("") +
    `</table></div>`;

  h += `<div class="dash-section-title">Recent events</div><div class="dcard scroll-x"><table class="dtable">
    <tr><th>Time</th><th>Payload</th><th>Vector</th><th>Outcome</th><th>Discount</th></tr>` +
    d.recent.slice(0,15).map(r => `<tr><td class="mono">${dEsc(String(r.ts).replace("T"," "))}</td><td class="mono">${dEsc(r.payload)}</td><td>${dEsc(r.vector)}</td>
      <td><span class="out out-${r.outcome}">${dEsc(OUT_LBL[r.outcome]||r.outcome)}</span></td><td>${r.discount==null?"-":Number(r.discount).toFixed(1)+"%"}</td></tr>`).join("") + `</table></div>`;

  h += `<div class="dash-foot">Sources: ${d.sources.map(s=>dEsc(s.file)+" ("+s.trials+" trials)").join(", ")}. Edit <code>offense/results/included.json</code> to choose which runs count. Single model, small samples: read the confidence intervals, not just the percentages.</div>`;
  root.innerHTML = h;
}

function liveTiles(l) {
  const keys = [["total","Inspected"],["blocked","Blocked"],["flagged","Flagged"],["forwarded","Forwarded"],["cache_hits","Cache hits"]];
  if (!Object.keys(l).length) return "";
  return `<div class="kpi-grid" style="grid-template-columns:repeat(5,1fr);margin-bottom:10px">` +
    keys.map(([a,b]) => kpi(l[a]??0, b, "", a==="blocked"?"good":a==="flagged"?"warn":"")).join("") + `</div>` +
    `<div class="dash-sub" style="margin-bottom:8px">Defense is <b>${l.defense_on?"ON":"OFF"}</b></div>`;
}

function evidence(ev) {
  if (!ev || !ev.length) return `<div class="dash-sub">No live inspections yet.</div>`;
  return `<table class="dtable"><tr><th>Checkpoint</th><th>Decision</th><th>Reason</th></tr>` +
    ev.slice(0,6).map(e => `<tr><td>${dEsc(e.checkpoint)}</td><td><span class="out ${e.decision==="forwarded"?"out-held":"out-blocked"}">${dEsc(e.decision)}</span></td><td>${dEsc(String(e.reason||"").slice(0,70))}</td></tr>`).join("") + `</table>`;
}

/* ---------------- Live attack runner ---------------- */
let _liveJob = null, _livePoll = null;

function initLivePanel() {
  const root = document.getElementById("live-root");
  if (!root || root.dataset.ready) return;
  root.dataset.ready = "1";
  root.innerHTML = `<div class="livebox"><h3>Live attack runner</h3>
    <div class="dsub" style="font-size:11.5px;color:var(--muted)">Fires a real attack at the running MarketFlow app and prints each result. Not saved to the baseline numbers below.</div>
    <div class="live-controls">
      <button class="btn btn-outline" data-atk="control">Control (no attack)</button>
      <button class="btn btn-primary" data-atk="direct">Direct</button>
      <button class="btn btn-primary" data-atk="indirect">Indirect</button>
      <button class="btn btn-primary" data-atk="rag">RAG poisoning</button>
      <button class="btn btn-primary" data-atk="cross_agent">Cross-agent</button>
      <label>Review payload <select id="live-variant"><option value="authority-a">authority-a (official notice)</option><option value="paraphrased">paraphrased (store notice)</option></select></label>
      <label>Trials <select id="live-trials"><option>1</option><option>3</option><option>5</option><option>10</option></select></label>
      <button class="btn btn-outline" id="live-clear">Clear</button>
    </div>
    <div class="console" id="live-console"><span class="l-info">Pick an attack above. Each trial takes roughly 20-60 seconds (4 paced Gemini calls).</span></div></div>`;
  root.querySelectorAll("[data-atk]").forEach(b => b.onclick = () => startLive(b.dataset.atk));
  document.getElementById("live-clear").onclick = () => { document.getElementById("live-console").innerHTML = ""; };
}

function liveLog(kind, text, t) {
  const c = document.getElementById("live-console");
  const d = document.createElement("div");
  d.className = "l-" + kind;
  d.innerHTML = `<span class="ts">${dEsc(t || new Date().toLocaleTimeString("en-GB"))}</span>${dEsc(text)}`;
  c.appendChild(d); c.scrollTop = c.scrollHeight;
}

async function startLive(atk) {
  if (_liveJob) { liveLog("error", "A run is already in progress."); return; }
  const btns = document.querySelectorAll("#live-root [data-atk]");
  btns.forEach(b => b.disabled = true);
  try {
    const r = await fetch("/api/live/start", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({attack_type: atk, variant: document.getElementById("live-variant").value,
                            trials: parseInt(document.getElementById("live-trials").value, 10)})});
    const d = await r.json();
    if (d.error) { liveLog("error", d.error); btns.forEach(b => b.disabled = false); return; }
    _liveJob = {id: d.id, since: 0};
    _livePoll = setInterval(pollLive, 2000);
  } catch (e) { liveLog("error", "Request failed: " + e.message); btns.forEach(b => b.disabled = false); }
}

async function pollLive() {
  if (!_liveJob) return;
  try {
    const d = await (await fetch(`/api/live/${_liveJob.id}?since=${_liveJob.since}`)).json();
    if (d.error) throw new Error(d.error);
    d.lines.forEach(l => liveLog(l.kind, l.text, l.t));
    _liveJob.since = d.next;
    if (d.status === "done") {
      clearInterval(_livePoll); _liveJob = null;
      document.querySelectorAll("#live-root [data-atk]").forEach(b => b.disabled = false);
      loadDashboard();
    }
  } catch (e) {
    liveLog("error", "Lost the run: " + e.message);
    clearInterval(_livePoll); _liveJob = null;
    document.querySelectorAll("#live-root [data-atk]").forEach(b => b.disabled = false);
  }
}

function liveSession(ls) {
  if (!ls || !ls.total) return `<div class="dash-sub">No live attacks yet. Use the runner above.</div>`;
  const rows = ls.by_attack.map(a => `<tr><td>${dEsc(a.attack)}</td><td><span class="out out-violation">${a.success}</span></td><td><span class="out out-held">${a.fail}</span></td><td><span class="out out-blocked">${a.blocked}</span></td><td><span class="out out-invalid">${a.invalid + a.error}</span></td></tr>`).join("");
  return `<div class="scroll-x"><table class="dtable"><tr><th>Attack</th><th>Succeeded</th><th>Failed</th><th>Blocked</th><th>Invalid</th></tr>${rows}</table></div>`;
}

function ragBench(rows) {
  if (!rows || !rows.length) return `<div class="dash-empty" style="padding:22px 10px">No benchmark run yet.<br><code>marketflow\\venv\\Scripts\\python -m offense.ragpoison --dataset nq</code></div>`;
  const bar = (label, v, col) => `<div class="hbar"><div class="name">${label}</div><div class="track"><div class="fill" style="width:${(v||0)*100}%;background:${col}"></div></div><div class="val">${pct(v,0)}</div></div>`;
  return rows.map(r => { const s = r.summary, m = r.meta;
    return `<div style="margin-bottom:14px"><div style="font-weight:700;font-size:12.5px;margin-bottom:6px">${dEsc(m.dataset)} <span class="dash-sub">&middot; ${s.poisoned_n} valid questions &middot; ${dEsc(m.llm)} &middot; ${dEsc(m.retriever.split(";")[0])}</span></div>
      ${bar("Clean accuracy (no attack)", s.clean_accuracy, "#1E8E5A")}
      ${bar("Poison reached top-" + m.top_k, s.retrieved_rate, "#B9770E")}
      ${bar("Attack success rate", s.asr, "#C6403A")}
      <div class="dash-sub">ASR 95% CI ${pct(s.asr_ci[0])}-${pct(s.asr_ci[1])} &middot; ASR when poison retrieved ${pct(s.asr_when_retrieved)} &middot; paper-style substring ASR ${pct(s.asr_paper_substring)} &middot; ${s.invalid_excluded} invalid excluded</div></div>`; }).join("");
}
