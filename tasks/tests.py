from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.db import IntegrityError, transaction

from tasks.models import (
    Team,
    TeamMembership,
    TeamRole,
    Task,
    TaskStatus,
    TaskPriority,
    ActivityEvent,
    EventType,
    IdempotencyRecord,
    TaskAttachment,
    WorkspaceInvitation,
    InvitationStatus,
    InAppNotification,
    NotificationCategory,
    SharedDocument,
    UserActivityReadState,
)
from tasks.services import (
    TaskService,
    TeamService,
    DashboardService,
    InvitationService,
    AttachmentService,
    NotificationService,
    SharedDocumentService,
    AuditTrackingService,
    StaleUpdateError,
    InvalidWorkflowTransitionError,
)
from tasks.permissions import (
    can_view_task,
    can_edit_task,
    can_change_task_status,
    can_manage_team,
    can_change_member_role,
    can_remove_member,
    can_view_shared_documents,
    can_upload_shared_document,
    can_download_shared_document,
    can_delete_shared_document,
    get_accessible_tasks_qs,
    get_accessible_teams_qs,
)


class TaskTrackerBaseTestCase(TestCase):
    def setUp(self):
        # Create users
        self.alice = User.objects.create_user(username='alice', password='Password123!', email='alice@test.local')
        self.bob = User.objects.create_user(username='bob', password='Password123!', email='bob@test.local')
        self.charlie = User.objects.create_user(username='charlie', password='Password123!', email='charlie@test.local')
        self.eve = User.objects.create_user(username='eve', password='Password123!', email='eve@test.local') # External user with no team access
        self.diana = User.objects.create_user(username='diana', password='Password123!', email='diana@test.local')


        # Create teams
        self.team_alpha = Team.objects.create(name='Alpha Team', description='Alpha Team Description')
        self.team_beta = Team.objects.create(name='Beta Team', description='Beta Team Description')

        # Set up memberships
        # Alice is ADMIN in Alpha
        self.m_alice_alpha = TeamMembership.objects.create(user=self.alice, team=self.team_alpha, role=TeamRole.ADMIN)
        # Bob is MANAGER in Alpha
        self.m_bob_alpha = TeamMembership.objects.create(user=self.bob, team=self.team_alpha, role=TeamRole.MANAGER)
        # Charlie is MEMBER in Alpha, and ADMIN in Beta
        self.m_charlie_alpha = TeamMembership.objects.create(user=self.charlie, team=self.team_alpha, role=TeamRole.MEMBER)
        self.m_charlie_beta = TeamMembership.objects.create(user=self.charlie, team=self.team_beta, role=TeamRole.ADMIN)

        # Clients for web testing
        self.client_alice = Client()
        self.client_alice.login(username='alice', password='Password123!')

        self.client_bob = Client()
        self.client_bob.login(username='bob', password='Password123!')

        self.client_charlie = Client()
        self.client_charlie.login(username='charlie', password='Password123!')

        self.client_eve = Client()
        self.client_eve.login(username='eve', password='Password123!')


