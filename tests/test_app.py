"""End-to-end tests of the web app flow.  Run:  python -m unittest discover tests

The real app always calls Gemini. Only these tests replace the extractor with a fixed
answer, so the flow (validation, review, confirmation, status, audit) can be tested
offline and without spending API quota.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from certikeep import create_app  # noqa: E402
from certikeep.domain import status, validate  # noqa: E402
from certikeep.extraction import Extraction, parse_response  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
FUTURE = (date.today() + timedelta(days=400)).isoformat()
SOON = (date.today() + timedelta(days=20)).isoformat()


def fake(fields, readable=True, conf="high"):
    def _extract(_bytes, _mime, _workers):
        ex = Extraction(readable=readable, model="fake-for-tests")
        ex.fields.update(fields)
        ex.confidences = {k: conf for k in ex.fields}
        return ex
    return _extract


class AppFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.pop("GEMINI_API_KEY", None)
        self.app = create_app({"TESTING": True, "DATABASE": os.path.join(self.tmp.name, "t.db"),
                               "UPLOAD_DIR": os.path.join(self.tmp.name, "up")})
        self.c = self.app.test_client()
        self.c.post("/workers/demo")

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, extractor, name="cert.png"):
        self.app.config["EXTRACT"] = extractor
        r = self.c.post("/upload", data={"user": "Mattéo", "file": (io.BytesIO(PNG), name)},
                        content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        return int(r.headers["Location"].rstrip("/").split("/")[-1])

    def worker_id(self, name):
        with self.app.app_context():
            from certikeep.db import get_db
            return get_db().execute("SELECT id FROM workers WHERE name = ?", (name,)).fetchone()["id"]

    def test_dashboard_starts_with_missing(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("Marc Weber", html)
        self.assertIn("Missing", html)

    def test_ai_suggestion_is_not_valid_until_confirmed(self):
        doc = self.upload(fake({"worker_name": "WEBER Marc", "certificate_type": "medical_fitness",
                                "issue_date": "2025-03-14", "expiry_date": FUTURE}))
        page = self.c.get(f"/documents/{doc}").get_data(as_text=True)
        self.assertIn("Needs review", page)
        self.assertIn("Waiting for review", self.c.get("/").get_data(as_text=True))

        r = self.c.post(f"/documents/{doc}/confirm", data={
            "worker_id": self.worker_id("Marc Weber"), "certificate_type": "medical_fitness",
            "issue_date": "2025-03-14", "expiry_date": FUTURE, "user": "Mattéo"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("Valid", self.c.get(f"/documents/{doc}").get_data(as_text=True))
        audit = self.c.get("/audit.csv").get_data(as_text=True)
        self.assertIn("confirmed", audit)
        self.assertIn("Mattéo", audit)

    def test_unreadable_document_needs_values_by_hand(self):
        doc = self.upload(fake({}, readable=False, conf="low"))
        page = self.c.get(f"/documents/{doc}").get_data(as_text=True)
        self.assertIn("unreadable", page)
        r = self.c.post(f"/documents/{doc}/confirm", data={
            "worker_id": self.worker_id("Jane Doe"), "certificate_type": "first_aid",
            "issue_date": "", "expiry_date": "", "user": "Mattéo"})
        self.assertEqual(r.status_code, 422)          # no expiry -> cannot be confirmed
        self.assertIn("No expiry date", r.get_data(as_text=True))

    def test_expiry_before_issue_blocks_confirmation(self):
        doc = self.upload(fake({"worker_name": "Jane Doe", "certificate_type": "first_aid",
                                "issue_date": "2026-01-01", "expiry_date": "2025-01-01"}))
        r = self.c.post(f"/documents/{doc}/confirm", data={
            "worker_id": self.worker_id("Jane Doe"), "certificate_type": "first_aid",
            "issue_date": "2026-01-01", "expiry_date": "2025-01-01", "user": "Mattéo"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("Expiry date must be after the issue date", r.get_data(as_text=True))

    def test_corrections_are_logged(self):
        doc = self.upload(fake({"worker_name": "John Smith", "certificate_type": "crane",
                                "issue_date": "2025-09-05", "expiry_date": "2029-05-09"}))
        self.c.post(f"/documents/{doc}/confirm", data={
            "worker_id": self.worker_id("John Smith"), "certificate_type": "crane",
            "issue_date": "2025-09-05", "expiry_date": SOON, "user": "Luc"})
        audit = self.c.get("/audit.csv").get_data(as_text=True)
        self.assertIn("corrected", audit)
        self.assertIn("2029-05-09", audit)            # the AI's wrong value is kept for the record
        self.assertIn("Expires ≤ 30 days", self.c.get("/").get_data(as_text=True))

    def test_unknown_name_is_not_linked_to_a_worker(self):
        doc = self.upload(fake({"worker_name": "Someone Else", "certificate_type": "first_aid",
                                "issue_date": "2025-01-01", "expiry_date": FUTURE}))
        page = self.c.get(f"/documents/{doc}").get_data(as_text=True)
        self.assertIn("not in the worker list", page)

    def test_missing_api_key_goes_to_review_instead_of_crashing(self):
        from certikeep.extraction import extract
        doc = self.upload(extract)
        page = self.c.get(f"/documents/{doc}").get_data(as_text=True)
        self.assertIn("GEMINI_API_KEY is not set", page)

    def test_rejects_wrong_file_type(self):
        r = self.c.post("/upload", data={"user": "M", "file": (io.BytesIO(b"x"), "virus.exe")},
                        content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("Only JPG, PNG, WEBP or PDF", r.get_data(as_text=True))


class Domain(unittest.TestCase):
    def test_parse_model_json(self):
        raw = json.dumps({"readable": True,
                          "worker_name": {"value": "Jane Doe", "confidence": "high"},
                          "certificate_type": {"value": "Certificat d'aptitude médicale", "confidence": "high"},
                          "issue_date": {"value": "14/03/2025", "confidence": "medium"},
                          "expiry_date": {"value": "not visible", "confidence": "low"}})
        ex = parse_response(raw)
        self.assertEqual(ex.fields["certificate_type"], "medical_fitness")
        self.assertEqual(ex.fields["issue_date"], "2025-03-14")
        self.assertIsNone(ex.fields["expiry_date"])   # garbage date -> None, never a guess

    def test_garbage_response_is_unreadable(self):
        ex = parse_response("sorry, I cannot help")
        self.assertFalse(ex.readable)
        self.assertTrue(ex.error)

    def test_status_requires_confirmation(self):
        self.assertEqual(status(False, FUTURE), "needs_review")
        self.assertEqual(status(True, FUTURE), "valid")
        self.assertEqual(status(True, "2020-01-01"), "expired")

    def test_low_confidence_is_a_warning(self):
        issues = validate({"worker_name": "Jane Doe", "certificate_type": "first_aid", "issue_date": "2025-01-01",
                           "expiry_date": FUTURE}, ["Jane Doe"], confidences={"expiry_date": "low"})
        self.assertEqual([i["level"] for i in issues], ["warning"])


if __name__ == "__main__":
    unittest.main()
