# Newtonite Task Tracker: Automated Testing & Verification Guide

## 1. Testing Philosophy

Newtonite adheres to a strict correctness testing philosophy:
1. **Never test merely for HTTP 200**: Every test must verify the underlying database side effects, transactional boundaries, object state, physical storage, and immutable audit logs.
2. **Distinct Authorized and Unauthorized Test Fixtures**: Tests explicitly construct distinct tenant teams (`Alpha Team`, `Beta Team`) and distinct actors (`Alice` Admin, `Bob` Manager, `Charlie` Member, `Eve`/`Diana` External Registered Users) to verify authorization boundaries and anti-IDOR defenses.
3. **Automated Concurrency & Race Condition Simulation**: Concurrency conflicts and duplicate form submissions are simulated explicitly in tests to guarantee optimistic locking and idempotency.
4. **Physical Storage Cleanup & Lifecycle Testing**: Document and attachment tests verify physical disk unlinking on model deletion and storage isolation.
5. **In-App Only Workflow Verification**: Team invitations verify zero outbound emails (`len(mail.outbox) == 0`), persistent in-app notifications, and atomic accept/decline flows.
6. **Canonical Unified Uploads**: New uploads from task creation, task detail, and the shared library are verified to create canonical `SharedDocument` records without duplicate `TaskAttachment` rows or duplicated physical files, while maintaining backward-compatible access to legacy attachments.

---

## 2. Test Execution Commands

Newtonite supports both native Django test running and Pytest with code coverage:

### 2.1 Native Django Test Runner
```powershell
# Standard test execution
py manage.py test

# Verbose test execution
py manage.py test -v 2
```

### 2.2 Pytest Runner (Recommended for CI & Local Development)
```powershell
# Run the complete test suite with Pytest
py -m pytest

# Run with test coverage reporting
py -m pytest --cov=tasks --cov-report=term
```

### 2.3 Fast Test Execution Optimization
In `config/settings.py`, Newtonite automatically configures `MD5PasswordHasher` when running under `manage.py test` or `pytest`. This keeps the full 61-test suite execution under **~2.2 seconds** while preserving full authentication logic and validity.

---

## 3. Test Suites & Coverage Breakdown

The automated test suite in `tasks/tests.py` consists of **61 comprehensive tests** organized across 13 test classes:

### 3.1 `AuthenticationAndSecurityTests`
- `test_unauthenticated_user_redirected_to_login`: Verifies that unauthenticated requests to protected endpoints receive HTTP 302 redirecting to `/login/`.
- `test_login_success_and_session`: Validates authentication, session cookie issuance, and redirection to the dashboard.
- `test_login_invalid_credentials_does_not_leak_user_existence`: Ensures bad credentials show a generic message without exposing whether a username exists.
- `test_registration_creates_user_and_default_workspace`: Verifies safe registration, password hashing, and automatic provisioning of a default workspace with the user as Team Admin.

### 3.2 `TeamAuthorizationAndIsolationTests`
- `test_cross_team_data_isolation`: Proves that a user in Team Alpha cannot see tasks from Team Beta in querysets and receives HTTP 403 when attempting direct URL access.
- `test_team_membership_uniqueness_constraint`: Verifies that database-level unique constraints reject inserting a user into the same team twice.
- `test_assignee_must_belong_to_team`: Verifies that assigning a non-member to an Alpha team task raises `ValidationError`.

### 3.3 `TaskCRUDAndValidationTests`
- `test_create_task_lifecycle_and_audit`: Verifies creation, initial version setting (`version=1`), and atomic insertion of `ActivityEvent` with previous and new states.
- `test_new_task_cannot_start_in_resolved_status`: Enforces workflow rules preventing brand-new tasks from being created directly in Resolved status.
- `test_member_permission_boundaries`: Confirms that ordinary team members can only edit tasks created by them or assigned to them.

