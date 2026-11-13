"""Domain rules: certificate types, date/name normalisation, validation and status.

Kept free of Flask and Gemini so it can be unit-tested on its own.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

CERT_TYPES: dict[str, str] = {
    "medical_fitness": "Medical fitness for work",
    "first_aid": "First aid",
    "working_at_height": "Working at height",
    "forklift": "Forklift",
    "electrical": "Electrical clearance",
    "scaffolding": "Scaffolding",
    "crane": "Crane operation",
    "asbestos": "Asbestos",
    "safety_training": "Safety training (VCA/SCC)",
    "other": "Other",
}

# Keywords (lower-case, no accents) to map free text from the model onto a type.
_TYPE_KEYWORDS = {
    "medical_fitness": ["medical", "fitness", "aptitude", "apte", "sante au travail", "arbeitsmedizin",
                        "tauglichkeit", "fit for work"],
    "first_aid": ["first aid", "premiers secours", "secourisme", "erste hilfe"],
    "working_at_height": ["height", "hauteur", "hohe"],
    "forklift": ["forklift", "chariot", "caces", "gabelstapler"],
    "electrical": ["electri", "elektro"],
    "scaffolding": ["scaffold", "echafaudage", "gerust"],
    "crane": ["crane", "grue", "kran"],
    "asbestos": ["asbestos", "amiante", "asbest"],
    "safety_training": ["vca", "scc", "safety"],
}

STATUS_LABELS = {
    "valid": "Valid",
    "expiring_60": "Expires ≤ 60 days",
    "expiring_30": "Expires ≤ 30 days",
    "expired": "Expired",
    "missing": "Missing",
    "needs_review": "Needs review",
}

MAX_VALIDITY_YEARS = 10
OLDEST_PLAUSIBLE_ISSUE = date(1980, 1, 1)


# --------------------------------------------------------------------------- normalisation
def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def name_key(name: str | None) -> str:
    """Order- and accent-insensitive key: 'NÉRÉ Mattéo' == 'Mattéo Néré'."""
    tokens = re.findall(r"[a-z]+", strip_accents(name or "").lower())
    return " ".join(sorted(tokens))


def canonical_cert_type(text: str | None) -> str | None:
    if not text:
        return None
    t = strip_accents(text).lower().strip()
    if t in CERT_TYPES:
        return t
    for key, words in _TYPE_KEYWORDS.items():
        if any(w in t for w in words):
            return key
    return "other"


_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")
_DMY = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*$")


def parse_date(value: str | None) -> date | None:
    """Accept ISO (2027-03-14) or European day-first (14/03/2027). Anything else -> None."""
    if not value:
        return None
    m = _ISO.match(value) or _DMY.match(value)
    if not m:
        return None
    a, b, c = (int(x) for x in m.groups())
    y, mth, d = (a, b, c) if m.re is _ISO else (c, b, a)
    try:
        return date(y, mth, d)
    except ValueError:
        return None


# --------------------------------------------------------------------------- validation
def validate(fields: dict, known_workers: list[str], today: date | None = None,
             confidences: dict | None = None, readable: bool = True) -> list[dict]:
    """Return a list of {"level": "error"|"warning", "msg": ...}.

    errors   block confirmation (the person must correct the value first)
    warnings must be looked at, but a person may confirm anyway
    """
    today = today or date.today()
    out: list[dict] = []
    err = lambda m: out.append({"level": "error", "msg": m})      # noqa: E731
    warn = lambda m: out.append({"level": "warning", "msg": m})   # noqa: E731

    if not readable:
        warn("The AI could not read this document. Enter the values by hand from the scan.")

    issue, expiry = parse_date(fields.get("issue_date")), parse_date(fields.get("expiry_date"))
    if fields.get("issue_date") and issue is None:
        err("Issue date is not a valid date.")
    if fields.get("expiry_date") and expiry is None:
        err("Expiry date is not a valid date.")
    if expiry is None and not fields.get("expiry_date"):
        err("No expiry date. Enter it from the document; if none is printed, the certificate cannot be marked valid.")
    if issue and expiry and expiry <= issue:
        err("Expiry date must be after the issue date.")
    if issue and issue > today:
        err("Issue date is in the future.")
    if issue and issue < OLDEST_PLAUSIBLE_ISSUE:
        err("Issue date is implausibly old.")
    if issue and expiry and expiry > issue + timedelta(days=365 * MAX_VALIDITY_YEARS + 3):
        warn(f"Validity is longer than {MAX_VALIDITY_YEARS} years. Check the dates.")
    if expiry and expiry > today + timedelta(days=365 * MAX_VALIDITY_YEARS + 3):
        err("Expiry date is implausibly far in the future.")

    name = fields.get("worker_name")
    if not name:
        err("No worker selected.")
    elif known_workers and name_key(name) not in {name_key(w) for w in known_workers}:
        err(f"'{name}' is not in the worker list. Pick the right worker or add them first.")

    ctype = fields.get("certificate_type")
    if not ctype:
        err("No certificate type.")
    elif ctype == "other":
        warn("Certificate type 'Other' does not count towards any requirement.")

    low = [k.replace("_", " ") for k, c in (confidences or {}).items() if c == "low" and fields.get(k)]
    if low:
        warn("The AI was not sure about: " + ", ".join(low) + ". Compare with the scan.")
    return out


def has_errors(issues: list[dict]) -> bool:
    return any(i["level"] == "error" for i in issues)


def status(confirmed: bool, expiry_date: str | None, today: date | None = None) -> str:
    """A certificate is only green after a person confirmed it."""
    today = today or date.today()
    expiry = parse_date(expiry_date)
    if not confirmed or expiry is None:
        return "needs_review"
    days = (expiry - today).days
    if days < 0:
        return "expired"
    if days <= 30:
        return "expiring_30"
    if days <= 60:
        return "expiring_60"
    return "valid"
