"""
What a rollback cannot undo.

Back End/portal/override/warnings.py

The confirmation dialog exists because a rollback is reversible in the
database and not in the world. These counts are the parts that have already
left the portal, plus the two things that survive a rollback and are easy
to assume do not.

READ-ONLY. Nothing here writes, so the GET that feeds the dialog is safe to
call as often as the screen likes.
"""

from django.db.models import Q

from portal.models import Documents, Notifications
from portal.override.rollback import form_document_names


def rollback_warnings(application):
    """Counts and flags for the confirmation dialog."""
    emails_sent = Notifications.objects.filter(
        application=application, delivery_status='Sent').count()

    emails_pending = Notifications.objects.filter(
        application=application, delivery_status='Pending').count()

    # Counted by the SAME rule the rollback uses, so the number in the dialog
    # is the number of files that will actually be withdrawn. Anything the
    # referral form did not ask for goes: not just the generated letter and
    # certificate, but Annexure B, the mentor's evaluation and anything else
    # HR attached during the internship.
    documents_to_quarantine = Documents.objects.filter(
        application=application
    ).filter(
        Q(is_current=1) | Q(is_pending_approval=1)
    ).exclude(
        doc_type__type_name__in=form_document_names(application)
    ).count()

    return {
        # "N emails have already been sent to the candidate and the
        #  referrer. Rolling back does not recall them."
        'emails_already_sent': emails_sent,

        # Re-rendered in place rather than discarded, so worth stating
        # separately: these WILL go out reflecting the corrected record.
        'emails_still_queued': emails_pending,

        # "The candidate has already handed over signed hard copies. Those
        #  pages are in a filing cabinet, not in this system."
        'hardcopy_handed_over': bool(
            application.hardcopy_undertaking_received
            or application.hardcopy_attendance_received),

        # "A signed certificate has already been issued." If it was also
        #  dispatched, the candidate is holding it and no rollback reaches
        #  it.
        'certificate_issued': application.certificate_issued_at is not None,
        'certificate_dispatched': application.certificate_dispatched_at is not None,

        # Every file added after submission, generated or uploaded by HR.
        'documents_to_quarantine': documents_to_quarantine,

        # NOT cleared by a rollback, and easy to assume otherwise. A
        # rollback is not a clean slate: the candidate keeps whatever
        # reschedules they have already spent, and a recorded no-show
        # stands.
        'reschedules_already_spent': application.doj_reschedules_count or 0,
        'no_show_recorded': bool(application.is_no_show),
    }