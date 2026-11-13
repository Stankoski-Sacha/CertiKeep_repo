"""Unit tests for date parsing, OCR rules and validation.  Run:  python -m unittest discover tests"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from common import canonical_cert_type, find_dates, name_key, normalize_date  # noqa: E402
from ocr_rules import extract_fields  # noqa: E402
from validation import check_record, status  # noqa: E402

TODAY = date(2026, 11, 10)
WORKERS = ["Mattéo Néré", "Jane Doe"]


def record(name="Jane Doe", ctype="first_aid", issue="2025-01-01", expiry="2027-01-01", conf="high", readable=True):
    f = lambda v: {"value": v, "confidence": conf}  # noqa: E731
    return {"readable": readable, "fields": {"worker_name": f(name), "certificate_type": f(ctype),
                                             "issue_date": f(issue), "expiry_date": f(expiry)}}


class DateParsing(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(normalize_date("2027-04-30"), "2027-04-30")
        self.assertEqual(normalize_date("15/02/2027"), "2027-02-15")   # day first
        self.assertEqual(normalize_date("07.03.27"), "2027-03-07")
        self.assertEqual(normalize_date("2 juin 2028"), "2028-06-02")
        self.assertEqual(normalize_date("5. März 2029"), "2029-03-05")
        self.assertEqual(normalize_date("12 September 2026"), "2026-09-12")

    def test_invalid_dates_ignored(self):
        self.assertIsNone(normalize_date("31/02/2027"))
        self.assertEqual(find_dates("no date here"), [])


class OcrRules(unittest.TestCase):
    def test_labelled_french_medical(self):
        text = "FICHE D'APTITUDE\nNom : NÉRÉ Mattéo\nDate de l'examen : 14/03/2025\nProchain examen : 14/03/2027"
        f = extract_fields(text, WORKERS)
        self.assertEqual(f["worker_name"]["value"], "Mattéo Néré")
        self.assertEqual(f["certificate_type"]["value"], "medical_fitness")
        self.assertEqual(f["issue_date"]["value"], "2025-03-14")
        self.assertEqual(f["expiry_date"]["value"], "2027-03-14")
        self.assertEqual(f["expiry_date"]["confidence"], "high")

    def test_label_words_are_not_a_name(self):
        f = extract_fields("Nom et prénom : WEBER Marc\nDate de l'examen : 14/03/2025", [])
        self.assertEqual(f["worker_name"]["value"], "WEBER Marc")
        f = extract_fields("Nom et prénom :\nDate de naissance :\n", [])
        self.assertIsNone(f["worker_name"]["value"])   # labels only -> abstain, never "et prénom"

    def test_no_expiry_printed_means_none(self):
        f = extract_fields("Travail en hauteur\nStagiaire : Jane Doe\nDate de formation : 10/10/2025\nValidité : 3 ans", WORKERS)
        self.assertIsNone(f["expiry_date"]["value"])   # we never compute 10/10/2025 + 3 years

    def test_label_without_date_does_not_borrow_next_line(self):
        text = "Nom : MARTIN Sophie\nDate de l'examen : 02/10/2026\nProchain examen : sur convocation du service.\nFait à X, le 02/10/2026"
        f = extract_fields(text, ["Sophie Martin"])
        self.assertIsNone(f["expiry_date"]["value"])

    def test_label_on_its_own_line(self):
        f = extract_fields("First aid\nJane Doe\nValid until:\n30.04.2027", WORKERS)
        self.assertEqual(f["expiry_date"]["value"], "2027-04-30")

    def test_unlabelled_dates_are_low_confidence(self):
        f = extract_fields("First aid\nJane Doe\n01.04.2024\n01.04.2027", WORKERS)
        self.assertEqual(f["expiry_date"]["value"], "2027-04-01")
        self.assertEqual(f["expiry_date"]["confidence"], "low")


class Validation(unittest.TestCase):
    def test_clean_record_passes(self):
        self.assertEqual(check_record(record(), WORKERS, TODAY), [])

    def test_expiry_before_issue(self):
        self.assertIn("expiry date is not after issue date",
                      check_record(record(issue="2027-01-01", expiry="2025-01-01"), WORKERS, TODAY))

    def test_unknown_worker(self):
        self.assertIn("name does not match a known worker", check_record(record(name="Bob"), WORKERS, TODAY))

    def test_name_order_does_not_matter(self):
        self.assertEqual(name_key("NÉRÉ Mattéo"), name_key("Mattéo Néré"))

    def test_low_confidence_flagged(self):
        self.assertTrue(any("low confidence" in i for i in check_record(record(conf="low"), WORKERS, TODAY)))

    def test_never_green_without_confirmation(self):
        r = record(expiry="2028-01-01")
        self.assertEqual(status(r, [], confirmed_by=None, today=TODAY), "needs_review")
        self.assertEqual(status(r, [], confirmed_by="site manager", today=TODAY), "valid")

    def test_expiring_windows(self):
        self.assertEqual(status(record(expiry="2026-12-01"), [], "x", TODAY), "expiring_30")
        self.assertEqual(status(record(expiry="2026-12-31"), [], "x", TODAY), "expiring_60")
        self.assertEqual(status(record(expiry="2026-11-01"), [], "x", TODAY), "expired")

    def test_unreadable(self):
        self.assertEqual(check_record(record(readable=False), WORKERS, TODAY), ["document unreadable"])

    def test_cert_type_mapping(self):
        self.assertEqual(canonical_cert_type("Certificat d'aptitude médicale"), "medical_fitness")
        self.assertEqual(canonical_cert_type("CACES R489"), "forklift")


if __name__ == "__main__":
    unittest.main()
