"""
Resetting a live application to 'Submitted'.

Back End/portal/override/rollback.py

A rollback is the only destructive action in Admin Mode. Everything else
this package does is a correction that can be corrected again; this one
clears columns, quarantines files and cannot be undone from the dashboard.

WHAT IS DECLARED RATHER THAN DERIVED
The three lists below are written out in full instead of being computed
from a rule such as "every column the pipeline writes". A rule would
quietly pick up any column added to `applications` next year and start
clearing it without anyone deciding that it should be cleared. These lists
pick up nothing they were not told about, which is the correct direction
for a destructive action to fail in.

WHAT THIS MODULE DOES NOT DO
It does not save the application row, set its status, write the audit
ledger, write the timeline, or re-render queued notifications. The endpoint
does all of that, so the whole override lands in one transaction and one
audit story rather than in pieces this function cannot see the shape of.
"""

from django.db.models import Q

from portal.models import (
    ApplicationDocumentRequirements, Documents, DocumentTypes)


# ==============================================================================
# WHAT A RESET TO 'Submitted' CLEARS
# ==============================================================================

# Set to NULL on the applications row.
APPLICATION_CLEAR_NULL = (
    'offer_letter_issued_at',
    'offer_letter_signed_by_user_id',
    'offer_letter_signature_path',
    'handover_completed_at',
    'mentor_evaluation_result',
    'mentor_evaluation_remarks',
    'project_report_title',
    'clearance_submitted_at',
    'certificate_issued_at',
    'certificate_signed_by_user_id',
    'certificate_signature_path',
    'certificate_dispatched_at',
    'certificate_email_status',
    'rejection_category',
    'form_correction_remarks',
    'approval_reference_id',
)

# Set to FALSE on the applications row. Kept apart from the list above
# because these columns are NOT NULL: writing None into them would be an
# IntegrityError, not a clear.
APPLICATION_CLEAR_FALSE = (
    'hardcopy_undertaking_received',
    'hardcopy_attendance_received',
    'attendance_record_verified',
    'project_report_verified',
    'awaiting_referrer_action',
    'is_resubmitted',
)

# All six mutable joining columns.
#
# requested_doj is NOT here. It is the referrer's original request from the
# submitted form -- candidate data rather than something the pipeline
# produced -- and survives a rollback exactly as the candidate's name does.
JOINING_CLEAR_NULL = (
    'allotted_date_of_joining',
    'allotted_sub_department_id',
    'dmra_session_date',
    'actual_date_of_joining',
    'dmra_attended',
    'date_of_completion',
)

# PRESERVED, by requirement: application_status_history (a rollback APPENDS
# a row to it), notifications, application_document_requirements,
# academic_details, students, and every candidate-uploaded document.
#
# DELIBERATELY NOT CLEARED
#   is_no_show, doj_reschedules_count
#     Both record something that actually happened to a real person on a
#     real date. A rollback undoes the PORTAL's processing of an
#     application; it does not undo the candidate having missed their
#     joining date or having already spent their one reschedule. Leaving
#     them standing means a rolled-back application still shows an accurate
#     history, and the one-reschedule rule cannot be reset by rolling an
#     application back and forth.
#
#     A consequence worth stating plainly: a rollback is NOT a clean slate,
#     and the confirmation dialog should not describe it as one.


# ==============================================================================
# THE ROLLBACK
# ==============================================================================

def _clear_application(application):
    """Blank every pipeline column. Returns the names actually changed.

    Only columns that held something are reported. An application rolled
    back from 'Under Verification' never had a certificate, and listing
    fifteen already-empty columns in the ledger would bury the two that
    genuinely changed.
    """
    cleared = []

    for name in APPLICATION_CLEAR_NULL:
        if getattr(application, name, None) is not None:
            setattr(application, name, None)
            cleared.append(name)

    for name in APPLICATION_CLEAR_FALSE:
        if getattr(application, name, False):
            setattr(application, name, False)
            cleared.append(name)

    return cleared


