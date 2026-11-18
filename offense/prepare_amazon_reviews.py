#!/usr/bin/env python3
"""
prepare_amazon_reviews.py
Step 1 of the Kraken FYP dataset pipeline.

Downloads real Amazon Electronics reviews (streaming, no full download),
selects 3 product categories matching the MarketFlow products, cleans the
reviews, replaces real brand names with fictional ones, and writes:

    amazon_earbuds.csv    (reviewer_name, rating, review_text)
    amazon_watches.csv    (reviewer_name, rating, review_text)
    amazon_backpacks.csv  (reviewer_name, rating, review_text)
    all_reviews.csv       (reviewer_name, rating, review_text, product_id)

Usage:
    pip install pandas requests
    python prepare_amazon_reviews.py                 # auto: Hugging Face, then UCSD fallback
    python prepare_amazon_reviews.py --n 80 --out data
    python prepare_amazon_reviews.py --source ucsd   # force UCSD 2018 5-core (has real reviewerName)
    python prepare_amazon_reviews.py --source hf --meta-path meta.jsonl --reviews-path Electronics.jsonl
        (use files you downloaded manually; .gz is supported)
"""
import argparse
import gzip
import hashlib
import html
import io
import json
import os
import random
import re
import sys
import time
from contextlib import closing

import pandas as pd
import requests

# ----------------------------------------------------------------------------
# 1. CONFIGURATION
# ----------------------------------------------------------------------------

MIN_LEN, MAX_LEN = 20, 500

# Target rating mix for the final sample (typical Amazon "J-shaped" distribution).
RATING_MIX = {5: 0.42, 4: 0.20, 3: 0.12, 2: 0.08, 1: 0.18}
MAX_PER_PRODUCT_FINAL = 12     # max reviews from one Amazon product in the final sample
MAX_PER_PRODUCT_POOL = 60      # max reviews from one Amazon product kept while streaming

SOURCES = {
    "hf": {
        "meta_url": "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/meta_categories/meta_Electronics.jsonl",
        "review_url": "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/review_categories/Electronics.jsonl",
        "meta_asin": "parent_asin", "meta_brand": "store", "meta_pop": "rating_number",
        "rev_asin": "parent_asin", "rev_text": "text", "rev_rating": "rating",
        "rev_user": "user_id", "rev_name": None,       # 2023 data has NO reviewer name
        "cand_cap": 60, "min_pop": 200, "max_meta_lines": 1_500_000, "max_review_lines": 12_000_000,
    },
    "ucsd": {
        "meta_url": "https://jmcauley.ucsd.edu/data/amazon_v2/metaFiles2/meta_Electronics.json.gz",
        "review_url": "https://jmcauley.ucsd.edu/data/amazon_v2/categoryFilesSmall/Electronics_5.json.gz",
        "meta_asin": "asin", "meta_brand": "brand", "meta_pop": None,
        "rev_asin": "asin", "rev_text": "reviewText", "rev_rating": "overall",
        "rev_user": "reviewerID", "rev_name": "reviewerName",
        "cand_cap": 250, "min_pop": 0, "max_meta_lines": 1_500_000, "max_review_lines": 2_000_000,
    },
}

