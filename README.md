# Kraken PoC — Running Instructions

## What's here
- `marketflow/` — the vulnerable-by-default 5-agent e-commerce system, INCLUDING the
  customer-facing storefront (chat-driven shopping UI) at http://localhost:8001
- `kraken/` — the red-teaming dashboard + attack engine at http://localhost:8002

## Setup
```bash
pip install fastapi uvicorn scikit-learn numpy pydantic httpx python-multipart
```

## Run (two terminals)
```bash
# Terminal 1 — the target e-commerce site
cd marketflow && uvicorn app.main:app --host 0.0.0.0 --port 8001

# Terminal 2 — the red-teaming dashboard
cd kraken && uvicorn app.main:app --host 0.0.0.0 --port 8002
```

Open **http://localhost:8001** — this is the MarketFlow storefront (what a real customer sees).
Open **http://localhost:8002** — this is the Kraken dashboard (what you use to attack it).

## MarketFlow Storefront (localhost:8001)
- Product catalog on the left, chat-driven "Buyer Assistant" on the right
- Try: "negotiate sku-001 to $100", "buy sku-002", "checkout"
- Every chat action is a REAL call into the live agent pipeline (Buyer → Orchestrator →
  Negotiation/Invoice/Inventory agents) — not a scripted demo bot
- sku-003 (Hydraulic Pump) has a hidden catalog-poisoning payload baked in for UC7 demos —
  negotiate on it and watch the discount get auto-applied

## Kraken Dashboard (localhost:8002) tour
1. **Overview** — target identity, agent count, live session count
2. **Threat Model** — trust boundaries + STRIDE/OWASP catalog
3. **Attack Console** — run any of UC1-UC7 baseline or defended, live status + evidence
4. **Agent Activity** — raw gray-box call log across all agents
5. **Memory / Handoff Inspector** — actual vector DB entries + handoff logs
6. **Defense Comparison** — toggle defenses live, see before/after attack success rate

## Suggested demo flow for your panel
1. Open MarketFlow storefront, negotiate normally on sku-001 — show it behaves like a normal
   shopping assistant
2. Switch to Kraken, run UC2 (Memory/Retrieval Poisoning) baseline — show the exploit succeed
3. Go back to MarketFlow, open a NEW session, negotiate on the same product — show the poisoned
   discount get applied to an innocent customer
4. Back in Kraken, toggle the UC2 defense on, re-run — show it now gets blocked
5. Show the Defense Comparison chart with real before/after data

## What's real vs. what's a stand-in (be upfront about this in your defense)
- All 7 use cases are REAL exploits against REAL agent logic and REAL memory — not staged.
- Negotiation memory retrieval uses TF-IDF + cosine similarity (scikit-learn) instead of a
  neural embedding model, since this build environment has no network access to download
  model weights. Swap in `sentence-transformers` for a production version — same mechanism,
  same vulnerability class.
- Agent "reasoning" is rule-based (regex/heuristic) rather than a live LLM call, so the whole
  system runs offline and deterministically for demo purposes — a reasonable, explicitly
  documented PoC scoping decision.
- MCP proxy layer is simulated as an in-process call log (`marketflow/app/proxy.py`).
- Docker sandboxing / arbitrary-agent-upload is NOT implemented in this PoC (documented as
  future work in the Kraken PoC Spec).

## Quick smoke test via curl
```bash
curl -X POST localhost:8002/api/attack/run_all?defended=false   # all 7 should succeed
curl -X POST localhost:8002/api/attack/run_all?defended=true    # all 7 should be blocked
```
