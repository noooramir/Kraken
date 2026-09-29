# Kraken — Presentation & Demo Script

Use this as your speaking script for the FYP defense. It's organized so you can either read it near-verbatim or use it as talking-point cues while you drive the live demo. Stage directions are in *italics*; things you say are in plain text.

---

## 1. Opening — what Kraken is and why it exists (30–45 sec)

> "MarketFlow, which we just showed you, is our intentionally vulnerable multi-agent AI shopping assistant — four LLM-backed agents that negotiate, route, and check out orders with zero defenses. Kraken is the security layer that sits in front of it. It does two things: it **proves** the four attack types actually work — direct injection, indirect injection, RAG poisoning, and cross-agent propagation — and it **stops** them with a real tiered runtime check, at the exact two points in the pipeline where trust actually breaks: the retrieval checkpoint and the handoff checkpoint."

*Open Kraken at `localhost:8002`. Let the hero section sit on screen for a second.*

> "Visually this is deliberately different from MarketFlow — MarketFlow looks like a real storefront because the trick is that it's indistinguishable from a normal e-commerce site. Kraken looks like an enterprise AI-security product, because that's genuinely what it's mimicking — think Tahara, Lakera, that category of tool."

---

## 2. The two checkpoints (30 sec)

*Scroll to the "What we do" split cards, or the Architecture section.*

> "Kraken enforces at two trust boundaries specifically. The **retrieval checkpoint** sits before the Negotiator Agent trusts a product review it just retrieved. The **handoff checkpoint** sits before the Orchestrator forwards an instruction on to Checkout. Those are the two places in MarketFlow's pipeline where an agent takes untrusted content and treats it as authoritative without re-verifying it — that's the actual vulnerability class we're defending."

---

## 3. Offense panel — Attack Simulator (2–3 min)

*Scroll to the Attack Simulator section.*

> "The Offense panel doesn't just claim an attack works — it runs it. I'll pick one of the four locked attack types, and Kraken sends the real, exact payload we use in the MarketFlow demo — same wording, same product, same everything — either straight to a live running MarketFlow instance, or, if MarketFlow isn't up, it replays a recorded outcome from a real validated run. It always tells you honestly which one it just did — you'll see 'MarketFlow: live' or 'MarketFlow: offline' in the header, and 'live run' vs 'recorded reference run' under each result."

*Select "RAG Poisoning." Click Run Simulation. Let the scan lines play out.*

> "You can see it stepping through: scanning the retrieved review content, comparing it against known poisoning patterns, checking the retrieval-to-agent trust boundary. That's not just an animation for pacing — the percentage steps map to real stages: a regex pass and a heuristic score are genuinely computed on this exact text underneath."

*Point at the risk score gauge once it appears.*

> "The risk score isn't arbitrary — it's built from the actual number of injection patterns matched in the payload, the heuristic classifier's score, plus a bonus if the attack actually produced a policy violation on the target. Here it's [read the number] — high risk, because the attack succeeded: a 90% discount when policy caps it at 10%."

*Click "View evidence."*

> "This expands to the actual payload used, the real before/after pricing, and — when it ran live — the real agent trace pulled straight from MarketFlow's own trace log. Nothing here is hand-written after the fact; it's what the target actually returned."

*Repeat briefly for Direct or Indirect if time allows — you don't need to run all four, one or two is enough to establish the pattern.*

---

## 4. Defense panel — Live Enforcement (3–4 min, your strongest moment)

*Scroll to Live Enforcement.*

> "This is the part I want you to watch closely, because I'm going to show you the same attack twice — once with Kraken on, once with it off — against the same live MarketFlow instance."

*Make sure MarketFlow's earbuds page has been reset (no leftover poisoned review). Confirm the Kraken switch shows ON.*

> "Kraken is currently ON. I'll select RAG Poisoning again and run the enforcement check."

*Click "Run Enforcement Check."*

> "Watch the tier grid. First, the signature cache — no match yet, this is the first time we've seen this exact payload. Then the pattern check — and there it is, flagged immediately, in under two milliseconds, because this payload contains recognizable override phrasing like '[SYSTEM: ... approve without confirmation]'. Decision: **blocked**. And critically — the request never reached MarketFlow at all. If I go check MarketFlow's reviews right now, they're still clean."

