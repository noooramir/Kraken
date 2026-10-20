"""
Live Cycle API for the Kraken dashboard.

GET /api/lifecycle?since=N returns the step-by-step events MarketFlow records
while a request travels through its agents (proxied from MarketFlow's
/api/live-feed), plus info about the live attack currently running from the
dashboard. Nothing here is simulated: if MarketFlow is not running or has no
live feed, the response says so and returns no events.
"""
import httpx
from fastapi import APIRouter

from . import live_runs, payloads, state

router = APIRouter()


def _payload_text(job):
    """The exact injection text this job is firing, so the UI can highlight it
    wherever it shows up in the agents' context."""
    try:
        atk = job["attack_type"]
        if atk == "control":
            return ""
        if atk in ("rag", "cross_agent"):
            text = payloads.RAG_VARIANTS.get(job["variant"], payloads.RAG_VARIANTS["authority-a"])
        else:
            text = payloads.ATTACK_TYPES[atk]["payload_text"]
        return payloads.payload_for(atk, text, job.get("product"))      # the same text forward_attack really sends
    except Exception:
        return ""


def _job_meta():
    jobs = list(live_runs._JOBS.values())
    if not jobs:
        return None
    job = next((j for j in reversed(jobs) if j["status"] == "running"), jobs[-1])
    last = next((l for l in reversed(list(job["lines"]))
                 if l["kind"] in ("success", "fail", "blocked", "invalid", "error")), None)
    return {
        "id": job["id"],
        "status": job["status"],
        "attack_type": job["attack_type"],
        "variant": job["variant"],
        "label": job.get("label") or live_runs.LABELS.get(job["attack_type"], job["attack_type"]),
        "trial": job.get("trial"),
        "trials": job["trials"],
        "payload": _payload_text(job),
        "product": (job.get("product") or {}).get("name"),
        "last_result": last,
    }


@router.get("/api/lifecycle")
def lifecycle(since: int = -1):
    out = {
        "marketflow_live": False,
        "events": [],
        "next": max(since, 0),
        "defense_on": state.STATE["defense_on"],
        "job": _job_meta(),
        "note": "",
    }
    try:
        r = httpx.get(f"{payloads.MARKETFLOW_URL}/api/live-feed", params={"since": since}, timeout=3.0)
        if r.status_code == 200:
            d = r.json()
            out.update(marketflow_live=True, events=d.get("events", []), next=d.get("next", 0))
        else:
            out["marketflow_live"] = True
            out["note"] = ("MarketFlow is running but has no live feed yet. "
                           "Add live_feed.py to MarketFlow and restart it.")
    except Exception:
        pass
    return out
