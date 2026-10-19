"""One-time download of the CLEAN passages PoisonedRAG needs.

PoisonedRAG ships the poisoned texts and the ids of the clean passages each
question normally retrieves, but not the clean passage text (that lives in the
public BEIR corpora). This script downloads the BEIR zip for ONE dataset, streams
through corpus.jsonl and keeps only the few hundred passages we need.

Run it on a machine with normal internet (your PowerShell, not the sandbox):
    marketflow\\venv\\Scripts\\python -m offense.prepare_poisonedrag --dataset nq
The zip is large (hundreds of MB to ~1 GB). It is deleted afterwards unless --keep-zip.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BEIR_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{name}.zip"
DATA = Path(__file__).parent / "datasets" / "poisonedrag"


def needed_ids(dataset, clean_k=10):
    ids = json.loads((DATA / f"clean_ids_{dataset}.json").read_text())
    return {d for v in ids.values() for d in v[:clean_k]}


def extract(zip_path, dataset, wanted):
    found = {}
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.endswith("corpus.jsonl"))
        with z.open(member) as f:
            for i, line in enumerate(f):
                if i % 500000 == 0 and i:
                    print(f"  scanned {i:,} passages, found {len(found)}/{len(wanted)}")
                row = json.loads(line)
                if row["_id"] in wanted:
                    found[row["_id"]] = row.get("text", "")
                    if len(found) == len(wanted):
                        break
    return found


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["nq", "hotpotqa", "msmarco"], default="nq")
    ap.add_argument("--zip", help="use an already-downloaded BEIR zip instead of downloading")
    ap.add_argument("--keep-zip", action="store_true")
    args = ap.parse_args(argv)

    wanted = needed_ids(args.dataset)
    zip_path = Path(args.zip) if args.zip else DATA / f"_{args.dataset}_beir.zip"
    if not args.zip:
        url = BEIR_URL.format(name=args.dataset)
        print(f"Downloading {url}\n(large file, this can take several minutes)")
        try:
            urllib.request.urlretrieve(url, zip_path,
                                       lambda b, bs, total: print(f"\r  {b*bs/1e6:,.0f} MB", end="") if b % 200 == 0 else None)
        except urllib.error.URLError as e:
            print(f"\nDownload failed: {e}\n\nDownload the zip another way, then run this script again with --zip:\n"
                  f"    curl.exe -L -o nq.zip {url}\n    (or open the URL in your browser)\n"
                  f"    marketflow\\venv\\Scripts\\python -m offense.prepare_poisonedrag --dataset {args.dataset} --zip nq.zip")
            return 3
        print()
    found = extract(zip_path, args.dataset, wanted)
    missing = len(wanted) - len(found)
    out = DATA / f"clean_texts_{args.dataset}.json"
    out.write_text(json.dumps(found))
    print(f"Saved {len(found)} clean passages to {out}" + (f" ({missing} ids not found)" if missing else ""))
    if not args.zip and not args.keep_zip:
        try:
            zip_path.unlink()
        except OSError:
            print(f"Could not delete {zip_path}; delete it manually to free space.")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
