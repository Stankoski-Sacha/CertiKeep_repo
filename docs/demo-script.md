# Demo video script (3 minutes)

Record from the running app (QuickTime: File → New Screen Recording, with microphone). Before recording:
start with an empty `instance/` folder, have the specimen pages and one real (redacted) certificate photo ready,
and check that your Gemini key works by uploading one file and deleting `instance/` again.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | Status page (empty) | "Construction firms track worker certificates in Excel and check expiries by hand. CertiKeep reads the certificate with AI and shows who is cleared." |
| 0:20–0:40 | Workers → *Add the 4 example workers* → Status | "Each worker has the certificates their role requires. Right now everything is missing." |
| 0:40–1:15 | Upload specimen page 1 (French) | "I upload a scan. Gemini reads the worker, type and dates. Here they are next to the scan, with the AI's confidence. Nothing is valid yet." Confirm. |
| 1:15–1:40 | Status page | "After I confirmed, Marc Weber's medical certificate is green until March 2027." |
| 1:40–2:10 | Upload specimen page 4 (no expiry date printed) | "This certificate has no expiry date. The AI leaves it empty instead of guessing, and the app won't let me confirm it." |
| 2:10–2:30 | Upload a blurry photo | "A blurry photo is flagged as unreadable. It goes to review, never to a guess." |
| 2:30–2:50 | Audit trail | "Everything is logged: the AI's original answer, my corrections, who confirmed and when. It can be exported as CSV." |
| 2:50–3:00 | Status page | "One known limitation: certificates without an expiry date stay in review. Next: reminders and logins." |

Keep the real Gemini call visible (the "Reading the document…" button state). Do not cut it out: the brief asks
for a recording of the running product.