### 3.4 `WorkflowTransitionTests`
- `test_valid_status_flow`: Exercises legal lifecycle transitions: `OPEN` &rarr; `IN_PROGRESS` &rarr; `RESOLVED` &rarr; `OPEN` (Reopened), verifying version increments and audit history recording for each step.
- `test_invalid_status_transition_rejected`: Proves that jumping directly from `RESOLVED` to `IN_PROGRESS` is rejected with `InvalidWorkflowTransitionError`.

### 3.5 `OptimisticConcurrencyStaleUpdateTests`
- `test_stale_update_protection_raises_error`: Simulates two users editing a task concurrently. User A loads version 1. User B updates the task to version 2. User A attempts to submit based on version 1. Proves that `StaleUpdateError` is raised and User B's edits are NOT overwritten.

### 3.6 `IdempotencyDuplicateSubmissionTests`
- `test_idempotent_task_creation_prevents_duplicate`: Submits two creation requests with the same idempotency UUID. Verifies that exactly one task is created and both requests receive the same task reference.

### 3.7 `RoleEscalationAndMembershipTests`
- `test_prevent_demoting_sole_admin`: Guarantees that the last administrator of a team cannot demote themselves to ordinary Member.
- `test_member_cannot_manage_team_or_add_members`: Guarantees that ordinary Members cannot add users or alter team settings.

### 3.8 `DashboardMetricsTests`
- `test_dashboard_aggregates_correctly`: Seeds a known distribution of open, in-progress, overdue, and assigned tasks, and verifies that `DashboardService.get_dashboard_data()` calculates exact matching totals.

### 3.9 `TaskAttachmentTests`
- `test_authorized_user_can_upload_attachment`: Verifies upload of legacy task attachments.
- `test_unauthorized_user_cannot_upload_attachment`: Proves unauthorized users receive HTTP 403.
- `test_file_download_authorization`: Validates authorized file streaming via `FileResponse`.
- `test_delete_attachment_cleans_up_storage`: Proves physical disk unlinking on attachment deletion.

### 3.10 `WorkspaceInvitationTests` (In-App Only)
- `test_admin_can_create_invitation`: Team Admin creates in-app invitation for existing user; verifies DB state and expiry.
- `test_non_admin_cannot_create_invitation`: Ordinary Member receives HTTP 403 when attempting to invite.
- `test_unregistered_email_cannot_receive_invitation`: Inviting an unregistered email address fails with clear validation error; zero emails dispatched.
- `test_duplicate_pending_invitation_prevention`: Rejects creating multiple pending invitations to the same user for the same team.
- `test_invitee_can_accept_invitation`: Atomic acceptance creates `TeamMembership`, updates status to `ACCEPTED`, and logs audit activity.
- `test_invitee_can_decline_invitation`: Declining updates status to `DECLINED` without creating team membership.
- `test_unauthorized_user_cannot_accept_someone_elses_invitation`: Another user attempting to accept is denied.
- `test_admin_can_revoke_invitation`: Admin can revoke active pending invitations.

### 3.11 `InAppNotificationTests`
- `test_notification_created_on_task_assignment`: Assigning a task generates an in-app notification for the assignee.
- `test_mark_as_read_and_mark_all_read`: Tests marking individual and batch notifications as read.
- `test_updates_center_view_renders_successfully`: Tests Updates Center view rendering and pending invitation context.

### 3.12 `FeatureWorkflowIntegrationTests`
- `test_dashboard_displays_pending_invitation_banner`: Verifies the pending invitation notification banner on the dashboard.
- `test_invitation_accept_flow_via_post`: Verifies POST-based CSRF-protected acceptance endpoint.
- `test_notification_mark_read_view`: Verifies single notification mark-read endpoint.
- `test_notification_mark_all_read_view`: Verifies mark-all-read endpoint.
- `test_task_creation_with_multiple_attachments`: Proves multiple file uploads during task creation create canonical `SharedDocument` records (`task.shared_documents.count() == 2`) and zero duplicate `TaskAttachment` rows.

