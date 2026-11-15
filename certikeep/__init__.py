"""CertiKeep web app: upload a certificate -> AI extracts fields -> code validates ->
a person confirms next to the scan -> workers x certificates status table.

The AI read runs in a background thread: the upload answers at once and the review page
polls /documents/<id>/status until the suggestion is there (or the read has failed)."""
from __future__ import annotations

import csv
import io
import json
import os
import secrets
import threading
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, redirect, render_template, request,
                   send_from_directory, session, url_for)

from . import db as dbm
from .db import get_db, log, now
from .domain import (CERT_TYPES, STATUS_LABELS, has_errors, name_key, parse_date, status,
                     validate)
from .extraction import FIELDS, TOTAL_BUDGET_S, ExtractionError, extract
from .icons import icon

ALLOWED = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
           ".webp": "image/webp", ".pdf": "application/pdf"}

DEMO_WORKERS = [
    ("Marc Weber", "Mason", ["medical_fitness", "first_aid"]),
    ("Jane Doe", "Scaffolder", ["medical_fitness", "working_at_height", "scaffolding"]),
    ("John Smith", "Crane operator", ["medical_fitness", "crane"]),
    ("Sophie Martin", "Site electrician", ["medical_fitness", "electrical"]),
]


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(16),
        DATABASE=os.path.join(app.instance_path, "certikeep.db"),
        UPLOAD_DIR=os.path.join(app.instance_path, "uploads"),
        MAX_CONTENT_LENGTH=15 * 1024 * 1024,
        EXTRACT=extract,     # swapped out only in unit tests
        AI_BACKGROUND=True,  # False: read inside the request (unit tests)
        AI_STALE_S=TOTAL_BUDGET_S + 50,   # a read still "pending" after this is declared failed
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    dbm.init_db(app.config["DATABASE"])
    app.teardown_appcontext(dbm.close_db)

    def asset(filename: str) -> str:
        """Static URL with the file's change time, so browsers pick up a new CSS/JS at once."""
        try:
            version = int((Path(app.static_folder) / filename).stat().st_mtime)
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    app.jinja_env.globals.update(CERT_TYPES=CERT_TYPES, STATUS_LABELS=STATUS_LABELS, icon=icon, asset=asset)

    # ------------------------------------------------------------------ helpers
    def user() -> str:
        return session.get("user", "")

    def remember_user(name: str) -> str:
        name = (name or "").strip()
        if name:
            session["user"] = name
        return name

    def workers() -> list:
        return get_db().execute("SELECT * FROM workers ORDER BY name").fetchall()

    def worker_names() -> list[str]:
        return [w["name"] for w in workers()]

    def doc_or_404(doc_id: int):
        doc = get_db().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if doc is None:
            abort(404)
        return doc

    def doc_issues(doc) -> list[dict]:
        fields = {f: doc[f] for f in FIELDS}
        return validate(fields, worker_names(), confidences=json.loads(doc["confidences"] or "{}"),
                        readable=bool(doc["ai_readable"]))

    def doc_status(doc) -> str:
        return status(bool(doc["confirmed_at"]), doc["expiry_date"])

    app.jinja_env.globals.update(doc_status=doc_status, current_user=user)

    def ai_pending(doc) -> bool:
        return doc["ai_status"] == "pending"

    def ai_elapsed(doc) -> int:
        try:
            return max(0, int((datetime.now() - datetime.fromisoformat(doc["ai_started_at"])).total_seconds()))
        except (TypeError, ValueError):
            return 0

    def ai_failed(doc_id: int, message: str) -> None:
        db = get_db()
        db.execute("UPDATE documents SET ai_status = 'done', ai_error = ?, ai_readable = 0 WHERE id = ?",
                   (message, doc_id))
        log(doc_id, "system", "ai_failed", message)
        db.commit()

    def run_ai(doc_id: int) -> None:
        """Run extraction and store the suggestion. Failures leave empty fields -> needs review."""
        db = get_db()
        doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        try:
            path = Path(app.config["UPLOAD_DIR"]) / doc["stored_name"]
            ex = app.config["EXTRACT"](path.read_bytes(), doc["mime_type"], worker_names())
        except ExtractionError as exc:
            ai_failed(doc_id, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - e.g. SDK not installed, file unreadable
            ai_failed(doc_id, f"The AI step stopped unexpectedly ({type(exc).__name__}: {str(exc)[:160]}).")
            return
        # Link to a known worker only on an exact (order/accent-insensitive) name match.
        worker_id, name = None, ex.fields.get("worker_name")
        for w in workers():
            if name and name_key(w["name"]) == name_key(name):
                worker_id, name = w["id"], w["name"]
                break
        # The AI's answer is always stored for the record ...
        db.execute("""UPDATE documents SET ai_json = ?, ai_model = ?, ai_readable = ?, ai_error = ?, ai_latency_s = ?,
                      ai_status = 'done' WHERE id = ?""",
                   (ex.raw, ex.model, int(ex.readable), ex.error, ex.latency_s, doc_id))
        # ... but it must not overwrite values a person confirmed (or rejected) while it was still reading.
        db.execute("""UPDATE documents SET worker_id = ?, worker_name = ?, certificate_type = ?, issue_date = ?,
                      expiry_date = ?, confidences = ? WHERE id = ? AND confirmed_at IS NULL AND rejected = 0""",
                   (worker_id, name, ex.fields.get("certificate_type"), ex.fields.get("issue_date"),
                    ex.fields.get("expiry_date"), json.dumps(ex.confidences), doc_id))
        if ex.error:
            log(doc_id, "system", "ai_failed", ex.error)
        else:
            log(doc_id, f"AI ({ex.model})", "ai_extracted",
                {"readable": ex.readable, **ex.fields, "confidence": ex.confidences, "seconds": ex.latency_s})
        db.commit()

    def start_ai(doc_id: int) -> None:
        """Mark the document as being read and start the read (in a thread unless AI_BACKGROUND is off)."""
        db = get_db()
        db.execute("UPDATE documents SET ai_status = 'pending', ai_started_at = ?, ai_error = NULL WHERE id = ?",
                   (now(), doc_id))
        db.commit()
        if not app.config["AI_BACKGROUND"]:
            run_ai(doc_id)
            return

        def work() -> None:
            with app.app_context():
                try:
                    run_ai(doc_id)
                except Exception as exc:  # noqa: BLE001 - last resort: the page must stop waiting
                    get_db().rollback()
                    ai_failed(doc_id, f"The AI step stopped unexpectedly ({type(exc).__name__}).")

        threading.Thread(target=work, name=f"certikeep-ai-{doc_id}", daemon=True).start()

    # ------------------------------------------------------------------ dashboard
    @app.route("/")
    def dashboard():
        db = get_db()
        docs = db.execute("SELECT * FROM documents WHERE rejected = 0").fetchall()
        rows, counts = [], {k: 0 for k in STATUS_LABELS}
        for w in workers():
            req = [r["cert_type"] for r in db.execute(
                "SELECT cert_type FROM requirements WHERE worker_id = ? ORDER BY cert_type", (w["id"],))]
            cells = []
            for ctype in req:
                mine = [d for d in docs if d["worker_id"] == w["id"] and d["certificate_type"] == ctype]
                confirmed = [d for d in mine if d["confirmed_at"]]
                pending = [d for d in mine if not d["confirmed_at"]]
                if confirmed:
                    best = max(confirmed, key=lambda d: d["expiry_date"] or "")
                    cell = {"status": doc_status(best), "doc": best, "pending": len(pending)}
                elif pending:
                    cell = {"status": "needs_review", "doc": pending[-1], "pending": len(pending)}
                else:
                    cell = {"status": "missing", "doc": None, "pending": 0}
                counts[cell["status"]] += 1
                cells.append((ctype, cell))
            rows.append({"worker": w, "cells": cells})
        inbox = [d for d in docs if not d["confirmed_at"]]
        return render_template("dashboard.html", rows=rows, counts=counts, inbox=inbox)

    # ------------------------------------------------------------------ workers
    @app.route("/workers", methods=["GET", "POST"])
    def workers_page():
        db = get_db()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            role = request.form.get("role", "").strip()
            required = [t for t in request.form.getlist("required") if t in CERT_TYPES]
            if not name:
                flash("Enter a name.", "error")
            elif any(name_key(n) == name_key(name) for n in worker_names()):
                flash(f"{name} is already in the list.", "error")
            else:
                cur = db.execute("INSERT INTO workers (name, role, created_at) VALUES (?,?,?)", (name, role, now()))
                db.executemany("INSERT INTO requirements VALUES (?,?)", [(cur.lastrowid, t) for t in required])
                log(None, user() or "unknown", "worker_added", {"name": name, "role": role, "required": required})
                db.commit()
                flash(f"Added {name}.", "ok")
            return redirect(url_for("workers_page"))
        reqs = {}
        for r in db.execute("SELECT * FROM requirements"):
            reqs.setdefault(r["worker_id"], []).append(r["cert_type"])
        return render_template("workers.html", workers=workers(), reqs=reqs)

    @app.post("/workers/demo")
    def add_demo_workers():
        db = get_db()
        existing = {name_key(n) for n in worker_names()}
        for name, role, required in DEMO_WORKERS:
            if name_key(name) in existing:
                continue
            cur = db.execute("INSERT INTO workers (name, role, created_at) VALUES (?,?,?)", (name, role, now()))
            db.executemany("INSERT INTO requirements VALUES (?,?)", [(cur.lastrowid, t) for t in required])
        log(None, user() or "unknown", "demo_workers_added")
        db.commit()
        flash("Added the example workers from the specimen certificates.", "ok")
        return redirect(url_for("workers_page"))

    @app.post("/workers/<int:worker_id>/delete")
    def delete_worker(worker_id: int):
        db = get_db()
        w = db.execute("SELECT name FROM workers WHERE id = ?", (worker_id,)).fetchone()
        if w:
            db.execute("DELETE FROM workers WHERE id = ?", (worker_id,))
            log(None, user() or "unknown", "worker_removed", {"name": w["name"]})
            db.commit()
            flash(f"Removed {w['name']}.", "ok")
        return redirect(url_for("workers_page"))

    # ------------------------------------------------------------------ upload
    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        if request.method == "GET":
            return render_template("upload.html")
        actor = remember_user(request.form.get("user", ""))
        f = request.files.get("file")
        if not actor:
            flash("Enter your name first (it is recorded in the audit trail).", "error")
            return redirect(url_for("upload"))
        if not f or not f.filename:
            flash("Choose a file.", "error")
            return redirect(url_for("upload"))
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED:
            flash("Only JPG, PNG, WEBP or PDF files.", "error")
            return redirect(url_for("upload"))
        stored = f"{uuid.uuid4().hex}{ext}"
        path = Path(app.config["UPLOAD_DIR"]) / stored
        f.save(path)
        db = get_db()
        cur = db.execute("""INSERT INTO documents (original_name, stored_name, mime_type, uploaded_at, uploaded_by)
                            VALUES (?,?,?,?,?)""", (f.filename, stored, ALLOWED[ext], now(), actor))
        doc_id = cur.lastrowid
        log(doc_id, actor, "uploaded", f.filename)
        db.commit()
        start_ai(doc_id)     # returns at once; the review page shows progress
        return redirect(url_for("review", doc_id=doc_id))

    # ------------------------------------------------------------------ review
    @app.get("/documents")
    def documents():
        docs = get_db().execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
        return render_template("documents.html", docs=docs)

    @app.get("/documents/<int:doc_id>")
    def review(doc_id: int):
        doc = doc_or_404(doc_id)
        history = get_db().execute("SELECT * FROM audit_log WHERE document_id = ? ORDER BY id",
                                   (doc_id,)).fetchall()
        pending = ai_pending(doc)
        # While the AI is still reading, empty fields are not mistakes yet: no validation messages.
        return render_template("review.html", doc=doc, form=None, issues=[] if pending else doc_issues(doc),
                               conf=json.loads(doc["confidences"] or "{}"), workers=workers(), history=history,
                               pending=pending, elapsed=ai_elapsed(doc))

    @app.get("/documents/<int:doc_id>/status")
    def ai_status(doc_id: int):
        """Polled by the review page while the AI reads. Also the safety net for a read that never ends."""
        doc = doc_or_404(doc_id)
        pending, elapsed = ai_pending(doc), ai_elapsed(doc)
        if pending and elapsed > app.config["AI_STALE_S"]:
            ai_failed(doc_id, f"The AI read did not finish within {app.config['AI_STALE_S']} s. "
                              "Press 'Run AI again', or fill in the fields by hand.")
            pending = False
        return {"pending": pending, "elapsed": elapsed}

    @app.get("/documents/<int:doc_id>/file")
    def document_file(doc_id: int):
        doc = doc_or_404(doc_id)
        return send_from_directory(app.config["UPLOAD_DIR"], doc["stored_name"], mimetype=doc["mime_type"])

    @app.post("/documents/<int:doc_id>/confirm")
    def confirm(doc_id: int):
        db = get_db()
        doc = doc_or_404(doc_id)
        actor = remember_user(request.form.get("user", ""))
        worker = db.execute("SELECT * FROM workers WHERE id = ?", (request.form.get("worker_id") or 0,)).fetchone()
        form = {
            "worker_name": worker["name"] if worker else "",
            "certificate_type": request.form.get("certificate_type", ""),
            "issue_date": request.form.get("issue_date", "").strip(),
            "expiry_date": request.form.get("expiry_date", "").strip(),
        }
        # A person is now vouching for the values, so AI confidence no longer applies.
        issues = validate(form, worker_names())
        if not actor:
            issues.insert(0, {"level": "error", "msg": "Enter your name: confirmations are recorded with who and when."})
        if has_errors(issues):
            history = db.execute("SELECT * FROM audit_log WHERE document_id = ? ORDER BY id", (doc_id,)).fetchall()
            return render_template("review.html", doc=doc, form={**form, "worker_id": worker["id"] if worker else None},
                                   issues=issues, conf=json.loads(doc["confidences"] or "{}"),
                                   workers=workers(), history=history,
                                   pending=ai_pending(doc), elapsed=ai_elapsed(doc)), 422
        changes = {f: {"ai": doc[f], "confirmed": form[f]} for f in FIELDS if (doc[f] or "") != form[f]}
        db.execute("""UPDATE documents SET worker_id = ?, worker_name = ?, certificate_type = ?, issue_date = ?,
                      expiry_date = ?, confirmed_by = ?, confirmed_at = ? WHERE id = ?""",
                   (worker["id"], form["worker_name"], form["certificate_type"], form["issue_date"] or None,
                    form["expiry_date"], actor, now(), doc_id))
        if changes:
            log(doc_id, actor, "corrected", changes)
        log(doc_id, actor, "confirmed", {**form, "warnings": [i["msg"] for i in issues]})
        db.commit()
        flash(f"Confirmed by {actor}. Status: {STATUS_LABELS[status(True, form['expiry_date'])]}.", "ok")
        return redirect(url_for("dashboard"))

    @app.post("/documents/<int:doc_id>/retry")
    def retry(doc_id: int):
        doc = doc_or_404(doc_id)
        if doc["confirmed_at"]:
            flash("Already confirmed; the AI result is kept for the record.", "error")
        elif not ai_pending(doc):       # a second click while it is reading does nothing
            log(doc_id, user() or "unknown", "ai_rerun_requested")
            start_ai(doc_id)
        return redirect(url_for("review", doc_id=doc_id))

    @app.post("/documents/<int:doc_id>/reject")
    def reject(doc_id: int):
        doc_or_404(doc_id)
        actor = remember_user(request.form.get("user", "")) or user() or "unknown"
        reason = request.form.get("reason", "").strip() or "no reason given"
        get_db().execute("UPDATE documents SET rejected = 1 WHERE id = ?", (doc_id,))
        log(doc_id, actor, "rejected", reason)
        get_db().commit()
        flash("Document rejected. It no longer counts for any worker.", "ok")
        return redirect(url_for("dashboard"))

    # ------------------------------------------------------------------ audit
    @app.get("/audit")
    def audit():
        entries = get_db().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 500").fetchall()
        return render_template("audit.html", entries=entries)

    @app.get("/audit.csv")
    def audit_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "document_id", "at", "actor", "action", "detail"])
        for e in get_db().execute("SELECT * FROM audit_log ORDER BY id"):
            w.writerow([e["id"], e["document_id"], e["at"], e["actor"], e["action"], e["detail"]])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=certikeep_audit.csv"})

    @app.errorhandler(413)
    def too_large(_e):
        flash("File is larger than 15 MB.", "error")
        return redirect(url_for("upload"))

    @app.template_filter("pretty_date")
    def pretty_date(value):
        d = parse_date(value) if isinstance(value, str) else None
        return d.strftime("%d %b %Y") if d else (value or "–")

    @app.template_filter("pretty_dt")
    def pretty_dt(value):
        """'2026-11-13T15:50:02' -> '13 Nov 2026, 15:50'."""
        try:
            return datetime.fromisoformat(value).strftime("%d %b %Y, %H:%M")
        except (TypeError, ValueError):
            return value or "–"

    @app.template_filter("initials")
    def initials(name):
        parts = (name or "").split()
        return ((parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")) if parts else "?").upper()

    @app.template_filter("hue")
    def hue(name):
        """Stable colour per person for the avatar circle."""
        return sum(ord(c) for c in (name or "")) * 37 % 360

    @app.template_filter("detail_pairs")
    def detail_pairs(detail):
        """Audit details are JSON objects or plain text; return [(key, text)] for objects, else None."""
        try:
            data = json.loads(detail)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        show = lambda v: "–" if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))  # noqa: E731
        return [(k.replace("_", " "), show(v)) for k, v in data.items()]

    return app
