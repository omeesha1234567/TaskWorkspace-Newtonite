# Newtonite Task Tracker: Permissions & Authorization Specification

## 1. Overview & Security Model

Newtonite implements a **multi-tenant, team-scoped Role-Based Access Control (RBAC)** architecture. 

In Newtonite:
- **Authentication** verifies *identity* ("Who are you?"). Handled by Django's `auth` framework with secure password hashing.
- **Authorization** governs *privileges* ("What actions are you permitted to execute on this specific resource?"). Handled by `tasks/permissions.py` and enforced on every backend view and service method.

A user may belong to multiple teams with distinct roles in each. For instance, a user can be an `ADMIN` in the "Frontend Team" while being an ordinary `MEMBER` in the "Core Platform Team".

---

## 2. Complete Permission Matrix

| Operation / Capability | System Admin (Superuser) | Team Admin | Team Manager | Team Member | Non-Member / Anonymous |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **View Team Dashboard & Analytics** | Allowed | Allowed | Allowed | Allowed | Denied (403/Redirect) |
| **View Team Tasks** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Create Task in Team** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Edit Any Task in Team** | Allowed | Allowed | Allowed | Denied | Denied (403) |
| **Edit Assigned / Created Tasks** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Progress Task Status (Workflow)** | Allowed | Allowed | Allowed | If Assigned/Creator | Denied (403) |
| **Change Task Priority** | Allowed | Allowed | Allowed | Denied | Denied (403) |
| **Assign / Reassign Tasks** | Allowed | Allowed | Allowed | Denied | Denied (403) |
| **Archive / Restore Tasks** | Allowed | Allowed | Allowed | Denied | Denied (403) |
| **Permanently Delete Task** | Allowed | Allowed | Denied | Denied | Denied (403) |
| **View Audit / Activity History** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Edit Team Settings (Name/Desc)** | Allowed | Allowed | Denied | Denied | Denied (403) |
| **Create In-App Invitation** | Allowed | Allowed | Denied | Denied | Denied (403) |
| **Revoke Team Invitation** | Allowed | Allowed | Denied | Denied | Denied (403) |
| **Accept/Decline Own Invitation** | Allowed | Allowed | Allowed | Allowed (If Invitee) | Denied (403) |
| **Change Member Roles** | Allowed | Allowed | Denied | Denied | Denied (403) |
| **Remove Member from Team** | Allowed | Allowed | Denied | Self-Leave Only | Denied (403) |
| **Create New Team Workspace** | Allowed | Allowed | Allowed | Allowed | Denied (Redirect) |
| **View Shared Documents Library** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Upload Shared Document (Any entry point)** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Download Shared Document / Attachment** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Delete Own Shared Document / Attachment** | Allowed | Allowed | Allowed | Allowed | Denied (403) |
| **Delete Any Shared Document in Team** | Allowed | Allowed | Allowed | Denied | Denied (403) |

---

## 3. Privilege Escalation Defenses & Security Invariants

### 3.1 Protection of Sole Administrator
A critical failure mode in multi-tenant workspaces is the accidental or malicious removal of the last remaining administrator, leaving the workspace orphaned and unmanageable.

Newtonite guards this in `can_change_member_role()` and `can_remove_member()`:
```python
if target_membership.role == TeamRole.ADMIN:
    admin_count = TeamMembership.objects.filter(
        team=target_membership.team,
        role=TeamRole.ADMIN
    ).count()
    if admin_count <= 1:
        return False # Demotion or removal blocked!
```

### 3.2 Anti-IDOR (Insecure Direct Object Reference) Protection
Endpoints taking an object ID in the URL (e.g. `/tasks/42/edit/`, `/teams/5/members/2/role/`, `/documents/12/download/`) do NOT perform naive `Model.objects.get(pk=pk)` lookups.

Instead, they enforce ownership scoping:
```python
task = get_object_or_404(
    Task.objects.select_related('team', 'assignee', 'creator'),
    pk=pk
)
if not can_edit_task(request.user, task):
    raise PermissionDenied("You do not have permission to edit this task.")
```
If an unauthorized user tampers with the URL to view or edit another team's task, Django raises a `PermissionDenied` exception and renders a clean HTTP 403 page.

### 3.3 Assignee Team-Membership Invariant
A task cannot be assigned to a user who does not belong to that task's team workspace. This invariant is enforced both in the model `clean()` method and in `TaskService.create_task()` / `TaskService.update_task()`:
```python
if assignee and not TeamMembership.objects.filter(team=team, user=assignee).exists():
    raise ValidationError({'assignee': f"User '{assignee.username}' is not a member of '{team.name}'."})
```
Furthermore, the task creation interface dynamically queries `/api/teams/<team_id>/members/` to asynchronously populate only valid team members into the assignee dropdown.

### 3.4 Shared Document Authorization & Canonical Upload Invariant
Shared documents are strictly team-scoped:
- **Unified Entry Points**: Uploading during task creation, uploading from the task detail page, and uploading from the team library all route through `SharedDocumentService.upload_document` and enforce identical team membership validation.
- **Cross-Team Isolation**: Non-members cannot list, search, view, download, or delete documents belonging to another team.
- **Task-Team Consistency**: A task-specific document must belong to the exact same team as the task (`task.team_id == team.id`). Attempting to associate a document with a task from a different team is rejected with `ValidationError`.
- **Deletion Boundaries**: Ordinary members can only delete documents they uploaded (`document.uploader == user`). Team Admins and Team Managers can delete any document within their team workspace.
- **Immediate Revocation**: Removing a user from a team immediately denies access to that team's document library and revokes their ability to download files, even if they possess the direct download URL.
- **Legacy Compatibility**: Legacy `TaskAttachment` records enforce identical authorization checks on download and deletion.

### 3.5 Invitation Recipient Verification (In-App Only)
- Invitations operate completely in-app with **zero email delivery**.
- Only Team Admins have permission to invite members (`can_invite_member`).
- Email serves strictly as an identifier for pre-existing registered Newtonite accounts (`email__iexact`).
- The invitation recipient must be authenticated with the invited email address to accept or decline:
  - `user.email.lower() == invitation.email.lower()`
- Tampering with the invitation ID or role in the POST request returns HTTP 403 / PermissionDenied.
- Acceptance atomically provisions `TeamMembership` and updates invitation status to `ACCEPTED`. Duplicate acceptance is strictly rejected.
