"""
Cross-agent propagation log.

trace.RunTrace only lives for the duration of ONE /api/run call, then it's
gone -- there is no way to look back and see "that review I planted three
runs ago just got another innocent customer's order poisoned again." This
module is that missing persistent record: every time a (possibly injected)
piece of content -- a planted review, a goal string, a gift note -- actually
reaches the Negotiator/Orchestrator/Checkout chain, we log which agents it
passed through and what it caused, keyed back to its original source so you
can trace one poisoned artifact across every run it ever touched.
"""
import time
import itertools
from .trace import detect_markers

_event_id = itertools.count(1)
PROPAGATION_LOG = []  # newest first


def record_propagation(run_id, product_id, source_type, source_id, source_text, hops,
                        order_id=None, discount_pct=None, approved=None):
    """
    source_type: "review" | "goal" | "notes" -- which field this content entered through
    source_id:   the review's id for "review" sources, else None
    hops:        ordered list of agent names this content's influence passed through
                 for THIS run, e.g. ["negotiator_agent", "orchestrator_agent", "checkout_agent"]
    """
    markers = detect_markers(source_text)
    entry = {
        "id": next(_event_id),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": run_id,
        "product_id": product_id,
        "source_type": source_type,
        "source_id": source_id,
        "source_text": source_text,
        "injected_markers": markers,
        "is_suspected_injection": len(markers) > 0,
        "hops": hops,
        "order_id": order_id,
        "discount_pct": discount_pct,
        "approved": approved,
    }
    PROPAGATION_LOG.insert(0, entry)
    return entry


def blast_radius(source_type: str, source_id):
    """Every propagation event traceable back to one planted source (e.g. one
    poisoned review id), across every run it has touched since it was planted
    -- the actual answer to 'how many customers did this one review hit.'"""
    events = [
        e for e in PROPAGATION_LOG
        if e["source_type"] == source_type and str(e["source_id"]) == str(source_id)
    ]
    orders_affected = [e["order_id"] for e in events if e.get("order_id") is not None]
    return {
        "source_type": source_type,
        "source_id": source_id,
        "runs_touched": len(events),
        "orders_affected": orders_affected,
        "orders_affected_count": len(orders_affected),
        "events": events,
    }


def all_sources_summary():
    """One row per distinct (source_type, source_id) seen, with blast radius --
    the 'which planted artifacts are actively propagating' overview."""
    seen = {}
    for e in PROPAGATION_LOG:
        key = (e["source_type"], e["source_id"])
        if key not in seen:
            seen[key] = {"source_type": e["source_type"], "source_id": e["source_id"],
                         "runs_touched": 0, "orders_affected": 0, "is_suspected_injection": e["is_suspected_injection"]}
        seen[key]["runs_touched"] += 1
        if e.get("order_id") is not None:
            seen[key]["orders_affected"] += 1
    return list(seen.values())


def reset():
    PROPAGATION_LOG.clear()
