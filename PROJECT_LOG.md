# Certification and Compliance Tracker

**Product working name:** CertiKeep  
**Initial market:** Small and medium-sized construction firms  

## 1. Problem statement

Small construction companies need to know whether every worker's safety training, first-aid certificate, forklift licence and other required credentials are still valid. In many small teams, the information sits in a spreadsheet, email attachments, paper folders or someone's memory. Someone has to check dates, chase workers for missing documents and arrange refresher training. Because certificates expire throughout the year, this is a recurring job rather than a once-a-year task. A missed expiry can keep a worker off a site, delay a job or create problems during an inspection.

## 2. Users and customers

**Market size.** We start with construction firms in Luxembourg that have at least
10 employees. Our interviews suggest that very small firms do not feel the problem
yet: a one-person business owner told us spreadsheets would be enough for years,
while a 36-employee company spends about 10 minutes every day checking certificates
and sending reminders by hand.

| Step | Number | Source |
|---|---|---|
| Active construction enterprises in Luxembourg (NACE F) | 4,496 | STATEC, Lustat D1300 |
| Share with more than 10 employees | ≈ 24% | Luxinnovation (75.6% have 1–10 employees) |
| **Serviceable market: construction firms with 10+ employees** | **≈ 1,100** | 4,496 × 24% |
| **Target: 5% within three years** | **≈ 55 firms** | our assumption |

Firms of this size have enough workers and certificates that manual tracking becomes
a recurring cost, but usually no dedicated HR or HSE software. Once we have customers
in Luxembourg, the next step is the Greater Region (Lorraine, Saarland,
Rhineland-Palatinate, Wallonia), where many construction firms work across the same
borders.

## 3. Interviews

| # | Company type | Size | Interviewee role | How we reached them | Format | Date | Interviewer(s) |
|---|---|---|---|---|---|---|---|
| A | [sector], Luxembourg | 36 employees | HR | Family connection of a team member | Phone, ~10 min | [date] | Sacha |
| B | [sector], Luxembourg | 1 person (owner) | Owner | Prior acquaintance; first contacted via Discord | Phone, ~15 min | [date] | Luc, Sacha |

Names and contact details are kept in a private team file and can be shown on request.

### Interview A: HR, 36-person company
- Tracks employees, certificates and expiry dates in an Excel sheet.
- Main pain: expiries are checked by hand and reminders are sent by hand.
- No missed work so far because of expired certificates, but some last-minute stress and extra work to get renewals done in time.
- Spends about 10 minutes a day checking certificates for 36 employees (~3.5 h/month).
- Most wanted features: automatic reminder emails and one central platform.
- Current cost: only the Office 365 subscription they already pay for.

### Interview B: owner, one-person business
- No employees yet; expects 2–3 within 3–5 years and more paperwork as the company grows.
- Has no system for certifications; would give the task to an employee later.
- Thinks spreadsheets are enough until roughly 100 employees; sees no benefit from CertiKeep at his current size.
- No preference between a custom build and a subscription; would decide on architecture, UI and ease of use. Expects a custom solution to cost from about €30,000.

### What we learned
- The pain is real at 36 employees: manual checks, manual reminders, last-minute renewals.
- Micro-businesses don't feel it. Our segment should be firms with 10+ employees.
- Their current tooling costs almost nothing (Excel/Office 365), so pricing has to be low and saved time has to be obvious.
- Neither company is in construction, yet the 36-employee company has the same problem (manual checks, manual reminders, last-minute renewals). This suggests the need is not specific to construction; we start with construction because certificates there are mandatory, numerous and checked on site, and expand to other regulated sectors later.
## 4. Existing alternatives

- **Excel and calendar reminders:** cheap and familiar, but someone still has to enter dates, chase missing files and keep records up to date.
- **Full HR/HSE compliance software:** may offer more controls, but can be expensive or too complex for a small firm that just needs reliable certificate tracking.
- **Paper folders or doing nothing until an audit:** requires last-minute searching and can leave managers discovering expired or missing documents when they are needed most.

## 5. Value proposition

For site and operations managers at small construction firms who need to keep workers qualified without chasing paperwork, CertiKeep is an AI-assisted certification tracker that flags expiries early, organises renewals and keeps audit-ready records, unlike spreadsheets and calendar reminders.

## 6. Why AI

Certificates arrive as scans, phone photos and PDFs in different layouts, so copying every name, certificate type and expiry date into a spreadsheet is slow and error-prone. AI-based document reading can extract the likely details and match them to a worker's record, while confidence checks send unclear cases to a person. It can also pre-fill renewal paperwork. A manager should still verify extracted dates and any role-specific legal requirements; AI should support compliance decisions, not make them unchecked.

## Sources

- STATEC, *Le Luxembourg en chiffres 2024*, active enterprises by economic activity (Lustat D1300): https://statistiques.public.lu/dam-assets/catalogue-publications/luxembourg-en-chiffres/2024/luxembourg-en-chiffres-2024.pdf
- Luxinnovation, *Panorama of Luxembourg's construction ecosystem* (2025): https://luxinnovation.lu/resources/construction-ecosystem-facts-figures
