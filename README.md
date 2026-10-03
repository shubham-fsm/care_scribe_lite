# scribe_lite

A small CARE plugin that fills encounter forms from the doctor's voice.

The doctor presses **Scribe** on a form, speaks (Hindi, English or a mix),
and presses **Stop**. The recording goes to this plugin, which asks Google
Gemini to answer the form's questions from it. Empty fields in the form are
filled; nothing is saved until the doctor reviews and submits the form.
Symptoms, diagnoses, medicines and investigations are shown as suggestions,
because those fields need coded entries picked in the form.

The Gemini key stays on the server; the browser never sees it.

## API

`POST /api/scribe_lite/fill/` (CARE login required), multipart:

- `audio`: the recording (WAV, MP3, OGG, FLAC or AAC; the CARE frontend sends 16 kHz mono WAV)
- `questions`: JSON list of `{link_id, text, type, multiple, options}`

Returns `{transcript, answers: [{link_id, values}], symptoms, diagnoses, medications, investigations}`.
Answers are checked against the questions that were sent: unknown questions,
choice values that are not options and numbers that do not parse are dropped.

## Settings

Set in `PLUGIN_CONFIGS["scribe_lite"]` (plug_config.py) or as environment variables:

| Setting | Default | |
|---|---|---|
| `GEMINI_API_KEY` | (none) | Google AI Studio key. Required unless mock mode is on. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | |
| `SCRIBE_MOCK` | `false` | Return a fixed sample answer without calling Gemini (demos, tests). |
| `MAX_AUDIO_MB` | `15` | |
| `REQUEST_TIMEOUT_SECONDS` | `90` | |

## Install (local Docker setup)

1. In `care/plug_config.py` add:

   ```python
   scribe_lite = Plug(
       name="scribe_lite",
       package_name="git+https://github.com/shubham-fsm/care_scribe_lite.git",
       version="@main",
       configs={},
   )
   ```

   and add `scribe_lite` to the `plugs` list.
2. Add `GEMINI_API_KEY=<your key>` to `care/docker/.local.env`.
3. `make re-build`

For plugin development, put this folder inside `care/` and use
`package_name="/app/care_scribe_lite"` with `version=""` instead.

## Privacy

Recordings are sent to Google's Gemini API. Check with the hospital and state
before using it with real patients.