class AuthenticationAndSecurityTests(TaskTrackerBaseTestCase):
    def test_unauthenticated_user_redirected_to_login(self):
        anon_client = Client()
        response = anon_client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_login_success_and_session(self):
        c = Client()
        response = c.post(reverse('login'), {'username': 'alice', 'password': 'Password123!'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))

    def test_login_invalid_credentials_does_not_leak_user_existence(self):
        c = Client()
        response = c.post(reverse('login'), {'username': 'non_existent_user', 'password': 'WrongPassword!'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password")

    def test_registration_creates_user_and_default_workspace(self):
        c = Client()
        response = c.post(reverse('register'), {
            'username': 'newuser',
            'first_name': 'New',
            'last_name': 'User',
            'email': 'newuser@test.local',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        u = User.objects.get(username='newuser')
        self.assertTrue(u.is_active)
        # Check automatic workspace provisioning
        membership = TeamMembership.objects.filter(user=u, role=TeamRole.ADMIN).first()
        self.assertIsNotNone(membership)
        self.assertIn("Newuser's Team", membership.team.name)


class TeamAuthorizationAndIsolationTests(TaskTrackerBaseTestCase):
    def test_cross_team_data_isolation(self):
        # Create task in Beta team
        beta_task = TaskService.create_task(
            user=self.charlie,
            team=self.team_beta,
            title="Secret Beta Task",
            priority=TaskPriority.HIGH
        )

        # Alice belongs only to Alpha team. Alice should NOT see beta_task in querysets
        alice_tasks = get_accessible_tasks_qs(self.alice)
        self.assertNotIn(beta_task, alice_tasks)

        # Alice attempting to access Beta task via direct URL (IDOR test)
        response = self.client_alice.get(reverse('task_detail', kwargs={'pk': beta_task.pk}))
        self.assertEqual(response.status_code, 403)

    def test_team_membership_uniqueness_constraint(self):
        with self.assertRaises(IntegrityError):
            TeamMembership.objects.create(user=self.alice, team=self.team_alpha, role=TeamRole.MEMBER)

    def test_assignee_must_belong_to_team(self):
        # Eve is NOT a member of Alpha team
        with self.assertRaises(ValidationError):
            TaskService.create_task(
                user=self.alice,
                team=self.team_alpha,
                title="Invalid Assignee Task",
                assignee=self.eve
            )


class TaskCRUDAndValidationTests(TaskTrackerBaseTestCase):
    def test_create_task_lifecycle_and_audit(self):
        task = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Database Sharding Strategy",
            description="Investigate horizontal partitioning.",
            priority=TaskPriority.HIGH,
            status=TaskStatus.OPEN,
            assignee=self.bob,
            due_date=timezone.localdate() + timedelta(days=5)
        )
        self.assertEqual(task.version, 1)
        self.assertEqual(task.status, TaskStatus.OPEN)

        # Verify audit activity event was created atomically
        event = ActivityEvent.objects.filter(task=task, event_type=EventType.TASK_CREATED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor, self.alice)
        self.assertEqual(event.team, self.team_alpha)

    def test_new_task_cannot_start_in_resolved_status(self):
        with self.assertRaises(ValidationError):
            TaskService.create_task(
                user=self.alice,
                team=self.team_alpha,
                title="Immediate Resolved Task",
                status=TaskStatus.RESOLVED
            )

    def test_member_permission_boundaries(self):
        # Alice (Admin) creates task
        task = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Core Refactoring",
            assignee=self.bob
        )
        # Charlie is MEMBER in team_alpha and is NOT creator nor assignee
        self.assertFalse(can_edit_task(self.charlie, task))

        # Assign Charlie to the task
        task.assignee = self.charlie
        task.save()
        self.assertTrue(can_edit_task(self.charlie, task))


class WorkflowTransitionTests(TaskTrackerBaseTestCase):
    def setUp(self):
        super().setUp()
        self.task = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Workflow Validation Test Task",
            status=TaskStatus.OPEN
        )

    def test_valid_status_flow(self):
        # OPEN -> IN_PROGRESS
        TaskService.transition_status(self.alice, self.task, TaskStatus.IN_PROGRESS)
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(self.task.version, 2)

        # IN_PROGRESS -> RESOLVED
        TaskService.transition_status(self.alice, self.task, TaskStatus.RESOLVED)
        self.assertEqual(self.task.status, TaskStatus.RESOLVED)
        self.assertEqual(self.task.version, 3)

        # RESOLVED -> OPEN (Reopen)
        TaskService.transition_status(self.alice, self.task, TaskStatus.OPEN)
        self.assertEqual(self.task.status, TaskStatus.OPEN)
        self.assertEqual(self.task.version, 4)

        # Verify audit events recorded
        events = ActivityEvent.objects.filter(task=self.task).order_by('created_at')
        event_types = [e.event_type for e in events]
        self.assertIn(EventType.TASK_CREATED, event_types)
        self.assertIn(EventType.STATUS_CHANGED, event_types)
        self.assertIn(EventType.TASK_RESOLVED, event_types)
        self.assertIn(EventType.TASK_REOPENED, event_types)

    def test_invalid_status_transition_rejected(self):
        # Mark as resolved
        TaskService.transition_status(self.alice, self.task, TaskStatus.RESOLVED)
        self.assertEqual(self.task.status, TaskStatus.RESOLVED)

        # Cannot jump directly from RESOLVED to IN_PROGRESS
        with self.assertRaises(InvalidWorkflowTransitionError):
            TaskService.transition_status(self.alice, self.task, TaskStatus.IN_PROGRESS)


class OptimisticConcurrencyStaleUpdateTests(TaskTrackerBaseTestCase):
    def test_stale_update_protection_raises_error(self):
        task = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Initial Title"
        )

        # User A loads version 1
        user_a_version = task.version

        # User B updates task in between (incrementing version to 2)
        TaskService.update_task(
            user=self.bob,
            task=task,
            title="User B Title Edit",
            description="",
            priority=task.priority,
            status=task.status,
            assignee=None,
            due_date=None,
            submitted_version=1
        )
        self.assertEqual(task.version, 2)

        # User A tries to save their edit using the stale version 1
        with self.assertRaises(StaleUpdateError):
            TaskService.update_task(
                user=self.alice,
                task=task,
                title="User A Overwrite Attempt",
                description="",
                priority=task.priority,
                status=task.status,
                assignee=None,
                due_date=None,
                submitted_version=user_a_version # Stale!
            )

        # Verify the database was NOT overwritten
        task.refresh_from_db()
        self.assertEqual(task.title, "User B Title Edit")
        self.assertEqual(task.version, 2)


