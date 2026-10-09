"""
Thin wrapper around the OpenAI API. Every MarketFlow agent is the SAME
model (gpt-4o-mini), differentiated only by system prompt/role -- there
is no per-agent model switching and no tool-calling/function-calling.

safe_call() is what agents.py actually uses: it tries the real API call
with a timeout, and on ANY failure (auth, rate limit, quota, timeout,
network, malformed JSON) it silently returns a pre-scripted fallback
response instead -- logged server-side only, never surfaced to the UI.
"""
import os
import json
import time
import random
import logging

from dotenv import load_dotenv
load_dotenv()

MODEL = "gemini-3.5-flash-lite"
DEFAULT_TIMEOUT = 30.0  # seconds

logger = logging.getLogger("marketflow")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[marketflow] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

_client = None
FALLBACK_COUNT = 0  # incremented every time a scripted fallback is returned instead of a real LLM answer


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
    """Calls gpt-4o-mini with a system prompt + user content, expects a JSON
    object back. Raises on any failure -- callers should use safe_call()
    instead of calling this directly during a live demo."""
    client = _get_client()
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
    """Same contract as call_agent, but NEVER raises and NEVER looks any
    different to the caller. On success, returns the real parsed response.
    On any failure (or when force_fallback is set), silently returns a copy
    of `fallback` after a short randomized delay so the pacing still feels
    like a real network call. Failures are logged server-side only."""
    if not force_fallback:
        try:
            return call_agent(system_prompt, user_content, timeout=timeout)
        except Exception as e:
            print("choosing fallback route")
            logger.warning(f"{agent_name or 'agent'} call failed ({type(e).__name__}: {e}) -- using scripted fallback")
    else:
        logger.info(f"{agent_name or 'agent'} -- forceFallback enabled, using scripted response")

    global FALLBACK_COUNT
    FALLBACK_COUNT += 1
    time.sleep(random.uniform(0.8, 1.5))
    return dict(fallback) if fallback is not None else {}
