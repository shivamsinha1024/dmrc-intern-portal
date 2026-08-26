# DMRC Intern Referral System & HR Command Center

## Architecture Overview

This repository contains the DMRC Intern Referral Portal, designed for deployment on the DMRC Intranet.

* **Backend:** Django REST Framework (Python) connected to a MySQL 8.0.16+ database.
* **Frontend:** HTML/JS powered by Alpine.js and Bootstrap 5.

**Note on Frontend:** The frontend requires no Node.js build step or `package.json`. All reactive state and UI styling are handled natively in the browser.

**No internet access required.** All frontend libraries are held locally at pinned versions — Alpine.js 3.16.2, Bootstrap 5.3.3, Bootstrap Icons 1.11.3, Flatpickr 4.6.13, and the web fonts. Neither page contacts the public internet, and both have been verified working offline.

**Note on authentication:** This portal authenticates nobody. It has no login screen and stores no passwords. Identity is supplied by DMRC's existing employee login; the portal only decides what an identified employee may do. See `portal/identity/base.py`.

---

## IT Deployment Instructions

### 1. Environment Setup

1. Clone this repository to the host server.
2. Navigate to the `Back End` directory.
3. Copy `.env.example` to `.env` and populate the production MySQL credentials and a freshly generated `SECRET_KEY`.
4. Restrict `.env` so only the account running the application can read it.

Confirm the Python version first — Django 4.2 supports Python 3.8 through 3.12:

```bash
python3 --version
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

An application server is not included in `requirements.txt`. Install Gunicorn or uWSGI according to DMRC standards.

### 3. Create the Database

`DB/Intern_Portal.sql` is the authoritative schema. It creates the database, all 27 tables, and seeds reference data (roles, departments, sub-departments, document types).

```bash
mysql -u <admin_user> -p < "DB/Intern_Portal.sql"
```

> ### ⚠ Run this exactly once, against an empty database.
> The script begins by dropping every table it creates. Re-running it on a database that holds live data will delete that data permanently.

**Do not run anything in `DB/history/`.** Those files record how the schema evolved during development. Every change they make is already present in the master script, and one of them uses TiDB-specific syntax that will not run on MySQL at all.

**Do not run anything in `DB/dev_only/`.** Those scripts reset or seed data for local development. One of them inserts fictitious employees.

### 4. Run Django's Migrations

```bash
python manage.py migrate
```

This creates only Django's own internal tables (sessions, content types, auth). The portal's own models are declared `managed = False`, so Django never creates or alters the tables from step 3.

### 5. Populate the Employee Directory — REQUIRED

**The portal will not work until this is done.** This portal does not own employee identity: it reads the `employees` table and never writes to it. On an empty table every request is refused with a 401, including the Phase 1 referral portal.

Each row requires an employee code, full name, designation, department and official email. The employee code must be *exactly* the string DMRC's login system returns for that person.

```sql
INSERT INTO employees (employee_code, full_name, designation, department_id)
VALUES (
  '14086',
  'NAME AS IN DIRECTORY',
  'DESIGNATION AS IN DIRECTORY',
  (SELECT department_id FROM departments WHERE department_name = 'IT')
);
```

`official_email` is optional and may be omitted. Employee codes at DMRC are numeric, 1 to 5 digits.

The designation is printed beneath the signature on every offer letter that person signs, so it must be kept current.

Departed employees are never deleted — the database refuses to remove anyone who has ever referred a candidate, since that would destroy referral history. Set `is_active = FALSE` instead; identity resolution ignores inactive employees, so access is withdrawn while every record naming them survives.

### 6. Create the First SYS-ADMIN — REQUIRED

Dashboard accounts are created from the IAM screen, which requires the caller to already hold the SYS-ADMIN role. The first account therefore cannot be created through the interface and must be inserted directly:

```sql
INSERT INTO users (role_id, employee_id, username, email)
VALUES (
  (SELECT role_id FROM roles WHERE role_name = 'SYS-ADMIN'),
  (SELECT employee_id FROM employees WHERE employee_code = '14086'),
  'chosen.username',
  'person@dmrc.org'
);
```

That person can then provision every other HR account from the dashboard.

### 7. Implement the Intranet Identity Provider

Implement `get_employee_code()` in `portal/identity/intranet.py`, then set in `.env`:

```
IDENTITY_PROVIDER=portal.identity.intranet.IntranetIdentityProvider
```

The contract is documented in `portal/identity/base.py`; four common integration patterns are sketched in `intranet.py`. This is the entire integration.

The server refuses to start in production while the development provider is configured.

### 8. Serve the Application

Run the Django application through Gunicorn or uWSGI behind the web server. **Never start it with `manage.py runserver` on a server** — that turns on development mode, which disables the production safety checks.

Serve the two frontend directories as static files:

* `Front End/Phase-1-User-Portal/` — the employee referral portal
* `Front End/Phase-2-HR-Dashboard/` — the HR dashboard

**Preferred arrangement:** serve the pages and forward `/api/` to the Django application from the *same* address. Requests are then same-origin, the CORS settings become irrelevant, and the frontend can use relative links.

If Pattern A (reverse-proxy header) is used for identity, the proxy must strip the identity header from inbound requests **and** the application must not be reachable except through the proxy.

---

## Operational Requirements

### File storage

Uploaded documents, generated letters and signature images are stored on the **server filesystem**, outside the web root — not in the database:

```
Back End/protected_documents/     candidate uploads
Back End/generated_documents/     offer letters and certificates
Back End/signatures/              officer signature images
Back End/quarantine/              superseded and rejected files
```

These directories are created automatically on first use. They require:

1. **Persistent storage** that survives redeployment.
2. **Backup together with the database.** A database-only backup restores records pointing at files that no longer exist, and closing an archive cycle fails when a referenced file is missing.
3. **Exclusion from any temporary-file cleanup policy.**

### Logging

Warnings and errors are written to `Back End/logs/portal.log`, rotating at 5 MB with five old copies retained. Set `LOG_DIR` in `.env` to redirect this to a central location.

### Personal data

Candidate records include **Aadhaar numbers, stored in full and unencrypted**, in the `students` and `archived_applications` tables. Consent is captured at upload and every document access is logged. Apply DMRC's data-protection and records-retention policy to both the database and the file storage directories above.

---

## Known Gaps

| Gap | Status |
|---|---|
| Frontend contains 61 hardcoded `http://127.0.0.1:8000` addresses that will not work on the intranet | To be fixed; depends on the API server address and the identity arrangement |
| Django 4.2 reached end of security support in April 2026 | Upgrade to 5.2 LTS planned |
| Automated email notifications | In development, delivered after integration |
| No upload size limit on candidate documents (file *types* are validated) | Pending a limit from HR |
| No automated test suite | Tested manually against the full workflow |
| No API versioning or rate limiting | Acceptable for a single internal consumer |

**Closed:** frontend libraries are now self-hosted at pinned versions; the database connection is configurable via `DB_SSL` / `DB_SSL_CA`; departed employees can be deactivated via `employees.is_active`.

---

## Repository Layout

```
Back End/          Django application
  dmrc_core/       project settings and root URLs
  portal/          the application: views, models, identity, document generation
  requirements.txt
  .env.example
DB/
  Intern_Portal.sql   THE master schema -- the only file to run
  history/            development migration history -- DO NOT RUN
  dev_only/           local development utilities -- DO NOT RUN
  ER Diagram.pdf
Front End/
  Phase-1-User-Portal/    employee referral portal
  Phase-2-HR-Dashboard/   HR dashboard
Docs/              handover documentation
```