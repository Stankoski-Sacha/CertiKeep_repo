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
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from certikeep import create_app  # noqa: E402
from certikeep.domain import status, validate  # noqa: E402
from certikeep import extraction  # noqa: E402
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
        # AI_BACKGROUND off: the read runs inside the request, so each test sees the result at once.
        self.app = create_app({"TESTING": True, "DATABASE": os.path.join(self.tmp.name, "t.db"),
                               "UPLOAD_DIR": os.path.join(self.tmp.name, "up"), "AI_BACKGROUND": False})
        self.c = self.app.test_client()
        self.c.post("/workers/demo")

    def tearDown(self):
        self.tmp.cleanup()

    def wait_until_read(self, doc, seconds=5):
        deadline = time.time() + seconds
        while self.c.get(f"/documents/{doc}/status").get_json()["pending"]:
            self.assertLess(time.time(), deadline, "the AI read never finished")
            time.sleep(0.02)

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
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):   # ignore a real key from .env
            doc = self.upload(extract)
        page = self.c.get(f"/documents/{doc}").get_data(as_text=True)
        self.assertIn("GEMINI_API_KEY is not set", page)

    def test_rejects_wrong_file_type(self):
        r = self.c.post("/upload", data={"user": "M", "file": (io.BytesIO(b"x"), "virus.exe")},
                        content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("Only JPG, PNG, WEBP or PDF", r.get_data(as_text=True))


    # ---- the AI read runs in the background: the upload must never wait for Gemini
    def test_upload_answers_before_the_ai_has_finished(self):
        self.app.config["AI_BACKGROUND"] = True
        release = threading.Event()

        def slow(_bytes, _mime, _workers):
            release.wait(5)
            return fake({"worker_name": "Jane Doe", "certificate_type": "first_aid",
                         "issue_date": "2025-01-01", "expiry_date": FUTURE})(_bytes, _mime, _workers)

        doc = self.upload(slow)                       # returns although the "AI" is still busy
        self.assertTrue(self.c.get(f"/documents/{doc}/status").get_json()["pending"])
        page = self.c.get(f"/documents/{doc}").get_data(as_text=True)
        self.assertIn("Reading the document", page)
        self.assertNotIn("No expiry date", page)      # empty fields are not errors while it is reading
        self.assertIn("AI reading", self.c.get("/").get_data(as_text=True))
        release.set()
        self.wait_until_read(doc)
        page = self.c.get(f"/documents/{doc}").get_data(as_text=True)
        self.assertNotIn("Reading the document", page)
        self.assertIn("Suggested by fake-for-tests", page)

    def test_confirming_while_the_ai_reads_is_not_overwritten(self):
        self.app.config["AI_BACKGROUND"] = True
        release = threading.Event()

        def slow(_bytes, _mime, _workers):
            release.wait(5)
            return fake({"worker_name": "John Smith", "certificate_type": "crane",
                         "issue_date": "2020-01-01", "expiry_date": "2021-01-01"})(_bytes, _mime, _workers)

        doc = self.upload(slow)
        r = self.c.post(f"/documents/{doc}/confirm", data={
            "worker_id": self.worker_id("Jane Doe"), "certificate_type": "first_aid",
            "issue_date": "2025-01-01", "expiry_date": FUTURE, "user": "Luc"})
        self.assertEqual(r.status_code, 302)
        release.set()
        self.wait_until_read(doc)
        with self.app.app_context():
            from certikeep.db import get_db
            row = get_db().execute("SELECT * FROM documents WHERE id = ?", (doc,)).fetchone()
        self.assertEqual((row["worker_name"], row["expiry_date"]), ("Jane Doe", FUTURE))   # the person's values
        self.assertEqual(row["ai_model"], "fake-for-tests")                                 # AI answer still recorded

    def test_crashing_ai_step_releases_the_page(self):
        self.app.config["AI_BACKGROUND"] = True

        def broken(_bytes, _mime, _workers):
            raise ModuleNotFoundError("No module named 'google'")

        doc = self.upload(broken)
        self.wait_until_read(doc)
        self.assertIn("stopped unexpectedly", self.c.get(f"/documents/{doc}").get_data(as_text=True))

    def test_read_that_never_ends_is_declared_failed(self):
        self.app.config.update(AI_BACKGROUND=True, AI_STALE_S=0)
        release = threading.Event()
        doc = self.upload(lambda *_: release.wait(5) and Extraction())
        time.sleep(1.1)                               # started_at has one-second resolution
        self.assertFalse(self.c.get(f"/documents/{doc}/status").get_json()["pending"])
        self.assertIn("did not finish", self.c.get(f"/documents/{doc}").get_data(as_text=True))
        release.set()
        time.sleep(0.2)                               # let the thread end before the temp folder goes

    def test_restart_releases_documents_left_pending(self):
        doc = self.upload(fake({}))
        with self.app.app_context():
            from certikeep.db import get_db
            get_db().execute("UPDATE documents SET ai_status = 'pending' WHERE id = ?", (doc,))
            get_db().commit()
        again = create_app({"TESTING": True, "DATABASE": self.app.config["DATABASE"],
                            "UPLOAD_DIR": self.app.config["UPLOAD_DIR"]})
        page = again.test_client().get(f"/documents/{doc}").get_data(as_text=True)
        self.assertNotIn("Reading the document", page)
        self.assertIn("interrupted", page)


class GeminiCalls(unittest.TestCase):
    """extract() with the network call replaced: timeouts, overload and fallback, without real requests."""
    GOOD = json.dumps({"readable": True, **{f: {"value": None, "confidence": "low"} for f in extraction.FIELDS}})

    def setUp(self):
        self.env = dict(os.environ)
        os.environ.update(GEMINI_MODEL="main-model", GEMINI_FALLBACK_MODEL="backup-model")
        self._sleep, extraction.time.sleep = extraction.time.sleep, lambda _s: None
        extraction._busy_until.clear()

    def tearDown(self):
        extraction.time.sleep = self._sleep
        os.environ.clear()
        os.environ.update(self.env)

    def run_with(self, answers):
        """answers: model -> list of results in call order; an Exception instance is raised."""
        calls = []

        def generate(model, timeout_s):
            calls.append((model, timeout_s))
            result = answers[model].pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return extraction.extract(b"x", "image/png", [], generate=generate), calls

    def test_every_call_has_a_timeout(self):
        ex, calls = self.run_with({"main-model": [self.GOOD]})
        self.assertEqual(ex.model, "main-model")
        self.assertTrue(0 < calls[0][1] <= extraction.ATTEMPT_TIMEOUT_S)

    def test_overloaded_model_falls_back_to_the_backup(self):
        ex, calls = self.run_with({"main-model": [RuntimeError("503 UNAVAILABLE high demand")],
                                   "backup-model": [self.GOOD]})
        self.assertEqual([m for m, _ in calls], ["main-model", "backup-model"])
        self.assertEqual(ex.model, "backup-model")
        self.assertIsNone(ex.error)

    def test_busy_model_is_tried_last_on_the_next_upload(self):
        self.run_with({"main-model": [RuntimeError("503 UNAVAILABLE")], "backup-model": [self.GOOD]})
        ex, calls = self.run_with({"backup-model": [self.GOOD]})
        self.assertEqual([m for m, _ in calls], ["backup-model"])   # no second wait for the busy model
        self.assertEqual(ex.model, "backup-model")

    def test_gives_up_with_a_clear_message_when_all_models_are_busy(self):
        busy = lambda: RuntimeError("504 DEADLINE_EXCEEDED")   # noqa: E731
        ex, calls = self.run_with({"main-model": [busy(), busy()], "backup-model": [busy(), busy()]})
        self.assertEqual(len(calls), 4)               # two rounds, then stop: never an endless wait
        self.assertIn("overloaded or too slow", ex.error)

    def test_rejected_key_stops_at_once(self):
        ex, calls = self.run_with({"main-model": [RuntimeError("400 API key not valid. API_KEY_INVALID")]})
        self.assertEqual(len(calls), 1)
        self.assertIn("rejected the API key", ex.error)

    def test_retired_model_uses_the_backup(self):
        ex, _ = self.run_with({"main-model": [RuntimeError("404 NOT_FOUND")], "backup-model": [self.GOOD]})
        self.assertEqual(ex.model, "backup-model")


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
