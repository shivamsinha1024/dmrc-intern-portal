import json
import re
import logging
from types import SimpleNamespace
import io
import pandas as pd
import shutil
from pathlib import Path
from datetime import datetime, date, timedelta, timezone as dt_timezone
from django.conf import settings
from django.utils import timezone
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.http import HttpResponse, FileResponse, Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction, IntegrityError
from portal.notifications import types as ntypes
from portal.notifications.queue import queue_notification
# Q for the archive's search and either-date filters; F for ordering that keeps
# blank dates at the bottom whichever way a column is sorted.
from django.db.models import Q, F
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

# Audit failures are reported here rather than silently swallowed.
logger = logging.getLogger(__name__)


# Correctly import all models globally
from .identity import get_identity, is_development_identity
from .permissions import (
    employee_required, role_required, ALL_HR_ROLES, ROLE_HIERARCHY,
)
from .documents.formatting import completion_date, salutation_for
from .documents.offer_letter import (
    build_offer_letter_docx, build_offer_letter_pdf,
)
from .documents.certificate import (
    build_completion_certificate_docx, build_completion_certificate_pdf,
)
from .documents.stamp import stamp_signature
from .models import (
    Students, Applications, AcademicDetails, Departments, 
    InternshipCycles, Documents, DocumentTypes, JoiningDetails, 
    ApplicationStatusHistory, CycleJoiningDates, CycleDepartmentCapacities, 
    SubDepartments, CycleSubDepartments, CycleDocumentRequirements,
    Users, Roles, Employees, SystemAuditLogs, ApplicationDrafts,
    ApplicationDocumentRequirements, ArchivedApplications, Notifications,
    ArchivedAcademicDetails, ArchivedDocuments,
    ArchivedStatusHistory, ArchivedDocumentRequirements,
    ArchivedCycleJoiningDates
)

# --- Universal Helpers ---
def safe_extract_time(obj, attr_name, format_str="%d-%m-%Y %I:%M %p", date_only=False):
    """Render a stored timestamp in the project's configured local timezone.

    Timestamps are stored in UTC (USE_TZ = True). Conversion goes through
    django.utils.timezone.localtime() so that settings.TIME_ZONE stays the
    single source of truth. This previously used a hardcoded +05:30 offset,
    which silently double-converts if TIME_ZONE is ever set to a real zone
    and ignores DST for any non-IST deployment.
    """
    val = getattr(obj, attr_name, None)

    def _fmt(value):
        # Plain dates have no time component and need no zone conversion.
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.strftime("%d-%m-%Y" if date_only else format_str)
        if timezone.is_naive(value):
            value = timezone.make_aware(value, dt_timezone.utc)
        value = timezone.localtime(value)
        return value.strftime("%d-%m-%Y" if date_only else format_str)

    if val:
        if hasattr(val, 'strftime'):
            return _fmt(val)
        if isinstance(val, str):
            try:
                parsed = datetime.strptime(val.split('.')[0].replace('T', ' '), "%Y-%m-%d %H:%M:%S")
                return _fmt(parsed)
            except ValueError:
                return val.split()[0] if date_only else val

    return _fmt(timezone.now())

# ------------------------------------------------------------------------------
# PROTECTED DOCUMENT ACCESS
#
# Referrer-uploaded documents are NOT served as static files. They live outside
# MEDIA_ROOT and are reachable only through SecureDocumentView, which checks the
# caller's role, streams the file inline, and records the access.
#
# What this achieves, honestly stated:
#   * no direct /media/ URL to a candidate's Aadhaar or photograph
#   * links expire, so one copied out of the page stops working
#   * every view is attributable in the audit ledger
#   * Content-Disposition is always inline, never attachment, so the browser
#     displays rather than saves
#
# What it does NOT achieve: a screenshot. Once a document is on screen the
# operating system can capture it, and no web application can prevent that.
# The control here is accountability, not physical impossibility.
#
# System-GENERATED documents (offer letters, certificates) are deliberately
# EXCLUDED: they exist to be printed, signed and circulated.
# ------------------------------------------------------------------------------
_document_signer = TimestampSigner(salt='dmrc.document.view')


def is_generated_document(document):
    """True for output the portal PRODUCED -- offer letters, certificates."""
    doc_type = getattr(document, 'doc_type', None)
    return bool(getattr(doc_type, 'is_system_generated', 0))


def is_protected_document(document):
    """True for every stored document. Nothing is served by URL any more.

    This used to return False for system-generated output, on the reasoning
    that a document meant to be circulated needs no protection. Two things were
    wrong with that:

      1. Those files were written to MEDIA_ROOT, and dmrc_core/urls.py only
         serves MEDIA_ROOT while DEBUG is on. On the intranet DEBUG is off, so
         every offer letter link would have returned 404 unless somebody
         remembered to configure the web server -- working perfectly in
         development and failing silently in production.

      2. An offer letter carries the candidate's name, college and joining
         date. A URL needing no login is a URL anyone can guess.

    So both kinds now reach HR through this endpoint. They are treated
    DIFFERENTLY once here, which is the distinction that actually matters:

      uploaded  -> watermarked viewer, no download control, every view logged
      generated -> downloaded directly, because HR-OPS has to print it

    See SecureDocumentView.
    """
    return True


def document_view_token(document_id):
    return _document_signer.sign(str(document_id))


def document_view_url(document):
    """Short-lived, role-checked URL for one document, or None."""
    if document is None or not document.document_id:
        return None
    return f"/api/documents/view/?t={document_view_token(document.document_id)}"


def archived_document_view_url(archived_doc):
    """Short-lived, role-checked URL for an ARCHIVED document, or None.

    Archived documents are addressed by their archive id with an 'a' prefix. The
    live row is gone -- hard-closing a cycle deletes it -- so the viewer cannot
    look them up in `documents` and needs to know which table to read.
    """
    if archived_doc is None or not archived_doc.archive_doc_id:
        return None
    token = _document_signer.sign(f"a{archived_doc.archive_doc_id}")
    return f"/api/documents/view/?t={token}"


# NOTE: protected_storage_path() has been replaced by stored_document_path(),
# which searches all three storage roots rather than two. See the block below
# supersede_document().


# ------------------------------------------------------------------------------
# DOCUMENT VAULT HELPERS  (versioning -- see documents table in Intern_Portal.sql)
#
# A document is never mutated or deleted in place. Uploading a replacement
# SUPERSEDES the previous one. Exactly one live row exists per
# (application, doc_type), enforced by the uq_doc_current index.
#
# RULE: never query Documents.objects directly in a view. Read through
# current_documents() and write through supersede_document(). Any read that
# forgets is_current=1 would resurrect a superseded file somewhere in the UI,
# which is the exact failure this design exists to prevent.
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# SEAT OCCUPANCY
#
# Computed live from the applications table rather than read from the stored
# cycle_department_capacities.seats_occupied counter, which nothing ever
# incremented and which drifts the moment any status changes outside the one
# code path that maintains it.
#
# WARD APPLICATIONS DO NOT CONSUME A SEAT. A direct ward of a DMRC employee is
# admitted outside the departmental quota, so they are excluded from the count
# and can never trigger a waitlist.
#
# INSTITUTIONAL APPLICATIONS DO NOT CONSUME A SEAT EITHER, for the same reason:
# a candidate arriving under a college arrangement is admitted outside the
# departmental quota. They are excluded from the count and can never trigger a
# waitlist, exactly as a ward cannot.
#
# A bounced application (Rejected + awaiting_referrer_action) KEEPS its seat:
# it is coming back, and releasing the seat would let the department overfill
# while the referrer is still correcting it.
# ------------------------------------------------------------------------------
NON_OCCUPYING_STATUSES = {
    'Draft',            # never submitted
    'Intake Draft',     # institutional staging, not yet a real application
    'Ready for Merge',  # ditto
}


def department_occupancy(cycle):
    """Seats consumed per department name for one cycle."""
    if cycle is None:
        return {}

    applications = (Applications.objects
                    .filter(cycle=cycle, is_ward=0)
                    .exclude(referral_source='Institutional')
                    .exclude(status__in=NON_OCCUPYING_STATUSES)
                    .select_related('department'))

    counts = {}
    for app in applications:
        # A final rejection frees the seat; a bounce awaiting the referrer does not.
        if app.status == 'Rejected' and not getattr(app, 'awaiting_referrer_action', False):
            continue
        name = getattr(app.department, 'department_name', None)
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


# ------------------------------------------------------------------------------
# DOCUMENT CONFIGURATION
#
# Documents are DATA, not code. The admin dashboard decides which exist, and
# every screen renders whatever is configured. Nothing is keyed by name any
# more: doc_type_id is the identifier, so renaming a document is safe.
#
# Two classes:
#   CORE    the five shipped documents. Always listed, toggled active/inactive,
#           never deleted -- historical applications and the archive assume
#           they can exist.
#   CUSTOM  added by an administrator. Deletable ONLY while unused; once any
#           application has uploaded against one it can only be disabled,
#           otherwise files are orphaned and archived records lose meaning.
#
# An application is judged against the rules in force WHEN IT WAS SUBMITTED.
# Those are frozen into application_document_requirements at submission, so
# mid-cycle changes never invalidate work already done.
# ------------------------------------------------------------------------------
# NOTE: the core documents are identified by document_types.is_core, NOT by a
# list in code. A hardcoded list here would drift from the database the first
# time an administrator changed anything.


def document_slug(doc_type_id):
    """Stable key used by the front ends for one document slot."""
    return f"doc_{doc_type_id}"


def document_slug_for_name(type_name):
    """Fallback key for a document slot whose type id is unknown.

    Used only by the archive, and only for rows that predate doc_type_id being
    carried into archived_documents -- or whose type was deleted from the
    catalogue before the id could be recorded. Derived from the NAME, so a
    requirement and the file that satisfied it still produce the same key and
    still pair up in the drawer.

    Never used for live documents: those always have a type id.
    """
    cleaned = re.sub(r'[^a-z0-9]+', '_', (type_name or '').strip().lower())
    return f"docname_{cleaned.strip('_')}"


# How many rows are sent to the database per INSERT when archiving.
#
# Archiving used to insert one row at a time. At DMRC's volumes -- 500 to 2,000
# applications, each carrying documents, requirements and a timeline -- that is
# tens of thousands of statements inside a single transaction, and TiDB caps
# both the statement count and the total size of one. A full-size cycle could
# fail outright, and even where it succeeded the round trips alone could outlast
# the web server's timeout.
#
# 500 is deliberately conservative: large enough that the statement count stops
# being the binding constraint, small enough that no single INSERT approaches a
# packet size limit.
ARCHIVE_BATCH_SIZE = 500


def serialize_rule(doc_type, is_mandatory=True, order=0, allowed_extensions=None):
    """One document rule in the shape both front ends consume.

    allowed_extensions comes from the CYCLE's own configuration when present.
    The value on document_types is only the catalogue default, used before a
    cycle has said otherwise.
    """
    return {
        "id": doc_type.doc_type_id,
        "key": document_slug(doc_type.doc_type_id),
        "name": doc_type.type_name,
        "format": allowed_extensions or doc_type.allowed_extensions or '.pdf,.jpg,.jpeg',
        "isMandatory": bool(is_mandatory),
        "requiresConsent": bool(getattr(doc_type, 'requires_consent', 0)),
        "isCore": bool(getattr(doc_type, 'is_core', 0)),
        "order": order,
    }


def active_document_rules(cycle):
    """Documents a NEW application must supply for this cycle.

    Configured requirements win; a cycle with none configured falls back to the
    active core documents so a partially set-up database still yields a usable
    form rather than an empty vault.
    """
    rules = []
    if cycle is not None:
        # Filtered on the CYCLE's own is_enabled, not the catalogue's is_active.
        # Disabling a document for one cycle must leave every other running
        # cycle untouched -- previously it removed the document everywhere.
        requirements = (CycleDocumentRequirements.objects
                        .filter(cycle=cycle, is_enabled=True)
                        .select_related('doc_type')
                        .order_by('doc_type_id'))
        for order, req in enumerate(requirements):
            doc_type = req.doc_type
            if doc_type is None or doc_type.is_system_generated:
                continue
            rules.append(serialize_rule(doc_type, req.is_mandatory, order,
                                        req.allowed_extensions))

    if not rules:
        defaults = (DocumentTypes.objects
                    .filter(is_core=1, is_active=1, is_system_generated=0)
                    .order_by('doc_type_id'))
        rules = [serialize_rule(dt, True, i) for i, dt in enumerate(defaults)]
    return rules


def cycle_accepts_submissions(cycle):
    """Whether an application may be submitted to this cycle right now.

    Enforced on the SERVER because the browser's version of this rule can be
    bypassed: a page left open past the closing date, a resumed draft, or simply
    a crafted request. An archived cycle is refused outright -- its applications
    have already been moved out and its records closed.

    Returns (allowed, reason).
    """
    if cycle is None:
        return False, "No cycle was specified for this application."
    if not cycle.is_active:
        return False, (f"{cycle.session_term} {cycle.application_year} has been closed and "
                       f"archived. It is no longer accepting applications.")
    today = timezone.localdate()
    if cycle.application_start_date and today < cycle.application_start_date:
        return False, (f"{cycle.session_term} {cycle.application_year} opens on "
                       f"{cycle.application_start_date.strftime('%d-%m-%Y')}.")
    if cycle.application_end_date and today > cycle.application_end_date:
        return False, (f"{cycle.session_term} {cycle.application_year} closed on "
                       f"{cycle.application_end_date.strftime('%d-%m-%Y')}. "
                       f"Applications and saved drafts can no longer be submitted.")
    return True, ""


def snapshot_requirements(application, cycle):
    """Freeze the cycle's document rules onto this application."""
    ApplicationDocumentRequirements.objects.filter(application=application).delete()
    for rule in active_document_rules(cycle):
        ApplicationDocumentRequirements.objects.create(
            application=application,
            doc_type_id=rule['id'],
            doc_type_name=rule['name'],
            allowed_extensions=rule['format'],
            is_mandatory=1 if rule['isMandatory'] else 0,
            requires_consent=1 if rule['requiresConsent'] else 0,
            display_order=rule['order'],
        )


def application_rules(application):
    """The rules THIS application was asked to satisfy.

    Reads the frozen snapshot. Applications created before snapshots existed
    have none, so those fall back to the cycle's current configuration.
    """
    rows = (ApplicationDocumentRequirements.objects
            .filter(application=application)
            .order_by('display_order', 'requirement_id'))
    if rows:
        return [{
            "id": r.doc_type_id,
            "key": document_slug(r.doc_type_id) if r.doc_type_id else f"doc_{r.requirement_id}",
            "name": r.doc_type_name,
            "format": r.allowed_extensions,
            "isMandatory": bool(r.is_mandatory),
            "requiresConsent": bool(r.requires_consent),
            "order": r.display_order,
        } for r in rows]
    return active_document_rules(getattr(application, 'cycle', None))


def document_type_in_use(doc_type):
    """True if any application has ever uploaded against this type.

    Guards permanent deletion: removing a type still referenced by documents
    would orphan files on disk and leave archived records pointing at nothing.
    """
    return (Documents.objects.filter(doc_type=doc_type).exists()
            or ApplicationDocumentRequirements.objects.filter(doc_type=doc_type).exists())


# ------------------------------------------------------------------------------
# DEFAULT DOCUMENT SET
#
# The documents a cycle starts with, and the only ones an applicant uploads.
# A SYS-ADMIN may add more during cycle initialisation or later from Edit
# Ruleset -- this is the starting point, not a limit.
#
# The wider document_types catalogue still holds Annexure B, Mentor's
# Evaluation, DMRA Exemption Letter and the system-generated Offer Letter and
# certificates. Those are produced or collected at other stages and must not
# appear in the applicant's upload vault.
#
# Documents are keyed by doc_type_id everywhere, so renaming one is safe.
# ------------------------------------------------------------------------------
# NOTE: defaults come from a query on is_core, not from a list in code, so the
# form always reflects what the administrator has actually configured.


def canonical_action_remark(bounce_category, is_admin_escalated, hr_remark):
    """The single wording for an HR action, stored once and read everywhere.

    Composed on the server so the drawer, the applicant timeline and the audit
    ledger cannot drift apart. The HR officer's own words are preserved after
    the prefix, since that is what explains the decision.
    """
    if bounce_category == 'No Show':
        return 'No Show: Escalated to ADMIN' if is_admin_escalated else 'No Show: Returned to Referrer'
    if bounce_category == 'Invalid Document':
        note = (hr_remark or '').strip()
        return f'Correction Requested: {note}' if note else 'Correction Requested.'
    return (hr_remark or '').strip()


def referrer_facing_remark(stored_remark):
    """How the same event reads in the REFERRER's portal.

    Most remarks are shown verbatim. A no-show is phrased from the referrer's
    point of view -- they need to know the candidate did not report, not the
    internal routing that followed.
    """
    text = stored_remark or ''
    if text.startswith('No Show:'):
        return 'Marked as No-Show.'
    return text


def is_resubmission_entry(history_row):
    """True when a 'Submitted' history row is a RESUBMISSION, not the original.

    Both land on status 'Submitted', so they are distinguished by the recorded
    remark. Keeping this in one function means the applicant timeline and the HR
    drawer can never disagree about what an entry means.
    """
    return ((history_row.remarks or '').lower().startswith('resubmitted')
            and history_row.new_status in ('Submitted', 'Ready for Merge'))


# What a resubmission says on the timeline, by the reason it was sent back.
RESUBMISSION_REMARKS = {
    'Invalid Document': 'Resubmitted after correction.',
    'No Show':          'Resubmitted after DOJ change.',
}

# Short labels for the resubmission badges shown in the HR queue.
RESUBMISSION_BADGES = {
    'Invalid Document': 'Resubmitted: Correction',
    'No Show':          'Resubmitted: DOJ',
}


# Human-readable timeline headings. The raw status is a database value; these
# are what a referrer or HR officer actually reads. Anything not listed falls
# back to "Status: <value>", so a new status is never hidden.
TIMELINE_TITLES = {
    'Submitted': 'Application Submitted',
    'Under Verification': 'Under Verification',
    'Approved': 'Application Approved',
    'Rejected': 'Returned by HR',
    'Scheduled': 'Joining Date Allotted',
    'Pending Offer Letter': 'Awaiting Offer Letter',
    'Pending Offer Re-Approval': 'Offer Sent for Re-Approval',
    'Offer Ready': 'Offer Letter Ready',
    'Pending Arrival': 'Awaiting Arrival',
    'Joined': 'Internship Started',
    'Fix Joining': 'Correction Requested',
    'Fix Clearance': 'Clearance Correction Requested',
    'Pending Certificate': 'Awaiting Completion Certificate',
    'Pending Dispatch': 'Awaiting Dispatch',
    'Completed': 'Internship Completed',
    'Intake Draft': 'Institutional Intake Started',
    'Ready for Merge': 'Ready for Merge',
}


# ------------------------------------------------------------------------------
# DRAFT HELPERS
#
# Draft files live under MEDIA_ROOT/draft_documents/<draft_id>/ and are true
# overwrites: a draft is not yet part of the audit trail, so replacing a file
# deletes the previous one outright. The versioning and quarantine rules in
# `documents` apply only after submission.
# ------------------------------------------------------------------------------
DRAFT_MEDIA_PREFIX = 'draft_documents'


def draft_dir(draft_id):
    return Path(settings.MEDIA_ROOT) / DRAFT_MEDIA_PREFIX / str(draft_id)


def delete_draft_file(relative_path):
    """Remove a draft file from disk. Silent if already gone."""
    if not relative_path:
        return
    target = Path(settings.MEDIA_ROOT) / str(relative_path)
    try:
        if target.exists():
            target.unlink()
    except OSError:
        pass


def purge_draft(draft):
    """Delete a draft and every file it owns."""
    folder = draft_dir(draft.draft_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    draft.delete()


def purge_drafts_for_closed_cycles():
    """Remove drafts belonging to cycles that are no longer active.

    A draft for a closed cycle can never be submitted, so it is dead weight
    holding uploaded files on disk. Called whenever cycles are modified, which
    avoids requiring a scheduler on the intranet deployment.
    """
    stale = ApplicationDrafts.objects.exclude(cycle__isnull=True).filter(cycle__is_active=0)
    count = 0
    for draft in stale:
        purge_draft(draft)
        count += 1
    return count


def serialize_draft(draft):
    payload = draft.payload if isinstance(draft.payload, dict) else json.loads(draft.payload or '{}')
    return {
        "id": draft.draft_id,
        "tab": "saved",
        "status": "Draft",
        "ticketId": "DRAFT",
        "candidateName": draft.candidate_name or payload.get('student', {}).get('fullName', ''),
        "targetCycle": f"{draft.cycle.session_term} {draft.cycle.application_year}" if draft.cycle else "—",
        "cycleId": draft.cycle_id,
        "currentStep": draft.current_step,
        "highestStepReached": draft.highest_step,
        # createdDate is required: the referrer list sorts on it, and a missing
        # value throws inside the comparator, which silently empties EVERY tab.
        "createdDate": safe_extract_time(draft, 'created_at', date_only=True),
        "updatedAt": safe_extract_time(draft, 'updated_at'),
        "student": payload.get('student', {}),
        "academic": payload.get('academic', {}),
        "placement": payload.get('placement', {}),
        "documents": payload.get('documents', {}),
    }


# ------------------------------------------------------------------------------
# REFERRER BOUNCE-BACK
#
# A "Request Correction" or "No Show -> Send to Referrer" parks an application
# with status='Rejected' so it appears in the HR Rejected tab, and sets
# awaiting_referrer_action so the referrer portal knows it is actionable rather
# than closed. Both facts are derived here and nowhere else -- an earlier
# version hardcoded status names ('Returned', 'Pending Correction') that never
# existed in the ENUM, so bounced applications silently never reached the
# referrer. Deriving it in one place prevents that class of drift.
# ------------------------------------------------------------------------------

# rejection_category values that represent a recoverable bounce-back rather
# than a terminal rejection.
BOUNCE_CATEGORIES = {
    'Invalid Document': 'Document Correction Required',
    'No Show': 'Joining No-Show — Response Required',
}


def is_awaiting_referrer(application):
    """True when the referrer must act before this application can progress."""
    return bool(getattr(application, 'awaiting_referrer_action', False))


def referrer_tab_for(application):
    """Which tab the referrer portal should file this application under."""
    if is_awaiting_referrer(application):
        return 'reopened'
    return 'submitted'


def bounce_reason_label(application):
    """Human-readable reason an application was sent back, or None."""
    if not is_awaiting_referrer(application):
        return None
    return BOUNCE_CATEGORIES.get(
        application.rejection_category,
        'Correction Required'
    )


def current_documents(application):
    """Live version of every document category for one application."""
    return Documents.objects.filter(
        application=application, is_current=1
    ).select_related('doc_type')


def current_document(application, doc_type):
    """Live document for a single category, or None."""
    return Documents.objects.filter(
        application=application, doc_type=doc_type, is_current=1
    ).first()


def _quarantine_file(relative_path):
    """Move a superseded file out of MEDIA_ROOT into QUARANTINE_ROOT.

    QUARANTINE_ROOT is not served by Django, so the file becomes unreachable
    by URL and invisible to every role, while remaining recoverable by a
    system administrator with filesystem access. Returns the new absolute
    path, or None if the source file was already gone.
    """
    if not relative_path:
        return None

    # Superseded files may live in ANY of the stores. Searching only the
    # protected and media roots silently missed generated output -- a rejected
    # offer letter stayed sitting in generated_documents/, still on disk and
    # still counted as quarantined by the caller.
    source = None
    for root in (settings.PROTECTED_DOCUMENT_ROOT,
                 settings.GENERATED_DOCUMENT_ROOT,
                 settings.MEDIA_ROOT):
        candidate = Path(root) / str(relative_path)
        if candidate.exists():
            source = candidate
            break
    if source is None:
        return None

    destination = Path(settings.QUARANTINE_ROOT) / str(relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        stamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
        destination = destination.parent / f"{destination.stem}__{stamp}{destination.suffix}"

    shutil.move(str(source), str(destination))
    return str(destination)


def supersede_document(application, doc_type, uploaded_file, *,
                       is_override=False, actor=None, remarks=None):
    """Make uploaded_file the one live document for (application, doc_type).

    Demotes the previous live row (is_current -> NULL, superseded_at stamped),
    quarantines its file, then inserts a new row at version + 1. Every role
    and every screen resolves to this new row immediately, because all reads
    go through current_documents().

    Must be called inside a transaction. Returns the new Documents row.
    """
    ticket = application.application_code or f"DRAFT-{application.application_id}"
    relative = f"intern_documents/{ticket}/{uploaded_file.name}"

    # Nothing is written where Django's static handler could serve it. Referrer
    # uploads go to PROTECTED_DOCUMENT_ROOT, generated output to
    # GENERATED_DOCUMENT_ROOT; both are outside MEDIA_ROOT and both are read
    # back only through SecureDocumentView, which checks the caller's role.
    #
    # Generated output USED to go to media storage on the reasoning that it is
    # meant to be circulated. See is_protected_document() for why that was
    # wrong in two separate ways.
    uploaded_file.seek(0)
    stored_path = write_document_file(
        document_root_for(doc_type), relative, uploaded_file.read()
    )

    previous = current_document(application, doc_type)
    next_version = 1

    if previous:
        next_version = (previous.version or 1) + 1
        quarantined_to = _quarantine_file(previous.file_path)

        previous.is_current = None
        previous.superseded_at = timezone.now()
        previous.save(update_fields=['is_current', 'superseded_at'])

        try:
            with transaction.atomic():
                SystemAuditLogs.objects.create(
                    actor_user=actor,
                    role_name=getattr(getattr(actor, 'role', None), 'role_name', 'SYSTEM'),
                    action_type='DOCUMENT_SUPERSEDED',
                    target_entity_type='Document',
                    target_entity_id=previous.document_id,
                    old_value=json.dumps({
                        "doc_type": doc_type.type_name,
                        "version": previous.version,
                        "file_path": str(previous.file_path),
                        "quarantined_to": quarantined_to,
                    }),
                    new_value=json.dumps({
                        "version": next_version,
                        "file_path": stored_path,
                        "is_manually_overridden": bool(is_override),
                        "remarks": remarks or "",
                    })
                )
        except Exception:
            pass

    return Documents.objects.create(
        application=application,
        doc_type=doc_type,
        file_path=stored_path,
        version=next_version,
        is_current=1,
        is_manually_overridden=bool(is_override),
        verification_status='Pending',
        hr_remarks=remarks or None,
    )


# ==============================================================================
# WHERE A DOCUMENT LIVES
#
# Three roots, none of them served by Django:
#
#   PROTECTED_DOCUMENT_ROOT  referrer and HR uploads (Aadhaar, photo, LOR...)
#   GENERATED_DOCUMENT_ROOT  output the portal produced (offer letters)
#   SIGNATURE_ROOT           HR-APP signature images
#
# MEDIA_ROOT still holds draft uploads and anything written before protected
# storage existed, which is why the read paths below fall back to it.
# ==============================================================================

def document_root_for(doc_type):
    """The storage root a document of this type belongs in."""
    if bool(getattr(doc_type, 'is_system_generated', 0)):
        return Path(settings.GENERATED_DOCUMENT_ROOT)
    return Path(settings.PROTECTED_DOCUMENT_ROOT)


def write_document_file(root, relative_path, data):
    """Write bytes under `root`, never overwriting an existing file.

    A colliding name gets a numeric suffix rather than replacing what is there:
    the row that points at the old file may still be referenced by the archive,
    and silently overwriting it would corrupt a record nobody is looking at.

    Returns the path relative to `root`, which is what goes in the database.
    """
    destination = Path(root) / str(relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    base, suffix = destination.stem, destination.suffix
    counter = 1
    while destination.exists():
        destination = destination.parent / f"{base}_{counter}{suffix}"
        counter += 1

    with open(destination, 'wb') as handle:
        handle.write(data)
    return str(destination.relative_to(Path(root)))


def stored_document_path(document):
    """Absolute path of a stored document, or None if the file is gone.

    Checks the root that matches the document's type first, then the other two,
    so a file written before this split existed is still found. Order matters
    only for speed; a given relative path exists in exactly one of them.
    """
    relative = getattr(document, 'file_path', None)
    if not relative:
        return None

    doc_type = getattr(document, 'doc_type', None)
    roots = [document_root_for(doc_type)]
    for fallback in (settings.PROTECTED_DOCUMENT_ROOT,
                     settings.GENERATED_DOCUMENT_ROOT,
                     settings.MEDIA_ROOT):
        if Path(fallback) not in roots:
            roots.append(Path(fallback))

    for root in roots:
        candidate = Path(root) / str(relative)
        if candidate.exists():
            return candidate
    return None


# ==============================================================================
# THE CORRECTION LOOP
#
# HR-APP signs a generated offer letter. HR-OPS downloads it, and either prints
# it or -- if something is wrong -- corrects the Word copy, exports a PDF and
# uploads that. The corrected file does NOT become official on upload: it waits
# for HR-APP to look at it and approve.
#
# Three states, using the same NULL-distinctness trick documents already relies
# on for is_current (see the documents table in Intern_Portal.sql):
#
#   is_current = 1            the official document
#   is_pending_approval = 1   uploaded, awaiting HR-APP's decision
#   both NULL                 superseded or rejected; never read again
#
# uq_doc_pending means the database itself permits only one pending upload per
# document per application, so HR-OPS cannot stack two corrections and leave
# HR-APP guessing which is live.
# ==============================================================================

def pending_document(application, doc_type):
    """The upload awaiting approval for one category, or None."""
    return Documents.objects.filter(
        application=application, doc_type=doc_type, is_pending_approval=1
    ).select_related('doc_type').first()


def stage_document_for_approval(application, doc_type, uploaded_file, *,
                                actor=None, remarks=None):
    """Store an uploaded file as PENDING. It does not become official here.

    Refuses if something is already pending for this category, rather than
    letting the database's unique index raise: the caller needs a sentence it
    can show HR-OPS, not an IntegrityError.

    Must be called inside a transaction. Returns the new Documents row.
    """
    existing = pending_document(application, doc_type)
    if existing is not None:
        raise ValueError(
            f"A corrected {doc_type.type_name} is already awaiting approval for "
            f"{application.application_code}. It must be approved or returned "
            f"before another can be uploaded."
        )

    ticket = application.application_code or f"DRAFT-{application.application_id}"
    relative = f"intern_documents/{ticket}/{uploaded_file.name}"

    uploaded_file.seek(0)
    stored_path = write_document_file(
        document_root_for(doc_type), relative, uploaded_file.read()
    )

    live = current_document(application, doc_type)
    document = Documents.objects.create(
        application=application,
        doc_type=doc_type,
        file_path=stored_path,
        # One past whatever is live, so the version it WOULD take is visible
        # while it waits. Recomputed on approval in case the live document
        # changed underneath it in the meantime.
        version=((live.version or 1) + 1) if live else 1,
        is_current=None,
        is_pending_approval=1,
        is_manually_overridden=True,
        verification_status='Pending',
        uploaded_by_user=actor,
        hr_remarks=remarks or None,
    )

    _audit(actor, 'DOCUMENT_PENDING_APPROVAL', 'Document', document.document_id,
           new_value={
               "doc_type": doc_type.type_name,
               "application": application.application_code,
               "file_path": stored_path,
           })
    return document


def approve_pending_document(document, actor):
    """Promote a pending upload to the official document for its category.

    Demotes and quarantines whatever was live, exactly as supersede_document()
    does, so the two paths leave the vault in the same shape.

    Must be called inside a transaction.
    """
    application = document.application
    doc_type = document.doc_type

    live = current_document(application, doc_type)
    next_version = ((live.version or 1) + 1) if live else 1

    quarantined_to = None
    if live is not None:
        quarantined_to = _quarantine_file(live.file_path)
        live.is_current = None
        live.superseded_at = timezone.now()
        live.save(update_fields=['is_current', 'superseded_at'])

    document.is_pending_approval = None
    document.is_current = 1
    document.version = next_version
    document.reviewed_by_user = actor
    document.reviewed_at = timezone.now()
    document.approval_remarks = None
    document.save(update_fields=[
        'is_pending_approval', 'is_current', 'version',
        'reviewed_by_user', 'reviewed_at', 'approval_remarks',
    ])

    _audit(actor, 'DOCUMENT_CORRECTION_APPROVED', 'Document', document.document_id,
           old_value={"superseded_document_id": getattr(live, 'document_id', None),
                      "quarantined_to": quarantined_to},
           new_value={"doc_type": getattr(doc_type, 'type_name', ''),
                      "application": application.application_code,
                      "version": next_version})
    return document


def reject_pending_document(document, actor, reason):
    """Return a pending upload to HR-OPS, with a reason they will see.

    The file is quarantined rather than deleted: it is invisible to every role
    and unreachable by URL, but a system administrator can still retrieve it.
    The row stays, so the timeline can show that a correction was refused and
    why.

    Must be called inside a transaction.
    """
    quarantined_to = _quarantine_file(document.file_path)

    document.is_pending_approval = None
    document.is_current = None
    document.superseded_at = timezone.now()
    document.reviewed_by_user = actor
    document.reviewed_at = timezone.now()
    document.approval_remarks = reason
    document.save(update_fields=[
        'is_pending_approval', 'is_current', 'superseded_at',
        'reviewed_by_user', 'reviewed_at', 'approval_remarks',
    ])

    _audit(actor, 'DOCUMENT_CORRECTION_REJECTED', 'Document', document.document_id,
           new_value={"doc_type": getattr(document.doc_type, 'type_name', ''),
                      "application": document.application.application_code,
                      "reason": reason,
                      "quarantined_to": quarantined_to})
    return document


def store_generated_document(application, doc_type, data, filename, *,
                             actor=None, remarks=None):
    """Make freshly generated bytes the official document for a category.

    The generator hands back bytes rather than a file, so this is the same
    operation as supersede_document() without an upload to read.

    Must be called inside a transaction.
    """
    ticket = application.application_code or f"DRAFT-{application.application_id}"
    stored_path = write_document_file(
        document_root_for(doc_type), f"generated/{ticket}/{filename}", data
    )

    previous = current_document(application, doc_type)
    next_version = 1
    quarantined_to = None

    if previous is not None:
        next_version = (previous.version or 1) + 1
        quarantined_to = _quarantine_file(previous.file_path)
        previous.is_current = None
        previous.superseded_at = timezone.now()
        previous.save(update_fields=['is_current', 'superseded_at'])

    document = Documents.objects.create(
        application=application,
        doc_type=doc_type,
        file_path=stored_path,
        version=next_version,
        is_current=1,
        is_manually_overridden=False,
        verification_status='Verified',
        uploaded_by_user=actor,
        hr_remarks=remarks or None,
    )

    _audit(actor, 'DOCUMENT_GENERATED', 'Document', document.document_id,
           old_value={"superseded_document_id": getattr(previous, 'document_id', None),
                      "quarantined_to": quarantined_to} if previous else None,
           new_value={"doc_type": getattr(doc_type, 'type_name', ''),
                      "application": application.application_code,
                      "version": next_version,
                      "file_path": stored_path})
    return document


def _audit(actor, action, entity_type, entity_id, *, old_value=None, new_value=None):
    """Write one ledger entry. Never raises; failures are logged, not swallowed."""
    try:
        with transaction.atomic():
            SystemAuditLogs.objects.create(
                actor_user=actor,
                role_name=getattr(getattr(actor, 'role', None), 'role_name', 'SYSTEM'),
                action_type=action,
                target_entity_type=entity_type,
                target_entity_id=entity_id,
                old_value=json.dumps(old_value) if old_value is not None else None,
                new_value=json.dumps(new_value) if new_value is not None else None,
            )
    except Exception as audit_error:
        logger.error("AUDIT WRITE FAILED (%s): %s",
                     type(audit_error).__name__, audit_error)


# ==============================================================================
# SIGNATURE AUTHORITY
#
# An HR-APP's signature is stamped onto every offer letter they issue, so
# replacing one is an administrative act rather than a preference:
#
#   HR-APP uploads     -> pending, awaiting a SYS-ADMIN
#   SYS-ADMIN approves -> pending becomes active
#   SYS-ADMIN rejects  -> pending quarantined, reason recorded
#
# The ACTIVE signature keeps working throughout. An officer waiting on a
# decision carries on issuing letters with their existing one: work does not
# stop for an approval.
#
# Signature files are the one thing here whose theft lets somebody forge a DMRC
# document, so they live under SIGNATURE_ROOT, outside every served directory,
# and are read from disk only while drawing a letter or being shown to the
# SYS-ADMIN deciding on them.
# ==============================================================================

SIGNATURE_ACTIVE = 'active'
SIGNATURE_PENDING = 'pending'


def signature_absolute_path(relative_path):
    """Absolute path of a stored signature, or None if the file is gone."""
    if not relative_path:
        return None
    candidate = Path(settings.SIGNATURE_ROOT) / str(relative_path)
    return candidate if candidate.exists() else None


def save_signature_upload(user, uploaded_file):
    """Store an uploaded signature as this user's PENDING signature.

    Returns the path relative to SIGNATURE_ROOT. Raises ValueError with a
    message fit to show the user if the file is the wrong type or too large.
    """
    extension = Path(uploaded_file.name).suffix.lower()
    allowed = getattr(settings, 'SIGNATURE_ALLOWED_EXTENSIONS',
                      ('.png', '.jpg', '.jpeg'))
    if extension not in allowed:
        raise ValueError(
            f"A signature must be one of: {', '.join(allowed)}. "
            f"A transparent PNG reproduces best on the letter."
        )

    max_mb = getattr(settings, 'SIGNATURE_MAX_SIZE_MB', 2)
    if uploaded_file.size > max_mb * 1024 * 1024:
        raise ValueError(f"A signature image must be under {max_mb} MB.")

    # Named for the user and stamped, so a replacement never overwrites the
    # file a previously issued letter still points at.
    stamp = timezone.now().strftime('%Y%m%d%H%M%S')
    relative = f"{SIGNATURE_PENDING}/{user.user_id}_{stamp}{extension}"

    uploaded_file.seek(0)
    return write_document_file(
        Path(settings.SIGNATURE_ROOT), relative, uploaded_file.read()
    )


def _quarantine_signature(relative_path):
    """Move a rejected or replaced signature out of SIGNATURE_ROOT."""
    if not relative_path:
        return None
    source = Path(settings.SIGNATURE_ROOT) / str(relative_path)
    if not source.exists():
        return None

    destination = Path(settings.QUARANTINE_ROOT) / 'signatures' / str(relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        stamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
        destination = destination.parent / f"{destination.stem}__{stamp}{destination.suffix}"

    shutil.move(str(source), str(destination))
    return str(destination)


def serialize_signature_state(user):
    """One officer's signature situation, for the dashboard."""
    if user is None:
        return None
    employee = getattr(user, 'employee', None)
    return {
        "userId": user.user_id,
        "name": getattr(employee, 'full_name', ''),
        # 'empId', not 'employeeCode': both dashboards have always called it
        # that, and a serialiser that invents a new name for an existing field
        # renders as a blank space rather than an error.
        "empId": getattr(employee, 'employee_code', ''),
        "designation": getattr(employee, 'designation', ''),
        "role": getattr(getattr(user, 'role', None), 'role_name', ''),
        "status": user.signature_approval_status or 'None',
        "hasActive": bool(user.active_signature_path),
        "hasPending": bool(user.pending_signature_path),
        "activeUrl": signature_view_url(user, SIGNATURE_ACTIVE),
        "pendingUrl": signature_view_url(user, SIGNATURE_PENDING),
        "uploadedAt": safe_extract_time(user, 'signature_uploaded_at'),
        "activatedAt": safe_extract_time(user, 'signature_activated_at'),
        "reviewedAt": safe_extract_time(user, 'signature_reviewed_at'),
        "rejectionReason": user.signature_rejection_reason or '',
        # What the officer can do right now, decided here rather than by the
        # browser re-deriving it from the fields above.
        "canIssue": bool(user.active_signature_path),
        "canUpload": user.signature_approval_status != 'Pending',
    }


_signature_signer = TimestampSigner(salt='dmrc.signature.view')


def signature_view_url(user, kind):
    """Short-lived link to a signature image, or None if there isn't one."""
    path = (user.active_signature_path if kind == SIGNATURE_ACTIVE
            else user.pending_signature_path)
    if not path:
        return None
    token = _signature_signer.sign(f"{user.user_id}:{kind}")
    return f"/api/signatures/image/?t={token}"


# ==============================================================================
# OFFER LETTERS
# ==============================================================================

OFFER_LETTER_TYPE = 'Offer Letter'


def offer_letter_type():
    """The Offer Letter row from the document catalogue, or None."""
    return DocumentTypes.objects.filter(type_name__iexact=OFFER_LETTER_TYPE).first()


def candidate_photo_path(application):
    """Absolute path of the candidate's passport photograph, or None.

    Matched on type NAME rather than on the requirement snapshot, because a
    cycle may legitimately have been configured without a photograph -- in
    which case the letter simply prints an empty box.
    """
    photo = Documents.objects.filter(
        application=application, is_current=1,
        doc_type__type_name__icontains='PASSPORT PHOTO',
    ).select_related('doc_type').first()
    return str(stored_document_path(photo)) if photo else None


def issue_blockers(application, signatory_user):
    """Everything preventing an offer letter from being issued right now.

    Returns human-readable labels, the same shape merge_blockers() uses, so the
    dashboard can say WHY a button is unavailable instead of leaving it greyed
    out with no explanation.

    An empty list means the letter may be signed.
    """
    missing = []

    if application.status != 'Pending Offer Letter':
        missing.append(
            f"Status is '{application.status}' -- an offer letter is issued from "
            f"'Pending Offer Letter'."
        )

    student = getattr(application, 'student', None)
    if not getattr(student, 'full_name', None):
        missing.append('Candidate name')
    if not getattr(student, 'salutation', None) and not getattr(student, 'gender', None):
        missing.append('Candidate title')

    academic = AcademicDetails.objects.filter(application=application).first()
    if not getattr(academic, 'degree_program', None):
        missing.append('Degree / course')
    if not getattr(academic, 'college_name', None):
        missing.append('College')

    if not application.duration_weeks:
        missing.append('Internship duration')

    joining = JoiningDetails.objects.filter(application=application).first()
    if joining is None or not joining.actual_date_of_joining:
        missing.append('Actual date of joining (mark the candidate as arrived first)')
    if joining is None or joining.allotted_sub_department_id is None:
        missing.append('Allotted sub-department')

    # No signature, no issuing. A letter with an empty signature space is worse
    # than no letter at all.
    if signatory_user is None or not signatory_user.active_signature_path:
        missing.append(
            'Your approved signature. Upload one and ask a system administrator '
            'to approve it before issuing letters.'
        )
    elif signature_absolute_path(signatory_user.active_signature_path) is None:
        missing.append('Your signature image is missing from storage. Upload it again.')

    return missing


def build_offer_letter_context(application, signatory_user, *,
                               issued_on=None, signature_path=None):
    """Assemble everything the letter builders need, from the database.

    Values are passed through EXACTLY as stored. The portal's convention is
    upper case throughout, and the letter follows it rather than converting --
    see portal/documents/formatting.py for why title-casing was removed.
    """
    student = getattr(application, 'student', None)
    academic = AcademicDetails.objects.filter(application=application).first()
    joining = JoiningDetails.objects.filter(application=application).first()
    cycle = getattr(application, 'cycle', None)

    start = getattr(joining, 'actual_date_of_joining', None)
    end = completion_date(start, application.duration_weeks)

    sub_department = getattr(
        getattr(joining, 'allotted_sub_department', None), 'sub_department_name', None)

    employee = getattr(signatory_user, 'employee', None)

    if signature_path is None and signatory_user is not None:
        signature_path = signatory_user.active_signature_path
    signature_file = signature_absolute_path(signature_path)

    return {
        'application_code': application.application_code,
        'issued_on': issued_on or timezone.localdate(),
        'salutation': salutation_for(getattr(student, 'salutation', None),
                                     getattr(student, 'gender', None)),
        'candidate_name': getattr(student, 'full_name', ''),
        'course': getattr(academic, 'degree_program', ''),
        'college': getattr(academic, 'college_name', ''),
        'duration_weeks': application.duration_weeks,
        'sub_department': sub_department,
        'start_date': start,
        'end_date': end,
        'session_term': getattr(cycle, 'session_term', ''),
        'application_year': getattr(cycle, 'application_year', ''),
        'signatory_name': getattr(employee, 'full_name', ''),
        'signatory_designation': getattr(employee, 'designation', ''),
        'photo_path': candidate_photo_path(application),
        'signature_path': str(signature_file) if signature_file else None,
    }


def issue_offer_letter(application, signatory_user, *, actor=None):
    """Generate, sign and store the offer letter for one application.

    Records the issue date and the exact signature used, then moves the
    application to 'Offer Ready'. The frozen signature path is what makes a
    reprint next year still carry the signature it was signed with, rather than
    whatever that officer's signature happens to be by then.

    Must be called inside a transaction. Returns the stored Documents row.
    Raises ValueError, carrying a message fit to show HR, if it may not be
    issued.
    """
    blockers = issue_blockers(application, signatory_user)
    if blockers:
        raise ValueError('; '.join(blockers))

    doc_type = offer_letter_type()
    if doc_type is None:
        raise ValueError(
            "The 'Offer Letter' document type is missing from the catalogue. "
            "A system administrator must restore it before letters can be issued."
        )

    issued_on = timezone.localdate()
    signature_path = signatory_user.active_signature_path

    context = build_offer_letter_context(
        application, signatory_user,
        issued_on=issued_on, signature_path=signature_path,
    )

    document = store_generated_document(
        application, doc_type,
        build_offer_letter_pdf(context),
        f"Offer_Letter_{application.application_code}.pdf",
        actor=actor or signatory_user,
        remarks=f"Generated and signed by {context['signatory_name']}.",
    )

    application.offer_letter_issued_at = timezone.now()
    application.offer_letter_signed_by_user = signatory_user
    application.offer_letter_signature_path = signature_path

    # The projected end date is written now rather than recomputed later, so
    # the certificate, the completion report and the archive all agree with
    # what the letter actually says.
    joining, _ = JoiningDetails.objects.get_or_create(application=application)
    if context['end_date'] and not joining.date_of_completion:
        joining.date_of_completion = context['end_date']
        joining.save(update_fields=['date_of_completion'])

    previous_status = application.status
    application.status = 'Offer Ready'
    application.save(update_fields=[
        'offer_letter_issued_at', 'offer_letter_signed_by_user',
        'offer_letter_signature_path', 'status',
    ])

    record_application_event(
        application, actor or signatory_user,
        previous_status=previous_status,
        new_status='Offer Ready',
        remark=f"Offer letter issued and signed by {context['signatory_name']}.",
        audit_action='OFFER_LETTER_ISSUED',
    )
    return document


def resolve_cycle(request, *, required=False):
    """The cycle an administrator is acting on.

    DMRC RUNS CONCURRENT CYCLES, so "the current cycle" is not something the
    server may infer. Every configuration screen sends the cycle it is showing,
    and this returns exactly that.

    The previous behaviour -- filter(is_active=1).order_by('-cycle_id').first(),
    i.e. the NEWEST active cycle -- silently picked one and ignored the rest. An
    administrator editing Winter's rules while Summer happened to be newer would
    read and write Summer's configuration without any indication.

    Falls back to the newest active cycle ONLY when nothing was specified, so
    older callers keep working; pass required=True where a wrong guess would be
    damaging.
    """
    data = request.data if hasattr(request, 'data') else {}
    cycle_id = data.get('cycleId') or request.GET.get('cycleId')
    if cycle_id:
        cycle = InternshipCycles.objects.filter(cycle_id=cycle_id).first()
        if cycle:
            return cycle

    cycle_name = data.get('cycleName') or request.GET.get('cycleName')
    if cycle_name and ' ' in str(cycle_name):
        term, _, year = str(cycle_name).rpartition(' ')
        cycle = InternshipCycles.objects.filter(
            session_term=term.strip(), application_year=year.strip()
        ).first()
        if cycle:
            return cycle

    if required:
        return None
    return InternshipCycles.objects.filter(is_active=1).order_by('-cycle_id').first()


def cycle_label(cycle):
    return f"{cycle.session_term} {cycle.application_year}" if cycle else "—"


# ------------------------------------------------------------------------------
# UPPER CASE IS A DATA RULE, NOT A STYLE
#
# Every field in this portal displays in upper case -- deliberately, because it
# removes ambiguity between similar-looking characters and keeps entries legible
# on a crowded screen. Email addresses are the sole exception; case can be
# significant in a local part, and an address is machine-read, not scanned.
#
# Until now that rule was enforced ONLY by the `text-uppercase` CSS class, which
# is `text-transform` and therefore purely visual. The value submitted is what
# the person actually typed. So a referrer entering "asha rao" saw "ASHA RAO"
# on screen while the database stored "asha rao" -- and that stored value is
# what reaches the Excel and PDF exports, the archive, and anything printed
# later. The screen and the record disagreed, and nothing showed it.
#
# Normalising HERE, on the server, means the rule holds wherever the data is
# read from and regardless of which client wrote it.
# ------------------------------------------------------------------------------

# Case is preserved for these. Anything holding an email address, a stored file
# path, or a signed token must survive untouched.
CASE_SENSITIVE_KEYS = {
    'personal_email', 'referrer_email', 'referrer_notification_email',
    'official_email', 'email', 'candidate_email', 'student_email',
    'file_path', 'filePath', 'path', 'viewUrl', 'previewUrl', 'url',
    'password', 'token',
}


def upper_text(value):
    """Upper-case a string, leaving anything else alone."""
    return value.upper() if isinstance(value, str) else value


# ==============================================================================
# ACADEMIC OPTIONS
#
# The degree and branch lists BOTH portals offer. They live here, on the server,
# and are handed to each front end by /api/me/ -- which both already call at
# startup.
#
# They used to be hardcoded in Phase-1's app.js, where the HR dashboard could
# not see them: the College Referrals intake had free-text boxes instead, so the
# same degree could enter the pipeline spelled two ways depending on which form
# it came through. Adding a course meant editing one file and remembering the
# other existed.
#
# TO ADD A COURSE OR BRANCH: edit the list below. Both forms pick it up on their
# next load, with nothing to rebuild.
#
# The values are stored upper case like every other typed field; the mixed case
# here is only what the dropdown shows.
# ==============================================================================

COURSE_OPTIONS = [
    'B.Tech / B.E.', 'M.Tech / M.E.', 'BCA', 'MCA', 'B.Sc', 'M.Sc', 'BBA',
    'MBA / PGDM', 'B.Com', 'M.Com', 'LLB', 'LLM', 'BA / MA', 'Diploma',
]

BRANCH_OPTIONS = [
    'Computer Science & Engineering', 'Information Technology',
    'Electronics & Communication', 'Electrical Engineering',
    'Mechanical Engineering', 'Civil Engineering', 'Finance', 'Marketing',
    'Human Resources', 'Operations', 'Accounting', 'Commerce',
    'Corporate Law', 'General Law', 'Physics', 'Chemistry', 'Mathematics',
    'General',
]

#: The dropdown entry that reveals a free-text box.
CUSTOM_OPTION = 'Other'


def resolve_custom_option(selected, typed):
    """Return what should be STORED for a dropdown that allows a custom value.

    Compares without regard to case, deliberately. Every payload is upper-cased
    on the way in, so a case-sensitive check against 'Other' silently fails and
    stores the word OTHER in place of what the person actually typed -- which is
    exactly the bug this replaced.

    Falls back to the selection when 'Other' was chosen and nothing was typed,
    rather than storing nothing: an empty degree would be caught by the merge
    check, but a visible wrong value is easier to notice than a blank one.
    """
    selected = (selected or '').strip()
    typed = (typed or '').strip()
    if selected.upper() == CUSTOM_OPTION.upper() and typed:
        return typed
    return selected


def normalise_case(data, extra_exempt=()):
    """Upper-case every string in a payload except the exempt keys.

    Applied to what a PERSON typed, at the point it is stored. Numbers, dates,
    booleans and nested structures other than plain dicts pass through unchanged.
    """
    if not isinstance(data, dict):
        return data
    exempt = CASE_SENSITIVE_KEYS | set(extra_exempt)
    out = {}
    for key, value in data.items():
        if key in exempt:
            out[key] = value
        elif isinstance(value, str):
            out[key] = value.strip().upper()
        elif isinstance(value, dict):
            out[key] = normalise_case(value, extra_exempt)
        else:
            out[key] = value
    return out


def parse_payload_array(data, primary_key, fallback_key):
    val = data.get(primary_key)
    if not val:
        val = data.get(fallback_key, [])
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return val if isinstance(val, list) else []


# ------------------------------------------------------------------------------
# COLLEGE REFERRALS (INSTITUTIONAL PIPELINE)
#
# DMRC receives candidates from two sources. An EMPLOYEE referral arrives
# complete: the referrer fills the whole Phase-1 form and the application enters
# the Verification Queue ready to be checked. A COLLEGE referral does not. The
# institution sends a list of names with a few details, and the rest is
# collected by HR afterwards.
#
# The College Referrals section is where that assembly happens. A record moves:
#
#   Intake Draft     HR has filed what the college sent. Nothing else is known.
#   Pending Arrival  A joining date and sub-department have been allotted.
#   Ready for Merge  HR has completed the full form and uploaded the documents.
#
# and then leaves, joining the main pipeline at 'Pending Offer Letter' the
# moment the candidate reports and HR marks them as arrived.
#
# These are ordinary Applications rows throughout, NOT a separate staging
# table. That is deliberate: a record outside the applications table can have no
# ticket number, no timeline (application_status_history is keyed to an
# application) and no place in the main pipeline's Rejected list -- all three of
# which are required from the moment of intake.
#
# What distinguishes them is referral_source='Institutional' plus one of the
# three statuses above. There is no employee referrer: the institution named in
# academic_details.college_name stands in that place on every screen.
# ------------------------------------------------------------------------------
INSTITUTIONAL_STAGING_STATUSES = ('Intake Draft', 'Pending Arrival', 'Ready for Merge')


def is_institutional(application):
    """True when this application came through a college rather than an employee."""
    return getattr(application, 'referral_source', None) == 'Institutional'


def is_in_college_referrals(application):
    """True while a record is still being assembled in the College Referrals section."""
    return (is_institutional(application)
            and application.status in INSTITUTIONAL_STAGING_STATUSES)


def next_application_code(cycle):
    """Allocate the next unused ticket number for one cycle.

    Format: DMRC-<year><S|W>-<nnn>, e.g. DMRC-2026S-001. Institutional and
    employee referrals draw from the SAME series, so a ticket never reveals
    where a candidate came from -- the institutional badge does that.

    Two properties matter, and neither held before:

      * THE YEAR COMES FROM THE CYCLE, not from a literal in this file. The
        previous implementation hardcoded '2026', so a Winter 2027 cycle would
        have issued DMRC-2026W- codes until somebody edited the source.

      * A NUMBER IS NOT REUSED BY ANY RECORD THAT REMAINS IN THE SYSTEM. The
        next number is derived from the highest already issued for this cycle,
        looking at BOTH the live applications table AND the archive. That covers
        every normal ending -- withdrawn, rejected, completed, archived -- all of
        which keep their row in one table or the other, and therefore keep their
        number reserved forever.

        The previous implementation counted existing rows instead, so archiving
        a cycle's applications reset the sequence and handed the same tickets
        out again -- two candidates on one number, years apart, with no way for
        an auditor to tell them apart.

        The limit of this approach, stated honestly: if the HIGHEST-numbered
        record were hard-deleted from both tables by direct database access,
        its number would become available again. Nothing in the portal deletes
        an application, so this does not arise in operation. Guarding against it
        would require a separate counter table, which was judged not worth the
        machinery.

    Gaps in the sequence are therefore expected and CORRECT: a gap is evidence
    that a record was removed, which is exactly what an auditor needs to see.

    Numbering restarts at 001 for every cycle. Summer and Winter of the same
    year are distinguished by the S/W letter.

    MUST be called inside a transaction. The cycle row is locked for the
    duration, so two simultaneous submissions cannot read the same highest
    number and then collide on the unique index -- which previously surfaced as
    an unexplained save failure for whoever submitted second.
    """
    letter = 'W' if cycle.session_term == 'Winter' else 'S'
    prefix = f"DMRC-{cycle.application_year}{letter}-"

    # Serialise allocation for this cycle. Other cycles are unaffected.
    list(InternshipCycles.objects.select_for_update().filter(pk=cycle.pk))

    highest = 0
    issued = list(
        Applications.objects
        .filter(application_code__startswith=prefix)
        .values_list('application_code', flat=True)
    ) + list(
        ArchivedApplications.objects
        .filter(application_code__startswith=prefix)
        .values_list('application_code', flat=True)
    )

    for code in issued:
        suffix = str(code)[len(prefix):]
        if suffix.isdigit():
            highest = max(highest, int(suffix))

    return f"{prefix}{highest + 1:03d}"


# Fields the full application must carry before an institutional record may
# leave the College Referrals section. Each entry is (attribute, label shown to
# HR). Kept as data so the check and the message can never disagree.
MERGE_REQUIRED_STUDENT_FIELDS = [
    # Title is required because the offer letter prints it: "approval has been
    # granted for Ms. PRIYA SHARMA". The Phase-1 form has always demanded it,
    # but that check lives in the browser, and this list is what actually
    # guarantees it -- a college referral completed by any other route would
    # otherwise reach the pipeline without one.
    ('salutation', 'Title'),
    ('full_name', 'Candidate name'),
    ('fathers_name', "Father's name"),
    ('gender', 'Gender'),
    ('date_of_birth', 'Date of birth'),
    ('mobile_number', 'Mobile number'),
    ('personal_email', 'Email address'),
    ('permanent_address', 'Permanent address'),
    ('emergency_contact_name', 'Emergency contact name'),
    ('emergency_contact_mobile', 'Emergency contact mobile'),
]

# The identity number is NOT in the list above, because whether it is required
# at all depends on the cycle's configuration.
#
# The number, its consent tick and the document itself are one thing: all three
# are driven by a document flagged requires_consent, so disabling Aadhaar for a
# cycle removes all three from the form together. The merge check demanded the
# number unconditionally, which made a candidate impossible to merge -- the
# field they were never shown could never be filled, and "Mark as Arrived"
# stayed disabled forever with no way to clear it.
#
# It is judged against the application's OWN frozen snapshot, not today's
# configuration, so a candidate is held to what they were actually asked for.
MERGE_CONDITIONAL_FIELDS = [
    ('aadhaar_number', 'Aadhaar number'),
]

MERGE_REQUIRED_ACADEMIC_FIELDS = [
    ('university_name', 'University'),
    ('college_name', 'College'),
    ('degree_program', 'Degree / course'),
    ('branch_name', 'Branch'),
    ('current_semester', 'Current semester'),
    ('grading_system', 'Grading system'),
    ('current_score', 'Current score'),
]


def merge_blockers(application):
    """Everything still missing before this record may be marked as arrived.

    THIS IS THE CHECK THAT REPLACES THE DATABASE'S NOT NULL CONSTRAINTS.

    Those constraints were relaxed so a college referral could be filed before
    its details were known (see migration 01). The guarantee they provided is
    not lost -- it moves here, to the one moment it actually applies: the point
    at which an institutional record stops being a work in progress and becomes
    a real application in the main pipeline.

    Returns a list of human-readable labels. An empty list means the record is
    complete and may be merged.

    Optional documents are NOT required: the administrator decides per cycle
    which documents are mandatory, and only those are enforced here.
    """
    missing = []

    student = getattr(application, 'student', None)
    for attr, label in MERGE_REQUIRED_STUDENT_FIELDS:
        value = getattr(student, attr, None) if student else None
        if value is None or str(value).strip() == '':
            missing.append(label)

    # Required only when this application was actually asked for a document
    # carrying a consent requirement -- the same test the form itself uses to
    # decide whether to show the field.
    rules = application_rules(application)
    identity_number_required = any(r.get('requiresConsent') for r in rules)
    if identity_number_required:
        for attr, label in MERGE_CONDITIONAL_FIELDS:
            value = getattr(student, attr, None) if student else None
            if value is None or str(value).strip() == '':
                missing.append(label)

    academic = AcademicDetails.objects.filter(application=application).first()
    for attr, label in MERGE_REQUIRED_ACADEMIC_FIELDS:
        value = getattr(academic, attr, None) if academic else None
        if value is None or str(value).strip() == '':
            missing.append(label)

    if application.department_id is None:
        missing.append('Department')
    if not application.duration_weeks:
        missing.append('Internship duration')

    joining = JoiningDetails.objects.filter(application=application).first()
    if joining is None or not joining.allotted_date_of_joining:
        missing.append('Allotted date of joining')
    if joining is None or joining.allotted_sub_department_id is None:
        missing.append('Allotted sub-department')

    # Documents are judged against the snapshot frozen onto THIS application,
    # not against today's configuration -- the same rule the main pipeline uses.
    uploaded = {d.doc_type_id for d in current_documents(application)}
    for rule in rules:
        if rule.get('isMandatory') and rule.get('id') not in uploaded:
            missing.append(f"Document: {rule.get('name')}")

    return missing


class ApplicationDraftAPIView(APIView):
    """Server-side wizard drafts, owned by the signed-in referrer.

    GET    /api/drafts/            list my drafts
    POST   /api/drafts/            create or update (autosave); body may carry id
    DELETE /api/drafts/?id=<id>    discard a draft and its files

    A draft is always scoped to the requesting employee. There is no way to read
    or modify another referrer's draft, even by guessing an id.
    """

    def _owner(self, request):
        return request.identity.employee

    @employee_required
    def get(self, request):
        purge_drafts_for_closed_cycles()
        drafts = (ApplicationDrafts.objects
                  .filter(owner_employee=self._owner(request))
                  .select_related('cycle')
                  .order_by('-updated_at'))
        return Response([serialize_draft(d) for d in drafts], status=status.HTTP_200_OK)

    @employee_required
    @transaction.atomic
    def post(self, request):
        owner = self._owner(request)
        draft_id = request.data.get('id')
        payload = request.data.get('payload') or {}
        if not isinstance(payload, dict):
            return Response({"error": "payload must be an object."}, status=status.HTTP_400_BAD_REQUEST)

        cycle = None
        cycle_id = request.data.get('cycleId')
        if cycle_id:
            cycle = InternshipCycles.objects.filter(cycle_id=cycle_id).first()

        candidate_name = (payload.get('student', {}) or {}).get('fullName') or None

        if draft_id:
            # Scoped by owner: a referrer cannot overwrite someone else's draft.
            draft = ApplicationDrafts.objects.filter(
                draft_id=draft_id, owner_employee=owner
            ).first()
            if not draft:
                return Response({"error": "Draft not found."}, status=status.HTTP_404_NOT_FOUND)
            # Preserve any document references already uploaded against this draft.
            existing = draft.payload if isinstance(draft.payload, dict) else json.loads(draft.payload or '{}')
            payload.setdefault('documents', existing.get('documents', {}))
        else:
            draft = ApplicationDrafts(owner_employee=owner, created_at=timezone.now())

        draft.cycle = cycle
        draft.candidate_name = candidate_name
        draft.payload = payload
        draft.current_step = int(request.data.get('currentStep') or 1)
        draft.highest_step = int(request.data.get('highestStep') or 1)
        draft.updated_at = timezone.now()
        draft.save()

        return Response(serialize_draft(draft),
                        status=status.HTTP_201_CREATED if not draft_id else status.HTTP_200_OK)

    @employee_required
    @transaction.atomic
    def delete(self, request):
        draft_id = request.query_params.get('id') or request.data.get('id')
        draft = ApplicationDrafts.objects.filter(
            draft_id=draft_id, owner_employee=self._owner(request)
        ).first()
        if not draft:
            return Response({"error": "Draft not found."}, status=status.HTTP_404_NOT_FOUND)
        purge_draft(draft)
        return Response({"message": "Draft discarded."}, status=status.HTTP_200_OK)


class DraftDocumentAPIView(APIView):
    """Upload or replace a single document on a draft.

    POST multipart/form-data:
        draft_id  -- the draft being edited
        doc_key   -- aadhar | college_id | lor | photograph | signature
        file      -- the file

    Replacement is a true overwrite: the previous draft file is deleted. Draft
    documents are not audit records, so there is nothing to preserve. Versioning
    begins only once the application is submitted.
    """

    # Any ACTIVE document type is a valid slot. Validated against the database
    # rather than a fixed list, so a document added by an administrator is
    # immediately uploadable without a code change.
    @staticmethod
    def resolve_slot(doc_key):
        raw = str(doc_key).replace('doc_', '')
        if not raw.isdigit():
            return None
        return DocumentTypes.objects.filter(doc_type_id=int(raw), is_active=1).first()

    @employee_required
    @transaction.atomic
    def post(self, request):
        draft_id = request.data.get('draft_id')
        doc_key = request.data.get('doc_key')
        upload = request.FILES.get('file')

        if not draft_id or not doc_key or not upload:
            return Response({"error": "draft_id, doc_key and file are all required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if self.resolve_slot(doc_key) is None:
            return Response({"error": f"'{doc_key}' is not an active document slot."},
                            status=status.HTTP_400_BAD_REQUEST)

        draft = ApplicationDrafts.objects.filter(
            draft_id=draft_id, owner_employee=request.identity.employee
        ).first()
        if not draft:
            return Response({"error": "Draft not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = draft.payload if isinstance(draft.payload, dict) else json.loads(draft.payload or '{}')
        documents = payload.get('documents', {}) or {}

        # Overwrite: drop whatever occupied this slot before.
        previous = documents.get(doc_key)
        if previous and previous.get('path'):
            delete_draft_file(previous['path'])

        saved_path = default_storage.save(
            f"{DRAFT_MEDIA_PREFIX}/{draft.draft_id}/{upload.name}",
            ContentFile(upload.read())
        )
        documents[doc_key] = {
            "name": upload.name,
            "path": saved_path,
            "url": f"{settings.MEDIA_URL}{saved_path}",
        }
        payload['documents'] = documents
        draft.payload = payload
        draft.updated_at = timezone.now()
        draft.save()

        return Response({"docKey": doc_key, **documents[doc_key]}, status=status.HTTP_200_OK)

    @employee_required
    @transaction.atomic
    def delete(self, request):
        draft_id = request.query_params.get('draft_id')
        doc_key = request.query_params.get('doc_key')
        draft = ApplicationDrafts.objects.filter(
            draft_id=draft_id, owner_employee=request.identity.employee
        ).first()
        if not draft:
            return Response({"error": "Draft not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = draft.payload if isinstance(draft.payload, dict) else json.loads(draft.payload or '{}')
        documents = payload.get('documents', {}) or {}
        entry = documents.pop(doc_key, None)
        if entry and entry.get('path'):
            delete_draft_file(entry['path'])
        payload['documents'] = documents
        draft.payload = payload
        draft.updated_at = timezone.now()
        draft.save()
        return Response({"message": f"{doc_key} removed."}, status=status.HTTP_200_OK)


class PortalBootstrapAPIView(APIView):
    """Everything the referrer portal needs to render its form. Employee-level.

    Phase 1 previously called /api/admin/cycles/ and /api/admin/configs/, which
    are SYS-ADMIN only. That worked in development purely because the fallback
    identity happened to be an administrator -- a real referrer would have been
    refused with 403. This endpoint exposes the same handful of facts an
    applicant form legitimately needs, and nothing else: no quotas management,
    no IAM data, no escalations, no audit ledger.
    """

    @employee_required
    def get(self, request):
        cycles = InternshipCycles.objects.filter(is_active=1).order_by('cycle_id')

        cycle_list = []
        allowed_doj = {}

        for cycle in cycles:
            label = f"{cycle.session_term} {cycle.application_year}"
            cycle_list.append({
                "id": cycle.cycle_id,
                "name": label,
                "term": cycle.session_term,
                "year": cycle.application_year,
                "isActive": True,
                # Phase 1 gates the form on these: isCycleOpen() compares today
                # against start/end, so omitting them makes every cycle look
                # closed regardless of is_active.
                "start": cycle.application_start_date.strftime('%Y-%m-%d') if cycle.application_start_date else None,
                "end": cycle.application_end_date.strftime('%Y-%m-%d') if cycle.application_end_date else None,
            })

            # Field is allowed_doj on CycleJoiningDates (not joining_date).
            allowed_doj[label] = [
                d.allowed_doj.strftime('%Y-%m-%d')
                for d in CycleJoiningDates.objects.filter(cycle=cycle, is_active=1).order_by('allowed_doj')
                if d.allowed_doj
            ]

        # Occupancy drives the waitlist warning the referrer sees, so it has to
        # be exposed. Capacity numbers only -- nothing candidate-identifying.
        # PER CYCLE, keyed by cycle id.
        #
        # This was previously flattened across every active cycle, which broke
        # in two ways once DMRC ran concurrent cycles:
        #
        #   * one row per (cycle, department) meant every department appeared
        #     once PER CYCLE in the referrer's dropdown -- Civil twice, IT
        #     twice, and so on; and
        #   * occupancy was merged into a single dict keyed by department name,
        #     so the later cycle's figures silently overwrote the earlier one's.
        #     The seats-remaining number shown to a referrer belonged to
        #     whichever cycle happened to be processed last, not the one they
        #     were applying to. A wrong number that looks right is worse than a
        #     duplicated list, because nobody notices it.
        capacities_by_cycle = {}
        for cycle in cycles:
            occupancy = department_occupancy(cycle)
            rows = []
            for cap in (CycleDepartmentCapacities.objects
                        .filter(cycle=cycle)
                        .select_related('department')
                        .order_by('department__department_name')):
                dept_name = cap.department.department_name
                rows.append({
                    "dept": dept_name,
                    "quota": cap.max_capacity,
                    # Live count for THIS cycle, excluding wards. The stored
                    # seats_occupied column is not maintained and would report
                    # every department as empty.
                    "occupied": occupancy.get(dept_name, 0),
                })
            capacities_by_cycle[str(cycle.cycle_id)] = rows

        # Fallback only, for the moment before a cycle has been chosen. One
        # cycle's figures rather than a blend of several.
        first_cycle = cycles[0] if cycles else None
        capacities = capacities_by_cycle.get(str(first_cycle.cycle_id), []) if first_cycle else []

        # Document rules come from cycle_document_requirements, the same source
        # the Admin Control Center configures. Listing DocumentTypes directly
        # would ignore is_mandatory, so the referrer's vault
        # could disagree with what an administrator actually configured -- and
        # would wrongly include Clearance-stage documents such as the Mentor's
        # Evaluation, which no applicant can supply.
        # Whatever the administrator has configured, keyed by doc_type_id.
        # Drafts pick up changes immediately, which is why this reads the LIVE
        # cycle configuration rather than any snapshot.
        # PER CYCLE, keyed by cycle id.
        #
        # These used to be MERGED into one flat list across every active cycle,
        # deduplicated by document id. With concurrent cycles that is wrong in
        # the most damaging direction: a document disabled for one cycle stayed
        # in the merged list because another cycle still used it, so the form
        # went on demanding it. Disabling Aadhaar for a cycle left the upload,
        # the consent checkbox and the Aadhaar number field all on screen.
        #
        # The form now reads the rules of the cycle the referrer selected.
        doc_rules_by_cycle = {
            str(cycle.cycle_id): active_document_rules(cycle) for cycle in cycles
        }

        # Fallback only, for the moment before a cycle has been chosen. Taken
        # from a single cycle rather than merged, so it can never describe a
        # combination that no cycle actually asks for.
        first_cycle = cycles[0] if cycles else None
        doc_rules = doc_rules_by_cycle.get(str(first_cycle.cycle_id), []) if first_cycle else []

        return Response({
            "cycles": cycle_list,
            "capacities": capacities,
            "capacitiesByCycle": capacities_by_cycle,
            "allowedDojDatesByCycle": allowed_doj,
            "docRules": doc_rules,
            "docRulesByCycle": doc_rules_by_cycle,
        }, status=status.HTTP_200_OK)


def render_secure_viewer(raw_url, watermark, title, is_pdf):
    """HTML wrapper that displays a document without a download control.

    Returning the raw PDF let the browser's own plugin render it, and that
    plugin has a download button no HTTP header can remove. Rendering the file
    ourselves removes the toolbar entirely: for images an <img> with the context
    menu and dragging suppressed, for PDFs a canvas painted by pdf.js.

    A repeating watermark carries the viewer's employee code and the time. This
    is the honest control: screenshots cannot be blocked by any web page, but a
    screenshot taken from here identifies who took it.

    NOTE FOR DMRC IT: pdf.js is loaded from a CDN. On an isolated intranet it
    must be vendored locally, as must Bootstrap, Alpine and Flatpickr in the
    two front ends.
    """
    body = (
        '<canvas id="page"></canvas>' if is_pdf
        else f'<img id="page" src="{raw_url}" alt="{title}">'
    )
    pdf_script = f"""
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <script>
      pdfjsLib.GlobalWorkerOptions.workerSrc =
        'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
      pdfjsLib.getDocument('{raw_url}').promise.then(function (pdf) {{
        var host = document.getElementById('stack');
        document.getElementById('page').remove();
        for (var n = 1; n <= pdf.numPages; n++) {{
          (function (num) {{
            pdf.getPage(num).then(function (page) {{
              var viewport = page.getViewport({{ scale: 1.5 }});
              var canvas = document.createElement('canvas');
              canvas.width = viewport.width; canvas.height = viewport.height;
              host.appendChild(canvas);
              page.render({{ canvasContext: canvas.getContext('2d'), viewport: viewport }});
            }});
          }})(n);
        }}
      }}).catch(function (e) {{
        document.getElementById('stack').innerHTML =
          '<p style="color:#fff;font-family:sans-serif">This document could not be displayed.</p>';
      }});
    </script>""" if is_pdf else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<meta name="referrer" content="no-referrer">
<style>
  html,body {{ margin:0; background:#1c2434; }}
  #stack {{ display:flex; flex-direction:column; align-items:center; gap:16px; padding:24px; }}
  #stack canvas, #page {{ max-width:100%; box-shadow:0 4px 24px rgba(0,0,0,.4); background:#fff; }}
  /* Suppress selection, dragging and long-press save. */
  * {{ -webkit-user-select:none; user-select:none; -webkit-touch-callout:none; }}
  img {{ -webkit-user-drag:none; pointer-events:none; }}
  /* Repeating watermark identifying the viewer. */
  #mark {{ position:fixed; inset:0; pointer-events:none; z-index:9999;
           display:flex; flex-wrap:wrap; align-content:flex-start;
           opacity:.16; overflow:hidden; }}
  #mark span {{ color:#fff; font:600 13px/1 sans-serif; transform:rotate(-30deg);
                white-space:nowrap; margin:48px 36px; }}
  #bar {{ position:fixed; bottom:0; left:0; right:0; z-index:10000;
          background:rgba(0,0,0,.75); color:#cbd5e1; font:500 12px sans-serif;
          padding:8px 16px; text-align:center; }}
</style></head>
<body>
  <div id="mark"></div>
  <div id="stack">{body}</div>
  <div id="bar">VIEW ONLY &middot; {watermark} &middot; This access has been recorded</div>
<script>
  // Fill the watermark layer.
  var mark = document.getElementById('mark');
  for (var i = 0; i < 60; i++) {{
    var s = document.createElement('span');
    s.textContent = {watermark!r};
    mark.appendChild(s);
  }}
  // No right-click save, no drag-out, no Ctrl/Cmd+S.
  document.addEventListener('contextmenu', function (e) {{ e.preventDefault(); }});
  document.addEventListener('dragstart', function (e) {{ e.preventDefault(); }});
  document.addEventListener('keydown', function (e) {{
    var k = (e.key || '').toLowerCase();
    if ((e.ctrlKey || e.metaKey) && (k === 's' || k === 'p')) {{ e.preventDefault(); }}
  }});
</script>{pdf_script}
</body></html>"""


class _ArchivedDocumentAdapter:
    """Presents an ArchivedDocuments row with the attributes SecureDocumentView
    reads from a live Documents row.

    Archived documents go through exactly the same watermarked, access-logged
    viewer. Rather than duplicating that ~80 lines for the archive -- where the
    two copies would inevitably drift -- the archived row is wrapped to look
    like a live one for the handful of fields the streaming path touches.
    """

    def __init__(self, archived):
        self._archived = archived
        # Prefixed so the viewer knows which table to read. This is a STRING and
        # must never reach the audit ledger, whose target_entity_id is an
        # integer column -- see audit_entity_id below.
        self.document_id = f"a{archived.archive_doc_id}"
        # What the access log records. Writing document_id there put "a1" into
        # an INT column; the insert failed and a silent `except` swallowed it,
        # so archived documents were being viewed with nothing written to the
        # ledger at all.
        self.audit_entity_id = archived.archive_doc_id
        self.audit_entity_type = 'ArchivedDocument'
        self.file_path = archived.file_path
        # The archive records whether a document was GENERATED by the portal,
        # and that decides how the viewer serves it: an archived offer letter is
        # downloaded like a live one, an archived Aadhaar card is watermarked.
        # This was hardcoded to 0, which watermarked DMRC's own letters.
        self.doc_type = SimpleNamespace(
            type_name=archived.doc_type_name,
            is_system_generated=1 if archived.is_system_generated else 0,
        )
        # The parent record, for the access log. Looked up rather than stored on
        # the document row, because archived_documents keys only on the original
        # application id.
        parent = ArchivedApplications.objects.filter(
            original_application_id=archived.original_application_id).first()
        self.application = SimpleNamespace(
            application_code=getattr(parent, 'application_code', None),
            student=SimpleNamespace(full_name=getattr(parent, 'student_name', None)),
            # No referrer: an archived cycle has no owner exemption. Every view
            # is watermarked and logged, including a SYS-ADMIN's.
            referrer_employee=None,
        )

        # Which closed cycle this belongs to. Recorded with every view: on an
        # archived record the ticket alone is not enough context years later,
        # and the cycle is what an auditor searches by.
        self.audit_cycle = (
            f"{parent.session_term} {parent.application_year}" if parent else None
        )


class SecureDocumentView(APIView):
    """Serve a referrer-uploaded document inline, to an authorised HR user only.

    GET /api/documents/view/?t=<signed token>

    The token is minted per request when a drawer payload is built and expires
    after settings.DOCUMENT_LINK_TTL_SECONDS, so a link copied out of the page
    stops working. The caller must additionally hold an HR role -- the token
    alone is not authorisation.

    Every successful view is written to the audit ledger, which is the point:
    the control this provides is ACCOUNTABILITY, not physical impossibility.
    A screenshot cannot be prevented by any web application, and claiming
    otherwise would be dishonest to whoever relies on this system.
    """

    # Inline for everything: the browser displays rather than offers to save.
    INLINE_TYPES = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png',
    }

    # employee_required, NOT role_required: a referrer must be able to preview
    # the documents they uploaded themselves. Authorisation is decided per
    # document below -- HR roles see everything, an ordinary employee sees only
    # applications they personally referred.
    @employee_required
    def get(self, request):
        token = request.query_params.get('t')
        if not token:
            return Response({"error": "A document link is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            document_id = _document_signer.unsign(
                token, max_age=getattr(settings, 'DOCUMENT_LINK_TTL_SECONDS', 600)
            )
        except SignatureExpired:
            return Response(
                {"error": "This document link has expired. Reopen the application to view it again."},
                status=status.HTTP_403_FORBIDDEN
            )
        except BadSignature:
            return Response({"error": "Invalid document link."},
                            status=status.HTTP_403_FORBIDDEN)

        # An 'a' prefix means the document belongs to an ARCHIVED application.
        # Hard-closing a cycle deletes the live row, so without this branch every
        # document link in the archive would return "Document not found".
        is_archived = str(document_id).startswith('a')
        identity = request.identity

        if is_archived:
            archived = ArchivedDocuments.objects.filter(
                archive_doc_id=int(str(document_id)[1:])).first()
            if archived is None:
                raise Http404("Document not found.")

            # Archived records are SYS-ADMIN only, matching the vault itself.
            # There is no referrer exemption: the employee who made the referral
            # has no standing over a closed cycle years later.
            if identity.role != 'SYS-ADMIN':
                return Response(
                    {"error": "Archived documents may only be viewed by a system administrator."},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Streamed through the same watermarked viewer as a live document:
            # same access log, same no-download page. A lightweight stand-in
            # carries the few fields the rest of this method reads, so there is
            # one streaming path rather than two that could drift apart.
            document = _ArchivedDocumentAdapter(archived)
            is_owner = False
            is_hr = True
        else:
            document = Documents.objects.filter(document_id=int(document_id)).select_related('doc_type', 'application').first()
            if document is None:
                raise Http404("Document not found.")

            # --- AUTHORISATION -------------------------------------------
            is_hr = identity.role in ALL_HR_ROLES
            referrer = getattr(document.application, 'referrer_employee', None)
            is_owner = (referrer is not None
                        and identity.employee is not None
                        and referrer.employee_id == identity.employee.employee_id)

        if not (is_hr or is_owner):
            return Response(
                {"error": "You are not authorised to view this document."},
                status=status.HTTP_403_FORBIDDEN
            )

        path = stored_document_path(document)
        if path is None:
            raise Http404("The stored file is missing.")

        # --- GENERATED OUTPUT: DOWNLOADED, NOT WATERMARKED -------------------
        # An offer letter is DMRC's own document, produced by this portal and
        # meant to be printed and handed over. Watermarking it or stripping the
        # download control would stop HR-OPS doing the job the letter exists
        # for. The restrictions below govern access to a CANDIDATE's identity
        # documents, which is a different question.
        #
        # The access is still logged, and still role-checked.
        if is_generated_document(document):
            _audit(identity.user, 'GENERATED_DOCUMENT_DOWNLOADED',
                   getattr(document, 'audit_entity_type', 'Document'),
                   getattr(document, 'audit_entity_id', document.document_id),
                   new_value={
                       "document": getattr(document.doc_type, 'type_name', 'Unknown'),
                       "application": getattr(document.application, 'application_code', None),
                       "downloadedBy": identity.employee_code,
                   })
            filename = Path(str(document.file_path)).name
            response = FileResponse(
                open(path, 'rb'),
                content_type=self.INLINE_TYPES.get(
                    Path(str(document.file_path)).suffix.lower(),
                    'application/octet-stream'))
            # INLINE, so the browser opens it in a tab with its own PDF viewer,
            # from which the reader can save or print it if they want to.
            #
            # This is DMRC's own document and is meant to be circulated, so the
            # restrictions that apply to a candidate's identity papers -- the
            # watermarked no-download viewer -- would only get in the way of the
            # job the letter exists for. What still applies is the part that
            # matters: the role is checked, and the access is in the ledger.
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            response['X-Content-Type-Options'] = 'nosniff'
            return response

        extension = Path(str(document.file_path)).suffix.lower()
        content_type = self.INLINE_TYPES.get(extension, 'application/octet-stream')

        # --- OWNING REFERRER: UNRESTRICTED ------------------------------------
        # The referrer uploaded this file and already holds the original, so
        # watermarking it, stripping the download control or recording them for
        # opening their own document would be friction with no security value.
        # The restrictions exist to govern HR access to someone else's identity
        # documents, which is a different question entirely.
        #
        # An HR user who happens to have referred this candidate is treated as
        # the owner for the same reason: it is their own submission.
        if is_owner:
            response = FileResponse(open(path, 'rb'), content_type=content_type)
            response['Content-Disposition'] = 'inline'
            response['X-Content-Type-Options'] = 'nosniff'
            return response

        # --- HR ACCESS LOG ----------------------------------------------------
        # Written before streaming, so an interrupted view is still recorded.
        try:
            with transaction.atomic():
                SystemAuditLogs.objects.create(
                    actor_user=identity.user,
                    role_name=identity.role or 'UNKNOWN',
                    action_type='DOCUMENT_VIEWED',
                    # An archived document reports its own table and numeric id.
                    # A live one falls back to the plain document id.
                    target_entity_type=getattr(document, 'audit_entity_type', 'Document'),
                    target_entity_id=getattr(document, 'audit_entity_id', document.document_id),
                    new_value=json.dumps({
                        "document": getattr(document.doc_type, 'type_name', 'Unknown'),
                        "application": getattr(document.application, 'application_code', None),
                        "candidate": getattr(getattr(document.application, 'student', None), 'full_name', None),
                        "viewedBy": identity.employee_code,
                        "archived": bool(getattr(document, 'audit_entity_type', None)),
                        "cycle": getattr(document, 'audit_cycle', None),
                    })
                )
        except Exception as audit_error:
            # Never silent. Access to someone's identity documents is exactly
            # the thing the ledger exists to record, so a failure to write it
            # must be visible in the server log rather than swallowed.
            logger.error("DOCUMENT ACCESS LOG FAILED (%s): %s",
                         type(audit_error).__name__, audit_error)

        # ?raw=1 returns the bytes themselves. The wrapper page below requests
        # this; a person can reach it directly through developer tools, which is
        # unavoidable for anything the browser must render. It is not linked
        # anywhere in the interface.
        if request.query_params.get('raw') == '1':
            response = FileResponse(open(path, 'rb'), content_type=content_type)
            response['Content-Disposition'] = 'inline'
            response['X-Content-Type-Options'] = 'nosniff'
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            return response

        # Otherwise return a VIEWER PAGE. Handing back the raw PDF let the
        # browser's own PDF plugin take over, and that plugin has a download
        # button no server header can remove. Rendering it ourselves means no
        # toolbar, no download control, and no right-click save.
        #
        # Every page carries a watermark naming the viewer and the time. A
        # screenshot cannot be prevented by any web application -- but one taken
        # from this viewer identifies who took it, which is the control that
        # actually works.
        raw_url = f"/api/documents/view/?t={token}&raw=1"
        if request.query_params.get('emp'):
            raw_url += f"&emp={request.query_params.get('emp')}"

        watermark = f"{identity.employee_code} · {timezone.localtime().strftime('%d-%m-%Y %H:%M')}"
        doc_title = getattr(document.doc_type, 'type_name', 'Document')
        is_pdf = extension == '.pdf'

        return HttpResponse(
            render_secure_viewer(raw_url, watermark, doc_title, is_pdf),
            content_type='text/html'
        )


class CurrentUserAPIView(APIView):
    """Who am I, and what may I do?

    Both front ends call this on load instead of hardcoding an employee or a
    role. Returns 401 when the request carries no recognised identity, which
    is the front end's cue to send the user back to the DMRC employee login.
    """

    @employee_required
    def get(self, request):
        identity = request.identity
        employee = identity.employee

        return Response({
            "employeeCode": employee.employee_code,
            "fullName": employee.full_name,
            # No salutation: the DMRC employee directory does not hold one, so
            # the portal has nothing to report. The CANDIDATE's title is a
            # separate field, collected on the Phase-1 form.
            "designation": employee.designation,
            "department": employee.department.department_name if employee.department else None,
            "officialEmail": employee.official_email,

            # None means: ordinary employee. Phase 1 referrals only, no dashboard.
            "role": identity.role,
            "hasDashboardAccess": identity.has_dashboard_access,
            "username": identity.user.username if identity.user else None,

            # False on the intranet. The dashboard hides the role switcher when
            # this is False, so the developer affordance cannot leak to production.
            "devMode": is_development_identity(),

            # The degree and branch dropdowns, served rather than hardcoded in
            # each front end. Both portals call this endpoint on load, so this is
            # the one place either of them has to look -- which is what stops the
            # referral form and the College Referrals intake offering different
            # lists for the same field.
            "academicOptions": {
                "courses": COURSE_OPTIONS,
                "branches": BRANCH_OPTIONS,
                "customLabel": CUSTOM_OPTION,
            },
        }, status=status.HTTP_200_OK)


class SubmitApplicationView(APIView):
    @employee_required
    @employee_required
    def get(self, request):
        """The signed-in employee's OWN referrals.

        This used to return `.all()` -- every application in the database. Every
        employee saw every other employee's candidates, with names, addresses,
        dates of birth and contact details, and college referrals appeared in
        the list of people who had referred nobody.

        Two conditions, deliberately, rather than one:

          referrer_employee   whose referral it is
          referral_source     what KIND of record it is

        A college referral has no referrer, so filtering on the first alone
        would already exclude it -- but only for as long as nothing ever writes
        an employee into that column, and an institutional record completed
        through this same Phase-1 form is exactly the case where something might.
        The second condition means that mistake could not expose it here.
        """
        identity = request.identity

        applications = (Applications.objects
                        .filter(referrer_employee=identity.employee)
                        .exclude(referral_source='Institutional')
                        .select_related('student', 'department', 'cycle')
                        .order_by('-application_id'))
        app_list = []
        

        for app in applications:
            student = app.student
            academic = AcademicDetails.objects.filter(application=app).first()
            docs = current_documents(app)   # live versions only
            joining = JoiningDetails.objects.filter(application=app).first()
            history = ApplicationStatusHistory.objects.filter(application=app).order_by('changed_at')
            
            # The rules THIS application was asked to satisfy, frozen at
            # submission. Rendering from here means a document added or removed
            # afterwards never changes what an existing application shows.
            rules_for_app = application_rules(app)

            doc_dict = {}
            for d in docs:
                # Keyed by doc_<doc_type_id> so it matches rule.key on the
                # front end. The old name-based map could only ever express the
                # five original documents.
                frontend_key = document_slug(d.doc_type_id) if d.doc_type_id else None
                if frontend_key and d.file_path:
                    file_name = str(d.file_path).split('/')[-1]
                    # No raw /media/ path: referrer uploads live outside
                    # MEDIA_ROOT and are reachable only through the role-checked,
                    # expiring viewer endpoint.
                    doc_dict[frontend_key] = {
                        "name": file_name,
                        "previewUrl": document_view_url(d),
                        "protected": is_protected_document(d),
                    }
            
            date_str = safe_extract_time(app, 'created_at', date_only=True)
            datetime_str = safe_extract_time(app, 'created_at')

            app_year = getattr(app.cycle, 'application_year', '2026') if app.cycle else '2026'
            target_cycle = f"{getattr(app.cycle, 'session_term', '')} {app_year}" if app.cycle else "—"
            
            badge_class = "bg-primary"
            if app.status in ['Submitted', 'Under Verification', 'Ready for Merge']: badge_class = "bg-warning text-dark"
            elif app.status == 'Approved': badge_class = "bg-success"
            elif app.status == 'Rejected': badge_class = "bg-danger"

            # application_status_history is the single source of truth for the
            # timeline. This used to be seeded with a hardcoded "Application
            # Submitted" entry, which was correct only while no history rows
            # existed -- once submissions started recording their own entry the
            # seed duplicated it. Anything shown here is a real recorded event.
            timeline = []

            # Steps the REFERRER is not shown. Everything between the joining
            # date being allotted and the intern actually starting is HR's
            # internal handling -- signing the letter, correcting it,
            # re-approving it. A referrer who sees 'Awaiting Offer Letter' sitting
            # there for three days has nothing to do about it and no way to help.
            #
            # The steps are still recorded, still in application_status_history,
            # and still visible on the HR dashboard and in the audit ledger.
            # This hides them from ONE audience, it does not stop recording them.
            # WHAT THE REFERRER IS TOLD THE STATUS IS.
            #
            # The pipeline has eighteen statuses because HR needs that
            # precision. A referrer needs six. Showing them 'Fix Joining' or
            # 'Pending Offer Re-Approval' tells them nothing they can act on and
            # invites them to chase HR about an exchange between two HR
            # officers.
            #
            # So internal states are reported as the last PUBLIC state the
            # application actually reached. Anything not listed is shown
            # unchanged, which is the safe default: a status nobody thought
            # about appears as itself rather than silently becoming something
            # else.
            REFERRER_PUBLIC_STATUS = {
                'Under Verification': 'Submitted',
                'Ready for Merge': 'Submitted',
                'Intake Draft': 'Submitted',
                'Pending Arrival': 'Scheduled',
                'Fix Joining': 'Scheduled',
                'Pending Offer Letter': 'Joined',
                'Offer Ready': 'Joined',
                'Pending Offer Re-Approval': 'Joined',
                'Fix Clearance': 'Joined',
                'Pending Certificate': 'Joined',
                'Pending Dispatch': 'Joined',
            }

            REFERRER_HIDDEN_STATUSES = {'Pending Offer Letter', 'Offer Ready',
                                        'Pending Offer Re-Approval',
                                        # HR-APP returning the paperwork to
                                        # HR-OPS. The referrer sees "Correction
                                        # Requested" and reasonably thinks they
                                        # have something to fix, when the whole
                                        # exchange is between two HR officers
                                        # about a joining date or a letter.
                                        #
                                        # A correction the REFERRER must act on
                                        # is a different thing entirely: those
                                        # bounce the application back to them
                                        # and are still shown.
                                        'Fix Joining', 'Fix Clearance'}

            # Remarks the referrer is not shown, whatever status carries them.
            # A no-show escalation and the administrator's date change are an
            # internal hold: the referrer sees the rejection itself, not the
            # machinery of DMRC deciding what to do about it.
            REFERRER_HIDDEN_REMARKS = ('STEALTH ESCALATION', 'ESCALATED TO ADMIN',
                                       'ADMIN OVERRIDE', 'GOD MODE')

            for h in history:
                if h.new_status in REFERRER_HIDDEN_STATUSES:
                    continue
                remark_text = (h.remarks or '').upper()
                if any(phrase in remark_text for phrase in REFERRER_HIDDEN_REMARKS):
                    continue
                user = getattr(h, 'changed_by_user', None)
                employee = getattr(user, 'employee', None) if user else None
                actor_name = getattr(employee, 'full_name', None)

                if h.remarks:
                    description = referrer_facing_remark(h.remarks)
                elif actor_name:
                    description = f"Processed by {actor_name}."
                else:
                    description = "Processed by DMRC HR."

                # A resubmission is a distinct event from the original
                # submission, even though both land on status 'Submitted'.
                # Detected from the recorded remark so no schema change is needed.
                title = TIMELINE_TITLES.get(h.new_status, f"Status: {h.new_status}")
                if is_resubmission_entry(h):
                    title = 'Application Resubmitted'

                timeline.append({
                    "date": safe_extract_time(h, 'changed_at'),
                    "title": title,
                    "desc": description
                })

            # Fallback only for applications predating the history write.
            if not timeline:
                timeline = [{
                    "date": datetime_str,
                    "title": "Application Submitted",
                    "desc": "Submitted for HR verification."
                }]

            app_list.append({
                "id": app.application_id,
                "tab": referrer_tab_for(app),
                "awaitingReferrerAction": is_awaiting_referrer(app),
                "bounceReason": bounce_reason_label(app),
                "rejectionCategory": app.rejection_category,
                "rejectionRemarks": app.form_correction_remarks,
                # What the referrer must DO, shown as a banner on the reopened
                # application. Derived here so both the list and the wizard use
                # identical wording.
                "actionRequired": (
                    'Choose a new Date of Joining.' if app.rejection_category == 'No Show'
                    else (f'Correction Requested: {app.form_correction_remarks}'
                          if app.form_correction_remarks else 'Correction Requested.')
                ) if is_awaiting_referrer(app) else None, 
                # The PUBLIC status. See REFERRER_PUBLIC_STATUS above.
                "status": REFERRER_PUBLIC_STATUS.get(app.status, app.status),
                "badge": badge_class,
                "ticketId": app.application_code,
                "targetCycle": target_cycle,
                "createdDate": date_str, 
                "dept": app.department.department_name if app.department else "—",
                "duration": f"{app.duration_weeks} Weeks",
                "doj": str(joining.requested_doj) if joining and joining.requested_doj else "",
                "isWard": bool(app.is_ward),
                "cycle_id": getattr(app.cycle, 'cycle_id', None) if app.cycle else None,
                "referrer_email": app.referrer_notification_email,
                "remarks": history.last().remarks if history.exists() else "",
                "student": {
                    "salutation": getattr(student, 'salutation', ""),
                    "fullName": getattr(student, 'full_name', ""),
                    "fathersName": getattr(student, 'fathers_name', ""),
                    "gender": getattr(student, 'gender', ""),
                    "dateOfBirth": str(student.date_of_birth) if student and student.date_of_birth else "",
                    "personal_email": getattr(student, 'personal_email', ""),
                    "mobile_number": getattr(student, 'mobile_number', ""),
                    "aadhaar_number": getattr(student, 'aadhaar_number', ""),
                    "permanent_address": getattr(student, 'permanent_address', ""),
                    "emergency_contact_name": getattr(student, 'emergency_contact_name', ""),
                    "emergency_contact_mobile": getattr(student, 'emergency_contact_mobile', ""),
                },
                "academic": {
                    "university_name": getattr(academic, 'university_name', ""),
                    "college_name": getattr(academic, 'college_name', ""),
                    "course": getattr(academic, 'degree_program', ""),
                    "branch": getattr(academic, 'branch_name', ""),
                    "current_semester": getattr(academic, 'current_semester', ""),
                    "grading_system": getattr(academic, 'grading_system', "CGPA"),
                    "current_score": getattr(academic, 'current_score', ""),
                },
                "documents": doc_dict,
                # What this application was ASKED for, so the vault can show
                # optional documents that were legitimately not provided rather
                # than silently omitting them.
                "documentRules": rules_for_app,
                "timeline": timeline
            })

        return Response(app_list, status=status.HTTP_200_OK)

    @employee_required
    @transaction.atomic
    def post(self, request):
        try:
            student_data = json.loads(request.POST.get('student', '{}'))
            academic_data = json.loads(request.POST.get('academic', '{}'))
            placement_data = json.loads(request.POST.get('placement', '{}'))

            # Upper case is the portal's data rule, not merely how it looks. The
            # form's `text-uppercase` styling only changes the rendering; the
            # value posted is whatever was typed. Normalising here means the
            # stored record matches what the person saw -- including in exports,
            # the archive and anything printed later.
            #
            # placement_data is left alone: it carries no free text, only ids,
            # dates and flags that are matched against stored values.
            student_data = normalise_case(student_data)
            academic_data = normalise_case(academic_data)
            
            ticket_id = request.POST.get('ticket_id')

            department = Departments.objects.get(department_name=placement_data.get('department_id'))
            cycle = InternshipCycles.objects.get(cycle_id=placement_data.get('cycle_id'))

            # The window is enforced HERE as well as in the browser. A page left
            # open past the closing date, a draft resumed afterwards, or simply a
            # crafted request would otherwise slip an application into a closed
            # or archived cycle.
            #
            # HR completing a COLLEGE REFERRAL is exempt: those records are
            # already inside the pipeline, and a closed window must never strand
            # a candidate who is mid-process.
            existing_for_cycle_check = (Applications.objects.filter(application_code=ticket_id).first()
                                        if ticket_id else None)
            is_institutional_completion = (existing_for_cycle_check is not None
                                           and is_in_college_referrals(existing_for_cycle_check))
            if not is_institutional_completion:
                allowed, reason = cycle_accepts_submissions(cycle)
                if not allowed:
                    return Response({"error": reason}, status=status.HTTP_400_BAD_REQUEST)

            
            # The custom name typed against "Other (Please Specify)".
            #
            # This comparison used to read == 'Other', two lines after
            # normalise_case() had upper-cased the payload to 'OTHER'. It
            # therefore never matched: the typed name was discarded and the
            # literal word OTHER was stored, printed in both drawers, and
            # printed on the offer letter as "a OTHER student at ...".
            #
            # resolve_custom_option() compares without regard to case, so the
            # normalisation above cannot break it again.
            course = resolve_custom_option(academic_data.get('course'),
                                           academic_data.get('course_other'))
            branch = resolve_custom_option(academic_data.get('branch'),
                                           academic_data.get('branch_other'))
            
            # Documents arrive as document_<doc_type_id>. The old fixed map of
            # five names meant a configured sixth document had nowhere to go.
            def resolve_doc_type(field_key):
                # Accept both 'document_12' and 'document_doc_12': the client key
                # carries the doc_ prefix, and tolerating it here means a stale
                # client build cannot silently drop a file.
                raw = field_key.replace('document_', '').replace('doc_', '')
                if raw.isdigit():
                    return DocumentTypes.objects.filter(doc_type_id=int(raw), is_active=1).first()
                # Legacy keys from an older client build.
                legacy = {
                    'aadhar': 'AADHAR Card', 'college_id': 'College ID',
                    'lor': 'Letter of Recommendation', 'photograph': 'Passport Photo',
                    'signature': 'Signature',
                }
                name = legacy.get(raw)
                return DocumentTypes.objects.filter(type_name=name).first() if name else None

            if ticket_id:
                application = Applications.objects.get(application_code=ticket_id)
                old_status = application.status
                
                student = application.student
                student.salutation = student_data.get('salutation')
                student.full_name = student_data.get('fullName')
                student.fathers_name = student_data.get('fathersName')
                student.gender = student_data.get('gender')
                student.date_of_birth = student_data.get('dateOfBirth') or None
                student.mobile_number = student_data.get('mobile_number')
                student.personal_email = student_data.get('personal_email')
                student.aadhaar_number = student_data.get('aadhaar_number')
                student.permanent_address = student_data.get('permanent_address')
                student.emergency_contact_name = student_data.get('emergency_contact_name')
                student.emergency_contact_mobile = student_data.get('emergency_contact_mobile')
                student.save()

                academic = AcademicDetails.objects.get(application=application)
                academic.university_name = academic_data.get('university_name')
                academic.college_name = academic_data.get('college_name')
                academic.degree_program = course
                academic.branch_name = branch
                academic.current_semester = academic_data.get('current_semester')
                academic.grading_system = academic_data.get('grading_system')
                academic.current_score = academic_data.get('current_score')
                academic.save()

                # --- INSTITUTIONAL COMPLETION / CORRECTION ------------------
                # A college referral reaches this form twice: once when HR fills
                # it from what the candidate emailed, and again if HR reopens it
                # to fix something before merging. Neither is a resubmission
                # after a bounce, so neither may take the path below -- which
                # forces the status to 'Submitted' and would silently drag the
                # record out of the College Referrals section into the main
                # Pending queue.
                if is_in_college_referrals(application):
                    return self._complete_institutional(
                        request, application, old_status,
                        department, placement_data, resolve_doc_type
                    )

                application.department = department
                application.duration_weeks = int(placement_data.get('duration_weeks', 4))
                application.is_ward = 1 if placement_data.get('is_ward') else 0
                application.status = 'Submitted'
                application.save()

                requested_doj = placement_data.get('requested_doj')
                if requested_doj:
                    joining, created = JoiningDetails.objects.get_or_create(application=application)
                    joining.requested_doj = requested_doj
                    joining.save()

                try:
                    system_user = getattr(getattr(request, 'identity', None), 'user', None)
                except ImportError:
                    system_user = None

                # Coming back from a bounce: clear the parked flag so the
                # application leaves the HR Rejected tab and re-enters Pending,
                # and mark it as a resubmission so it also surfaces in the
                # Resubmissions tab with its reason badge. rejection_category is
                # deliberately preserved -- it is what the badge displays.
                was_bounced = bool(getattr(application, 'awaiting_referrer_action', False))
                bounce_kind = application.rejection_category if was_bounced else None
                application.awaiting_referrer_action = False
                if was_bounced:
                    application.is_resubmitted = True
                application.save()

                ApplicationStatusHistory.objects.create(
                    application=application,
                    changed_by_user=system_user,
                    previous_status=old_status,
                    new_status='Submitted',
                    # RESUBMISSION_REMARKS makes the timeline say what actually
                    # changed, rather than a generic "submitted" that reads
                    # identically to the original application.
                    remarks=(RESUBMISSION_REMARKS.get(bounce_kind, 'Resubmitted after correction.')
                             if was_bounced else 'Resubmitted with corrections.'),
                    changed_at=timezone.now()
                )

                for key, file_obj in request.FILES.items():
                    if key.startswith('document_'):
                        doc_type = resolve_doc_type(key)
                        if doc_type:
                            # Supersede rather than delete: the previous version is
                            # demoted and quarantined, never destroyed in place.
                            supersede_document(
                                application, doc_type, file_obj,
                                is_override=False,
                                remarks='Applicant resubmission (correction mode).'
                            )

                # A resubmission consumes its draft exactly as a new application
                # does. This branch returned before reaching the shared cleanup,
                # so every correction left an orphaned draft behind.
                draft_id = request.POST.get('draft_id')
                if draft_id:
                    stale = ApplicationDrafts.objects.filter(
                        draft_id=draft_id, owner_employee=request.identity.employee
                    ).first()
                    if stale:
                        purge_draft(stale)

                # AND ANY DRAFT THE BROWSER DID NOT NAME.
                #
                # Opening a bounced application for editing creates a draft
                # before the portal has an id to send back, so a correction
                # submitted without touching a document left that draft behind
                # and the candidate appeared twice -- once under Submitted and
                # again under Saved Drafts.
                #
                # Matched on OWNER, CYCLE and CANDIDATE NAME, all of which this
                # application already fixes. It is deliberately not left to the
                # browser to remember: the draft exists to protect half-finished
                # work, and once the work is submitted it protects nothing.
                #
                # A referrer holding two drafts for the same candidate in the
                # same cycle has a duplicate either way, so clearing both is the
                # correct outcome rather than a risk.
                candidate_name = getattr(getattr(application, 'student', None), 'full_name', None)
                if candidate_name:
                    leftovers = ApplicationDrafts.objects.filter(
                        owner_employee=request.identity.employee,
                        cycle=application.cycle,
                        candidate_name__iexact=candidate_name,
                    )
                    for leftover in leftovers:
                        purge_draft(leftover)

                # No notification on a resubmission. Confirmed with HR: the
                # referrer has just performed the action and can see the status
                # on their portal, and Application Submitted's approved wording
                # is written for a first filing -- it quotes the Application No.
                # they already have and warns against submitting more than once.
                return Response({"message": "Application corrections submitted successfully.", "ticket_id": ticket_id}, status=status.HTTP_200_OK)

            else:
                student = Students.objects.create(
                    salutation=student_data.get('salutation'),
                    full_name=student_data.get('fullName'),
                    fathers_name=student_data.get('fathersName'),
                    gender=student_data.get('gender'),
                    date_of_birth=student_data.get('dateOfBirth') or None,
                    mobile_number=student_data.get('mobile_number'),
                    personal_email=student_data.get('personal_email'),
                    aadhaar_number=student_data.get('aadhaar_number'),
                    permanent_address=student_data.get('permanent_address'),
                    emergency_contact_name=student_data.get('emergency_contact_name'),
                    emergency_contact_mobile=student_data.get('emergency_contact_mobile')
                )

                application = Applications.objects.create(
                    student=student,
                    referral_source='Institutional' if placement_data.get('isInstitutionalMerge') else 'Employee',
                    department=department,
                    cycle=cycle,
                    duration_weeks=int(placement_data.get('duration_weeks', 4)),
                    is_ward=1 if placement_data.get('is_ward') else 0,
                    status='Ready for Merge' if placement_data.get('isInstitutionalMerge') else 'Submitted',
                    # The referrer is the signed-in employee. Previously never
                    # stored, which left the entire referrer block blank in the
                    # HR drawer. Taken from the server-side identity rather than
                    # the request body, so a referral cannot be attributed to
                    # someone else by editing the payload.
                    referrer_employee=getattr(getattr(request, 'identity', None), 'employee', None),
                    referrer_notification_email=placement_data.get('referrer_email'),
                    accepted_declarations=1,
                    doj_reschedules_count=0
                )

                # Opening entry of the audit trail. Previously absent, which left
                # both the applicant timeline and the HR audit ledger empty for
                # every new application -- only corrections were ever recorded.
                ApplicationStatusHistory.objects.create(
                    application=application,
                    changed_by_user=getattr(getattr(request, 'identity', None), 'user', None),
                    previous_status=None,
                    new_status=application.status,
                    remarks='Submitted for HR verification.',
                    # Explicit: Django sends NULL for nullable fields, which
                    # defeats the column's DEFAULT CURRENT_TIMESTAMP and leaves
                    # every timeline entry undated.
                    changed_at=timezone.now()
                )

                AcademicDetails.objects.create(
                    application=application,
                    university_name=academic_data.get('university_name'),
                    college_name=academic_data.get('college_name'),
                    degree_program=course,
                    branch_name=branch,
                    current_semester=academic_data.get('current_semester'),
                    grading_system=academic_data.get('grading_system'),
                    current_score=academic_data.get('current_score')
                )

                requested_doj = placement_data.get('requested_doj')
                if requested_doj:
                    JoiningDetails.objects.create(application=application, requested_doj=requested_doj)

                # Year read from the cycle; number derived from the highest
                # already issued and never reused. See next_application_code().
                ticket_id = next_application_code(cycle)

                application.application_code = ticket_id
                application.save()

                # Documents uploaded directly with this request.
                # Freeze the rules this application must satisfy. Everything that
                # displays its documents later reads this snapshot, so mid-cycle
                # configuration changes can never invalidate it.
                snapshot_requirements(application, cycle)

                submitted_keys = set()
                for key, file_obj in request.FILES.items():
                    if key.startswith('document_'):
                        doc_type = resolve_doc_type(key)
                        if doc_type:
                            submitted_keys.add(str(doc_type.doc_type_id))
                            supersede_document(
                                application, doc_type, file_obj,
                                is_override=False,
                                remarks='Uploaded with the application.'
                            )

                # --- CONVERT DRAFT -> APPLICATION ---
                # Files already uploaded against the draft are promoted into the
                # real document vault, so the referrer does not re-upload work
                # they did on another machine. A slot supplied directly with this
                # request wins over the draft copy of the same slot.
                draft_id = request.POST.get('draft_id')
                if draft_id:
                    draft = ApplicationDrafts.objects.filter(
                        draft_id=draft_id, owner_employee=request.identity.employee
                    ).first()
                    if draft:
                        draft_payload = (draft.payload if isinstance(draft.payload, dict)
                                         else json.loads(draft.payload or '{}'))
                        for doc_key, entry in (draft_payload.get('documents') or {}).items():
                            raw_id = str(doc_key).replace('doc_', '')
                            if raw_id in submitted_keys:
                                continue
                            doc_type = (DocumentTypes.objects
                                        .filter(doc_type_id=int(raw_id), is_active=1).first()
                                        if raw_id.isdigit() else None)
                            if doc_type is None:
                                continue
                            source = Path(settings.MEDIA_ROOT) / str(entry.get('path', ''))
                            if not entry.get('path') or not source.exists():
                                continue
                            with open(source, 'rb') as handle:
                                promoted = ContentFile(handle.read())
                                promoted.name = entry.get('name') or source.name
                                supersede_document(
                                    application, doc_type, promoted,
                                    is_override=False,
                                    remarks='Promoted from referrer draft.'
                                )
                        # The draft has become a real application; remove it and
                        # its working files so nothing is left behind on disk.
                        purge_draft(draft)

                 # --- THE EMAIL ------------------------------------------
                #
                # LAST, and this position is not cosmetic. HR's wording quotes
                # the Application No., but application_code does not exist when
                # the row is created -- next_application_code() assigns it
                # afterwards. Queue any earlier and the template's required
                # data is missing, and the notification is recorded Failed for
                # a submission that was perfectly fine.
                #
                # Skipped entirely for an institutional merge. That record has
                # no referring employee, and Application Submitted is addressed
                # to one. Guarded here rather than left to resolve_recipient()
                # because an institutional intake is a routine, expected event
                # -- letting it record Failed every time would fill the table
                # with rows describing nothing wrong. Contrast
                # HRApplicationActionAPIView, where a referrer-facing type on an
                # institutional record IS an anomaly and should be recorded.
                if not is_institutional(application):
                    queue_notification(application, ntypes.APPLICATION_SUBMITTED)

                return Response({"message": "Application and document vault successfully submitted and locked.", "ticket_id": ticket_id}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _complete_institutional(self, request, application, old_status,
                                department, placement_data, resolve_doc_type):
        """Fill in a college referral from the full Phase-1 form.

        Called for a record still inside the College Referrals section. Two
        cases, distinguished by where it currently sits:

          Pending Arrival  -> first completion. HR has collected the candidate's
                              details and documents by email and is entering
                              them. The record advances to Ready for Merge.

          Ready for Merge  -> a correction. HR reopened the form to fix
                              something before merging. The record STAYS where
                              it is; only its contents change.

        Neither case touches referrer_employee: a college referral has no
        employee behind it, and recording the HR officer would both misattribute
        the referral and grant them unlogged access to the candidate's identity
        documents.

        A correction is recorded as a resubmission on the timeline and in the
        audit ledger, naming the HR user and their role -- but is_resubmitted is
        deliberately NOT set, so the badge does not follow the record into the
        main pipeline after merge. This was HR correcting their own entry, not a
        referrer responding to a rejection.
        """
        was_already_complete = (old_status == 'Ready for Merge')

        application.department = department
        duration = placement_data.get('duration_weeks')
        application.duration_weeks = int(duration) if duration else None
        # A ward is a DMRC employee's child. An institutional candidate never is.
        application.is_ward = 0
        application.status = 'Ready for Merge'
        application.save()

        # THE FORM'S DATE WINS. HR allotted a provisional joining date at
        # scheduling; if they picked a different one here, that later decision
        # is the operative one. It stays editable right up until arrival, at
        # which point it is frozen as the actual date of joining.
        #
        # requested_doj stays empty: an employee referrer REQUESTS a date, but
        # for an institutional candidate DMRC allots one. Recording HR's own
        # allotment as the candidate's request would misrepresent it.
        chosen_doj = placement_data.get('requested_doj')
        if chosen_doj:
            joining, _ = JoiningDetails.objects.get_or_create(application=application)
            joining.allotted_date_of_joining = chosen_doj
            joining.save()

        # Freeze the document rules onto this application, exactly as an
        # employee referral does at submission. From here on every screen and
        # the merge check read this snapshot, so a mid-cycle configuration
        # change cannot alter what this record was asked to supply.
        snapshot_requirements(application, application.cycle)

        for key, file_obj in request.FILES.items():
            if key.startswith('document_'):
                doc_type = resolve_doc_type(key)
                if doc_type:
                    supersede_document(
                        application, doc_type, file_obj,
                        is_override=False,
                        actor=getattr(getattr(request, 'identity', None), 'user', None),
                        remarks=('Replaced during HR correction.' if was_already_complete
                                 else 'Collected by HR from the candidate.'),
                    )

        actor = getattr(getattr(request, 'identity', None), 'user', None)
        actor_name = getattr(getattr(actor, 'employee', None), 'full_name', 'HR')
        actor_role = getattr(getattr(actor, 'role', None), 'role_name', 'HR')

        if was_already_complete:
            remark = (f'Resubmitted after correction by {actor_name} ({actor_role}). '
                      f'Application details amended before merge.')
        else:
            remark = (f'Institutional intake completed by {actor_name} ({actor_role}). '
                      f'Candidate details and documents recorded.')

        record_application_event(
            application, actor,
            previous_status=old_status,
            new_status='Ready for Merge',
            remark=remark,
            audit_action='Ready for Merge',
        )

        return Response({
            "message": ("Corrections saved." if was_already_complete
                        else "Application completed and ready for merge."),
            "ticket_id": application.application_code,
            # What still stands between this record and the main pipeline, so
            # the dashboard can say so plainly rather than silently refusing.
            "missing": merge_blockers(application),
        }, status=status.HTTP_200_OK)

    @employee_required
    @transaction.atomic
    def patch(self, request):
        ticket_id = request.data.get('ticket')
        action = request.data.get('action')

        if not ticket_id or action != 'withdraw':
            return Response({"error": "Invalid request or missing ticket ID."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            app = Applications.objects.get(application_code=ticket_id)
            old_status = app.status
            
            app.status = 'Rejected'
            app.rejection_category = 'Withdrawn'
            app.save()

            try:
                system_user = getattr(getattr(request, 'identity', None), 'user', None)
            except ImportError:
                system_user = None

            ApplicationStatusHistory.objects.create(
                application=app,
                changed_by_user=system_user,
                previous_status=old_status,
                new_status='Rejected',
                remarks='Withdrawn by Referrer.',
                changed_at=timezone.now()
            )

            return Response({"message": f"Application {ticket_id} withdrawn successfully."}, status=status.HTTP_200_OK)

        except Applications.DoesNotExist:
            return Response({"error": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        
def serialize_hr_application(app):
    """One application in the shape BOTH HR dashboards consume.

    Extracted from HROmniQueueAPIView so the College Referrals section renders
    an institutional record through exactly the same code path as the main
    Verification Queue. That is what makes the two drawers identical: fields an
    institutional record has not collected yet simply come back empty, rather
    than being described by a second, subtly different serialiser that would
    drift from this one the first time either was changed.
    """
    student = app.student
    academic = AcademicDetails.objects.filter(application=app).first()
    joining = JoiningDetails.objects.filter(application=app).first()
    history = ApplicationStatusHistory.objects.filter(application=app).order_by('changed_at')
    docs = current_documents(app)   # live versions only
    
    app_year = getattr(app.cycle, 'application_year', '2026') if app.cycle else '2026'
    target_cycle = f"{getattr(app.cycle, 'session_term', '')} {app_year}" if app.cycle else "—"
    
    date_str = safe_extract_time(app, 'created_at', date_only=True)
    datetime_str = safe_extract_time(app, 'created_at')

    # History table is authoritative; no seeded entry (it duplicated the
    # real 'Submitted' row once submissions began recording their own).
    audit_history = []

    for h in history:
        user = getattr(h, 'changed_by_user', None)
        employee = getattr(user, 'employee', None) if user else None
        actor_name = getattr(employee, 'full_name', 'System')
        role = getattr(user, 'role', None) if user else None
        role_name = getattr(role, 'role_name', 'API')
        
        # A resubmission is reported as 'Resubmitted' rather than another
        # 'Submitted', which reads identically to the original filing.
        # The badge palette in hr_dashboard.html has a matching entry.
        action_label = 'Resubmitted' if is_resubmission_entry(h) else h.new_status
        audit_history.append({"action": action_label, "timestamp": safe_extract_time(h, 'changed_at'), "actor": actor_name, "role": role_name, "remark": h.remarks or ""})

    # Keyed by doc_<doc_type_id> to match rule.key on the front end.
    # Starts EMPTY: pre-seeding the five original names meant a document
    # added by an administrator had no slot, and the membership test
    # below silently discarded it.
    doc_dict = {}
    annexure_b_file = None
    dmra_exemption_file = None
    # Viewer links, so the drawer never has to build a path by hand. Every
    # hand-built /media/ address in this project has turned out to be broken.
    annexure_b_view = None
    dmra_exemption_view = None

    for d in docs:
        frontend_key = document_slug(d.doc_type_id) if d.doc_type_id else None
        if not frontend_key or not d.file_path:
            continue
        file_name = str(d.file_path).split('/')[-1]
        doc_dict[frontend_key] = {
            "name": file_name,
            "viewUrl": document_view_url(d),
            "protected": is_protected_document(d),
        }

        # Annexure B and the DMRA exemption are collected by HR during
        # the internship rather than uploaded by the applicant, so they
        # are surfaced separately. Matched on type NAME because they are
        # deliberately not part of the applicant's requirement snapshot.
        #
        # Compared WITHOUT regard to case: the catalogue stores 'ANNEXURE B'
        # like every other text field, so an exact match never fired and both
        # documents appeared missing however many times they were uploaded.
        type_name = (getattr(d.doc_type, 'type_name', '') or '').upper()
        if type_name == 'ANNEXURE B':
            annexure_b_file = file_name
            annexure_b_view = document_view_url(d)
        elif type_name == 'DMRA EXEMPTION LETTER':
            dmra_exemption_file = file_name
            dmra_exemption_view = document_view_url(d)

    if app.referral_source == 'Institutional':
        ref_id = "INSTITUTIONAL"
        ref_desig = "COLLEGE REFERRAL"
        ref_dept = "EXTERNAL"
        ref_email = ""
        ref_name = getattr(academic, 'college_name', "INSTITUTION")
    else:
        referrer = getattr(app, 'referrer_employee', None)
        ref_id = getattr(referrer, 'employee_code', "")
        ref_desig = getattr(referrer, 'designation', "")
        dept = getattr(referrer, 'department', None)
        ref_dept = getattr(dept, 'department_name', "")
        ref_email = app.referrer_notification_email or ""
        # The name alone. The employee directory holds no salutation, so there
        # is nothing to prefix it with -- and prefixing some names and not
        # others, depending on what happened to be seeded, read as a bug.
        ref_name = getattr(referrer, 'full_name', "Pending Referrer")

    req_doj = ""
    allotted_doj = ""
    actual_doj = None
    sub_dept = None
    dmra_date = None
    dmra_att = None
    # The END DATE AS STORED, written when the offer letter was issued and read
    # by the certificate, the completion report and the archive. The dashboard
    # used to recompute its own estimate instead, so a corrected completion date
    # changed both documents and neither queue. Empty until a letter is issued;
    # the dashboard estimates only while this is empty.
    completion_doj = None

    if joining:
        req_doj = str(joining.requested_doj) if joining.requested_doj else ""
        allotted_doj = str(joining.allotted_date_of_joining) if joining.allotted_date_of_joining else req_doj
        actual_doj = str(joining.actual_date_of_joining) if joining.actual_date_of_joining else None
        completion_doj = str(joining.date_of_completion) if joining.date_of_completion else None
        s_dept = getattr(joining, 'allotted_sub_department', None)
        sub_dept = getattr(s_dept, 'sub_department_name', None)
        dmra_date = str(joining.dmra_session_date) if joining.dmra_session_date else None
        if joining.dmra_attended is not None:
            # Sent as the STRING "true"/"false" because the dashboard binds it
            # to a pair of radio buttons, whose values are strings. NULL stays
            # None: "not yet answered" is a different state from "did not
            # attend", and the clearance blocker list distinguishes the two.
            dmra_att = "true" if joining.dmra_attended else "false"

    # --- OFFER LETTER ---------------------------------------------------------
    # Everything the Authorization & Issuance console needs about this
    # application's letter, resolved here so neither dashboard has to work it
    # out from loose fields.
    offer_doc_type = offer_letter_type()
    live_offer = current_document(app, offer_doc_type) if offer_doc_type else None
    waiting_offer = pending_document(app, offer_doc_type) if offer_doc_type else None

    signer = getattr(app, 'offer_letter_signed_by_user', None)
    signer_employee = getattr(signer, 'employee', None)

    offer_letter_state = {
        "issued": bool(app.offer_letter_issued_at),
        "issuedOn": safe_extract_time(app, 'offer_letter_issued_at', date_only=True),
        "signedBy": getattr(signer_employee, 'full_name', None),
        "signedByDesignation": getattr(signer_employee, 'designation', None),
        "version": getattr(live_offer, 'version', None),
        "fileName": (str(live_offer.file_path).split('/')[-1] if live_offer else None),
        "viewUrl": document_view_url(live_offer) if live_offer else None,
        # Downloads go through the offer letter endpoint rather than the vault,
        # because the Word copy is built on demand and has no stored row.
        "pdfUrl": (f"/api/offer-letters/file/?ticket={app.application_code}&variant=pdf"
                   if app.offer_letter_issued_at else None),
        "docxUrl": (f"/api/offer-letters/file/?ticket={app.application_code}&variant=docx"
                    if app.offer_letter_issued_at else None),
        "handoverCompletedAt": safe_extract_time(app, 'handover_completed_at'),
    }

    # --- COMPLETION CERTIFICATE ------------------------------------------
    # The same shape as the offer letter block, so both dashboards read the two
    # documents the same way.
    cert_doc_type = certificate_type()
    live_cert = current_document(app, cert_doc_type) if cert_doc_type else None
    waiting_cert = pending_document(app, cert_doc_type) if cert_doc_type else None

    cert_signer = getattr(app, 'certificate_signed_by_user', None)
    cert_employee = getattr(cert_signer, 'employee', None)

    certificate_state = {
        "issued": bool(app.certificate_issued_at),
        "issuedOn": safe_extract_time(app, 'certificate_issued_at', date_only=True),
        "signedBy": getattr(cert_employee, 'full_name', None),
        "signedByDesignation": getattr(cert_employee, 'designation', None),
        "version": getattr(live_cert, 'version', None),
        "fileName": (str(live_cert.file_path).split('/')[-1] if live_cert else None),
        "viewUrl": document_view_url(live_cert) if live_cert else None,
        "pdfUrl": (f"/api/certificates/file/?ticket={app.application_code}&variant=pdf"
                   if app.certificate_issued_at else None),
        "docxUrl": (f"/api/certificates/file/?ticket={app.application_code}&variant=docx"
                    if app.certificate_issued_at else None),
        "dispatchedAt": safe_extract_time(app, 'certificate_dispatched_at'),
        "emailStatus": app.certificate_email_status or None,
        "pending": None,
    }
    if waiting_cert is not None:
        cert_uploader = getattr(waiting_cert, 'uploaded_by_user', None)
        certificate_state["pending"] = {
            "fileName": str(waiting_cert.file_path).split('/')[-1],
            "viewUrl": document_view_url(waiting_cert),
            "uploadedBy": getattr(getattr(cert_uploader, 'employee', None), 'full_name', None),
            "uploadedAt": safe_extract_time(waiting_cert, 'uploaded_at'),
            "remark": waiting_cert.hr_remarks or "",
        }

    pending_offer = None
    if waiting_offer is not None:
        uploader = getattr(waiting_offer, 'uploaded_by_user', None)
        pending_offer = {
            "fileName": str(waiting_offer.file_path).split('/')[-1],
            # HR-APP must be able to READ a corrected letter before approving
            # it. Approving one sight-unseen would make the whole loop
            # pointless.
            "viewUrl": document_view_url(waiting_offer),
            "uploadedBy": getattr(getattr(uploader, 'employee', None), 'full_name', None),
            "uploadedAt": safe_extract_time(waiting_offer, 'uploaded_at'),
            "remark": waiting_offer.hr_remarks or "",
        }

    app_dict = {
        "id": app.application_id,
        "ticket": app.application_code or f"DRAFT-{app.application_id}",
        "name": getattr(student, 'full_name', ""),
        "cycle": target_cycle,
        "department": app.department.department_name if app.department else "",
        "status": app.status,
        "date": date_str,
        "doj": req_doj,
        "waitlisted": bool(app.is_waitlisted),
        "ward": bool(app.is_ward),
        "allottedDoj": allotted_doj,
        "subDepartment": sub_dept,
        # Real stored values. These were hardcoded, so everything HR-OPS
        # recorded during clearance vanished on the next page load.
        "evaluationResult": app.mentor_evaluation_result or "",
        "evaluationRemark": app.mentor_evaluation_remarks or "",
        "attendanceCleared": bool(app.attendance_record_verified),
        "reportCleared": bool(app.project_report_verified),
        "annexureBFile": annexure_b_file,
        "annexureB": {"fileName": annexure_b_file, "viewUrl": annexure_b_view} if annexure_b_file else None,
        "referrerName": ref_name,
        "actualDoj": actual_doj,
        "originalSubmissionDate": date_str,
        "hasUsedDocumentLifeline": False, 
        "documentResubmissionDetails": None,
        "hasUsedDojLifeline": False,
        "dojResubmissionDetails": None,
        # Bounce-back state, consumed by the Rejected / Resubmissions
        # tabs and the reason badge.
        "awaitingReferrerAction": is_awaiting_referrer(app),
        "bounceReason": bounce_reason_label(app),
        "isResubmitted": bool(app.is_resubmitted),
        "isNoShow": bool(app.is_no_show),
        # Which kind of resubmission this was, for the queue badge.
        "resubmissionBadge": (RESUBMISSION_BADGES.get(app.rejection_category)
                              if app.is_resubmitted and not is_awaiting_referrer(app) else None),
        # One-time no-show lifeline: once used, HR cannot bounce again.
        "dojLifelineUsed": (app.doj_reschedules_count or 0) >= 1,
        "isAdminEscalated": bool(app.is_admin_escalated),
        # The corrected letter waiting on HR-APP, if there is one. This used to
        # report form_correction_remarks -- a text column holding a rejection
        # remark, standing in for a file that had nowhere to live. It has a
        # proper home now: a documents row flagged is_pending_approval.
        "customOverrideFile": (pending_offer.get('fileName') if pending_offer else None),
        "pendingOfferLetter": pending_offer,
        "offerLetter": offer_letter_state,
        "referralSource": app.referral_source,
        "rejectionCategory": app.rejection_category,
        # The project report title, printed on the certificate. Kept under its
        # old name as well because the markup still binds to it; 'projectTitle'
        # is what new code should read.
        "universalTextField": app.project_report_title or "",
        "projectTitle": app.project_report_title or "",
        "clearanceBlockers": clearance_blockers(app),
        "certificate": certificate_state,
        "dmraSessionDate": dmra_date,
        "dmraAttended": dmra_att,
        "dmraExemptionFile": dmra_exemption_file,
        "dmraExemption": {"fileName": dmra_exemption_file, "viewUrl": dmra_exemption_view} if dmra_exemption_file else None,
        # What HR-APP wrote when returning the application. The Fix Joining
        # drawer has always had a red box bound to this field, and the field was
        # never sent -- so the box rendered empty and HR-OPS was told an
        # application had been returned without being told why.
        "formCorrectionRemarks": app.form_correction_remarks or "",
        "approvalRefId": app.approval_reference_id,
        # Real stored values. These were hardcoded False, so the two hard-copy
        # confirmations HR-OPS ticked at handover vanished on the next reload.
        "hardCopyUndertaking": bool(app.hardcopy_undertaking_received),
        "hardCopyAttendance": bool(app.hardcopy_attendance_received),
        "bio": {
            "salutation": getattr(student, 'salutation', ""),
            "father": getattr(student, 'fathers_name', ""),
            "gender": getattr(student, 'gender', ""),
            "dob": str(student.date_of_birth) if student and student.date_of_birth else "",
            "mobile": getattr(student, 'mobile_number', ""),
            "email": getattr(student, 'personal_email', ""),
            "address": getattr(student, 'permanent_address', ""),
            "emergencyName": getattr(student, 'emergency_contact_name', ""),
            "emergencyMobile": getattr(student, 'emergency_contact_mobile', ""),
            "aadhaar_number": getattr(student, 'aadhaar_number', "")
        },
        "academic": {
            "university": getattr(academic, 'university_name', ""),
            "college": getattr(academic, 'college_name', ""),
            "course": getattr(academic, 'degree_program', ""),
            "branch": getattr(academic, 'branch_name', ""),
            "semester": getattr(academic, 'current_semester', ""),
            "grading": getattr(academic, 'grading_system', ""),
            "score": str(academic.current_score) if academic and academic.current_score else ""
        },
        # 'duration' is the printable text and is kept because existing markup
        # binds to it. 'weeks' is the same value as a NUMBER: the dashboard used
        # to read the digits back out of the text and fall back to 4 when it
        # found none, so an application whose duration had not been chosen yet
        # silently displayed and sorted as a four-week internship. A missing
        # duration now arrives as None and is shown as unknown.
        "internship": {"duration": f"{app.duration_weeks} Weeks",
                       "weeks": app.duration_weeks},
        "completionDate": completion_doj,
        "referrer": {"id": ref_id, "designation": ref_desig, "dept": ref_dept, "email": ref_email},
        "docs": doc_dict,
        "documentRules": application_rules(app),
        "audit_history": audit_history
    }
    return app_dict


class HROmniQueueAPIView(APIView):
    """The MAIN pipeline queue.

    Institutional records still in the College Referrals section are EXCLUDED
    here. They are not yet part of the main pipeline: they hold no verified
    data, and surfacing them would put half-filled records into the Verification
    Queue's tabs, its master search and its exports. They are served instead by
    CollegeReferralAPIView, and they enter this queue the moment they are marked
    as arrived.
    """

    @role_required(*ALL_HR_ROLES)
    def get(self, request):
        applications = (Applications.objects
                        .select_related('student', 'department', 'cycle')
                        .exclude(status__in=INSTITUTIONAL_STAGING_STATUSES)
                        .order_by('-application_id'))
        return Response([serialize_hr_application(app) for app in applications],
                        status=status.HTTP_200_OK)


def archived_cycle_label(rec):
    """'Summer 2026', from an archived record's own term and year."""
    return f"{rec.session_term} {rec.application_year}"


def serialize_archived_row(rec):
    """One archived record as the TABLE needs it, and nothing more.

    This is the cheap half of a deliberate split. It reads only the
    archived_applications row itself -- no documents, no requirements, no
    timeline, no academic details -- so listing a cycle costs ONE query however
    many records it holds.

    That split is the whole reason the archive can page at all. The previous
    serialiser built the full drawer payload for every record in the cycle
    before sending anything, at four extra queries each: a 2,000-application
    cycle was roughly 10,000 queries and several megabytes of JSON, most of it
    describing records nobody would open.

    The expensive half is serialize_archived_for_drawer(), run ONCE, when a
    drawer is actually opened.
    """
    doj = rec.actual_date_of_joining or rec.allotted_date_of_joining
    return {
        "ticket": rec.application_code,
        "name": rec.student_name,
        "cycle": archived_cycle_label(rec),
        "status": rec.status,
        "ward": bool(rec.is_employee_ward),
        "submitted": rec.created_at.strftime('%d-%m-%Y') if rec.created_at else "",
        "department": rec.department_name or "",
        "referrerName": rec.referrer_name or "",
        "doj": doj.strftime('%d-%m-%Y') if doj else "",
        # The ONLY badge the archive shows. Waitlisting, resubmission and
        # lifeline history all live in the timeline, where the dates and reasons
        # are too; a badge here would repeat them without the context.
        "isInstitutional": rec.referral_source == 'Institutional',
        # Not displayed. Carried so the drawer can be fetched by a stable key
        # even if two archived cycles ever shared a ticket number.
        "originalId": rec.original_application_id,
    }


def archived_outcome_stage(rec):
    """How far this candidate actually got, derived rather than stored.

    'Completed' and 'Rejected' is a blunt cut. Rejected covers a candidate
    turned away in week one over a bad photograph AND somebody who served the
    full internship and failed their mentor's assessment -- filed identically,
    though they are not remotely the same record.

    Every branch reads a field the archive already holds, so this needs no
    column of its own and cannot fall out of step with the data.
    """
    if rec.status == 'Completed':
        return 'completed'
    if rec.rejection_category == 'Unsatisfactory Evaluation':
        # Served the internship and failed it. There is no honest version of the
        # certificate for this, so the application is rejected under its own
        # category -- but the person did the work.
        return 'failed_evaluation'
    if rec.actual_date_of_joining:
        return 'joined_not_completed'
    if rec.allotted_date_of_joining:
        return 'offered_never_joined'
    return 'rejected_at_verification'


def serialize_archived_for_drawer(rec):
    """One archived record in the EXACT shape serialize_hr_application returns.

    The archive is displayed through the same drawer as a live application, so
    this has to match that serialiser's output key for key. Where it cannot --
    an archived record has no pending correction to approve and no live
    document rows -- the key is present and empty rather than absent, because
    the drawer reads these fields unconditionally and a missing one throws.

    Built ENTIRELY from the archived_* tables. It touches no live table, so it
    reads correctly after the document catalogue, the sub-department list and
    the cycle configuration have all changed -- which, over a retention period,
    they will.
    """
    aid = rec.original_application_id
    academic = ArchivedAcademicDetails.objects.filter(original_application_id=aid).first()

    # --- DOCUMENTS ------------------------------------------------------
    # Keyed by doc_<doc_type_id> to match rule['key'], exactly as the live
    # drawer keys them. This is why doc_type_id is carried into the archive:
    # matching on NAME alone showed every requirement as unsupplied while the
    # file sat right there.
    #
    # Highest version wins, which is what current_documents() resolves to on
    # the live side.
    docs = {}
    annexure_b_file = None
    annexure_b_view = None
    dmra_exemption_file = None
    dmra_exemption_view = None
    offer_letter_doc = None
    certificate_doc = None

    for d in (ArchivedDocuments.objects
              .filter(original_application_id=aid)
              .order_by('-version', '-archive_doc_id')):
        key = (document_slug(d.doc_type_id) if d.doc_type_id
               else document_slug_for_name(d.doc_type_name))
        file_name = Path(str(d.file_path)).name
        if key not in docs:
            docs[key] = {
                "name": file_name,
                "viewUrl": archived_document_view_url(d),
                # Every archived document is served through the secure endpoint.
                # WHAT happens there differs -- an archived Aadhaar card is
                # watermarked, an archived offer letter is served for printing --
                # and that is decided by is_system_generated, carried on the row.
                "protected": True,
                "isGenerated": bool(d.is_system_generated),
                "version": d.version,
                "verification": d.verification_status,
            }

        # Annexure B and the DMRA exemption are collected by HR during the
        # internship rather than uploaded by the applicant, so the drawer
        # surfaces them separately. Matched on type NAME without regard to case,
        # for the reason the live serialiser does: the catalogue stores
        # 'ANNEXURE B' in capitals like every other text field.
        type_name = (d.doc_type_name or '').upper()
        if type_name == 'ANNEXURE B' and annexure_b_file is None:
            annexure_b_file = file_name
            annexure_b_view = archived_document_view_url(d)
        elif type_name == 'DMRA EXEMPTION LETTER' and dmra_exemption_file is None:
            dmra_exemption_file = file_name
            dmra_exemption_view = archived_document_view_url(d)

        # The two GENERATED documents, matched by the same name constants the
        # live code uses. Matched on name rather than looked up through
        # DocumentTypes because the archive must not depend on the catalogue
        # still holding a row for either of them.
        if type_name == OFFER_LETTER_TYPE.upper() and offer_letter_doc is None:
            offer_letter_doc = docs[key]
        elif type_name == CERTIFICATE_TYPE.upper() and certificate_doc is None:
            certificate_doc = docs[key]

    # --- WHAT THE CANDIDATE WAS ASKED FOR --------------------------------
    # Empty is a MEANINGFUL answer. A college referral rejected before its form
    # was ever filled was never asked for anything, and the drawer says exactly
    # that rather than showing today's rules in its place.
    #
    # Deliberately NOT falling back to the cycle's live configuration the way
    # application_rules() does for live records: that fallback exists for
    # applications predating snapshots, and applying it here would invent a
    # history this candidate never had.
    document_rules = [{
        "id": r.doc_type_id,
        "key": (document_slug(r.doc_type_id) if r.doc_type_id
                else document_slug_for_name(r.doc_type_name)),
        "name": r.doc_type_name,
        "format": r.allowed_extensions,
        "isMandatory": bool(r.is_mandatory),
        "requiresConsent": bool(r.requires_consent),
        "order": r.display_order,
        "wasSupplied": bool(r.was_supplied),
    } for r in (ArchivedDocumentRequirements.objects
                .filter(original_application_id=aid)
                .order_by('display_order', 'archive_requirement_id'))]

    # --- TIMELINE ---------------------------------------------------------
    # Named audit_history and shaped action/timestamp/actor/role/remark, because
    # that is what the live drawer's timeline renders.
    audit_history = [{
        "action": h.new_status,
        "timestamp": safe_extract_time(h, 'changed_at'),
        "actor": h.changed_by_name or "System",
        "role": h.changed_by_role or "API",
        "remark": h.remarks or "",
    } for h in (ArchivedStatusHistory.objects
                .filter(original_application_id=aid)
                .order_by('archive_history_id'))]

    doj = rec.actual_date_of_joining or rec.allotted_date_of_joining

    def _date(value):
        return value.strftime('%Y-%m-%d') if value else None

    # --- OFFER LETTER AND CERTIFICATE -------------------------------------
    # The same shape the live drawer reads, built from the archived fields.
    #
    # pdfUrl and docxUrl are NULL on purpose. Those endpoints regenerate a
    # document from the live application row, which no longer exists -- and the
    # Word copy is built on demand and never stored. What DOES exist is the
    # signed PDF as it was filed, reachable through viewUrl below.
    offer_doc = offer_letter_doc or {}
    cert_doc = certificate_doc or {}

    offer_letter_state = {
        "issued": bool(rec.offer_letter_issued_at),
        "issuedOn": safe_extract_time(rec, 'offer_letter_issued_at', date_only=True),
        "signedBy": rec.offer_letter_signed_by_name,
        "signedByDesignation": rec.offer_letter_signed_by_designation,
        "version": offer_doc.get('version'),
        "fileName": offer_doc.get('name'),
        "viewUrl": offer_doc.get('viewUrl'),
        "pdfUrl": None,
        "docxUrl": None,
        "handoverCompletedAt": safe_extract_time(rec, 'handover_completed_at'),
    }

    certificate_state = {
        "issued": bool(rec.certificate_issued_at),
        "issuedOn": safe_extract_time(rec, 'certificate_issued_at', date_only=True),
        "signedBy": rec.certificate_signed_by_name,
        "signedByDesignation": rec.certificate_signed_by_designation,
        "version": cert_doc.get('version'),
        "fileName": cert_doc.get('name'),
        "viewUrl": cert_doc.get('viewUrl'),
        "pdfUrl": None,
        "docxUrl": None,
        "dispatchedAt": safe_extract_time(rec, 'certificate_dispatched_at'),
        "emailStatus": rec.certificate_email_status or None,
        # An archived cycle cannot hold a correction awaiting approval: nothing
        # closes with work still parked with HR-APP.
        "pending": None,
    }

    return {
        # --- IDENTITY -----------------------------------------------------
        "id": rec.original_application_id,
        "ticket": rec.application_code,
        "name": rec.student_name,
        "cycle": archived_cycle_label(rec),
        "department": rec.department_name or "",
        "status": rec.status,
        "date": rec.created_at.strftime('%d-%m-%Y') if rec.created_at else "",
        "originalSubmissionDate": rec.created_at.strftime('%d-%m-%Y') if rec.created_at else "",

        # --- THE READ-ONLY GUARD ------------------------------------------
        # ONE flag, read once at the top of the drawer, rather than a condition
        # on each action panel. An action added to the drawer next year is then
        # disabled by default instead of being live on closed records until
        # somebody remembers it exists.
        "isArchivedRecord": True,
        "archivedOn": rec.archived_at.strftime('%d-%m-%Y') if rec.archived_at else "",
        "outcomeStage": archived_outcome_stage(rec),

        # --- DATES --------------------------------------------------------
        "doj": _date(rec.requested_date_of_joining) or "",
        "allottedDoj": _date(rec.allotted_date_of_joining) or _date(rec.requested_date_of_joining) or "",
        "actualDoj": _date(rec.actual_date_of_joining),
        "completionDate": _date(rec.date_of_completion),
        "dojDisplay": doj.strftime('%d-%m-%Y') if doj else "",

        # --- FLAGS --------------------------------------------------------
        "waitlisted": bool(rec.is_waitlisted),
        "ward": bool(rec.is_employee_ward),
        "isNoShow": bool(rec.is_no_show),
        "isResubmitted": bool(rec.is_resubmitted),
        "isAdminEscalated": bool(rec.is_admin_escalated),
        "dojLifelineUsed": (rec.doj_reschedules_count or 0) >= 1,
        "referralSource": rec.referral_source,
        "rejectionCategory": rec.rejection_category,
        "subDepartment": rec.allotted_sub_department,

        # Bounce-back state. FALSE by definition: a cycle cannot be closed while
        # anything is still parked with a referrer awaiting their correction.
        "awaitingReferrerAction": False,
        "bounceReason": None,
        "resubmissionBadge": None,
        "hasUsedDocumentLifeline": False,
        "documentResubmissionDetails": None,
        "hasUsedDojLifeline": (rec.doj_reschedules_count or 0) >= 1,
        "dojResubmissionDetails": None,

        # --- CLEARANCE ----------------------------------------------------
        "evaluationResult": rec.mentor_evaluation_result or "",
        "evaluationRemark": rec.mentor_evaluation_remarks or "",
        "attendanceCleared": bool(rec.attendance_record_verified),
        "reportCleared": bool(rec.project_report_verified),
        "universalTextField": rec.project_report_title or "",
        "projectTitle": rec.project_report_title or "",
        # Nothing is left to block: the internship is closed. An empty list is
        # what the drawer reads as "no blockers".
        "clearanceBlockers": [],
        "approvalRefId": rec.approval_reference_id,
        "formCorrectionRemarks": rec.form_correction_remarks or "",

        # --- DMRA ---------------------------------------------------------
        "dmraSessionDate": _date(rec.dmra_session_date),
        "dmraAttended": (None if rec.dmra_attended is None
                         else ("true" if rec.dmra_attended else "false")),
        "dmraExemptionFile": dmra_exemption_file,
        "dmraExemption": ({"fileName": dmra_exemption_file, "viewUrl": dmra_exemption_view}
                          if dmra_exemption_file else None),
        "annexureBFile": annexure_b_file,
        "annexureB": ({"fileName": annexure_b_file, "viewUrl": annexure_b_view}
                      if annexure_b_file else None),

        # --- HANDOVER -----------------------------------------------------
        "hardCopyUndertaking": bool(rec.hardcopy_undertaking_received),
        "hardCopyAttendance": bool(rec.hardcopy_attendance_received),

        # --- DOCUMENTS AND LETTERS ----------------------------------------
        "offerLetter": offer_letter_state,
        "certificate": certificate_state,
        "pendingOfferLetter": None,
        "customOverrideFile": None,

        # --- THE PERSON ---------------------------------------------------
        "bio": {
            "salutation": rec.student_salutation or "",
            "father": rec.student_fathers_name or "",
            "gender": rec.student_gender or "",
            "dob": _date(rec.student_date_of_birth) or "",
            "mobile": rec.student_mobile or "",
            "email": rec.student_email or "",
            "address": rec.student_permanent_address or "",
            "emergencyName": rec.student_emergency_contact_name or "",
            "emergencyMobile": rec.student_emergency_contact_mobile or "",
            "aadhaar_number": rec.student_aadhaar or "",
        },
        "academic": {
            "university": (academic.university_name if academic else "") or "",
            "college": rec.college_name or "",
            "course": (academic.degree_program if academic else "") or "",
            "branch": rec.branch_name or "",
            "semester": (academic.current_semester if academic else "") or "",
            "grading": rec.grading_system or "",
            "score": str(rec.current_score) if rec.current_score is not None else "",
        },
        "internship": {
            "duration": f"{rec.duration_weeks} Weeks" if rec.duration_weeks else "",
            "weeks": rec.duration_weeks,
        },
        "referrerName": rec.referrer_name or "",
        "referrer": {
            "id": rec.referrer_employee_code or ("INSTITUTIONAL" if rec.referral_source == 'Institutional' else ""),
            "designation": rec.referrer_designation or ("COLLEGE REFERRAL" if rec.referral_source == 'Institutional' else ""),
            "dept": rec.referrer_department or ("EXTERNAL" if rec.referral_source == 'Institutional' else ""),
            "email": rec.referrer_notification_email or "",
        },

        "docs": docs,
        "documentRules": document_rules,
        "audit_history": audit_history,
    }


def archive_cycle_records(cycle, actor_user):
    """Move every application in one cycle into the archive.

    COPY, VERIFY, THEN DELETE -- inside the caller's transaction, so a failure
    at any point leaves the cycle exactly as it was rather than half archived.

    Six things are copied, because everything attached to an application is ON
    DELETE CASCADE and would otherwise be destroyed with it:

        1. the application record          -> archived_applications
        2. academic details                -> archived_academic_details
        3. documents (paths only)          -> archived_documents
        4. what it was ASKED to supply     -> archived_document_requirements
        5. its timeline                    -> archived_status_history
        6. the cycle's approved DOJ list   -> archived_cycle_joining_dates

    (6) is per-CYCLE rather than per-application, and it is what lets the
    archive's joining-date calendar distinguish a normal intake date from one
    HR allotted outside the approved calendar.

    FILES ARE NOT MOVED. They stay under PROTECTED_DOCUMENT_ROOT and the archive
    keeps their paths, which are stored RELATIVE to a configured root -- so
    relocating the document folder is a settings change and archived documents
    keep resolving. What is new here is that every file is CHECKED before
    anything is deleted; see below.

    The archive is deliberately SELF-CONTAINED. Every field is a name or a value
    -- never a link to document_types, sub_departments or internship_cycles --
    so a record stays readable after the document catalogue, the unit list and
    the cycle configuration have all changed, which over a retention period they
    certainly will.

    Returns a count of what was archived.
    """
    applications = (Applications.objects
                    .filter(cycle=cycle)
                    .select_related('student', 'department',
                                    'referrer_employee',
                                    'referrer_employee__department',
                                    'offer_letter_signed_by_user__employee',
                                    'certificate_signed_by_user__employee'))

    counts = {'applications': 0, 'documents': 0, 'requirements': 0,
              'history': 0, 'drafts': 0, 'joiningDates': 0}
    student_ids = []

    # --- SAVED DRAFTS ----------------------------------------------------
    # Deleted HERE, inside the archive transaction, along with their uploaded
    # files. A draft for an archived cycle can never be submitted, so leaving it
    # would show every referrer a half-finished application for a cycle that no
    # longer exists -- and clicking Resume on one used to silently reassign it
    # to a different cycle.
    #
    # There is a housekeeping sweep, purge_drafts_for_closed_cycles(), but it
    # runs at the START of an admin request, so on the archiving request itself
    # it clears drafts for cycles closed EARLIER, never the one being closed
    # now. Those drafts survived until an administrator happened to touch a
    # cycle again.
    for draft in ApplicationDrafts.objects.filter(cycle=cycle):
        purge_draft(draft)
        counts['drafts'] += 1

    # --- ROWS ARE BUILT IN MEMORY, THEN INSERTED IN BATCHES ---------------
    # The previous version called .create() once per row inside a single
    # transaction. At DMRC's volumes -- 500 to 2,000 applications, each with
    # documents, requirements and a timeline -- that is tens of thousands of
    # individual statements in one transaction. TiDB caps both the statement
    # count and the total size of a transaction, so a full-size cycle could fail
    # outright, and even where it succeeded the round trips alone could outlast
    # the web server's timeout.
    #
    # Correctness is unchanged: this is still one transaction, and the delete
    # below still happens only after the copy is verified.
    archived_rows = []
    academic_rows = []
    document_rows = []
    requirement_rows = []
    history_rows = []
    missing_files = []

    for app in applications:
        student = app.student
        academic = AcademicDetails.objects.filter(application=app).first()
        joining = JoiningDetails.objects.filter(application=app).first()

        # For an institutional application the INSTITUTION stands in the
        # referrer's place, exactly as it does on every live screen.
        if app.referral_source == 'Institutional':
            referrer_name = getattr(academic, 'college_name', None) or 'INSTITUTIONAL'
            referrer_code = None
            referrer_designation = 'COLLEGE REFERRAL'
            referrer_department = 'EXTERNAL'
        else:
            referrer = app.referrer_employee
            referrer_name = getattr(referrer, 'full_name', None)
            referrer_code = getattr(referrer, 'employee_code', None)
            # The post and unit AS THEY WERE. The directory follows an employee
            # when they are promoted or transferred; the record of who sponsored
            # this candidate must not follow them.
            referrer_designation = getattr(referrer, 'designation', None)
            referrer_department = getattr(
                getattr(referrer, 'department', None), 'department_name', None)

        archived_rows.append(ArchivedApplications(
            original_application_id=app.application_id,
            application_code=app.application_code,
            dmrc_reference_code=getattr(app, 'dmrc_reference_code', None),

            # --- THE CANDIDATE, IN FULL -----------------------------------
            # All eleven, because the archived record is now displayed through
            # the same drawer as a live one. Seven of these were previously
            # discarded, so the drawer's personal block would have opened blank.
            student_salutation=getattr(student, 'salutation', None),
            student_name=getattr(student, 'full_name', '') or '',
            student_fathers_name=getattr(student, 'fathers_name', None),
            student_gender=getattr(student, 'gender', None),
            student_date_of_birth=getattr(student, 'date_of_birth', None),
            student_email=getattr(student, 'personal_email', '') or '',
            student_mobile=getattr(student, 'mobile_number', None),
            student_aadhaar=getattr(student, 'aadhaar_number', None),
            student_permanent_address=getattr(student, 'permanent_address', None),
            student_emergency_contact_name=getattr(student, 'emergency_contact_name', None),
            student_emergency_contact_mobile=getattr(student, 'emergency_contact_mobile', None),

            college_name=getattr(academic, 'college_name', None) or '\u2014',
            branch_name=getattr(academic, 'branch_name', None),
            grading_system=getattr(academic, 'grading_system', None),
            current_score=getattr(academic, 'current_score', None),
            department_name=getattr(app.department, 'department_name', None),
            # The sub-department by NAME. The unit may later be renamed or
            # removed; what this candidate was posted to must not change with it.
            allotted_sub_department=getattr(
                getattr(joining, 'allotted_sub_department', None),
                'sub_department_name', None),
            session_term=cycle.session_term,
            application_year=cycle.application_year,
            duration_weeks=app.duration_weeks,
            status=app.status,
            is_waitlisted=bool(getattr(app, 'is_waitlisted', 0)),
            is_no_show=bool(getattr(app, 'is_no_show', 0)),
            is_employee_ward=bool(getattr(app, 'is_ward', 0)),
            referral_source=app.referral_source,
            referrer_name=referrer_name,
            referrer_employee_code=referrer_code,
            referrer_designation=referrer_designation,
            referrer_department=referrer_department,
            referrer_notification_email=getattr(app, 'referrer_notification_email', None),

            # Three dates. The gap between requested and allotted is the record
            # of a scheduling decision somebody made.
            requested_date_of_joining=getattr(joining, 'requested_doj', None),
            allotted_date_of_joining=getattr(joining, 'allotted_date_of_joining', None),
            actual_date_of_joining=getattr(joining, 'actual_date_of_joining', None),
            dmra_session_date=getattr(joining, 'dmra_session_date', None),
            dmra_attended=getattr(joining, 'dmra_attended', None),
            date_of_completion=getattr(joining, 'date_of_completion', None),
            rejection_category=getattr(app, 'rejection_category', None),

            # --- OFFER LETTER AND HANDOVER --------------------------------
            offer_letter_issued_at=getattr(app, 'offer_letter_issued_at', None),
            offer_letter_signed_by_name=getattr(
                getattr(getattr(app, 'offer_letter_signed_by_user', None), 'employee', None),
                'full_name', None),
            offer_letter_signed_by_designation=getattr(
                getattr(getattr(app, 'offer_letter_signed_by_user', None), 'employee', None),
                'designation', None),
            hardcopy_undertaking_received=bool(getattr(app, 'hardcopy_undertaking_received', 0)),
            hardcopy_attendance_received=bool(getattr(app, 'hardcopy_attendance_received', 0)),
            handover_completed_at=getattr(app, 'handover_completed_at', None),

            # --- CLEARANCE, CERTIFICATE AND DISPATCH ----------------------
            # NONE OF THESE WERE PREVIOUSLY COPIED. The offer-letter fields
            # above were, and these were skipped -- so every intern who actually
            # completed was archived with no evaluation, no project title and no
            # record of who signed their certificate. Archiving is irreversible,
            # so that was destroyed at closure rather than merely hidden.
            mentor_evaluation_result=getattr(app, 'mentor_evaluation_result', None),
            mentor_evaluation_remarks=getattr(app, 'mentor_evaluation_remarks', None),
            project_report_title=getattr(app, 'project_report_title', None),
            attendance_record_verified=bool(getattr(app, 'attendance_record_verified', 0)),
            project_report_verified=bool(getattr(app, 'project_report_verified', 0)),
            certificate_issued_at=getattr(app, 'certificate_issued_at', None),
            certificate_signed_by_name=getattr(
                getattr(getattr(app, 'certificate_signed_by_user', None), 'employee', None),
                'full_name', None),
            certificate_signed_by_designation=getattr(
                getattr(getattr(app, 'certificate_signed_by_user', None), 'employee', None),
                'designation', None),
            certificate_dispatched_at=getattr(app, 'certificate_dispatched_at', None),
            certificate_email_status=getattr(app, 'certificate_email_status', None),
            form_correction_remarks=getattr(app, 'form_correction_remarks', None),

            approval_reference_id=getattr(app, 'approval_reference_id', None),
            is_admin_escalated=bool(getattr(app, 'is_admin_escalated', 0)),
            is_resubmitted=bool(getattr(app, 'is_resubmitted', 0)),
            doj_reschedules_count=app.doj_reschedules_count or 0,
            archived_year=timezone.localdate().year,
            created_at=app.created_at or timezone.now(),
            archived_at=timezone.now(),
        ))
        counts['applications'] += 1

        if academic:
            academic_rows.append(ArchivedAcademicDetails(
                original_application_id=app.application_id,
                university_name=academic.university_name,
                college_name=academic.college_name or '\u2014',
                degree_program=academic.degree_program,
                branch_name=academic.branch_name,
                current_semester=academic.current_semester,
                grading_system=academic.grading_system,
                current_score=academic.current_score,
            ))

        # --- DOCUMENTS: paths only; the files stay on disk ----------------
        supplied_names = set()
        for doc in Documents.objects.filter(application=app).select_related('doc_type'):
            type_name = getattr(doc.doc_type, 'type_name', 'Unknown')
            if doc.is_current:
                supplied_names.add(type_name)

            # --- VERIFY THE FILE IS ACTUALLY THERE ------------------------
            # Checked BEFORE anything is deleted. A file already missing from
            # disk at closure -- removed by hand, lost in a restore, never
            # written because of an earlier failure -- would otherwise be
            # recorded as archived and only discovered years later, when there
            # is no live row left to compare it against.
            if stored_document_path(doc) is None:
                missing_files.append(
                    f"{app.application_code}: {type_name} ({doc.file_path})")

            document_rows.append(ArchivedDocuments(
                original_application_id=app.application_id,
                original_document_id=doc.document_id,
                application_code=app.application_code,
                # Carried so the drawer can pair this file with the requirement
                # it satisfied. Matching on name alone showed every requirement
                # as unsupplied while the file sat right there.
                doc_type_id=doc.doc_type_id,
                doc_type_name=type_name,
                file_path=doc.file_path,
                version=doc.version or 1,
                is_manually_overridden=bool(getattr(doc, 'is_manually_overridden', 0)),
                is_system_generated=bool(getattr(doc.doc_type, 'is_system_generated', 0)),
                verification_status=doc.verification_status,
                hr_remarks=getattr(doc, 'hr_remarks', None),
                uploaded_at=doc.uploaded_at or timezone.now(),
            ))
            counts['documents'] += 1

        # --- WHAT IT WAS ASKED FOR ---------------------------------------
        for req in (ApplicationDocumentRequirements.objects
                    .filter(application=app)
                    .order_by('display_order', 'requirement_id')):
            requirement_rows.append(ArchivedDocumentRequirements(
                original_application_id=app.application_id,
                application_code=app.application_code,
                doc_type_id=req.doc_type_id,
                doc_type_name=req.doc_type_name,
                allowed_extensions=req.allowed_extensions,
                is_mandatory=bool(req.is_mandatory),
                requires_consent=bool(req.requires_consent),
                display_order=req.display_order or 0,
                # Recorded rather than derived, so the archive can answer
                # "was this supplied?" without joining anything.
                was_supplied=req.doc_type_name in supplied_names,
            ))
            counts['requirements'] += 1

        # --- TIMELINE -----------------------------------------------------
        for h in (ApplicationStatusHistory.objects
                  .filter(application=app)
                  .select_related('changed_by_user__employee',
                                  'changed_by_user__role')
                  .order_by('history_id')):
            actor = h.changed_by_user
            history_rows.append(ArchivedStatusHistory(
                original_application_id=app.application_id,
                application_code=app.application_code,
                previous_status=h.previous_status,
                new_status=h.new_status,
                # Name and role, not a link: staff leave and accounts are
                # removed, but an archived decision must still say who took it.
                changed_by_name=getattr(getattr(actor, 'employee', None), 'full_name', None),
                changed_by_role=getattr(getattr(actor, 'role', None), 'role_name', None),
                remarks=h.remarks,
                changed_at=h.changed_at,
                archived_at=timezone.now(),
            ))
            counts['history'] += 1

        student_ids.append(app.student_id)

    # --- REFUSE ON A MISSING FILE ----------------------------------------
    # Named individually, the way the cycle already names the tickets blocking
    # closure. Archiving is irreversible: an administrator has to be able to
    # find the file or accept its loss knowingly, not discover it in 2031.
    if missing_files:
        shown = missing_files[:10]
        more = len(missing_files) - len(shown)
        raise RuntimeError(
            f"{len(missing_files)} document file(s) for "
            f"{cycle.session_term} {cycle.application_year} are missing from "
            f"storage and cannot be archived: "
            + "; ".join(shown)
            + (f"; and {more} more" if more else "")
            + "."
        )

    # --- WRITE ------------------------------------------------------------
    ArchivedApplications.objects.bulk_create(archived_rows, batch_size=ARCHIVE_BATCH_SIZE)
    ArchivedAcademicDetails.objects.bulk_create(academic_rows, batch_size=ARCHIVE_BATCH_SIZE)
    ArchivedDocuments.objects.bulk_create(document_rows, batch_size=ARCHIVE_BATCH_SIZE)
    ArchivedDocumentRequirements.objects.bulk_create(requirement_rows, batch_size=ARCHIVE_BATCH_SIZE)
    ArchivedStatusHistory.objects.bulk_create(history_rows, batch_size=ARCHIVE_BATCH_SIZE)

    # --- THE CYCLE'S APPROVED JOINING CALENDAR ---------------------------
    # Snapshotted so the archive's date filter can tell a normal intake date
    # from one HR allotted outside the approved calendar. Withdrawn dates are
    # kept with was_enabled = False rather than skipped: a date an administrator
    # removed mid-cycle can still have people allotted to it, and dropping it
    # would misreport those candidates as exceptions.
    joining_date_rows = [
        ArchivedCycleJoiningDates(
            session_term=cycle.session_term,
            application_year=cycle.application_year,
            allowed_doj=d.allowed_doj,
            was_enabled=bool(d.is_active),
            archived_at=timezone.now(),
        )
        for d in CycleJoiningDates.objects.filter(cycle=cycle).order_by('allowed_doj')
        if d.allowed_doj
    ]
    ArchivedCycleJoiningDates.objects.bulk_create(joining_date_rows,
                                                  batch_size=ARCHIVE_BATCH_SIZE)
    counts['joiningDates'] = len(joining_date_rows)

    # --- VERIFY BEFORE DELETING ------------------------------------------
    # Nothing is destroyed until the copy is confirmed present. On failure the
    # caller's transaction rolls back and the cycle stays exactly as it was.
    archived_codes = set(
        ArchivedApplications.objects
        .filter(session_term=cycle.session_term, application_year=cycle.application_year)
        .values_list('application_code', flat=True)
    )
    live_codes = set(applications.values_list('application_code', flat=True))
    missing = live_codes - archived_codes
    if missing:
        raise RuntimeError(
            f"Archive verification failed for {cycle.session_term} "
            f"{cycle.application_year}: {len(missing)} application(s) were not "
            f"copied. Nothing has been deleted."
        )

    # --- DELETE -----------------------------------------------------------
    # Children are removed EXPLICITLY, in foreign-key order, rather than left to
    # the database's ON DELETE CASCADE.
    #
    # The live schema does declare those cascades, so relying on them would work
    # today. But this code is being handed to DMRC IT to deploy, and a table
    # rebuilt without its constraints would silently leave orphaned rows behind
    # instead of failing. Doing it here means the behaviour is identical on any
    # engine and visible to anyone reading the function.
    app_ids = list(applications.values_list('application_id', flat=True))

    AcademicDetails.objects.filter(application_id__in=app_ids).delete()
    Documents.objects.filter(application_id__in=app_ids).delete()
    JoiningDetails.objects.filter(application_id__in=app_ids).delete()
    ApplicationStatusHistory.objects.filter(application_id__in=app_ids).delete()
    ApplicationDocumentRequirements.objects.filter(application_id__in=app_ids).delete()
    Notifications.objects.filter(application_id__in=app_ids).delete()

    Applications.objects.filter(application_id__in=app_ids).delete()

    # Students last: applications cascade FROM students, so removing the
    # applications first leaves these rows orphaned.
    Students.objects.filter(student_id__in=student_ids).delete()

    return counts


# How many archived records are drawn at once.
#
# Matches the two live queues, which page at 25. Unlike those, this is not only
# a drawing limit: the archive slices in SQL, so a page is also all that is ever
# fetched. The EXPORTS remain unpaged -- see UniversalExportAPIView.
ARCHIVE_PAGE_SIZE = 25

# What may be sorted on, and the archived column behind each.
#
# A fixed map rather than passing the request's value into order_by(): that
# would let a crafted request order by any column in the table, including ones
# never meant to leave it.
ARCHIVE_SORT_COLUMNS = {
    'ticket': 'application_code',
    'name': 'student_name',
    'college': 'college_name',
    'department': 'department_name',
    'submitted': 'created_at',
    'doj': 'actual_date_of_joining',
    'completion': 'date_of_completion',
    'duration': 'duration_weeks',
}

# Sorts where an EMPTY value must sink to the bottom whichever way the column is
# ordered. A rejected candidate never joined and never completed; scattering
# those blanks through the dated records makes the list unreadable. The live
# archive screen already behaved this way in the browser and the behaviour is
# preserved now that sorting happens in SQL.
ARCHIVE_SORT_NULLS_LAST = {'doj', 'completion', 'duration', 'submitted'}


def archive_filter_queryset(records, params):
    """Apply the archive's filters to a queryset, in SQL.

    Every filter reads a field the archive holds in its own tables. Nothing here
    touches a live cycle, department or document type: the point of the archive
    is that it still reads correctly once all three have changed.
    """
    def value(name):
        raw = (params.get(name) or '').strip()
        return raw or None

    def flag(name):
        return (params.get(name) or '').lower() in ('1', 'true', 'yes')

    outcome = value('outcome')
    if outcome:
        records = records.filter(status=outcome)

    # HOW FAR THEY GOT. Derived from stored fields rather than a column of its
    # own, so it cannot fall out of step with the data -- see
    # archived_outcome_stage(), which is the same logic for a single record.
    stage = value('stage')
    if stage == 'completed':
        records = records.filter(status='Completed')
    elif stage == 'failed_evaluation':
        # Served the internship and failed the assessment. Not the same record
        # as somebody turned away in week one, though both read 'Rejected'.
        records = records.exclude(status='Completed').filter(
            rejection_category='Unsatisfactory Evaluation')
    elif stage == 'joined_not_completed':
        records = (records.exclude(status='Completed')
                   .exclude(rejection_category='Unsatisfactory Evaluation')
                   .filter(actual_date_of_joining__isnull=False))
    elif stage == 'offered_never_joined':
        records = (records.exclude(status='Completed')
                   .exclude(rejection_category='Unsatisfactory Evaluation')
                   .filter(actual_date_of_joining__isnull=True,
                           allotted_date_of_joining__isnull=False))
    elif stage == 'rejected_at_verification':
        records = (records.exclude(status='Completed')
                   .exclude(rejection_category='Unsatisfactory Evaluation')
                   .filter(actual_date_of_joining__isnull=True,
                           allotted_date_of_joining__isnull=True))

    if value('department'):
        records = records.filter(department_name=params.get('department').strip())
    if value('subDepartment'):
        records = records.filter(allotted_sub_department=params.get('subDepartment').strip())
    if value('source'):
        records = records.filter(referral_source=params.get('source').strip())
    if value('rejectionCategory'):
        records = records.filter(rejection_category=params.get('rejectionCategory').strip())
    if value('evaluationResult'):
        records = records.filter(mentor_evaluation_result=params.get('evaluationResult').strip())
    if value('emailStatus'):
        records = records.filter(certificate_email_status=params.get('emailStatus').strip())

    duration = value('duration')
    if duration:
        try:
            records = records.filter(duration_weeks=int(duration))
        except (TypeError, ValueError):
            pass

    # A SINGLE joining date, because joining dates cluster on a handful of
    # approved intake dates -- 'the batch that joined on 14 July' is the real
    # question. Matched against EITHER date: a candidate who was allotted a date
    # and never arrived still belongs to that intake.
    doj = value('doj')
    if doj:
        records = records.filter(
            Q(actual_date_of_joining=doj) | Q(allotted_date_of_joining=doj))

    # Completion dates are a RANGE, because they do not cluster: each is that
    # person's joining date plus their own duration, and with 4, 6 and 8-week
    # internships mixed together a single date would usually match nobody.
    if value('completedFrom'):
        records = records.filter(date_of_completion__gte=params.get('completedFrom').strip())
    if value('completedTo'):
        records = records.filter(date_of_completion__lte=params.get('completedTo').strip())

    if flag('ward'):
        records = records.filter(is_employee_ward=True)
    if flag('waitlisted'):
        records = records.filter(is_waitlisted=True)
    if flag('noShow'):
        records = records.filter(is_no_show=True)
    if flag('resubmitted'):
        records = records.filter(is_resubmitted=True)
    if flag('adminEscalated'):
        records = records.filter(is_admin_escalated=True)
    if flag('dojRescheduleUsed'):
        records = records.filter(doj_reschedules_count__gte=1)

    # OFF-CALENDAR JOINING DATE: allotted a day the administrator never
    # approved. HR may do this deliberately, and after closure this is the only
    # place it is visible -- which is exactly why an auditor would ask.
    #
    # Compared against the SNAPSHOT taken at closure, not against live cycle
    # configuration, so it keeps answering correctly after the cycle rows have
    # been tidied away.
    if flag('offCalendarDoj'):
        term = params.get('term')
        year = params.get('year')
        approved = list(ArchivedCycleJoiningDates.objects
                        .filter(session_term=term, application_year=year)
                        .values_list('allowed_doj', flat=True))
        records = records.filter(
            Q(actual_date_of_joining__isnull=False) |
            Q(allotted_date_of_joining__isnull=False))
        if approved:
            records = records.exclude(actual_date_of_joining__in=approved).exclude(
                allotted_date_of_joining__in=approved)

    # SEARCH runs after the filters, narrowing what is already on screen.
    #
    # Department and sub-department are deliberately NOT searched: both have
    # their own dropdown, and matching them here as well meant a typed search
    # quietly returned a different set than the dropdown did.
    search = value('search')
    if search:
        records = records.filter(
            Q(application_code__icontains=search) |
            Q(student_name__icontains=search) |
            Q(college_name__icontains=search) |
            Q(referrer_name__icontains=search) |
            Q(referrer_employee_code__icontains=search)
        )

    return records


class HRArchiveAPIView(APIView):
    """Cold Storage Vault -- applications from cycles that have been hard-closed.

    SYS-ADMIN ONLY. Archived records carry full candidate details including
    Aadhaar numbers and are kept for years; access is deliberately narrower than
    the live queue, which all three HR roles may read.

    Read entirely from the archived_* tables. Nothing here depends on a live
    cycle, document type or sub-department still existing.

    FILTERED, SORTED AND PAGED IN SQL. It used to serialise every record in a
    cycle -- the full drawer payload, four extra queries each -- and send the
    lot for the browser to filter. At DMRC's volumes that is around 10,000
    queries and several megabytes for a single cycle, most of it describing
    records nobody would open. The browser now receives one page of nine
    columns, and the drawer payload is built once, on demand, by
    /api/hr/archives/record/.
    """

    @role_required('SYS-ADMIN')
    def get(self, request):
        params = request.GET

        # The year and cycle pickers offer ONLY what has actually been archived.
        # They used to be hardcoded to 2025 and 2026 with both terms assumed,
        # which offered cycles that had never existed.
        #
        # Keyed by the CYCLE's own term and year, not the year of archiving: a
        # Winter 2026 cycle closed in March 2027 is still Winter 2026 to
        # everyone who goes looking for it.
        cycles_by_year = {}
        for term, year in (ArchivedApplications.objects
                           .values_list('session_term', 'application_year')
                           .distinct()):
            cycles_by_year.setdefault(str(year), set()).add(f"{term} {year}")
        available = {y: sorted(v) for y, v in cycles_by_year.items()}
        pickers = {
            "availableYears": sorted(available.keys(), reverse=True),
            "cyclesByYear": available,
        }

        term = params.get('term')
        year = params.get('year')
        if not (term and year):
            # Nothing selected yet: send the pickers, not the whole vault.
            return Response({"records": [], "total": 0, "page": 1, "pageCount": 1,
                             "pageSize": ARCHIVE_PAGE_SIZE, "rangeLabel": "0 of 0",
                             "options": {}, **pickers}, status=status.HTTP_200_OK)

        # Two cycles that somehow shared a term and year would merge here,
        # because the archive is keyed by term and year rather than by cycle id.
        # Ticket numbers stay unique across them: numbering never reuses a
        # number and checks the archive as well as the live table.
        cycle_records = ArchivedApplications.objects.filter(
            session_term=term, application_year=year)

        records = archive_filter_queryset(cycle_records, params)

        # --- SORT ---------------------------------------------------------
        sort_key = params.get('sortKey') or 'ticket'
        if sort_key not in ARCHIVE_SORT_COLUMNS:
            sort_key = 'ticket'
        column = ARCHIVE_SORT_COLUMNS[sort_key]
        descending = (params.get('sortDir') or 'asc').lower() == 'desc'

        if sort_key in ARCHIVE_SORT_NULLS_LAST:
            # Blanks sink to the bottom in BOTH directions, which is not what
            # plain DESC does -- it would surface every empty date first.
            order = F(column).desc(nulls_last=True) if descending else F(column).asc(nulls_last=True)
            # application_code second, so a page boundary never splits records
            # that tie on the sort column into an arbitrary order.
            records = records.order_by(order, 'application_code')
        else:
            records = records.order_by(f"-{column}" if descending else column,
                                       'application_code')

        # --- PAGE ---------------------------------------------------------
        total = records.count()
        page_count = max(1, -(-total // ARCHIVE_PAGE_SIZE))
        try:
            page = int(params.get('page') or 1)
        except (TypeError, ValueError):
            page = 1
        # CLAMPED rather than rejected: a filter that shortens the list while
        # the reader is on page 8 should show the last page, not an error and
        # not an empty table under a pager still claiming page 8 of 2.
        page = min(max(1, page), page_count)
        start = (page - 1) * ARCHIVE_PAGE_SIZE
        window = records[start:start + ARCHIVE_PAGE_SIZE]

        range_label = ("0 of 0" if total == 0 else
                       f"{start + 1}\u2013{min(start + ARCHIVE_PAGE_SIZE, total)} of {total}")

        return Response({
            "records": [serialize_archived_row(r) for r in window],
            "total": total,
            "page": page,
            "pageCount": page_count,
            "pageSize": ARCHIVE_PAGE_SIZE,
            "rangeLabel": range_label,
            # The dropdown options for THIS cycle. Computed here because the
            # browser now holds one page and could no longer derive them: built
            # from the page, a Department dropdown would list only the
            # departments that happened to appear in the first 25 rows.
            "options": archive_filter_options(term, year),
            **pickers,
        }, status=status.HTTP_200_OK)


def archive_filter_options(term, year):
    """The dropdown values and calendar marks for ONE archived cycle.

    Only what actually appears in this cycle. Offering today's live lists would
    suggest options matching nothing, since departments, units and document
    rules all change over the years the archive is kept.
    """
    cycle_records = ArchivedApplications.objects.filter(
        session_term=term, application_year=year)

    def distinct(column):
        return sorted({v for v in cycle_records.values_list(column, flat=True) if v})

    # --- THE JOINING CALENDAR -----------------------------------------
    # Three kinds of day, which is what the filter's calendar marks:
    #
    #   approved and used        a normal intake date
    #   approved, never used     offered, nobody was allotted it
    #   used but NEVER approved  an exception was made for that candidate
    #
    # The third is the one worth having. HR may allot ANY date when scheduling,
    # and after closure this is the only place that decision is visible.
    approved = sorted({d.strftime('%Y-%m-%d') for d in
                       ArchivedCycleJoiningDates.objects
                       .filter(session_term=term, application_year=year)
                       .values_list('allowed_doj', flat=True) if d})

    used = set()
    for actual, allotted in cycle_records.values_list('actual_date_of_joining',
                                                      'allotted_date_of_joining'):
        chosen = actual or allotted
        if chosen:
            used.add(chosen.strftime('%Y-%m-%d'))

    return {
        "departments": distinct('department_name'),
        "subDepartments": distinct('allotted_sub_department'),
        "rejectionCategories": distinct('rejection_category'),
        "durations": sorted({v for v in
                             cycle_records.values_list('duration_weeks', flat=True)
                             if v}),
        "approvedDojDates": approved,
        "usedDojDates": sorted(used),
        # Allotted a day the administrator never approved. Sent separately so
        # the calendar can mark it differently rather than the browser having to
        # work out the difference itself.
        "offCalendarDojDates": sorted(used - set(approved)),
    }


class HRArchiveRecordAPIView(APIView):
    """ONE archived record, in the shape the live drawer consumes.

    Split out from the list because it is the expensive half: documents,
    requirements, the timeline and the academic details, four queries beyond the
    record itself. Building that for every record in a cycle just in case one
    was opened is what made the archive screen unusable at DMRC's volumes.

    SYS-ADMIN only, matching the vault itself.
    """

    @role_required('SYS-ADMIN')
    def get(self, request):
        ticket = (request.GET.get('ticket') or '').strip()
        if not ticket:
            return Response({"error": "No ticket was specified."},
                            status=status.HTTP_400_BAD_REQUEST)

        rec = ArchivedApplications.objects.filter(application_code=ticket).first()
        if rec is None:
            return Response({"error": f"No archived record found for {ticket}."},
                            status=status.HTTP_404_NOT_FOUND)

        return Response(serialize_archived_for_drawer(rec),
                        status=status.HTTP_200_OK)


def date_value_changed(incoming, previous):
    """True if `incoming` names a different date from the one already stored.

    Guards against re-sending an email for a date that has not moved. HR may
    PATCH the same record several times -- correcting a sub-department, marking
    an arrival -- and the browser resends the whole form each time, so the
    joining date arrives again unchanged on every one of those requests.

    The queue's duplicate guard does not cover this. It suppresses a second
    PENDING row, which stops a double-click, but once the first email has been
    sent that row is Sent and no longer blocks anything. Without this check the
    candidate would be re-told their reporting date on every subsequent edit.

    The two sides arrive in different shapes: `incoming` is the string the
    browser posted ('2026-03-15'), `previous` is a datetime.date read from the
    database. Both are reduced to an ISO string rather than parsed, which needs
    no import and behaves the same if a real date object is ever passed in.
    """
    if not incoming:
        return False
    return str(incoming) != (previous.isoformat() if previous else '')

class HRApplicationActionAPIView(APIView):
    @role_required(*ALL_HR_ROLES)
    @transaction.atomic
    def patch(self, request):
        try:
            ticket = request.data.get('ticket')
            new_status = request.data.get('status')
            # Remark fields are styled uppercase in the dashboard, so the stored
            # text must match what the person saw themselves type.
            remark = upper_text(request.data.get('remark', '') or '')
            
            allotted_doj = request.data.get('allottedDoj')
            actual_doj = request.data.get('actualDoj')
            sub_department = request.data.get('subDepartment')
            is_admin_escalated = request.data.get('isAdminEscalated')
            is_god_mode = request.data.get('isGodMode', False)
            custom_override_file = request.data.get('customOverrideFile')
            dmra_session_date = request.data.get('dmraSessionDate')
            
            department_name = request.data.get('department')
            ward = request.data.get('ward')
            dob = request.data.get('dob')

            if not ticket or not new_status:
                return Response({"error": "Ticket ID and new status are required."}, status=status.HTTP_400_BAD_REQUEST)

            app = Applications.objects.get(application_code=ticket)
            old_status = app.status

            app.status = new_status

            # --- REFERRER BOUNCE-BACK -------------------------------------
            # bounceCategory is sent when HR pushes an application back to the
            # referrer ('Invalid Document' for a correction request, 'No Show'
            # for a joining no-show). The application is parked as Rejected so
            # it appears in the HR Rejected tab, while awaiting_referrer_action
            # marks it as recoverable rather than closed.
            bounce_category = request.data.get('bounceCategory')
            if bounce_category:
                if bounce_category not in BOUNCE_CATEGORIES:
                    return Response(
                        {"error": f"'{bounce_category}' is not a valid bounce reason. "
                                  f"Expected one of: {', '.join(BOUNCE_CATEGORIES)}."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # A correction request MUST carry a reason. The remark is the only
                # thing telling the referrer WHAT to fix, so an empty one sends
                # them back an application with no instruction. Enforced here, on
                # the server, so it holds regardless of what the browser does.
                if bounce_category == 'Invalid Document' and not (remark or '').strip():
                    return Response(
                        {"error": "A remark is required when requesting a correction. "
                                  "It is the only explanation the referrer receives, "
                                  "so state clearly what needs to be fixed."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # LIFELINE RULES
                #   Document correction : unlimited. A referrer may be asked to
                #       fix paperwork as many times as HR requires, and every
                #       round is recorded in the timeline and audit ledger.
                #   No-show             : ONE ONLY. A candidate who fails to
                #       report gets a single second chance at a new joining date.
                #       Enforced here, on the server, so it cannot be bypassed
                #       from the browser.
                # An exhausted lifeline can still be REJECTED -- it just cannot
                # be returned to the referrer for a third date. lifelineExhausted
                # says the caller knows that and is closing the application.
                lifeline_exhausted = bool(request.data.get('lifelineExhausted'))
                if (bounce_category == 'No Show' and not lifeline_exhausted
                        and (app.doj_reschedules_count or 0) >= 1):
                    return Response(
                        {"error": "No-show lifeline already used. This candidate has already "
                                  "been given one rescheduled joining date and cannot be "
                                  "returned to the referrer again."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                app.status = 'Rejected'
                app.rejection_category = bounce_category
                # An ADMIN ESCALATION is a rejection that is NOT the referrer's
                # to act on: the application is held for a SYS-ADMIN to change
                # the joining date. It still carries its category, so it appears
                # in the Rejected tab and reads as Rejected to the referrer --
                # it used to be filed with no category at all and vanished from
                # the queue entirely, visible to nobody.
                # Neither an escalation nor an exhausted-lifeline rejection is
                # the referrer's to act on.
                app.awaiting_referrer_action = not (bool(is_admin_escalated) or lifeline_exhausted)
                app.form_correction_remarks = remark or None
                if bounce_category == 'No Show':
                    app.is_no_show = True
                    # The lifeline is consumed by the REFERRER route only. An
                    # escalation asks an administrator to fix a date; it is not
                    # the candidate's second chance and must not spend it.
                    if not is_admin_escalated:
                        app.doj_reschedules_count = (app.doj_reschedules_count or 0) + 1

            # RETURNED TO HR-OPS FOR JOINING CORRECTIONS.
            #
            # Not a rejection and not a referrer bounce. The candidate is fine;
            # the joining logistics are wrong -- the sub-department, the date --
            # and those belong to HR-OPS, not to the referrer, who can do
            # nothing about either.
            #
            # The remark is what HR-OPS is shown in the red box on the Fix
            # Joining drawer, so it is the whole point of the action and is
            # stored even though the status is not a rejection.
            elif new_status in ('Fix Joining', 'Fix Clearance'):
                app.awaiting_referrer_action = False
                app.form_correction_remarks = remark or None

            # LEAVING a fix queue clears the remark. It describes a problem that
            # has just been put right, and leaving it behind would show the red
            # correction box on an application with nothing wrong with it.
            #
            # OLD_STATUS, not app.status: the new status was assigned above, so
            # testing app.status here compares the destination against itself and
            # the branch can never be true.
            elif old_status in ('Fix Joining', 'Fix Clearance'):
                app.form_correction_remarks = None

            # A final rejection closes the application: it must not remain
            # actionable for the referrer.
            elif new_status == 'Rejected':
                app.awaiting_referrer_action = False
                if request.data.get('rejectionCategory'):
                    app.rejection_category = request.data.get('rejectionCategory')
                if remark:
                    # No rejection_reason column exists; the remark lives in
                    # form_correction_remarks for both bounces and rejections.
                    app.form_correction_remarks = remark
            # --------------------------------------------------------------

            # --- WHICH NOTIFICATION THIS ACTION OWES ----------------------
            #
            # Decided here, not at the bottom, because three different outcomes
            # all leave status='Rejected' and only the branch that produced it
            # knows which one this was. Nothing is sent from this method: a
            # queued row is a Pending record, and `manage.py send_notifications`
            # sends it later.
            #
            # A NO-SHOW is announced only when the referrer can actually act on
            # it. HR's approved wording tells them to pick a new joining date
            # from the referrer portal -- true for an ordinary no-show, false
            # for an admin escalation (held for a SYS-ADMIN) and false for an
            # exhausted lifeline (their one reschedule is spent). Both of those
            # leave awaiting_referrer_action False, which is exactly the test.
            # Sending it anyway would send someone to a portal with nothing on
            # it. Confirmed with HR.
            #
            # The no-show branch deliberately does NOT fall through to
            # Application Rejected. Those cases carry status='Rejected' and
            # would otherwise pick it up, telling a referrer their candidate was
            # rejected when what happened was a missed joining date.
            notification_type = None
            if bounce_category == 'Invalid Document':
                notification_type = ntypes.RETURNED_FOR_CORRECTION
            elif bounce_category == 'No Show':
                if app.awaiting_referrer_action:
                    notification_type = ntypes.NO_SHOW
            elif app.status == 'Rejected' and old_status != 'Rejected':
                notification_type = ntypes.APPLICATION_REJECTED
            elif app.status == 'Approved' and old_status != 'Approved':
                notification_type = ntypes.APPLICATION_APPROVED

            # Filled in by the arrival/scheduling block below. Initialised here
            # because that block is conditional and may not run at all.
            joining_notifications = []

            if is_admin_escalated is not None:
                # Field confirmed present on Applications; no hasattr guard so a
                # future rename fails loudly instead of silently dropping the flag.
                app.is_admin_escalated = is_admin_escalated

            if is_god_mode:
                if department_name:
                    try:
                        new_dept = Departments.objects.get(department_name=department_name)
                        app.department = new_dept
                    except Departments.DoesNotExist:
                        pass
                if ward is not None:
                    app.is_ward = 1 if ward else 0
                if dob and app.student:
                    app.student.date_of_birth = dob
                    app.student.save()
            app.save()

            # --- ARRIVAL ---------------------------------------------------
            # Confirming arrival is what sets the ACTUAL date of joining, and
            # that date is the operative one from then on: it is printed on the
            # offer letter and the completion certificate, it drives the
            # projected end date, and it is what the archive and every audit
            # report carry. A candidate never marked as arrived never joined.
            #
            # This was previously set in the browser only -- no code path on the
            # server ever wrote actual_date_of_joining -- so the date vanished
            # on the next page load, leaving the completion report, the exports
            # and the archive permanently blank. It is written here, once, for
            # BOTH pipelines.
            #
            # HR may supply an explicit date when recording an arrival a day or
            # two late; otherwise today's date is used.
            is_arrival = (app.status == 'Pending Offer Letter'
                          and old_status != 'Pending Offer Letter')

            if is_arrival or allotted_doj or sub_department or dmra_session_date or custom_override_file:
                joining, created = JoiningDetails.objects.get_or_create(application=app)

                # Read BEFORE anything below overwrites them. These decide
                # whether the candidate is told about a date they have not been
                # told about yet.
                previous_allotted_doj = joining.allotted_date_of_joining
                previous_dmra_session_date = joining.dmra_session_date

                if is_arrival:
                    joining.actual_date_of_joining = actual_doj or timezone.localdate()
                elif actual_doj:
                    # An explicit correction to an already-recorded arrival.
                    joining.actual_date_of_joining = actual_doj

                # NOTE: field names below MUST match models.py exactly. Django does
                # not raise on assigning an unknown attribute -- it silently creates
                # a throwaway Python attribute that .save() ignores. Do NOT wrap these
                # in hasattr() guards; a wrong name should fail loudly, not vanish.
                if allotted_doj:
                    joining.allotted_date_of_joining = allotted_doj

                if sub_department:
                    # allotted_sub_department is a ForeignKey, so the incoming name
                    # string must be resolved to a SubDepartments row.
                    try:
                        # Names are stored upper-cased by cycle initialisation, but
                        # the value arriving from the picker may differ in case or
                        # padding. Matching loosely avoids rejecting a legitimate
                        # selection over presentation.
                        joining.allotted_sub_department = SubDepartments.objects.get(
                            sub_department_name__iexact=str(sub_department).strip()
                        )
                    except SubDepartments.DoesNotExist:
                        return Response(
                            {"error": f"Unknown sub-department '{sub_department}'. "
                                      f"It is not registered in the sub_departments table."},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                if dmra_session_date:
                    joining.dmra_session_date = dmra_session_date

                # TODO(schema): custom_override_file has no column on joining_details
                # and no home in the schema yet. Deliberately NOT assigned -- writing
                # it here would be a silent no-op. Decide between a new
                # joining_details column or a documents-table row, then wire it up.
                # if custom_override_file:
                #     joining.custom_offer_file = custom_override_file

                joining.save()

                # A joining date confirms the candidate's reporting details; a
                # DMRA session date summons them to the Academy. Both go to the
                # candidate, and both are announced only when the date is new or
                # has moved -- see date_value_changed().
                if date_value_changed(allotted_doj, previous_allotted_doj):
                    joining_notifications.append(ntypes.JOINING_SCHEDULE)
                if date_value_changed(dmra_session_date, previous_dmra_session_date):
                    joining_notifications.append(ntypes.ACADEMY_SCHEDULE)

            system_user = getattr(getattr(request, 'identity', None), 'user', None)

            # --- PER-APPLICATION TIMELINE ---
            # application_status_history drives the timeline shown in BOTH portals.
            # It is a different table from system_audit_logs (the global admin
            # ledger) and both must be written. Previously only the global ledger
            # was updated here, so every HR action -- approvals, corrections,
            # no-shows, rejections -- was invisible on the timeline, which only
            # ever showed the applicant's original submission.
            #
            # Written OUTSIDE the try/except below so a genuine failure surfaces
            # rather than silently costing the application its audit trail.
            if app.status != old_status:
                action_remark = canonical_action_remark(
                    bounce_category, bool(is_admin_escalated), remark
                ) or f'Status changed to {app.status}.'
                ApplicationStatusHistory.objects.create(
                    application=app,
                    changed_by_user=system_user,
                    previous_status=old_status,
                    new_status=app.status,
                    remarks=action_remark,
                    changed_at=timezone.now()
                )

            try:
                with transaction.atomic():
                    SystemAuditLogs.objects.create(
                        actor_user=system_user,
                        role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                        action_type='SYSTEM_OVERRIDE' if is_god_mode else new_status,
                        target_entity_type='Application',
                        target_entity_id=app.pk,
                        new_value=json.dumps({"remarks": canonical_action_remark(
                            bounce_category, bool(is_admin_escalated), remark) or remark})
                    )
            except Exception as audit_error:
                logger.error("AUDIT WRITE FAILED (%s): %s",
                             type(audit_error).__name__, audit_error)

            # --- NOTIFICATIONS --------------------------------------------
            #
            # Last, deliberately. Everything above has been written, so each
            # email is composed from the record as it now stands rather than
            # from half-applied state -- the joining date in a Joining Schedule
            # email is the one that was just saved.
            #
            # INSIDE the transaction, also deliberately. This method is
            # @transaction.atomic, so if anything later rolls the request back
            # the queued rows go with it and no email is sent for an action that
            # did not happen.
            #
            # queue_notification() writes a row and never raises: a missing
            # referrer address or an absent joining date is recorded as a Failed
            # row with a reason, not thrown. A notification problem cannot turn
            # a completed HR action into a 500.
            for queued_type in [notification_type, *joining_notifications]:
                if queued_type:
                    queue_notification(app, queued_type)

            return Response({"message": f"Ticket {ticket} synchronized successfully."}, status=status.HTTP_200_OK)

        except Applications.DoesNotExist:
            return Response({"error": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# archive_one_application() WAS REMOVED HERE.
#
# It archived a SINGLE application and nothing ever called it -- but it was
# worse than dead, it was broken. It passed actor_name / actor_role to
# ArchivedStatusHistory, whose fields were renamed to changed_by_name /
# changed_by_role, so it would have raised TypeError on the first timeline row
# it touched. It also omitted application_code, original_document_id and
# is_system_generated when copying documents, which would have left every
# archived document unopenable in the secure viewer and served DMRC's own
# letters through the watermarked candidate-document path.
#
# Per-application archiving was considered and deliberately NOT built: a cycle
# is the unit of closure, and archiving one person out of a running cycle would
# remove them from the queue their colleagues are still working.




def record_application_event(application, actor_user, *, previous_status,
                             new_status, remark, audit_action=None,
                             audit_only=False):
    """Write ONE event to the timeline and the audit ledger together.

    Two separate records serve two separate readers:

      application_status_history -- the candidate's story, shown on the timeline
                                    in both portals.
      system_audit_logs          -- the forensic ledger, showing who did what,
                                    under which role, with what detail.

    Every step of the College Referrals pipeline writes both, exactly as the
    main pipeline does, so an institutional record's history is as complete and
    as attributable as an employee referral's.

    audit_only=True records to the ledger alone. Used for small in-place edits
    -- correcting a misspelt surname, say -- which belong in the forensic record
    but would clutter the candidate's timeline with non-events.
    """
    role_name = getattr(getattr(actor_user, 'role', None), 'role_name', 'SYSTEM')

    if not audit_only:
        ApplicationStatusHistory.objects.create(
            application=application,
            changed_by_user=actor_user,
            previous_status=previous_status,
            new_status=new_status,
            remarks=remark,
            # Explicit: Django sends NULL for nullable fields, which defeats the
            # column's DEFAULT CURRENT_TIMESTAMP and leaves the entry undated.
            changed_at=timezone.now(),
        )

    try:
        with transaction.atomic():
            SystemAuditLogs.objects.create(
                actor_user=actor_user,
                role_name=role_name,
                action_type=audit_action or new_status,
                target_entity_type='Application',
                target_entity_id=application.pk,
                new_value=json.dumps({"remarks": remark or ""}),
            )
    except Exception as audit_error:
        logger.error("AUDIT WRITE FAILED (%s): %s",
                     type(audit_error).__name__, audit_error)


class CollegeReferralAPIView(APIView):
    """The College Referrals pipeline: intake, scheduling, completion, arrival.

    GET   /api/college-referrals/          every record still in the section
    POST  /api/college-referrals/          file a preliminary intake
    PATCH /api/college-referrals/          act on one record (see ACTIONS)

    All three dashboard roles may operate this section, exactly as they may the
    main Verification Queue. There is deliberately no god-mode override here:
    every field is already editable by design while a record is being
    assembled, so a privileged bypass would add risk without adding capability.

    Records are invisible to the main queue -- including its master search and
    its exports -- until they are marked as arrived. See HROmniQueueAPIView.
    """

    ACTIONS = ('update', 'schedule', 'reject', 'reschedule', 'arrive')

    # --------------------------------------------------------------- GET ---
    @role_required(*ALL_HR_ROLES)
    def get(self, request):
        applications = (Applications.objects
                        .filter(referral_source='Institutional',
                                status__in=INSTITUTIONAL_STAGING_STATUSES)
                        .select_related('student', 'department', 'cycle')
                        .order_by('-application_id'))

        records = []
        for app in applications:
            # Serialised through the SAME function as the main queue, so the
            # drawer is identical field for field. Anything not yet collected
            # comes back empty rather than fabricated.
            record = serialize_hr_application(app)

            # What still stands between this record and the main pipeline. The
            # dashboard uses it to explain a disabled 'Mark as Arrived' button
            # instead of leaving HR guessing why nothing happens.
            record['mergeBlockers'] = merge_blockers(app)
            record['canReschedule'] = (app.doj_reschedules_count or 0) < 1

            # The cycle by ID, not by name. The application form previously had
            # to match the cycle's LABEL ("Winter 2027") against its own list to
            # recover the id -- and when that match failed for any reason the
            # form silently opened on the referrer's dashboard instead of the
            # candidate's application, with nothing said about why. The record
            # already knows which cycle it belongs to; it now says so.
            record['cycleId'] = app.cycle_id
            records.append(record)

        # --- REFERENCE DATA ---------------------------------------------
        # Cycles, joining dates and sub-departments are ALSO served here, and
        # deliberately so.
        #
        # The dashboard's other source for these is /api/admin/cycles/ and
        # /api/admin/configs/, both of which are SYS-ADMIN only. An HR-OPS or
        # HR-APP user gets 403 from both, which would leave this screen with an
        # empty cycle dropdown, no selectable joining dates and no
        # sub-departments -- unusable for precisely the people who operate it.
        #
        # This exposes only what the College Referrals screen legitimately
        # needs: which cycles accept an intake, which dates may be allotted, and
        # which units a candidate may be posted to. No quotas, no IAM data, no
        # audit ledger. It is the same reasoning that produced
        # PortalBootstrapAPIView for the referrer portal.
        today = timezone.localdate()
        cycles, doj_by_cycle, sub_depts_by_cycle = [], {}, {}

        for cycle in InternshipCycles.objects.filter(is_active=1).order_by('-cycle_id'):
            label = f"{cycle.session_term} {cycle.application_year}"

            # A closed cycle still appears, marked shut: records already inside
            # it must stay workable, and HR needs to see why no new intake can
            # be filed against it.
            cycles.append({
                "id": cycle.cycle_id,
                "name": label,
                "term": cycle.session_term,
                "year": cycle.application_year,
                "acceptsNewIntake": bool(
                    cycle.application_end_date is None or today <= cycle.application_end_date
                ),
                "start": cycle.application_start_date.strftime('%Y-%m-%d') if cycle.application_start_date else None,
                "end": cycle.application_end_date.strftime('%Y-%m-%d') if cycle.application_end_date else None,
            })

            doj_by_cycle[label] = [
                d.allowed_doj.strftime('%Y-%m-%d')
                for d in CycleJoiningDates.objects.filter(cycle=cycle, is_active=1).order_by('allowed_doj')
                if d.allowed_doj
            ]

            # Per-cycle sub-department list, so a unit switched off by an
            # administrator disappears here immediately -- the same source the
            # Admin Control Center configures.
            mapped = (CycleSubDepartments.objects
                      .filter(cycle=cycle, is_active=1)
                      .select_related('sub_department'))
            names = [m.sub_department.sub_department_name for m in mapped if m.sub_department]
            if not names:
                names = list(SubDepartments.objects
                             .filter(is_global_active=1)
                             .order_by('sub_department_name')
                             .values_list('sub_department_name', flat=True))
            sub_depts_by_cycle[label] = names

        return Response({
            "records": records,
            "cycles": cycles,
            "allowedDojDatesByCycle": doj_by_cycle,
            "subDepartmentsByCycle": sub_depts_by_cycle,
            "departments": list(Departments.objects
                                .order_by('department_name')
                                .values_list('department_name', flat=True)),
        }, status=status.HTTP_200_OK)

    # -------------------------------------------------------------- POST ---
    @role_required(*ALL_HR_ROLES)
    @transaction.atomic
    def post(self, request):
        """File a preliminary intake from what the college actually sent.

        Mandatory: cycle, candidate name, college name, email.
        Optional:  department, course, branch, mobile.

        The optional fields are genuinely optional -- a college's list is often
        incomplete, and refusing the whole record over a missing branch would
        force HR to invent one. They are collected later, in the full form.
        """
        # Upper case on the way in, so the stored record matches the form's
        # styling. The email keeps its case: it is machine-read, not scanned.
        cycle_id = request.data.get('cycleId')
        student_name = upper_text((request.data.get('studentName') or '').strip())
        college_name = upper_text((request.data.get('collegeName') or '').strip())
        email = (request.data.get('email') or '').strip()

        missing = []
        if not cycle_id:      missing.append('Target cycle')
        if not student_name:  missing.append('Candidate name')
        if not college_name:  missing.append('College / institution name')
        if not email:         missing.append('Email address')
        if missing:
            return Response(
                {"error": f"Cannot file this intake. Missing: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        cycle = InternshipCycles.objects.filter(cycle_id=cycle_id).first()
        if cycle is None:
            return Response({"error": "That cycle does not exist."},
                            status=status.HTTP_400_BAD_REQUEST)

        # A closed cycle accepts no NEW intakes. Records already inside the
        # section are unaffected and can still be completed and merged -- see
        # the PATCH handler, which deliberately performs no such check.
        today = timezone.localdate()
        if not cycle.is_active or (cycle.application_end_date and today > cycle.application_end_date):
            return Response(
                {"error": f"{cycle.session_term} {cycle.application_year} is closed to new "
                          f"intakes. Records already in the College Referrals section can "
                          f"still be completed and merged."},
                status=status.HTTP_400_BAD_REQUEST
            )

        department = None
        department_name = (request.data.get('department') or '').strip()
        if department_name:
            department = Departments.objects.filter(department_name=department_name).first()
            if department is None:
                return Response({"error": f"Unknown department '{department_name}'."},
                                status=status.HTTP_400_BAD_REQUEST)

        student = Students.objects.create(
            full_name=student_name,
            personal_email=email,
            mobile_number=(request.data.get('mobile') or '').strip() or None,
        )

        application = Applications.objects.create(
            student=student,
            referral_source='Institutional',
            # No employee referrer, and none is invented. Recording the HR
            # officer here would attribute the referral to them and would also
            # grant them unlogged access to the candidate's identity documents,
            # since document access treats the referrer as the owner.
            referrer_employee=None,
            referrer_notification_email=None,
            department=department,
            cycle=cycle,
            duration_weeks=None,
            is_ward=0,
            accepted_declarations=0,
            status='Intake Draft',
            doj_reschedules_count=0,
            awaiting_referrer_action=0,
        )

        application.application_code = next_application_code(cycle)
        application.save(update_fields=['application_code'])

        AcademicDetails.objects.create(
            application=application,
            college_name=college_name,
            # Same resolver the Phase-1 form uses, so a custom degree entered
            # at institutional intake survives the merge and reaches the letter
            # exactly as one entered by a referrer does.
            degree_program=upper_text(resolve_custom_option(
                request.data.get('course'), request.data.get('course_other'))) or None,
            branch_name=upper_text(resolve_custom_option(
                request.data.get('branch'), request.data.get('branch_other'))) or None,
        )

        actor = getattr(getattr(request, 'identity', None), 'user', None)
        record_application_event(
            application, actor,
            previous_status=None,
            new_status='Intake Draft',
            remark=f'Institutional intake filed from {college_name}.',
            audit_action='Intake Draft',
        )

        return Response({
            "message": f"Intake filed as {application.application_code}.",
            "ticket": application.application_code,
            "id": application.application_id,
        }, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------- PATCH ---
    @role_required(*ALL_HR_ROLES)
    @transaction.atomic
    def patch(self, request):
        ticket = request.data.get('ticket')
        action = request.data.get('action')

        if not ticket or action not in self.ACTIONS:
            return Response(
                {"error": f"A ticket and one of these actions are required: "
                          f"{', '.join(self.ACTIONS)}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        application = (Applications.objects
                       .select_related('student', 'department', 'cycle')
                       .filter(application_code=ticket).first())
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if not is_in_college_referrals(application):
            return Response(
                {"error": "This application is no longer in the College Referrals "
                          "section. Act on it from the Verification Queue instead."},
                status=status.HTTP_400_BAD_REQUEST
            )

        actor = getattr(getattr(request, 'identity', None), 'user', None)
        remark = upper_text((request.data.get('remark') or '').strip())
        old_status = application.status

        handler = getattr(self, f"_action_{action}")
        return handler(request, application, actor, remark, old_status)

    # ------------------------------------------------------------------------
    def _action_update(self, request, application, actor, remark, old_status):
        """Correct the preliminary details in place, without moving the record.

        Everything HR filed at intake stays editable while the record is being
        assembled -- a name taken down wrongly from a college's list should be
        fixable without ceremony. The change is recorded in the AUDIT LEDGER but
        NOT on the timeline: the ledger is where forensic detail belongs, while
        the timeline tells the candidate's story and would be drowned by
        typo corrections.
        """
        changes = []
        student = application.student

        for field, attr in (('studentName', 'full_name'),
                            ('email', 'personal_email'),
                            ('mobile', 'mobile_number')):
            if field in request.data:
                value = (request.data.get(field) or '').strip() or None
                # Everything but the email is upper-cased, matching the form.
                if field != 'email':
                    value = upper_text(value)
                if value != getattr(student, attr, None):
                    changes.append(f"{attr}: {getattr(student, attr, None)} -> {value}")
                    setattr(student, attr, value)
        student.save()

        academic = AcademicDetails.objects.filter(application=application).first()
        if academic:
            for field, attr in (('collegeName', 'college_name'),
                                ('course', 'degree_program'),
                                ('branch', 'branch_name')):
                if field in request.data:
                    # Course and branch may be a dropdown choice or the custom
                    # name typed against "Other". resolve_custom_option() picks
                    # the right one, comparing without regard to case -- the
                    # payload has already been upper-cased by the time it gets
                    # here, which is exactly what broke this comparison before.
                    if field in ('course', 'branch'):
                        value = upper_text(resolve_custom_option(
                            request.data.get(field),
                            request.data.get(field + '_other'))) or None
                    else:
                        value = upper_text((request.data.get(field) or '').strip()) or None
                    if value != getattr(academic, attr, None):
                        changes.append(f"{attr}: {getattr(academic, attr, None)} -> {value}")
                        setattr(academic, attr, value)
            academic.save()

        if 'department' in request.data:
            name = (request.data.get('department') or '').strip()
            department = Departments.objects.filter(department_name=name).first() if name else None
            if name and department is None:
                return Response({"error": f"Unknown department '{name}'."},
                                status=status.HTTP_400_BAD_REQUEST)
            if department != application.department:
                old_name = getattr(application.department, 'department_name', None)
                changes.append(f"department: {old_name} -> {name or None}")
                application.department = department
                application.save(update_fields=['department'])

        if changes:
            record_application_event(
                application, actor,
                previous_status=old_status,
                new_status=old_status,
                remark='Intake details corrected. ' + '; '.join(changes),
                audit_action='INTAKE_EDITED',
                audit_only=True,
            )

        return Response({"message": "Details updated.",
                         "changes": len(changes)}, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------------
    def _action_schedule(self, request, application, actor, remark, old_status):
        """Allot a joining date and sub-department; move to the Reporting Queue."""
        allotted_doj = request.data.get('allottedDoj')
        sub_department = (request.data.get('subDepartment') or '').strip()

        if not allotted_doj or not sub_department:
            return Response(
                {"error": "Both a date of joining and a sub-department are required "
                          "before a candidate can be told when to report."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            sub_dept_row = SubDepartments.objects.get(
                sub_department_name__iexact=sub_department
            )
        except SubDepartments.DoesNotExist:
            return Response(
                {"error": f"Unknown sub-department '{sub_department}'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        joining, _ = JoiningDetails.objects.get_or_create(application=application)

        # Read BEFORE the assignment below. Decides whether the candidate is
        # being told a reporting date they have not been told before.
        previous_allotted_doj = joining.allotted_date_of_joining

        joining.allotted_date_of_joining = allotted_doj
        joining.allotted_sub_department = sub_dept_row
        joining.save()

        application.status = 'Pending Arrival'
        application.save(update_fields=['status'])

        record_application_event(
            application, actor,
            previous_status=old_status,
            new_status='Pending Arrival',
            remark=remark or f'Reporting date {allotted_doj} allotted to {sub_dept_row.sub_department_name}.',
            audit_action='Pending Arrival',
        )

        # --- THE EMAIL ------------------------------------------------------
        #
        # The joining instructions, with the Student Information Format and the
        # documents checklist attached from portal/static_attachments/. It goes
        # to the CANDIDATE -- a college referral has no employee referrer, and
        # this is the message that tells them where and when to turn up.
        #
        # Only when the date is new or has moved. The whole PATCH endpoint stays
        # reachable while a record sits in the College Referrals section, so
        # this action can be repeated -- correcting a sub-department, say --
        # with the same joining date resent each time. The queue's own duplicate
        # guard does not cover that: it suppresses a second PENDING row, but
        # once the first email is Sent it no longer blocks anything, and the
        # candidate would be re-told their reporting date on every later edit.
        #
        # A date that genuinely MOVES does re-notify, and must: a candidate told
        # the wrong date has to be told the new one.
        #
        # Inside the transaction: this method runs under the @transaction.atomic
        # on patch(), so a rollback takes the queued row with it.
        if date_value_changed(allotted_doj, previous_allotted_doj):
            queue_notification(application, ntypes.COLLEGE_REFERRAL)

        return Response({"message": f"{application.application_code} scheduled."},
                        status=status.HTTP_200_OK)

    # ------------------------------------------------------------------------
    def _action_reject(self, request, application, actor, remark, old_status):
        """Close the record. It leaves this section for the main Rejected list.

        The remark is MANDATORY and is enforced here, on the server, so it holds
        regardless of what the browser does. It is the only account of why a
        candidate was turned away, and it is what the timeline, the audit ledger
        and any future enquiry will rely on.
        """
        if not remark:
            return Response(
                {"error": "A reason is required to reject an application. It is the "
                          "only record of why this candidate was turned away."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 'No Show' when the candidate failed to report; 'Other' otherwise --
        # most often a candidate who never sent their documents. The free-text
        # remark carries the actual explanation either way.
        category = 'No Show' if request.data.get('fromNoShow') else 'Other'

        application.status = 'Rejected'
        application.rejection_category = category
        application.form_correction_remarks = remark
        # There is no referrer to send this back to, so it is final, not parked.
        application.awaiting_referrer_action = 0
        if category == 'No Show':
            application.is_no_show = 1
        application.save()

        record_application_event(
            application, actor,
            previous_status=old_status,
            new_status='Rejected',
            remark=f'Rejected ({category}): {remark}',
            audit_action='Rejected',
        )

        return Response({"message": f"{application.application_code} rejected."},
                        status=status.HTTP_200_OK)

    # ------------------------------------------------------------------------
    def _action_reschedule(self, request, application, actor, remark, old_status):
        """Give a no-show candidate a new joining date. ONCE only.

        A candidate who fails to report gets a single second chance. The limit
        is enforced here rather than in the browser, so it cannot be bypassed,
        and it matches the one-lifeline rule the employee pipeline applies.
        Once spent, rejection is the only remaining option.
        """
        if (application.doj_reschedules_count or 0) >= 1:
            return Response(
                {"error": "This candidate has already been given one rescheduled "
                          "joining date. The only remaining option is to reject "
                          "the application."},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_doj = request.data.get('allottedDoj')
        if not new_doj:
            return Response({"error": "A new date of joining is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        joining, _ = JoiningDetails.objects.get_or_create(application=application)
        previous_doj = joining.allotted_date_of_joining
        joining.allotted_date_of_joining = new_doj
        joining.save()

        application.is_no_show = 1
        application.doj_reschedules_count = (application.doj_reschedules_count or 0) + 1
        # The record stays where it is, now waiting on the new date.
        application.save(update_fields=['is_no_show', 'doj_reschedules_count'])

        record_application_event(
            application, actor,
            previous_status=old_status,
            new_status=old_status,
            remark=(f'Marked no-show. Joining date moved from {previous_doj or "unset"} '
                    f'to {new_doj}.' + (f' {remark}' if remark else '')),
            audit_action='No Show',
        )

        # --- THE EMAIL ------------------------------------------------------
        #
        # A no-show candidate is being given their one second chance, so they
        # have to be told the new date. Same email as the original scheduling,
        # carrying the new reporting date and the same two attachments.
        #
        # date_value_changed() rather than an unconditional call: the endpoint
        # requires allottedDoj, but it does not require it to be DIFFERENT, and
        # resending an identical date would tell the candidate their joining
        # date had moved when it had not.
        if date_value_changed(new_doj, previous_doj):
            queue_notification(application, ntypes.COLLEGE_REFERRAL)

        return Response({
            "message": f"New joining date {new_doj} allotted.",
            "canReschedule": False,
        }, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------------
    def _action_arrive(self, request, application, actor, remark, old_status):
        """The candidate reported. Merge into the main pipeline.

        This is the moment the record stops being a work in progress, so it is
        where completeness is enforced -- the check that replaces the database
        constraints relaxed in migration 01. Nothing incomplete leaves this
        section.

        The date of arrival becomes the ACTUAL date of joining, which is printed
        on the offer letter and the completion certificate and drives the
        projected end date. A candidate never marked as arrived never joined.
        """
        blockers = merge_blockers(application)
        if blockers:
            return Response(
                {"error": "This application is not complete and cannot be merged yet.",
                 "missing": blockers},
                status=status.HTTP_400_BAD_REQUEST
            )

        arrival_date = request.data.get('actualDoj') or timezone.localdate()

        joining, _ = JoiningDetails.objects.get_or_create(application=application)
        joining.actual_date_of_joining = arrival_date
        joining.save()

        application.status = 'Pending Offer Letter'
        application.save(update_fields=['status'])

        record_application_event(
            application, actor,
            previous_status=old_status,
            new_status='Pending Offer Letter',
            remark=(f'Candidate reported on {arrival_date}. Merged into the main '
                    f'pipeline for offer letter issuance.'),
            audit_action='Pending Offer Letter',
        )

        return Response({
            "message": f"{application.application_code} merged into the main pipeline.",
            "actualDoj": str(arrival_date),
        }, status=status.HTTP_200_OK)


class HRDocumentOverrideAPIView(APIView):
    """Replace the live document for one category with an HR-supplied file.

    POST multipart/form-data:
        ticket    -- application_code, e.g. DMRC-2026W-022
        doc_type  -- document_types.type_name, e.g. "Offer Letter"
        file      -- the replacement file

    The uploaded file becomes the single live document for that category and
    is what every role sees everywhere from that moment on. The previous
    version is demoted and quarantined, never served again.
    """

    # Categories HR may override. Anything outside this set is refused so that
    # an unexpected doc_type cannot silently create a new category.
    # Categories HR-APP may override outright. 'Completion Letter' has been
    # removed: it never existed as anything but a name in the catalogue.
    #
    # NOTE: an OFFER LETTER correction does NOT come through here. HR-OPS
    # uploads a corrected letter through OfferLetterCorrectionAPIView, where it
    # waits for HR-APP's approval before becoming official. This endpoint makes
    # a file live immediately, which is the wrong behaviour for that loop.
    OVERRIDABLE = {
        'Offer Letter',
        'Completion Certificate',
        'Annexure B',
        'DMRA Exemption Letter',
    }

    # WHO MAY UPLOAD WHAT is decided per document, below, not by this decorator.
    #
    # Replacing an official LETTER is HR-APP's alone: a SYS-ADMIN administers
    # the system and does not sign documents in an officer's name.
    #
    # But Annexure B and the DMRA exemption letter are CLEARANCE paperwork that
    # HR-OPS collects during the internship -- they are not signed by anybody
    # and are not DMRC's own output. Restricting them to HR-APP locked the one
    # person whose job it is out of doing it, and clearance could never be
    # completed.
    @role_required(*ALL_HR_ROLES)
    @transaction.atomic
    def post(self, request):
        ticket = request.data.get('ticket')
        type_name = request.data.get('doc_type')
        upload = request.FILES.get('file')
        remarks = request.data.get('remark') or 'Manual override by HR.'

        if not ticket or not type_name or not upload:
            return Response(
                {"error": "ticket, doc_type and file are all required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if type_name not in self.OVERRIDABLE:
            return Response(
                {"error": f"'{type_name}' is not an overridable document category."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Official documents are circulated externally, so the format is fixed.
        if not upload.name.lower().endswith('.pdf'):
            return Response(
                {"error": "Official document overrides must be PDF files."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            application = Applications.objects.get(application_code=ticket)
        except Applications.DoesNotExist:
            return Response({"error": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        # Matched WITHOUT regard to case. The catalogue stores 'ANNEXURE B',
        # like every other stored text field, while OVERRIDABLE above and the
        # dashboard both say 'Annexure B'. An exact match therefore never found
        # it, and uploading an Annexure B or a completion certificate failed
        # with "not registered" for a type that was registered all along.
        # Clearance paperwork HR-OPS collects. Everything else is an official
        # document and belongs to HR-APP.
        OPS_UPLOADABLE = {'Annexure B', 'DMRA Exemption Letter'}
        if type_name not in OPS_UPLOADABLE and request.identity.role != 'HR-APP':
            return Response(
                {"error": f"Replacing the {type_name} is an HR-APP action. "
                          f"Your role is {request.identity.role}."},
                status=status.HTTP_403_FORBIDDEN
            )

        doc_type = DocumentTypes.objects.filter(type_name__iexact=type_name).first()
        if doc_type is None:
            return Response(
                {"error": f"Document type '{type_name}' is not registered."},
                status=status.HTTP_400_BAD_REQUEST
            )

        document = supersede_document(
            application, doc_type, upload,
            is_override=True,
            actor=getattr(getattr(request, 'identity', None), 'user', None),
            remarks=remarks
        )

        return Response({
            "message": f"{type_name} overridden for {ticket}.",
            "ticket": ticket,
            "doc_type": type_name,
            "version": document.version,
            "fileName": str(document.file_path).split('/')[-1],
            # A viewer link, not a media path: these files are no longer served
            # by URL. See is_protected_document().
            "url": document_view_url(document),
        }, status=status.HTTP_201_CREATED)


# ==============================================================================
# THE CLEARANCE STAGE
#
# Between an intern joining and receiving their certificate:
#
#   DMRA session scheduled  -> unlocks everything below it
#   mentor's evaluation     -> Satisfactory, or Unsatisfactory and it ends here
#   attendance + report     -> two physical confirmations
#   project report title    -> printed on the certificate
#   Annexure B              -> uploaded
#   DMRA attended, or an exemption letter uploaded
#   file number             -> typed at Submit for Final Review
# ==============================================================================

def parse_date_field(raw):
    """Parse a date from the browser, or None if it is not one.

    Accepts the ISO form an <input type="date"> sends and the DD-MM-YYYY form
    DMRC writes, because both reach this API: the picker sends one and a typed
    correction can send the other. Returning None rather than raising lets the
    caller answer with a sentence naming the offending value.
    """
    if not raw:
        return None
    if hasattr(raw, 'year'):
        return raw
    text = str(raw).strip()
    for pattern in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


CERTIFICATE_TYPE = 'Completion Certificate'
ANNEXURE_B_TYPE = 'Annexure B'
EXEMPTION_LETTER_TYPE = 'DMRA Exemption Letter'


def certificate_type():
    """The Completion Certificate row from the document catalogue, or None."""
    return DocumentTypes.objects.filter(type_name__iexact=CERTIFICATE_TYPE).first()


def clearance_document(application, type_name):
    """The live document of one category, matched by NAME.

    Matched on name rather than on the cycle's requirement snapshot because
    Annexure B and the exemption letter are collected DURING the internship by
    HR, not offered to the applicant, so they are not in that snapshot at all.
    """
    return Documents.objects.filter(
        application=application, is_current=1,
        doc_type__type_name__iexact=type_name,
    ).select_related('doc_type').first()


def clearance_blockers(application):
    """Everything preventing this application from going for final review.

    Returns human-readable labels, the same shape merge_blockers() and
    issue_blockers() use, so the dashboard can say WHY a button is unavailable
    instead of leaving it greyed out with no explanation.

    An UNSATISFACTORY evaluation is a different situation and is not checked
    here: that path rejects the application, and demanding a complete document
    set before somebody can be failed would be pointless paperwork. The one
    thing still required is the evaluation itself and the file number, both
    enforced by the endpoint.
    """
    missing = []

    joining = JoiningDetails.objects.filter(application=application).first()

    if joining is None or not joining.dmra_session_date:
        missing.append('DMRA Academy session date')

    if not application.mentor_evaluation_result:
        missing.append("Mentor's evaluation")

    if not application.attendance_record_verified:
        missing.append('Attendance record confirmation')
    if not application.project_report_verified:
        missing.append('Project report confirmation')
    if not (application.project_report_title or '').strip():
        missing.append('Project report title')

    if clearance_document(application, ANNEXURE_B_TYPE) is None:
        missing.append('Annexure B')

    # Attended, or missed WITH an exemption letter. dmra_attended is NULL until
    # HR answers, which is distinct from answering "no".
    if joining is None or joining.dmra_attended is None:
        missing.append('Whether the candidate attended the DMRA session')
    elif not joining.dmra_attended and clearance_document(application, EXEMPTION_LETTER_TYPE) is None:
        missing.append('DMRA exemption letter (the candidate missed the session)')

    return missing


def certificate_blockers(application, signatory_user):
    """Everything preventing a completion certificate from being issued."""
    missing = []

    if application.status not in ('Pending Certificate',):
        missing.append(
            f"Status is '{application.status}' -- a certificate is issued from "
            f"'Pending Certificate'."
        )

    if application.mentor_evaluation_result == 'Unsatisfactory':
        missing.append(
            'The mentor marked this internship Unsatisfactory. No certificate '
            'is issued; the application must be rejected instead.'
        )

    if not (application.approval_reference_id or '').strip():
        missing.append('File number')
    if not (application.project_report_title or '').strip():
        missing.append('Project report title')

    joining = JoiningDetails.objects.filter(application=application).first()
    if joining is None or not joining.actual_date_of_joining:
        missing.append('Actual date of joining')
    if joining is None or not joining.date_of_completion:
        missing.append('Completion date')
    if joining is None or joining.allotted_sub_department_id is None:
        missing.append('Allotted sub-department')

    student = getattr(application, 'student', None)
    if not getattr(student, 'full_name', None):
        missing.append('Candidate name')

    academic = AcademicDetails.objects.filter(application=application).first()
    if not getattr(academic, 'college_name', None):
        missing.append('College')

    if signatory_user is None or not signatory_user.active_signature_path:
        missing.append(
            'Your approved signature. Upload one and ask a system administrator '
            'to approve it before issuing certificates.'
        )
    elif signature_absolute_path(signatory_user.active_signature_path) is None:
        missing.append('Your signature image is missing from storage. Upload it again.')

    return missing


def build_certificate_context(application, signatory_user, *,
                              issued_on=None, signature_path=None):
    """Assemble everything the certificate builders need, from the database.

    Values pass through EXACTLY as stored -- the portal's convention is upper
    case and the certificate follows it, as the offer letter does.

    The end date is READ from joining_details.date_of_completion, written when
    the offer letter was issued. It is never recalculated here: that is what
    makes the certificate agree with the offer letter rather than merely hoping
    the two arithmetic paths match, and it means a SYS-ADMIN correcting the date
    corrects both documents at once.
    """
    student = getattr(application, 'student', None)
    academic = AcademicDetails.objects.filter(application=application).first()
    joining = JoiningDetails.objects.filter(application=application).first()

    sub_department = getattr(
        getattr(joining, 'allotted_sub_department', None), 'sub_department_name', None)

    employee = getattr(signatory_user, 'employee', None)

    if signature_path is None and signatory_user is not None:
        signature_path = signatory_user.active_signature_path
    signature_file = signature_absolute_path(signature_path)

    return {
        'application_code': application.application_code,
        'issued_on': issued_on or timezone.localdate(),
        'salutation': salutation_for(getattr(student, 'salutation', None),
                                     getattr(student, 'gender', None)),
        'candidate_name': getattr(student, 'full_name', ''),
        'college': getattr(academic, 'college_name', ''),
        'sub_department': sub_department,
        'start_date': getattr(joining, 'actual_date_of_joining', None),
        'end_date': getattr(joining, 'date_of_completion', None),
        'project_title': application.project_report_title or '',
        'gender': getattr(student, 'gender', None),
        'signatory_name': getattr(employee, 'full_name', ''),
        'signatory_designation': getattr(employee, 'designation', ''),
        'signature_path': str(signature_file) if signature_file else None,
    }


def issue_certificate(application, signatory_user, *, actor=None):
    """Generate, sign and store the completion certificate for one application.

    Records the issue date and the exact signature used, then moves the
    application to 'Pending Dispatch'.

    Must be called inside a transaction. Raises ValueError, carrying a message
    fit to show HR, if it may not be issued.
    """
    blockers = certificate_blockers(application, signatory_user)
    if blockers:
        raise ValueError('; '.join(blockers))

    doc_type = certificate_type()
    if doc_type is None:
        raise ValueError(
            "The 'Completion Certificate' document type is missing from the "
            "catalogue. A system administrator must restore it before "
            "certificates can be issued."
        )

    issued_on = timezone.localdate()
    signature_path = signatory_user.active_signature_path

    context = build_certificate_context(
        application, signatory_user,
        issued_on=issued_on, signature_path=signature_path,
    )

    document = store_generated_document(
        application, doc_type,
        build_completion_certificate_pdf(context),
        f"Completion_Certificate_{application.application_code}.pdf",
        actor=actor or signatory_user,
        remarks=f"Generated and signed by {context['signatory_name']}.",
    )

    application.certificate_issued_at = timezone.now()
    application.certificate_signed_by_user = signatory_user
    application.certificate_signature_path = signature_path

    previous_status = application.status
    application.status = 'Pending Dispatch'
    application.save(update_fields=[
        'certificate_issued_at', 'certificate_signed_by_user',
        'certificate_signature_path', 'status',
    ])

    record_application_event(
        application, actor or signatory_user,
        previous_status=previous_status,
        new_status='Pending Dispatch',
        remark=f"Completion certificate issued and signed by {context['signatory_name']}.",
        audit_action='CERTIFICATE_ISSUED',
    )
    return document


class SignatureAPIView(APIView):
    """An HR-APP's signature, and the SYS-ADMIN approval that authorises it.

    GET    -- my own signature state; a SYS-ADMIN also gets the pending queue
    POST   -- HR-APP uploads a new signature (multipart: file)
    PATCH  -- SYS-ADMIN approves or rejects one (userId, decision, reason)

    WHY THIS NEEDS AN APPROVAL AT ALL
    A signature image is the one file in this system whose theft lets somebody
    produce a document DMRC did not issue. Letting an officer swap their own
    without a second person looking would mean anyone who got hold of an HR-APP
    session could substitute a signature and sign letters with it.
    """

    @role_required(*ALL_HR_ROLES)
    def get(self, request):
        identity = request.identity
        payload = {"mine": serialize_signature_state(identity.user)}

        # The approval queue belongs to the SYS-ADMIN: every officer with
        # something waiting, so the decision screen has one source.
        if identity.role == 'SYS-ADMIN':
            waiting = (Users.objects
                       .filter(signature_approval_status='Pending', is_active=True)
                       .select_related('employee', 'role')
                       .order_by('signature_uploaded_at'))
            payload["pending"] = [serialize_signature_state(u) for u in waiting]

        return Response(payload, status=status.HTTP_200_OK)

    # HR-APP ONLY. A SYS-ADMIN cannot hold a signature here, because a
    # SYS-ADMIN cannot issue letters -- see OfferLetterAPIView.
    @role_required('HR-APP')
    @transaction.atomic
    def post(self, request):
        user = request.identity.user
        upload = request.FILES.get('file')

        if upload is None:
            return Response({"error": "A signature image is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        if user.signature_approval_status == 'Pending':
            return Response(
                {"error": "You already have a signature awaiting approval. "
                          "A system administrator must decide on it before you "
                          "can submit another."},
                status=status.HTTP_409_CONFLICT
            )

        try:
            stored = save_signature_upload(user, upload)
        except ValueError as invalid:
            return Response({"error": str(invalid)},
                            status=status.HTTP_400_BAD_REQUEST)

        user.pending_signature_path = stored
        user.signature_approval_status = 'Pending'
        user.signature_uploaded_at = timezone.now()
        user.signature_rejection_reason = None
        user.signature_reviewed_at = None
        user.signature_reviewed_by_user = None
        user.save(update_fields=[
            'pending_signature_path', 'signature_approval_status',
            'signature_uploaded_at', 'signature_rejection_reason',
            'signature_reviewed_at', 'signature_reviewed_by_user',
        ])

        _audit(user, 'SIGNATURE_SUBMITTED', 'User', user.user_id,
               new_value={"file_path": stored})

        return Response({
            "message": "Signature submitted. A system administrator will review it. "
                       "Your current signature stays in use until then.",
            "signature": serialize_signature_state(user),
        }, status=status.HTTP_201_CREATED)

    @role_required('SYS-ADMIN')
    @transaction.atomic
    def patch(self, request):
        actor = request.identity.user
        target_id = request.data.get('userId')
        decision = (request.data.get('decision') or '').strip().lower()
        reason = upper_text(request.data.get('reason', '') or '')

        if not target_id or decision not in ('approve', 'reject'):
            return Response(
                {"error": "userId and decision ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        target = (Users.objects.filter(user_id=target_id)
                  .select_related('employee', 'role').first())
        if target is None:
            return Response({"error": "User not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if target.signature_approval_status != 'Pending' or not target.pending_signature_path:
            return Response(
                {"error": "That officer has no signature awaiting approval."},
                status=status.HTTP_409_CONFLICT
            )

        # A refusal MUST carry a reason: it is the only thing telling the
        # officer what to fix, exactly as a correction request does.
        if decision == 'reject' and not reason.strip():
            return Response(
                {"error": "A reason is required when rejecting a signature. "
                          "It is the only explanation the officer receives."},
                status=status.HTTP_400_BAD_REQUEST
            )

        now = timezone.now()

        if decision == 'approve':
            # The signature being REPLACED is quarantined, not deleted. Letters
            # already issued keep pointing at their own frozen copy, so the file
            # must survive somewhere reachable by the generator... but nothing
            # reprints from the active path, so quarantining is safe and keeps
            # the active folder to exactly one file per officer.
            replaced = target.active_signature_path
            quarantined_to = _quarantine_signature(replaced) if replaced else None

            pending_path = Path(settings.SIGNATURE_ROOT) / str(target.pending_signature_path)
            active_relative = f"{SIGNATURE_ACTIVE}/{target.user_id}{pending_path.suffix}"
            active_absolute = Path(settings.SIGNATURE_ROOT) / active_relative
            active_absolute.parent.mkdir(parents=True, exist_ok=True)
            if active_absolute.exists():
                active_absolute.unlink()
            shutil.move(str(pending_path), str(active_absolute))

            target.active_signature_path = active_relative
            target.pending_signature_path = None
            target.signature_approval_status = 'Approved'
            target.signature_activated_at = now
            target.signature_rejection_reason = None
            message = f"Signature approved for {getattr(target.employee, 'full_name', 'the officer')}."
            audit_action = 'SIGNATURE_APPROVED'
            audit_detail = {"active_path": active_relative,
                            "replaced": replaced,
                            "quarantined_to": quarantined_to}
        else:
            quarantined_to = _quarantine_signature(target.pending_signature_path)
            target.pending_signature_path = None
            target.signature_approval_status = 'Rejected'
            target.signature_rejection_reason = reason
            message = f"Signature returned to {getattr(target.employee, 'full_name', 'the officer')}."
            audit_action = 'SIGNATURE_REJECTED'
            audit_detail = {"reason": reason, "quarantined_to": quarantined_to}

        target.signature_reviewed_at = now
        target.signature_reviewed_by_user = actor
        target.save(update_fields=[
            'active_signature_path', 'pending_signature_path',
            'signature_approval_status', 'signature_activated_at',
            'signature_rejection_reason', 'signature_reviewed_at',
            'signature_reviewed_by_user',
        ])

        _audit(actor, audit_action, 'User', target.user_id, new_value=audit_detail)

        return Response({"message": message,
                         "signature": serialize_signature_state(target)},
                        status=status.HTTP_200_OK)


class SignatureImageView(APIView):
    """Stream one signature image, to the two people entitled to see it.

    GET /api/signatures/image/?t=<signed token>

    Signature files are never served from a directory Django exposes. This is
    the only way to see one, and it is limited to:

      * the officer the signature belongs to, and
      * a SYS-ADMIN, who must see it to decide on it.

    Every access by anyone other than the owner is written to the ledger, for
    the same reason document views are.
    """

    CONTENT_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}

    @role_required(*ALL_HR_ROLES)
    def get(self, request):
        token = request.query_params.get('t')
        if not token:
            return Response({"error": "A signature link is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = _signature_signer.unsign(
                token, max_age=getattr(settings, 'DOCUMENT_LINK_TTL_SECONDS', 600))
        except SignatureExpired:
            return Response({"error": "This link has expired. Reload the page."},
                            status=status.HTTP_403_FORBIDDEN)
        except BadSignature:
            return Response({"error": "Invalid signature link."},
                            status=status.HTTP_403_FORBIDDEN)

        try:
            user_id, kind = str(payload).split(':', 1)
        except ValueError:
            return Response({"error": "Invalid signature link."},
                            status=status.HTTP_403_FORBIDDEN)

        identity = request.identity
        owner = Users.objects.filter(user_id=int(user_id)).select_related('employee').first()
        if owner is None:
            raise Http404("Signature not found.")

        is_owner = identity.user is not None and identity.user.user_id == owner.user_id
        if not (is_owner or identity.role == 'SYS-ADMIN'):
            return Response(
                {"error": "A signature may only be viewed by the officer it "
                          "belongs to, or by a system administrator."},
                status=status.HTTP_403_FORBIDDEN
            )

        relative = (owner.active_signature_path if kind == SIGNATURE_ACTIVE
                    else owner.pending_signature_path)
        path = signature_absolute_path(relative)
        if path is None:
            raise Http404("The stored signature file is missing.")

        if not is_owner:
            _audit(identity.user, 'SIGNATURE_VIEWED', 'User', owner.user_id,
                   new_value={"kind": kind,
                              "officer": getattr(owner.employee, 'full_name', None),
                              "viewedBy": identity.employee_code})

        response = FileResponse(
            open(path, 'rb'),
            content_type=self.CONTENT_TYPES.get(path.suffix.lower(), 'application/octet-stream'))
        response['Content-Disposition'] = 'inline'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        return response


class OfferLetterAPIView(APIView):
    """Issue offer letters, and hand back the files HR-OPS needs.

    GET  ?ticket=...&variant=pdf|docx   download the letter
    POST {tickets: [...]}               sign and issue, one or many

    The download parameter is 'variant', NOT 'format'. Django REST Framework
    reserves ?format= for its own content negotiation: it would look for a
    renderer called "pdf", fail to find one, and raise a 404 before this method
    ever ran. The error it produces -- {"detail": "Not found."} -- looks exactly
    like a missing application, which makes it a genuinely nasty thing to
    diagnose. Do not rename this back.

    WHY HR-APP ONLY
    A SYS-ADMIN administers the portal. They do not sign official documents in
    an officer's name, and they hold no signature to sign with. If the only
    HR-APP is unavailable, DMRC appoints another -- which is an administrative
    act with a record, rather than an administrator quietly signing for someone.
    """

    @role_required(*ALL_HR_ROLES)
    def get(self, request):
        ticket = request.query_params.get('ticket')
        wanted = (request.query_params.get('variant') or 'pdf').strip().lower()

        if not ticket:
            return Response({"error": "A ticket is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if wanted not in ('pdf', 'docx'):
            return Response({"error": "variant must be 'pdf' or 'docx'."},
                            status=status.HTTP_400_BAD_REQUEST)

        application = (Applications.objects
                       .filter(application_code=ticket)
                       .select_related('student', 'cycle').first())
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if not application.offer_letter_issued_at:
            return Response(
                {"error": "No offer letter has been issued for this application yet."},
                status=status.HTTP_409_CONFLICT
            )

        signatory = application.offer_letter_signed_by_user

        # --- PDF: the stored, signed file ------------------------------------
        # Served from disk rather than regenerated, so what HR-OPS prints is
        # byte-for-byte what HR-APP signed -- including a corrected version that
        # HR-APP has since approved.
        if wanted == 'pdf':
            doc_type = offer_letter_type()
            document = current_document(application, doc_type) if doc_type else None
            path = stored_document_path(document) if document else None
            if path is None:
                return Response(
                    {"error": "The stored offer letter file is missing. "
                              "Re-issue the letter to produce it again."},
                    status=status.HTTP_404_NOT_FOUND
                )

            _audit(request.identity.user, 'OFFER_LETTER_DOWNLOADED', 'Document',
                   document.document_id,
                   new_value={"application": ticket, "format": "pdf",
                              "downloadedBy": request.identity.employee_code})

            # Inline: opened in a browser tab, saved from there if wanted.
            # The Word branch below stays a download -- a browser cannot
            # display a .docx, so 'inline' would only produce a confusing
            # save dialog.
            response = FileResponse(open(path, 'rb'), content_type='application/pdf')
            response['Content-Disposition'] = (
                f'inline; filename="Offer_Letter_{ticket}.pdf"')
            return response

        # --- Word: built on demand, and NEVER signed --------------------------
        # A signature inside a downloadable Word file can be lifted in three
        # clicks and pasted onto anything, and this file is downloaded as a
        # matter of routine. The corrected PDF gets its signature when HR-APP
        # approves it, not before.
        context = build_offer_letter_context(
            application, signatory,
            issued_on=(timezone.localtime(application.offer_letter_issued_at).date()
                       if application.offer_letter_issued_at else None),
            signature_path=None,
        )
        context['signature_path'] = None

        _audit(request.identity.user, 'OFFER_LETTER_DOWNLOADED', 'Application',
               application.application_id,
               new_value={"application": ticket, "format": "docx",
                          "downloadedBy": request.identity.employee_code})

        response = HttpResponse(
            build_offer_letter_docx(context),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = (
            f'attachment; filename="Offer_Letter_{ticket}.docx"')
        return response

    @role_required('HR-APP')
    def post(self, request):
        tickets = request.data.get('tickets')
        if not tickets:
            single = request.data.get('ticket')
            tickets = [single] if single else []
        if isinstance(tickets, str):
            tickets = [tickets]

        if not tickets:
            return Response({"error": "At least one ticket is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        signatory = request.identity.user
        issued, failed = [], []

        # PER-APPLICATION transactions, not one around the batch. Bulk issuing
        # is meant to get twenty letters out; one candidate with a missing
        # sub-department should not silently undo the other nineteen. Each
        # failure is reported with its reason, and HR-OPS corrects it afterwards
        # through the ordinary correction loop.
        for ticket in tickets:
            try:
                with transaction.atomic():
                    application = (Applications.objects
                                   .select_for_update()
                                   .select_related('student', 'cycle')
                                   .get(application_code=ticket))
                    issue_offer_letter(application, signatory, actor=signatory)
                    issued.append(ticket)
            except Applications.DoesNotExist:
                failed.append({"ticket": ticket, "reason": "Application not found."})
            except ValueError as blocked:
                failed.append({"ticket": ticket, "reason": str(blocked)})
            except Exception as unexpected:
                logger.error("OFFER LETTER FAILED (%s): %s",
                             type(unexpected).__name__, unexpected)
                failed.append({"ticket": ticket, "reason": str(unexpected)})

        if issued and not failed:
            message = (f"Offer letter issued for {issued[0]}." if len(issued) == 1
                       else f"{len(issued)} offer letters issued.")
        elif issued and failed:
            message = (f"{len(issued)} issued, {len(failed)} could not be. "
                       f"Those are listed below and can be issued once corrected.")
        else:
            message = "No offer letters could be issued."

        return Response(
            {"message": message, "issued": issued, "failed": failed},
            status=status.HTTP_200_OK if issued else status.HTTP_400_BAD_REQUEST
        )


class OfferLetterCorrectionAPIView(APIView):
    """The correction loop for an issued offer letter.

    POST   HR-OPS uploads a corrected PDF (multipart: ticket, file, remark)
    PATCH  HR-APP approves it or returns it (ticket, decision, reason)

    An upload does NOT become the official letter. It waits, visible to HR-APP,
    until they have looked at it and approved it. Rejection sends it back with a
    mandatory reason and the file is quarantined.

    The loop may run as many times as needed. Whatever HR-APP last approved is
    the official letter.
    """

    @role_required('HR-OPS', 'SYS-ADMIN')
    @transaction.atomic
    def post(self, request):
        ticket = request.data.get('ticket')
        upload = request.FILES.get('file')
        remark = upper_text(request.data.get('remark', '') or '')

        if not ticket or upload is None:
            return Response({"error": "A ticket and a file are both required."},
                            status=status.HTTP_400_BAD_REQUEST)

        if not upload.name.lower().endswith('.pdf'):
            return Response(
                {"error": "A corrected offer letter must be a PDF. Make your "
                          "changes in the Word copy, export it as PDF, and "
                          "upload that."},
                status=status.HTTP_400_BAD_REQUEST
            )

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if not application.offer_letter_issued_at:
            return Response(
                {"error": "No offer letter has been issued for this application, "
                          "so there is nothing to correct."},
                status=status.HTTP_409_CONFLICT
            )

        doc_type = offer_letter_type()
        if doc_type is None:
            return Response(
                {"error": "The 'Offer Letter' document type is missing from the catalogue."},
                status=status.HTTP_400_BAD_REQUEST
            )

        actor = request.identity.user
        try:
            document = stage_document_for_approval(
                application, doc_type, upload, actor=actor,
                remarks=remark or 'Corrected offer letter uploaded by HR-OPS.',
            )
        except ValueError as conflict:
            return Response({"error": str(conflict)}, status=status.HTTP_409_CONFLICT)

        previous_status = application.status
        application.status = 'Pending Offer Re-Approval'
        application.save(update_fields=['status'])

        record_application_event(
            application, actor,
            previous_status=previous_status,
            new_status='Pending Offer Re-Approval',
            remark=remark or 'Corrected offer letter sent for re-approval.',
            audit_action='OFFER_LETTER_CORRECTION_SUBMITTED',
        )

        return Response({
            "message": f"Corrected offer letter sent for approval. It will not "
                       f"replace the current letter until an HR-APP officer approves it.",
            "ticket": ticket,
            "fileName": str(document.file_path).split('/')[-1],
            "viewUrl": document_view_url(document),
        }, status=status.HTTP_201_CREATED)

    @role_required('HR-APP')
    @transaction.atomic
    def patch(self, request):
        ticket = request.data.get('ticket')
        decision = (request.data.get('decision') or '').strip().lower()
        reason = upper_text(request.data.get('reason', '') or '')

        if not ticket or decision not in ('approve', 'reject'):
            return Response(
                {"error": "ticket and decision ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        doc_type = offer_letter_type()
        document = pending_document(application, doc_type) if doc_type else None
        if document is None:
            return Response(
                {"error": "There is no corrected offer letter awaiting approval "
                          "for this application."},
                status=status.HTTP_409_CONFLICT
            )

        actor = request.identity.user
        previous_status = application.status

        if decision == 'approve':
            # THE SIGNATURE IS APPLIED HERE, and only here.
            #
            # HR-OPS corrects the Word copy, which carries no signature by
            # design, and uploads the PDF they exported from it. That file is
            # unsigned. Approving it is what signs it -- so the approver's own
            # active signature is stamped onto the stored file before it becomes
            # official, rather than the letter going out with an empty space
            # above the printed name.
            stored = stored_document_path(document)
            signature_file = signature_absolute_path(actor.active_signature_path)
            placed_precisely = True

            if stored is not None and signature_file is not None:
                try:
                    with open(stored, 'rb') as handle:
                        original = handle.read()
                    signed, placed_precisely, failure = stamp_signature(
                        original, str(signature_file),
                        getattr(getattr(actor, 'employee', None), 'full_name', ''),
                    )
                except Exception as stamping_error:
                    logger.error("SIGNATURE STAMPING FAILED (%s): %s",
                                 type(stamping_error).__name__, stamping_error)
                    signed, placed_precisely = None, False
                    failure = str(stamping_error)

                # REFUSE rather than store an unsigned letter as the signed one.
                #
                # Approving IS signing. If the signature could not be applied,
                # completing the approval would produce an official letter with
                # an empty space above the printed name and nothing anywhere
                # recording that it happened -- which is exactly how this went
                # unnoticed before. The transaction rolls back, so the letter
                # stays in the approval queue and can be approved again once the
                # cause named below is dealt with.
                if failure:
                    return Response(
                        {"error": f"The letter could not be signed, so it has not "
                                  f"been approved: {failure}."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE
                    )

                with open(stored, 'wb') as handle:
                    handle.write(signed)
            elif stored is None:
                return Response(
                    {"error": "The uploaded letter is missing from storage, so it "
                              "cannot be signed. Ask HR-OPS to upload it again."},
                    status=status.HTTP_409_CONFLICT
                )
            elif signature_file is None:
                return Response(
                    {"error": "You have no approved signature on file, so this "
                              "letter cannot be signed. Upload one and have a "
                              "system administrator approve it first."},
                    status=status.HTTP_409_CONFLICT
                )

            approve_pending_document(document, actor)
            application.status = 'Offer Ready'
            # The signer of record becomes whoever approved the corrected
            # letter: it is their approval the document now carries.
            application.offer_letter_signed_by_user = actor
            application.offer_letter_signature_path = actor.active_signature_path
            # The objection has been met, so the red box must not follow the
            # application forward describing a problem that no longer exists.
            application.form_correction_remarks = None
            application.save(update_fields=[
                'status', 'offer_letter_signed_by_user', 'offer_letter_signature_path',
                'form_correction_remarks'])

            record_application_event(
                application, actor,
                previous_status=previous_status, new_status='Offer Ready',
                remark=reason or 'Corrected offer letter approved.',
                audit_action='OFFER_LETTER_CORRECTION_APPROVED',
            )
            message = (f"Corrected offer letter approved for {ticket}. "
                       f"It is now the official letter, signed with your signature.")
            if not placed_precisely:
                # Said plainly rather than hidden. The signature block could not
                # be located in the uploaded file, so the signature was placed
                # where the generated letter puts it -- which may not be where
                # this one's block ended up.
                message += ("\n\nNOTE: the signature block could not be located "
                            "in the uploaded PDF, so the signature was placed at "
                            "the standard position. Open the letter and check it "
                            "before it is printed.")
            return Response({"message": message}, status=status.HTTP_200_OK)

        if not reason.strip():
            return Response(
                {"error": "A remark is required when returning a corrected letter. "
                          "It is the only explanation HR-OPS receives, so state "
                          "clearly what is wrong with it."},
                status=status.HTTP_400_BAD_REQUEST
            )

        reject_pending_document(document, actor, reason)
        application.status = 'Offer Ready'
        # The reason also goes on the APPLICATION, not only on the document row.
        # It is stored on the document for the audit trail, but the drawer's red
        # correction box reads form_correction_remarks -- so without this the
        # letter came back to HR-OPS with no visible explanation of what to fix.
        application.form_correction_remarks = reason
        application.save(update_fields=['status', 'form_correction_remarks'])

        record_application_event(
            application, actor,
            previous_status=previous_status, new_status='Offer Ready',
            remark=f"Corrected offer letter returned: {reason}",
            audit_action='OFFER_LETTER_CORRECTION_REJECTED',
        )
        return Response(
            {"message": f"Corrected letter returned to HR-OPS for {ticket}."},
            status=status.HTTP_200_OK
        )


class OfferHandoverAPIView(APIView):
    """Record that the signed offer letter was handed to the intern.

    POST {ticket, undertaking: true, attendance: true}

    Both declarations are physical documents collected on the intern's first
    day. Nothing is uploaded, so the tick IS the record -- which is exactly why
    it has to be stored and stamped here rather than left in the browser, where
    it vanished on the next page load.

    Completing the handover is what moves the intern to 'Joined'.
    """

    @role_required('HR-OPS', 'SYS-ADMIN')
    @transaction.atomic
    def post(self, request):
        ticket = request.data.get('ticket')
        undertaking = bool(request.data.get('undertaking'))
        attendance = bool(request.data.get('attendance'))

        if not ticket:
            return Response({"error": "A ticket is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if application.status != 'Offer Ready':
            return Response(
                {"error": f"Handover is recorded from 'Offer Ready'. This "
                          f"application is '{application.status}'."},
                status=status.HTTP_409_CONFLICT
            )

        # A pending correction means the letter in HR-OPS's hands may not be
        # the one that ends up official. Handing it over now would put a
        # superseded letter in the intern's hands.
        doc_type = offer_letter_type()
        if doc_type is not None and pending_document(application, doc_type) is not None:
            return Response(
                {"error": "A corrected offer letter is still awaiting approval. "
                          "Handover cannot be recorded until it is approved or returned."},
                status=status.HTTP_409_CONFLICT
            )

        if not (undertaking and attendance):
            missing = []
            if not undertaking:
                missing.append('hard copy of the undertaking')
            if not attendance:
                missing.append('hard copy of the attendance record')
            return Response(
                {"error": "Both declarations must be confirmed before the intern "
                          "can be marked as joined. Still outstanding: "
                          + ' and '.join(missing) + "."},
                status=status.HTTP_400_BAD_REQUEST
            )

        actor = request.identity.user
        previous_status = application.status

        application.hardcopy_undertaking_received = 1
        application.hardcopy_attendance_received = 1
        application.handover_completed_at = timezone.now()
        application.status = 'Joined'
        application.save(update_fields=[
            'hardcopy_undertaking_received', 'hardcopy_attendance_received',
            'handover_completed_at', 'status',
        ])

        record_application_event(
            application, actor,
            previous_status=previous_status, new_status='Joined',
            remark='Offer letter handed over. Undertaking and attendance record collected.',
            audit_action='OFFER_LETTER_HANDED_OVER',
        )

        return Response({"message": f"{ticket} marked as joined."},
                        status=status.HTTP_200_OK)


class DMRASessionAPIView(APIView):
    """Schedule the DMRC Academy session for a joined intern.

    POST {ticket, sessionDate}

    SET ONCE. The date is locked the moment it is saved, because it is what the
    candidate is told to turn up on -- an auto-generated email goes out carrying
    it, and a date that can be quietly changed afterwards is a date the
    candidate and the portal can disagree about.

    There is no separate 'locked' flag: the date being present IS the lock. A
    second column tracking lockedness could fall out of step with the date
    itself, and then there would be two answers to one question.

    Only a SYS-ADMIN can change it once set, and that goes through Admin Mode,
    not here. The audit ledger records the override; the old value is not kept,
    which is what DMRC asked for.
    """

    @role_required('HR-OPS', 'SYS-ADMIN')
    @transaction.atomic
    def post(self, request):
        ticket = request.data.get('ticket')
        raw_date = (request.data.get('sessionDate') or '').strip()

        if not ticket or not raw_date:
            return Response({"error": "A ticket and a session date are both required."},
                            status=status.HTTP_400_BAD_REQUEST)

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if application.status != 'Joined':
            return Response(
                {"error": f"A DMRA session is scheduled once the intern has joined. "
                          f"This application is '{application.status}'."},
                status=status.HTTP_409_CONFLICT
            )

        session_date = parse_date_field(raw_date)
        if session_date is None:
            return Response({"error": f"'{raw_date}' is not a valid date."},
                            status=status.HTTP_400_BAD_REQUEST)

        joining, _ = JoiningDetails.objects.get_or_create(application=application)

        # Refused here, on the server. A disabled field in the browser is a
        # suggestion; this is the guarantee, and it is what holds when somebody
        # reaches the API directly.
        if joining.dmra_session_date:
            return Response(
                {"error": f"The DMRA session for this intern is already set to "
                          f"{joining.dmra_session_date.strftime('%d-%m-%Y')} and "
                          f"cannot be changed. A system administrator can correct "
                          f"it from Admin Mode if it is genuinely wrong."},
                status=status.HTTP_409_CONFLICT
            )

        joining.dmra_session_date = session_date
        joining.save(update_fields=['dmra_session_date'])

        actor = request.identity.user
        record_application_event(
            application, actor,
            previous_status=application.status,
            new_status=application.status,
            remark=f"DMRA Academy session scheduled for {session_date.strftime('%d-%m-%Y')}.",
            audit_action='DMRA_SESSION_SCHEDULED',
        )
        
        # --- THE EMAIL ------------------------------------------------------
        #
        # The candidate is summoned to the Academy on this date, so the email
        # is queued the moment the date is set -- exactly as this class's
        # docstring has always said it would be.
        #
        # No duplicate guard needed here beyond the queue's own: the 409 above
        # refuses a second POST once dmra_session_date is present, so this line
        # can be reached only once per application through this endpoint. A
        # SYS-ADMIN correcting a locked date goes through Admin Mode instead,
        # which is HRApplicationActionAPIView -- and that path re-notifies only
        # when the date genuinely moves. A candidate told the wrong date must be
        # told the new one.
        #
        # Inside the transaction: this method is @transaction.atomic, so a
        # rollback takes the queued row with it and nobody is summoned to a
        # session that was not scheduled.
        queue_notification(application, ntypes.ACADEMY_SCHEDULE)

        return Response({
            "message": f"DMRA session set to {session_date.strftime('%d-%m-%Y')}. "
                       f"This date is now locked.",
            "sessionDate": session_date.strftime('%d-%m-%Y'),
        }, status=status.HTTP_200_OK)


class ClearanceAPIView(APIView):
    """The clearance checklist, and the decision at the end of it.

    PATCH  save progress (evaluation, tick-boxes, project title, attendance)
    POST   {ticket, fileNumber, decision}  submit for review, or reject

    WHY SAVING AND SUBMITTING ARE SEPARATE
    Clearance is collected over days, not in one sitting: the evaluation arrives
    from a mentor, Annexure B is chased, the project report is read. PATCH lets
    HR-OPS record each piece as it arrives. POST is the one-way door.
    """

    @role_required('HR-OPS', 'SYS-ADMIN')
    @transaction.atomic
    def patch(self, request):
        ticket = request.data.get('ticket')
        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if application.status not in ('Joined', 'Fix Clearance'):
            return Response(
                {"error": f"Clearance is recorded while the intern is active or "
                          f"has been returned for correction. This application "
                          f"is '{application.status}'."},
                status=status.HTTP_409_CONFLICT
            )

        joining, _ = JoiningDetails.objects.get_or_create(application=application)

        # Nothing below the session date is collectable until it is set: the
        # session is the first thing that happens, and the dashboard hides these
        # sections until then.
        if not joining.dmra_session_date:
            return Response(
                {"error": "Schedule the DMRA Academy session before recording "
                          "anything else. Everything below it follows from that date."},
                status=status.HTTP_409_CONFLICT
            )

        changed = []

        if 'evaluationResult' in request.data:
            result = (request.data.get('evaluationResult') or '').strip().title()
            if result and result not in ('Satisfactory', 'Unsatisfactory'):
                return Response(
                    {"error": "The evaluation must be 'Satisfactory' or 'Unsatisfactory'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            application.mentor_evaluation_result = result or None
            changed.append('mentor_evaluation_result')

        if 'evaluationRemarks' in request.data:
            application.mentor_evaluation_remarks = upper_text(
                (request.data.get('evaluationRemarks') or '').strip()) or None
            changed.append('mentor_evaluation_remarks')

        if 'attendanceVerified' in request.data:
            application.attendance_record_verified = 1 if request.data.get('attendanceVerified') else 0
            changed.append('attendance_record_verified')

        if 'reportVerified' in request.data:
            application.project_report_verified = 1 if request.data.get('reportVerified') else 0
            changed.append('project_report_verified')

        if 'projectTitle' in request.data:
            application.project_report_title = upper_text(
                (request.data.get('projectTitle') or '').strip()) or None
            changed.append('project_report_title')

        if changed:
            application.save(update_fields=changed)

        # Attended / missed. Stored as NULL until answered, which is a different
        # thing from answering "no" -- the blocker list distinguishes the two.
        if 'dmraAttended' in request.data:
            answer = request.data.get('dmraAttended')
            joining.dmra_attended = None if answer is None else (1 if answer else 0)
            joining.save(update_fields=['dmra_attended'])

        return Response({
            "message": "Clearance details saved.",
            "blockers": clearance_blockers(application),
        }, status=status.HTTP_200_OK)

    @role_required('HR-OPS', 'SYS-ADMIN')
    @transaction.atomic
    def post(self, request):
        ticket = request.data.get('ticket')
        file_number = upper_text((request.data.get('fileNumber') or '').strip())
        decision = (request.data.get('decision') or 'submit').strip().lower()

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if application.status not in ('Joined', 'Fix Clearance'):
            return Response(
                {"error": f"This application is '{application.status}' and is not "
                          f"awaiting clearance."},
                status=status.HTTP_409_CONFLICT
            )

        if not application.mentor_evaluation_result:
            return Response(
                {"error": "Record the mentor's evaluation before submitting or "
                          "rejecting."},
                status=status.HTTP_409_CONFLICT
            )

        # The file number is required either way -- including a rejection, which
        # is itself an official act against a physical approval.
        #
        # Kept on a RESUBMISSION after HR-APP returned the application: it is
        # the same approval, so re-typing it would only be a chance to mistype
        # it. Sent again, it is accepted; omitted, the stored one stands.
        if file_number:
            application.approval_reference_id = file_number
        elif not (application.approval_reference_id or '').strip():
            return Response(
                {"error": "A file number is required. It is the reference for the "
                          "physical approval covering this clearance."},
                status=status.HTTP_400_BAD_REQUEST
            )

        actor = request.identity.user
        previous_status = application.status
        unsatisfactory = application.mentor_evaluation_result == 'Unsatisfactory'

        # --- REJECTION ------------------------------------------------------
        # An Unsatisfactory internship produces no certificate. Whatever
        # documents and details HR-OPS managed to collect are kept: they were
        # optional for this path, but they are the record of an internship that
        # was actually served.
        if decision == 'reject' or unsatisfactory:
            if not unsatisfactory:
                return Response(
                    {"error": "An application can only be rejected here when the "
                              "mentor's evaluation is Unsatisfactory."},
                    status=status.HTTP_409_CONFLICT
                )

            application.status = 'Rejected'
            application.rejection_category = 'Unsatisfactory Evaluation'
            application.awaiting_referrer_action = False
            application.clearance_submitted_at = timezone.now()
            application.save(update_fields=[
                'status', 'rejection_category', 'awaiting_referrer_action',
                'approval_reference_id', 'clearance_submitted_at',
            ])

            remark = (application.mentor_evaluation_remarks
                      or 'Internship assessed as Unsatisfactory.')
            record_application_event(
                application, actor,
                previous_status=previous_status, new_status='Rejected',
                remark=f"Rejected on an Unsatisfactory evaluation. {remark}",
                audit_action='CLEARANCE_REJECTED',
            )
            return Response(
                {"message": f"{ticket} rejected on an Unsatisfactory evaluation. "
                            f"No completion certificate is issued."},
                status=status.HTTP_200_OK
            )

        # --- SUBMIT FOR FINAL REVIEW ----------------------------------------
        blockers = clearance_blockers(application)
        if blockers:
            return Response(
                {"error": "Clearance is incomplete: " + '; '.join(blockers) + ".",
                 "blockers": blockers},
                status=status.HTTP_400_BAD_REQUEST
            )

        application.status = 'Pending Certificate'
        application.clearance_submitted_at = timezone.now()
        # The objection, if this is a resubmission, has been answered.
        application.form_correction_remarks = None
        application.save(update_fields=[
            'status', 'clearance_submitted_at', 'approval_reference_id',
            'form_correction_remarks',
        ])

        record_application_event(
            application, actor,
            previous_status=previous_status, new_status='Pending Certificate',
            remark=f"Clearance submitted for final review under file "
                   f"{application.approval_reference_id}.",
            audit_action='CLEARANCE_SUBMITTED',
        )
        return Response(
            {"message": f"{ticket} sent for final review."},
            status=status.HTTP_200_OK
        )


class CertificateAPIView(APIView):
    """Issue the completion certificate, and hand back the files.

    GET  ?ticket=...&variant=pdf|docx   view the certificate, or edit the Word copy
    POST {tickets: [...]}               issue, one or many
    PATCH {ticket, decision, reason}    return to HR-OPS for clearance corrections

    HR-APP ONLY, like the offer letter: a SYS-ADMIN administers the portal and
    holds no signature to sign with.

    The 'variant' parameter is NOT called 'format'. Django REST Framework
    reserves ?format= for content negotiation and would raise a 404 that looks
    exactly like a missing application. See OfferLetterAPIView.
    """

    @role_required(*ALL_HR_ROLES)
    def get(self, request):
        ticket = request.query_params.get('ticket')
        wanted = (request.query_params.get('variant') or 'pdf').strip().lower()

        if not ticket:
            return Response({"error": "A ticket is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if wanted not in ('pdf', 'docx'):
            return Response({"error": "variant must be 'pdf' or 'docx'."},
                            status=status.HTTP_400_BAD_REQUEST)

        application = (Applications.objects.filter(application_code=ticket)
                       .select_related('student', 'cycle').first())
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if not application.certificate_issued_at:
            return Response(
                {"error": "No completion certificate has been issued for this "
                          "application yet."},
                status=status.HTTP_409_CONFLICT
            )

        signatory = application.certificate_signed_by_user

        # --- PDF: the stored, signed file ------------------------------------
        # Served from disk rather than regenerated, so what is read is
        # byte-for-byte what was signed -- including a correction since approved.
        if wanted == 'pdf':
            doc_type = certificate_type()
            document = current_document(application, doc_type) if doc_type else None
            path = stored_document_path(document) if document else None
            if path is None:
                return Response(
                    {"error": "The stored certificate file is missing. Re-issue "
                              "the certificate to produce it again."},
                    status=status.HTTP_404_NOT_FOUND
                )

            _audit(request.identity.user, 'CERTIFICATE_VIEWED', 'Document',
                   document.document_id,
                   new_value={"application": ticket, "variant": "pdf",
                              "viewedBy": request.identity.employee_code})

            response = FileResponse(open(path, 'rb'), content_type='application/pdf')
            response['Content-Disposition'] = (
                f'inline; filename="Completion_Certificate_{ticket}.pdf"')
            return response

        # --- Word: built on demand, and NEVER signed --------------------------
        context = build_certificate_context(
            application, signatory,
            issued_on=(timezone.localtime(application.certificate_issued_at).date()
                       if application.certificate_issued_at else None),
            signature_path=None,
        )
        context['signature_path'] = None

        _audit(request.identity.user, 'CERTIFICATE_VIEWED', 'Application',
               application.application_id,
               new_value={"application": ticket, "variant": "docx",
                          "viewedBy": request.identity.employee_code})

        response = HttpResponse(
            build_completion_certificate_docx(context),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = (
            f'attachment; filename="Completion_Certificate_{ticket}.docx"')
        return response

    @role_required('HR-APP')
    def post(self, request):
        tickets = request.data.get('tickets')
        if not tickets:
            single = request.data.get('ticket')
            tickets = [single] if single else []
        if isinstance(tickets, str):
            tickets = [tickets]

        if not tickets:
            return Response({"error": "At least one ticket is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        signatory = request.identity.user
        issued, failed = [], []

        # Per-application transactions, as with offer letters: one incomplete
        # clearance must not silently undo the rest of the batch.
        for ticket in tickets:
            try:
                with transaction.atomic():
                    application = (Applications.objects.select_for_update()
                                   .select_related('student', 'cycle')
                                   .get(application_code=ticket))
                    issue_certificate(application, signatory, actor=signatory)
                    issued.append(ticket)
            except Applications.DoesNotExist:
                failed.append({"ticket": ticket, "reason": "Application not found."})
            except ValueError as blocked:
                failed.append({"ticket": ticket, "reason": str(blocked)})
            except Exception as unexpected:
                logger.error("CERTIFICATE FAILED (%s): %s",
                             type(unexpected).__name__, unexpected)
                failed.append({"ticket": ticket, "reason": str(unexpected)})

        if issued and not failed:
            message = (f"Completion certificate issued for {issued[0]}." if len(issued) == 1
                       else f"{len(issued)} completion certificates issued.")
        elif issued and failed:
            message = (f"{len(issued)} issued, {len(failed)} could not be. "
                       f"Those are listed below.")
        else:
            message = "No certificates could be issued."

        return Response({"message": message, "issued": issued, "failed": failed},
                        status=status.HTTP_200_OK if issued else status.HTTP_400_BAD_REQUEST)

    @role_required('HR-APP')
    @transaction.atomic
    def patch(self, request):
        """Return the application to HR-OPS for clearance corrections."""
        ticket = request.data.get('ticket')
        reason = upper_text((request.data.get('reason') or '').strip())

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if application.status != 'Pending Certificate':
            return Response(
                {"error": f"Only an application awaiting certification can be "
                          f"returned. This one is '{application.status}'."},
                status=status.HTTP_409_CONFLICT
            )

        # The reason is the only thing telling HR-OPS what to fix.
        if not reason:
            return Response(
                {"error": "A remark is required when returning a clearance. State "
                          "clearly what is wrong, because it is all HR-OPS receives."},
                status=status.HTTP_400_BAD_REQUEST
            )

        actor = request.identity.user
        previous_status = application.status

        application.status = 'Fix Clearance'
        application.form_correction_remarks = reason
        application.awaiting_referrer_action = False
        application.save(update_fields=[
            'status', 'form_correction_remarks', 'awaiting_referrer_action'])

        record_application_event(
            application, actor,
            previous_status=previous_status, new_status='Fix Clearance',
            remark=f"Clearance returned to HR-OPS: {reason}",
            audit_action='CLEARANCE_RETURNED',
        )
        return Response(
            {"message": f"{ticket} returned to HR-OPS. Everything already "
                        f"recorded is kept."},
            status=status.HTTP_200_OK
        )


class CertificateCorrectionAPIView(APIView):
    """The correction loop for an issued certificate.

    POST   HR-APP uploads a corrected PDF (multipart: ticket, file, remark)
    PATCH  HR-APP approves it (ticket, decision)

    UNLIKE THE OFFER LETTER, both ends are the same person. That is deliberate:
    once a certificate exists, corrections and re-approval belong to HR-APP
    alone and no other role is involved. So this is a self-check rather than an
    approval -- the value is that the corrected file goes back through the same
    door, gets signed by the same mechanism, and leaves the same audit trail,
    rather than being swapped in silently.
    """

    @role_required('HR-APP')
    @transaction.atomic
    def post(self, request):
        ticket = request.data.get('ticket')
        upload = request.FILES.get('file')
        remark = upper_text(request.data.get('remark', '') or '')

        if not ticket or upload is None:
            return Response({"error": "A ticket and a file are both required."},
                            status=status.HTTP_400_BAD_REQUEST)

        if not upload.name.lower().endswith('.pdf'):
            return Response(
                {"error": "A corrected certificate must be a PDF. Make your "
                          "changes in the Word copy, export it as PDF, and upload that."},
                status=status.HTTP_400_BAD_REQUEST
            )

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if not application.certificate_issued_at:
            return Response(
                {"error": "No certificate has been issued for this application, "
                          "so there is nothing to correct."},
                status=status.HTTP_409_CONFLICT
            )

        doc_type = certificate_type()
        if doc_type is None:
            return Response(
                {"error": "The 'Completion Certificate' document type is missing "
                          "from the catalogue."},
                status=status.HTTP_400_BAD_REQUEST
            )

        actor = request.identity.user
        try:
            document = stage_document_for_approval(
                application, doc_type, upload, actor=actor,
                remarks=remark or 'Corrected certificate uploaded by HR-APP.',
            )
        except ValueError as conflict:
            return Response({"error": str(conflict)}, status=status.HTTP_409_CONFLICT)

        previous_status = application.status
        application.status = 'Pending Certificate'
        application.save(update_fields=['status'])

        record_application_event(
            application, actor,
            previous_status=previous_status, new_status='Pending Certificate',
            remark=remark or 'Corrected certificate queued for re-approval.',
            audit_action='CERTIFICATE_CORRECTION_SUBMITTED',
        )
        return Response({
            "message": "Corrected certificate queued for re-approval. It will not "
                       "replace the current certificate until you approve it.",
            "ticket": ticket,
            "fileName": str(document.file_path).split('/')[-1],
            "viewUrl": document_view_url(document),
        }, status=status.HTTP_201_CREATED)

    @role_required('HR-APP')
    @transaction.atomic
    def patch(self, request):
        ticket = request.data.get('ticket')
        decision = (request.data.get('decision') or '').strip().lower()
        reason = upper_text((request.data.get('reason') or '').strip())

        if not ticket or decision not in ('approve', 'reject'):
            return Response(
                {"error": "ticket and decision ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        application = Applications.objects.filter(application_code=ticket).first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        doc_type = certificate_type()
        document = pending_document(application, doc_type) if doc_type else None
        if document is None:
            return Response(
                {"error": "There is no corrected certificate awaiting approval "
                          "for this application."},
                status=status.HTTP_409_CONFLICT
            )

        actor = request.identity.user
        previous_status = application.status

        if decision == 'reject':
            if not reason:
                return Response(
                    {"error": "A remark is required when discarding a corrected "
                              "certificate."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            reject_pending_document(document, actor, reason)
            application.status = 'Pending Dispatch'
            application.save(update_fields=['status'])
            record_application_event(
                application, actor,
                previous_status=previous_status, new_status='Pending Dispatch',
                remark=f"Corrected certificate discarded: {reason}",
                audit_action='CERTIFICATE_CORRECTION_REJECTED',
            )
            return Response({"message": f"Corrected certificate discarded for {ticket}."},
                            status=status.HTTP_200_OK)

        # --- APPROVE: the signature is applied HERE, and only here -----------
        stored = stored_document_path(document)
        signature_file = signature_absolute_path(actor.active_signature_path)

        if signature_file is None:
            return Response(
                {"error": "You have no approved signature on file, so this "
                          "certificate cannot be signed."},
                status=status.HTTP_409_CONFLICT
            )
        if stored is None:
            return Response(
                {"error": "The uploaded certificate is missing from storage. "
                          "Upload it again."},
                status=status.HTTP_409_CONFLICT
            )

        try:
            with open(stored, 'rb') as handle:
                original = handle.read()
            signed, placed_precisely, failure = stamp_signature(
                original, str(signature_file),
                getattr(getattr(actor, 'employee', None), 'full_name', ''),
            )
        except Exception as stamping_error:
            logger.error("CERTIFICATE STAMPING FAILED (%s): %s",
                         type(stamping_error).__name__, stamping_error)
            signed, placed_precisely, failure = None, False, str(stamping_error)

        # Refuse rather than store an unsigned certificate as the signed one.
        # Approving IS signing.
        if failure:
            return Response(
                {"error": f"The certificate could not be signed, so it has not "
                          f"been approved: {failure}."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        with open(stored, 'wb') as handle:
            handle.write(signed)

        approve_pending_document(document, actor)

        application.status = 'Pending Dispatch'
        application.certificate_signed_by_user = actor
        application.certificate_signature_path = actor.active_signature_path
        application.save(update_fields=[
            'status', 'certificate_signed_by_user', 'certificate_signature_path'])

        record_application_event(
            application, actor,
            previous_status=previous_status, new_status='Pending Dispatch',
            remark='Corrected certificate approved and signed.',
            audit_action='CERTIFICATE_CORRECTION_APPROVED',
        )

        message = (f"Corrected certificate approved for {ticket}. It is now the "
                   f"official certificate, signed with your signature.")
        if not placed_precisely:
            message += ("\n\nNOTE: the signature block could not be located in "
                        "the uploaded PDF, so the signature was placed at the "
                        "standard position. Open it and check before dispatch.")
        return Response({"message": message}, status=status.HTTP_200_OK)


class CertificateDispatchAPIView(APIView):
    """Send the certificate to the candidate and close the internship.

    POST {ticket}

    Dispatch marks the intern Completed, records the dispatch time, and QUEUES
    the completion email. Nothing is sent from this request: the row is written
    Pending and `manage.py send_notifications` sends it, with the signed
    certificate PDF attached, resolved at send time.

    TWO RECORDS OF THE SAME FACT, and they must not drift:

      notifications                      the queue row, and the failure reason
                                         if it never went out
      applications.certificate_email_status
                                         what HR's dashboard and the archive
                                         filter actually read

    The send command syncs the column when it processes the row. A row recorded
    Failed at QUEUE time never reaches the send command, so this method syncs
    that case itself -- otherwise the column would sit on 'Pending' forever,
    telling HR a message was owed that nothing would ever send.
    """

    @role_required('HR-APP')
    @transaction.atomic
    def post(self, request):
        ticket = request.data.get('ticket')
        application = Applications.objects.filter(application_code=ticket).select_related('student').first()
        if application is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if application.status != 'Pending Dispatch':
            return Response(
                {"error": f"A certificate is dispatched from 'Pending Dispatch'. "
                          f"This application is '{application.status}'."},
                status=status.HTTP_409_CONFLICT
            )

        doc_type = certificate_type()
        if doc_type is not None and pending_document(application, doc_type) is not None:
            return Response(
                {"error": "A corrected certificate is still awaiting your approval. "
                          "Approve or discard it before dispatching."},
                status=status.HTTP_409_CONFLICT
            )

        if not application.certificate_issued_at:
            return Response({"error": "No certificate has been issued yet."},
                            status=status.HTTP_409_CONFLICT)

        actor = request.identity.user
        previous_status = application.status
        candidate_email = getattr(application.student, 'personal_email', None)

        application.certificate_dispatched_at = timezone.now()
        application.certificate_email_status = 'Pending'
        application.status = 'Completed'
        application.save(update_fields=[
            'certificate_dispatched_at', 'certificate_email_status', 'status'])

        record_application_event(
            application, actor,
            previous_status=previous_status, new_status='Completed',
            remark=f"Completion certificate dispatched to {candidate_email or 'the candidate'}. "
                   f"Completion email queued for sending.",
            audit_action='CERTIFICATE_DISPATCHED',
        )

        # --- THE EMAIL ------------------------------------------------------
        #
        # Queued, not sent. The signed PDF is attached by the send command,
        # located through certificate_type() + current_document() at that
        # moment -- never a path captured here. A correction uploaded between
        # now and then supersedes the certificate and quarantines the old file,
        # so a path stored now could point at a document that has moved.
        #
        # Inside the transaction: this method is @transaction.atomic, so if
        # anything rolls the dispatch back the queued row goes with it and no
        # certificate is emailed for a dispatch that did not happen.
        notification = queue_notification(
            application, ntypes.COMPLETION_CERTIFICATE_ISSUED)

        # A notification recorded Failed at queue time -- no candidate address,
        # say -- is never picked up by the send command, so nothing else will
        # ever move certificate_email_status off 'Pending'. Without this, the
        # dashboard would show a message permanently owed and permanently
        # un-sent, with no indication anything was wrong.
        if notification is not None and notification.delivery_status == ntypes.STATUS_FAILED:
            application.certificate_email_status = ntypes.STATUS_FAILED
            application.save(update_fields=['certificate_email_status'])
            logger.error(
                'Certificate email for %s could not be queued: %s',
                ticket, notification.failure_reason,
            )

        return Response({
            "message": f"{ticket} marked as completed. The certificate is "
                       f"queued for email to {candidate_email or 'the candidate'} "
                       f"— the email system is not built yet, so the message is "
                       f"recorded as pending rather than sent.",
            "emailStatus": "Pending",
            "candidateEmail": candidate_email,
        }, status=status.HTTP_200_OK)


def serialize_audit_row(h):
    """One audit ledger row, exactly as the dashboard shows it.

    Extracted so the LEDGER and the EXPORT read from ONE place. They used to
    build the details column separately and had already drifted: the screen
    showed a readable sentence while the export showed raw JSON, or an empty
    cell, for every event type added after the export was written.

    An export that disagrees with the screen it was taken from is worse than no
    export at all -- it is a document somebody will file.
    """
    user = h.actor_user
    employee = getattr(user, 'employee', None) if user else None
    actor_name = getattr(employee, 'full_name', 'System')
    role_name = h.role_name or 'API Engine'

    # Forensic detail. Payload shape varies by event, so each is rendered
    # from its own fields rather than assuming a 'remarks' key -- which
    # is why document views previously showed an empty detail column.
    payload = {}
    try:
        payload = json.loads(h.new_value) if h.new_value else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    if h.action_type == 'DOCUMENT_VIEWED':
        # Name the document AND whose application it belongs to: "who
        # opened what" is the entire point of recording these.
        doc_name = payload.get('document') or 'Document'
        candidate = payload.get('candidate') or ''
        if h.target_entity_type == 'ArchivedDocument':
            # An archived view is identified by TICKET and CYCLE rather
            # than by candidate name. The record is read years later,
            # when the cycle is how anyone would find it, and the ticket
            # is the only identifier guaranteed to be unique.
            ticket = payload.get('application') or 'unknown'
            cyc = payload.get('cycle')
            details = (f"Viewed archived document: {doc_name} "
                       f"(Ticket ID: {ticket}"
                       + (f", cycle: {cyc}" if cyc else "") + ")")
        else:
            details = f"Viewed document: {doc_name}"
            if candidate:
                details += f" (candidate: {candidate})"
    elif h.action_type == 'DOCUMENT_SUPERSEDED':
        old_payload = {}
        try:
            old_payload = json.loads(h.old_value) if h.old_value else {}
        except Exception:
            pass
        details = (f"Replaced {old_payload.get('doc_type', 'document')} "
                   f"(version {old_payload.get('version', '?')} superseded)")
    elif h.action_type in ('OFFER_LETTER_DOWNLOADED', 'GENERATED_DOCUMENT_DOWNLOADED'):
        # 'variant' is the current key; 'format' is what earlier rows
        # carry. Both are read so the ledger stays readable backwards.
        kind = (payload.get('variant') or payload.get('format') or '').upper()
        who = payload.get('downloadedBy') or 'an HR user'
        doc = payload.get('document') or 'Offer letter'
        ticket = payload.get('application') or ''
        details = f"Downloaded {doc}" + (f" {kind}" if kind else "")
        if ticket:
            details += f" for {ticket}"
        details += f", by {who}."
    elif h.action_type == 'DOCUMENT_GENERATED':
        details = (f"Generated {payload.get('doc_type', 'document').title()} "
                   f"version {payload.get('version', '?')} "
                   f"for {payload.get('application', 'this application')}.")
    elif h.action_type == 'DOCUMENT_PENDING_APPROVAL':
        details = (f"Corrected {payload.get('doc_type', 'document').title()} uploaded "
                   f"for {payload.get('application', 'this application')}. "
                   f"Awaiting approval; the existing document remains in force.")
    elif h.action_type == 'DOCUMENT_CORRECTION_APPROVED':
        details = (f"Approved the corrected {payload.get('doc_type', 'document').title()} "
                   f"for {payload.get('application', 'this application')}. "
                   f"It is now version {payload.get('version', '?')} and the official copy.")
    elif h.action_type == 'DOCUMENT_CORRECTION_REJECTED':
        details = (f"Returned the corrected {payload.get('doc_type', 'document').title()} "
                   f"for {payload.get('application', 'this application')} to HR-OPS. "
                   f"Reason: {payload.get('reason', 'not recorded')}")
    elif h.action_type == 'REPORT_EXPORTED':
        # Who took data out of the portal, how much of it, and what they could
        # see at the time. The tab and the filters matter as much as the count:
        # 'exported 40 records' says little, 'exported the 40 Fix Joining
        # records for Summer 2026' says who was in that file.
        label = payload.get('moduleLabel') or payload.get('module') or 'records'
        fmt = (payload.get('format') or '').upper()
        count = payload.get('recordCount')
        tab = payload.get('tab') or ''
        filters = payload.get('filters') or 'No filters'
        details = f"Exported {label}"
        if tab and tab != label:
            details += f" ({tab})"
        details += f" to {fmt or 'file'}"
        if count is not None:
            details += f": {count} record{'' if count == 1 else 's'}"
        details += f". Filters: {filters}."
    elif h.action_type == 'SIGNATURE_SUBMITTED':
        details = "Submitted a new signature for administrator approval."
    elif h.action_type == 'SIGNATURE_APPROVED':
        details = ("Approved a new signature. It applies to every letter issued "
                   "from now on; letters already issued are unchanged.")
        if payload.get('replaced'):
            details += " The previous signature was quarantined."
    elif h.action_type == 'SIGNATURE_REJECTED':
        details = f"Returned a signature to the officer. Reason: {payload.get('reason', 'not recorded')}"
    elif h.action_type == 'SIGNATURE_VIEWED':
        details = (f"Viewed the {payload.get('kind', 'stored')} signature of "
                   f"{payload.get('officer') or 'an officer'}, "
                   f"by {payload.get('viewedBy') or 'an administrator'}.")
    else:
        # A status transition records its remark. When HR left the
        # remark blank the raw JSON was printed instead -- literally
        # '{"remarks": ""}' in the details column, which told an auditor
        # nothing. Fall back to naming the transition itself.
        details = (payload.get('remarks') or '').strip()
        if not details:
            if h.action_type and h.action_type.upper() != h.action_type:
                details = f"Status changed to {h.action_type}."
            elif payload:
                details = "Recorded. No remark was entered."
            else:
                details = h.new_value or "System state transition recorded."

    # Target string. A document event names the APPLICATION it concerns,
    # not "Document Configuration": an auditor needs the ticket.
    if h.target_entity_type == 'Application':
        app = Applications.objects.filter(pk=h.target_entity_id).first()
        if app:
            target_str = (f"Ticket: {app.application_code}" if app.application_code
                          else f"Ticket: DRAFT-{app.application_id}")
        else:
            # The live row is gone, which for a hard-closed cycle is
            # normal rather than an error: archiving MOVES applications.
            # The archive keeps the ticket, so look there before giving
            # up -- every entry for an archived cycle used to degrade to
            # "APP-ID-420001", an internal row number that means nothing
            # to anyone, on precisely the records kept longest.
            archived = ArchivedApplications.objects.filter(
                original_application_id=h.target_entity_id).first()
            if archived and archived.application_code:
                target_str = (f"Ticket: {archived.application_code} "
                              f"({archived.session_term} {archived.application_year}, archived)")
            else:
                target_str = f"Ticket: APP-ID-{h.target_entity_id}"
    elif h.target_entity_type == 'Document':
        ticket = payload.get('application')
        target_str = f"Ticket: {ticket}" if ticket else f"Document #{h.target_entity_id}"
    elif h.target_entity_type == 'ArchivedDocument':
        # Named as the event it is. The generic branch below rendered
        # this as "ArchivedDocument Configuration", which describes
        # neither a configuration change nor anything an auditor would
        # recognise.
        target_str = "Archived Document Viewed"
    elif h.target_entity_type == 'Export':
        # Named as the event it is. The generic branch below would render this
        # as "Export Configuration", which sounds like a settings change rather
        # than data leaving the portal.
        target_str = payload.get('moduleLabel') or 'Data Export'
    else:
        target_str = f"{h.target_entity_type} Configuration"

    return {
        "logId": h.log_id,
        "ticketId": target_str,
        "timestamp": safe_extract_time(h, 'created_at'),
        "action": h.action_type,
        "actor": actor_name,
        "role": role_name,
        "remark": details
    }


class HRAuditLedgerAPIView(APIView):
    @role_required(*ALL_HR_ROLES)
    def get(self, request):
        history_records = SystemAuditLogs.objects.select_related(
            'actor_user', 
            'actor_user__employee', 
        ).all().order_by('-created_at')

        ledger_data = []
        # Built by serialize_audit_row(), which the EXPORT also uses, so the
        # file and the screen can never disagree about what an event says.
        ledger_data = [serialize_audit_row(h) for h in history_records]

        return Response(ledger_data, status=status.HTTP_200_OK)

class IAMUserAPIView(APIView):
    """Dashboard accounts: which employee holds which role.

    GET                      the personnel directory
    GET ?employee_code=...   look ONE employee up in the DMRC directory
    POST                     grant a role to an employee who already exists
    PATCH                    revoke or restore an account

    WHY PROVISIONING TAKES ONLY AN EMPLOYEE CODE
    ---------------------------------------------------------------------------
    This portal does not own employee identity. `employees` is a projection of
    DMRC's directory keyed on employee_code -- see portal/identity/base.py. A
    name or designation typed into the provisioning form would be a second,
    unverified copy of something the directory already holds, free to drift from
    it and wrong the moment somebody is promoted.

    The designation matters more than it looks: it is printed under the
    signature on every offer letter that person signs. It must come from the
    directory, not from whatever an administrator typed months earlier.

    So the administrator supplies the CODE and the ROLE. Everything else is
    read. An unknown code is refused.
    """

    @role_required('SYS-ADMIN')
    def get(self, request):
        # --- SINGLE EMPLOYEE LOOKUP ------------------------------------------
        # Backs the provisioning form: type a code, see who it is before
        # granting them anything.
        lookup_code = upper_text((request.query_params.get('employee_code') or '').strip())
        if lookup_code:
            employee = (Employees.objects
                        .filter(employee_code__iexact=lookup_code)
                        .select_related('department').first())
            if employee is None:
                return Response(
                    {"error": f"'{lookup_code}' is not in the employee directory. "
                              f"Check the code, or ask DMRC IT to add the employee."},
                    status=status.HTTP_404_NOT_FOUND
                )

            existing = (Users.objects.filter(employee=employee)
                        .select_related('role').first())
            return Response({
                "empId": employee.employee_code,
                "name": employee.full_name,
                "designation": employee.designation or '',
                "department": getattr(employee.department, 'department_name', ''),
                # A second account for the same person is impossible: users
                # holds a UNIQUE key on employee_id.
                "alreadyProvisioned": existing is not None,
                "existingRole": getattr(getattr(existing, 'role', None), 'role_name', None),
                "existingIsActive": bool(getattr(existing, 'is_active', 0)) if existing else False,
            }, status=status.HTTP_200_OK)

        try:
            users = Users.objects.select_related('employee', 'role').all().order_by('-user_id')
            user_list = []
            for u in users:
                employee = getattr(u, 'employee', None)
                role = getattr(u, 'role', None)
                user_list.append({
                    "id": u.user_id,
                    "empId": getattr(employee, 'employee_code', 'N/A') if employee else 'N/A',
                    "name": getattr(employee, 'full_name', 'System Admin') if employee else 'System Admin',
                    # Printed under the signature on every letter this person
                    # signs, so it belongs on the screen that grants the role.
                    "designation": getattr(employee, 'designation', '') if employee else '',
                    "role": getattr(role, 'role_name', 'SYS-ADMIN') if role else 'SYS-ADMIN',
                    "isActive": bool(u.is_active),
                    "added": safe_extract_time(u, 'created_at'),
                    "updated": safe_extract_time(u, 'status_updated_at')
                })
            return Response(user_list, status=status.HTTP_200_OK)
        except Exception as e:
            print("IAM GET Error:", str(e))
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @role_required('SYS-ADMIN')
    @transaction.atomic
    def post(self, request):
        """Grant a dashboard role to an employee who already exists.

        Takes an employee code and a role, and nothing else.

        THREE THINGS THIS FIXES
        1. It used to CREATE an employee from whatever was typed, defaulting the
           department to id 1. A typo in the code silently produced a phantom
           employee carrying somebody else's name, in the wrong department,
           holding a real role. The employee must now already exist.
        2. It created the Users row without a username or an email, both of
           which are UNIQUE NOT NULL in the schema -- so provisioning could
           never actually succeed. Both are now derived from the directory.
        3. It accepted any role string and created it on the fly, so a typo
           produced a role nothing grants and nothing checks.
        """
        try:
            emp_id = upper_text((request.data.get('empId') or '').strip())
            role_name = (request.data.get('role') or '').strip()

            if not emp_id or not role_name:
                return Response(
                    {"error": "An employee ID and a role are both required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if role_name not in ROLE_HIERARCHY:
                return Response(
                    {"error": f"'{role_name}' is not a valid role. "
                              f"Expected one of: {', '.join(ROLE_HIERARCHY)}."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            employee = (Employees.objects
                        .filter(employee_code__iexact=emp_id)
                        .select_related('department').first())
            if employee is None:
                return Response(
                    {"error": f"'{emp_id}' is not in the employee directory, so no "
                              f"role can be granted. Check the code, or ask DMRC IT "
                              f"to add the employee first."},
                    status=status.HTTP_404_NOT_FOUND
                )

            if Users.objects.filter(employee=employee).exists():
                return Response(
                    {"error": f"{employee.full_name} already holds a dashboard "
                              f"account. Change or revoke it from the directory "
                              f"instead of provisioning a second one."},
                    status=status.HTTP_409_CONFLICT
                )

            role = Roles.objects.filter(role_name=role_name).first()
            if role is None:
                return Response(
                    {"error": f"The '{role_name}' role is missing from the roles "
                              f"table. Restore it before granting it."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # username and email are UNIQUE NOT NULL. Both are derived from the
            # directory rather than typed: the email IS the directory's, and the
            # username follows the convention the seed data uses -- the local
            # part of that address, or the employee code when there is no email.
            email = (employee.official_email or '').strip()
            username = email.split('@')[0] if email else employee.employee_code.lower()
            if not email:
                # A placeholder that is unique and obviously not deliverable,
                # rather than a NULL the column will not accept.
                email = f"{employee.employee_code.lower()}@no-email.invalid"

            suffix = 1
            base_username = username
            while Users.objects.filter(username=username).exists():
                suffix += 1
                username = f"{base_username}{suffix}"

            user = Users.objects.create(
                employee=employee, role=role, username=username,
                email=email, is_active=1,
            )

            _audit(getattr(getattr(request, 'identity', None), 'user', None),
                   'IAM_UPDATE', 'User', user.pk,
                   new_value={"remarks": f"Provisioned {role_name} access for "
                                         f"{employee.full_name} ({employee.employee_code}), "
                                         f"{employee.designation or 'no designation on file'}."})

            return Response({
                "message": f"{role_name} access granted to {employee.full_name}.",
                "empId": employee.employee_code,
                "name": employee.full_name,
                "designation": employee.designation or '',
                "role": role_name,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            print("IAM POST Error:", str(e))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @role_required('SYS-ADMIN')
    def patch(self, request):
        try:
            user_id = request.data.get('id')
            if not user_id:
                return Response({"error": "User ID required."}, status=status.HTTP_400_BAD_REQUEST)

            user = Users.objects.get(pk=user_id)
            user.is_active = 0 if user.is_active else 1 
            user.save()
            
            try:
                employee_name = getattr(user.employee, 'full_name', 'User') if user.employee else 'User'
                status_text = 'Restored' if user.is_active else 'Revoked'
                system_user = getattr(getattr(request, 'identity', None), 'user', None)
                with transaction.atomic():
                    SystemAuditLogs.objects.create(
                        actor_user=system_user,
                        role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                        action_type='IAM_UPDATE',
                        target_entity_type='User',
                        target_entity_id=user.pk,
                        new_value=json.dumps({"remarks": f"Account access {status_text} for {employee_name}."})
                    )
            except Exception as audit_error:
                logger.error("AUDIT WRITE FAILED (%s): %s",
                             type(audit_error).__name__, audit_error)

            return Response({"message": f"Access {status_text}."}, status=status.HTTP_200_OK)
        except Users.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class AdminCycleAPIView(APIView):
    @role_required('SYS-ADMIN')
    def get(self, request):
        try:
            cycles = InternshipCycles.objects.all().order_by('-cycle_id')
            cycle_list = []
            doj_map = {}
            
            for c in cycles:
                cycle_name = f"{getattr(c, 'session_term', 'Summer')} {getattr(c, 'application_year', '2026')}"
                start_val = getattr(c, 'application_start_date', None)
                end_val = getattr(c, 'application_end_date', None)
                
                cycle_list.append({
                    "id": getattr(c, 'cycle_id', c.pk),
                    "cycle_id": getattr(c, 'cycle_id', c.pk),
                    "name": cycle_name,
                    "start": str(start_val) if start_val else "2026-01-01",
                    "end": str(end_val) if end_val else "2026-12-31",
                    "isActive": bool(getattr(c, 'is_active', 1)),
                    "is_active": bool(getattr(c, 'is_active', 1))
                })

                doj_dates = CycleJoiningDates.objects.filter(cycle=c, is_active=1).values_list('allowed_doj', flat=True)
                doj_map[cycle_name] = [str(d) for d in doj_dates]

            depts = Departments.objects.all().order_by('department_name')
            capacity_list = []
            
            # The capacity matrix belongs to ONE cycle. It used to be built for
            # the newest active cycle whatever the administrator had selected,
            # so with concurrent cycles you could read Summer's occupancy while
            # editing Winter's quotas.
            active_cycle = resolve_cycle(request)
            cap_records = {}
            if active_cycle:
                for cap in CycleDepartmentCapacities.objects.filter(cycle=active_cycle):
                    try:
                        d_name = cap.department.department_name
                    except AttributeError:
                        try:
                            dept = Departments.objects.get(pk=cap.department_id)
                            d_name = dept.department_name
                        except Exception:
                            continue
                    cap_records[d_name] = getattr(cap, 'max_capacity', 25)
            
            # Single shared definition of occupancy, so the admin matrix and the
            # referrer's waitlist warning can never disagree. This block used a
            # different exclusion list ('Withdrawn' is not even a status, and
            # 'Completed' was treated as freeing a seat), which meant the two
            # screens could show different numbers for the same cycle.
            occupancy_map = department_occupancy(active_cycle)
            for d in depts:
                occupied = occupancy_map.get(d.department_name, 0)
                
                capacity_list.append({
                    "dept": d.department_name,
                    "quota": cap_records.get(d.department_name, 25), 
                    "occupied": occupied
                })

            return Response({
                "cycles": cycle_list,
                "capacities": capacity_list,
                "allowedDojDatesByCycle": doj_map
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            print("Cycle GET Error:", str(e))
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @role_required('SYS-ADMIN')
    @transaction.atomic
    def post(self, request):
        try:
            term = request.data.get('term')
            year = request.data.get('year')
            start = request.data.get('start')
            end = request.data.get('end')
            
            # Validate before touching the database. application_start_date and
            # application_end_date are NOT NULL, so a missing date surfaced as a
            # raw "(1048, Column ... cannot be null)" that told an administrator
            # nothing about which field to fill.
            missing = []
            if not term:  missing.append('Session term')
            if not year:  missing.append('Application year')
            if not start: missing.append('Application start date')
            if not end:   missing.append('Application end date')
            if missing:
                return Response(
                    {"error": f"Cannot create the cycle. Missing required field(s): "
                              f"{', '.join(missing)}. Complete step 1 of the wizard and try again."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if str(start) > str(end):
                return Response(
                    {"error": "The application start date cannot be after the end date."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # The year is typed by hand and nothing checked it, so a slip such as
            # '20276' was accepted and stored. It then appeared in every ticket
            # this cycle issued -- DMRC-20276W-001 -- because ticket codes are
            # built from it, and a ticket cannot be corrected once handed out.
            try:
                year = int(str(year).strip())
            except (TypeError, ValueError):
                return Response(
                    {"error": f"'{year}' is not a valid year. Enter a four-digit year, e.g. 2027."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if not (2000 <= year <= 2100):
                return Response(
                    {"error": f"{year} is not a valid application year. Enter a four-digit "
                              f"year between 2000 and 2100 -- this year appears in every "
                              f"ticket number the cycle issues."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            quotas = parse_payload_array(request.data, 'quotas', 'capacities')
            sub_depts = parse_payload_array(request.data, 'subDepts', 'sub_departments')
            rules = parse_payload_array(request.data, 'rules', 'docRules')
            dojs = parse_payload_array(request.data, 'dojs', 'allowedDojs')
            
            new_cycle = InternshipCycles.objects.create(
                session_term=term,
                application_year=year,
                application_start_date=start if start else None,
                application_end_date=end if end else None,
                is_active=1
            )
            
            # Every cycle_* config table carries UNIQUE (cycle_id, <thing>), so a
            # repeated entry raises IntegrityError 1062 and fails the whole
            # initialisation. Two wizard rows can legitimately collapse onto one
            # database row -- names are normalised (trimmed and upper-cased)
            # before lookup, so "Civil - Viaducts" and "CIVIL - VIADUCTS" resolve
            # to the same sub-department. update_or_create plus a seen-set makes
            # each loop idempotent, so duplicates in the payload are absorbed
            # rather than aborting the cycle.
            seen_departments = set()
            for q in quotas:
                dept_name = q.get('dept') if isinstance(q, dict) else None
                if not dept_name:
                    continue
                quota_val = int(q.get('quota', 25))
                dept, _ = Departments.objects.get_or_create(department_name=dept_name.strip())
                if dept.department_id in seen_departments:
                    continue
                seen_departments.add(dept.department_id)
                CycleDepartmentCapacities.objects.update_or_create(
                    cycle=new_cycle, department=dept,
                    defaults={'max_capacity': quota_val, 'seats_occupied': 0}
                )

            seen_sub_departments = set()
            for sd in sub_depts:
                name = sd.get('name') if isinstance(sd, dict) else sd
                if not name:
                    continue
                sub_dept, _ = SubDepartments.objects.get_or_create(
                    sub_department_name=name.strip().upper(),
                    defaults={'is_global_active': 1}
                )
                if sub_dept.sub_department_id in seen_sub_departments:
                    continue
                seen_sub_departments.add(sub_dept.sub_department_id)
                CycleSubDepartments.objects.update_or_create(
                    cycle=new_cycle, sub_department=sub_dept,
                    defaults={'is_active': 1}
                )

            seen_doc_types = set()
            for r in rules:
                doc_name = r.get('name') if isinstance(r, dict) else None
                if doc_name:
                    doc_format = r.get('format', 'PDF, JPG')
                    is_mandatory = 1 if r.get('isMandatory', True) else 0
                    
                    # Every configured document is collected in the Phase 1 form.
                    
                    doc_type, _ = DocumentTypes.objects.get_or_create(type_name=doc_name.strip(), defaults={'allowed_extensions': doc_format, 'is_system_generated': 0, 'is_active': 1})
                    if doc_type.doc_type_id in seen_doc_types:
                        continue
                    seen_doc_types.add(doc_type.doc_type_id)
                    CycleDocumentRequirements.objects.update_or_create(
                        cycle=new_cycle, doc_type=doc_type,
                        defaults={'is_mandatory': is_mandatory}
                    )

            seen_dojs = set()
            for doj in dojs:
                if not doj:
                    continue
                doj_value = str(doj).strip()
                if doj_value in seen_dojs:
                    continue
                seen_dojs.add(doj_value)
                CycleJoiningDates.objects.update_or_create(
                    cycle=new_cycle, allowed_doj=doj_value,
                    defaults={'is_active': 1}
                )

            try:
                system_user = getattr(getattr(request, 'identity', None), 'user', None)
                with transaction.atomic():
                    SystemAuditLogs.objects.create(
                        actor_user=system_user,
                        role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                        action_type='SYSTEM_OVERRIDE',
                        target_entity_type='Cycle',
                        target_entity_id=new_cycle.pk,
                        new_value=json.dumps({"remarks": f"Initialized new cycle: {term} {year} with all parameters."})
                    )
            except Exception as audit_error:
                logger.error("AUDIT WRITE FAILED (%s): %s",
                             type(audit_error).__name__, audit_error)

            return Response({"message": "Cycle initialized successfully."}, status=status.HTTP_201_CREATED)
        except IntegrityError as e:
            # Translate the database's own codes into something an administrator
            # can act on. Reporting every IntegrityError as a duplicate would be
            # wrong: 1048 is a missing required value, not a repeated one.
            detail = str(e)
            print("Cycle POST IntegrityError:", detail)

            if '1062' in detail or 'Duplicate entry' in detail:
                message = ("This cycle could not be created because one of its entries is "
                           "duplicated. Check for a department, sub-department, document rule "
                           "or joining date listed twice in the wizard, then try again.")
            elif '1048' in detail or 'cannot be null' in detail:
                column = ''
                if "Column '" in detail:
                    column = detail.split("Column '")[1].split("'")[0].replace('_', ' ')
                message = (f"A required field is missing{': ' + column if column else ''}. "
                           "Complete every step of the wizard and try again.")
            else:
                message = f"The cycle could not be saved: {detail}"

            return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print("Cycle POST Error:", str(e))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @role_required('SYS-ADMIN')
    @transaction.atomic
    def patch(self, request):
        # A draft for a closed cycle can never be submitted; free its files.
        purge_drafts_for_closed_cycles()
        try:
            action = request.data.get('action')
            # Resolved once for the whole method. It used to be assigned inside
            # each branch's audit block, so the archive branch -- which needs it
            # before that point -- referenced it before assignment and failed.
            system_user = getattr(getattr(request, 'identity', None), 'user', None)

            if action == 'save_master_calendar':
                cycle_name = request.data.get('cycleName')
                dojs = parse_payload_array(request.data, 'dojs', 'allowedDojs')
                
                if not cycle_name:
                    return Response({"error": "Cycle name required."}, status=status.HTTP_400_BAD_REQUEST)

                term, year = cycle_name.split(' ')
                cycle = InternshipCycles.objects.filter(session_term=term, application_year=year).first()
                
                if cycle:
                    CycleJoiningDates.objects.filter(cycle=cycle).delete()
                    for d_str in dojs:
                        CycleJoiningDates.objects.create(cycle=cycle, allowed_doj=str(d_str), is_active=1)
                    
                    try:
                        system_user = getattr(getattr(request, 'identity', None), 'user', None)
                        with transaction.atomic():
                            SystemAuditLogs.objects.create(
                                actor_user=system_user,
                                role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                                action_type='RULES_UPDATE',
                                target_entity_type='Cycle',
                                target_entity_id=cycle.pk,
                                new_value=json.dumps({"remarks": f"Joining dates updated for {cycle_name}: {len(dojs)} date(s) now available. Other cycles unaffected."})
                            )
                    except Exception as audit_error:
                        # The ledger records who did what. A failed write must not
                        # take the action down with it, but it must not vanish either:
                        # a silent pass here hid a broken audit block for a whole
                        # round of changes.
                        logger.error("AUDIT WRITE FAILED (%s): %s",
                                     type(audit_error).__name__, audit_error)

                return Response({"message": "Master DOJ Calendar updated."}, status=status.HTTP_200_OK)

            elif action == 'edit_dates':
                cycle_name = request.data.get('cycleName')
                term, year = cycle_name.split(' ')
                cycle = InternshipCycles.objects.filter(session_term=term, application_year=year).first()
                if cycle:
                    old_start = safe_extract_time(cycle, 'application_start_date', date_only=True)
                    old_end = safe_extract_time(cycle, 'application_end_date', date_only=True)
                    
                    cycle.application_start_date = request.data.get('start')
                    cycle.application_end_date = request.data.get('end')
                    cycle.save()
                    
                    try:
                        system_user = getattr(getattr(request, 'identity', None), 'user', None)
                        with transaction.atomic():
                            SystemAuditLogs.objects.create(
                                actor_user=system_user,
                                role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                                action_type='RULES_UPDATE',
                                target_entity_type='Cycle',
                                target_entity_id=cycle.pk,
                                new_value=json.dumps({"remarks": f"Timeline updated for {cycle_name}. Start: {old_start} ➔ {cycle.application_start_date} | End: {old_end} ➔ {cycle.application_end_date}"})
                            )
                    except Exception as audit_error:
                        # The ledger records who did what. A failed write must not
                        # take the action down with it, but it must not vanish either:
                        # a silent pass here hid a broken audit block for a whole
                        # round of changes.
                        logger.error("AUDIT WRITE FAILED (%s): %s",
                                     type(audit_error).__name__, audit_error)
                
            elif action == 'archive_cycle':
                cycle_name = request.data.get('cycleName')
                term, year = cycle_name.split(' ')
                cycle = InternshipCycles.objects.filter(session_term=term, application_year=year).first()

                # A cycle may only be closed once every application in it has
                # reached a terminal state -- Completed or Rejected. Anything
                # else is still live work: a candidate awaiting an offer letter,
                # an intern mid-internship, or a college referral nobody has
                # decided about. Deactivating the cycle would strip those records
                # of their joining dates, document rules and capacity, leaving
                # them unworkable with no warning.
                #
                # The College Referrals staging states are deliberately NOT
                # treated as closeable: an abandoned intake must be rejected
                # explicitly, so a person decides its fate rather than it
                # disappearing with the cycle.
                if cycle:
                    open_apps = (Applications.objects
                                 .filter(cycle=cycle)
                                 .exclude(status__in=['Completed', 'Rejected'])
                                 .select_related('student')
                                 .order_by('status', 'application_code'))
                    if open_apps.exists():
                        by_status = {}
                        for a in open_apps:
                            by_status.setdefault(a.status, []).append(a.application_code)
                        summary = [
                            {"status": st,
                             "count": len(codes),
                             "tickets": codes[:5],
                             "more": max(0, len(codes) - 5)}
                            for st, codes in sorted(by_status.items())
                        ]
                        return Response({
                            "error": f"{cycle_name} cannot be archived yet. "
                                     f"{open_apps.count()} application(s) have not reached "
                                     f"Completed or Rejected.",
                            "blockers": summary,
                        }, status=status.HTTP_400_BAD_REQUEST)

                if cycle:
                    # --- COLD STORAGE -------------------------------------
                    # Everything is COPIED first and only then deleted, all in
                    # one transaction. If any part fails, nothing is committed
                    # and the cycle stays open -- a half-archived cycle would be
                    # unrecoverable, since the live rows would already be gone.
                    #
                    # ARCHIVING IS FINAL. There is no route back, by design: the
                    # value of the archive is that it provably has not been
                    # altered since the cycle closed.
                    try:
                        with transaction.atomic():
                            archived = archive_cycle_records(cycle, system_user)
                            cycle.is_active = 0
                            cycle.save(update_fields=['is_active'])
                    except Exception as archive_error:
                        logger.error("ARCHIVE FAILED for %s: %s",
                                     cycle_name, archive_error)
                        return Response(
                            {"error": f"{cycle_name} could not be archived: {archive_error} "
                                      f"Nothing has been changed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )

                    try:
                        with transaction.atomic():
                            SystemAuditLogs.objects.create(
                                actor_user=system_user,
                                role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                                action_type='SYSTEM_OVERRIDE',
                                target_entity_type='Cycle',
                                target_entity_id=cycle.pk,
                                new_value=json.dumps({"remarks":
                                    f"Hard closed and archived cycle {cycle_name}. "
                                    f"{archived['applications']} application(s) moved to cold "
                                    f"storage with {archived['documents']} document(s), "
                                    f"{archived['requirements']} requirement record(s) and "
                                    f"{archived['history']} timeline entr(ies). "
                                    f"Live records removed."})
                            )
                    except Exception as audit_error:
                        logger.error("AUDIT WRITE FAILED (%s): %s",
                                     type(audit_error).__name__, audit_error)

                    return Response({
                        "message": f"{cycle_name} archived. {archived['applications']} "
                                   f"application(s) moved to cold storage.",
                        "archived": archived,
                    }, status=status.HTTP_200_OK)


                return Response({"error": f"Cycle '{cycle_name}' not found."},
                                status=status.HTTP_404_NOT_FOUND)

            elif action == 'update_quotas':
                quotas = parse_payload_array(request.data, 'quotas', 'capacities')
                cycle_name = request.data.get('cycleName')
                term, year = cycle_name.split(' ') if cycle_name else (None, None)
                cycle = InternshipCycles.objects.filter(session_term=term, application_year=year).first() if term else InternshipCycles.objects.filter(is_active=1).order_by('-cycle_id').first()
                
                changes = []
                if cycle:
                    for q in quotas:
                        dept = Departments.objects.filter(department_name=q.get('dept')).first()
                        if dept:
                            cap_obj, created = CycleDepartmentCapacities.objects.get_or_create(cycle=cycle, department=dept, defaults={'max_capacity': q.get('quota', 25), 'seats_occupied': 0})
                            old_cap = cap_obj.max_capacity if not created else 0
                            new_cap = int(q.get('quota', 25))
                            
                            if old_cap != new_cap:
                                changes.append(f"{dept.department_name}: {old_cap}➔{new_cap}")
                            if old_cap != new_cap or created:
                                cap_obj.max_capacity = new_cap
                                cap_obj.save()
                        
                try:
                    system_user = getattr(getattr(request, 'identity', None), 'user', None)
                    cyc_name = cycle_label(cycle)
                    remark_text = (f"Capacity matrix adjusted for {cyc_name}: " + ", ".join(changes)
                                   if changes else f"Capacity matrix saved for {cyc_name} with no changes.")
                    with transaction.atomic():
                        SystemAuditLogs.objects.create(
                            actor_user=system_user,
                            role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                            action_type='CAPACITY_CHANGED',
                            target_entity_type='Cycle',
                            target_entity_id=cycle.pk if cycle else 0,
                            new_value=json.dumps({"remarks": remark_text})
                        )
                except Exception as audit_error:
                    # The ledger records who did what. A failed write must not
                    # take the action down with it, but it must not vanish either:
                    # a silent pass here hid a broken audit block for a whole
                    # round of changes.
                    logger.error("AUDIT WRITE FAILED (%s): %s",
                                 type(audit_error).__name__, audit_error)

            return Response({"message": f"Action '{action}' executed successfully."}, status=status.HTTP_200_OK)
            
        except Exception as e:
            print("Cycle PATCH Error:", str(e))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        
class AdminConfigAPIView(APIView):
    @role_required('SYS-ADMIN')
    def get(self, request):
        try:
            # The cycle the administrator is LOOKING AT, sent by the screen.
            # Never inferred: DMRC runs concurrent cycles, so guessing means
            # showing one cycle's configuration while the administrator
            # believes they are editing another.
            active_cycle = resolve_cycle(request)
            
            sub_dept_list = []
            if active_cycle and CycleSubDepartments.objects.filter(cycle=active_cycle).exists():
                cycle_sds = CycleSubDepartments.objects.filter(cycle=active_cycle)
                for csd in cycle_sds:
                    try:
                        sd_name = csd.sub_department.sub_department_name
                    except AttributeError:
                        sd_name = SubDepartments.objects.get(pk=csd.sub_department_id).sub_department_name
                    sub_dept_list.append({"name": sd_name, "isActive": bool(csd.is_active)})
            else:
                sub_depts = SubDepartments.objects.filter(is_global_active=1).order_by('sub_department_name')
                sub_dept_list = [{"name": s.sub_department_name, "isActive": bool(s.is_global_active)} for s in sub_depts]
            
            rule_list = []
            if active_cycle and CycleDocumentRequirements.objects.filter(cycle=active_cycle).exists():
                reqs = CycleDocumentRequirements.objects.filter(cycle=active_cycle)
                for req in reqs:
                    doc_type = req.doc_type
                    if doc_type is None:
                        continue
                    rule_list.append({
                        "id": doc_type.doc_type_id,
                        "key": document_slug(doc_type.doc_type_id),
                        "name": doc_type.type_name,
                        # Format and enabled come from THIS CYCLE's row. The
                        # values on document_types are only the catalogue
                        # default for a document not yet configured anywhere.
                        "format": req.allowed_extensions or doc_type.allowed_extensions or '.pdf,.jpg,.jpeg',
                        "isMandatory": bool(req.is_mandatory),
                        "isActive": bool(req.is_enabled),
                        "requiresConsent": bool(doc_type.requires_consent),
                        "isCore": bool(doc_type.is_core),
                        # Deletion is refused once any application has used it.
                        "canDelete": (not doc_type.is_core) and (not document_type_in_use(doc_type)),
                    })
            else:
                # No cycle configured yet. Core documents are ALWAYS listed, so
                # an administrator can see and toggle them before any cycle
                # exists rather than facing an empty configuration screen.
                for dt in DocumentTypes.objects.filter(is_core=1, is_system_generated=0).order_by('doc_type_id'):
                    rule_list.append({
                        "id": dt.doc_type_id,
                        "key": document_slug(dt.doc_type_id),
                        "name": dt.type_name,
                        "format": dt.allowed_extensions or '.pdf,.jpg,.jpeg',
                        "isMandatory": True,
                        "requiresConsent": bool(dt.requires_consent),
                        "isCore": True,
                        "isActive": bool(dt.is_active),
                        "canDelete": False,
                    })

            # The cycle these settings belong to is returned with them, so the
            # dashboard can name it in the confirmation dialog rather than
            # leaving an administrator to assume which cycle they just changed.
            return Response({
                "subDepts": sub_dept_list,
                "docRules": rule_list,
                "cycleId": active_cycle.cycle_id if active_cycle else None,
                "cycleName": cycle_label(active_cycle),
            }, status=status.HTTP_200_OK)
        except Exception as e:
            print("Config GET Error:", str(e))
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @role_required('SYS-ADMIN')
    @transaction.atomic
    def post(self, request):
        try:
            action = request.data.get('action')
            system_user = getattr(getattr(request, 'identity', None), 'user', None)
            # The cycle being configured, sent explicitly by the screen.
            active_cycle = resolve_cycle(request)

            if action == 'add_subdept':
                name = request.data.get('name', '').strip().upper()
                sd, created = SubDepartments.objects.get_or_create(sub_department_name=name, defaults={'is_global_active': 1})
                
                if active_cycle:
                    CycleSubDepartments.objects.get_or_create(cycle=active_cycle, sub_department=sd, defaults={'is_active': 1})
                
                try:
                    with transaction.atomic():
                        SystemAuditLogs.objects.create(
                            actor_user=system_user,
                            role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                            action_type='RULES_UPDATE',
                            target_entity_type='SubDepartment',
                            target_entity_id=sd.pk,
                            new_value=json.dumps({"remarks":
                                (f"Created new Sub-Department unit: {name}" if created
                                 else f"Sub-Department unit already existed: {name}")
                                + (f", made available to {cycle_label(active_cycle)}"
                                   if active_cycle else "")})
                        )
                except Exception as audit_error:
                    # The ledger records who did what. A failed write must not
                    # take the action down with it, but it must not vanish either:
                    # a silent pass here hid a broken audit block for a whole
                    # round of changes.
                    logger.error("AUDIT WRITE FAILED (%s): %s",
                                 type(audit_error).__name__, audit_error)
                
                return Response({"message": "Sub-department added."}, status=status.HTTP_201_CREATED)

            elif action == 'toggle_subdept':
                # Scoped to ONE cycle. This used to flip SubDepartments
                # .is_global_active and then mirror it into the newest active
                # cycle, so switching a unit off for Summer also switched it off
                # for Winter -- invisibly, since the screen showed only one
                # cycle. The global flag now means what its name says: whether
                # the unit exists at all, org-wide.
                # Upper-cased to match how units are stored, so a toggle sent
                # from any client finds the right row.
                name = upper_text((request.data.get('name') or '').strip())
                dept = SubDepartments.objects.filter(sub_department_name=name).first()
                if dept and active_cycle:
                    csd, created = CycleSubDepartments.objects.get_or_create(
                        cycle=active_cycle, sub_department=dept,
                        defaults={'is_active': 0 if dept.is_global_active else 1}
                    )
                    if not created:
                        csd.is_active = 0 if csd.is_active else 1
                        csd.save(update_fields=['is_active'])

                    state = 'Active' if csd.is_active else 'Inactive'
                    try:
                        with transaction.atomic():
                            SystemAuditLogs.objects.create(
                                actor_user=system_user,
                                role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                                action_type='RULES_UPDATE',
                                target_entity_type='SubDepartment',
                                target_entity_id=dept.pk,
                                new_value=json.dumps({"remarks": f"Marked Sub-Department '{name}' as {state} for {cycle_label(active_cycle)}"})
                            )
                    except Exception as audit_error:
                        # The ledger records who did what. A failed write must not
                        # take the action down with it, but it must not vanish either:
                        # a silent pass here hid a broken audit block for a whole
                        # round of changes.
                        logger.error("AUDIT WRITE FAILED (%s): %s",
                                     type(audit_error).__name__, audit_error)
                return Response({"message": "Status toggled."}, status=status.HTTP_200_OK)

            elif action == 'save_rules':
                rules = parse_payload_array(request.data, 'rules', 'docRules')
                kept_doc_type_ids = []

                if active_cycle is None:
                    return Response(
                        {"error": "No cycle selected. Choose the cycle these rules "
                                  "apply to before saving."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # What this cycle looked like BEFORE the save, so the ledger can
                # record what actually changed rather than merely that something
                # did. Read here on the server: the dashboard computes its own
                # diff for the confirmation dialog, but an audit trail must not
                # depend on what a browser chose to report.
                # Keyed in upper case so the comparison holds regardless of how
                # a document's name was capitalised when it entered the
                # catalogue. Without this every rule reads as newly "added".
                previous = {}
                for prev_row in (CycleDocumentRequirements.objects
                                 .filter(cycle=active_cycle)
                                 .select_related('doc_type')):
                    if prev_row.doc_type:
                        previous[prev_row.doc_type.type_name.upper()] = {
                            'mandatory': bool(prev_row.is_mandatory),
                            'enabled': bool(prev_row.is_enabled),
                            'format': prev_row.allowed_extensions,
                        }
                rule_changes = []

                for r in rules:
                    if not r.get('name'):
                        continue
                    doc_name = upper_text(str(r.get('name')).strip())
                    doc_format = r.get('format') or '.pdf,.jpg,.jpeg'
                    is_mandatory = 1 if r.get('isMandatory', True) else 0
                    is_enabled = 1 if r.get('isActive', True) else 0

                    # Matched WITHOUT regard to case. Names are stored in upper
                    # case, but a catalogue seeded before that rule holds entries
                    # like 'AADHAR Card'; an exact match would treat the
                    # uppercased name as a new document and quietly create a
                    # duplicate alongside it, splitting the cycle's requirements
                    # across two rows for the same thing.
                    existing = DocumentTypes.objects.filter(type_name__iexact=doc_name).first()

                    if existing:
                        # The catalogue row is NOT touched. Its name, core flag
                        # and consent flag are genuinely global, but its format
                        # and active flag are only the default for a document not
                        # yet configured anywhere -- writing to them here would
                        # change every other running cycle at the same time.
                        doc_type = existing
                    else:
                        # A brand-new document enters the catalogue with the
                        # settings it was given here as its default.
                        doc_type = DocumentTypes.objects.create(
                            type_name=doc_name,
                            allowed_extensions=doc_format,
                            is_system_generated=0,
                            is_active=1,
                            is_core=0,
                            requires_consent=0,
                        )

                    kept_doc_type_ids.append(doc_type.pk)

                    # Difference against what this cycle held before.
                    was = previous.get(doc_name.upper())
                    if was is None:
                        rule_changes.append(
                            f"added '{doc_name}' ({'mandatory' if is_mandatory else 'optional'}, "
                            f"{'enabled' if is_enabled else 'disabled'})")
                    else:
                        if was['enabled'] != bool(is_enabled):
                            rule_changes.append(
                                f"'{doc_name}' {'enabled' if is_enabled else 'disabled'}")
                        if was['mandatory'] != bool(is_mandatory):
                            rule_changes.append(
                                f"'{doc_name}' now {'mandatory' if is_mandatory else 'optional'}")
                        if (was['format'] or '') != (doc_format or ''):
                            rule_changes.append(
                                f"'{doc_name}' format {was['format'] or 'unset'} -> {doc_format}")

                    # Mandatory, enabled and format are all written per cycle,
                    # and all remain editable while the cycle runs. Applications
                    # already submitted are unaffected: each froze its own copy
                    # of the rules at submission, so a change here reaches only
                    # applications submitted from now on.
                    #
                    # A disabled document keeps its row rather than losing it, so
                    # re-enabling restores the cycle's own mandatory flag and
                    # format instead of silently reverting to a default.
                    obj, created = CycleDocumentRequirements.objects.get_or_create(
                        cycle=active_cycle, doc_type=doc_type,
                        defaults={'is_mandatory': is_mandatory,
                                  'is_enabled': is_enabled,
                                  'allowed_extensions': doc_format}
                    )
                    if not created:
                        obj.is_mandatory = is_mandatory
                        obj.is_enabled = is_enabled
                        obj.allowed_extensions = doc_format
                        obj.save(update_fields=['is_mandatory', 'is_enabled',
                                                'allowed_extensions'])

                # Documents removed from the list entirely stop applying to NEW
                # applications of THIS cycle. Other cycles keep their own rows.
                # The document type and every file already collected against it
                # remain, so submitted applications keep showing exactly what
                # they were asked for.
                if kept_doc_type_ids:
                    dropped = (CycleDocumentRequirements.objects
                               .filter(cycle=active_cycle)
                               .exclude(doc_type_id__in=kept_doc_type_ids)
                               .select_related('doc_type'))
                    for gone in dropped:
                        if gone.doc_type:
                            rule_changes.append(f"removed '{gone.doc_type.type_name}'")
                    dropped.delete()

                # Permanent deletion is only offered for a CUSTOM document that
                # no application has touched. Anything already used is disabled
                # instead, so files are never orphaned and archived records keep
                # their meaning.
                # Core documents are NEVER deleted -- refused here regardless of
                # what the browser sends, because historical applications and the
                # archive assume they can exist.
                for doomed_name in (request.data.get('deleteDocuments') or []):
                    target = DocumentTypes.objects.filter(type_name=str(doomed_name).strip()).first()
                    if not target or target.is_core:
                        continue

                    if document_type_in_use(target):
                        # Already collected against some application. Removed from
                        # THIS cycle only; the type and its files survive, and any
                        # other cycle still using it is untouched. Previously this
                        # set the global is_active flag, which reached every cycle.
                        CycleDocumentRequirements.objects.filter(
                            cycle=active_cycle, doc_type=target
                        ).delete()
                    elif CycleDocumentRequirements.objects.filter(
                            doc_type=target).exclude(cycle=active_cycle).exists():
                        # Unused, but another cycle is configured with it. Drop it
                        # from this cycle and leave the catalogue entry alone.
                        CycleDocumentRequirements.objects.filter(
                            cycle=active_cycle, doc_type=target
                        ).delete()
                    else:
                        # Unused anywhere and belonging to no other cycle: safe to
                        # remove from the catalogue entirely.
                        CycleDocumentRequirements.objects.filter(doc_type=target).delete()
                        target.delete()

                try:
                    with transaction.atomic():
                        SystemAuditLogs.objects.create(
                            actor_user=system_user,
                            role_name=system_user.role.role_name if system_user and system_user.role else 'SYS-ADMIN',
                            action_type='RULES_UPDATE',
                            # Attributed to the CYCLE, and it says which. The
                            # remark used to read "configured globally", which
                            # described the old design and is now actively
                            # misleading: one cycle's rules no longer affect
                            # another's, so an auditor must be able to see which
                            # cycle a change landed on.
                            target_entity_type='Cycle',
                            target_entity_id=active_cycle.pk,
                            new_value=json.dumps({"remarks":
                                f"Document rules updated for {cycle_label(active_cycle)}: "
                                + ("; ".join(rule_changes) if rule_changes else "no changes")
                                + f". {len(kept_doc_type_ids)} document(s) now configured."})
                        )
                except Exception as audit_error:
                    # The ledger records who did what. A failed write must not
                    # take the action down with it, but it must not vanish either:
                    # a silent pass here hid a broken audit block for a whole
                    # round of changes.
                    logger.error("AUDIT WRITE FAILED (%s): %s",
                                 type(audit_error).__name__, audit_error)
                
                return Response({"message": "Rules updated."}, status=status.HTTP_200_OK)

            return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print("Config POST Error:", str(e))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class UniversalExportAPIView(APIView):
    @role_required(*ALL_HR_ROLES)
    def post(self, request):
        try:
            module = request.data.get('module')
            export_format = request.data.get('format')
            item_ids = request.data.get('ids', [])

            if not module or not export_format:
                return Response({"error": "Missing parameters or empty selection."},
                                status=status.HTTP_400_BAD_REQUEST)

            # The ARCHIVE export sends filters rather than a list of records,
            # because the archive is paged and the visible list is one page of
            # 25. Every other module still sends the ids on screen, and for
            # those an empty selection is still nothing to export.
            if module != 'archive' and not item_ids:
                return Response({"error": "Missing parameters or empty selection."},
                                status=status.HTTP_400_BAD_REQUEST)

            data = []
            headers = []

            # --- ARCHIVE EXPORT: WHAT YOU SEE -------------------------------
            # The browser sends the FILTERS that are in force, WHICH columns are
            # on screen and the sort. The records and their values are resolved
            # here, from the archive.
            #
            # It used to send the list of tickets on screen. That worked while
            # the browser held the whole cycle -- but the archive is paged now,
            # so the visible list is 25 records, and an export built from it
            # would have silently produced a 25-row file that only revealed
            # itself as incomplete after somebody had sent it on. Paging is a
            # drawing limit; an export covers everything the filters match, the
            # same rule the two live queues already follow.
            #
            # Re-running the filters here rather than trusting values from the
            # page also means a screen left open for an hour cannot be exported
            # verbatim into a document DMRC may keep as a record.
            if module == 'archive':
                columns = request.data.get('columns') or []
                if not columns:
                    return Response({"error": "No columns specified for export."},
                                    status=status.HTTP_400_BAD_REQUEST)

                archive_filters = request.data.get('filters') or {}
                term = archive_filters.get('term')
                year = archive_filters.get('year')
                if not (term and year):
                    return Response(
                        {"error": "An archived cycle must be selected before exporting."},
                        status=status.HTTP_400_BAD_REQUEST)

                records = archive_filter_queryset(
                    ArchivedApplications.objects.filter(
                        session_term=term, application_year=year),
                    archive_filters)

                # The administrator's sort carried into the file, resolved the
                # same way the screen resolves it -- including blanks sinking to
                # the bottom whichever way a date column is ordered.
                sort_key = archive_filters.get('sortKey') or 'ticket'
                if sort_key not in ARCHIVE_SORT_COLUMNS:
                    sort_key = 'ticket'
                column = ARCHIVE_SORT_COLUMNS[sort_key]
                descending = (archive_filters.get('sortDir') or 'asc').lower() == 'desc'
                if sort_key in ARCHIVE_SORT_NULLS_LAST:
                    order = (F(column).desc(nulls_last=True) if descending
                             else F(column).asc(nulls_last=True))
                    records = records.order_by(order, 'application_code')
                else:
                    records = records.order_by(f"-{column}" if descending else column,
                                               'application_code')

                headers = [c.get('label', c.get('key', '')) for c in columns]
                data = []
                # serialize_archived_row, not the drawer serialiser: the export
                # carries the columns the TABLE shows, and the drawer version
                # would run four extra queries per record to build documents and
                # a timeline that no column displays.
                for rec in records.iterator(chunk_size=500):
                    view = serialize_archived_row(rec)
                    row = []
                    for col in columns:
                        key = col.get('key')
                        value = view.get(key, '')
                        if isinstance(value, bool):
                            value = 'Yes' if value else 'No'
                        elif value is None:
                            value = ''
                        row.append(str(value))
                    data.append(row)

            elif module in ('queue', 'college'):
                # WHAT YOU SEE IS WHAT YOU GET, in both senses.
                #
                # ORDER: item_ids arrives in the order shown on screen, so the
                # administrator's sort and filters survive into the file. The
                # queue export used to iterate the queryset instead, which
                # returns rows in whatever order the database chose.
                #
                # COLUMNS: the two pipelines are exported with the columns each
                # SHOWS. A college referral has no employee referrer and its
                # college and university are the whole point of the record, so
                # giving it the queue's columns would produce a sheet that is
                # half empty and missing the useful part.
                indexed = {a.application_code: a for a in
                           Applications.objects
                           .select_related('student', 'department', 'cycle')
                           .filter(application_code__in=item_ids)}
                ordered = [indexed[code] for code in item_ids if code in indexed]

                # The joining-date column is HEADED as the screen heads it --
                # 'Requested DOJ', 'Allotted DOJ', 'Actual DOJ' or the generic
                # 'Date of Joining' -- and its values follow the same status rule
                # the dashboard uses. The two were previously out of step: the
                # file worked its own actual-then-allotted-then-requested
                # fallback, so a rejected candidate who had once been allotted a
                # date showed one date on screen and a different one in the file.
                #
                # The label comes from the browser because it is a LABEL: taking
                # it from the screen is what guarantees the file cannot disagree
                # with it. It is checked against the four permitted headings, so
                # nothing arbitrary can be written into a document DMRC files.
                context = request.data.get('context') or {}
                doj_header = context.get('dojHeader')
                if doj_header not in ('Date of Joining', 'Requested DOJ',
                                      'Allotted DOJ', 'Actual DOJ'):
                    doj_header = 'Date of Joining'

                if module == 'college':
                    headers = ['Ticket ID', 'Candidate Name', 'College / Institution',
                               'University', 'Course', 'Branch', 'Department',
                               'Status', 'Date of Joining', 'Cycle']
                else:
                    headers = ['Ticket ID', 'Candidate Name', 'Department', 'Status',
                               'Ward', 'Submitted', doj_header, 'Referrer',
                               'Referrer Type', 'Cycle']

                # THE SAME STATUS RULE THE DASHBOARD USES (getDisplayDojValue).
                # Before approval the only committed date is the one requested;
                # once a date is allotted that is the operative one; once the
                # candidate has arrived, the date they actually arrived on.
                DOJ_ALLOTTED_STATUSES = ('Approved', 'Scheduled', 'Pending Offer Letter',
                                         'Fix Joining', 'Offer Ready',
                                         'Pending Offer Re-Approval', 'Pending Arrival',
                                         'Ready for Merge')
                DOJ_ACTUAL_STATUSES = ('Joined', 'Fix Clearance', 'Pending Certificate',
                                       'Pending Dispatch', 'Completed')

                for app in ordered:
                    joining = JoiningDetails.objects.filter(application=app).first()

                    if app.status in DOJ_ACTUAL_STATUSES:
                        field = 'actual_date_of_joining'
                    elif app.status in DOJ_ALLOTTED_STATUSES:
                        field = 'allotted_date_of_joining'
                    else:
                        field = 'requested_doj'

                    doj = ""
                    if joining and getattr(joining, field, None):
                        doj = safe_extract_time(joining, field, date_only=True)
                    elif joining and field == 'allotted_date_of_joining' and getattr(joining, 'requested_doj', None):
                        # A date is allotted moments after approval. Until then
                        # the requested date stands in, exactly as the server
                        # does when it builds the queue.
                        doj = safe_extract_time(joining, 'requested_doj', date_only=True)
                    if not doj:
                        doj = "Pending"

                    submitted = safe_extract_time(app, 'created_at', date_only=True) or "—"

                    student_salutation = getattr(app.student, 'salutation', '')
                    student_name = getattr(app.student, 'full_name', 'Unknown')
                    full_candidate_name = f"{student_salutation} {student_name}".strip() if student_salutation else student_name

                    cycle = app.cycle
                    cycle_label = (f"{cycle.session_term} {cycle.application_year}"
                                   if cycle else "N/A")
                    department = app.department.department_name if app.department else "N/A"

                    if module == 'college':
                        academic = AcademicDetails.objects.filter(application=app).first()
                        data.append([
                            app.application_code,
                            full_candidate_name,
                            getattr(academic, 'college_name', '') or "Not recorded",
                            getattr(academic, 'university_name', '') or "Not recorded",
                            getattr(academic, 'degree_program', '') or "Not recorded",
                            getattr(academic, 'branch_name', '') or "Not recorded",
                            department,
                            app.status,
                            doj,
                            cycle_label,
                        ])
                    else:
                        referrer = getattr(app, 'referrer_employee', None)
                        data.append([
                            app.application_code,
                            full_candidate_name,
                            department,
                            app.status,
                            # Spelled out rather than TRUE/FALSE: a ward is over
                            # and above the cycle's ceiling, so anyone reading the
                            # sheet needs to see it at a glance.
                            # is_ward on Applications. is_employee_ward is the
                            # ARCHIVE's name for the same fact -- using it here
                            # raised AttributeError and failed the whole export.
                            'Yes' if app.is_ward else 'No',
                            submitted,
                            doj,
                            getattr(referrer, 'full_name', '') or "—",
                            app.referral_source,
                            cycle_label,
                        ])

            elif module == 'audit':
                # WHAT YOU SEE IS WHAT YOU GET.
                #
                # Two things make that true, and both were missing.
                #
                # ORDER: item_ids arrives in the order shown on screen, so any
                # sort or filter the administrator applied survives into the
                # file. This used to re-sort by created_at and discard it.
                #
                # CONTENT: every cell comes from serialize_audit_row(), the same
                # function the ledger screen uses. The export had its own copy
                # that read only a 'remarks' key, so a downloaded ledger showed
                # blank cells exactly where the screen showed the most useful
                # sentences -- who downloaded a letter, who approved a signature.
                logs = {log.log_id: log for log in
                        SystemAuditLogs.objects
                        .select_related('actor_user', 'actor_user__employee')
                        .filter(log_id__in=item_ids)}

                headers = ['Timestamp', 'Actor', 'Role', 'Action Category',
                           'Target Entity', 'Forensic Details']

                for log_id in item_ids:
                    log = logs.get(log_id)
                    if log is None:
                        continue
                    row = serialize_audit_row(log)
                    data.append([
                        row['timestamp'],
                        row['actor'],
                        row['role'],
                        row['action'],
                        row['ticketId'],
                        row['remark'],
                    ])

            if not data:
                return Response({"error": "No matching records found in the database."}, status=status.HTTP_404_NOT_FOUND)

            # --- THE EXPORT IS RECORDED -------------------------------------
            #
            # Every export of every module, including the audit ledger itself.
            # Exporting the ledger writes a line into the ledger, which is the
            # correct behaviour: taking a copy of the record of who did what is
            # itself something a reviewer needs to be able to see.
            #
            # Written HERE, after the rows have been assembled and before the
            # file is handed over, so the count in the ledger is the number of
            # records the file actually contains. Recording it earlier would log
            # exports that then failed to build.
            #
            # _audit never raises: a ledger failure must not cost the officer
            # their file.
            export_context = request.data.get('context') or {}
            module_label = {
                'queue': 'Verification Queue',
                'college': 'College Referrals',
                'archive': 'Archives',
                'audit': 'Audit Ledger',
            }.get(module, module.title())

            _audit(
                request.identity.user,
                'REPORT_EXPORTED',
                'Export',
                # This action is about a SET of records rather than one entity,
                # so there is no row to point at. The column cannot be null, and
                # the useful identifiers are in the payload below.
                0,
                new_value={
                    'module': module,
                    'moduleLabel': module_label,
                    'format': export_format,
                    'recordCount': len(data),
                    'tab': export_context.get('tab') or '',
                    'filters': export_context.get('filters') or 'No filters',
                    'sort': export_context.get('sort') or '',
                    'columns': headers,
                }
            )

            if export_format == 'excel':
                df = pd.DataFrame(data, columns=headers)
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name=module.capitalize())
                
                excel_buffer.seek(0)
                response = HttpResponse(excel_buffer.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                response['Content-Disposition'] = f'attachment; filename="DMRC_{module.capitalize()}_Export.xlsx"'
                return response

            elif export_format == 'pdf':
                pdf_buffer = io.BytesIO()
                # A4, not US Letter. Every other document this portal produces is A4,
                # which is the standard for Indian government correspondence, and
                # an export printed on a different size to the letters beside it
                # in the same file is a small but permanent annoyance.
                doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(A4))
                elements = []
                styles = getSampleStyleSheet()
                
                elements.append(Paragraph(f"DMRC {module.capitalize()} Export Report", styles['Title']))
                elements.append(Paragraph(f"Generated on: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
                elements.append(Paragraph(" ", styles['Normal']))
                
                table_data = [headers] + data
                wrapped_data = []
                for row in table_data:
                    wrapped_row = [Paragraph(str(cell), styles['Normal']) if isinstance(cell, str) and len(str(cell)) > 30 else str(cell) for cell in row]
                    wrapped_data.append(wrapped_row)

                t = Table(wrapped_data)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0A3284')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('TOPPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
                    ('VALIGN',(0,0),(-1,-1),'TOP'),
                ]))
                
                elements.append(t)
                doc.build(elements)
                
                pdf_buffer.seek(0)
                response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="DMRC_{module.capitalize()}_Export.pdf"'
                return response

            return Response({"error": "Invalid export format requested."}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)