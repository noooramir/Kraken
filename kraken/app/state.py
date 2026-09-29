"""In-memory runtime state for Kraken -- tallies, signature cache, evidence log."""
import time
import itertools

STATE = {
    "defense_on": True,
    "blocked": 0,
    "flagged": 0,
    "forwarded": 0,
    "cache_hits": 0,
    "total": 0,
    "false_positive_rate": None,  # computed at startup, see main.py
}

SIGNATURE_CACHE = {}
EVIDENCE_LOG = []
_evidence_id = itertools.count(1)


def record_defense_run(attack_type, checkpoint, decision, cache_hit, reason, tiers, marketflow_result=None):
    STATE["total"] += 1
    if cache_hit:
        STATE["cache_hits"] += 1
    if decision == "blocked":
        STATE["blocked"] += 1
    elif decision == "flagged":
        STATE["flagged"] += 1
    else:
        STATE["forwarded"] += 1

    entry = {
        "id": next(_evidence_id),
        "ts": time.strftime("%H:%M:%S"),
        "attack_type": attack_type,
        "checkpoint": checkpoint,
        "decision": decision,
        "cache_hit": cache_hit,
        "reason": reason,
        "tiers": tiers,
        "defense_on": STATE["defense_on"],
        "marketflow_result": marketflow_result,
    }
    EVIDENCE_LOG.insert(0, entry)
    EVIDENCE_LOG[:] = EVIDENCE_LOG[:50]
    return entry


def reset_tallies():
    STATE["blocked"] = 0
    STATE["flagged"] = 0
    STATE["forwarded"] = 0
    STATE["cache_hits"] = 0
    STATE["total"] = 0
    SIGNATURE_CACHE.clear()
    EVIDENCE_LOG.clear()
