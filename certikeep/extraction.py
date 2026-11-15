"""AI feature: read a certificate scan with Gemini and return structured fields.

The model only *suggests* values. They are validated in code (domain.validate) and
a person must confirm them before a certificate can turn green.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .domain import CERT_TYPES, canonical_cert_type, parse_date

FIELDS = ["worker_name", "certificate_type", "issue_date", "expiry_date"]

PROMPT = """You are reading ONE worker certificate (training certificate, licence, or
medical fitness-for-work certificate) uploaded by a company.

Extract exactly these fields:
- worker_name: full name of the person the certificate is about (not the doctor, trainer or company).
- certificate_type: one of {types}. Use "other" if none fits.
- issue_date: date of issue / exam / training, as YYYY-MM-DD.
- expiry_date: date the certificate stops being valid (expiry, "valid until", next exam due), as YYYY-MM-DD.
Dates on these documents are usually European (day first): 03/04/2027 is 3 April 2027.

Rules:
- Only report what is printed on the document. NEVER guess or compute a value.
  If a field is not visible or you are unsure, return null for it.
- Do not calculate an expiry date from the issue date and a validity period.
- For each field give confidence "high", "medium" or "low".
- Set readable=false if the image is too blurry, cut off, or not a certificate.
{workers}"""

_FIELD_SCHEMA = {
    "type": "OBJECT",
    "properties": {"value": {"type": "STRING", "nullable": True},
                   "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]}},
    "required": ["value", "confidence"],
}
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"readable": {"type": "BOOLEAN"}, **{f: _FIELD_SCHEMA for f in FIELDS},
                   "notes": {"type": "STRING", "nullable": True}},
    "required": ["readable", *FIELDS],
}


@dataclass
class Extraction:
    fields: dict = field(default_factory=lambda: {f: None for f in FIELDS})
    confidences: dict = field(default_factory=lambda: {f: "low" for f in FIELDS})
    readable: bool = False
    model: str = ""
    raw: str = ""
    error: str | None = None
    latency_s: float = 0.0


class ExtractionError(RuntimeError):
    """Setup problem (no key, wrong model) — shown to the user, document goes to review."""


def build_prompt(known_workers: list[str]) -> str:
    hint = ""
    if known_workers:
        hint = ("\nKnown workers of this company (use the exact spelling if the name on the document is "
                "clearly one of them, otherwise copy the name as printed):\n- " + "\n- ".join(known_workers))
    return PROMPT.format(types=", ".join(CERT_TYPES), workers=hint)


def parse_response(raw: str) -> Extraction:
    """Turn the model's JSON into an Extraction. Anything unparseable -> unreadable, all None."""
    ex = Extraction(raw=raw)
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        ex.error = "The AI returned an answer we could not read."
        return ex
    ex.readable = bool(data.get("readable", False))
    for f in FIELDS:
        item = data.get(f) or {}
        value = item.get("value") if isinstance(item, dict) else None
        if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a", "unknown"}:
            value = None
        if value is not None and f.endswith("_date"):
            d = parse_date(value)
            value = d.isoformat() if d else None   # unparseable date -> None, never a guess
        if value is not None and f == "certificate_type":
            value = canonical_cert_type(value)
        ex.fields[f] = value
        conf = item.get("confidence") if isinstance(item, dict) else None
        ex.confidences[f] = conf if conf in {"high", "medium", "low"} else "low"
    return ex

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_FALLBACK_MODEL = "gemini-3.8-flash"   # tried when the main model is overloaded, slow or retired
ATTEMPT_TIMEOUT_S = 30     # one call may take this long, then we move on
TOTAL_BUDGET_S = 100       # the whole read gives up after this, so nobody waits forever
BUSY_COOLDOWN_S = 300      # a model that was overloaded is tried last for this long

_busy_until: dict[str, float] = {}   # model -> time.time() until which it counts as busy


