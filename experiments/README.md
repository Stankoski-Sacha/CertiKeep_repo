# M2 experiment: Gemini (vision AI) vs Tesseract (local OCR + rules)

**Question:** which approach reads worker certificates more reliably — names, certificate
types, issue dates and expiry dates — on real scans and phone photos?

Both approaches get exactly the same images. Their output is compared field by field with
what is actually printed on each document (`ground_truth.csv`). Wrong or invented expiry
dates count as the most serious error, because they could mark an expired worker as valid.

## Files

| File | What it does |
|---|---|
| `run_gemini.py` | Approach A: sends each image to Gemini (free tier) and asks for JSON |
| `run_tesseract.py` | Approach B: Tesseract OCR + transparent rules (`ocr_rules.py`) |
| `evaluate.py` | Compares both with the ground truth and writes `RESULTS.md` |
| `validation.py` | Checks in code (expiry after issue, plausible range, known worker, low confidence) + status rules |
| `common.py` | Shared helpers: date parsing (FR/DE/EN), certificate types, file handling |
| `ground_truth.example.csv` | Template for `ground_truth.csv` |
| `workers.example.csv` | Template for `workers.csv` (names of known workers) |

## Steps

### 1. Install (once)

```bash
pip install -r experiments/requirements.txt
```

Tesseract itself is a separate program:
- **Windows:** installer from https://github.com/UB-Mannheim/tesseract/wiki (tick French + German), then add it to PATH
- **macOS:** `brew install tesseract tesseract-lang`
- **Linux:** `sudo apt install tesseract-ocr tesseract-ocr-fra tesseract-ocr-deu`

For PDF scans you also need `pdftoppm` (poppler): `brew install poppler` / `sudo apt install poppler-utils` /
on Windows the poppler release from https://github.com/oschwartz10612/poppler-windows.

### 2. Add the scans

Put 5–10 certificates in `experiments/scans/` (jpg, png or pdf). Aim for a mix:
a clean PDF, a flatbed scan, a phone photo, one in French, one in German, and **one deliberately
blurry photo** (to check that it ends up as "needs review" instead of a guess).

Use your own certificates or ones from people who agreed. Black out ID numbers, addresses and
any medical details before running anything — the Gemini free tier may use inputs to improve
Google's products.

### 3. Write the ground truth

```bash
cp experiments/ground_truth.example.csv experiments/ground_truth.csv
cp experiments/workers.example.csv experiments/workers.csv
```

In `ground_truth.csv`, one row per scan, typed by a person looking at the document:

- `file`: file name in `scans/`
- `worker_name`, `issue_date`, `expiry_date` (YYYY-MM-DD) exactly as printed. **Leave empty if it is not printed** (e.g. only "valid 3 years").
- `certificate_type`: one of `medical_fitness, first_aid, working_at_height, forklift, electrical, scaffolding, crane, asbestos, safety_training, other`
- `readable`: `no` for the deliberately unreadable photo
- `source`: where the scan comes from (e.g. "own certificate, Luc") — this makes it traceable

In `workers.csv`, list the names of the people whose certificates you use (this is the
"known workers" list the validation checks names against).

Do this **before** looking at any model output, so the ground truth isn't influenced by it.

### 4. Run both approaches

```bash
python experiments/run_tesseract.py
export GEMINI_API_KEY=...            # free key: https://aistudio.google.com/apikey
python experiments/run_gemini.py     # waits a few seconds between files (free-tier limit)
```

Optional: `--model <name>` to try another Gemini model (default `gemini-3.8-flash`; check AI Studio for which models are on the free tier).

### 5. Evaluate

```bash
python experiments/evaluate.py
```

This writes `experiments/RESULTS.md` (names shown as initials only) and `results/summary.json`.
Commit those two files, then write the decision in `docs/submission-one-page.md`.

## Privacy

`scans/`, `ground_truth.csv`, `workers.csv` and the raw outputs in `results/gemini/` and
`results/tesseract/` are git-ignored because they contain names. Keep them in the team's private
drive so we can show them if the teaching team asks.

## Tests

```bash
python -m unittest discover tests
```
