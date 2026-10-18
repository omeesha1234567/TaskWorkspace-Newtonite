# Newtonite Task Tracker 🚀

> A production-grade, collaborative, multi-tenant operations task management web application built with Python and Django for the **Newtonite Software Engineering Challenge: Operations Under Pressure**.

![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-blue)
![Django](https://img.shields.io/badge/Django-6.0-green)
![Tests](https://img.shields.io/badge/Tests-61%20Passed%20(100%25)-success)
![Architecture](https://img.shields.io/badge/Architecture-Modular%20Monolith-indigo)
![Deployment](https://img.shields.io/badge/Deployment-Render%20Ready-brightgreen)

---

## 1. Project Overview

**Newtonite Task Tracker** is engineered to solve real-world high-pressure operations challenges:
- **Canonical Unified Document Storage**: All new document uploads—whether initiated from task creation, the task detail page, or the team shared library—create a single canonical `SharedDocument` record and a single physical stored file. Backward compatibility is seamlessly preserved for legacy `TaskAttachment` records.
- **In-App Only Team Invitations**: Completely in-app workflow with **zero outbound email delivery**. Invitations are targeted to registered Newtonite accounts, generate instant in-app notifications, and feature atomic POST-based accept/decline actions, expiration, revocation, and duplicate prevention.
- **Persistent Unread Audit Indicator**: Live red indicator dot on the Audit Log navigation item driven by an immutable per-user database read cursor (`UserActivityReadState`), scoped to accessible teams, isolated from the Updates center, and protected against false-read clearing on filtered views.
- **Prevent Lost Updates**: Multi-user optimistic concurrency control (OCC) prevents users from overwriting each other's edits with side-by-side diff conflict resolution.
- **Deduplicate Submissions**: Idempotency token architecture ensures network retries and double clicks never create duplicate tasks.
- **Team-Scoped RBAC & Anti-IDOR**: Strict team isolation guarantees users cannot access, view, or alter work items or documents from teams they do not belong to.
- **Enforced Workflow Lifecycles**: Backend state-machine validates all status progressions (`OPEN` &rarr; `IN_PROGRESS` &rarr; `RESOLVED` &rarr; `OPEN`).
- **Immutable Audit Logging**: Every state change, reassignment, priority shift, document upload, and membership change is recorded atomically.
- **Premium Editorial Visual Identity**: Warm ivory (`#FDFBF7`), sage (`#5C8571`), deep forest green (`#285741`), custom botanical vector emblem (`leaf_emblem.svg`), architectural isometric hero artwork (`cityscape_art.svg`), and full dark mode.

---

## 2. Technology Stack

- **Backend**: Python 3.14 / 3.12, Django 6.0 (Modular Monolith)
- **Database**: SQLite 3 (local development) / PostgreSQL (production Render via `DATABASE_URL` and `dj-database-url`)
- **Production Asset Serving**: WhiteNoise 6.12 (`CompressedManifestStaticFilesStorage`)
- **WSGI Production Server**: Gunicorn 21.2
- **Frontend**: Django Templates, Semantic HTML5, Vanilla CSS Design System (`app.css`), Vanilla JavaScript (`app.js`)
- **Typography**: Google Fonts (*Newsreader* editorial display serif, *Plus Jakarta Sans* UI, *Inter* tabular copy, *JetBrains Mono* code/version badges)
- **Testing**: Pytest & Django Test Framework (61 automated tests, 100% pass rate in ~2.2s, 74% coverage)
- **Continuous Integration**: GitHub Actions (`.github/workflows/test.yml`)

---

## 3. Quick Start (Windows Setup Guide)

### Step 1: System Checks
```powershell
py manage.py check
```

### Step 2: Run Database Migrations
```powershell
py manage.py migrate
```

### Step 3: Seed Showcase Demo Data (Idempotent)
Populates realistic showcase users, teams, tasks, invitations, notifications, and shared documents:
```powershell
py manage.py seed_demo_data
```

### Step 4: Run Automated Tests (61/61 Passing)
```powershell
# Native Django Test Runner
py manage.py test

# Pytest with Coverage
py -m pytest --cov=tasks --cov-report=term
```

### Step 5: Start Development Server
```powershell
py manage.py runserver 127.0.0.1:8000
```
Open **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)** in your browser.

---

## 4. Demo Accounts & Evaluator Credentials

All demonstration accounts share the password: `Password123!`

| Username | Role | Team Membership | Focus Area |
| :--- | :--- | :--- | :--- |
| **`alice`** | **Team Admin** | Core Platform | Team settings, member management, task creation, in-app invitations, shared document upload & deletion. |
| **`bob`** | **Team Manager** | Core Platform (Manager), Frontend (Member) | Multi-team management, task assignments, document library access. |
| **`charlie`** | **Team Member** | Core Platform (Member), Mobile Apps (Admin) | Contributor workflows; editing assigned tasks; deleting own documents. |
| **`diana`** | **Team Admin** | Frontend Engineering | Design lead, inviting members, managing frontend deliverables. |
| **`edward`** | **Team Manager** | Frontend Engineering | UI review, managing team task transitions. |
| **`fiona`** | **Team Member / Invitee** | Core Platform (Member), Pending invite to Frontend | Testing in-app invitation acceptance and multi-team collaboration. |
| **`george`** | **Isolated Member** | Operations Support | Testing team data isolation and anti-IDOR boundaries. |
| **`admin`** | **System Superuser** | Organization-wide | Password: `AdminPass123!`. Access to Django Admin at `/admin/`. |

---

## 5. Render Deployment Architecture

The application is fully pre-configured for automated continuous deployment on [Render](https://render.com):

### Build & Run Configuration
- **Build Command**: `./build.sh` (installs `requirements.txt`, runs `collectstatic`, and applies `migrate`)
- **Start Command**: `gunicorn config.wsgi:application`
- **Blueprint Manifest**: [`render.yaml`](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/render.yaml)

### Required Environment Variables on Render
| Variable | Value / Format | Purpose |
| :--- | :--- | :--- |
| `DATABASE_URL` | Auto-provided from Render PostgreSQL | Connected database URI |
| `SECRET_KEY` | Auto-generated or strong random secret | Django production cryptography |
| `DEBUG` | `False` | Disables debug mode in production |
| `ALLOWED_HOSTS` | `.onrender.com,your-domain.com` | Allowed host headers |
| `CSRF_TRUSTED_ORIGINS` | `https://*.onrender.com` | CSRF origin protection |
| `MEDIA_ROOT` | `/var/data/media` | Target mount for Render Persistent Disk |

> [!IMPORTANT]
> **Persistent Disk & Data Notice**:
> - **Storage Durability**: Render's free tier provides an ephemeral filesystem where disk changes are discarded across restarts. To ensure shared documents and attachments persist durably, `render.yaml` configures a **Starter web service** with a 1GB persistent disk mounted at `/var/data/media`.
> - **Database Distinction**: Local SQLite data and user accounts in `db.sqlite3` do not transfer to Render. Render deploys with a clean PostgreSQL instance. To seed demonstration data on Render, execute `python manage.py seed_demo_data` via Render's SSH/Shell console.

---

## 6. Project Documentation Sitemap

| Document | Purpose |
| :--- | :--- |
| **[PROJECT_CONTEXT.txt](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/PROJECT_CONTEXT.txt)** | Complete living architectural context, design tokens, data models, RBAC rules, Phase 1, Phase 2, and Final Pass audits. |
| **[PROJECT_ARCHITECTURE.md](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/PROJECT_ARCHITECTURE.md)** | System architecture, request lifecycles, and component diagrams. |
| **[DATABASE_ENGINEERING.md](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/DATABASE_ENGINEERING.md)** | Schema design, indexing, composite keys, ACID invariants, and OCC concurrency. |
| **[PERMISSIONS.md](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/PERMISSIONS.md)** | Scoped RBAC permissions matrix, privilege escalation prevention, and anti-IDOR policies. |
| **[ENGINEERING_DECISIONS.md](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/ENGINEERING_DECISIONS.md)** | Architecture Decision Records (ADRs) explaining technical trade-offs. |
| **[TESTING.md](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/TESTING.md)** | Automated testing strategy, 61 test descriptions, and verification reports. |
| **[KNOWN_LIMITATIONS.md](file:///d:/AIML%20Projects/omeesha/tasktrackernewtonite-main/tasktrackernewtonite-main/KNOWN_LIMITATIONS.md)** | Production scaling recommendations, storage guarantees, and roadmap. |
