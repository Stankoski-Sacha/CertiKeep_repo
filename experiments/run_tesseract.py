#!/usr/bin/env python3
"""Approach B: local OCR (Tesseract) + transparent rules.

Usage:
    python experiments/run_tesseract.py                 # all files in experiments/scans/
    python experiments/run_tesseract.py --lang fra+deu+eng
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

from common import SCANS_DIR, empty_fields, image_for, list_scans, load_workers, save_record, tmpdir
from ocr_rules import extract_fields

MIN_WORDS = 5          # fewer words than this -> treat as unreadable
MIN_MEAN_CONF = 55     # Tesseract word confidence (0-100) below this -> unreadable


def ocr(path, lang: str, psm: int) -> tuple[str, float, int]:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img).convert("L")          # respect phone rotation, greyscale
    if max(img.size) < 2000:                                    # small photos OCR better upscaled
        scale = 2000 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    # --psm 6 = read the page as one block of text lines. Certificates are forms
    # ("Label : value"); the default mode can split labels and values into separate
    # columns, so the value no longer appears next to its label.
    config = f"--psm {psm}"
    data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=pytesseract.Output.DICT)
    words = [(w, float(c)) for w, c in zip(data["text"], data["conf"]) if w.strip() and float(c) >= 0]
    mean_conf = sum(c for _, c in words) / len(words) if words else 0.0
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    return text, mean_conf, len(words)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scans", default=str(SCANS_DIR))
    ap.add_argument("--lang", default="fra+deu+eng", help="Tesseract languages (default: fra+deu+eng)")
    ap.add_argument("--psm", type=int, default=6, help="Tesseract page segmentation mode (default 6: one block of lines)")
    args = ap.parse_args()

    workers = load_workers()
    files = list_scans(Path(args.scans))
    if not files:
        raise SystemExit(f"No scans found in {args.scans}")

    with tmpdir() as tmp:
        for f in files:
            start = time.perf_counter()
            text, mean_conf, n_words = ocr(image_for(f, Path(tmp)), args.lang, args.psm)
            readable = n_words >= MIN_WORDS and mean_conf >= MIN_MEAN_CONF
            fields = extract_fields(text, workers) if readable else empty_fields()
            record = {
                "file": f.name,
                "method": "tesseract",
                "readable": readable,
                "fields": fields,
                "ocr_mean_confidence": round(mean_conf, 1),
                "ocr_word_count": n_words,
                "latency_s": round(time.perf_counter() - start, 2),
                "raw": text,
            }
            save_record(record, "tesseract")
            summary = ", ".join(f"{k}={v['value']}" for k, v in fields.items())
            print(f"[tesseract] {f.name}: readable={readable} conf={mean_conf:.0f} | {summary}")


if __name__ == "__main__":
    main()