class IdempotencyDuplicateSubmissionTests(TaskTrackerBaseTestCase):
    def test_idempotent_task_creation_prevents_duplicate(self):
        key = "idemp-unique-token-12345"

        # First request
        task1 = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Idempotent Task",
            idempotency_key=key
        )

        # Retry request with SAME idempotency key
        task2 = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Idempotent Task (Retried)",
            idempotency_key=key
        )

        # Must return the SAME task without creating a duplicate
        self.assertEqual(task1.id, task2.id)
        self.assertEqual(Task.objects.filter(team=self.team_alpha, title__contains="Idempotent").count(), 1)


class RoleEscalationAndMembershipTests(TaskTrackerBaseTestCase):
    def test_prevent_demoting_sole_admin(self):
        # Alice is the only ADMIN in Alpha team
        # Alice tries to change her own role to MEMBER
        can_demote = can_change_member_role(self.alice, self.m_alice_alpha, TeamRole.MEMBER)
        self.assertFalse(can_demote)

    def test_member_cannot_manage_team_or_add_members(self):
        # Charlie is MEMBER in Alpha team
        self.assertFalse(can_manage_team(self.charlie, self.team_alpha))
        with self.assertRaises(PermissionDenied):
            TeamService.add_member(self.charlie, self.team_alpha, self.eve, TeamRole.MEMBER)


class DashboardMetricsTests(TaskTrackerBaseTestCase):
    def test_dashboard_aggregates_correctly(self):
        today = timezone.localdate()
        # 1 Open task
        TaskService.create_task(user=self.alice, team=self.team_alpha, title="T1", status=TaskStatus.OPEN)
        # 1 In Progress task assigned to Alice
        TaskService.create_task(user=self.alice, team=self.team_alpha, title="T2", status=TaskStatus.IN_PROGRESS, assignee=self.alice)
        # 1 Overdue task
        Task.objects.create(
            title="T3 Overdue",
            team=self.team_alpha,
            creator=self.alice,
            due_date=today - timedelta(days=2),
            status=TaskStatus.OPEN
        )

        data = DashboardService.get_dashboard_data(self.alice)
        self.assertEqual(data['total_active'], 3)
        self.assertEqual(data['open_count'], 2)
        self.assertEqual(data['in_progress_count'], 1)
        self.assertEqual(data['overdue_count'], 1)
        self.assertEqual(data['my_tasks_count'], 1)


from django.core.files.uploadedfile import SimpleUploadedFile
from tasks.models import (
    TaskAttachment,
    WorkspaceInvitation,
    InvitationStatus,
    InAppNotification,
    NotificationCategory,
)
from tasks.services import (
    AttachmentService,
    InvitationService,
    NotificationService,
)


