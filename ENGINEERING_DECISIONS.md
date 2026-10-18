# Newtonite Task Tracker: Architecture Decision Records (ADR)

This document formalizes the significant software engineering, database, architectural, and design decisions adopted in the Newtonite Task Tracker codebase.

---

## Decision 1: Architecture Style — Modular Django Monolith with Server-Side Rendering

### 1. The Problem
The challenge mandates building a complete, cohesive, secure, and production-grade task tracking SaaS application that is easy to install, run, verify, and demonstrate on Windows without brittle dependency chains.

### 2. The Chosen Solution
A **Modular Django Monolith** utilizing Django's Model-View-Template (MVT) architecture with server-side rendered HTML, a clean domain service layer (`services.py`), a policy layer (`permissions.py`), and vanilla CSS/JS.

### 3. Alternatives Considered
- **Decoupled React / Next.js SPA with Django REST Framework (DRF)**:
  - *Drawback*: Requires running Node.js alongside Python, managing dual dev servers, handling CORS, JWT expiration, client-side state hydration, and multi-gigabyte `node_modules` folders.
- **Microservices Architecture**:
  - *Drawback*: Extreme operational complexity (RPCs, distributed transactions, service discovery) for a challenge task manager.

### 4. Why This Solution Is Appropriate
- Immediate local installation (`pip install django` and run).
- Zero build tools (no Webpack, Vite, or npm bundle build step required to run).
- Native CSRF protection, session management, and server-side validation.
- Sub-millisecond template rendering latency with minimal CPU overhead.

### 5. Trade-offs & Limitations
- Full-page navigation on some interactions (mitigated by instant server response times and the Post-Redirect-Get pattern).
- Dynamic client-side features require targeted vanilla JavaScript (implemented cleanly in `app.js`).

---

## Decision 2: Concurrency Management — Optimistic Concurrency Control (OCC)

