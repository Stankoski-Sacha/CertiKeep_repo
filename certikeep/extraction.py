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


def extract(file_bytes: bytes, mime_type: str, known_workers: list[str]) -> Extraction:
    """Call Gemini on one document. Network/model errors are returned in Extraction.error."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    if not api_key:
        raise ExtractionError("GEMINI_API_KEY is not set. Add it to the .env file (see README).")

    from google import genai          # imported here so the rest of the app runs without the SDK
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                         response_schema=RESPONSE_SCHEMA)
    contents = [types.Part.from_bytes(data=file_bytes, mime_type=mime_type), build_prompt(known_workers)]

    start = time.perf_counter()
    last_error = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            ex = parse_response(resp.text)
            ex.model, ex.latency_s = model, round(time.perf_counter() - start, 2)
            return ex
        except Exception as exc:  # noqa: BLE001 - the SDK raises several error types
            last_error = str(exc)
            if any(c in last_error for c in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")) and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            break
    ex = Extraction(model=model, error=_friendly(last_error), latency_s=round(time.perf_counter() - start, 2))
    return ex


def _friendly(msg: str | None) -> str:
    msg = msg or "unknown error"
    if "404" in msg or "NOT_FOUND" in msg:
        return "Gemini model not found. Set GEMINI_MODEL in .env to a model listed in Google AI Studio."
    if "API_KEY" in msg or "401" in msg or "403" in msg:
        return "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "Gemini free-tier limit reached. Wait a minute and press 'Run AI again', or fill in the fields by hand."
    return "Gemini call failed: " + msg[:200]