class TaskAttachmentTests(TaskTrackerBaseTestCase):
    def setUp(self):
        super().setUp()
        self.task = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Attachment Test Task",
            status=TaskStatus.OPEN
        )

    def test_authorized_user_can_upload_attachment(self):
        sample_file = SimpleUploadedFile("spec.pdf", b"%PDF-1.4 test binary data", content_type="application/pdf")
        attachment = AttachmentService.add_attachment(
            user=self.alice,
            task=self.task,
            uploaded_file=sample_file
        )
        self.assertIsNotNone(attachment.pk)
        self.assertEqual(attachment.filename, "spec.pdf")
        self.assertEqual(attachment.file_size, len(b"%PDF-1.4 test binary data"))
        self.assertEqual(attachment.uploader, self.alice)

    def test_unauthorized_user_cannot_upload_attachment(self):
        # Eve is not in team_alpha
        sample_file = SimpleUploadedFile("exploit.txt", b"unauthorized content", content_type="text/plain")
        with self.assertRaises(PermissionDenied):
            AttachmentService.add_attachment(
                user=self.eve,
                task=self.task,
                uploaded_file=sample_file
            )

    def test_file_download_authorization(self):
        sample_file = SimpleUploadedFile("readme.txt", b"hello world", content_type="text/plain")
        attachment = AttachmentService.add_attachment(
            user=self.alice,
            task=self.task,
            uploaded_file=sample_file
        )

        # Team member Alice can download
        resp_alice = self.client_alice.get(reverse('task_attachment_download', kwargs={'task_pk': self.task.pk, 'attachment_pk': attachment.pk}))
        self.assertEqual(resp_alice.status_code, 200)

        # Non-member Eve cannot download
        resp_eve = self.client_eve.get(reverse('task_attachment_download', kwargs={'task_pk': self.task.pk, 'attachment_pk': attachment.pk}))
        self.assertEqual(resp_eve.status_code, 403)

    def test_delete_attachment_cleans_up_storage(self):
        sample_file = SimpleUploadedFile("delete_me.txt", b"ephemeral data", content_type="text/plain")
        attachment = AttachmentService.add_attachment(
            user=self.alice,
            task=self.task,
            uploaded_file=sample_file
        )
        att_pk = attachment.pk
        AttachmentService.delete_attachment(user=self.alice, attachment_id=att_pk)
        self.assertFalse(TaskAttachment.objects.filter(pk=att_pk).exists())


