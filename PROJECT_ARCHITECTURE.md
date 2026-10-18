# Newtonite Task Tracker: System Architecture & Design Specification

## 1. Executive Summary

**Newtonite Task Tracker** is a secure, collaborative, multi-tenant task management web application engineered with Python and Django. Designed specifically to satisfy the enterprise requirements of the Newtonite Software Engineering Challenge, it provides robust task tracking, workflow lifecycle automation, role-based access control (RBAC), team data isolation, optimistic concurrency protection, and an immutable audit log.

---

## 2. Problem Statement & Target Audience

### 2.1 The Problem
In modern engineering and operations teams, basic task management tools often suffer from:
1. **Lost Updates & Race Conditions**: Multiple team members simultaneously editing the same task overwrite each other's work silently (stale updates).
2. **Double Submissions**: Network latency and user retries lead to duplicate task entries.
3. **Insecure Direct Object References (IDOR)**: Users accessing or modifying work items of unauthorized teams by altering URL parameters.
4. **Lack of Auditability**: State and priority transitions occur without recorded accountability or historical diffs.
5. **Over-Engineered Frontend Complexity**: Complex client-side frameworks (e.g. React/Next.js) introducing bloated bundle sizes, brittle hydration states, and unnecessary maintenance overhead for standard SaaS task workflows.

### 2.2 Target Audience
- **Engineering Managers & Tech Leads**: Requiring real-time visibility into team velocity, active workloads, and overdue milestones without data leaks across functional departments.
- **Developers & Team Members**: Managing daily assignments, progressing tasks through verified workflow states, and reviewing task histories.
- **System Administrators**: Maintaining organization-wide security, user onboarding, and workspace partitioning.

---

## 3. User Roles & The Multi-Team Model

Newtonite uses a **scoped Role-Based Access Control (RBAC)** architecture where permissions are evaluated per team workspace:

| Role | Scope | Key Permissions |
| :--- | :--- | :--- |
| **System Admin** | Global (Superuser/Staff) | Full access across all teams, users, settings, and Django admin. |
| **Team Admin** | Team Workspace | Full control over the team: edit team settings, invite/remove members, promote/demote member roles, create/edit/archive/restore any task in the team. Cannot demote or remove the sole admin of a team. |
| **Team Manager** | Team Workspace | Operational lead: create tasks, edit all tasks in the team, assign tasks to members, change priorities, progress workflows, archive completed tasks. Cannot modify team settings or member roles. |
| **Team Member** | Team Workspace | Contributor: view team tasks and activity feed, create tasks, edit tasks assigned to or created by them, transition status of assigned tasks. Cannot assign tasks to others or modify team structure. |

---

## 4. Architectural Overview & Component Diagram

Newtonite is structured as a **Modular Django Monolith** adhering to the Model-View-Template (MVT) pattern, augmented with a dedicated **Domain Service Layer** (`services.py`) and **Authorization Policy Layer** (`permissions.py`).

### 4.1 Mermaid Architecture Diagram

```mermaid
graph TD
    Client["Browser Client (HTML5 / Vanilla CSS / Vanilla JS / Chart.js)"]
    
    subgraph Django_Application ["Django Application Core (config & tasks)"]
        Router["URL Dispatcher (config/urls.py & tasks/urls.py)"]
        AuthMiddleware["Security & Auth Middleware (Session, CSRF, Authentication)"]
        
        subgraph Presentation_Layer ["Presentation Layer"]
            Views["Views (tasks/views.py)"]
            Forms["Forms & Validation (tasks/forms.py)"]
            Templates["Django Templates (Jinja-style Server Rendered)"]
        end
        
        subgraph Policy_Layer ["Policy & Security Layer"]
            Permissions["Permissions & Queryset Scoping (tasks/permissions.py)"]
        end
        
        subgraph Service_Layer ["Domain Service Layer (tasks/services.py)"]
            TaskService["TaskService (Workflows, Concurrency, Idempotency)"]
            TeamService["TeamService (Memberships, Roles, Anti-Escalation)"]
            DashboardService["DashboardService (Optimized Aggregations)"]
        end
        
        subgraph Data_Layer ["Data & ORM Layer (tasks/models.py)"]
            Models["Django ORM Models (Team, TeamMembership, Task, ActivityEvent, IdempotencyRecord)"]
        end
    end
    
    subgraph Storage ["Database Engine"]
        SQLite[("SQLite 3 Database (WAL Mode, Composite Indexes, Unique Constraints)")]
    end

    Client -->|HTTP Request / Session Cookies| Router
    Router --> AuthMiddleware
    AuthMiddleware --> Views
    Views --> Forms
    Views --> Permissions
    Views --> Service_Layer
    Service_Layer --> Models
    Models -->|SQL Queries & Transactions| SQLite
    Views --> Templates
    Templates -->|Rendered HTML + JSON Data| Client
```

---

