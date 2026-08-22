# API Endpoint Reference

**DMRC Intern Referral Portal** — 28 endpoints, all under `/api/`.

Every endpoint is protected. Authorisation is decided server-side on each request by looking up the caller's employee code in the `employees` table and, for dashboard endpoints, their role in the `users` table. Nothing sent by the browser influences the decision.

**Responses common to all endpoints**

| Code | Meaning |
|---|---|
| 401 | No identity, or an employee code not present in the `employees` table |
| 403 | A known employee with no dashboard account, or the wrong role for this action |

**Access levels used below**

| Level | Who |
|---|---|
| Any employee | Any DMRC employee found in `employees`. No dashboard account needed. |
| All HR roles | HR-OPS, HR-APP or SYS-ADMIN |
| Named roles | Only those listed |

---

## Phase 1 — referral portal

Open to all DMRC staff. No dashboard account required.

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/me/` | GET | Any employee | Who the caller is, and what they may see |
| `/api/portal/bootstrap/` | GET | Any employee | Cycle, departments and document rules the form needs |
| `/api/apply/` | GET, POST, PATCH | Any employee | Submit a referral; resubmit a corrected one |
| `/api/drafts/` | GET, POST, DELETE | Any employee | Server-side draft of a part-completed referral |
| `/api/drafts/document/` | POST, DELETE | Any employee | Attach or remove a document on a draft |
| `/api/documents/view/` | GET | Any employee | The only route to any stored document — role-checked, link expires after 10 minutes, every access written to the ledger |

## Phase 2 — HR dashboard

### Queue and applications

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/hr/queue/` | GET | All HR roles | The live application queue |
| `/api/hr/action/` | PATCH | All HR roles | Verify, reject, request correction, advance a stage |
| `/api/hr/documents/override/` | POST | All HR roles | Override a document verification decision |
| `/api/college-referrals/` | GET, POST, PATCH | All HR roles | Institutional intake, scheduling, completion and merge |

### Offer letters

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/offer-letters/issue/` | POST | **HR-APP** | Sign and issue, one application or many |
| `/api/offer-letters/file/` | GET | All HR roles | Signed PDF, or an unsigned Word copy |
| `/api/offer-letters/correction/` | POST | HR-OPS, SYS-ADMIN | Upload a corrected PDF |
| `/api/offer-letters/correction/` | PATCH | **HR-APP** | Approve or return a correction |
| `/api/offer-letters/handover/` | POST | HR-OPS, SYS-ADMIN | Confirm hard copies; the intern joins |

The Word copy carries no signature by design — it is downloaded routinely, and a signature inside a Word file can be lifted in three clicks. A corrected letter receives its signature when HR-APP approves it.

### Clearance and completion certificates

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/dmra-session/` | POST | HR-OPS, SYS-ADMIN | Schedule the Academy session. Set once — the candidate is told this date. |
| `/api/clearance/` | PATCH | HR-OPS, SYS-ADMIN | Save clearance progress as it arrives |
| `/api/clearance/` | POST | HR-OPS, SYS-ADMIN | Submit for review, or reject on an unsatisfactory evaluation |
| `/api/certificates/issue/` | POST | **HR-APP** | Sign and issue |
| `/api/certificates/issue/` | PATCH | **HR-APP** | Return the clearance to HR-OPS with a reason |
| `/api/certificates/file/` | GET | All HR roles | Signed PDF, or an unsigned Word copy |
| `/api/certificates/correction/` | POST, PATCH | **HR-APP** | Upload a corrected PDF and re-approve it |
| `/api/certificates/dispatch/` | POST | **HR-APP** | Send to the candidate and close the internship. Currently recorded as PENDING until the mail system exists. |

### Signatures

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/signatures/` | GET | All HR roles | Signature status |
| `/api/signatures/` | POST | **HR-APP** | Upload a new signature for approval |
| `/api/signatures/` | PATCH | **SYS-ADMIN** | Approve or reject a pending signature |
| `/api/signatures/image/` | GET | Owner or SYS-ADMIN | The image itself. The outer guard admits any HR role; the endpoint then narrows to the officer it belongs to and a SYS-ADMIN. Every access by anyone other than the owner is logged. |

Signature images are stored outside every served directory and never pass through the ordinary document viewer. A signature that can be downloaded is a signature that can be reused on anything.

### Audit

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/audit-ledger/` | GET | All HR roles | The audit ledger |

### Archives

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/hr/archives/` | GET | **SYS-ADMIN** | Applications in closed cycles. Filtered, sorted and paged server-side. |
| `/api/hr/archives/record/` | GET | **SYS-ADMIN** | One archived record in full — documents, requirements, timeline, academic detail |

### Administration

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/admin/iam/` | GET | **SYS-ADMIN** | Personnel directory; single employee lookup by code |
| `/api/admin/iam/` | POST | **SYS-ADMIN** | Grant a dashboard role to an existing employee |
| `/api/admin/iam/` | PATCH | **SYS-ADMIN** | Revoke or restore an account |
| `/api/admin/cycles/` | GET, POST, PATCH | **SYS-ADMIN** | Internship cycle configuration |
| `/api/admin/configs/` | GET, POST | **SYS-ADMIN** | Document types and portal configuration |
| `/api/admin/export/` | POST | All HR roles | Data export |

Provisioning takes only an employee code and a role. Name, designation and department are read from `employees`, never typed — the designation is printed under the signature on every offer letter that person signs, so it must come from the directory rather than from whatever an administrator entered months earlier. An unknown code is refused.

**Note:** `/api/admin/export/` is reachable by all three dashboard roles despite its path. If exports should be restricted to SYS-ADMIN, that is a one-line change.

---

## Characteristics

**No versioning.** Paths carry no `/v1/`. Acceptable while the only consumer is this application's own frontend; worth adding if other systems begin calling it.

**No rate limiting.** Nothing prevents a program calling an endpoint repeatedly. Same reasoning.

**No outbound calls.** The portal calls no external service. Everything it needs is in its own database and filesystem.

**Identity assumes a browser.** The model resolves a person from their intranet session. A program calling this API has no session and cannot be identified — that would need a service account or token, which does not exist today.
