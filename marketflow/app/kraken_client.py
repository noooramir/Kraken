"""
Inline call-out to Kraken's real detection API (/api/inspect). This is what
turns Kraken from "a dashboard that replays canned attacks against
MarketFlow from outside" into an actual inline defense: MarketFlow calls
this at every real injection point (review submission, goal/notes, and the
Negotiator->Orchestrator handoff) on REAL user input, not a fixed payload.

Fails OPEN if Kraken isn't running -- MarketFlow must keep working as an
undefended baseline when Kraken is off/down, exactly like the untouched
attack surface you already have. The failure is always visible in the
returned dict (`kraken_reachable: False`), never silent.
"""
import httpx

KRAKEN_URL = "http://127.0.0.1:8002"
TIMEOUT = 2.0


def inspect(text: str, checkpoint: str):
    if not text:
        return {"decision": "forwarded", "reason": "(empty)", "tiers": {}, "kraken_reachable": True, "checkpoint": checkpoint}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(f"{KRAKEN_URL}/api/inspect", json={"text": text, "checkpoint": checkpoint})
            if r.status_code == 200:
                result = r.json()
                result["kraken_reachable"] = True
                result["checkpoint"] = checkpoint
                return result
    except Exception:
        pass
    return {"decision": "forwarded", "reason": "Kraken unreachable -- failed open, request not inspected.",
            "tiers": {}, "kraken_reachable": False, "checkpoint": checkpoint}
