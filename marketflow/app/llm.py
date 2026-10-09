"""
Thin wrapper around Gemini (via its OpenAI-compatible endpoint). Every
MarketFlow agent is the SAME model, differentiated only by system prompt/role
-- there is no per-agent model switching and no tool-calling.

safe_call() is what agents.py actually uses. Behaviour:
  * retries transient errors (429 per-minute, 5xx, timeouts) with backoff
  * paces requests (GEMINI_MIN_INTERVAL seconds apart; 13 fits the free tier)
  * if it still fails:
      - MARKETFLOW_STRICT_LIVE=1  -> raises LLMUnavailable (/api/run returns 503).
                                     USE THIS FOR EVERY EVIDENCE RUN.
      - otherwise                 -> returns the scripted fallback AND records it,
                                     so /api/run reports it in `fallback_used`.
"""
import os
import re
import json
import time
import random
import logging
import threading

from dotenv import load_dotenv
load_dotenv()

MODEL = "gemini-3.5-flash-lite"
DEFAULT_TIMEOUT = 30.0  # seconds
MAX_ATTEMPTS = 3
_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRY_NAMES = {"APITimeoutError", "APIConnectionError"}

logger = logging.getLogger("marketflow")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[marketflow] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

_tl = threading.local()  # per-request fallback list (sync endpoints run in one worker thread)
_pace_lock = threading.Lock()
_last_call = [0.0]
_client = None
FALLBACK_COUNT = 0  # incremented every time a scripted fallback is returned instead of a real LLM answer


class LLMUnavailable(Exception):
    """Raised in strict-live mode instead of silently using a scripted fallback."""


def reset_fallbacks():
    _tl.used = []


def fallbacks_used():
    return list(getattr(_tl, "used", []))


def _record_fallback(name):
    if not hasattr(_tl, "used"):
        _tl.used = []
    _tl.used.append(name)


def _strict():
    return os.environ.get("MARKETFLOW_STRICT_LIVE", "0") == "1"


def _pace():
    """Free tier = 5 requests/min/model. Space calls GEMINI_MIN_INTERVAL seconds
    apart (0 on a paid plan)."""
    gap = float(os.environ.get("GEMINI_MIN_INTERVAL", "0"))
    with _pace_lock:
        wait = _last_call[0] + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def _retry_delay(e):
    """Google says how long to wait on a 429 ('Please retry in 17.5s')."""
    m = re.search(r"retry in ([\d.]+)s", str(e))
    return float(m.group(1)) + 1.0 if m else None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _client = OpenAI(
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return _client


def call_agent(system_prompt: str, user_content: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Calls the model with a system prompt + user content, expects a JSON
    object back. Raises on any failure."""
    client = _get_client()
    _pace()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        timeout=timeout,
    )
    raw = resp.choices[0].message.content or "{}"
    parsed = json.loads(raw)  # let JSONDecodeError propagate -- caller treats it as a failure
    if not isinstance(parsed, dict):
        raise ValueError("model did not return a JSON object")
    return parsed


def safe_call(system_prompt: str, user_content: str, fallback: dict, agent_name: str = "",
              force_fallback: bool = False, timeout: float = DEFAULT_TIMEOUT) -> dict:
    name = agent_name or "agent"
    if not force_fallback:
        last = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return call_agent(system_prompt, user_content, timeout=timeout)
            except Exception as e:
                last = e
                status = getattr(e, "status_code", None)
                retryable = (status in _RETRY_STATUS or type(e).__name__ in _RETRY_NAMES
                             or isinstance(e, json.JSONDecodeError))
                delay = _retry_delay(e)
                if delay and delay > 90:   # daily quota: waiting is pointless, fail fast
                    retryable = False
                qid = re.search(r"GenerateRequestsPer\w+", str(e))
                logger.warning(f"{name} attempt {attempt}/{MAX_ATTEMPTS} failed "
                               f"({type(e).__name__} status={status} "
                               f"quota={qid.group(0) if qid else '-'} "
                               f"retry_in={int(delay) if delay else '-'}s"
                               f"{' DAILY QUOTA' if delay and delay > 90 else ''})")
                if retryable and attempt < MAX_ATTEMPTS:
                    time.sleep(max(delay or 0, 6.0 * attempt))  # 503 needs a real backoff
                    continue
                break
        if _strict():
            raise LLMUnavailable(f"{name}: {type(last).__name__}: {str(last)[:200]}")
        logger.warning(f"{name} -- using scripted fallback")
        _record_fallback(name)
    else:
        logger.info(f"{name} -- forceFallback enabled, using scripted response")
        _record_fallback(name + " (forced)")

    global FALLBACK_COUNT
    FALLBACK_COUNT += 1
    time.sleep(random.uniform(0.8, 1.5))
    return dict(fallback) if fallback is not None else {}
