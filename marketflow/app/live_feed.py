"""
Live Cycle feed for MarketFlow.

A read-only observer. It records every step a request takes through
MarketFlow (entry -> Kraken checkpoint -> Buyer -> review retrieval ->
Negotiator -> Kraken handoff -> Orchestrator -> Checkout -> outcome) into an
in-memory list, and serves it at GET /api/live-feed so Kraken's dashboard can
animate the run while it happens.

It never changes what MarketFlow does: it wraps a few functions in place and
re-raises anything they raise. Every event comes from a real call, nothing is
scripted. If this module breaks, MarketFlow still behaves exactly as before
(each hook is wrapped in try/except).

Hooked in with two lines at the end of app/main.py:
    from . import live_feed
    live_feed.install(app)
"""
import functools
import itertools
import json
import threading
import time

from fastapi import APIRouter

MAX_EVENTS = 3000
MAX_CONTENT = 1400

_lock = threading.Lock()
_seq = itertools.count(1)
FEED = []
_tl = threading.local()
_installed = False
router = APIRouter()

NODE_OF_AGENT = {
    "buyer_agent": "buyer",
    "negotiator_agent": "negotiator",
    "orchestrator_agent": "orchestrator",
    "checkout_agent": "checkout",
}


def emit(node, phase, title, content="", run_id=None, **extra):
    """Append one event. node: entry|kraken_in|buyer|store|negotiator|
    kraken_hand|orchestrator|checkout|outcome|env."""
    try:
        from .trace import detect_markers
        text = "" if content is None else str(content)
        ev = {
            "ts": time.strftime("%H:%M:%S"),
            "run_id": run_id,
            "node": node,
            "phase": phase,
            "title": title,
            "content": text[:MAX_CONTENT] + ("..." if len(text) > MAX_CONTENT else ""),
            "markers": detect_markers(text),
        }
        ev.update(extra)
        with _lock:
            ev["seq"] = next(_seq)
            FEED.append(ev)
            if len(FEED) > MAX_EVENTS:
                del FEED[: len(FEED) - MAX_EVENTS]
        return ev
    except Exception:
        return None


@router.get("/api/live-feed")
def live_feed(since: int = -1):
    """since < 0: everything from the most recent environment reset onward
    (so a viewer who opens mid-run still sees the whole run). since >= 0:
    only events with seq > since."""
    with _lock:
        if since < 0:
            start = 0
            for i in range(len(FEED) - 1, -1, -1):
                if FEED[i]["phase"] == "reset":
                    start = i
                    break
            events = list(FEED[start:])
        else:
            events = [e for e in FEED if e["seq"] > since]
        nxt = FEED[-1]["seq"] if FEED else 0
    return {"events": events, "next": nxt}


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

def _policy_max():
    try:
        from . import store
        return float(store.POLICY["max_discount_pct"])
    except Exception:
        return 10.0


def _on_trace(run_id, entry):
    node = NODE_OF_AGENT.get(entry["agent"])
    if node is None:
        return  # Kraken hops are recorded by the inspect() hook
    direction, peer = entry["direction"], str(entry["peer"])
    content, note = entry["content"], entry.get("note", "")

    if node == "negotiator" and direction == "input" and peer.startswith("review store"):
        emit("store", "retrieved", "Top reviews retrieved by TF-IDF similarity", content,
             run_id=run_id, note=note)
        return

    emit(node, "in" if direction == "input" else "out",
         note or ("Input to model" if direction == "input" else "Model output"),
         content, run_id=run_id, peer=peer)

    if node == "buyer" and direction == "output" and peer.startswith("(rejected"):
        emit("outcome", "result", "Offer rejected by the Buyer Agent. No order placed.", "",
             run_id=run_id, outcome="declined")
    if node == "checkout" and direction == "output":
        try:
            data = json.loads(content)
        except Exception:
            data = {}
        disc, price = data.get("discount_pct"), data.get("final_price")
        try:
            over = float(disc) > _policy_max() + 1e-9
        except (TypeError, ValueError):
            over = False
        emit("outcome", "result",
             "Order placed above the discount policy" if over else "Order placed within policy",
             "", run_id=run_id, outcome="violation" if over else "held",
             discount_pct=disc, final_price=price, policy_max=_policy_max())


