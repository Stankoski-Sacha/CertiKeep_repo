# CertiKeep — M3 summary

**Team:** Sacha Stankoski · Luc [surname] · Mattéo [surname]  
**Repository:** https://github.com/Stankoski-Sacha/CertiKeep_repo — **tag `m3`**  
**Demo video (3 min, unlisted):** [paste link]  
**Run it:** README, 5 steps (`git clone --branch m3 …` → venv → `pip install -r requirements.txt` → `.env` with Gemini key → `python app.py`).
Tested on a laptop that is not ours: [whose laptop, OS, date].

## What it does

A site manager or HR person uploads a certificate scan or phone photo. **Gemini reads the worker, certificate type,
issue date and expiry date** (with a confidence per field). The values are **validated in code** (expiry after issue,
plausible dates, known worker). The person **checks them next to the scan and confirms**. Only then does the
certificate count. The status table shows every worker × required certificate as *valid*, *expires ≤ 60 / ≤ 30
days*, *expired*, *missing* or *needs review*. Every upload, AI answer, correction and confirmation is in the
audit trail (who and when, CSV export).

**AI feature in the critical path:** without the extraction step, every field has to be typed by hand from the scan.
The app always calls the real Gemini API; there are no mocked responses (only the unit tests use a fixed answer).
Unreadable photos, unknown layouts and API failures lead to *needs review* with empty fields, never to a guess.

## Architecture

See [`architecture.md`](architecture.md): Browser → Upload → Gemini extraction → normalise → validation in code →
human review → SQLite + audit log → status table. Files and data stay on the machine running the app; only the
document image goes to Gemini.

## Known bugs and limitations

1. **Certificates without a printed expiry date can never turn green.** Some medical certificates say "next exam
   on notice" instead of a date. Validation then blocks confirmation, so they stay *needs review*. There is no
   "valid until further notice" option yet.
2. **No login.** The reviewer types their name, so anyone with access to the app can confirm under any name. The
   audit trail records the name typed, not a verified identity.
3. **The upload waits for Gemini (5–20 s, up to ~30 s on free-tier rate limits).** The extraction runs inside the
   request; on rate limits the person sees an error and must press *Run AI again* or type the values.
4. **One certificate per file.** A PDF with several certificates or several workers produces one record only.
5. **Documents are sent to Google.** On the free tier Google may use inputs to improve its products, so the
   current version is only suitable for own, consented or redacted documents, not real customer data.
6. **No reminders yet.** Expiring certificates are visible in the table but nobody is emailed.
7. **Date fields follow the browser's language.** An English-language browser shows MM/DD/YYYY, which can
   confuse European users even though the stored date is correct.
8. **Accuracy on real, messy photos is unproven.** Our test set is small and partly synthetic (specimen
   certificates).

## Who did what since M2

| Person | Contribution |
|---|---|
| Sacha | [one line] |
| Luc | [one line] |
| Mattéo | [one line] |
