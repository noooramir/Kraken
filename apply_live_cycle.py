"""
Wires the Live Cycle files into an existing kraken-poc checkout.

Run from the kraken-poc folder (the one that contains kraken/, marketflow/, offense/):
    python apply_live_cycle.py

It makes four small edits, skips any that are already applied, and keeps line
endings as they were. Copy the new files in first (see README.md).
"""
import os
import sys

EDITS = [
    # (file, marker that means "already applied", old text or None to append, new text)
    ("kraken/static/index.html", "/static/lifecycle.css",
     '<link rel="stylesheet" href="/static/dashboard.css" />',
     '<link rel="stylesheet" href="/static/dashboard.css" />\n<link rel="stylesheet" href="/static/lifecycle.css" />'),
    ("kraken/static/index.html", "/static/lifecycle.js",
     '<script src="/static/dashboard.js"></script>',
     '<script src="/static/dashboard.js"></script>\n<script src="/static/lifecycle.js"></script>'),
    ("kraken/app/main.py", "lifecycle.router", None,
     "\n\n# Live Cycle view: step-by-step lifecycle of the attack currently running\n"
     "from . import lifecycle  # noqa: E402\napp.include_router(lifecycle.router)\n"),
    ("kraken/app/live_runs.py", 'job["trial"]',
     '        _add(job, "info", f"[{label} {i}/{n}] running (resets product, takes ~20-60s)...")',
     '        job["trial"], job["label"] = i, label\n'
     '        _add(job, "info", f"[{label} {i}/{n}] running (resets product, takes ~20-60s)...")'),
    ("marketflow/app/main.py", "live_feed.install", None,
     "\n\n# Live Cycle feed: records each step of a run so Kraken can show it live\n"
     "from . import live_feed  # noqa: E402\nlive_feed.install(app)\n"),
]

NEW_FILES = ["kraken/app/lifecycle.py", "kraken/static/lifecycle.js", "kraken/static/lifecycle.css",
             "marketflow/app/live_feed.py"]


def main():
    missing = [p for p in NEW_FILES + sorted({e[0] for e in EDITS}) if not os.path.exists(p)]
    if missing:
        print("Run this from the kraken-poc folder, after copying the new files in. Missing:")
        for p in missing:
            print("  ", p)
        sys.exit(1)

    for path, marker, old, new in EDITS:
        with open(path, "r", encoding="utf-8", newline="") as f:
            raw = f.read()
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        if marker in text:
            print(f"already applied: {path} ({marker})")
            continue
        if old is None:
            text = text.rstrip("\n") + new
        else:
            if old not in text:
                print(f"COULD NOT PATCH {path}: expected line not found:\n   {old.strip()}")
                sys.exit(1)
            text = text.replace(old, new, 1)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text.replace("\n", "\r\n") if crlf else text)
        print(f"patched: {path}")
    print("\nDone. Restart MarketFlow and Kraken, then open the Dashboard page and click Live Cycle.")


if __name__ == "__main__":
    main()
