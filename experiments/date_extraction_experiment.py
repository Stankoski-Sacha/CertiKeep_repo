#!/usr/bin/env python3
"""Small reproducible baseline experiment for CertiKeep.

This experiment evaluates a transparent date-extraction baseline on 10 synthetic
certificate OCR-text cases. It does NOT evaluate image OCR or an AI model.
Run: python3 experiments/date_extraction_experiment.py
"""
from datetime import date
import re
import json

CASES = [
    {"id": "C01", "text": "FIRST AID CERTIFICATE\nHolder: Alex Martin\nExpiry date: 2027-04-30", "expected": "2027-04-30"},
    {"id": "C02", "text": "Forklift Operator\nName: Jamie Lee\nValid until: 15/02/2027", "expected": "2027-02-15"},
    {"id": "C03", "text": "Working at Height\nParticipant: Morgan Chen\nCertificate expires on 2026.12.01", "expected": "2026-12-01"},
    {"id": "C04", "text": "Fire Safety Training\nEmployee: Sam Dubois\nExpiry: 31-01-2027", "expected": "2027-01-31"},
    {"id": "C05", "text": "First aid level 2\nIssued: 2025-06-10\nRenewal date: 10/06/2028", "expected": "2028-06-10"},
    {"id": "C06", "text": "Forklift licence\nHolder: Taylor Smith\nValid to 2027/09/05", "expected": "2027-09-05"},
    {"id": "C07", "text": "Safety passport\nWorker: Robin Klein\nExpires: 2026-11-09", "expected": "2026-11-09"},
    {"id": "C08", "text": "Electrical safety\nWorker: Casey Martin\nExpiry date 07.03.2027", "expected": "2027-03-07"},
    {"id": "C09", "text": "Manual handling certificate\nHolder: Jordan Ali\nValid until 2027-08-22", "expected": "2027-08-22"},
    {"id": "C10", "text": "Site induction\nEmployee: Riley Bernard\nExpiry date: not shown", "expected": None},
]

DATE_RE = re.compile(
    r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"
    r"|(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)"
)

def normalize_date(match):
    groups = match.groups()
    try:
        if groups[0] is not None:  # year-first
            y, m, d = map(int, groups[:3])
        else:  # day-first, as used in this synthetic European dataset
            d, m, y = map(int, groups[3:])
        return date(y, m, d).isoformat()
    except ValueError:
        return None

def extract_expiry(text):
    # Prefer a date on a line mentioning expiry/expire/valid/renewal.
    lines = text.splitlines()
    for line in lines:
        if re.search(r"expir|valid (?:until|to)|renewal", line, re.I):
            for match in DATE_RE.finditer(line):
                value = normalize_date(match)
                if value:
                    return value
    # Conservative fallback: only accept a single unambiguous date in the text.
    found = [normalize_date(m) for m in DATE_RE.finditer(text)]
    found = [x for x in found if x]
    return found[0] if len(found) == 1 else None

def main():
    rows = []
    correct = 0
    for case in CASES:
        predicted = extract_expiry(case["text"])
        ok = predicted == case["expected"]
        correct += int(ok)
        rows.append({"id": case["id"], "expected": case["expected"],
                     "predicted": predicted, "correct": ok})
    metric = correct / len(CASES)
    print("CertiKeep expiry-date extraction baseline")
    print("Dataset: 10 synthetic OCR-text cases; no real personal documents.")
    print(f"Exact-match accuracy (including missing-date case): {correct}/{len(CASES)} = {metric:.0%}")
    print(json.dumps(rows, indent=2))
    print("\nInterpretation: this tests date parsing from already-extracted text only.")
    print("It does not measure OCR quality, AI performance, real-world generalisation, or compliance.")
    print("The dataset is small and hand-authored; treat this as a baseline, not proof of production accuracy.")

if __name__ == "__main__":
    main()