I = re.IGNORECASE
CATEGORIES = {
    "earbuds-01": {
        "label": "Earbuds/headphones", "brand": "AeroBuds", "file": "amazon_earbuds.csv",
        "include": re.compile(r"\b(earbuds?|ear buds?|earphones?|in[- ]ear|headphones?|airpods)\b", I),
        "exclude": re.compile(
            r"\b(replacement|ear ?pads?|ear ?tips?|eartips?|ear ?hooks?|cases? for|covers? for|skin|adapter|"
            r"splitter|cable|chargers? for|stand|holder|protective case|compatible with|cleaning|cleaner|"
            r"organizer|extension)\b", I),
        "brands": ["Sony", "JBL", "Bose", "Beats", "Jabra", "Sennheiser", "Anker",
                   "Soundcore", "Skullcandy", "Jaybird", "Bang & Olufsen", "Plantronics", "Panasonic",
                   "Pixel Buds", "Galaxy Buds", "AirPods", "Raycon", "TOZO", "Mpow",
                   "Soundpeats", "Tribit", "QCY", "Amazon Basics", "AmazonBasics", "Audio-Technica",
                   "Bowers & Wilkins", "OnePlus", "Realme", "Xiaomi", "Redmi"],
    },
    "watch-02": {
        "label": "Smartwatches/fitness trackers", "brand": "PulseFit", "file": "amazon_watches.csv",
        "include": re.compile(
            r"\b(smart ?watch(es)?|fitness (tracker|watch|band)s?|activity tracker|sports? watch|"
            r"smart ?band|gps watch)\b", I),
        "exclude": re.compile(
            r"\b(watch ?bands?|bands? for|straps?|replacement|screen protectors?|protectors?|cases? for|"
            r"covers?|chargers?|charging (cable|dock)|dock|stand|holder|compatible with|bumper|"
            r"bracelets? for|loop|skin|film|tempered)\b", I),
        "brands": ["Garmin", "Fitbit", "Amazfit", "Huawei", "Xiaomi", "Fossil",
                   "Polar", "Suunto", "Withings", "Casio", "Timex", "Pixel Watch",
                   "Galaxy Watch", "Apple Watch", "Mi Band", "Coros", "TicWatch", "Mobvoi", "Wyze",
                   "Letsfit", "Lintelek", "Willful", "Amazon Basics", "AmazonBasics", "Realme", "OnePlus",
                   "Skagen", "Michael Kors", "Misfit", "Oppo", "Whoop", "Oura"],
    },
    "backpack-03": {
        "label": "Backpacks/travel bags", "brand": "TrailPack", "file": "amazon_backpacks.csv",
        "include": re.compile(r"\b(backpacks?|daypacks?|rucksacks?|travel bags?|carry[- ]on)\b", I),
        "exclude": re.compile(
            r"\b(rain ?covers?|covers? for|replacement|straps? for|organizer insert|compatible with|"
            r"keychains?|zipper pulls?|sleeve only)\b", I),
        "brands": ["The North Face", "North Face", "Osprey", "Herschel", "JanSport", "Samsonite", "Targus",
                   "Kelty", "Patagonia", "Fjallraven", "Fjällräven", "Nike", "Adidas", "SwissGear",
                   "Swiss Gear", "Eastsport", "Amazon Basics", "AmazonBasics", "Timbuk2", "Incase",
                   "Tumi", "Travelpro", "Deuter", "Under Armour", "Puma",
                   "Dell", "HP", "Lenovo", "Matein", "Mancro", "Kenneth Cole", "Eddie Bauer", "Coleman",
                   "Arcteryx", "Arc'teryx", "Pacsafe", "Wenger", "Victorinox", "Thule", "Briggs & Riley",
                   "High Sierra", "Volcom", "Dakine", "Rick Steves", "Tortuga", "Peak Design", "Kuhl"],
    },
}

ALL_BRANDS = sorted({b for c in CATEGORIES.values() for b in c["brands"]})

# Store/brand strings from metadata that must never be treated as a brand to replace.
GENERIC_BRANDS = {"generic", "unknown", "amazon", "visit", "brand", "unbranded", "oem", "n/a", "na", "none"}

FIRST_NAMES = ["Alex", "Sam", "Jordan", "Taylor", "Chris", "Morgan", "Jamie", "Casey", "Riley", "Drew",
               "Sarah", "Mike", "Emily", "David", "Jessica", "Daniel", "Laura", "Mark", "Anna", "Kevin",
               "Maria", "James", "Linda", "Robert", "Karen", "Brian", "Nina", "Omar", "Priya", "Chen",
               "Fatima", "Ahmed", "Sofia", "Lucas", "Hannah", "Ethan", "Olivia", "Noah", "Grace", "Ryan",
               "Megan", "Tyler", "Amber", "Jason", "Rachel", "Eric", "Nicole", "Paul", "Julia", "Adam"]


# ----------------------------------------------------------------------------
# 2. STREAMING HELPERS
# ----------------------------------------------------------------------------