def _clear_joining(application):
    """Blank the six mutable joining columns. Returns the names changed.

    Saved here rather than by the caller: joining_details is a separate row
    with its own lifetime, and an application that never reached scheduling
    has no joining row at all.
    """
    joining = getattr(application, 'joiningdetails', None)
    if joining is None:
        return []

    cleared = []
    columns = []

    for name in JOINING_CLEAR_NULL:
        if getattr(joining, name, None) is not None:
            setattr(joining, name, None)
            columns.append(name)
            cleared.append('joining_details.' + name)

    if columns:
        joining.save(update_fields=columns)

    return cleared


def form_document_names(application):
    """The document types the REFERRAL FORM asked this candidate to upload.

    Read from application_document_requirements, the per-application snapshot
    frozen at submission. That snapshot is the only honest answer to "what did
    this candidate actually submit", because the form's document list is
    configured per cycle: a document added to the form this cycle is in this
    application's snapshot and a document dropped from it is not, regardless
    of what document_types says today.

    document_types.is_core is the fallback and NOT the primary test. It
    describes what is offered by default, not what this application was
    asked for.
    """
    names = set(
        ApplicationDocumentRequirements.objects
        .filter(application=application)
        .values_list('doc_type_name', flat=True))

    if names:
        return names

    # No snapshot: an application predating the requirements table, or one
    # whose rows were lost. Fall back to the default core set rather than
    # quarantining every document the candidate ever uploaded.
    return set(
        DocumentTypes.objects.filter(is_core=1)
        .values_list('type_name', flat=True))


def _quarantine_non_form_documents(application, now, quarantine_file):
    """Withdraw every document that did NOT come in on the referral form.

    THE LINE IS WHERE A DOCUMENT CAME FROM, NOT WHAT MADE IT.
    A rollback returns an application to the moment after the referrer
    submitted it. Everything the portal accumulated after that point --
    Annexure B, the mentor's evaluation, a DMRA exemption letter, the offer
    letter, the certificate -- belongs to a pipeline run that no longer
    happened, and leaving any of it attached means the record claims a
    history it no longer has.

    An earlier version of this quarantined only the two GENERATED documents.
    That was too narrow: it kept every file HR had uploaded during the
    internship, so a rolled-back application sat at Submitted still carrying
    a signed Annexure B for an internship that had been undone.

    CANDIDATE UPLOADS ARE UNTOUCHED. Their photograph, signature, college ID,
    Aadhaar and recommendation letter are the candidate's own evidence and
    are exactly what the form collected. Keeping them is the whole reason a
    rollback is survivable: the candidate does not have to submit anything
    again.

    PENDING CORRECTIONS GO TOO. A corrected offer letter awaiting HR-APP sits
    at is_current NULL / is_pending_approval 1, so an is_current filter alone
    misses it. Leaving it would drop an approval into HR-APP's queue for an
    application that has been rolled back.

    quarantine_file is INJECTED rather than imported: _quarantine_file()
    lives in views.py, and importing it here would make portal.override
    depend on portal.views while views.py imports portal.override -- a
    circular import. Passing it in also means this function can be tested
    without touching the filesystem.

    Returns a list of dicts, one per quarantined row, for the ledger.
    """
    keep = form_document_names(application)
    quarantined = []

    rows = Documents.objects.filter(
        application=application
    ).filter(
        Q(is_current=1) | Q(is_pending_approval=1)
    ).exclude(
        doc_type__type_name__in=keep
    ).select_related('doc_type')

    for row in rows:
        moved_to = quarantine_file(row.file_path)

        row.is_current = None
        row.is_pending_approval = None
        row.superseded_at = now
        row.save(update_fields=[
            'is_current', 'is_pending_approval', 'superseded_at'])

        quarantined.append({
            'document': row,
            'doc_type_name': row.doc_type.type_name,
            'quarantined_to': moved_to,
        })

    return quarantined


def perform_rollback(application, *, quarantine_file, now):
    """Reset a live application to 'Submitted'.

    Must be called inside a transaction, and inside one the caller owns:
    this function writes to joining_details and documents but leaves the
    application row unsaved, so a caller that does not save it will leave
    the record half-cleared.

    Returns (cleared_field_names, quarantined_documents).
    """
    cleared = _clear_application(application)
    cleared += _clear_joining(application)
    quarantined = _quarantine_non_form_documents(
        application, now, quarantine_file)
    return cleared, quarantined