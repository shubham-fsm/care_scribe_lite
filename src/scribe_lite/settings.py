"""Plugin settings: PLUGIN_CONFIGS["scribe_lite"] first, then environment variables."""

import os

from django.conf import settings

from scribe_lite.apps import PLUGIN_NAME

DEFAULTS = {
    # Google AI Studio key. Never sent to the browser.
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "gemini-3.8-flash",
    # Comma-separated models tried when GEMINI_MODEL is overloaded (503/429/timeout).
    "GEMINI_FALLBACK_MODELS": "",
    # How many times GEMINI_MODEL is tried before the fallbacks.
    "GEMINI_ATTEMPTS_PER_MODEL": 2,
    # low keeps the doctor waiting less; medium/high think longer.
    "GEMINI_THINKING_LEVEL": "low",
    # Return a fixed sample answer instead of calling Gemini (for demos/tests).
    "SCRIBE_MOCK": False,
    "MAX_AUDIO_MB": 15,
    # Wait per Gemini call, and for all calls together (retries included).
    "REQUEST_TIMEOUT_SECONDS": 40,
    "TOTAL_TIMEOUT_SECONDS": 100,
}


def get(name):
    configs = getattr(settings, "PLUGIN_CONFIGS", {}).get(PLUGIN_NAME, {})
    if name in configs:
        return configs[name]
    default = DEFAULTS[name]
    raw = os.environ.get(name)
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    return raw