def open_lines(src):
    """Yield raw byte lines from a URL or local path (.gz supported). Never loads the full file."""
    resp = None
    if src.startswith(("http://", "https://")):
        headers = {"User-Agent": "kraken-fyp-dataset/1.0"}
        token = os.environ.get("HF_TOKEN")
        if token and "huggingface.co" in src:
            headers["Authorization"] = "Bearer " + token
        resp = requests.get(src, stream=True, headers=headers, timeout=(20, 120))
        resp.raise_for_status()
        resp.raw.decode_content = True
        stream = io.BufferedReader(resp.raw, buffer_size=1 << 20)
    else:
        stream = open(src, "rb")
    if src.endswith(".gz"):
        stream = gzip.GzipFile(fileobj=stream)
    try:
        for line in stream:
            yield line
    finally:
        try:
            stream.close()
        finally:
            if resp is not None:
                resp.close()


def parse_json(line):
    try:
        return json.loads(line)
    except Exception:
        return None


# ----------------------------------------------------------------------------
# 3. CLEANING
# ----------------------------------------------------------------------------

URL_RE = re.compile(r"(https?://|www\.|\b[\w.-]+@[\w.-]+\.\w+\b)", I)


def clean_text(t):
    if not isinstance(t, str):
        return ""
    t = html.unescape(t)
    t = re.sub(r"<[^>]+>", " ", t)        # strip html tags like <br />
    t = re.sub(r"\s+", " ", t).strip()
    return t


def looks_english(t):
    non_ascii = sum(1 for c in t if ord(c) > 127)
    letters = sum(1 for c in t if c.isalpha())
    return non_ascii / max(len(t), 1) < 0.05 and letters / max(len(t), 1) > 0.6


def make_brand_regex(brands):
    brands = sorted({b.strip() for b in brands if b and b.strip()}, key=len, reverse=True)
    parts = [r"\s+".join(re.escape(w) for w in b.split()) for b in brands]
    return re.compile(r"(?<![A-Za-z0-9])(" + "|".join(parts) + r")(?![A-Za-z0-9])", I)


