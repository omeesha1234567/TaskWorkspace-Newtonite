from .models import InAppNotification, WorkspaceInvitation
from .services import AuditTrackingService


def global_context(request):
    """
    Context processor to inject unread notification count, pending workspace
    invitation count, and unread audit indicator into all template contexts for authenticated users.
    """
    if not request.user.is_authenticated:
        return {
            'unread_notifications_count': 0,
            'pending_invitations_count': 0,
            'recent_notifications': [],
            'has_unread_audit': False,
        }

    unread_count = InAppNotification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()

    pending_invitations_count = WorkspaceInvitation.objects.filter(
        invitee_user=request.user,
        status='PENDING'
    ).count()

    # If the user has an email, also check for invitations matching their email directly
    if request.user.email and pending_invitations_count == 0:
        pending_invitations_count = WorkspaceInvitation.objects.filter(
            invitee_email__iexact=request.user.email,
            status='PENDING'
        ).count()

    recent_notifications = InAppNotification.objects.filter(
        recipient=request.user
    ).select_related('actor', 'task', 'team').order_by('-created_at')[:5]

    has_unread_audit = AuditTrackingService.has_unread_activity(request.user)

    return {
        'unread_notifications_count': unread_count,
        'pending_invitations_count': pending_invitations_count,
        'recent_notifications': recent_notifications,
        'has_unread_audit': has_unread_audit,
    }