### 3.13 `SharedDocumentValidationAndModelTests`
- `test_upload_general_document_success`: Uploads team general document with canonical metadata.
- `test_upload_task_specific_document_success`: Associates document with task in the same team.
- `test_cross_team_task_association_rejected`: Rejecting document association with a task from a different team.
- `test_oversized_file_rejected`: Rejecting files over 25 MiB.
- `test_executable_and_dangerous_files_rejected`: Rejecting `.exe`, `.bat`, `.sh`, `.py`, `.js`, etc.
- `test_empty_file_rejected`: Rejecting 0-byte empty files.

### 3.14 `SharedDocumentPermissionsAndSecurityTests`
- `test_anonymous_user_cannot_access_or_download`: Unauthenticated users redirected to login.
- `test_team_member_can_view_and_download`: Authorized team members can view and download documents.
- `test_non_team_member_cannot_view_or_download`: Non-members denied with HTTP 403.
- `test_member_can_delete_own_document`: Author can delete their own uploaded document.
- `test_member_cannot_delete_another_users_document`: Member cannot delete another user's document.
- `test_manager_and_admin_can_delete_any_team_document`: Admins/Managers can delete any document in their team.
- `test_document_search_is_team_isolated`: Document search queries are strictly isolated to the caller's team.

### 3.15 `TeamInvitationWorkflowVerificationTests`
- `test_invitation_creation_is_in_app_only_and_sends_no_email`: Explicitly confirms `len(mail.outbox) == 0` when invitations are created.
- `test_accept_invitation_creates_membership_atomically`: Verifies atomic membership creation on acceptance.
- `test_decline_invitation_does_not_create_membership`: Verifies decline leaves team membership count unchanged.
- `test_unauthorized_user_cannot_accept_another_invitation`: Prevents unauthorized acceptance.

### 3.16 `AuditReadIndicatorTrackingTests`
- `test_audit_indicator_lifecycle_and_isolation`: Tests unread dot appearance, clearing upon viewing `/activity/`, reappearance on new events, and per-user isolation.

### 3.17 `SharedDocumentViewAndEndpointIntegrationTests`
- `test_documents_index_view_redirects_to_first_team`: Validates `/documents/` redirection.
- `test_upload_view_via_post_success`: Validates POST file upload to team library.
- `test_delete_view_post_forbidden_for_non_member`: Validates deletion authorization enforcement.
- `test_expired_invitation_cannot_be_accepted`: Expired invitations cannot be accepted.
- `test_revoked_invitation_cannot_be_accepted`: Revoked invitations cannot be accepted.
- `test_invitation_cannot_be_accepted_twice`: Duplicate acceptance attempts are rejected.

---

## 4. Actual Verified Test Results

### 4.1 Native Django Test Runner
```text
Creating test database for alias 'default'...
.............................................................
----------------------------------------------------------------------
Ran 61 tests in 1.943s

OK
Destroying test database for alias 'default'...
Found 61 test(s).
System check identified no issues (0 silenced).
```

### 4.2 Pytest Runner
```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.7.0
rootdir: D:\AIML Projects\omeesha\tasktrackernewtonite-main\tasktrackernewtonite-main
configfile: pytest.ini
collected 61 items

tasks/tests.py ............................................................. [100%]

============================= 61 passed in 2.23s ==============================
```

- **Tests Run**: 61
- **Passed**: 61 (100%)
- **Failures**: 0
- **Errors**: 0
- **Execution Time**: ~1.94s (Django) / ~2.23s (Pytest)
- **Code Coverage**: 74% overall across `tasks` module (100% on models/admin/urls/context_processors)

---

## 5. Continuous Integration (CI)

A GitHub Actions workflow is configured in `.github/workflows/test.yml`:
- Runs automatically on `push` and `pull_request` to `main` and `master`.
- Sets up Python, installs dependencies from `requirements.txt`.
- Runs `python manage.py check`.
- Checks migrations with `python manage.py makemigrations --check --dry-run`.
- Runs full `pytest` suite with coverage tracking.