def model_chain() -> list[str]:
    """Models to try, in order: GEMINI_MODEL, then GEMINI_FALLBACK_MODEL (comma-separated, may be empty)."""
    primary = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    fallbacks = os.environ.get("GEMINI_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL).split(",")
    return list(dict.fromkeys([primary, *(m.strip() for m in fallbacks if m.strip())]))


def _gemini_caller(api_key: str, file_bytes: bytes, mime_type: str, prompt: str):
    """Return generate(model, timeout_s) -> raw JSON text, backed by the real Gemini API."""
    from google import genai          # imported here so the rest of the app runs without the SDK
    from google.genai import types

    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                         response_schema=RESPONSE_SCHEMA)
    contents = [types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt]

    def generate(model: str, timeout_s: float) -> str:
        # Without a timeout the SDK waits as long as Google does (minutes when the model is overloaded).
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        return client.models.generate_content(model=model, contents=contents, config=config).text

    return generate


def extract(file_bytes: bytes, mime_type: str, known_workers: list[str], generate=None) -> Extraction:
    """Read one document with Gemini. Network/model errors are returned in Extraction.error.

    Each call is capped at ATTEMPT_TIMEOUT_S. If a model is overloaded, too slow or not found, the next
    model in model_chain() is tried; the whole read stops after TOTAL_BUDGET_S. An overloaded model is
    tried last for the next BUSY_COOLDOWN_S.
    `generate` is only passed by unit tests.
    """
    if generate is None:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ExtractionError("GEMINI_API_KEY is not set. Add it to the .env file (see README).")
        generate = _gemini_caller(api_key, file_bytes, mime_type, build_prompt(known_workers))

    # Models that were overloaded a moment ago go to the back, so the next upload does not wait for them again.
    models = sorted(model_chain(), key=lambda m: _busy_until.get(m, 0) > time.time())
    start = time.perf_counter()
    elapsed = lambda: time.perf_counter() - start   # noqa: E731
    failures: list[tuple[str, str]] = []            # (kind, message)
    for round_no in range(2):
        busy = False
        for model in models:
            left = TOTAL_BUDGET_S - elapsed()
            if left < 5:
                break
            try:
                raw = generate(model, min(ATTEMPT_TIMEOUT_S, left))
            except Exception as exc:  # noqa: BLE001 - the SDK raises several error types
                kind = _kind(exc)
                failures.append((kind, str(exc)))
                if kind == "auth":                  # the same key fails on every model
                    return Extraction(model=model, error=_friendly(failures), latency_s=round(elapsed(), 2))
                if kind == "busy":
                    busy = True
                    _busy_until[model] = time.time() + BUSY_COOLDOWN_S
                continue
            _busy_until.pop(model, None)
            ex = parse_response(raw)
            ex.model, ex.latency_s = model, round(elapsed(), 2)
            return ex
        # One more round only for overload/timeouts, which are often gone a few seconds later.
        if not busy or round_no or TOTAL_BUDGET_S - elapsed() < 10:
            break
        time.sleep(3)
    return Extraction(model=models[0], error=_friendly(failures), latency_s=round(elapsed(), 2))


def _kind(exc: Exception) -> str:
    """Classify an SDK/network error: auth, quota, busy (overloaded or timed out), not_found or other."""
    code, msg = getattr(exc, "code", None), str(exc)
    has = lambda *words: any(w in msg for w in words)   # noqa: E731
    if code in (401, 403) or has("API_KEY", "API key", "PERMISSION_DENIED", "UNAUTHENTICATED"):
        return "auth"
    if code == 429 or has("429", "RESOURCE_EXHAUSTED"):
        return "quota"
    if code == 404 or has("NOT_FOUND"):
        return "not_found"
    if (code in (500, 502, 503, 504) or "timeout" in type(exc).__name__.lower()
            or has("503", "504", "UNAVAILABLE", "DEADLINE_EXCEEDED", "timed out", "overloaded")):
        return "busy"
    return "other"


def _friendly(failures: list[tuple[str, str]]) -> str:
    kinds = [k for k, _ in failures]
    if "auth" in kinds:
        return "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
    if "quota" in kinds:
        return "Gemini free-tier limit reached. Wait a minute and press 'Run AI again', or fill in the fields by hand."
    if "busy" in kinds:
        return ("Gemini is overloaded or too slow right now, so the read was stopped. "
                "Press 'Run AI again' in a moment, or fill in the fields by hand.")
    if "not_found" in kinds:
        return "Gemini model not found. Set GEMINI_MODEL in .env to a model listed in Google AI Studio."
    return "Gemini call failed: " + (failures[-1][1] if failures else "unknown error")[:200]
