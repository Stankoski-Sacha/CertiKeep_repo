# CertiKeep

AI-assisted tracking of worker certificates (medical fitness, first aid, working at height, forklift …)
for companies whose workers need valid certificates. First market: construction firms in Luxembourg
with 10+ employees.

Upload a scan or phone photo → **Gemini reads the worker, certificate type and dates** → the values are
checked in code → **a person confirms them next to the scan** → the status table shows who is valid,
expiring in 30/60 days, expired, missing or waiting for review. Every step is recorded in an audit trail.

## Run it (5 steps)

You need **Python 3.10+** and a free **Gemini API key** from https://aistudio.google.com/apikey.

```bash
# 1. Get the code (M3 version)
git clone --branch m3 https://github.com/Stankoski-Sacha/CertiKeep_repo.git && cd CertiKeep_repo

# 2. Create a virtual environment
python3 -m venv .venv && source .venv/bin/activate        # Windows: py -m venv .venv && .venv\Scripts\activate

# 3. Install
pip install -r requirements.txt

# 4. Add your Gemini key: copy the example file, then paste the key after GEMINI_API_KEY=
cp .env.example .env                                       # Windows: copy .env.example .env

# 5. Start, then open http://127.0.0.1:8000
python app.py
```

**Try it:** Workers → *Add the 4 example workers* → Upload → pick a page from
[`experiments/specimens/certikeep_specimen_certificates.pdf`](experiments/specimens/) (PDF or a phone photo of it)
→ check the fields next to the scan → Confirm → Status.

Data (database and uploaded files) is stored locally in `instance/` and is not committed.

## How it works

| Step | What happens | Code |
|---|---|---|
| Upload | JPG, PNG, WEBP or PDF, max 15 MB | `certikeep/__init__.py` |
| AI extraction | Gemini returns JSON: worker, type, issue date, expiry date, confidence per field, readable yes/no. It is told never to guess or compute dates. | `certikeep/extraction.py` |
| Validation in code | Expiry after issue, dates in a plausible range, name matches a known worker, low-confidence fields flagged | `certikeep/domain.py` |
| Human review | Scan and fields side by side; the person corrects and confirms. Errors block confirmation. | `templates/review.html` |
| Status | Nothing is green until confirmed. Unreadable or failed AI → *needs review*, never a guess. | `certikeep/domain.py` |
| Audit trail | Upload, AI answer, every correction, who confirmed and when; CSV export | `/audit` |

Architecture diagram: [`docs/architecture.md`](docs/architecture.md) ·
M3 summary: [`docs/m3-summary.md`](docs/m3-summary.md)

## Tests

```bash
python -m unittest discover tests
```

The tests replace Gemini with a fixed answer so the flow can be checked offline; the running app always calls Gemini.

## Troubleshooting

- **"GEMINI_API_KEY is not set"** – the `.env` file is missing or the key is empty (step 4).
- **"Gemini model not found"** – Google retired the model; set `GEMINI_MODEL=` in `.env` to a current one from AI Studio.
- **"free-tier limit reached"** – wait a minute and press *Run AI again*, or enter the fields by hand.
- **Port already in use** – `PORT=8001 python app.py` (Windows PowerShell: `$env:PORT=8001; python app.py`).

## M2 experiment

The comparison of Gemini and Tesseract that led to this choice is in [`experiments/`](experiments/README.md).

## Safety principle

AI-extracted fields are suggestions. A person must verify certificate details before they count, and the
tool does not declare legal compliance on its own.
