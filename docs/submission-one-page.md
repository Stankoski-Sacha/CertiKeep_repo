# CertiKeep — technical choice and first MVP plan
**19 October 2026 | Initial market: small and medium-sized construction firms**

**Problem.** Site managers and HSE officers receive certificates as PDFs, scans and photos. CertiKeep should extract likely worker names, certificate types and dates, flag missing/expiring credentials and support audit-ready records. AI output must be reviewed by a qualified person before it is treated as confirmed.

## Two candidate approaches

| Dimension | A. Hosted vision AI | B. Local OCR + rules |
|---|---|---|
| Output quality | Likely handles varied layouts/context better; must test | Predictable on clean text; brittle on varied layouts |
| Cost per unit | API usage charges, variable with tokens/images | No per-request model fee; compute and maintenance remain |
| Latency | Network + model processing | Local processing; depends on device and scan |
| Data needed | Certificate image/PDF page + schema/prompt | Image/PDF + OCR language pack and parsing rules |
| Failure modes | Misread/hallucinated fields, API outage, privacy risk | OCR errors, ambiguous dates, rules miss unseen layouts |
| Vendor lock-in | Medium–high unless behind an adapter | Low–medium; engine can be swapped, rules still need work |

**Decision.** For the first prototype, keep a provider-neutral extraction interface and measure local OCR/rules as a baseline before selecting a hosted vision model. Do not claim a winner before comparing both on the same documents.

## First experiment
`python3 experiments/date_extraction_experiment.py` runs 10 synthetic OCR-text cases. Result: **10/10 exact matches (100%)** for expiry-date extraction, including one missing-date case. This tests date parsing only; it does not measure OCR, AI quality or real-world generalisation. Three illustrative cases: ISO date `2027-04-30` → correct; day-first `15/02/2027` → `2027-02-15`; missing expiry → `null`. The last case shows the parser can abstain when no date is present.

## First cost estimate — 19 October 2026
Candidate pricing reference: OpenAI GPT-6 Luna standard short-context rates, **$0.05/1M input tokens and $0.25/1M output tokens** (official pricing: https://developers.openai.com/api/docs/pricing?tab=suite; checked 19 Oct 2026).
Illustrative text-only action: 1,500 input tokens × $0.05/1,000,000 = $0.000075; 200 output tokens × $0.25/1,000,000 = $0.000050; total **$0.000125/action**. Image tokens, retries, taxes and infrastructure are excluded; this is not a full image-processing quote. Official image calculator: https://developers.openai.com/api/docs/guides/image-cost-calculator. Tesseract OCR is Apache-2.0 licensed: https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE.

## Architecture sketch
`Upload PDF/photo → validate/preprocess → extraction adapter (local OCR/rules OR hosted vision AI) → normalize and validate fields → human review queue → confirmed certificate database → expiry statuses/reminders + audit export`

## Three limitations and switch criteria
1. Synthetic text is not real scanned certificates.
2. Ambiguous layouts and dates can associate a correct date with the wrong field/person.
3. Extracted data cannot itself establish legal/site compliance; human verification remains mandatory.

Switch the default only after testing both candidates on the same ≥50 synthetic/redacted representative documents. Target: ≥10 percentage-point improvement in exact-match expiry-date and certificate-type extraction, within agreed cost/latency limits, and after privacy review. Any incorrect expiry date is high severity and must be reviewable.

## MVP plan
| Task | Owner | Due |
|---|---|---|
| Finalise fields and status rules | Whole team | 20 Oct 2026 |
| Build 50-case evaluation set | Whole team | 22 Oct 2026 |
| Implement provider-neutral extraction schema | Whole team | 26 Oct 2026 |
| Test hosted candidate on same cases | Whole team | 27 Oct 2026 |
| Build human-review UI | Whole team  | 30 Oct 2026 |
| Add reminders and audit export; privacy review/demo | Whole team | 6 Nov 2026 |

