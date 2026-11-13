"""Shared helpers for the CertiKeep extraction experiment.

Both pipelines (Gemini and Tesseract) produce the same record shape, so the
evaluation can compare them field by field:

    {
      "file": "cert_01.jpg",
      "method": "gemini" | "tesseract",
      "readable": true/false,
      "fields": {
        "worker_name":      {"value": "Jane Doe" | None, "confidence": "high"|"medium"|"low"},
        "certificate_type": {...},
        "issue_date":       {"value": "2025-03-14" | None, ...},
        "expiry_date":      {...}
      },
      "latency_s": 1.23,
      "raw": "...model output or OCR text..."
    }
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent
SCANS_DIR = EXPERIMENT_DIR / "scans"
RESULTS_DIR = EXPERIMENT_DIR / "results"
GROUND_TRUTH = EXPERIMENT_DIR / "ground_truth.csv"
WORKERS = EXPERIMENT_DIR / "workers.csv"

FIELDS = ["worker_name", "certificate_type", "issue_date", "expiry_date"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".pdf"}

# Canonical certificate types. Keys are what we store; values are keywords
# (EN / FR / DE, lower-case, accents removed) used by the OCR rules and to map
# free-text answers onto a category.
CERT_TYPES: dict[str, list[str]] = {
    "medical_fitness": ["medical fitness", "fit for work", "aptitude", "apte", "medecine du travail",
                        "sante au travail", "examen medical", "visite medicale", "arbeitsmedizin",
                        "tauglichkeit", "medical certificate", "certificat medical", "stm"],
    "first_aid": ["first aid", "premiers secours", "secourisme", "erste hilfe", "sauveteur"],
    "working_at_height": ["working at height", "work at height", "travail en hauteur",
                          "hohenarbeit", "arbeiten in der hohe", "harnais", "fall protection"],
    "forklift": ["forklift", "chariot elevateur", "caces", "gabelstapler", "fork lift"],
    "electrical": ["electrical", "habilitation electrique", "elektro", "electricite"],
    "scaffolding": ["scaffold", "echafaudage", "gerust"],
    "crane": ["crane", "grue", "kran"],
    "asbestos": ["asbestos", "amiante", "asbest"],
    "safety_training": ["vca", "scc", "safety passport", "safety training", "formation securite",
                        "sicherheitsschulung", "site induction"],
    "other": [],
}

MONTHS = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # French (accents removed)
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    # German (umlauts removed)
    "januar": 1, "februar": 2, "marz": 3, "maerz": 3, "juni": 6, "juli": 7,
    "oktober": 10, "dezember": 12,
}


# --------------------------------------------------------------------------- text
def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(text: str | None) -> str:
    """Lower-case, accent-free, single-spaced."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


def name_key(name: str | None) -> str:
    """Order-insensitive key so 'DOE Jane' == 'Jane Doe'."""
    tokens = re.findall(r"[a-z]+", norm(name))
    return " ".join(sorted(tokens))


def canonical_cert_type(text: str | None) -> str | None:
    """Map free text ('Certificat d'aptitude médicale') to a CERT_TYPES key."""
    if not text:
        return None
    t = norm(text)
    if t in CERT_TYPES:
        return t
    for key, words in CERT_TYPES.items():
        if any(w in t for w in words):
            return key
    return "other"


# --------------------------------------------------------------------------- dates
_NUMERIC_DATE = re.compile(
    r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"      # 2027-04-30
    r"|(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)"     # 30.04.2027 (day first)
    r"|(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2})(?!\d)"     # 30.04.27
)
_TEXT_DATE = re.compile(r"(?<!\d)(\d{1,2})(?:er|st|nd|rd|th)?\.?\s+([a-z]{3,9})\.?\s+(\d{4})(?!\d)")


def _safe_date(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[int, str]]:
    """Return (position, ISO date) for every date in the text. Day-first (European)."""
    out: list[tuple[int, str]] = []
    plain = norm(text)
    for m in _NUMERIC_DATE.finditer(plain):
        g = m.groups()
        if g[0]:
            iso = _safe_date(int(g[0]), int(g[1]), int(g[2]))
        elif g[3]:
            iso = _safe_date(int(g[5]), int(g[4]), int(g[3]))
        else:
            iso = _safe_date(2000 + int(g[8]), int(g[7]), int(g[6]))
        if iso:
            out.append((m.start(), iso))
    for m in _TEXT_DATE.finditer(plain):
        month = MONTHS.get(m.group(2))
        if month:
            iso = _safe_date(int(m.group(3)), month, int(m.group(1)))
            if iso:
                out.append((m.start(), iso))
    return sorted(out)


def normalize_date(value: str | None) -> str | None:
    """Turn any single date string into ISO format, or None."""
    if not value:
        return None
    found = find_dates(str(value))
    return found[0][1] if found else None


# --------------------------------------------------------------------------- files
def list_scans(folder: Path = SCANS_DIR) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def image_for(path: Path, workdir: Path) -> Path:
    """Return an image path. PDFs are rendered (first page, 300 dpi) with pdftoppm."""
    if path.suffix.lower() != ".pdf":
        return path
    if not shutil.which("pdftoppm"):
        raise RuntimeError("pdftoppm (poppler-utils) is needed to read PDFs")
    out_prefix = workdir / path.stem
    subprocess.run(["pdftoppm", "-r", "300", "-png", "-f", "1", "-l", "1", "-singlefile",
                    str(path), str(out_prefix)], check=True)
    return out_prefix.with_suffix(".png")


def mime_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
        ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp", ".pdf": "application/pdf",
    }[path.suffix.lower()]


def load_workers(path: Path = WORKERS) -> list[str]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [row["worker_name"].strip() for row in csv.DictReader(f) if row.get("worker_name", "").strip()]


def load_ground_truth(path: Path = GROUND_TRUTH) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = {}
        for row in csv.DictReader(f):
            if not row.get("file", "").strip() or row["file"].startswith("#"):
                continue
            rows[row["file"].strip()] = {k: (v or "").strip() for k, v in row.items()}
        return rows


def save_record(record: dict, method: str) -> Path:
    out_dir = RESULTS_DIR / method
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{record['file']}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_records(method: str) -> dict[str, dict]:
    folder = RESULTS_DIR / method
    if not folder.exists():
        return {}
    return {json.loads(p.read_text(encoding="utf-8"))["file"]: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(folder.glob("*.json"))}


def empty_fields(conf: str = "low") -> dict:
    return {f: {"value": None, "confidence": conf} for f in FIELDS}


def tmpdir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="certikeep_")
