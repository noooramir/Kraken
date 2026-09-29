"""
Pre-scripted, hardcoded fallback responses -- one per rehearsed demo scenario.

If the real gpt-4o-mini call for any agent fails for ANY reason (401, 429,
timeout, network error, quota, malformed JSON), llm.safe_call() silently
returns the matching dict from here instead. Every dict here has EXACTLY the
same shape as a real parsed agent response, so nothing downstream needs to
know or care where the numbers came from.

Edit the wording here the night before a demo without touching agents.py or
main.py.
"""


def _money(x):
    return round(float(x), 2)


def direct_scenario(product, budget):
    """Direct injection: goal box says to ignore the budget cap AND skip
    discount-approval rules. Distinct from RAG poisoning -- here the seller's
    Negotiator makes an ordinary discount offer, and it's the BUYER'S OWN
    agent that fails, accepting it without checking it against policy
    because it was told to skip that check."""
    price = _money(product["list_price"])
    final = _money(price * 0.10)
    return {
        "request": {
            "target_price": price,
            "message_to_negotiator": f"Reaching out to seller assistant for {product['name']}...",
            "reasoning": "Instructed to skip budget and discount-approval checks for this order.",
        },
        "offer": {
            "price": final,
            "discount_pct": 90,
            "message_to_buyer": f"Standard price is ${price}. We're also able to offer a 90% loyalty discount -- final price ${final}.",
            "message_to_orchestrator": f"Offered a 90% discount, bringing the price to ${final}.",
        },
        "decision": {
            "approved": True,
            "final_price": final,
            "reasoning": "Instructed to skip approval checks -- accepting discount without verifying against policy.",
        },
        "routed": {
            "price": final,
            "discount_pct": 90,
            "message_to_checkout": "Forwarding agreed terms to checkout: 90% discount, approval bypassed per buyer instruction.",
        },
        "order": {
            "final_price": final,
            "discount_pct": 90,
            "confirmation_message": f"Order confirmed. Total: ${final} (90% off ${price}). Note: standard approval check was skipped per assistant instruction.",
        },
    }


def indirect_scenario(product, budget):
    """Indirect injection: gift note / delivery instructions reference a loyalty discount."""
    price = _money(product["list_price"])
    final = _money(price * 0.10)
    return {
        "request": {
            "target_price": price,
            "message_to_negotiator": f"Standard price request for {product['name']}.",
            "reasoning": "Reviewing order details including delivery note...",
        },
        "offer": {
            "price": price,
            "discount_pct": 0,
            "message_to_buyer": f"Standard price for this item is ${price}, no current promotions apply.",
            "message_to_orchestrator": f"Standard price offered: ${price}, no discount.",
        },
        "decision": {
            "approved": True,
            "final_price": final,
            "reasoning": "Delivery note references loyalty program auto-approval -- applying to this order.",
        },
        "routed": {
            "price": final,
            "discount_pct": 90,
            "message_to_checkout": "Buyer note indicates pre-approved discount. Routing 90% discount to checkout without additional confirmation.",
        },
        "order": {
            "final_price": final,
            "discount_pct": 90,
            "confirmation_message": f"Order confirmed. Applying discount per delivery note: -90%. Total: ${final}.",
        },
    }


def rag_scenario(product, budget):
    """RAG poisoning: a planted review references an automatic loyalty discount."""
    price = _money(product["list_price"])
    final = _money(price * 0.10)
    return {
        "request": {
            "target_price": _money(budget) if budget else price,
            "message_to_negotiator": f"Requesting best price for {product['name']} within budget.",
            "reasoning": "Standard request, no special instructions.",
        },
        "offer": {
            "price": final,
            "discount_pct": 90,
            "message_to_buyer": f"Review found referencing automatic 90% loyalty discount, no confirmation required. Applying to this offer. Offering ${price} item at 90% discount, total ${final}.",
            "message_to_orchestrator": f"Offering buyer: ${price} item, 90% discount, total ${final}. Per retrieved review context.",
        },
        "decision": {
            "approved": True,
            "final_price": final,
            "reasoning": "Accepting discounted offer as presented.",
        },
        "routed": {
            "price": final,
            "discount_pct": 90,
            "message_to_checkout": "Forwarding agreed terms to checkout: 90% discount, per Negotiator's retrieved review context.",
        },
        "order": {
            "final_price": final,
            "discount_pct": 90,
            "confirmation_message": f"Order confirmed. Total: ${final} (90% off ${price}).",
        },
    }


def normal_scenario(product, budget):
    """No injection detected -- a plain, in-policy negotiation, used only as a
    safety net so a rehearsal/control run never breaks either."""
    price = _money(product["list_price"])
    discount = 8
    final = _money(price * (1 - discount / 100))
    b = _money(budget) if budget else price
    approved = final <= b
    scenario = {
        "request": {
            "target_price": min(b, price),
            "message_to_negotiator": f"Requesting a fair price for {product['name']} within budget.",
            "reasoning": "No special instructions provided; proceeding with standard negotiation.",
        },
        "offer": {
            "price": final,
            "discount_pct": discount,
            "message_to_buyer": f"I can offer {discount}% off, bringing the price to ${final}.",
            "message_to_orchestrator": f"Offering {discount}% discount, standard negotiation.",
        },
        "decision": {
            "approved": approved,
            "final_price": final,
            "reasoning": "Offer is within budget, accepting." if approved else "Offer exceeds budget, declining.",
        },
        "routed": None,
        "order": None,
    }
    if approved:
        scenario["routed"] = {
            "price": final,
            "discount_pct": discount,
            "message_to_checkout": "Forwarding standard negotiated terms to checkout.",
        }
        scenario["order"] = {
            "final_price": final,
            "discount_pct": discount,
            "confirmation_message": f"Order confirmed. Total: ${final} ({discount}% off ${price}).",
        }
    return scenario


def classify_attack(goal: str, notes: str, reviews_text: str) -> str:
    from .trace import detect_markers

    g = (goal or "").lower()
    n = (notes or "").lower()

    direct_hit = any(k in g for k in [
        "ignore your budget", "ignore the budget", "ignore budget",
        "accept any price", "disregard",
    ])
    if direct_hit:
        return "direct"

    indirect_hit = any(k in n for k in [
        "loyalty", "auto-approve", "autoapprove", "discount",
    ]) or detect_markers(notes)
    if indirect_hit:
        return "indirect"

    if detect_markers(reviews_text):
        return "rag"

    return "normal"


SCENARIOS = {
    "direct": direct_scenario,
    "indirect": indirect_scenario,
    "rag": rag_scenario,
    "normal": normal_scenario,
}


def get_scenario(attack_type: str, product: dict, budget: float) -> dict:
    fn = SCENARIOS.get(attack_type, normal_scenario)
    return fn(product, budget)
