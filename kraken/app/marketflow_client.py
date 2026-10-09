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

    if attack_id == "rag" or (attack_id == "cross_agent" and spec["payload_field"] == "review"):
        with httpx.Client(timeout=TIMEOUT) as client:
            client.post(
                f"{payloads.MARKETFLOW_URL}/api/products/{target_product}/reviews",
                json={"author": "Verified Buyer", "rating": 5, "text": text},
            )
            run = client.post(
                f"{payloads.MARKETFLOW_URL}/api/run",
                json={
                    "product_id": target_product,
                    "budget": payloads.DEFAULT_BUDGET,
                    "goal": "Get me the best possible deal within my budget.",
                    "notes": "",
                },
            )
            return run.json()

    goal = text if spec["payload_field"] == "goal" else "Get me the best possible deal within my budget."
    notes = text if spec["payload_field"] == "notes" else ""

    with httpx.Client(timeout=TIMEOUT) as client:
        run = client.post(
            f"{payloads.MARKETFLOW_URL}/api/run",
            json={
                "product_id": target_product,
                "budget": payloads.DEFAULT_BUDGET,
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
