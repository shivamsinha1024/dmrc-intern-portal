"""Queueing a notification. This is the function views.py calls.

    from portal.notifications.queue import queue_notification
    from portal.notifications import types as ntypes

    queue_notification(application, ntypes.APPLICATION_APPROVED)

A call site says WHAT happened. It does not decide who is written to, what the
email says, or whether it can be sent -- all of that is worked out here and in
recipients.py, so the rule exists in one place and cannot drift between the
twenty-eight endpoints in views.py.

WHAT THIS FUNCTION GUARANTEES

  It always leaves a row, or deliberately none.
      Success queues a Pending row. Any problem it can detect -- a missing
      address, an absent joining date, a routing mistake -- writes a Failed row
      with a reason instead. Nothing is skipped silently. The only case that
      writes nothing is a duplicate, which is reported to the caller.

  It never raises.
      A notification is a consequence of an HR action, not a precondition of it.
      If queueing were allowed to throw, a bug in this module would roll back
      the approval that triggered it and HR would see a 500 for an action that
      was otherwise valid. So everything is caught, recorded and logged.

  It does not send anything.
      Sending is `manage.py send_notifications`. This function only writes a
      row, so it is safe to call inside the transaction that performs the status
      change: if that transaction rolls back, the queued row goes with it.

DUPLICATES

If HR double-clicks Approve, the second call finds an unsent row for the same
(application, type) and returns None instead of queueing a second email.

The guard looks at Pending rows only, and it is here rather than in the database
on purpose. A UNIQUE index would also block the legitimate case: an application
returned for correction twice genuinely needs two "Returned for Correction"
emails, months apart. A Pending row means "this has not gone out yet, and
another one would be the same email twice"; a Sent row from an earlier round of
the same workflow is history and must not block anything.
"""

import logging

from django.db import DatabaseError, transaction
from django.utils import timezone

from ..models import Notifications
from . import content
from .recipients import NotificationRoutingError, resolve_recipient
from .types import ACTIVE_TYPES, STATUS_FAILED, STATUS_PENDING

logger = logging.getLogger('portal')


def queue_notification(application, notification_type):
    """Queue one notification. Returns the row written, or None.

    None means nothing was written and nothing needs to be: either an identical
    email is already waiting to go out, or the row could not be written at all,
    which is logged as an ERROR.

    A returned row may be Pending or Failed. The caller does not need to check
    which -- there is nothing useful it could do about a Failed row -- but the
    row is returned so that a view can log or reference it if it wants to.
    """
    try:
        return _queue(application, notification_type)
    except Exception:
        # Deliberately broad. See the module docstring: this must not be able to
        # break the HR action that triggered it. Anything reaching here is a bug
        # in this package, so it is logged with a traceback rather than
        # swallowed.
        logger.exception(
            'Could not queue a %s notification for application %s. '
            'The action itself succeeded; the email was not queued.',
            notification_type, getattr(application, 'application_id', '?'),
        )
        return None


def _queue(application, notification_type):
    if notification_type not in ACTIVE_TYPES:
        logger.error(
            'Refusing to queue unknown notification type %r for application %s.',
            notification_type, application.application_id,
        )
        return None

    if _already_pending(application, notification_type):
        logger.info(
            'Skipping duplicate %s notification for application %s: one is '
            'already Pending.',
            notification_type, application.application_id,
        )
        return None

    # --- who ---------------------------------------------------------------
    try:
        recipient = resolve_recipient(application, notification_type)
    except NotificationRoutingError as exc:
        # A programming error: a call site asked for a referrer-facing type on
        # an application with no referrer. Recorded rather than raised, so the
        # HR action completes, but logged at ERROR because it needs fixing.
        logger.error(
            'Routing error queueing %s for application %s: %s',
            notification_type, application.application_id, exc,
        )
        return _write(
            application, notification_type,
            email='', subject=_safe_subject(notification_type),
            message=content.UNCOMPOSED_MESSAGE,
            status=STATUS_FAILED, failure_reason=str(exc),
        )

    # --- what --------------------------------------------------------------
    context = content.build_context(application)
    missing = content.missing_context(notification_type, context)

    if missing or recipient.failure_reason:
        reasons = []
        if recipient.failure_reason:
            reasons.append(recipient.failure_reason)
        if missing:
            reasons.append(
                'Missing data required by this template: '
                + ', '.join(missing)
                + '. Supply it and re-trigger the action.'
            )
        reason = ' '.join(reasons)

        logger.warning(
            'Recording %s notification for application %s as Failed: %s',
            notification_type, application.application_id, reason,
        )

        # The body is only composed when it can be composed completely. A
        # half-filled template is not something to keep.
        message = (
            content.UNCOMPOSED_MESSAGE if missing
            else content.render_body(notification_type, context)
        )
        return _write(
            application, notification_type,
            email=recipient.email, subject=_safe_subject(notification_type),
            message=message,
            status=STATUS_FAILED, failure_reason=reason,
        )

    return _write(
        application, notification_type,
        email=recipient.email,
        subject=content.render_subject(notification_type, context),
        message=content.render_body(notification_type, context),
        status=STATUS_PENDING, failure_reason=None,
    )


def _already_pending(application, notification_type):
    return Notifications.objects.filter(
        application_id=application.application_id,
        notification_type=notification_type,
        delivery_status=STATUS_PENDING,
    ).exists()


def _write(application, notification_type, *, email, subject, message,
           status, failure_reason):
    """Insert the row. Every path through _queue ends here.

    The INSERT sits in its own atomic block, which matters because the callers
    are views wrapped in @transaction.atomic. Catching a database error inside
    an atomic block without a savepoint leaves the connection marked for
    rollback, and every later query in that request fails with
    TransactionManagementError -- so a failed notification INSERT would take the
    HR action down with it, which is precisely backwards. The inner block makes
    a savepoint: a failure here rolls back this INSERT alone and leaves the
    outer transaction healthy.
    """
    try:
        with transaction.atomic():
            return Notifications.objects.create(
                application_id=application.application_id,
                notification_type=notification_type,
                recipient_email=email[:150],
                subject=subject[:150],
                message=message,
                delivery_status=status,
                # Written explicitly rather than left to the column's
                # DEFAULT CURRENT_TIMESTAMP. The database clock is TiDB's, in
                # UTC; timezone.now() is Django's, and TIME_ZONE is
                # Asia/Kolkata. Setting it here keeps queued_at on the same
                # clock as processed_at and as every other timestamp the portal
                # writes.
                queued_at=timezone.now(),
                # A Failed row was processed the moment it was recorded. It is
                # never picked up again, so leaving processed_at NULL would make
                # it look like it were still waiting for something.
                processed_at=timezone.now() if status == STATUS_FAILED else None,
                failure_reason=(failure_reason or None) and failure_reason[:500],
            )
    except DatabaseError:
        logger.exception(
            'INSERT into notifications failed for application %s, type %s.',
            application.application_id, notification_type,
        )
        raise


def _safe_subject(notification_type):
    """A subject for a row that failed before its context was usable.

    None of HR's subjects contains a placeholder, so rendering one needs no
    context and cannot fail for want of data. If the template file itself is
    missing, fall back to the type name rather than losing the row --
    notifications.subject is NOT NULL.
    """
    try:
        return content.render_subject(notification_type, {})
    except Exception:
        logger.exception('Subject template missing for %s.', notification_type)
        return notification_type[:150]