class WorkspaceInvitationTests(TaskTrackerBaseTestCase):
    def test_admin_can_create_invitation(self):
        # Alice is Admin in Alpha team; invites registered user Eve (not in Alpha)
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MANAGER
        )
        self.assertEqual(invitation.status, InvitationStatus.PENDING)
        self.assertEqual(invitation.role, TeamRole.MANAGER)
        self.assertEqual(invitation.invitee_user, self.eve)

    def test_unregistered_email_cannot_receive_invitation(self):
        # Unregistered emails must be rejected with an honest validation message
        with self.assertRaises(ValidationError) as ctx:
            InvitationService.create_invitation(
                inviter=self.alice,
                team=self.team_alpha,
                invitee_email="unregistered@outside.com",
                role=TeamRole.MEMBER
            )
        self.assertIn("register an account in Newtonite", str(ctx.exception))

    def test_non_admin_cannot_create_invitation(self):
        # Charlie is Member in Alpha team
        with self.assertRaises(PermissionDenied):
            InvitationService.create_invitation(
                inviter=self.charlie,
                team=self.team_alpha,
                invitee_email=self.eve.email,
                role=TeamRole.MEMBER
            )

    def test_duplicate_pending_invitation_prevention(self):
        InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        with self.assertRaises(ValidationError):
            InvitationService.create_invitation(
                inviter=self.alice,
                team=self.team_alpha,
                invitee_email=self.eve.email,
                role=TeamRole.MEMBER
            )

    def test_invitee_can_accept_invitation(self):
        # Invite Eve (currently not in team_alpha)
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MANAGER
        )

        # Eve accepts
        membership = InvitationService.accept_invitation(self.eve, invitation.pk)
        self.assertEqual(membership.team, self.team_alpha)
        self.assertEqual(membership.role, TeamRole.MANAGER)
        
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, InvitationStatus.ACCEPTED)

    def test_unauthorized_user_cannot_accept_someone_elses_invitation(self):
        # Alice invites Diana
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.diana.email,
            role=TeamRole.MEMBER
        )
        # Eve tries to accept an invitation addressed to Diana
        with self.assertRaises(PermissionDenied):
            InvitationService.accept_invitation(self.eve, invitation.pk)

    def test_invitee_can_decline_invitation(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        declined_inv = InvitationService.decline_invitation(self.eve, invitation.pk)
        self.assertEqual(declined_inv.status, InvitationStatus.DECLINED)
        self.assertFalse(TeamMembership.objects.filter(user=self.eve, team=self.team_alpha).exists())

    def test_admin_can_revoke_invitation(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.diana.email,
            role=TeamRole.MEMBER
        )
        revoked_inv = InvitationService.revoke_invitation(self.alice, invitation.pk)
        self.assertEqual(revoked_inv.status, InvitationStatus.REVOKED)



class InAppNotificationTests(TaskTrackerBaseTestCase):
    def test_notification_created_on_task_assignment(self):
        task = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Design Review",
            assignee=self.bob,
            status=TaskStatus.OPEN
        )
        # Bob should have received an assignment notification
        notifications = InAppNotification.objects.filter(recipient=self.bob, task=task)
        self.assertTrue(notifications.exists())
        notif = notifications.first()
        self.assertEqual(notif.category, NotificationCategory.ASSIGNMENT)
        self.assertFalse(notif.is_read)

    def test_mark_as_read_and_mark_all_read(self):
        NotificationService.create_notification(
            recipient=self.bob,
            category=NotificationCategory.STATUS,
            title="Status Changed",
            message="Task #1 status transitioned to In Progress",
        )
        NotificationService.create_notification(
            recipient=self.bob,
            category=NotificationCategory.DEADLINE,
            title="Upcoming Deadline",
            message="Task #2 deadline in 24 hours",
        )

        self.assertEqual(InAppNotification.objects.filter(recipient=self.bob, is_read=False).count(), 2)

        # Mark all as read
        NotificationService.mark_all_as_read(self.bob)
        self.assertEqual(InAppNotification.objects.filter(recipient=self.bob, is_read=False).count(), 0)

    def test_updates_center_view_renders_successfully(self):
        resp = self.client_bob.get(reverse('updates_center'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Updates Center")


class FeatureWorkflowIntegrationTests(TaskTrackerBaseTestCase):
    def test_dashboard_displays_pending_invitation_banner(self):
        InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        resp = self.client_eve.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Workspace Invitations")
        self.assertContains(resp, "Alpha Team")
        self.assertContains(resp, "Accept")
        self.assertContains(resp, "Decline")

    def test_task_creation_with_multiple_attachments(self):
        f1 = SimpleUploadedFile("doc1.txt", b"Content 1", content_type="text/plain")
        f2 = SimpleUploadedFile("doc2.txt", b"Content 2", content_type="text/plain")

        resp = self.client_alice.post(reverse('task_create'), {
            'title': 'Task With Attachments',
            'team': self.team_alpha.pk,
            'priority': TaskPriority.MEDIUM,
            'status': TaskStatus.OPEN,
            'attachments': [f1, f2],
        })
        self.assertEqual(resp.status_code, 302)
        task = Task.objects.get(title='Task With Attachments')
        # All new uploads use the canonical SharedDocument model
        self.assertEqual(task.shared_documents.count(), 2)
        self.assertEqual(task.attachments.count(), 0) # No duplicate TaskAttachment records
        self.assertEqual(SharedDocument.objects.filter(task=task).count(), 2)


    def test_notification_mark_read_view(self):
        notif = NotificationService.create_notification(
            recipient=self.bob,
            category=NotificationCategory.STATUS,
            title="Notice",
            message="Test Notice Message"
        )
        self.assertFalse(notif.is_read)
        resp = self.client_bob.post(reverse('notification_mark_read', kwargs={'pk': notif.pk}))
        self.assertEqual(resp.status_code, 302)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_notification_mark_all_read_view(self):
        NotificationService.create_notification(
            recipient=self.bob,
            category=NotificationCategory.STATUS,
            title="Notice 1",
            message="Test 1"
        )
        NotificationService.create_notification(
            recipient=self.bob,
            category=NotificationCategory.DEADLINE,
            title="Notice 2",
            message="Test 2"
        )
        resp = self.client_bob.post(reverse('notification_mark_all_read'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(InAppNotification.objects.filter(recipient=self.bob, is_read=False).count(), 0)

    def test_invitation_accept_flow_via_post(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        resp = self.client_eve.post(reverse('invitation_accept', kwargs={'pk': invitation.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TeamMembership.objects.filter(user=self.eve, team=self.team_alpha).exists())


class SharedDocumentValidationAndModelTests(TaskTrackerBaseTestCase):
    def setUp(self):
        super().setUp()
        self.task_alpha = TaskService.create_task(
            user=self.alice,
            team=self.team_alpha,
            title="Alpha Architecture Task"
        )
        self.task_beta = TaskService.create_task(
            user=self.charlie,
            team=self.team_beta,
            title="Beta Network Task"
        )

    def test_upload_general_document_success(self):
        f = SimpleUploadedFile("architecture_v1.pdf", b"%PDF-1.4 test content", content_type="application/pdf")
        doc = SharedDocumentService.upload_document(
            user=self.alice,
            team=self.team_alpha,
            uploaded_file=f,
            description="Main system architecture blueprint."
        )
        self.assertEqual(doc.team, self.team_alpha)
        self.assertIsNone(doc.task)
        self.assertEqual(doc.original_filename, "architecture_v1.pdf")
        self.assertEqual(doc.extension, "pdf")
        self.assertEqual(doc.icon_category, "pdf")
        self.assertIn("shared_documents/team_", doc.file.name)
        self.assertIn("/general/", doc.file.name)

        # Check audit event
        event = ActivityEvent.objects.filter(team=self.team_alpha, event_type=EventType.DOCUMENT_UPLOADED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor, self.alice)

    def test_upload_task_specific_document_success(self):
        f = SimpleUploadedFile("task_specs.docx", b"PK docx content", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        doc = SharedDocumentService.upload_document(
            user=self.bob,
            team=self.team_alpha,
            uploaded_file=f,
            task=self.task_alpha
        )
        self.assertEqual(doc.team, self.team_alpha)
        self.assertEqual(doc.task, self.task_alpha)
        self.assertIn(f"/task_{self.task_alpha.id}/", doc.file.name)

    def test_cross_team_task_association_rejected(self):
        # Attempting to assign task_beta (Team Beta) to Team Alpha's document library
        f = SimpleUploadedFile("leak.pdf", b"pdf content", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            SharedDocumentService.upload_document(
                user=self.alice,
                team=self.team_alpha,
                uploaded_file=f,
                task=self.task_beta
            )

    def test_empty_file_rejected(self):
        empty_f = SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            SharedDocumentService.upload_document(
                user=self.alice,
                team=self.team_alpha,
                uploaded_file=empty_f
            )

    def test_oversized_file_rejected(self):
        oversized = SimpleUploadedFile("huge.pdf", b"0" * (25 * 1024 * 1024 + 10), content_type="application/pdf")
        with self.assertRaises(ValidationError):
            SharedDocumentService.upload_document(
                user=self.alice,
                team=self.team_alpha,
                uploaded_file=oversized
            )

    def test_executable_and_dangerous_files_rejected(self):
        for bad_name in ["malware.exe", "script.sh", "exploit.bat", "powershell.ps1"]:
            bad_f = SimpleUploadedFile(bad_name, b"binary content", content_type="application/octet-stream")
            with self.assertRaises(ValidationError):
                SharedDocumentService.upload_document(
                    user=self.alice,
                    team=self.team_alpha,
                    uploaded_file=bad_f
                )


class SharedDocumentPermissionsAndSecurityTests(TaskTrackerBaseTestCase):
    def setUp(self):
        super().setUp()
        f1 = SimpleUploadedFile("alice_doc.pdf", b"%PDF content", content_type="application/pdf")
        self.doc_alice = SharedDocumentService.upload_document(
            user=self.alice,
            team=self.team_alpha,
            uploaded_file=f1,
            description="Alice's confidential blueprint"
        )
        f2 = SimpleUploadedFile("charlie_doc.xlsx", b"Excel content", content_type="application/vnd.ms-excel")
        self.doc_charlie = SharedDocumentService.upload_document(
            user=self.charlie,
            team=self.team_alpha,
            uploaded_file=f2,
            description="Charlie's member notes"
        )

    def test_anonymous_user_cannot_access_or_download(self):
        anon_client = Client()
        resp_list = anon_client.get(reverse('team_documents', kwargs={'pk': self.team_alpha.pk}))
        self.assertEqual(resp_list.status_code, 302)

        resp_down = anon_client.get(reverse('shared_document_download', kwargs={'pk': self.doc_alice.pk}))
        self.assertEqual(resp_down.status_code, 302)

    def test_team_member_can_view_and_download(self):
        resp = self.client_charlie.get(reverse('team_documents', kwargs={'pk': self.team_alpha.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "alice_doc.pdf")
        self.assertContains(resp, "charlie_doc.xlsx")

        down_resp = self.client_charlie.get(reverse('shared_document_download', kwargs={'pk': self.doc_alice.pk}))
        self.assertEqual(down_resp.status_code, 200)

    def test_non_team_member_cannot_view_or_download(self):
        resp = self.client_eve.get(reverse('team_documents', kwargs={'pk': self.team_alpha.pk}))
        self.assertEqual(resp.status_code, 403)

        down_resp = self.client_eve.get(reverse('shared_document_download', kwargs={'pk': self.doc_alice.pk}))
        self.assertEqual(down_resp.status_code, 403)

    def test_member_can_delete_own_document(self):
        self.assertTrue(can_delete_shared_document(self.charlie, self.doc_charlie))
        resp = self.client_charlie.post(reverse('shared_document_delete', kwargs={'pk': self.doc_charlie.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(SharedDocument.objects.filter(pk=self.doc_charlie.pk).exists())

    def test_member_cannot_delete_another_users_document(self):
        self.assertFalse(can_delete_shared_document(self.charlie, self.doc_alice))
        resp = self.client_charlie.post(reverse('shared_document_delete', kwargs={'pk': self.doc_alice.pk}))
        self.assertTrue(SharedDocument.objects.filter(pk=self.doc_alice.pk).exists())

    def test_manager_and_admin_can_delete_any_team_document(self):
        self.assertTrue(can_delete_shared_document(self.bob, self.doc_alice))
        self.assertTrue(can_delete_shared_document(self.alice, self.doc_alice))

    def test_document_search_is_team_isolated(self):
        f_beta = SimpleUploadedFile("beta_secret.pdf", b"secret", content_type="application/pdf")
        doc_beta = SharedDocumentService.upload_document(
            user=self.charlie,
            team=self.team_beta,
            uploaded_file=f_beta
        )
        resp = self.client_alice.get(reverse('team_documents', kwargs={'pk': self.team_alpha.pk}) + "?q=beta_secret")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "beta_secret.pdf")


class TeamInvitationWorkflowVerificationTests(TaskTrackerBaseTestCase):
    def test_invitation_creation_is_in_app_only_and_sends_no_email(self):
        mail.outbox.clear()
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MANAGER
        )
        # Strictly in-app: zero outbound emails dispatched
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(invitation.status, InvitationStatus.PENDING)
        self.assertEqual(invitation.invitee_user, self.eve)
        # Verify in-app notification delivered
        notif = InAppNotification.objects.filter(recipient=self.eve, invitation=invitation).first()
        self.assertIsNotNone(notif)
        self.assertIn("Alpha Team", notif.title)

    def test_accept_invitation_creates_membership_atomically(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MANAGER
        )
        self.assertEqual(invitation.status, InvitationStatus.PENDING)

        resp = self.client_eve.post(reverse('invitation_accept', kwargs={'pk': invitation.pk}))
        self.assertEqual(resp.status_code, 302)

        membership = TeamMembership.objects.filter(user=self.eve, team=self.team_alpha).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, TeamRole.MANAGER)

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, InvitationStatus.ACCEPTED)

    def test_decline_invitation_does_not_create_membership(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        resp = self.client_eve.post(reverse('invitation_decline', kwargs={'pk': invitation.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TeamMembership.objects.filter(user=self.eve, team=self.team_alpha).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, InvitationStatus.DECLINED)

    def test_unauthorized_user_cannot_accept_another_invitation(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.diana.email,
            role=TeamRole.MEMBER
        )
        resp = self.client_eve.post(reverse('invitation_accept', kwargs={'pk': invitation.pk}))
        self.assertFalse(TeamMembership.objects.filter(user=self.eve, team=self.team_alpha).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, InvitationStatus.PENDING)



class AuditReadIndicatorTrackingTests(TaskTrackerBaseTestCase):
    def test_audit_indicator_lifecycle_and_isolation(self):
        # 1. Initially, create a new activity event in team_alpha
        ActivityEvent.objects.create(
            actor=self.alice,
            team=self.team_alpha,
            event_type=EventType.TASK_CREATED,
            details="New operational task created by Alice."
        )

        # Alice & Bob (members of Alpha) should see unread activity
        self.assertTrue(AuditTrackingService.has_unread_activity(self.alice))
        self.assertTrue(AuditTrackingService.has_unread_activity(self.bob))

        # Eve (not in Alpha) must NOT see unread activity (no data leak)
        self.assertFalse(AuditTrackingService.has_unread_activity(self.eve))

        # 2. Alice visits the activity page
        resp = self.client_alice.get(reverse('activity_list'))
        self.assertEqual(resp.status_code, 200)

        # Alice's unread indicator should now be cleared
        self.assertFalse(AuditTrackingService.has_unread_activity(self.alice))

        # Bob has NOT visited the activity page yet, his unread indicator must still be True!
        self.assertTrue(AuditTrackingService.has_unread_activity(self.bob))

        # 3. Visiting the unrelated updates center does NOT clear the audit indicator
        resp_upd = self.client_bob.get(reverse('updates_center'))
        self.assertEqual(resp_upd.status_code, 200)
        self.assertTrue(AuditTrackingService.has_unread_activity(self.bob))

        # 4. A new activity event arrives in Alpha
        ActivityEvent.objects.create(
            actor=self.bob,
            team=self.team_alpha,
            event_type=EventType.STATUS_CHANGED,
            details="Status updated to In Progress."
        )

        # Alice's unread indicator should reappear!
        self.assertTrue(AuditTrackingService.has_unread_activity(self.alice))

        # 5. Verify that ActivityEvent records themselves remain completely immutable
        event_count = ActivityEvent.objects.count()
        AuditTrackingService.mark_activity_read(self.alice)
        self.assertEqual(ActivityEvent.objects.count(), event_count)


class SharedDocumentViewAndEndpointIntegrationTests(TaskTrackerBaseTestCase):
    def test_upload_view_via_post_success(self):
        f = SimpleUploadedFile("post_test.pdf", b"%PDF-1.4 file data", content_type="application/pdf")
        resp = self.client_alice.post(reverse('shared_document_upload', kwargs={'pk': self.team_alpha.pk}), {
            'file': f,
            'description': 'Uploaded via web view'
        })
        self.assertEqual(resp.status_code, 302)
        doc = SharedDocument.objects.filter(team=self.team_alpha, original_filename="post_test.pdf").first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.description, 'Uploaded via web view')

    def test_delete_view_post_forbidden_for_non_member(self):
        f = SimpleUploadedFile("delete_forbid.pdf", b"%PDF data", content_type="application/pdf")
        doc = SharedDocumentService.upload_document(
            user=self.alice,
            team=self.team_alpha,
            uploaded_file=f
        )
        # Eve is non-member
        resp = self.client_eve.post(reverse('shared_document_delete', kwargs={'pk': doc.pk}))
        # Eve should not be able to delete and document must remain intact
        self.assertTrue(SharedDocument.objects.filter(pk=doc.pk).exists())

    def test_documents_index_view_redirects_to_first_team(self):
        resp = self.client_alice.get(reverse('documents_index'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/teams/{self.team_alpha.pk}/documents/", resp.url)

    def test_invitation_cannot_be_accepted_twice(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        InvitationService.accept_invitation(self.eve, invitation.pk)
        with self.assertRaises(ValidationError):
            InvitationService.accept_invitation(self.eve, invitation.pk)

    def test_expired_invitation_cannot_be_accepted(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        # Manually expire invitation
        invitation.expires_at = timezone.now() - timedelta(hours=1)
        invitation.save(update_fields=['expires_at'])

        with self.assertRaises(ValidationError):
            InvitationService.accept_invitation(self.eve, invitation.pk)

    def test_revoked_invitation_cannot_be_accepted(self):
        invitation = InvitationService.create_invitation(
            inviter=self.alice,
            team=self.team_alpha,
            invitee_email=self.eve.email,
            role=TeamRole.MEMBER
        )
        InvitationService.revoke_invitation(self.alice, invitation.pk)
        with self.assertRaises(ValidationError):
            InvitationService.accept_invitation(self.eve, invitation.pk)




