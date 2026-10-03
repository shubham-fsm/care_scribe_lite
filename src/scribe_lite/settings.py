"""Plugin settings: PLUGIN_CONFIGS["scribe_lite"] first, then environment variables."""

import os

from django.conf import settings

from scribe_lite.apps import PLUGIN_NAME

DEFAULTS = {
    # Google AI Studio key. Never sent to the browser.
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "gemini-3.8-flash",
    # low keeps the doctor waiting less; medium/high think longer.
    "GEMINI_THINKING_LEVEL": "low",
    # Return a fixed sample answer instead of calling Gemini (for demos/tests).
    "SCRIBE_MOCK": False,
    "MAX_AUDIO_MB": 15,
    "REQUEST_TIMEOUT_SECONDS": 90,
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