### 1. The Problem
Multiple users simultaneously editing the same task cause "lost updates" (User A saves changes, User B overwrites them seconds later without knowing User A's changes ever happened).

### 2. The Chosen Solution
**Optimistic Concurrency Control (OCC)** using a dedicated integer `version` field on the `Task` model, verified via an atomic conditional SQL update:
```sql
UPDATE tasks_task
SET ..., version = version + 1
WHERE id = %s AND version = %s;
```
If the number of affected rows is 0, a concurrent edit has occurred. The system raises `StaleUpdateError` and presents a side-by-side reconciliation diff.

### 3. Alternatives Considered
- **Pessimistic Locking (`SELECT FOR UPDATE`)**:
  - *Drawback*: Locks the database row while the user has the page open in their browser. If a user walks away for lunch, nobody else can edit the task. Also causes database deadlocks and holds connections open.
- **Last-Write-Wins (LWW)**:
  - *Drawback*: Silently discards data; unacceptable for a professional engineering team tracker.

### 4. Why This Solution Is Appropriate
- Non-blocking: Users never wait for locks while composing descriptions.
- Completely safe against race conditions.
- Works identically on SQLite, PostgreSQL, and MySQL.

### 5. Trade-offs & Limitations
- If two users submit edits in the same second, the second user receives a conflict alert and must re-verify their inputs against the newest state.

---

## Decision 3: Idempotency Protection — Database-Enforced Idempotency Key

### 1. The Problem
Users accidentally double-clicking submit buttons or network timeouts retried by HTTP clients cause duplicate task creation.

### 2. The Chosen Solution
An **Idempotency Key Architecture**:
1. When rendering the task creation form, a unique UUID token is generated and stored in a hidden field.
2. On submission, `TaskService.create_task()` checks `IdempotencyRecord` inside an atomic transaction.
3. If the key exists for the user and action, the previously created task is returned.
4. Database unique constraint on `(user_id, key, action)` guarantees that even concurrent duplicate submissions cannot insert duplicate tasks.

### 3. Alternatives Considered
- **Client-Side Button Disabling (`disabled=true`)**:
  - *Drawback*: Fails if JavaScript is slow, if the user presses enter twice, or if network retries originate from an automated client or API script. Disabling a button is UX convenience, not security.
- **In-Memory Cache (e.g. Redis cache)**:
  - *Drawback*: Cache keys are lost if Redis restarts; introduces another external server dependency.

### 4. Why This Solution Is Appropriate
- ACID compliant and persistent across server restarts.
- Zero extra dependencies.

---

## Decision 4: Multi-Tenant Team Isolation — Scoped Queryset Layer

### 1. The Problem
Preventing users from accessing, viewing, or modifying tasks belonging to other teams (Insecure Direct Object Reference - IDOR).

### 2. The Chosen Solution
Centralized **Queryset Scoping** in `tasks/permissions.py`:
`get_accessible_tasks_qs(user)` filters all task queries by `team__memberships__user=user`. Views and forms exclusively build on top of these scoped querysets.

### 3. Alternatives Considered
- **Separate SQLite Database per Team**:
  - *Drawback*: Prevents cross-team reporting, complicates system-wide migrations, and prevents users belonging to multiple teams from viewing a unified "My Tasks" queue.
- **Ad-hoc checks in every view**:
  - *Drawback*: Error-prone; easy for a developer to forget an `if` condition in a new endpoint.

### 4. Why This Solution Is Appropriate
- Declarative and reusable across list views, search filters, and detail endpoints.
- High performance through composite indexes.

---

## Decision 5: Task Deletion — Soft Archiving with Immutable Audit Timeline

### 1. The Problem
Accidental task deletions destroy project history, metrics, and accountability.

### 2. The Chosen Solution
**Soft Archiving (`is_archived = True`, `archived_at = timestamp`)**:
Archived tasks are excluded from active boards, active counters, and searches by default, but remain fully inspectable in audit logs and can be restored by Team Admins or Managers.

### 3. Alternatives Considered
- **Physical Hard Deletion (`DELETE FROM tasks_task`)**:
  - *Drawback*: Cascades or nullifies related records, permanently destroying historical audit trails.

### 4. Why This Solution Is Appropriate
- Preserves referential integrity for metrics and audit compliance.
- Allows immediate recovery from accidental deletions.

---

## Decision 6: Shared Document Storage — Internal Logical Hierarchy & Server-Authorized Streaming

### 1. The Problem
Teams need a shared document repository with team-wide and task-specific organization. In addition, unauthorized public media file exposure must be prevented.

### 2. The Chosen Solution
- **Logical Folder Partitions**: Physical storage path organized by `shared_documents/team_<id>/general/` and `shared_documents/team_<id>/task_<id>/` with collision-resistant UUID-prefixed filenames (`<slug>_<uuid8>.<ext>`).
- **Server-Authorized Download Endpoint**: The direct media URL is never exposed to untrusted clients. Downloads are served via `/documents/<id>/download/`, which evaluates server-side team membership before streaming via `FileResponse(as_attachment=True)`.
- **OneDrive Integration Avoidance**: Deferred external Microsoft Graph integration due to absent Azure credentials, ensuring zero mock/fake external claims while keeping the internal storage backend cleanly pluggable.

### 3. Alternatives Considered
- **Direct Web Server Static Serving (`/media/...`)**:
  - *Drawback*: Bypasses Django authentication and permissions. Anyone with the URL can download sensitive documents.
- **Mock OneDrive Integration**:
  - *Drawback*: Fake credentials and simulated cloud sync violate engineering integrity.

---

## Decision 7: Audit Read State Tracking — Immutable Events with Per-User Read Cursors

### 1. The Problem
Users need a clear indicator (red dot) when new activity occurs in their teams, without modifying historical audit events. Furthermore, viewing filtered activity or paginated sub-views must never falsely advance the global read cursor beyond actually viewed events.

### 2. The Chosen Solution
A separate **`UserActivityReadState`** model storing `(user_id, last_read_event_id)`:
- The audit log (`ActivityEvent`) remains 100% immutable.
- Checking for unread events runs an efficient `id__gt=last_read_event_id` query across accessible teams.
- Visiting `/activity/` advances `last_read_event_id` only up to the maximum event actually displayed on that page (`max_event_id`). If filters are applied, the cursor is not falsely advanced beyond visible items.

### 3. Alternatives Considered
- **Boolean `is_read` Flag on `ActivityEvent`**:
  - *Drawback*: Activity events are shared across all team members. If User A reads the event, it would mark it read for User B, or require mutating audit rows.
- **Local Storage Flag**:
  - *Drawback*: Fails across different devices, browsers, and sessions.

---

## Decision 8: In-App Only Team Invitations — Zero Outbound Email Delivery

### 1. The Problem
Operations teams need a reliable, fully self-contained workflow for team invitations that does not depend on external SMTP servers, third-party transactional mail APIs, or internet delivery latencies. Email must serve strictly as a registered account identifier, not as a transport mechanism.

### 2. The Chosen Solution
**In-App Invitation Workflow**:
- `InvitationService.create_invitation` strictly resolves the invited email to a pre-existing registered Newtonite `User` record using normalized, case-insensitive comparison (`email__iexact`).
- If no user account matches the email address, creation is rejected with a clear validation error informing the Admin that the user must register in Newtonite first. Zero outbound emails are sent.
- Active invitations create a database-backed `WorkspaceInvitation` and an instant in-app `InAppNotification` with direct action links.
- Recipient accepts or declines via POST requests protected by CSRF tokens. Acceptance atomically provisions `TeamMembership` and updates status to `ACCEPTED`.
- The Django email subsystem remains intact for unrelated features (e.g. password resets), but the invitation lifecycle never invokes `send_mail`.

### 3. Alternatives Considered
- **Mandatory SMTP Outbound Email**:
  - *Drawback*: Fails without active SMTP credentials, breaks automated offline testing, and leaks internal team invitations across unverified external networks.
- **Token-in-URL Anonymous Acceptance**:
  - *Drawback*: Vulnerable to link interception, email scanner bots pre-fetching accept links, and missing authentication context.

---

## Decision 9: Canonical Unified Document Storage with Legacy Attachment Compatibility

### 1. The Problem
The codebase previously contained two separate file models: `TaskAttachment` (scoped to a task) and `SharedDocument` (scoped to a team, with an optional task link). Having multiple upload entry points risked duplicating database records, duplicating physical disk storage, and creating conflicting document views between task details and the shared library.

### 2. The Chosen Solution
**Unified Canonical Path**:
- All NEW uploads—whether originating from the task creation form, the task detail page, or the team shared library—are processed through `SharedDocumentService.upload_document` and saved as `SharedDocument` records.
- Exactly one canonical database record and one physical stored file are created per upload.
- The task detail page and team shared library present unified views of the same underlying record.
- **Legacy Compatibility**: The legacy `TaskAttachment` model, its existing database records, authorized download endpoints (`/tasks/<id>/attachment/<att_id>/download/`), and deletion endpoints are preserved intact. The task detail view queries both canonical `shared_documents` and legacy `attachments`, ensuring old data remains fully functional without risking duplicate physical files or breaking historical links.

### 3. Alternatives Considered
- **Destructive Database Migration to Merge Models**:
  - *Drawback*: Risks data loss, file path corruption, and breaks existing references in running deployments.
- **Dual-Writing to Both Models**:
  - *Drawback*: Creates duplicate records and doubles physical disk consumption for every uploaded file.
