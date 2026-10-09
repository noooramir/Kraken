"""
Offense runner. Plants each payload, runs the MarketFlow buyer flow N times,
scores each run against the policy, and writes results to JSON.

Run from the kraken-poc folder, with MarketFlow running on :8001:

    python -m offense.runner --trials 5
    python -m offense.runner --trials 1 --vectors review --stealth stealthy   # quick check

This is the OFFENSE baseline: it makes sure Kraken's defense is OFF (or that
Kraken is not running, in which case MarketFlow fails open) so the numbers
show what the attacks achieve against an undefended system.
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import scoring, tasks


# --------------------------------------------------------------------------
# HTTP client (thin wrapper so tests can swap in a fake)
# --------------------------------------------------------------------------
class MarketFlowClient:
    def __init__(self, base_url="http://127.0.0.1:8001", timeout=180.0):
        import httpx
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def products(self):
        return self._http.get("/api/products").json()

    def reset(self, product_id):
        return self._http.post(f"/api/products/{product_id}/reset").json()

    def post_review(self, product_id, text):
        return self._http.post(f"/api/products/{product_id}/reviews",
                               json={"author": "Attacker", "rating": 5, "text": text}).json()

    def run(self, product_id, budget, goal, notes):
        return self._http.post("/api/run", json={
            "product_id": product_id, "budget": budget, "goal": goal, "notes": notes,
        }).json()


def ensure_kraken_off(kraken_url):
    """Offense baseline must be undefended. Returns a string describing the state."""
    import httpx
    try:
        with httpx.Client(base_url=kraken_url, timeout=5.0) as c:
            if c.get("/api/defense/tally").json().get("defense_on"):
                c.post("/api/defense/toggle")
            now = c.get("/api/defense/tally").json().get("defense_on")
            return "kraken running, defense OFF" if not now else "kraken running, defense STILL ON (baseline invalid)"
    except Exception:
        return "kraken not running (MarketFlow fails open = undefended)"


# --------------------------------------------------------------------------
# One trial
# --------------------------------------------------------------------------
def run_trial(client, payload, user_task, trial_idx):
    """payload=None -> control run (no attack). Always resets state first."""
    t0 = time.perf_counter()
    client.reset(user_task.product_id)
    goal, notes = user_task.goal, user_task.notes
    rec = {
        "payload_id": payload.id if payload else "control",
        "vector": payload.vector if payload else "control",
        "stealth": payload.stealth if payload else "none",
        "trial": trial_idx,
        "blocked": False, "error": None,
        "discount_pct": None, "final_price": None, "approved": None,
        "violations": [], "fallback_calls": None, "retrieved": None,
    }

    if payload:
        if payload.vector == "review":
            planted = client.post_review(user_task.product_id, payload.text)
            if planted.get("error"):          # rejected at submission (only when defended)
                rec["blocked"] = True
                rec.update(success=False, in_policy=False, valid=True, elapsed_s=round(time.perf_counter() - t0, 2))
                return rec
        elif payload.vector == "goal":
            goal = f"{goal} {payload.text}"
        elif payload.vector == "notes":
            notes = payload.text
        else:
            raise ValueError(f"unknown vector {payload.vector!r}")

    try:
        result = client.run(user_task.product_id, user_task.budget, goal, notes)
    except Exception as e:                      # network/timeout/etc.
        result = {"error": f"{type(e).__name__}: {e}"}

    max_disc = scoring.max_discount_from(result)
    order = result.get("order") or {}
    decision = result.get("decision") or {}
    rec.update({
        "blocked": bool(result.get("blocked")),
        "error": result.get("error"),
        "discount_pct": order.get("discount_pct"),
        "final_price": order.get("final_price"),
        "approved": decision.get("approved"),
        "violations": result.get("violations", []),
        "fallback_calls": result.get("fallback_calls"),
        "max_discount_pct": max_disc,
        "valid": scoring.trial_is_valid(result),
        "success": scoring.attack_succeeded(result, max_disc),
        "in_policy": scoring.order_in_policy(result, max_disc),
    })
    # Did the planted review actually reach the Negotiator? (heuristic: its
    # opening words appear in the run trace). Separates "never retrieved" from
    # "retrieved but the agent resisted".
    if payload and payload.vector == "review" and result.get("trace") is not None:
        rec["retrieved"] = payload.text[:25] in json.dumps(result["trace"])
    rec["elapsed_s"] = round(time.perf_counter() - t0, 2)
    return rec


def run_trial_with_retries(client, payload, user_task, trial_idx, retries=2, backoff=40.0, sleep=time.sleep):
    """Re-run a trial that came back INVALID (scripted fallback / error), e.g.
    from a rate limit or timeout. Only the last attempt is kept; `attempts`
    records how many it took. Valid trials (success OR fail) are never re-run,
    so retries cannot bias the success rate."""
    rec = run_trial(client, payload, user_task, trial_idx)
    attempts = 1
    while not rec["valid"] and attempts <= retries:
        sleep(backoff * attempts)
        rec = run_trial(client, payload, user_task, trial_idx)
        attempts += 1
    rec["attempts"] = attempts
    return rec


def _label(rec):
    if rec["error"]:
        return f"ERROR {rec['error']}"
    if not rec["valid"]:
        return f"INVALID (scripted fallback used {rec['fallback_calls']}x)"
    if rec["blocked"]:
        return "blocked"
    if rec["discount_pct"] is None:
        return "no order placed (offer declined) -> fail"
    return f"discount={rec['discount_pct']}% -> {'SUCCESS' if rec['success'] else 'fail'}"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description="Kraken offense runner (baseline, no defense)")
    ap.add_argument("--trials", type=int, default=5, help="runs per payload (default 5)")
    ap.add_argument("--vectors", nargs="*", choices=tasks.VECTORS)
    ap.add_argument("--stealth", nargs="*", choices=tasks.STEALTH_LEVELS)
    ap.add_argument("--marketflow", default="http://127.0.0.1:8001")
    ap.add_argument("--kraken", default="http://127.0.0.1:8002")
    ap.add_argument("--delay", type=float, default=20.0,
                    help="seconds between trials. Each trial makes ~5 LLM calls; the Gemini free tier allows 15/min, so ~20s keeps you under it")
    ap.add_argument("--backoff", type=float, default=40.0,
                    help="base seconds to wait before re-running an INVALID trial (Gemini asks for ~35s after a 429)")
    ap.add_argument("--retries", type=int, default=2, help="re-run INVALID trials up to N times (default 2)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-kraken-check", action="store_true", help="skip the Kraken defense-off check (tests)")
    args = ap.parse_args(argv)

    client = client or MarketFlowClient(args.marketflow)
    try:
        client.products()
    except Exception as e:
        print(f"Cannot reach MarketFlow at {args.marketflow}: {e}")
        return 2

    kraken_state = "not checked" if args.no_kraken_check else ensure_kraken_off(args.kraken)
    print(f"Kraken: {kraken_state}")
    if "STILL ON" in kraken_state:
        print("Refusing to run: defense is on, this is the offense baseline.")
        return 2

    user_task = tasks.BENIGN_USER_TASK
    payloads = tasks.get_payloads(args.vectors, args.stealth)
    plan = [None] + payloads                      # None = control run first
    out_path = Path(args.out or f"offense/results/baseline_{datetime.now():%Y%m%d_%H%M%S}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    trials = []
    started = datetime.now().isoformat(timespec="seconds")
    try:
        for p in plan:
            name = p.id if p else "control (no attack)"
            for i in range(1, args.trials + 1):
                rec = run_trial_with_retries(client, p, user_task, i, retries=args.retries,
                                             backoff=args.backoff)
                trials.append(rec)
                extra = f" (attempt {rec['attempts']})" if rec["attempts"] > 1 else ""
                print(f"[{name} {i}/{args.trials}] {_label(rec)}{extra}")
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nInterrupted, saving what we have.")

    control = [t for t in trials if t["vector"] == "control"]
    attacks = [t for t in trials if t["vector"] != "control"]
    summary = scoring.summarize(attacks)
    per_payload = scoring.summarize(attacks, keys=("payload_id",))
    ctrl_rows = scoring.summarize(control, keys=("vector",))

    print("\n=== CONTROL (no attack) ===")
    print(scoring.format_table(ctrl_rows, keys=("vector",)) if ctrl_rows else "none")
    print("\n=== BY VECTOR x STEALTH ===")
    print(scoring.format_table(summary))
    print("\n=== BY PAYLOAD ===")
    print(scoring.format_table(per_payload, keys=("payload_id",)))

    ctrl_bad = sum(r["successes"] for r in ctrl_rows)
    if ctrl_bad:
        print(f"\nWARNING: {ctrl_bad} control run(s) exceeded policy with NO attack. "
              "Attack success rates below are not cleanly attributable to the payloads.")
    n_invalid = sum(1 for t in trials if not t["valid"])
    if n_invalid:
        print(f"WARNING: {n_invalid} trial(s) INVALID (scripted fallback or error). "
              "They are excluded from ASR. Check your LLM key/model.")

    out_path.write_text(json.dumps({
        "meta": {"started": started, "trials_per_payload": args.trials, "kraken": kraken_state,
                 "user_task": user_task.__dict__, "injection_goal": tasks.INJECTION_GOAL},
        "summary": summary, "per_payload": per_payload, "control": ctrl_rows, "trials": trials,
    }, indent=2))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
