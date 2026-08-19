# DMRC Intern Referral System & HR Command Center

## Project Overview
This repository contains the source code, API architecture, and database schema for the official Delhi Metro Rail Corporation (DMRC) Intern Referral Portal. 

Designed exclusively for deployment on the DMRC Intranet, this system allows authorized DMRC employees to formally refer candidates for internships and provides the HR department with a centralized Command Center to manage verification, logistics, and document clearance.

**Tech Stack:**
* **Frontend:** Decoupled architecture using Alpine.js (Reactive State Machine) and Bootstrap 5.
* **Backend:** Django REST Framework (Python).
* **Database:** Highly normalized TiDB/MySQL 5 design scaled for enterprise transaction loads.

---

## Current System State

### Phase-1: Employee Referrer Portal
* **Core Files:** `app.js`, `index.html`
* **Functionality:** Reactive multi-step application wizard for DMRC employees. Includes real-time capacity matrix checks, dynamic department routing, and a dashboard for employees to track the live HR status of their referred candidates, withdraw applications, or resume saved drafts.
* **Data Handling:** Secure multi-part form data parsing, including strict 2MB validation limits for physical document vaults (Aadhaar, LORs, College IDs, Signatures).

### Phase-2: HR Command Center
* **Core Files:** `hr_app.js`, `hr_dashboard.html`, `styles.css`
* **Functionality:** Comprehensive Command Center for HR operators to process the referral queue.
  * Maker-Checker workflows (Approve, Reject, Fix Joining, Process No-Show).
  * Logistics Allotment (Department/Sub-Department assignment and DOJ scheduling).
  * Immutable Audit Ledger tracking every state change.
  * SYS-ADMIN Control Center for managing internship cycles, master quotas, and User Access Management (IAM).
  * Direct parallel routing for Institutional (College) referrals.

---

## IT Team Deployment Guide (Local to Production)

To migrate this system from the local development environment to the live DMRC Intranet servers, the IT Operations team must execute the following infrastructure configurations:

### 1. Database Timezone & Timestamp Configuration (Crucial)
The local development codebase contains a manual `timedelta` offset in `views.py` used for local testing between disparate system clocks. **This must be removed.**
* **Database Level:** Configure the production TiDB/MySQL database to store all timestamps strictly in **UTC**.
* **Django Settings:** In `settings.py`, configure Django to handle real-time timezone translation for the Indian server environment:
  ```python
  TIME_ZONE = 'Asia/Kolkata'
  USE_TZ = True