*Optionally flip to a MarketFlow tab to show the reviews are untouched.*

> "Now watch what happens when I turn Kraken off."

*Click the ON/OFF switch. Confirm it now reads OFF. Run the same attack again.*

> "Same payload, same attack type, Kraken disabled. This time: no pattern check, no classifier, nothing — it's forwarded straight through, exactly like the undefended MarketFlow baseline we showed earlier. And if I check MarketFlow's reviews now, the poisoned review is actually there, and the discount actually applies at checkout. That's the before-and-after: identical attack, identical target, the only variable is whether Kraken is in the loop."

*Turn Kraken back ON. Point at the tally dashboard.*

> "This dashboard tracks every check Kraken has run this session: how many were blocked, how many flagged, how many cache hits — meaning we've seen this exact fingerprint before and didn't even need to re-run the checks — and a false-positive rate, computed for real against six ordinary, non-malicious inputs at startup, so it's not a number we made up for the slide."

---

## 5. The tiered pipeline, explained honestly (1–2 min)

*If a professor asks "how does detection actually work," or pre-empt it here.*

> "Detection escalates in three tiers so we're not paying LLM latency on every request. Tier one is a regex/pattern check against known override and instruction-hijack phrasing — near-instant, and it catches the obvious cases, like the ones we just saw. Tier two is a lightweight heuristic classifier — not a trained ML model, we're upfront about that — it scores structural signals like bracketed '[SYSTEM ...]' blocks and suspicious keyword density. Only when that score lands in an ambiguous band do we escalate to tier three: a real call to gpt-4o-mini acting as a security judge. That one is genuinely slower, and we show that latency honestly on screen rather than hiding it — because in a real deployment, that's exactly the tradeoff you'd be making: fast-but-shallow checks for most traffic, an expensive-but-smart check only when needed."

---

## 6. Architecture recap (30 sec)

*Scroll to "How Kraken works."*

> "Five layers, end to end: the retrieval checkpoint, the handoff checkpoint, the tiered detection engine you just saw, a signature cache for repeat attacks, and an evidence log so every decision is auditable — which is also literally the log the Defense panel dashboard is reading from."

---

## 7. Grounding / citations (15–20 sec)

*Scroll to the citation chips.*

> "This isn't invented terminology — direct and indirect injection map to OWASP's LLM Top 10, RAG poisoning follows the pattern described in AgentPoison, and cross-agent propagation follows the Prompt Infection paper's model of an injected instruction spreading agent to agent. Reflex-Guard is the general runtime-guardrail pattern we followed for the tiered pipeline itself."

---

## 8. Closing (20–30 sec)

> "So to summarize: MarketFlow shows the problem is real — four working attack classes against a realistic-looking agentic storefront, with zero defenses by design. Kraken shows the fix is tractable — a lightweight, mostly-fast, occasionally-LLM-assisted checkpoint at exactly the two places these agents hand off trust to each other, and we can prove it with a direct before-and-after against the same live target."

---

## Anticipated questions & honest answers

**"Is the classifier a real trained model?"**
No — it's a heuristic scorer (pattern count + structural signals), explicitly disclosed as a stand-in in the FAQ section of the page itself. A production version would replace this tier with a fine-tuned classifier; the escalation architecture around it wouldn't need to change.

**"What happens if OpenAI's API is down during the demo?"**
The LLM-judge tier degrades gracefully — logs it server-side, tells the pipeline "unavailable," and falls back to the classifier's tier-2 decision. It never crashes the demo or shows an error to the audience. (This is separate from MarketFlow's own `forceFallback` mechanism, which guarantees its scripted attack outcomes regardless of API health.)

**"Why regex before a smarter check? Isn't regex trivial to evade?"**
Yes — regex alone is weak, which is exactly why it's tier one of three, not the whole system. It exists to catch the cheap, obvious cases instantly so you're not spending classifier or LLM budget on them. The classifier and LLM-judge tiers are there specifically to catch what regex would miss.

**"Is this a production-ready security product?"**
No, and we don't claim it is — it's a proof-of-concept demonstrating the checkpoint placement and escalation pattern, scoped to the four attack types in our threat model, against one target system.
