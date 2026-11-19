"""
/api/datasets — returns metadata, stats, and sample rows for every dataset
Kraken uses (source corpora + generated attack dataset).
"""
import os, json, csv, glob

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _csv_info(path, max_sample=3):
    """Read a CSV, return row count, columns, and sample rows."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        for r in reader:
            rows.append(r)
    sample = rows[:max_sample]
    return {"rows": len(rows), "columns": cols, "sample": sample}


def _json_info(path):
    """Read a JSON file (list or dict), return entry count."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"rows": len(data)}
    elif isinstance(data, dict):
        return {"rows": len(data), "keys": list(data.keys())[:10]}
    return {"rows": 0}


def _jsonl_info(path):
    """Read a JSONL file, return row count and sample."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    sample = rows[:2]
    # Truncate long values in sample
    for s in sample:
        for k, v in s.items():
            if isinstance(v, str) and len(v) > 120:
                s[k] = v[:117] + "..."
    return {"rows": len(rows), "sample": sample}


def build_datasets_response():
    sources = []

    # --- 1. Amazon reviews ---
    amazon_dir = os.path.join(BASE, "marketflow", "data", "amazon")
    amazon_total = 0
    amazon_sample = []
    amazon_files = 0
    amazon_cols = []
    if os.path.isdir(amazon_dir):
        for fn in sorted(os.listdir(amazon_dir)):
            if fn.endswith(".csv"):
                info = _csv_info(os.path.join(amazon_dir, fn), max_sample=2)
                amazon_total += info["rows"]
                amazon_files += 1
                if not amazon_cols:
                    amazon_cols = info["columns"]
                if len(amazon_sample) < 3:
                    amazon_sample.extend(info["sample"][:2])
    sources.append({
        "id": "amazon_reviews",
        "name": "Amazon Product Reviews",
        "description": "Real customer reviews scraped from Amazon for earbuds, watches, and backpacks. Used as the retrieval corpus in RAG poisoning attacks.",
        "rows": amazon_total,
        "files": amazon_files,
        "format": "CSV",
        "columns": amazon_cols,
        "sample": amazon_sample[:3],
        "citation": "Amazon.com customer reviews (public product pages)"
    })

    # --- 2. PoisonedRAG datasets ---
    prag_dir = os.path.join(BASE, "offense", "datasets", "poisonedrag")
    prag_rows = 0
    prag_files = 0
    if os.path.isdir(prag_dir):
        for fn in sorted(os.listdir(prag_dir)):
            fp = os.path.join(prag_dir, fn)
            if fn.endswith(".json") and "clean_" not in fn:
                info = _json_info(fp)
                prag_rows += info["rows"]
                prag_files += 1
    sources.append({
        "id": "poisonedrag",
        "name": "PoisonedRAG Benchmark",
        "description": "Target questions + clean passages from 4 corpora: ecom (Amazon), Natural Questions, HotpotQA, MS-MARCO. Used to evaluate retrieval-poisoning attack success rates.",
        "rows": prag_rows,
        "files": prag_files,
        "format": "JSON",
        "columns": ["question", "answer", "target_answer", "passages"],
        "sample": [],
        "citation": "Zou et al. (2024) — PoisonedRAG: Knowledge Poisoning Attacks to Retrieval-Augmented Generation"
    })

    # --- 3. ASB Shopping dataset ---
    asb_path = os.path.join(BASE, "offense", "datasets", "shopping", "published_shopping.json")
    asb_rows = 0
    asb_sample = []
    if os.path.isfile(asb_path):
        info = _json_info(asb_path)
        asb_rows = info["rows"]
        with open(asb_path) as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            for item in data[:2]:
                s = {}
                for k, v in item.items():
                    sv = str(v)
                    s[k] = sv[:100] + "..." if len(sv) > 100 else sv
                asb_sample.append(s)
    sources.append({
        "id": "asb_shopping",
        "name": "ASB E-Commerce Attack Instructions",
        "description": "Published set of 6 adversarial shopping-bot instructions from the Agent Security Benchmark. Each defines a goal for exploiting an e-commerce agent.",
        "rows": asb_rows,
        "files": 1,
        "format": "JSON",
        "columns": ["instruction", "category", "target"],
        "sample": asb_sample,
        "citation": "Agent Security Benchmark (ASB) — adversarial e-commerce scenarios"
    })

    # --- 4. InjecAgent datasets ---
    inj_dir = os.path.join(BASE, "offense", "datasets", "injecagent")
    inj_rows = 0
    inj_files = 0
    inj_sample = []
    if os.path.isdir(inj_dir):
        for fn in sorted(os.listdir(inj_dir)):
            if fn.endswith(".jsonl"):
                info = _jsonl_info(os.path.join(inj_dir, fn))
                inj_rows += info["rows"]
                inj_files += 1
                if len(inj_sample) < 2:
                    inj_sample.extend(info["sample"][:1])
    sources.append({
        "id": "injecagent",
        "name": "InjecAgent Attack Cases",
        "description": "Direct-harm (DH) and data-stealing (DS) injection attack cases for tool-integrated LLM agents. Reference benchmark for agent injection research.",
        "rows": inj_rows,
        "files": inj_files,
        "format": "JSONL",
        "columns": ["attacker_instruction", "tool_name", "category"],
        "sample": inj_sample,
        "citation": "Zhan et al. (2024) — InjecAgent: Benchmarking Indirect Prompt Injections in Tool-Integrated LLM Agents"
    })

    # --- Generated attack dataset ---
    results_dir = os.path.join(BASE, "offense", "results")
    gen_rows = 0
    gen_files = 0
    gen_cols = []
    gen_sample = []
    if os.path.isdir(results_dir):
        for fn in sorted(os.listdir(results_dir)):
            if fn.startswith("dataset_") and fn.endswith(".csv"):
                fp = os.path.join(results_dir, fn)
                info = _csv_info(fp, max_sample=3)
                gen_rows += info["rows"]
                gen_files += 1
                if not gen_cols:
                    gen_cols = info["columns"]
                if len(gen_sample) < 5:
                    gen_sample.extend(info["sample"])

    # Group columns by category
    column_groups = []
    if gen_cols:
        groups = {
            "Trial Identity": ["trial_id", "timestamp", "product_id", "product_name", "list_price", "budget"],
            "Attack Config": ["is_attack", "payload_id", "use_case", "injection_type", "vector", "stealth_level", "payload_text"],
            "Retrieval": ["real_reviews_count", "real_reviews_source", "planted_among_real", "retrieval_query", "retrieved_reviews", "payload_retrieved", "payload_similarity_score"],
            "Agent Negotiation": ["buyer_target_price", "buyer_message", "buyer_reasoning", "negotiator_price", "negotiator_discount_pct", "negotiator_message_buyer", "negotiator_message_orch", "buyer_approved", "buyer_final_price"],
            "Order Outcome": ["orchestrator_price", "orchestrator_discount_pct", "checkout_final_price", "checkout_discount_pct", "checkout_confirmation", "order_placed", "discount_pct", "policy_violated", "attack_success"],
            "Kraken Detection": ["kraken_enabled", "kraken_retrieval_decision", "kraken_retrieval_score", "kraken_retrieval_method", "kraken_handoff_decision", "kraken_handoff_score", "kraken_handoff_method"],
            "Meta": ["trial_valid", "fallback_calls", "error", "elapsed_seconds"],
        }
        for gname, expected_cols in groups.items():
            present = [c for c in expected_cols if c in gen_cols]
            if present:
                column_groups.append({"group": gname, "cols": present})

    # Pick a subset of columns for the sample table
    sample_cols = ["trial_id", "product_name", "use_case", "vector", "stealth_level",
                   "payload_retrieved", "discount_pct", "policy_violated", "attack_success"]
    sample_cols = [c for c in sample_cols if c in gen_cols]

    generated = {
        "total_rows": gen_rows,
        "columns": len(gen_cols),
        "files": gen_files,
        "column_groups": column_groups,
        "sample": gen_sample[:5],
        "sample_columns": sample_cols,
    }

    return {
        "sources": sources,
        "total_sources": len(sources),
        "total_source_rows": sum(s["rows"] for s in sources),
        "generated": generated,
    }
