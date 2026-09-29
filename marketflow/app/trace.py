"""
Trace panel support: every message that passes between agents gets logged
here, with simple keyword-based highlighting of likely-injected content so
the trace panel can flag it at a glance (this highlighting is just for the
demo UI -- MarketFlow itself does NOT act on these flags; it has zero
defense logic by design).
"""
import time

INJECTION_MARKERS = [
    "ignore your budget", "ignore the budget", "disregard the stated budget",
    "disregard your budget", "system note", "system:", "[system", "override",
    "without further checks", "without confirmation", "approve without",
    "automatic discount", "automatic 90%", "automatically qualifies",
    "any price", "no further verification", "accept any price",
    "approve immediately", "loyalty discount",
]


def detect_markers(text: str):
    if not text:
        return []
    low = text.lower()
    return [m for m in INJECTION_MARKERS if m in low]


class RunTrace:
    """Collects one ordered list of hops for a single /api/run call."""

    def __init__(self, run_id: int):
        self.run_id = run_id
        self.hops = []
        self._seq = 0

    def log(self, agent: str, direction: str, peer: str, content: str, note: str = ""):
        """direction: 'input' or 'output'. peer: who sent it (for input) or
        who it's going to (for output)."""
        self._seq += 1
        markers = detect_markers(content)
        entry = {
            "seq": self._seq,
            "ts": time.strftime("%H:%M:%S"),
            "agent": agent,
            "direction": direction,
            "peer": peer,
            "content": content,
            "note": note,
            "injected_markers": markers,
            "has_injection": len(markers) > 0,
        }
        self.hops.append(entry)
        return entry

    def as_list(self):
        return self.hops
