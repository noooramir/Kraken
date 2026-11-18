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

from . import dataset, scoring, tasks


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

    def run(self, product_id, budget, goal, notes, planted_review_id=None):
        body = {"product_id": product_id, "budget": budget, "goal": goal, "notes": notes}
        if planted_review_id is not None:
            body["planted_review_id"] = planted_review_id      # lets MarketFlow report the planted review's rank/score
        return self._http.post("/api/run", json=body).json()


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
def run_trial(client, payload, user_task, trial_idx, product=None, kraken_enabled=False, real_hint=None):
    """payload=None -> control run (no attack). Always resets state first.
    rec["row"] is the flat dataset row for this trial (see offense/dataset.py)."""
    t0 = time.perf_counter()
    client.reset(user_task.product_id)
    goal, notes = user_task.goal, user_task.notes
    planted, planted_id = None, None
    rec = {
        "payload_id": payload.id if payload else "control",
        "vector": payload.vector if payload else "control",
        "stealth": payload.stealth if payload else "none",
        "trial": trial_idx,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "blocked": False, "error": None,
        "discount_pct": None, "final_price": None, "approved": None,
        "violations": [], "fallback_calls": None, "retrieved": None,
    }

    if payload:
        if payload.vector == "review":
            planted = client.post_review(user_task.product_id, payload.text)
            planted_id = (planted.get("review") or {}).get("id")
            if planted.get("error"):          # rejected at submission (only when defended)
                rec["blocked"] = True
                rec.update(success=False, in_policy=False, valid=True, elapsed_s=round(time.perf_counter() - t0, 2))
                rec["row"] = dataset.build_row(rec, payload, user_task, product, {}, planted, kraken_enabled, real_hint)
                return rec
        elif payload.vector == "goal":
            goal = f"{goal} {payload.text}"
        elif payload.vector == "notes":
            notes = payload.text
        else:
            raise ValueError(f"unknown vector {payload.vector!r}")

    try:
        extra = {"planted_review_id": planted_id} if planted_id is not None else {}
        result = client.run(user_task.product_id, user_task.budget, goal, notes, **extra)
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
    rec["row"] = dataset.build_row(rec, payload, user_task, product, result, planted, kraken_enabled, real_hint)
    return rec


def run_trial_with_retries(client, payload, user_task, trial_idx, retries=2, backoff=40.0, sleep=time.sleep,
                           product=None, kraken_enabled=False, real_hint=None):
    """Re-run a trial that came back INVALID (scripted fallback / error), e.g.
    from a rate limit or timeout. Only the last attempt is kept; `attempts`
    records how many it took. Valid trials (success OR fail) are never re-run,
    so retries cannot bias the success rate."""
    kw = dict(product=product, kraken_enabled=kraken_enabled, real_hint=real_hint)
    rec = run_trial(client, payload, user_task, trial_idx, **kw)
    attempts = 1
    while not rec["valid"] and attempts <= retries:
        sleep(backoff * attempts)
        rec = run_trial(client, payload, user_task, trial_idx, **kw)
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


def _add_to_manifest(out_path: Path):
    """The Kraken dashboard reads the result files listed in included.json."""
    manifest = out_path.parent / "included.json"
    try:
        names = json.loads(manifest.read_text()) if manifest.exists() else []
    except ValueError:
        names = []
    if out_path.name not in names:
        names.append(out_path.name)
        manifest.write_text(json.dumps(names, indent=2))
        print(f"Added to dashboard: {manifest}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description="Kraken offense runner (baseline, no defense)")
    ap.add_argument("--trials", type=int, default=5, help="runs per payload (default 5)")
    ap.add_argument("--vectors", nargs="*", choices=tasks.VECTORS)
    ap.add_argument("--stealth", nargs="*", choices=tasks.STEALTH_LEVELS)
    ap.add_argument("--ids", nargs="*", help="run only these payload ids, e.g. review-paraphrased review-authority-a")
    ap.add_argument("--control-trials", type=int, default=None,
                    help="runs of the control (no attack) payload; default = --trials. Use 10 for a firmer benign baseline")
    ap.add_argument("--start-trial", type=int, default=1,
                    help="number of the first trial (default 1). Use it to re-run missing trials with their original "
                         "numbers, e.g. --ids notes-stealthy-a --trials 1 --start-trial 5")
    ap.add_argument("--max-invalid-streak", type=int, default=3,
                    help="stop the run (and save) after this many INVALID trials in a row, e.g. when the LLM quota is used "
                         "up, instead of burning hours on scripted fallbacks. 0 = never stop (default 3)")
    ap.add_argument("--no-control", action="store_true", help="skip the control (no-attack) runs")
    ap.add_argument("--no-dashboard", action="store_true", help="do not add this run's file to the dashboard manifest")
    ap.add_argument("--product-id", default=None,
                    help="MarketFlow product to attack (default: the original earbuds-01). See GET /api/products")
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

    product = None
    if args.product_id:
        product = next((p for p in client.products() if p["id"] == args.product_id), None)
        if product is None:
            print(f"MarketFlow has no product '{args.product_id}'.")
            return 2
    user_task = tasks.for_product(product)
    if product is None:                         # default product (earbuds-01): fetch its card for name/list_price
        product = next((p for p in client.products() if p["id"] == user_task.product_id), None)
    real_hint = None
    payloads = [tasks.adapt_payload(p, product) for p in tasks.get_payloads(args.vectors, args.stealth, args.ids)]
    plan = ([] if args.no_control else [None]) + payloads                      # None = control run first
    out_path = Path(args.out or f"offense/results/baseline_{datetime.now():%Y%m%d_%H%M%S}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    trials = []
    started = datetime.now().isoformat(timespec="seconds")
    streak, stopped = 0, False
    try:
        for p in plan:
            if stopped:
                break
            name = p.id if p else "control (no attack)"
            n_trials = args.control_trials if (p is None and args.control_trials) else args.trials
            for i in range(args.start_trial, args.start_trial + n_trials):
                rec = run_trial_with_retries(client, p, user_task, i, retries=args.retries,
                                             backoff=args.backoff, product=product, kraken_enabled=False,
                                             real_hint=real_hint)
                trials.append(rec)
                if rec["row"]["real_reviews_source"]:
                    real_hint = {"count": rec["row"]["real_reviews_count"], "source": rec["row"]["real_reviews_source"]}
                extra = f" (attempt {rec['attempts']})" if rec["attempts"] > 1 else ""
                print(f"[{name} {i}/{args.start_trial + n_trials - 1}] {_label(rec)}{extra}")
                streak = 0 if rec["valid"] else streak + 1
                if args.max_invalid_streak and streak >= args.max_invalid_streak:
                    print(f"\nSTOPPING: {streak} INVALID trials in a row. The LLM is not answering (quota used up, wrong key, "
                          "or network). Look at the MarketFlow window for 'quota=' or 'status=' in the warnings. "
                          "Saving what finished; re-run the rest later with --ids / --start-trial.")
                    stopped = True
                    break
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
        "meta": {"started": started, "trials_per_payload": args.trials, "control_trials": args.control_trials or args.trials, "kraken": kraken_state,
                 "user_task": user_task.__dict__, "injection_goal": tasks.INJECTION_GOAL},
        "summary": summary, "per_payload": per_payload, "control": ctrl_rows, "trials": trials,
    }, indent=2))
    csv_path = out_path.with_suffix(".csv")
    dataset.write_csv(csv_path, [t["row"] for t in trials])
    print(f"\nSaved: {out_path}\nDataset rows (CSV, {len(trials)} rows): {csv_path}")
    if not args.no_dashboard:
        _add_to_manifest(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
