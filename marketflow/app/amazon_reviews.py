"""Real Amazon reviews for the three core MarketFlow products.

Reads marketflow/data/amazon/all_reviews.csv (built by `python offense\\prepare_amazon_reviews.py`):
real Amazon Electronics reviews (McAuley Lab, Amazon Reviews 2023) with real brand names replaced by the
fictional brands AeroBuds / PulseFit / TrailPack. Reviewer names are generated (the dataset has none).

These REPLACE the 3 hand-written seed reviews of earbuds-01, watch-02 and backpack-03 so the TF-IDF retrieval
step is realistic: a planted payload has to out-rank real reviews to reach the Negotiator.

Set MARKETFLOW_AMAZON_REVIEWS=0 to go back to the hand-written seed reviews (for comparison runs).
If the CSV is missing, MarketFlow starts with the hand-written reviews.
"""
import csv
import os
import random
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "amazon" / "all_reviews.csv"
SOURCE_LABEL = "amazon"          # value for the dataset column real_reviews_source


def load(make_review):
    """-> {product_id: [review, ...]} in the shape store.py uses. `make_review` is store._seed_review."""
    if os.environ.get("MARKETFLOW_AMAZON_REVIEWS", "1") == "0" or not PATH.exists():
        return {}
    rng = random.Random(42)      # fixed seed: same review dates on every start
    reviews = {}
    with open(PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            e = make_review(row["reviewer_name"], int(row["rating"]), row["review_text"], rng.randint(2, 400))
            e["source"] = SOURCE_LABEL
            reviews.setdefault(row["product_id"], []).append(e)
    return reviews
