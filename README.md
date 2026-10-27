# CertiKeep

AI-assisted certification and compliance tracking for small and medium-sized construction firms.

## Problem
Certificate details arrive as PDFs, scans and phone photos. CertiKeep aims to help managers find missing or expiring credentials, prepare renewals and maintain reviewable audit records.

## MVP goals
- Upload and organise worker certificates.
- Extract likely worker name, certificate type and issue/expiry dates.
- Require human review before extracted values are treated as confirmed.
- Show valid, expiring soon, missing and needs-review statuses.
- Support reminders and audit-friendly exports.

## Current status
Early discovery and technical feasibility. See [`PROJECT_LOG.md`](PROJECT_LOG.md) for interview notes and project framing, and [`docs/decision-and-plan.md`](docs/decision-and-plan.md) for the initial approach comparison, cost estimate, architecture and MVP plan.

## Run the baseline experiment
Requires Python 3.9+ and no third-party packages:

```bash
python3 experiments/date_extraction_experiment.py
```

The experiment evaluates a simple date parser on 10 synthetic OCR-text cases. It does not evaluate image OCR or a hosted AI model; do not interpret the score as production accuracy.

## Safety principle
AI-extracted fields are suggestions. A qualified person must verify certificate details and site/task requirements. The tool must not independently declare legal compliance.

## License
To be decided.
