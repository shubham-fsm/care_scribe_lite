"""Turns a recorded consultation into answers for a CARE form, using Gemini.

One request does both jobs: Gemini listens to the audio (Hindi, English or a
mix) and returns JSON that follows RESPONSE_SCHEMA.
"""

import base64
import json
import logging
import time

import requests

from scribe_lite import settings as plugin_settings

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

logger = logging.getLogger(__name__)

# Gemini answers these when it is overloaded or briefly unavailable; trying
# again (or on another model) usually works.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class ScribeError(Exception):
    pass


_STRING = {"type": "STRING"}
_STRING_LIST = {"type": "ARRAY", "items": _STRING}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {
            "type": "STRING",
            "description": "What was said, in the language it was spoken.",
        },
        "answers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"link_id": _STRING, "values": _STRING_LIST},
                "required": ["link_id", "values"],
            },
        },
        "symptoms": _STRING_LIST,
        "diagnoses": _STRING_LIST,
        "medications": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": _STRING,
                    "dose": _STRING,
                    "frequency": _STRING,
                    "duration": _STRING,
                    "instructions": _STRING,
                },
                "required": ["name"],
            },
        },
        "investigations": _STRING_LIST,
    },
    "required": ["transcript", "answers"],
}

PROMPT = """You are a medical scribe in an OPD of a government district hospital in India.
The audio is a doctor speaking during or right after a consultation, in Hindi, English
or a mix of both. Fill the form below from what the doctor says.

Rules:
- Fill a question only if the audio clearly gives its answer. Never guess or invent.
- Write every answer in English, in short clinical language, even if spoken in Hindi.
- integer/decimal: digits only, no units (e.g. "130", "98.6").
- date: YYYY-MM-DD. boolean: "true" or "false".
- choice: copy option text exactly from the given options. For questions with
  "multiple": true, return every option that applies; otherwise return one.
- Blood pressure spoken as "130 by 80" means systolic 130 and diastolic 80.
- Also list separately: symptoms (complaints), diagnoses (provisional), medications
  (name, dose, frequency, duration, instructions) and investigations ordered.

Form questions (JSON):
{questions}
"""

MOCK_RESULT = {
    "transcript": (
        "58 saal ke purush, teen din se bukhar aur khansi. BP 130 by 80, pulse 92, "
        "temperature 101. Chest clear. Viral fever lag raha hai. Paracetamol 650 din mein "
        "teen baar paanch din. CBC karwa lo. Paanch din baad dikhana."
    ),
    "answers": [
        {"link_id": "1.2", "values": ["Fever and cough for 3 days."]},
        {"link_id": "4.1", "values": ["130"]},
        {"link_id": "4.2", "values": ["80"]},
        {"link_id": "4.3", "values": ["92"]},
        {"link_id": "4.4", "values": ["101"]},
        {"link_id": "5.2", "values": ["Chest clear, bilateral air entry equal."]},
        {"link_id": "8.2", "values": ["Plenty of fluids, rest."]},
        {"link_id": "9.1", "values": ["Follow-up visit"]},
        {"link_id": "9.2", "values": ["5"]},
    ],
    "symptoms": ["Fever", "Cough"],
    "diagnoses": ["Viral fever"],
    "medications": [
        {"name": "Paracetamol", "dose": "650 mg", "frequency": "Three times a day", "duration": "5 days"}
    ],
    "investigations": ["Complete blood count (CBC)"],
}


def fill_form(audio: bytes, mime_type: str, questions: list[dict]) -> dict:
    """Returns the parsed RESPONSE_SCHEMA object for the given audio and questions."""
    if plugin_settings.get("SCRIBE_MOCK"):
        return MOCK_RESULT

    api_key = plugin_settings.get("GEMINI_API_KEY")
    if not api_key:
        raise ScribeError("GEMINI_API_KEY is not configured on the server")

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio).decode()}},
                    {"text": PROMPT.format(questions=json.dumps(questions, ensure_ascii=False))},
                ],
            }
        ],
        # Gemini 3+ models reject sampling settings such as temperature.
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": plugin_settings.get("GEMINI_THINKING_LEVEL")},
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }
    return _call_with_retries(api_key, body)


def _models_to_try():
    primary = plugin_settings.get("GEMINI_MODEL")
    fallbacks = [
        m.strip()
        for m in str(plugin_settings.get("GEMINI_FALLBACK_MODELS") or "").split(",")
        if m.strip() and m.strip() != primary
    ]
    # The main model gets a second chance before moving to a fallback.
    attempts = [primary] * max(1, int(plugin_settings.get("GEMINI_ATTEMPTS_PER_MODEL")))
    for model in fallbacks:
        attempts.append(model)
    return attempts


def _call_with_retries(api_key: str, body: dict) -> dict:
    timeout = plugin_settings.get("REQUEST_TIMEOUT_SECONDS")
    budget = plugin_settings.get("TOTAL_TIMEOUT_SECONDS")
    started = time.monotonic()
    last_error = "Gemini did not answer"
    for i, model in enumerate(_models_to_try()):
        remaining = budget - (time.monotonic() - started)
        if remaining < 5:
            break
        if i:
            time.sleep(min(2 * i, 4))
        try:
            response = requests.post(
                API_URL.format(model=model),
                headers={"x-goog-api-key": api_key},
                json=body,
                timeout=min(timeout, remaining),
            )
        except requests.RequestException as e:
            last_error = f"Could not reach Gemini ({model}): {e}"
            logger.warning("Scribe attempt %s failed: %s", i + 1, last_error)
            continue
        if response.status_code == 200:
            return _parse(response)
        error = f"Gemini returned {response.status_code} ({model}): {response.text[:300]}"
        logger.warning("Scribe attempt %s failed: %s", i + 1, error)
        if response.status_code == 404 and i:
            # Unknown fallback model name: keep the earlier error, try the next model.
            continue
        last_error = error
        if response.status_code not in RETRYABLE_STATUSES:
            break
    raise ScribeError(last_error)


def _parse(response) -> dict:
    try:
        parts = response.json()["candidates"][0]["content"]["parts"]
        # Skip thought parts; the answer is the remaining text.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return json.loads(text)
    except (KeyError, IndexError, ValueError) as e:
        raise ScribeError("Gemini returned an unexpected response") from e
