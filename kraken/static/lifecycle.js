/* Kraken "Live Cycle": animates the attack that is running right now as it moves
   through MarketFlow's agents and Kraken's checkpoints.
   Data: GET /api/lifecycle (events recorded by MarketFlow, nothing simulated). */
(function () {
  "use strict";

  const esc = s => (typeof dEsc === "function") ? dEsc(s)
    : String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

  const NW = 104, NH = 64, STEP = 125, X0 = 12, Y0 = 26, Y1 = 178;
  const NODES = [
    {id:"entry",       label:"Entry point",    col:0, y:Y0},
    {id:"kraken_in",   label:"Kraken input",   col:1, y:Y0, kraken:true},
    {id:"buyer",       label:"Buyer Agent",    col:2, y:Y0},
    {id:"negotiator",  label:"Negotiator",     col:3, y:Y0},
    {id:"kraken_hand", label:"Kraken handoff", col:4, y:Y0, kraken:true},
    {id:"orchestrator",label:"Orchestrator",   col:5, y:Y0},
    {id:"checkout",    label:"Checkout",       col:6, y:Y0},
    {id:"outcome",     label:"Outcome",        col:7, y:Y0},
    {id:"store",       label:"Review store",   col:3, y:Y1},
  ];
  const N = Object.fromEntries(NODES.map(n => [n.id, Object.assign(n, {x: X0 + n.col * STEP})]));
  const EDGES = [
    ["entry","kraken_in"], ["kraken_in","buyer"], ["buyer","negotiator"], ["negotiator","kraken_hand"],
    ["kraken_hand","orchestrator"], ["orchestrator","checkout"], ["checkout","outcome"],
    ["kraken_in","store","Review ingestion"], ["store","negotiator","Retrieval"],
  ];
  const TAG = {entry:"ENTRY", kraken_in:"KRAKEN", kraken_hand:"KRAKEN", buyer:"BUYER", store:"STORE",
               negotiator:"NEGOTIATOR", orchestrator:"ORCH", checkout:"CHECKOUT", outcome:"RESULT", env:"ENV"};
  const PHASE = {start:"started", in:"input to model", out:"model output", decision:"decision",
                 retrieved:"retrieved", planted:"planted", llm:"model call", fallback:"fallback",
                 error:"error", result:"result", run:"run", reset:"reset"};
  const INFO = {
    entry: "Where the payload enters. Reviews are checked by Kraken when they are submitted. The shopper's goal and delivery note are checked when the order starts.",
    kraken_in: "Kraken's tiered check (signature cache, regex, classifier, LLM judge) runs on every review, goal and note before the agents ever see it.",
    buyer: "Turns the shopper's goal and notes into an opening request, then approves or rejects the seller's counter-offer. It acts on its own with no human reviewing each message.",
    store: "TF-IDF retrieval ranks reviews by similarity to the buyer's request. A review written with the right keywords gets pulled into the Negotiator's context.",
    negotiator: "Its system prompt says customer reviews are verified and trustworthy, so retrieved review text sits in the same context as its instructions. That is how a planted review can steer the price.",
    kraken_hand: "Second checkpoint: the Negotiator's message to the Orchestrator is inspected before it is allowed to move on.",
    orchestrator: "Told not to re-verify pricing, so it forwards whatever was agreed upstream.",
    checkout: "Executes the routed order at face value and finalises the price.",
    outcome: "Final result: order placed (and whether it broke the discount policy), declined, or stopped by Kraken.",
  };

  const LC = {open:false, since:-1, events:[], seen:new Set(), job:null, reach:null, defenseOn:null,
              note:"", err:"", sel:null, follow:true, timer:null, sig:"", evCount:-1, selSig:""};

  /* ---------- taint detection ---------- */
  const norm = s => String(s || "").toLowerCase().replace(/\s+/g, " ").trim();
  function payloadKey() { const p = LC.job && LC.job.payload; return p ? norm(p).slice(0, 48) : ""; }
  function isTainted(ev) {
    if (ev.markers && ev.markers.length) return true;
    const k = payloadKey();
    return !!k && norm(ev.content).includes(k);
  }
  function hl(text, needles) {
    const src = String(text ?? ""), low = src.toLowerCase(), mark = new Array(src.length).fill(false);
    needles.filter(Boolean).forEach(nd => {
      const k = String(nd).toLowerCase(); let i = low.indexOf(k);
      while (i !== -1) { for (let j = i; j < i + k.length; j++) mark[j] = true; i = low.indexOf(k, i + k.length); }
    });
    let out = "", open = false;
    for (let i = 0; i < src.length; i++) {
      if (mark[i] && !open) { out += "<mark>"; open = true; }
      if (!mark[i] && open) { out += "</mark>"; open = false; }
      out += esc(src[i]);
    }
    return open ? out + "</mark>" : out;
  }

  /* ---------- state from events ---------- */
  const byNode = id => LC.events.filter(e => e.node === id);
  const hasOutcome = () => LC.events.some(e => e.node === "outcome");

  function nodeState(n, firstTaint, finished) {
    const evs = byNode(n.id);
    if (!evs.length) return {state:"idle", text:n.id === "outcome" ? "pending" : "waiting", count:0};
    const last = evs[evs.length - 1];
    const tainted = evs.some(isTainted);
    const exposed = !tainted && firstTaint !== null && evs[0].seq > firstTaint;
    const base = tainted ? "tainted" : exposed ? "exposed" : "clean";
    const res = c => ({state:c.state, text:c.text, count:evs.length});

    if (n.kraken) {
      const dec = evs.filter(e => e.phase === "decision").pop();
      if (!dec) return res({state:"active", text:"inspecting..."});
      const off = /disabled/i.test(dec.reason || "") || dec.reachable === false;
      if (dec.decision === "blocked" || dec.decision === "flagged")
        return res({state:"blocked", text:String(dec.decision).toUpperCase() + (dec.cache_hit ? " (cache)" : "")});
      if (off) return res({state:"off", text:dec.reachable === false ? "UNREACHABLE" : "OFF: passed"});
      if (isTainted(dec)) return res({state:"tainted", text:"MISSED the payload"});
      return res({state:"clean", text:"PASSED" + (dec.cache_hit ? " (cache)" : "")});
    }
    if (n.id === "entry") {
      const src = (evs.find(e => e.source) || {}).source;
      return res({state:tainted ? "tainted" : "clean", text:(src ? "via " + src : "input") + (tainted ? ", payload" : "")});
    }
    if (n.id === "store") {
      const ret = evs.filter(e => e.phase === "retrieved").pop();
      if (ret) return res({state:isTainted(ret) ? "tainted" : base, text:isTainted(ret) ? "payload retrieved" : "retrieved"});
      return res({state:base, text:tainted ? "payload planted" : "review saved"});
    }
    if (n.id === "outcome") {
      const o = evs.filter(e => e.phase === "result").pop() || last;
      if (o.outcome === "violation") return res({state:"tainted", text:"VIOLATION " + (o.discount_pct ?? "?") + "%"});
      if (o.outcome === "held") return res({state:"clean", text:"within policy"});
      if (o.outcome === "declined") return res({state:"clean", text:"declined"});
      if (o.outcome === "blocked") return res({state:"blocked", text:"STOPPED"});
      return res({state:base, text:"done"});
    }
    // agents
    if (evs.some(e => e.phase === "fallback")) return res({state:"off", text:"SCRIPTED FALLBACK"});
    if (evs.some(e => e.phase === "error")) return res({state:"off", text:"MODEL ERROR"});
    if (!finished && (last.phase === "in" || last.phase === "start"))
      return res({state:"active", text:"thinking..."});
    return res({state:base, text:tainted ? "carries payload" : exposed ? "after payload" : "responded"});
  }

  function compute() {
    const tainted = LC.events.filter(isTainted).map(e => e.seq);
    const firstTaint = tainted.length ? Math.min(...tainted) : null;
    const finished = hasOutcome();
    const st = {};
    NODES.forEach(n => st[n.id] = nodeState(n, firstTaint, finished));
    return st;
  }

  /* ---------- svg ---------- */
  function edgeGeom(a, b, kind) {
    const A = N[a], B = N[b];
    if (a === "kraken_in" && b === "store") {
      const sx = A.x + NW / 2, sy = A.y + NH, ex = B.x - 2, ey = B.y + NH / 2;
      return {d:`M${sx} ${sy} C${sx} ${ey}, ${sx + 24} ${ey}, ${ex} ${ey}`, lx:sx + 112, ly:ey + 15};
    }
    if (a === "store" && b === "negotiator") {
      const x = A.x + NW / 2, sy = A.y - 2, ey = B.y + NH + 3;
      return {d:`M${x} ${sy} L${x} ${ey}`, lx:x + 34, ly:(sy + ey) / 2};
    }
    const sx = A.x + NW, ex = B.x - 3, y = A.y + NH / 2;
    return {d:`M${sx} ${y} L${ex} ${y}`, lx:0, ly:0};
  }

  function svgHtml(st) {
    let s = `<svg viewBox="0 0 1000 270" class="lc-svg" role="img" aria-label="Attack lifecycle">`;
    s += `<defs>` + [["g","#1E8E5A"],["r","#C6403A"],["w","#B9770E"],["n","#C7D2E3"],["b","#2E5AAC"]].map(([k, c]) =>
      `<marker id="lc-ar-${k}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${c}"/></marker>`).join("") + `</defs>`;
    EDGES.forEach(([a, b, label]) => {
      const sa = st[a], sb = st[b], g = edgeGeom(a, b);
      let cls = "", mk = "n";
      if (sa.state === "blocked") { cls = "cut"; }
      else if (sb.state !== "idle" && sa.state !== "idle") {
        cls = sb.state === "tainted" ? "tainted" : sb.state === "exposed" ? "exposed" : "lit";
        mk = cls === "tainted" ? "r" : cls === "exposed" ? "w" : "g";
      }
      if (sb.state === "active" && sa.state !== "idle" && sa.state !== "blocked") { cls += " flow"; mk = "b"; }
      s += `<g class="lc-e ${cls}"><path d="${g.d}" marker-end="url(#lc-ar-${mk})"/>`;
      if (/flow/.test(cls)) {
        const col = /tainted/.test(cls) ? "#C6403A" : "#2E5AAC";
        s += `<circle r="4" fill="${col}"><animateMotion dur="1.1s" repeatCount="indefinite" path="${g.d}"/></circle>`;
      }
      if (label) s += `<text class="lc-el" x="${g.lx}" y="${g.ly}">${esc(label)}</text>`;
      s += `</g>`;
    });
    NODES.forEach(n => {
      const t = st[n.id];
      s += `<g class="lc-n ${t.state}${LC.sel === n.id ? " sel" : ""}" data-node="${n.id}" transform="translate(${n.x},${n.y})">
        <rect width="${NW}" height="${NH}" rx="10"/>
        <text class="t1" x="${NW / 2}" y="24">${esc(n.label)}</text>
        <text class="t2" x="${NW / 2}" y="41">${esc(t.text)}</text>
        <text class="t3" x="${NW / 2}" y="55">${t.count ? t.count + (t.count === 1 ? " event" : " events") : ""}</text></g>`;
    });
    return s + `</svg>`;
  }

  /* ---------- panels ---------- */
  function tiersHtml(tiers) {
    const rows = [];
    const T = tiers || {};
    if (T.cache) rows.push(["Signature cache", T.cache.hit ? "HIT" : "miss", T.cache.elapsed_ms]);
    if (T.regex) rows.push(["Regex patterns", T.regex.flagged ? "matched " + (T.regex.matches || []).length : "clean", T.regex.elapsed_ms]);
    if (T.classifier) rows.push(["Classifier", "score " + T.classifier.score, T.classifier.elapsed_ms]);
    if (T.llm_judge) rows.push(["LLM judge", T.llm_judge.available === false ? "unavailable" : (T.llm_judge.is_injection ? "injection" : "clean"), T.llm_judge.elapsed_ms]);
    if (!rows.length) return "";
    return `<table class="lc-tiers"><tr><th>Tier</th><th>Result</th><th>ms</th></tr>` +
      rows.map(r => `<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td>${r[2] ?? "-"}</td></tr>`).join("") + `</table>`;
  }

  function cardHtml(ev) {
    const needles = (ev.markers || []).concat(LC.job && LC.job.payload ? [LC.job.payload.trim()] : []);
    const bad = isTainted(ev);
    let h = `<div class="lc-card${bad ? " bad" : ""}"><div class="lc-card-h"><span class="ph">${esc(PHASE[ev.phase] || ev.phase)}</span><b>${esc(ev.title)}</b><span class="ts">${esc(ev.ts)}</span></div>`;
    if (ev.peer) h += `<div class="lc-peer">${ev.phase === "in" ? "from" : "to"}: ${esc(ev.peer)}</div>`;
    if (ev.content) h += `<pre class="lc-pre">${hl(ev.content, needles)}</pre>`;
    if (ev.phase === "decision") {
      h += tiersHtml(ev.tiers);
      if (ev.reason) h += `<div class="lc-reason"><b>Reason:</b> ${esc(ev.reason)}</div>`;
    }
    if (ev.outcome === "violation" || ev.outcome === "held")
      h += `<div class="lc-reason">Final price <b>$${esc(ev.final_price ?? "?")}</b>, discount <b>${esc(ev.discount_pct ?? "?")}%</b>, policy limit ${esc(ev.policy_max ?? "?")}%.</div>`;
    if (ev.phase === "retrieved" && ev.note) h += `<div class="lc-peer">${esc(ev.note)}</div>`;
    return h + `</div>`;
  }

  function evClass(ev) {
    if (ev.phase === "fallback" || ev.phase === "error") return "warn";
    if (ev.phase === "decision") {
      if (ev.decision === "blocked" || ev.decision === "flagged") return "stop";
      return isTainted(ev) ? "bad" : "ok";   // forwarded text that carries the payload = Kraken missed it (or is off)
    }
    if (ev.phase === "result") return ev.outcome === "violation" ? "bad" : ev.outcome === "blocked" ? "stop" : "ok";
    return isTainted(ev) ? "bad" : "";
  }

  function feedHtml() {
    if (!LC.events.length) return "";
    const lastSeq = LC.events[LC.events.length - 1].seq;
    return LC.events.map(ev => `<div class="lc-ev ${evClass(ev)}${ev.seq === lastSeq ? " cur" : ""}" data-node="${ev.node}">
      <span class="ts">${esc(ev.ts)}</span><span class="tag">${esc(TAG[ev.node] || ev.node)}</span><span>${esc(ev.title)}</span></div>`).join("");
  }

  function detailHtml(st) {
    const id = LC.sel;
    if (!id || !N[id]) return `<div class="lc-empty">Click a step in the diagram to see exactly what it received and produced.</div>`;
    const evs = byNode(id);
    let h = `<div class="lc-info"><b>${esc(N[id].label)}.</b> ${esc(INFO[id] || "")}</div>`;
    if (!evs.length) return h + `<div class="lc-empty">Nothing has reached this step yet.</div>`;
    return h + evs.map(cardHtml).join("");
  }

  /* ---------- header ---------- */
  function headerState() {
    const j = LC.job, running = j && j.status === "running";
    let title = "No attack running", sub = "Start one from the Live attack runner, or place an order in MarketFlow. This view follows it live.";
    if (running) {
      title = j.label;
      sub = `Trial ${j.trial || 1} of ${j.trials}. Fired from the live attack runner.`;
    } else if (LC.events.length) {
      const src = (LC.events.find(e => e.node === "entry" && e.source) || {}).source;
      title = j ? `Last run: ${j.label}` : "Run in MarketFlow";
      sub = src ? `Payload entered through the ${src} field.` : "Showing the most recent run.";
    }
    let pill = ["Idle", ""];
    if (LC.reach === false) pill = ["MarketFlow offline", "bad"];
    else if (LC.note) pill = ["No live feed", "warn"];
    else if (running) pill = ["Running", "live"];
    else if (LC.events.length && hasOutcome()) pill = ["Run complete", "live"];
    else if (LC.events.length) pill = ["In progress", "live"];
    return {title, sub, pill};
  }

  function render() {
    const root = document.getElementById("lc-overlay");
    if (!root) return;
    const hs = headerState();
    root.querySelector("#lc-title").textContent = hs.title;
    root.querySelector("#lc-sub").textContent = hs.sub;
    const pill = root.querySelector("#lc-pill"); pill.textContent = hs.pill[0]; pill.className = "lc-pill " + hs.pill[1];
    const dp = root.querySelector("#lc-def");
    dp.textContent = LC.defenseOn == null ? "Kraken: ?" : "Kraken: " + (LC.defenseOn ? "ON" : "OFF");
    dp.className = "lc-pill " + (LC.defenseOn ? "live" : "");

    const st = compute();
    if (LC.follow && LC.events.length) {
      const lastNode = [...LC.events].reverse().find(e => N[e.node]);
      if (lastNode) LC.sel = lastNode.node;
    }
    const sig = JSON.stringify(NODES.map(n => [st[n.id].state, st[n.id].text, st[n.id].count])) + "|" + LC.sel;
    if (sig !== LC.sig) {
      LC.sig = sig;
      root.querySelector("#lc-svg").innerHTML = svgHtml(st);
      root.querySelectorAll("#lc-svg .lc-n").forEach(g => g.onclick = () => { LC.follow = false; root.querySelector("#lc-follow").checked = false; LC.sel = g.dataset.node; LC.sig = ""; render(); });
    }
    const feed = root.querySelector("#lc-feed"), det = root.querySelector("#lc-detail");
    const evSig = LC.events.length + ":" + (LC.events.length ? LC.events[LC.events.length - 1].seq : 0) + ":" + LC.sel;
    if (evSig !== LC.selSig) {
      LC.selSig = evSig;
      const atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
      feed.innerHTML = feedHtml() || `<div class="lc-empty">${emptyMessage()}</div>`;
      if (atBottom) feed.scrollTop = feed.scrollHeight;
      feed.querySelectorAll(".lc-ev").forEach(r => r.onclick = () => { if (N[r.dataset.node]) { LC.follow = false; root.querySelector("#lc-follow").checked = false; LC.sel = r.dataset.node; LC.sig = ""; LC.selSig = ""; render(); } });
      const dBottom = det.scrollTop + det.clientHeight >= det.scrollHeight - 30;
      det.innerHTML = LC.events.length ? detailHtml(st) : `<div class="lc-empty">${emptyMessage()}</div>`;
      if (dBottom || LC.follow) det.scrollTop = det.scrollHeight;
    }
  }

  function emptyMessage() {
    if (LC.reach === false) return "MarketFlow is not running on port 8001, so there is nothing to follow.";
    if (LC.note) return esc(LC.note);
    if (LC.err) return "Could not load the live feed: " + esc(LC.err);
    return "Waiting for a run. Start an attack from the Live attack runner and this fills in as it happens.";
  }

  /* ---------- polling ---------- */
  function ingest(list) {
    list.forEach(ev => {
      if (LC.seen.has(ev.seq)) return;
      LC.seen.add(ev.seq);
      if (ev.node === "env" && ev.phase === "reset") { LC.events = []; LC.sel = null; LC.sig = ""; LC.selSig = ""; }
      if (ev.node === "env" && ev.phase === "run" && hasOutcome()) { LC.events = []; LC.sel = null; LC.sig = ""; LC.selSig = ""; }
      LC.events.push(ev);
    });
  }

  async function poll() {
    if (!LC.open) return;
    try {
      const r = await fetch("/api/lifecycle?since=" + LC.since);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      LC.reach = d.marketflow_live; LC.job = d.job; LC.defenseOn = d.defense_on; LC.note = d.note || ""; LC.err = "";
      if (d.next < LC.since) { LC.events = []; LC.seen = new Set(); LC.since = -1; LC.sig = ""; LC.selSig = ""; }  // MarketFlow restarted
      else { ingest(d.events || []); LC.since = d.next; }
    } catch (e) { LC.err = e.message; }
    try { render(); } catch (e) { console.error("Live Cycle render failed", e); }
    if (LC.open) LC.timer = setTimeout(poll, 1000);
  }

  /* ---------- modal ---------- */
  function build() {
    if (document.getElementById("lc-overlay")) return;
    const o = document.createElement("div");
    o.id = "lc-overlay"; o.className = "lc-overlay"; o.hidden = true;
    o.innerHTML = `<div class="lc-modal" role="dialog" aria-label="Live Cycle">
      <div class="lc-head">
        <div><div class="eyebrow">Live Cycle</div><h2 id="lc-title">No attack running</h2><div class="lc-sub" id="lc-sub"></div></div>
        <div class="lc-spacer">
          <span class="lc-pill" id="lc-def">Kraken: ?</span><span class="lc-pill" id="lc-pill">Idle</span>
          <label class="lc-follow"><input type="checkbox" id="lc-follow" checked /> Follow live</label>
          <button class="lc-close" id="lc-close" aria-label="Close">&times;</button>
        </div></div>
      <div class="lc-body">
        <div class="lc-diagram"><div id="lc-svg"></div>
          <div class="lc-legend">
            <span style="--c:#1E8E5A">Clean</span><span style="--c:#C6403A">Carries the payload</span>
            <span style="--c:#B9770E">Came after the payload</span><span style="--c:#2E5AAC">Working now / stopped by Kraken</span>
            <span style="--c:#8A97AB">Kraken off or fallback</span><span style="--c:#C7D2E3">Not reached</span></div></div>
        <div class="lc-split">
          <div class="lc-panel"><h3>Timeline</h3><div class="lc-scroll" id="lc-feed"></div></div>
          <div class="lc-panel"><h3>What this step saw</h3><div class="lc-scroll" id="lc-detail"></div></div></div>
        <div class="lc-note">Every event comes from a real call inside MarketFlow. Red highlights mark the injection text (known payload or known trigger phrases), so a reworded payload can pass through without being highlighted.</div>
      </div></div>`;
    document.body.appendChild(o);
    o.addEventListener("mousedown", e => { if (e.target === o) close(); });
    o.querySelector("#lc-close").onclick = close;
    o.querySelector("#lc-follow").onchange = e => { LC.follow = e.target.checked; LC.sig = ""; LC.selSig = ""; render(); };
    document.addEventListener("keydown", e => { if (e.key === "Escape" && LC.open) close(); });
  }

  function open() {
    build();
    Object.assign(LC, {open:true, since:-1, events:[], seen:new Set(), sel:null, follow:true, sig:"", selSig:"", err:""});
    const o = document.getElementById("lc-overlay");
    o.hidden = false; o.querySelector("#lc-follow").checked = true;
    clearTimeout(LC.timer); render(); poll();
  }
  function close() {
    LC.open = false; clearTimeout(LC.timer);
    const o = document.getElementById("lc-overlay"); if (o) o.hidden = true;
  }

  /* ---------- button on the dashboard page ---------- */
  function inject() {
    const box = document.querySelector("#live-root .livebox");
    if (!box || box.querySelector("#lc-open")) return;
    const h3 = box.querySelector("h3");
    const row = document.createElement("div"); row.className = "lc-row";
    h3.parentNode.insertBefore(row, h3); row.appendChild(h3);
    const b = document.createElement("button");
    b.id = "lc-open"; b.className = "btn btn-primary lc-btn"; b.type = "button";
    b.innerHTML = `<span class="lc-dot"></span>Live Cycle`;
    b.title = "Watch the current attack move through the agents, live";
    b.onclick = open; row.appendChild(b);
  }

  const origShowView = window.showView;
  window.showView = function (name) {
    const r = origShowView.apply(this, arguments);
    if (name === "dashboard") inject(); else close();
    return r;
  };

  // pulse the button while a run started from the live runner is in progress
  setInterval(() => {
    const b = document.getElementById("lc-open");
    if (!b) return;
    let on = false;
    try { on = !!_liveJob; } catch (e) { on = false; }
    b.classList.toggle("running", on);
  }, 1000);

  window.KrakenLiveCycle = {open, close};
})();
