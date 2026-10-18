from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.utils import timezone

from tasks.models import (
    Team,
    TeamMembership,
    TeamRole,
    Task,
    TaskStatus,
    TaskPriority,
    ActivityEvent,
    EventType,
    SharedDocument,
    WorkspaceInvitation,
    InvitationStatus,
    InAppNotification,
    NotificationCategory,
)


class Command(BaseCommand):
    help = "Seeds database with showcase teams, realistic users across roles, tasks, invitations, notifications, and shared documents (100% idempotent)."

    def handle(self, *args, **options):
        self.stdout.write("Seeding showcase demo data...")

        # 1. Superuser
        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@newtonite.local',
                'first_name': 'System',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        admin_user.set_password('AdminPass123!')
        admin_user.save()

        # 2. Demo Users
        users_def = [
            ('alice', 'alice@newtonite.local', 'Alice', 'Morgan', 'Password123!'),
            ('bob', 'bob@newtonite.local', 'Bob', 'Chen', 'Password123!'),
            ('charlie', 'charlie@newtonite.local', 'Charlie', 'Kim', 'Password123!'),
            ('diana', 'diana@newtonite.local', 'Diana', 'Prince', 'Password123!'),
            ('edward', 'edward@newtonite.local', 'Edward', 'Norton', 'Password123!'),
            ('fiona', 'fiona@newtonite.local', 'Fiona', 'Gallagher', 'Password123!'),
            ('george', 'george@newtonite.local', 'George', 'Clark', 'Password123!'),
        ]
        users = {}
        for uname, email, fname, lname, pwd in users_def:
            u, _ = User.objects.get_or_create(
                username=uname,
                defaults={'email': email, 'first_name': fname, 'last_name': lname}
            )
            u.set_password(pwd)
            u.save()
            users[uname] = u

        # 3. Teams
        core_team, _ = Team.objects.get_or_create(
            name="Core Platform",
            defaults={"description": "Backend architecture, distributed database engineering, APIs, and infrastructure."}
        )
        frontend_team, _ = Team.objects.get_or_create(
            name="Frontend Engineering",
            defaults={"description": "Design systems, accessible interfaces, React/Django templates, and UX polish."}
        )
        mobile_team, _ = Team.objects.get_or_create(
            name="Mobile Apps",
            defaults={"description": "iOS and Android native client applications and offline syncing."}
        )
        ops_team, _ = Team.objects.get_or_create(
            name="Operations Support",
            defaults={"description": "Incident response, on-call coordination, and infrastructure reliability."}
        )

        # 4. Team Memberships
        memberships = [
            # Core Platform: Alice (Admin), Bob (Manager), Charlie (Member), Fiona (Member)
            (users['alice'], core_team, TeamRole.ADMIN),
            (users['bob'], core_team, TeamRole.MANAGER),
            (users['charlie'], core_team, TeamRole.MEMBER),
            (users['fiona'], core_team, TeamRole.MEMBER),
            # Frontend Engineering: Diana (Admin), Bob (Member), Edward (Manager)
            (users['diana'], frontend_team, TeamRole.ADMIN),
            (users['bob'], frontend_team, TeamRole.MEMBER),
            (users['edward'], frontend_team, TeamRole.MANAGER),
            # Mobile Apps: Charlie (Admin)
            (users['charlie'], mobile_team, TeamRole.ADMIN),
            # Operations Support: George (Member - isolated)
            (users['george'], ops_team, TeamRole.MEMBER),
        ]

        for u, t, r in memberships:
            m, created = TeamMembership.objects.get_or_create(
                user=u, team=t,
                defaults={'role': r}
            )
            if not created and m.role != r:
                m.role = r
                m.save()

        # 5. Tasks
        today = timezone.localdate()
        tasks_def = [
            # Core Team Tasks
            (
                "Implement Optimistic Concurrency Control on Tasks",
                "Ensure conditional version checks are performed atomically on the DB level to prevent lost updates.",
                core_team, TaskPriority.URGENT, TaskStatus.IN_PROGRESS, users['alice'], users['bob'], today + timedelta(days=2)
            ),
            (
                "Fix Database Connection Pool Leak Under Load",
                "Connections remain open when unhandled exceptions occur in worker threads.",
                core_team, TaskPriority.HIGH, TaskStatus.OPEN, users['alice'], users['charlie'], today - timedelta(days=2)  # Overdue
            ),
            (
                "Design Idempotency Middleware for Create Endpoints",
                "Persist UUID keys in IdempotencyRecord with unique constraint on user + key + action.",
                core_team, TaskPriority.HIGH, TaskStatus.RESOLVED, users['bob'], users['alice'], today - timedelta(days=5)
            ),
            (
                "Migrate SQLite Schema to Support Composite Indexes",
                "Add multi-column indexes on (team, status, priority) to accelerate dashboard aggregations.",
                core_team, TaskPriority.MEDIUM, TaskStatus.OPEN, users['charlie'], users['fiona'], today + timedelta(days=7)
            ),
            (
                "Conduct Security Audit of Object-Level Authorization",
                "Verify no Insecure Direct Object References (IDOR) exist in team scoping logic.",
                core_team, TaskPriority.URGENT, TaskStatus.IN_PROGRESS, users['alice'], users['alice'], today - timedelta(days=1)  # Overdue
            ),
            # Frontend Team Tasks
            (
                "Implement Clean SaaS Design System and Responsive Shell",
                "Typography with Inter, calm neutral slate palette, responsive mobile collapsible drawer.",
                frontend_team, TaskPriority.HIGH, TaskStatus.RESOLVED, users['diana'], users['diana'], today - timedelta(days=1)
            ),
            (
                "Add Dynamic Team Member Filtering in Task Creation",
                "Fetch members asynchronously when team changes to prevent illegal cross-team assignments.",
                frontend_team, TaskPriority.MEDIUM, TaskStatus.IN_PROGRESS, users['diana'], users['bob'], today + timedelta(days=3)
            ),
            (
                "Design Stale Update Conflict Modal and Diff View",
                "When a 409 conflict is received, show current DB state alongside user submitted changes.",
                frontend_team, TaskPriority.HIGH, TaskStatus.OPEN, users['edward'], users['edward'], today + timedelta(days=5)
            ),
            (
                "Audit Accessibility Contrast and Keyboard Navigation",
                "Ensure WCAG AA contrast ratio across all badge states and form inputs.",
                frontend_team, TaskPriority.LOW, TaskStatus.OPEN, users['diana'], None, today + timedelta(days=10)
            ),
            # Mobile App Tasks
            (
                "Define Offline Sync Protocol for Task Tracker",
                "Buffer state changes locally in SQLite and reconcile timestamps during reconnect.",
                mobile_team, TaskPriority.HIGH, TaskStatus.OPEN, users['charlie'], users['charlie'], today + timedelta(days=4)
            ),
            # Operations Support Tasks
            (
                "Deploy Continuous Monitoring and Alerting",
                "Configure uptime checks and latency thresholds for production endpoints.",
                ops_team, TaskPriority.MEDIUM, TaskStatus.OPEN, users['george'], users['george'], today + timedelta(days=6)
            ),
        ]

        seeded_tasks = {}
        for title, desc, team, prio, status, creator, assignee, due in tasks_def:
            task, created = Task.objects.get_or_create(
                title=title,
                team=team,
                defaults={
                    'description': desc,
                    'priority': prio,
                    'status': status,
                    'creator': creator,
                    'assignee': assignee,
                    'due_date': due,
                    'version': 1
                }
            )
            seeded_tasks[title] = task
            if created:
                ActivityEvent.objects.create(
                    actor=creator,
                    team=team,
                    task=task,
                    event_type=EventType.TASK_CREATED,
                    details=f"Task '{task.title}' initialized with priority {task.get_priority_display()}.",
                    new_state={'status': task.status, 'priority': task.priority}
                )

        # 6. Seed Pending & Accepted Invitations
        # Fiona has a realistic pending invitation to Frontend Engineering from Diana
        inv_fiona, created_inv = WorkspaceInvitation.objects.get_or_create(
            team=frontend_team,
            invitee_email='fiona@newtonite.local',
            defaults={
                'inviter': users['diana'],
                'invitee_user': users['fiona'],
                'role': TeamRole.MEMBER,
                'status': InvitationStatus.PENDING,
                'expires_at': timezone.now() + timedelta(days=7),
            }
        )
        if created_inv:
            ActivityEvent.objects.create(
                actor=users['diana'],
                team=frontend_team,
                event_type=EventType.MEMBER_ADDED,
                details=f"Invitation sent to 'fiona@newtonite.local' for role Member by diana.",
                new_state={'email': 'fiona@newtonite.local', 'role': TeamRole.MEMBER}
            )
            InAppNotification.objects.create(
                recipient=users['fiona'],
                actor=users['diana'],
                category=NotificationCategory.INVITATION,
                title="Workspace Invitation: Frontend Engineering",
                message="Diana Prince invited you to join 'Frontend Engineering' as Member.",
                invitation=inv_fiona,
                team=frontend_team,
                is_urgent=False
            )

        # 7. Seed In-App Notifications (Read and Unread across categories)
        task_overdue = seeded_tasks.get("Fix Database Connection Pool Leak Under Load")
        if task_overdue:
            InAppNotification.objects.get_or_create(
                recipient=users['charlie'],
                task=task_overdue,
                category=NotificationCategory.DEADLINE,
                defaults={
                    'actor': None,
                    'title': f"Overdue Task: #{task_overdue.id} {task_overdue.title}",
                    'message': f"Task was due on {task_overdue.due_date}. Please update milestone status.",
                    'team': task_overdue.team,
                    'is_urgent': True,
                    'is_read': False
                }
            )

        task_idempotency = seeded_tasks.get("Design Idempotency Middleware for Create Endpoints")
        if task_idempotency:
            InAppNotification.objects.get_or_create(
                recipient=users['alice'],
                task=task_idempotency,
                category=NotificationCategory.STATUS,
                defaults={
                    'actor': users['bob'],
                    'title': f"Task Resolved: #{task_idempotency.id} {task_idempotency.title}",
                    'message': "Bob Chen marked this task as Resolved.",
                    'team': task_idempotency.team,
                    'is_urgent': False,
                    'is_read': True,
                    'read_at': timezone.now() - timedelta(hours=3)
                }
            )

        # 8. Seed Physical Shared Documents
        docs_def = [
            (
                "system_architecture_spec_v2.pdf",
                "Core platform microservice architecture diagram, data flow invariants, and optimistic locking protocols.",
                core_team,
                None,  # General
                users['alice'],
                b"%PDF-1.4 Newtonite Architecture Blueprint Specification v2.0 - Core Invariants and Concurrency Control"
            ),
            (
                "database_sharding_plan.xlsx",
                "Table partition strategy, index distribution, and SQLite to PostgreSQL migration plan.",
                core_team,
                seeded_tasks.get("Migrate SQLite Schema to Support Composite Indexes"),
                users['charlie'],
                b"PK\x03\x04 Newtonite Database Sharding & Index Benchmarks Spreadsheets"
            ),
            (
                "design_system_tokens.json",
                "Color palette specifications (ivory, sage, forest), font hierarchies, and accessibility contrast standards.",
                frontend_team,
                None,  # General
                users['diana'],
                b'{\n  "theme": "newtonite-editorial",\n  "primary": "#285741",\n  "sage": "#5C8571",\n  "ivory": "#FDFBF7"\n}'
            ),
            (
                "offline_sync_protocol.md",
                "Local SQLite write-ahead log format, conflict resolution vector clocks, and re-sync endpoints.",
                mobile_team,
                seeded_tasks.get("Define Offline Sync Protocol for Task Tracker"),
                users['charlie'],
                b"# Newtonite Offline Sync Protocol\n\n1. Buffer mutations in local WAL.\n2. Reconnect handshake with version clock.\n"
            ),
        ]

        for filename, desc, team, task, uploader, content in docs_def:
            doc = SharedDocument.objects.filter(team=team, original_filename=filename).first()
            if not doc:
                doc = SharedDocument(
                    team=team,
                    task=task,
                    uploader=uploader,
                    original_filename=filename,
                    description=desc,
                    file_size=len(content),
                    content_type='application/octet-stream'
                )
                doc.file.save(filename, ContentFile(content), save=True)
                ActivityEvent.objects.create(
                    actor=uploader,
                    team=team,
                    task=task,
                    event_type=EventType.DOCUMENT_UPLOADED,
                    details=f"Shared document uploaded: '{filename}' ({doc.human_size}) to {'Task #' + str(task.id) if task else 'General'} by {uploader.username}.",
                    new_state={'filename': filename, 'size': doc.file_size}
                )

        self.stdout.write(self.style.SUCCESS("Showcase demo data seeded successfully and verified idempotent!"))
        self.stdout.write("\nShowcase Demonstration Credentials:")
        self.stdout.write("  - System Superuser:  'admin'   / 'AdminPass123!' (Full system admin)")
        self.stdout.write("  - Team Admin:        'alice'   / 'Password123!' (Admin @ Core Platform)")
        self.stdout.write("  - Team Manager:      'bob'     / 'Password123!' (Manager @ Core Platform, Member @ Frontend)")
        self.stdout.write("  - Team Member:       'charlie' / 'Password123!' (Member @ Core Platform, Admin @ Mobile)")
        self.stdout.write("  - Invitee User:      'fiona'   / 'Password123!' (Member @ Core, Pending invite to Frontend)")
        self.stdout.write("  - Isolated User:     'george'  / 'Password123!' (Member @ Operations Support)")
        self.stdout.write("  - Frontend Lead:     'diana'   / 'Password123!' (Admin @ Frontend Engineering)")
