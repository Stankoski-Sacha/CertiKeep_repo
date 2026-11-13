#!/usr/bin/env python3
"""Approach A: hosted vision model (Google Gemini, free tier).

Setup:
    1. Create a free API key at https://aistudio.google.com/apikey
    2. export GEMINI_API_KEY=...        (Windows PowerShell: $env:GEMINI_API_KEY="...")
    3. python experiments/run_gemini.py

Free-tier requests may be used by Google to improve its products, so only send
your own certificates or redacted ones, with the holder's consent.

The free tier allows only a few requests per minute, so the script waits between
files (--pause) and retries on HTTP 429.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from google import genai
from google.genai import types

from common import (CERT_TYPES, FIELDS, SCANS_DIR, canonical_cert_type, empty_fields, image_for,
                    list_scans, load_workers, mime_type, normalize_date, save_record, tmpdir)

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

PROMPT = """You are reading ONE worker certificate (training certificate, licence, or
medical fitness-for-work certificate) from a construction company.

Extract exactly these fields:
- worker_name: the full name of the person the certificate is about (not the doctor, trainer or company).
- certificate_type: one of {types}. Use "other" if none fits.
- issue_date: date of issue / exam / training, as YYYY-MM-DD.
- expiry_date: date the certificate stops being valid (expiry, "valid until", next exam due), as YYYY-MM-DD.
Dates on these documents are European (day first): 03/04/2027 is 3 April 2027.

Rules:
- Only report what is printed on the document. NEVER guess or compute a value.
  If a field is not visible or you are unsure, return null for it.
- Do not calculate an expiry date from the issue date and a validity period.
- For each field give confidence "high", "medium" or "low".
- Set readable=false if the image is too blurry, cut off, or not a certificate.
{workers}"""

FIELD_SCHEMA = {
    "type": "OBJECT",
    "properties": {"value": {"type": "STRING", "nullable": True},
                   "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]}},
    "required": ["value", "confidence"],
}
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "readable": {"type": "BOOLEAN"},
        **{f: FIELD_SCHEMA for f in FIELDS},
        "notes": {"type": "STRING", "nullable": True},
    },
    "required": ["readable", *FIELDS],
}


def build_prompt(workers: list[str]) -> str:
    worker_hint = ""
    if workers:
        worker_hint = ("\nKnown workers of this company (use the exact spelling if the name on the "
                       "document is clearly one of them, otherwise copy the name as printed):\n- "
                       + "\n- ".join(workers))
    return PROMPT.format(types=", ".join(CERT_TYPES), workers=worker_hint)


def call_gemini(client, model: str, image: Path, prompt: str, retries: int = 4) -> str:
    part = types.Part.from_bytes(data=image.read_bytes(), mime_type=mime_type(image))
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
    )
    for attempt in range(retries + 1):
        try:
            return client.models.generate_content(model=model, contents=[part, prompt], config=config).text
        except Exception as exc:  # noqa: BLE001 - SDK raises several error types
            msg = str(exc)
            if attempt < retries and ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg):
                wait = 20 * (attempt + 1)
                print(f"    rate-limited, waiting {wait}s ...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def to_record(file_name: str, raw: str, latency: float, model: str) -> dict:
    fields = empty_fields()
    readable = False
    try:
        data = json.loads(raw)
        readable = bool(data.get("readable", False))
        for f in FIELDS:
            item = data.get(f) or {}
            value = item.get("value")
            if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a"}:
                value = None
            if f.endswith("_date"):
                value = normalize_date(value)
            elif f == "certificate_type":
                value = canonical_cert_type(value)
            fields[f] = {"value": value, "confidence": item.get("confidence", "low")}
    except (json.JSONDecodeError, AttributeError):
        pass  # unparseable answer -> everything stays None / unreadable -> needs review
    return {"file": file_name, "method": "gemini", "model": model, "readable": readable,
            "fields": fields, "latency_s": round(latency, 2), "raw": raw}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scans", default=str(SCANS_DIR))
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Gemini model (default {DEFAULT_MODEL}; check AI Studio for current free-tier models)")
    ap.add_argument("--pause", type=float, default=7.0, help="seconds between requests (free tier is rate-limited)")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("Set GEMINI_API_KEY first (free key: https://aistudio.google.com/apikey)")

    client = genai.Client()  # reads GEMINI_API_KEY
    prompt = build_prompt(load_workers())
    files = list_scans(Path(args.scans))
    if not files:
        raise SystemExit(f"No scans found in {args.scans}")

    with tmpdir() as tmp:
        for i, f in enumerate(files):
            # Gemini accepts PDFs directly, but we send page 1 as an image so both
            # approaches see exactly the same input.
            image = image_for(f, Path(tmp))
            start = time.perf_counter()
            try:
                raw = call_gemini(client, args.model, image, prompt)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                # Setup problems (wrong model name, bad key) would fail for every file:
                # stop instead of saving empty results that look like real answers.
                if any(code in msg for code in ("404", "NOT_FOUND", "400", "401", "403", "API_KEY")):
                    raise SystemExit(f"[gemini] stopped: {msg}\nFix the setup (model name with --model, or GEMINI_API_KEY) and run again.")
                print(f"[gemini] {f.name}: ERROR {exc}")
                raw = json.dumps({"error": msg})
            record = to_record(f.name, raw, time.perf_counter() - start, args.model)
            save_record(record, "gemini")
            summary = ", ".join(f"{k}={v['value']}" for k, v in record["fields"].items())
            print(f"[gemini] {f.name}: readable={record['readable']} | {summary}")
            if i < len(files) - 1:
                time.sleep(args.pause)


if __name__ == "__main__":
    main()