def fake_name(user_key):
    h = int(hashlib.md5(str(user_key).encode()).hexdigest(), 16)
    return "%s %s." % (FIRST_NAMES[h % len(FIRST_NAMES)], chr(65 + (h // 100) % 26))


def valid_store(s):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) < 3 or s.lower() in GENERIC_BRANDS or len(s.split()) > 3:
        return None
    return s


# ----------------------------------------------------------------------------
# 4. PIPELINE STAGES
# ----------------------------------------------------------------------------

def scan_metadata(cfg, meta_src):
    """Find popular Electronics products whose title matches each category."""
    print("\n[1/3] Scanning product metadata: %s" % meta_src)
    cands = {pid: {} for pid in CATEGORIES}     # product_id -> {asin: (pop, store)}
    n = 0
    t0 = time.time()
    with closing(open_lines(meta_src)) as lines:
        for line in lines:
            n += 1
            if n % 200_000 == 0:
                print("   metadata lines: %d | candidates: %s | %.0fs" % (
                    n, {k: len(v) for k, v in cands.items()}, time.time() - t0))
            rec = parse_json(line)
            if not rec:
                continue
            title = rec.get("title") or ""
            asin = rec.get(cfg["meta_asin"])
            if not asin or not isinstance(title, str):
                continue
            pop = rec.get(cfg["meta_pop"]) if cfg["meta_pop"] else 0
            pop = pop if isinstance(pop, (int, float)) else 0
            if pop < cfg["min_pop"]:
                continue
            for pid, c in CATEGORIES.items():
                if len(cands[pid]) >= cfg["cand_cap"]:
                    continue
                if c["include"].search(title) and not c["exclude"].search(title):
                    cands[pid][asin] = (pop, valid_store(rec.get(cfg["meta_brand"])))
                    break
            if all(len(v) >= cfg["cand_cap"] for v in cands.values()) or n >= cfg["max_meta_lines"]:
                break
    for pid, c in CATEGORIES.items():
        print("   %-12s %-30s candidate products: %d" % (pid, c["label"], len(cands[pid])))
    if any(len(v) == 0 for v in cands.values()):
        raise RuntimeError("No candidate products found for at least one category.")
    return cands


def collect_reviews(cfg, review_src, cands, pool_target):
    """Stream reviews, keep those of candidate products, clean + filter them."""
    print("\n[2/3] Streaming reviews: %s" % review_src)
    asin_to_pid = {}
    for pid, d in cands.items():
        for asin in d:
            asin_to_pid[asin] = pid

    # brand regex per category: static list + store names of the candidate products
    brand_re = {}
    for pid, c in CATEGORIES.items():
        extra = [s for _, s in cands[pid].values() if s]
        brand_re[pid] = make_brand_regex(ALL_BRANDS + extra)

    asin_pat = re.compile(r'"%s":\s*"([^"]+)"' % re.escape(cfg["rev_asin"]))
    pool = {pid: [] for pid in CATEGORIES}
    per_asin = {pid: {} for pid in CATEGORIES}
    seen_text = {pid: set() for pid in CATEGORIES}
    raw_matched = {pid: 0 for pid in CATEGORIES}
    drop = {pid: {"length": 0, "other": 0, "dup": 0, "cap": 0} for pid in CATEGORIES}

    n = 0
    t0 = time.time()
    with closing(open_lines(review_src)) as lines:
        for line in lines:
            n += 1
            if n % 500_000 == 0:
                print("   review lines: %d | pool: %s | %.0fs" % (
                    n, {k: len(v) for k, v in pool.items()}, time.time() - t0))
            if n >= cfg["max_review_lines"]:
                print("   reached max_review_lines, stopping")
                break
            m = asin_pat.search(line.decode("utf-8", "ignore"))     # cheap pre-filter before json parse
            if not m or m.group(1) not in asin_to_pid:
                continue
            rec = parse_json(line)
            if not rec:
                continue
            asin = m.group(1)
            pid = asin_to_pid[asin]
            raw_matched[pid] += 1

            text = clean_text(rec.get(cfg["rev_text"]))
            rating = rec.get(cfg["rev_rating"])
            try:
                rating = int(round(float(rating)))
            except Exception:
                drop[pid]["other"] += 1
                continue
            if rating < 1 or rating > 5 or not text or URL_RE.search(text) or not looks_english(text):
                drop[pid]["other"] += 1
                continue
            if not (MIN_LEN <= len(text) <= MAX_LEN):
                drop[pid]["length"] += 1
                continue

            text = brand_re[pid].sub(CATEGORIES[pid]["brand"], text)
            if not (MIN_LEN <= len(text) <= MAX_LEN):
                drop[pid]["length"] += 1
                continue
            key = text.lower()
            if key in seen_text[pid]:
                drop[pid]["dup"] += 1
                continue
            if per_asin[pid].get(asin, 0) >= MAX_PER_PRODUCT_POOL:
                drop[pid]["cap"] += 1
                continue

            name = clean_text(rec.get(cfg["rev_name"])) if cfg["rev_name"] else ""
            if not name:
                name = fake_name(rec.get(cfg["rev_user"]) or key)
            seen_text[pid].add(key)
            per_asin[pid][asin] = per_asin[pid].get(asin, 0) + 1
            pool[pid].append({"asin": asin, "reviewer_name": name, "rating": rating, "review_text": text})

            if all(len(v) >= pool_target for v in pool.values()):
                print("   pool target reached for all categories, stopping early")
                break

    print("   total review lines scanned: %d" % n)
    for pid, c in CATEGORIES.items():
        print("   %-12s raw reviews of candidate products: %-6d after filtering: %-5d dropped %s" % (
            pid, raw_matched[pid], len(pool[pid]), drop[pid]))
    return pool, brand_re


def stratified_sample(rows, n, seed):
    """Pick n reviews following RATING_MIX, max MAX_PER_PRODUCT_FINAL per product."""
    rng = random.Random(seed)
    rows = rows[:]
    rng.shuffle(rows)
    chosen, used, per_asin = [], set(), {}

    def take(candidates, k):
        got = 0
        for i, r in candidates:
            if got >= k:
                break
            if i in used or per_asin.get(r["asin"], 0) >= MAX_PER_PRODUCT_FINAL:
                continue
            used.add(i)
            per_asin[r["asin"]] = per_asin.get(r["asin"], 0) + 1
            chosen.append(r)
            got += 1

    indexed = list(enumerate(rows))
    for star in (1, 2, 3, 4, 5):
        share = RATING_MIX[star]
        take([(i, r) for i, r in indexed if r["rating"] == star], round(n * share))
    if len(chosen) < n:                                   # fill shortage from any rating
        take(indexed, n - len(chosen))
    rng.shuffle(chosen)
    return chosen[:n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=80, help="reviews per category (50-100), default 80")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "marketflow", "data", "amazon"),
                    help="output directory, default marketflow/data/amazon")
    ap.add_argument("--source", choices=["auto", "hf", "ucsd"], default="auto")
    ap.add_argument("--meta-path", help="local or URL path to the metadata file (overrides default)")
    ap.add_argument("--reviews-path", help="local or URL path to the reviews file (overrides default)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if not 50 <= args.n <= 100:
        sys.exit("--n must be between 50 and 100")
    os.makedirs(args.out, exist_ok=True)

    order = ["hf", "ucsd"] if args.source == "auto" else [args.source]
    pool = brand_re = None
    for name in order:
        cfg = SOURCES[name]
        meta_src = args.meta_path or cfg["meta_url"]
        rev_src = args.reviews_path or cfg["review_url"]
        print("=" * 70)
        print("SOURCE: %s" % name)
        try:
            cands = scan_metadata(cfg, meta_src)
            pool, brand_re = collect_reviews(cfg, rev_src, cands, pool_target=max(600, args.n * 8))
            if all(len(pool[p]) >= args.n for p in CATEGORIES):
                used_cfg = cfg
                break
            print("   WARNING: source '%s' gave fewer than %d usable reviews for some category" % (name, args.n))
            if name == order[-1]:
                used_cfg = cfg
        except Exception as e:                           # network error, bad file, etc.
            print("   FAILED with source '%s': %s: %s" % (name, type(e).__name__, e))
            pool = None
    if pool is None:
        sys.exit(
            "\nAll sources failed. Download the files manually and run again:\n"
            "  HF   : %s\n         %s\n"
            "  UCSD : %s\n         %s\n"
            "then: python prepare_amazon_reviews.py --source hf --meta-path <meta file> --reviews-path <reviews file>\n"
            % (SOURCES["hf"]["meta_url"], SOURCES["hf"]["review_url"],
               SOURCES["ucsd"]["meta_url"], SOURCES["ucsd"]["review_url"]))

    print("\n[3/3] Sampling and writing CSV files")
    frames, summary = [], []
    for pid, c in CATEGORIES.items():
        sample = stratified_sample(pool[pid], args.n, args.seed)
        if len(sample) < 50:
            print("   WARNING: %s has only %d reviews (< 50)" % (pid, len(sample)))
        df = pd.DataFrame(sample)[["reviewer_name", "rating", "review_text"]]
        df.to_csv(os.path.join(args.out, c["file"]), index=False, encoding="utf-8")
        print("   %-12s selected %d of %d filtered reviews -> %s" % (pid, len(df), len(pool[pid]), c["file"]))

        # sanity check: no real brand left
        left = sum(1 for t in df["review_text"]
                   if re.search(r"(?<![A-Za-z0-9])(%s)(?![A-Za-z0-9])" % "|".join(
                       re.escape(b) for b in ALL_BRANDS), t, I))
        if left:
            print("   WARNING: %d reviews in %s still contain a listed brand name" % (left, pid))

        lens = df["review_text"].str.len()
        dist = df["rating"].value_counts().reindex([5, 4, 3, 2, 1], fill_value=0)
        summary.append({
            "category": c["label"], "product_id": pid, "total_reviews": len(df),
            "avg_rating": round(df["rating"].mean(), 2),
            "min_len": int(lens.min()), "max_len": int(lens.max()),
            "5/4/3/2/1 star": "/".join(str(int(x)) for x in dist),
        })
        d2 = df.copy()
        d2["product_id"] = pid
        frames.append(d2)

    all_df = pd.concat(frames, ignore_index=True)[["reviewer_name", "rating", "review_text", "product_id"]]
    all_df.to_csv(os.path.join(args.out, "all_reviews.csv"), index=False, encoding="utf-8")
    print("   combined %d reviews -> all_reviews.csv" % len(all_df))

    if not used_cfg["rev_name"]:
        print("\nNOTE: this source has no reviewer names. reviewer_name was generated (e.g. 'Sarah M.')"
              "\n      from a hash of the user id. Use --source ucsd for real reviewerName values.")
    print("\nSUMMARY")
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
