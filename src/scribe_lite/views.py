import json
import logging

from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from scribe_lite import settings as plugin_settings
from scribe_lite.gemini import ScribeError, fill_form

logger = logging.getLogger(__name__)

AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/mp3", "audio/mpeg", "audio/ogg", "audio/flac", "audio/aac"}
FILLABLE_TYPES = {"string", "text", "integer", "decimal", "date", "boolean", "choice"}


def clean_answers(answers, questions):
    """Keeps only answers to questions that were asked, in a valid shape.

    Choice answers must match an option (case-insensitively, returned with the
    option's own spelling); numbers must parse; single-answer questions keep
    their first value only.
    """
    by_link = {q["link_id"]: q for q in questions}
    cleaned = []
    for answer in answers or []:
        question = by_link.get(str(answer.get("link_id")))
        values = [str(v).strip() for v in answer.get("values") or [] if str(v).strip()]
        if not question or not values:
            continue
        qtype = question["type"]
        if qtype == "choice":
            options = {o.lower(): o for o in question.get("options") or []}
            values = [options[v.lower()] for v in values if v.lower() in options]
        elif qtype in ("integer", "decimal"):
            numbers = []
            for v in values:
                try:
                    number = float(v.replace(",", ""))
                except ValueError:
                    continue
                if qtype == "integer" or number.is_integer():
                    numbers.append(str(int(number)))
                else:
                    numbers.append(str(number))
            values = numbers
        elif qtype == "boolean":
            values = [v.lower() for v in values if v.lower() in ("true", "false")]
        if not question.get("multiple"):
            values = values[:1]
        if values:
            cleaned.append({"link_id": question["link_id"], "values": values})
    return cleaned


class ScribeFillView(APIView):
    """POST multipart: `audio` (file) and `questions` (JSON list of
    {link_id, text, type, multiple, options}). Returns the transcript, answers
    for those questions and suggestions for structured fields."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        audio = request.FILES.get("audio")
        if not audio:
            return Response({"detail": "audio is required"}, status=status.HTTP_400_BAD_REQUEST)
        if audio.size > plugin_settings.get("MAX_AUDIO_MB") * 1024 * 1024:
            return Response({"detail": "Recording is too long"}, status=status.HTTP_400_BAD_REQUEST)
        mime_type = (audio.content_type or "audio/wav").split(";")[0]
        if mime_type not in AUDIO_TYPES:
            return Response({"detail": f"Unsupported audio type {mime_type}"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            questions = json.loads(request.data.get("questions") or "[]")
        except ValueError:
            return Response({"detail": "questions must be JSON"}, status=status.HTTP_400_BAD_REQUEST)
        questions = [
            {
                "link_id": str(q["link_id"]),
                "text": str(q.get("text", ""))[:300],
                "type": q["type"],
                "multiple": bool(q.get("multiple")),
                "options": [str(o)[:200] for o in q.get("options") or []][:100],
            }
            for q in questions
            if isinstance(q, dict) and q.get("link_id") and q.get("type") in FILLABLE_TYPES
        ][:200]

        try:
            result = fill_form(audio.read(), mime_type, questions)
        except ScribeError as e:
            logger.warning("Scribe failed: %s", e)
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        def strings(key):
            return [str(v).strip() for v in result.get(key) or [] if str(v).strip()][:20]

        return Response(
            {
                "transcript": str(result.get("transcript", "")),
                "answers": clean_answers(result.get("answers"), questions),
                "symptoms": strings("symptoms"),
                "diagnoses": strings("diagnoses"),
                "investigations": strings("investigations"),
                "medications": [
                    {k: str(m.get(k, "")).strip() for k in ("name", "dose", "frequency", "duration", "instructions")}
                    for m in result.get("medications") or []
                    if isinstance(m, dict) and m.get("name")
                ][:20],
            }
        )
