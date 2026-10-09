import os
import time
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

from . import payloads, detectors, state, marketflow_client

load_dotenv()

app = FastAPI(title="Kraken", description="AI-security layer detecting and mitigating prompt injection across MarketFlow's 4 locked attack types")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Compute an honest false-positive rate once at startup against a fixed,
# non-malicious sample set (see detectors.BENIGN_SAMPLES).
try:
    state.STATE["false_positive_rate"] = detectors.compute_false_positive_rate()
except Exception:
    state.STATE["false_positive_rate"] = None


@app.get("/api/meta")
def meta():
    return {
        "marketflow_live": marketflow_client.is_marketflow_live(),
        "defense_on": state.STATE["defense_on"],
    }


@app.get("/api/attack-types")
def attack_types():
    return list(payloads.ATTACK_TYPES.values())


@app.get("/api/citations")
def citations():
    return payloads.CITATIONS


# ---------------------------------------------------------------------------
# OFFENSE -- Attack Simulator
# ---------------------------------------------------------------------------

class SimulateReq(BaseModel):
    attack_type: str
    custom_payload: Optional[str] = None
    product_id: Optional[str] = None


SCAN_STEPS = {
    "direct": [
        "Scanning input for override patterns...",
        "Checking against known jailbreak signatures...",
        "Evaluating instruction-hijack likelihood...",
    ],
    "indirect": [
        "Scanning secondary fields (notes, metadata)...",
        "Cross-referencing against primary instruction...",
        "Evaluating hidden-instruction likelihood...",
    ],
    "rag": [
        "Scanning retrieved content (reviews)...",
        "Comparing against known poisoning patterns...",
        "Checking retrieval-to-agent trust boundary...",
    ],
    "cross_agent": [
        "Tracing agent-to-agent handoff (Negotiator -> Orchestrator -> Checkout)...",
        "Checking for unverified instruction forwarding...",
        "Confirming propagation path...",
    ],
}
SCAN_PCTS = [20, 55, 85]


@app.post("/api/simulate")
def simulate(req: SimulateReq):
    spec = payloads.ATTACK_TYPES.get(req.attack_type)
    if not spec:
        return {"error": "unknown attack type"}

    text = req.custom_payload if req.custom_payload else spec["payload_text"]
    is_custom = bool(req.custom_payload)
    r1 = detectors.regex_check(text)
    c2 = detectors.classifier_score(text, r1["matches"])

    live = marketflow_client.is_marketflow_live()
    mf_result = None
    source = "recorded"
    if live:
        try:
            mf_result = marketflow_client.forward_attack(req.attack_type, custom_payload=req.custom_payload,
                                                           product_id=req.product_id)
            source = "live"
        except Exception as e:
            mf_result = None
            source = f"live-failed ({type(e).__name__}) -- no result, NOT substituting recorded numbers"
    elif is_custom:
        # A custom payload has no recorded reference outcome -- don't pretend
        # to have one, be upfront that we couldn't actually test it live.
        source = "unavailable (MarketFlow offline, no recorded reference exists for a custom payload)"

    ref = payloads.RECORDED_REFERENCE[req.attack_type]
    live_ok = mf_result is not None and "error" not in mf_result
    if live_ok:
        # ALWAYS report the live result, including when the agents resisted
        # (order is None). Previously a resisted attack fell through to the
        # hardcoded 90% reference and was shown as a successful exploit.
        order = mf_result.get("order") or {}
        outcome = {
            "final_price": order.get("final_price"),
            "discount_pct": order.get("discount_pct"),
            "list_price": mf_result.get("product", {}).get("list_price"),
            "violations": mf_result.get("violations", []),
            "trace": mf_result.get("trace", []),
            "order_placed": bool(mf_result.get("order")),
            "fallback_used": mf_result.get("fallback_used", []),
        }
        if outcome["fallback_used"]:
            source = f"live-CONTAMINATED (scripted fallback used by: {', '.join(outcome['fallback_used'])})"
    elif live:
        outcome = {
            "final_price": None, "discount_pct": None, "list_price": None,
            "violations": [], "trace": [], "order_placed": False,
            "note": "Live run failed or returned an error; no result reported.",
            "error": mf_result,
        }
    elif is_custom:
        # Never fabricate an outcome for a payload we never actually validated.
        outcome = {
            "final_price": None, "discount_pct": None, "list_price": None,
            "violations": [], "trace": [],
            "note": "No live result and no recorded reference exists for a custom payload -- run MarketFlow live to get a real outcome.",
        }
    else:
        outcome = {
            "final_price": ref["final_price"],
            "discount_pct": ref["discount_pct"],
            "list_price": ref["list_price"],
            "violations": [ref["violation"]],
            "trace": [],
        }

    # Risk score: base per type + regex/classifier signal + violation bonus
    base = {"direct": 55, "indirect": 60, "rag": 65, "cross_agent": 70}[req.attack_type]
    score = base + len(r1["matches"]) * 5 + round(c2["score"] * 15)
    if outcome["violations"]:
        score += 15
    score = max(0, min(100, score))

    finding = ref["finding"]
    if live_ok and not is_custom:
        if outcome["fallback_used"]:
            finding = "INVALID RUN: at least one agent used a scripted fallback. Do not report this as a result."
        elif outcome["violations"]:
            finding = "Live result: policy violated -- " + outcome["violations"][0] + " (compare with the no-attack control rate before calling this an exploit)"
        else:
            finding = "Live result: no policy violation (agents resisted, or no order was placed)."
    elif live and not is_custom:
        finding = "Live run failed; no finding."

    return {
        "attack_type": req.attack_type,
        "label": spec["label"],
        "checkpoint": spec["checkpoint"],
        "steps": SCAN_STEPS[req.attack_type],
        "pcts": SCAN_PCTS,
        "risk_score": score,
        "finding": finding if not is_custom else "Custom payload -- risk score is a live regex/classifier estimate, not the locked reference finding.",
        "payload": text,
        "is_custom_payload": is_custom,
        "outcome": outcome,
        "target": {"live": live, "source": source},
    }


