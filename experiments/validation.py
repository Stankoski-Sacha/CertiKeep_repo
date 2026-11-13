"""Validation rules applied in code AFTER extraction (never trust the model alone).

These are the rules the M3 feedback asks for. The experiment uses them to measure
how many extraction mistakes would be caught before a person confirms a record.

A certificate only turns 'valid' (green) when:
  * the document was readable,
  * no validation issue was found, and
  * a person confirmed it (confirmed_by / confirmed_at = the audit trail).
"""
from __future__ import annotations

from datetime import date, timedelta

from common import CERT_TYPES, name_key

MAX_VALIDITY_YEARS = 10          # no construction certificate we know of lasts longer
OLDEST_PLAUSIBLE_ISSUE = date(1980, 1, 1)


def _d(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def check_record(record: dict, known_workers: list[str], today: date | None = None) -> list[str]:
    """Return a list of human-readable problems. Empty list = passes all checks."""
    today = today or date.today()
    issues: list[str] = []
    if not record.get("readable", False):
        return ["document unreadable"]

    f = record["fields"]
    name, ctype = f["worker_name"]["value"], f["certificate_type"]["value"]
    issue, expiry = _d(f["issue_date"]["value"]), _d(f["expiry_date"]["value"])

    if expiry is None:
        issues.append("no expiry date found")
    if issue and expiry and expiry <= issue:
        issues.append("expiry date is not after issue date")
    if issue and issue > today:
        issues.append("issue date is in the future")
    if issue and issue < OLDEST_PLAUSIBLE_ISSUE:
        issues.append("issue date implausibly old")
    if issue and expiry and expiry > issue + timedelta(days=365 * MAX_VALIDITY_YEARS + 3):
        issues.append(f"validity longer than {MAX_VALIDITY_YEARS} years")
    if expiry and expiry > today + timedelta(days=365 * MAX_VALIDITY_YEARS + 3):
        issues.append("expiry date implausibly far in the future")

    if not name:
        issues.append("no worker name found")
    elif known_workers and name_key(name) not in {name_key(w) for w in known_workers}:
        issues.append("name does not match a known worker")

    if ctype in (None, "other") or ctype not in CERT_TYPES:
        issues.append("certificate type not recognised")

    low = [k for k, v in f.items() if v["value"] is not None and v.get("confidence") == "low"]
    if low:
        issues.append("low confidence: " + ", ".join(low))
    return issues


def status(record: dict, issues: list[str], confirmed_by: str | None = None,
           today: date | None = None) -> str:
    """Status shown to the site manager.

    needs_review  - unreadable, failed a check, or not yet confirmed by a person
    expired       - confirmed, expiry date passed
    expiring_30   - confirmed, expires within 30 days
    expiring_60   - confirmed, expires within 60 days
    valid         - confirmed and more than 60 days left
    ('missing' is decided at the worker x required-certificate level, not per document.)
    """
    today = today or date.today()
    if issues or not confirmed_by:
        return "needs_review"
    expiry = _d(record["fields"]["expiry_date"]["value"])
    days_left = (expiry - today).days
    if days_left < 0:
        return "expired"
    if days_left <= 30:
        return "expiring_30"
    if days_left <= 60:
        return "expiring_60"
    return "valid"
