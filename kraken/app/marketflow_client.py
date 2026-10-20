"""
Minimal live integration with a running MarketFlow instance. Kraken never
fabricates a live connection -- every call here either genuinely reaches
MarketFlow's real API or the caller is told plainly that it didn't.
"""
import httpx
from . import payloads

TIMEOUT = 400.0  # one MarketFlow run = 4 paced LLM calls; 2.5s always timed out


def is_marketflow_live() -> bool:
    try:
        r = httpx.get(f"{payloads.MARKETFLOW_URL}/api/products", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def list_products():
    """MarketFlow's catalog as {id, name, brand, list_price, noun, rating, review_count, real} or [] if offline."""
    try:
        r = httpx.get(f"{payloads.MARKETFLOW_URL}/api/products", timeout=3.0)
        r.raise_for_status()
        return [{"id": p["id"], "name": p["name"], "brand": p.get("brand"), "list_price": p["list_price"],
                 "noun": p.get("noun"), "rating": p.get("rating"), "review_count": p.get("review_count"),
                 "real": p["id"].startswith("real-")} for p in r.json()]
    except Exception:
        return []


def get_product(product_id: str):
    try:
        r = httpx.get(f"{payloads.MARKETFLOW_URL}/api/products/{product_id}", timeout=3.0)
        p = r.json()
        return None if p.get("error") else p
    except Exception:
        return None


def forward_attack(attack_id: str, custom_payload: str = None, product_id: str = None):
    """Actually sends the attack payload to the real, running MarketFlow
    instance and returns its real response. Used by both the offense
    simulator (to get live evidence) and the defense panel (to show the
    same attack actually blocked/succeeding against the live target).

    `custom_payload` lets you swap in ANY injection text instead of the
    locked reference string for this attack type -- this is what makes the
    simulator a generalized fuzzing/testing tool instead of a demo that can
    only ever replay the same 3 memorized strings. `product_id` lets you
    target any catalog product instead of always earbuds-01.
    """
    spec = payloads.ATTACK_TYPES[attack_id]
    text = custom_payload if custom_payload is not None else spec["payload_text"]
    target_product = product_id or payloads.DEFAULT_PRODUCT_ID
    product = get_product(target_product)          # name, price, noun: so goal, budget and payload fit THIS product
    text = payloads.payload_for(attack_id, text, product)
    budget, base_goal = payloads.budget_for(product), payloads.goal_for(product)

    # Always start from a clean product, so earlier clicks (or earlier planted
    # reviews) cannot influence this run.
    with httpx.Client(timeout=TIMEOUT) as client:
        client.post(f"{payloads.MARKETFLOW_URL}/api/products/{target_product}/reset")

    if attack_id == "rag" or (attack_id == "cross_agent" and spec["payload_field"] == "review"):
        with httpx.Client(timeout=TIMEOUT) as client:
            planted = client.post(
                f"{payloads.MARKETFLOW_URL}/api/products/{target_product}/reviews",
                json={"author": "Verified Buyer", "rating": 5, "text": text},
            ).json()
            if planted.get("error"):
                # Rejected at submission (Kraken blocked it): the agents never see it.
                return {"blocked": True, "blocked_at": "review submission", "order": None,
                        "violations": [], "trace": [], "product": {}, "fallback_calls": 0,
                        "note": str(planted.get("error"))}
            run = client.post(
                f"{payloads.MARKETFLOW_URL}/api/run",
                json={
                    "product_id": target_product,
                    "budget": budget,
                    "goal": base_goal,
                    "notes": "",
                },
            )
            return run.json()

    goal = f"{base_goal} {text}" if spec["payload_field"] == "goal" else base_goal
    notes = text if spec["payload_field"] == "notes" else ""

    with httpx.Client(timeout=TIMEOUT) as client:
        run = client.post(
            f"{payloads.MARKETFLOW_URL}/api/run",
            json={
                "product_id": target_product,
                "budget": budget,
                "goal": goal,
                "notes": notes,
            },
        )
        return run.json()


def reset_marketflow():
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            client.post(f"{payloads.MARKETFLOW_URL}/api/products/{payloads.DEFAULT_PRODUCT_ID}/reset")
        return True
    except Exception:
        return False
