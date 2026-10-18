# Newtonite Task Tracker: Known Limitations & Production Roadmap

This document transparently records architectural trade-offs, environmental constraints, storage guarantees, and future expansion paths for the Newtonite Task Tracker.

---

## 1. Current Environmental & Architectural Limitations

### 1.1 Database Concurrency & Production PostgreSQL
- **Observation**: Newtonite supports both local SQLite 3 (with Write-Ahead Logging and optimistic concurrency control) and PostgreSQL via `DATABASE_URL` (using `dj-database-url`).
- **Limitation**: While SQLite supports unlimited concurrent readers, only one database connection can write at any given millisecond. High concurrent write throughput may encounter lock contention.
- **Production Recommendation**: When deploying to production (such as Render), configure a PostgreSQL database via `DATABASE_URL`. The codebase automatically detects `DATABASE_URL` and routes all transactions and querysets to PostgreSQL seamlessly.
- **Data Transfer**: Local SQLite database rows (`db.sqlite3`) do not automatically transfer to remote cloud PostgreSQL instances. For production demonstration environments, use `python manage.py seed_demo_data` via Render's SSH/Shell console to seed showcase accounts and teams.

### 1.2 File Storage Durability on Render
- **Observation**: Newtonite implements both legacy `TaskAttachment` and a unified `SharedDocument` library. Uploads are stored on the filesystem path defined by `MEDIA_ROOT`.
- **Limitation**: On cloud platforms with ephemeral containers (such as Render's Free web services), any files written to the local container filesystem are discarded upon redeployment or dyno restart.
- **Production Storage Requirements**:
  1. **Render Paid Plan Requirement**: Render Persistent Disks are not supported on Free web services. Durability requires a **Starter web service** ($7/mo) with an attached 1GB Persistent Disk ($0.25/GB/mo) mounted at `/var/data/media` and configured via `MEDIA_ROOT=/var/data/media`.
  2. **Cloud Object Storage**: For horizontally auto-scaled multi-instance deployments, integrate `django-storages` with an S3-compatible bucket (AWS S3, Cloudflare R2, Google Cloud Storage).

### 1.3 Team Invitations: Strictly In-App Workflow
- **Observation**: Team invitations operate 100% within the Newtonite web interface.
- **Specification**: Zero outbound emails are dispatched during invitation creation, acceptance, decline, or revocation. The invitee's email is utilized strictly as a lookup key for pre-existing registered Newtonite accounts.
- **Unregistered Users**: Inviting an unregistered email address displays an honest validation message indicating that the candidate must register an account first. No email delivery is attempted or required.
- **Email Backend Scope**: Django's email configuration is strictly reserved for user-initiated account recovery (e.g. password resets), and is not a prerequisite for team collaboration.

### 1.4 Microsoft OneDrive / External Cloud Storage Status
- **Observation**: The shared document library is designed as a first-class internal Django document repository with logical team and task folder structures.
- **Status**: External Microsoft OneDrive / Microsoft Graph integration is intentionally absent because no verified Microsoft Azure AD application registrations, client IDs, client secrets, or tenant credentials exist in the environment. A fake or mock OneDrive integration would compromise security and truthfulness.
- **Future Integration Path**: Because the document library uses Django's storage abstraction and a clean `SharedDocumentService` layer, integrating an external OAuth2 OneDrive backend in the future requires only swapping the storage provider and token handshake without altering the user-facing document library views or RBAC model.

### 1.5 Real-Time WebSockets vs Polling
- **Observation**: State transitions and concurrency conflicts are evaluated deterministically when actions are submitted.
- **Limitation**: If User A updates a task or uploads a document, User B's open browser screen will not update live until User B navigates or refreshes.
- **Production Recommendation**: Introduce Django Channels and Redis to stream live WebSocket push events for real-time task card updates and instant unread audit badges.

---

## 2. Security Considerations & Production Checklist

- **Secret Key**: `SECRET_KEY` in `config/settings.py` defaults to a development secret if unset. In production, provide a cryptographically random string via `DJANGO_SECRET_KEY` or Render's secret generator.
- **Debug Mode**: `DEBUG = True` is default for local development. Set `DEBUG=False` in production.
- **Allowed Hosts & CSRF**: Provide exact hostnames in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (e.g. `https://your-app.onrender.com`).
- **HTTPS & Secure Cookies**: When `DEBUG=False`, ensure HTTPS is enabled with `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, and `SECURE_SSL_REDIRECT = True`.
