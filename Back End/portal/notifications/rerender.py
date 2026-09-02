"""Re-rendering PENDING notifications after an Admin Mode correction.

WHY THIS EXISTS

notifications.subject and .message are composed once, at queue time, and
stored -- see content.py's module docstring. That's fine for the ordinary
lifecycle. It stops being fine the moment a SYS-ADMIN corrects a field on the
same application before that email goes out -- the stored text is now
describing a candidate who no longer exists.

Every successful Admin Mode override calls rerender_pending_notifications()
for the application it just changed. It does not need to be told which
fields were edited: recomputing the full context for every Pending row and
overwriting subject/message is always correct and always cheap. If nothing
relevant changed, a row is left exactly as it was -- see the "unchanged"
check in _rerender_one.

WHAT THIS DELIBERATELY DOES NOT DO

  It does not touch Sent or Failed rows, or queued_at.
      Sent is history. A Failed row is a dead end, same as in queue.py.
      queued_at is never touched, so it keeps recording when the email was
      first queued, not when it was last corrected.

  It does not re-resolve the recipient.
      None of the four affected keys can change who the email goes to.

  It does not send anything, and it never raises.
      Same reasoning as queue.py: this runs as a consequence of an admin
      action that has already succeeded. A bug here must not roll back the
      correction that triggered it.
"""

import logging

from django.db import DatabaseError, transaction
from django.utils import timezone

from ..models import Notifications
from . import content
from .types import STATUS_FAILED, STATUS_PENDING

logger = logging.getLogger('portal')


def pending_notification_count(application):
    """How many Pending rows exist for this application right now.

    For the Admin Mode confirmation dialog, BEFORE any edit is made -- e.g.
    "2 notifications are queued and will be updated with the corrected
    details."
    """
    return Notifications.objects.filter(
        application_id=application.application_id,
        delivery_status=STATUS_PENDING,
    ).count()


def rerender_pending_notifications(application):
    """Recompute subject/message for every Pending row on this application.

    Call this AFTER an Admin Mode override has been saved. Safe to call from
    inside the same @transaction.atomic block as the edit -- each row is
    written in its own savepoint (see _write), so a problem with one row
    cannot roll back the edit itself.

    Returns the rows this actually changed. Rows left alone because nothing
    relevant changed are not included. Never raises.
    """
    touched = []
    pending_rows = Notifications.objects.filter(
        application_id=application.application_id,
        delivery_status=STATUS_PENDING,
    )
    for row in pending_rows:
        try:
            if _rerender_one(application, row):
                touched.append(row)
        except Exception:
            # Deliberately broad, matching queue.py: a bug here must not
            # undo the admin correction that triggered it.
            logger.exception(
                'Could not re-render notification %s (application %s) '
                'after an admin correction. The correction itself was '
                'saved; this row was left exactly as it was.',
                row.notification_id, application.application_id,
            )
    return touched


def _rerender_one(application, row):
    """Recompute one row in place. Returns True if it was written."""
    context = content.build_context(application)
    missing = content.missing_context(row.notification_type, context)

    if missing:
        new_subject = _safe_subject(row.notification_type)
        new_message = content.UNCOMPOSED_MESSAGE
        new_status = STATUS_FAILED
        new_reason = (
            'An admin correction left this template missing required '
            'data: ' + ', '.join(missing) + '.'
        )
    else:
        new_subject = content.render_subject(row.notification_type, context)
        new_message = content.render_body(row.notification_type, context)
        new_status = STATUS_PENDING
        new_reason = None

    if (row.subject == new_subject and row.message == new_message
            and row.delivery_status == new_status):
        return False  # Nothing relevant changed -- skip the write.

    return _write(row, subject=new_subject, message=new_message,
                  status=new_status, failure_reason=new_reason)


def _write(row, *, subject, message, status, failure_reason):
    """Save the row in its own atomic block -- same reason as queue.py's
    _write: an UPDATE that fails inside an atomic block with no savepoint
    marks the WHOLE outer transaction for rollback. This makes the row's
    UPDATE its own savepoint, so a failure here rolls back only this row.
    """
    try:
        with transaction.atomic():
            row.subject = subject[:150]
            row.message = message
            row.delivery_status = status
            row.failure_reason = (
                (failure_reason or None) and failure_reason[:500]
            )
            if status == STATUS_FAILED:
                row.processed_at = timezone.now()
            row.save(update_fields=[
                'subject', 'message', 'delivery_status',
                'failure_reason', 'processed_at',
            ])
        return True
    except DatabaseError:
        logger.exception(
            'UPDATE on notifications failed for row %s while re-rendering '
            'after an admin correction.', row.notification_id,
        )
        raise


def _safe_subject(notification_type):
    """Same fallback as queue.py's _safe_subject. Duplicated rather than
    imported because it's a private helper of that module -- if you'd
    rather share one copy, export it from queue.py or move it into
    content.py and both modules can import it from there.
    """
    try:
        return content.render_subject(notification_type, {})
    except Exception:
        logger.exception('Subject template missing for %s.', notification_type)
        return notification_type[:150]