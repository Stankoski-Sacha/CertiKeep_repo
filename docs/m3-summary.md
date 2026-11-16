# CertiKeep — M3 summary

**Team:** Sacha Stankoski · Luc Muller · Mattéo Nere
**Repository:** https://github.com/Stankoski-Sacha/CertiKeep_repo 
**Demo video (3 min, unlisted):** [paste link]  
**Run it:** README, 5 steps (`git clone` → venv → `pip install -r requirements.txt` → `.env` with Gemini key → `python app.py`).
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
3. **The AI read depends on Google's capacity, and it fails when the models are overloaded.** On 16 Nov 2026,
   `gemini-3.6-flash` and `gemini-3.8-flash` (our main and fallback model) both returned
   *503 "high demand"* or *504 timeout* on the same specimen, so the read gave up after about 90 s and the
   document went to *needs review* with empty fields. `gemini-3.7-flash` and `gemini-3.1-flash-lite` also
   returned 503 or timed out, while `gemini-3.5-flash-lite` read the same file correctly in about 2 s.
   The app handles this safely (banner, *Run AI again*, manual entry, no guessed values), but on such days
   the user waits up to ~100 s for nothing. Model names are also not stable: `gemini-2.5-flash` is no longer
   available to new users. The read runs as a thread inside the app, so a read in progress is lost if the
   app is restarted. We now try `gemini-3.5-flash-lite` first; it is faster but a smaller model, and its accuracy on messy phone photos is not yet tested.
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
| Sacha | First website design and AI implementation, demo video |
| Luc | Made the architecture |
| Mattéo | Improvements to the website design, with help of claude code. Solving the issues with the AI |
