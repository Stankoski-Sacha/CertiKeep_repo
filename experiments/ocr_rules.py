"""Rule-based field extraction from OCR text (the 'Tesseract + rules' approach).

The rules are deliberately transparent. Every field gets a confidence:
  high   - found next to a matching label (e.g. 'Expiry date: ...') or matched a known worker exactly
  medium - fuzzy worker-name match, or type found by keyword anywhere
  low    - a guess from position/order; must be reviewed by a person
A field we cannot find is returned as None (we abstain instead of guessing).
"""
from __future__ import annotations

import difflib
import re

from common import CERT_TYPES, empty_fields, find_dates, name_key, norm, strip_accents

EXPIRY_LABELS = [
    "expir", "valid until", "valid to", "valid thru", "valid through", "renewal", "renew by",
    "valable jusqu", "valide jusqu", "validite", "jusqu'au", "date d'echeance", "echeance", "date limite", "a renouveler",
    "prochain examen", "prochaine visite", "next exam", "next visit",
    "gultig bis", "gueltig bis", "ablauf", "befristet bis", "nachste untersuchung",
]
ISSUE_LABELS = [
    "issued", "date of issue", "issue date", "date of exam", "examination date", "completed on",
    "delivre", "date de delivrance", "date de l'examen", "date de la visite", "fait a", "fait le",
    "date de formation", "ausgestellt", "ausstellungsdatum", "datum der untersuchung", "date:",
]
NAME_LABELS = [
    "name", "holder", "participant", "employee", "worker", "candidate", "trainee",
    "nom", "prenom", "titulaire", "salarie", "stagiaire", "monsieur", "madame", "m.", "mme",
    "teilnehmer", "mitarbeiter", "herr", "frau",
]


def _label_dates(lines: list[str], labels: list[str]) -> list[str]:
    """Dates on a line that contains one of the labels (or on the next line)."""
    hits = []
    for i, line in enumerate(lines):
        found = [lbl for lbl in labels if lbl in line]
        if not found:
            continue
        dates = find_dates(line)
        # Only look at the next line when the label line ends right after the label
        # ("Valid until:" / newline / "30.04.2027"). Otherwise "Next exam: on request"
        # would wrongly pick up a date printed on the following line.
        tail = line[line.index(found[0]) + len(found[0]):]
        if not dates and re.fullmatch(r"[\s:.\-]*", tail) and i + 1 < len(lines):
            dates = find_dates(lines[i + 1])
        hits.extend(d for _, d in dates)
    return hits


def extract_dates(text: str) -> tuple[dict, dict]:
    lines = [norm(l) for l in text.splitlines() if l.strip()]
    expiry = _label_dates(lines, EXPIRY_LABELS)
    issue = [d for d in _label_dates(lines, ISSUE_LABELS) if d not in expiry]

    exp_field = {"value": expiry[0], "confidence": "high"} if expiry else {"value": None, "confidence": "low"}
    iss_field = {"value": issue[0], "confidence": "high"} if issue else {"value": None, "confidence": "low"}

    # Fallback: no labels. With exactly two distinct dates, assume earlier=issue, later=expiry,
    # but mark LOW so a person must check. With one or 3+ dates we abstain.
    if exp_field["value"] is None and iss_field["value"] is None:
        all_dates = sorted({d for _, d in find_dates(text)})
        if len(all_dates) == 2:
            iss_field = {"value": all_dates[0], "confidence": "low"}
            exp_field = {"value": all_dates[1], "confidence": "low"}
    return iss_field, exp_field


def extract_cert_type(text: str) -> dict:
    t = norm(text)
    scores = {k: sum(t.count(w) for w in words) for k, words in CERT_TYPES.items() if words}
    best = max(scores, key=scores.get) if scores else None
    if not best or scores[best] == 0:
        return {"value": None, "confidence": "low"}
    # Title-ish match in the first lines is more trustworthy than a mention in small print.
    head = norm(" ".join(text.splitlines()[:6]))
    conf = "high" if any(w in head for w in CERT_TYPES[best]) else "medium"
    return {"value": best, "confidence": conf}


def extract_name(text: str, known_workers: list[str]) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    plain = name_key(text)

    # 1. Known worker whose name tokens all appear in the text -> high.
    for worker in known_workers:
        tokens = name_key(worker).split()
        if tokens and all(re.search(rf"\b{re.escape(t)}\b", plain) for t in tokens):
            return {"value": worker, "confidence": "high"}

    # 2. Candidate from a labelled line ('Name: ...', 'Nom : ...').
    candidate = None
    for i, line in enumerate(lines):
        low = strip_accents(line).lower()  # same length as `line`, so indexes line up
        for lbl in NAME_LABELS:
            m = re.match(rf"^{re.escape(lbl)}(?:\b|\s)\s*[:\-]?\s*(.*)$", low)
            if m:
                rest = line[m.start(1):].strip(" :-")
                if not rest and i + 1 < len(lines):
                    rest = lines[i + 1]
                # "Nom et prénom : X" -> drop leftover label words ("et prénom") before the value
                rest = re.sub(r"^(?:(?:et|and|und|/|,)?\s*(?:prenoms?|prénoms?|vorname|first name|surname|nom)\s*)+[:\-]?\s*",
                              "", rest or "", flags=re.I).strip()
                if not rest and i + 1 < len(lines):
                    rest = lines[i + 1]
                if re.search(r"[A-Za-zÀ-ÿ]{2,}", rest or "") and not re.search(r":\s*$", rest):
                    candidate = re.sub(r"[^A-Za-zÀ-ÿ' \-]", "", rest).strip()
                    break
        if candidate:
            break

    # 3. Fuzzy-match the candidate (or every line) against known workers -> medium.
    pool = [candidate] if candidate else lines
    best, best_score = None, 0.0
    for worker in known_workers:
        for chunk in pool:
            score = difflib.SequenceMatcher(None, name_key(worker), name_key(chunk)).ratio()
            if score > best_score:
                best, best_score = worker, score
    if best and best_score >= 0.80:
        return {"value": best, "confidence": "medium"}
    if candidate:
        return {"value": candidate, "confidence": "low"}
    return {"value": None, "confidence": "low"}


def extract_fields(text: str, known_workers: list[str]) -> dict:
    fields = empty_fields()
    fields["worker_name"] = extract_name(text, known_workers)
    fields["certificate_type"] = extract_cert_type(text)
    fields["issue_date"], fields["expiry_date"] = extract_dates(text)
    return fields