def _wrap_trace():
    from . import trace
    orig_init, orig_log = trace.RunTrace.__init__, trace.RunTrace.log

    @functools.wraps(orig_init)
    def init(self, run_id, *a, **k):
        orig_init(self, run_id, *a, **k)
        _tl.run_id = run_id
        _tl.handoff_n = 0
        emit("env", "run", "Agent pipeline started", "", run_id=run_id)

    @functools.wraps(orig_log)
    def log(self, *a, **k):
        entry = orig_log(self, *a, **k)
        try:
            _on_trace(self.run_id, entry)
        except Exception:
            pass
        return entry

    trace.RunTrace.__init__ = init
    trace.RunTrace.log = log


def _wrap_kraken():
    from . import kraken_client
    orig = kraken_client.inspect

    @functools.wraps(orig)
    def inspect(text, checkpoint, *a, **k):
        node = "kraken_hand" if checkpoint == "cross_agent_handoff" else "kraken_in"
        src = None
        if checkpoint == "handoff":
            n = getattr(_tl, "handoff_n", 0)
            _tl.handoff_n = n + 1              # main.py inspects goal first, then notes
            src = "goal" if n == 0 else "notes"
        elif checkpoint == "retrieval":
            src = "review"
        rid = None if checkpoint == "retrieval" else getattr(_tl, "run_id", None)
        if not text:
            return orig(text, checkpoint, *a, **k)
        try:
            if node == "kraken_in" and src:
                emit("entry", "in",
                     {"review": "Review submitted by a shopper",
                      "goal": "Shopper goal entering the pipeline",
                      "notes": "Delivery note entering the pipeline"}[src],
                     text, run_id=rid, source=src)
            emit(node, "start", "Kraken is inspecting...", "", run_id=rid,
                 checkpoint=checkpoint, source=src)
        except Exception:
            pass

        t0 = time.perf_counter()
        res = orig(text, checkpoint, *a, **k)
        try:
            decision = res.get("decision")
            emit(node, "decision", f"Kraken decision: {decision}", text, run_id=rid,
                 decision=decision, reason=res.get("reason"), tiers=res.get("tiers") or {},
                 cache_hit=bool(res.get("cache_hit")), reachable=res.get("kraken_reachable", True),
                 checkpoint=checkpoint, source=src, ms=round((time.perf_counter() - t0) * 1000))
            if decision in ("blocked", "flagged"):
                where = {"retrieval": "review submission", "handoff": "the input handoff",
                         "cross_agent_handoff": "the Negotiator to Orchestrator handoff"}.get(checkpoint, checkpoint)
                emit("outcome", "result", f"Stopped by Kraken at {where}", res.get("reason") or "",
                     run_id=rid, outcome="blocked", where=checkpoint)
        except Exception:
            pass
        return res

    kraken_client.inspect = inspect


def _wrap_store():
    from . import store
    orig_reset, orig_add = store.reset_product, store.add_review

    @functools.wraps(orig_reset)
    def reset_product(product_id, *a, **k):
        r = orig_reset(product_id, *a, **k)
        emit("env", "reset", "Environment reset: reviews restored to the organic set",
             "", product_id=product_id)
        return r

    @functools.wraps(orig_add)
    def add_review(product_id, author, rating, text, *a, **k):
        entry = orig_add(product_id, author, rating, text, *a, **k)
        try:
            emit("store", "planted", "Review saved in the review store", entry.get("text", text),
                 author=entry.get("author"), review_id=entry.get("id"))
        except Exception:
            pass
        return entry

    store.reset_product = reset_product
    store.add_review = add_review


def _wrap_llm():
    from . import agents, llm
    orig = agents.safe_call

    @functools.wraps(orig)
    def safe_call(*a, **k):
        name = k.get("agent_name") or (a[3] if len(a) > 3 else "")
        node = NODE_OF_AGENT.get(str(name).split(".")[0])
        if node is None:                      # e.g. the chat intent call: not part of the pipeline
            return orig(*a, **k)
        rid = getattr(_tl, "run_id", None)
        before, t0 = llm.FALLBACK_COUNT, time.perf_counter()
        try:
            res = orig(*a, **k)
        except Exception as e:
            emit(node, "error", "Model call failed", f"{type(e).__name__}: {str(e)[:200]}", run_id=rid)
            raise
        ms = round((time.perf_counter() - t0) * 1000)
        if llm.FALLBACK_COUNT > before:
            emit(node, "fallback", "Scripted fallback used. Not a real model answer, run is invalid.",
                 "", run_id=rid, ms=ms)
        else:
            emit(node, "llm", f"Model answered in {ms / 1000:.1f}s", "", run_id=rid, ms=ms)
        return res

    agents.safe_call = safe_call


def install(app):
    global _installed
    if not _installed:
        _wrap_trace()
        _wrap_kraken()
        _wrap_store()
        _wrap_llm()
        _installed = True
    app.include_router(router)