# ---------------------------------------------------------------------------
# DEFENSE -- Live Enforcement
# ---------------------------------------------------------------------------

@app.post("/api/defense/toggle")
def toggle_defense():
    state.STATE["defense_on"] = not state.STATE["defense_on"]
    return {"defense_on": state.STATE["defense_on"]}


@app.get("/api/defense/tally")
def defense_tally():
    return state.STATE


@app.get("/api/evidence")
def evidence_log():
    return state.EVIDENCE_LOG


@app.post("/api/defense/reset")
def defense_reset():
    state.reset_tallies()
    marketflow_client.reset_marketflow()
    return {"ok": True}


# ---------------------------------------------------------------------------
# INLINE MIDDLEWARE API -- the real "WAF for agentic AI" endpoint. Any
# external system (MarketFlow, or any other agent app) can call this to have
# arbitrary text checked by Kraken's tiered pipeline BEFORE acting on it.
# This is what makes Kraken an actual inline defense instead of a standalone
# attack-replay demo: MarketFlow calls this for real, on real user input.
# ---------------------------------------------------------------------------

class InspectReq(BaseModel):
    text: str
    checkpoint: str = "unknown"  # e.g. "handoff" (goal/notes), "retrieval" (review)


@app.post("/api/inspect")
def inspect(req: InspectReq):
    if not state.STATE["defense_on"]:
        entry = state.record_defense_run(req.checkpoint, req.checkpoint, "forwarded", False,
                                          "Kraken is disabled -- request passed through unchecked.", {})
        return {"decision": "forwarded", "cache_hit": False,
                "reason": "Kraken is disabled -- request passed through unchecked.",
                "tiers": {}, "evidence_id": entry["id"]}

    result = detectors.run_tiered_pipeline(req.text, state.SIGNATURE_CACHE,
                                           force_llm=(req.checkpoint == "retrieval"))
    entry = state.record_defense_run(req.checkpoint, req.checkpoint, result["decision"], result["cache_hit"],
                                      result["reason"], result["tiers"])
    return {
        "decision": result["decision"],
        "cache_hit": result["cache_hit"],
        "reason": result["reason"],
        "tiers": result["tiers"],
        "evidence_id": entry["id"],
    }


class DefenseRunReq(BaseModel):
    attack_type: str
    forward_to_marketflow: bool = True
    custom_payload: Optional[str] = None
    product_id: Optional[str] = None


@app.post("/api/defense/run")
def defense_run(req: DefenseRunReq):
    spec = payloads.ATTACK_TYPES.get(req.attack_type)
    if not spec:
        return {"error": "unknown attack type"}
    text = req.custom_payload if req.custom_payload else spec["payload_text"]
    checkpoint = spec["checkpoint"]

    if not state.STATE["defense_on"]:
        decision, cache_hit, reason, tiers = "forwarded", False, "Kraken is disabled -- request passed through unchecked.", {}
    else:
        result = detectors.run_tiered_pipeline(text, state.SIGNATURE_CACHE, force_llm=(checkpoint == "retrieval"))
        decision, cache_hit, reason, tiers = result["decision"], result["cache_hit"], result["reason"], result["tiers"]

    mf_result = None
    live = marketflow_client.is_marketflow_live()
    if req.forward_to_marketflow and decision != "blocked" and live:
        try:
            mf_result = marketflow_client.forward_attack(req.attack_type, custom_payload=req.custom_payload,
                                                           product_id=req.product_id)
        except Exception:
            mf_result = None

    entry = state.record_defense_run(req.attack_type, checkpoint, decision, cache_hit, reason, tiers,
                                      marketflow_result=mf_result)

    return {
        "checkpoint": checkpoint,
        "decision": decision,
        "cache_hit": cache_hit,
        "reason": reason,
        "tiers": tiers,
        "defense_on": state.STATE["defense_on"],
        "marketflow_live": live,
        "marketflow_result": mf_result,
        "tally": state.STATE,
        "evidence_id": entry["id"],
    }


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
