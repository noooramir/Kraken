"""Real-review products for MarketFlow.

Reads marketflow/data/real_catalog.json (built by `python -m offense.prepare_ecommerce`): 14 products whose
reviews are real amazon.com customer-review sentences (Hu & Liu 2004, Ding/Liu/Yu 2008). Prices and photos do
not exist in that data, so prices are flagged illustrative and the image is a labelled placeholder.

Set MARKETFLOW_REAL_CATALOG=0 to run with only the three original synthetic products.
If the file is missing MarketFlow simply starts without these products.
"""
import json
import os
import time
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "real_catalog.json"
AVATAR = "#64748b"


def load(make_review):
    """-> (products, reviews) dicts in the same shape store.py uses. `make_review` is store._seed_review."""
    if os.environ.get("MARKETFLOW_REAL_CATALOG", "1") == "0" or not PATH.exists():
        return {}, {}
    data = json.loads(PATH.read_text(encoding="utf-8"))
    products, reviews = {}, {}
    for p in data.get("products", []):
        rv = []
        for r in p.pop("reviews", []):
            e = make_review(r["author"], r["rating"], r["text"], r["days_ago"], verified=r.get("verified", False))
            e["avatar_color"] = AVATAR
            e["ts"] = time.time() - r["days_ago"] * 86400
            rv.append(e)
        products[p["id"]] = p
        reviews[p["id"]] = rv
    return products, reviews