## 5. Domain Model Relationships & Entity Relationship Diagram

The data model connects users, teams, memberships, tasks, and audit logs.

### 5.1 Mermaid Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    User ||--o{ TeamMembership : "participates in"
    Team ||--o{ TeamMembership : "has members"
    Team ||--o{ Task : "owns"
    User ||--o{ Task : "assigned to"
    User ||--o{ Task : "created by"
    Team ||--o{ ActivityEvent : "scoped to"
    Task ||--o{ ActivityEvent : "subject of"
    User ||--o{ ActivityEvent : "acted by"
    User ||--o{ IdempotencyRecord : "initiates"
    Task ||--o| IdempotencyRecord : "generated by"

    User {
        int id PK
        string username UK
        string email
        string first_name
        string last_name
        string password
    }

    Team {
        int id PK
        string name UK
        string description
        datetime created_at
        datetime updated_at
    }

    TeamMembership {
        int id PK
        int user_id FK
        int team_id FK
        string role "ADMIN | MANAGER | MEMBER"
        datetime created_at
    }

    Task {
        int id PK
        string title
        string description
        string status "OPEN | IN_PROGRESS | RESOLVED"
        string priority "LOW | MEDIUM | HIGH | URGENT"
        int team_id FK
        int assignee_id FK "nullable"
        int creator_id FK
        date due_date "nullable"
        boolean is_archived
        datetime archived_at "nullable"
        int version "Optimistic Locking"
        datetime created_at
        datetime updated_at
    }

    ActivityEvent {
        int id PK
        int actor_id FK "nullable"
        int team_id FK
        int task_id FK "nullable"
        string event_type
        string details
        json previous_state
        json new_state
        datetime created_at
    }

    IdempotencyRecord {
        int id PK
        string key
        int user_id FK
        string action
        int response_code
        int task_id FK "nullable"
        datetime created_at
    }
```

---

## 6. How the Frontend Communicates with Django

1. **Standard Form Submissions & PRG Pattern**:
   Forms submit standard `application/x-www-form-urlencoded` payloads over POST protected by Django CSRF tokens. Views implement the **Post/Redirect/Get (PRG)** pattern to eliminate accidental form re-submissions when reloading pages.
2. **Idempotency Keys**:
   When a user opens the Task Creation screen, an idempotency UUID token is embedded into the form. If an idempotent request is retried (or double-clicked), the backend detects the token, returns the existing resource, and prevents duplicate records.
3. **Asynchronous Dropdown Hydration (`/api/teams/<id>/members/`)**:
   On the task creation screen, choosing a team triggers a lightweight vanilla JavaScript `fetch()` call to retrieve members belonging strictly to that team. This prevents users from picking invalid assignees on the client before submission.
4. **Interactive Analytics Visualizations**:
   The dashboard injects structured JSON metrics calculated on the server directly into DOM attributes and initializes lightweight **Chart.js** instances (Doughnut, Bar, and Line charts). Chart segments are interactive and link directly to filtered task lists.

---

## 7. How Django Interacts with the Database

1. **Query Optimization & Anti-N+1 Protection**:
   - `select_related('team', 'assignee', 'creator')`: Performs SQL `INNER JOIN` / `LEFT OUTER JOIN` in a single query when fetching task lists and detail views.
   - `prefetch_related('memberships__user')`: Pre-fetches team rosters efficiently in two queries rather than querying per row.
   - Database Aggregation: The dashboard computes KPIs using SQL `Count('id')` aggregations grouped by status and priority, never loading full object lists into Python memory for counting.
2. **Indexing Strategy**:
   - Composite index on `(team, is_archived, status)` accelerates team board queries.
   - Composite index on `(team, is_archived, priority)` optimizes urgency-based filtering.
   - Index on `(due_date)` accelerates overdue task detection.
   - Index on `(created_at)` powers chronological timelines.

---

## 8. How Permissions & Data Isolation are Enforced

1. **Queryset Scoping (Defense in Depth)**:
   Views never query `Task.objects.all()` directly. Instead, they invoke `get_accessible_tasks_qs(request.user)`, which applies:
   ```python
   Task.objects.filter(team__memberships__user=request.user)
   ```
   This prevents **Insecure Direct Object References (IDOR)** even if an attacker manipulates the task ID in the URL.
2. **Backend Action Guards**:
   Every state modification endpoint explicitly checks permissions via `permissions.py`:
   - `can_view_task(user, task)`
   - `can_edit_task(user, task)`
   - `can_change_task_status(user, task)`
   - `can_archive_task(user, task)`
   - `can_manage_team(user, team)`
3. **Sole Admin Protection**:
   A team administrator cannot demote or remove themselves if they are the last administrator of the team, preventing orphaned workspaces.

---

## 9. Transactions, Data Integrity & Concurrency

1. **ACID Transaction Boundaries**:
   All multi-step state alterations (e.g., task creation + audit logging, status update + version increment + audit logging, membership removal + task unassignment) are wrapped in `transaction.atomic()`. If any step fails or raises an unhandled exception, the entire operation is rolled back, preventing orphaned records.
2. **Optimistic Concurrency Control (Stale-Update Protection)**:
   Every task possesses an integer `version` field. During updates, the backend executes a conditional SQL update:
   ```sql
   UPDATE tasks_task
   SET title = %s, description = %s, status = %s, priority = %s, version = version + 1
   WHERE id = %s AND version = %s;
   ```
   If 0 rows were updated, a concurrent request modified the task first. A `StaleUpdateError` is raised, HTTP 409 conflict handling is invoked, and the user is shown a diff between their changes and the latest database record.

---

## 10. Existing Code vs Newly Implemented Functionality

| Component | Existing Initial State | Newly Implemented Enterprise Solution |
| :--- | :--- | :--- |
| **`tasks/models.py`** | Baseline domain models | Complete schema including `SharedDocument` (canonical uploads & team/task folders), `UserActivityReadState` (per-user audit cursor), `WorkspaceInvitation` (in-app only), and legacy `TaskAttachment`. |
| **`tasks/services.py`** | Basic TaskService & TeamService | Comprehensive domain service layer including `SharedDocumentService`, `AuditTrackingService`, and `InvitationService` (strictly in-app, zero email delivery). |
| **`tasks/permissions.py`** | Basic task and team permissions | Full RBAC including shared document policies (admin/manager full deletion, member self-deletion, non-member rejection), invitation issuance, and IDOR protection. |
| **`tasks/views.py`** | Basic task & team views | Full views for unified shared document uploads, folder browsing, streaming downloads, deletion, in-app invitation workflows, and activity read state. |
| **`tasks/forms.py`** | Basic forms | Added `SharedDocumentUploadForm` with 25 MiB validation, dangerous extension blocking, and task-team isolation. |
| **`tasks/tests.py`** | 36 baseline tests | 61 comprehensive automated tests (100% pass rate in ~2.2s) covering unified uploads, in-app invitations, audit tracking, concurrency, and RBAC. |
| **UI Templates & CSS** | Baseline templates | Premium minimalist SaaS redesign with dark mode, unified task document card (`detail.html`), document library UI (`team_library.html`), and pulsing unread audit dot. |
| **Deployment** | Local SQLite only | Full Render compatibility: `requirements.txt`, `build.sh`, `render.yaml`, WhiteNoise static asset pipeline, persistent disk media storage, and PostgreSQL auto-detection. |

---

## 11. Final Pass Architecture Extensions

### 11.1 Canonical Unified Document Storage & Backward Compatibility
- **Canonical Model**: All new uploads across the application (task creation, task detail, and team shared library) write to `SharedDocument`.
- **Zero Duplicate Disk Storage**: Exactly one database record and one physical stored file are created per upload.
- **Legacy Compatibility**: Historical `TaskAttachment` records remain fully accessible for authorized download and deletion through their dedicated endpoints. The task detail view queries both canonical documents and legacy attachments into a unified presentation.
- **Storage Path**: `shared_documents/team_<id>/general/<slug>_<uuid8>.<ext>` and `shared_documents/team_<id>/task_<id>/<slug>_<uuid8>.<ext>`.
- **Security**: Direct public media URLs are bypassed; all document downloads are streamed through an authorized endpoint (`/documents/<id>/download/`) verifying current team membership on the server.
- **Deletion**: Deleting a `SharedDocument` atomically removes both the database record and unlinks the physical file from storage.

### 11.2 In-App Only Team Invitation Architecture
- **Zero Outbound Email**: Invitations operate 100% within the Newtonite web application. No external SMTP or email service is required or invoked (`len(mail.outbox) == 0`).
- **Account Lookup**: The recipient's email is used strictly as an identifier for pre-existing registered Newtonite user accounts (`email__iexact`). Unregistered emails display an honest validation error.
- **Persistent In-App Delivery**: Active invitations generate database-backed `WorkspaceInvitation` records and immediate `InAppNotification` items.
- **Atomic State Transitions**: Recipient accepts or declines via POST requests protected with CSRF tokens. Acceptance atomically provisions `TeamMembership` and marks the invitation `ACCEPTED`.

### 11.3 Audit Read Tracking Architecture
- **Read Cursor**: `UserActivityReadState` maintains `last_read_event_id` per user.
- **Filter-Aware Updates**: Visiting `/activity/` advances the cursor only up to the maximum event actually rendered on that page (`max_event_id`), preventing filtered views from falsely clearing unread badges for unseen events.
- **Context Processor**: `has_unread_audit` evaluates efficiently via `.exists()` scoped to teams the user belongs to, preventing N+1 queries.
- **UI Indicator**: High-visibility pulsing red dot badge on the navigation link, cleared upon visiting `/activity/`.


