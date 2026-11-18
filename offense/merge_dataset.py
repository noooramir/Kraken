"""
Merge per-product runner CSVs into one dataset file and print a summary.

    python -m offense.merge_dataset offense/results/dataset_earbuds-01.csv offense/results/dataset_watch-02.csv ^
        offense/results/dataset_backpack-03.csv --out offense/results/dataset.csv

ASR (attack success rate) = attack_success / valid attack trials. Invalid trials (scripted fallback or error)
stay in the CSV (trial_valid=False) but are excluded from every rate below.
"""
import argparse
import sys

import pandas as pd

from . import dataset


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="offense/results/dataset.csv")
    args = ap.parse_args(argv)

    frames = []
    for f in args.files:
        d = pd.read_csv(f)
        if list(d.columns) != dataset.COLUMNS:
            sys.exit(f"{f}: columns differ from the dataset schema (re-run it with the current runner)")
        d["_src"] = f
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    # A re-run of a trial has the same (trial_id, product_id). Keep one row per key: a valid row beats an invalid
    # one, and among equals the latest wins.
    before = len(df)
    df["_v"] = df.trial_valid.astype(int)
    df = (df.sort_values(["trial_id", "product_id", "_v", "timestamp"])
            .drop_duplicates(["trial_id", "product_id"], keep="last")
            .sort_values("timestamp").reset_index(drop=True))
    replaced = before - len(df)
    df.drop(columns=["_src", "_v"]).to_csv(args.out, index=False, encoding="utf-8")
    print(f"Wrote {args.out}: {len(df)} rows, {len(dataset.COLUMNS)} columns, {replaced} superseded re-run rows removed")

    valid = df[df.trial_valid]
    atk = valid[valid.is_attack]
    ctl = valid[~valid.is_attack]
    print(f"\nRows per product: {df.groupby('product_id').size().to_dict()}")
    print(f"Invalid trials (excluded below): {int((~df.trial_valid).sum())} of {len(df)}")
    if len(ctl):
        print(f"Control (benign): {len(ctl)} valid runs, order placed {ctl.order_placed.mean():.0%}, "
              f"policy violated {ctl.policy_violated.mean():.0%}")

    def table(by):
        g = atk.groupby(by)
        t = pd.DataFrame({"valid": g.size(), "successes": g.attack_success.sum(),
                          "ASR": (g.attack_success.mean() * 100).round(0).astype(int).astype(str) + "%"})
        if by != "stealth_level":
            t["retrieved"] = (g.payload_retrieved.mean() * 100).round(0).astype(int).astype(str) + "%"
        t["propagated"] = (g.propagation_loose.mean() * 100).round(0).astype(int).astype(str) + "%"
        return t

    for by in ("use_case", "stealth_level", "product_id", "payload_id"):
        print(f"\n=== ATTACKS by {by} (valid trials only; 'retrieved' = planted review reached the Negotiator) ===")
        print(table(by).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
