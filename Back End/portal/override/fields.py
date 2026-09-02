"""
Editable-field allowlist for Admin Mode overrides.

Back End/portal/override/fields.py

PURE MODULE. No model imports, no database access, no settings -- the same
rule documents/staleness.py and documents/formatting.py already follow.
Everything here is either a declaration or a check on a single value.
Anything requiring a query (does this department_id exist?) is marked 'fk'
below and is deliberately left to the caller.

WHY AN ALLOWLIST AND NOT A DENYLIST
A denylist fails open. Add a column to `students` next year and a denylist
silently makes it admin-editable; this list silently does not. For the most
dangerous endpoint in the portal, failing closed is the only acceptable
direction.

KEY FORMAT
Keys are 'table.field' strings spelled identically to the keys in
documents/staleness.py FIELD_MAP, so a changes dict built from this module
feeds straight into staleness.relevant_changes_by_kind() with no
translation step in between. If you rename a key here, rename it there.

NOT LISTED, AND DELIBERATELY SO
    referrer_employee_id, referrer_notification_email, referral_source
        Who referred this candidate is not a clerical detail; changing it
        rewrites provenance.
    application_code, dmrc_reference_code
        The ticket number is quoted in emails already sent and printed on
        documents already issued.
    cycle_id
        Drives the ticket series and the list of allowed joining dates.
        Moving an application between cycles is a different feature with
        different capacity consequences.
    applications.project_report_title
        Belongs to the clearance workflow, which is where it is collected
        and where its verification tick-box lives. It remains in
        staleness.py FIELD_MAP: a clearance-workflow correction to the
        title genuinely does outdate an issued certificate. It is simply
        not reachable from Admin Mode.
    joining_details.date_of_completion
        The internship END DATE, excluded by requirement. Frozen at
        scheduling and printed on the certificate.
    joining_details.allotted_date_of_joining, dmra_session_date
        Scheduling fields owned by the scheduling workflow, which enforces
        the one-reschedule rule. An override here would bypass the counter.
    everything in `documents`
        Files are never edited, only superseded or quarantined.
"""

import datetime
import decimal
import re


class OverrideFieldError(ValueError):
    """A submitted value is not acceptable for the field it was sent for.

    Carries the field key so the endpoint can return a per-field error map
    rather than one opaque string, and so a bad value in field seven does
    not discard the six good ones the admin typed before it.
    """

    def __init__(self, field_key, message):
        self.field_key = field_key
        self.message = message
        super().__init__('%s: %s' % (field_key, message))


# Every constraint below mirrors one that DB/Intern_Portal.sql already
# enforces. They are repeated here so a mistyped value comes back as a
# readable field error instead of an IntegrityError raised halfway through
# a transaction, with the admin left guessing which of their edits was the
# bad one.
FIELDS = {
    # -- students -----------------------------------------------------------
    'students.salutation': {
        'label': 'Salutation', 'kind': 'text', 'max_length': 10},
    'students.full_name': {
        'label': 'Full name', 'kind': 'text', 'max_length': 150,
        'required': True},
    'students.fathers_name': {
        'label': "Father's name", 'kind': 'text', 'max_length': 150},
    'students.gender': {
        'label': 'Gender', 'kind': 'enum',
        'choices': ('Male', 'Female', 'Other')},
    'students.date_of_birth': {
        'label': 'Date of birth', 'kind': 'date'},
    'students.mobile_number': {
        'label': 'Mobile number', 'kind': 'text', 'max_length': 20},
    'students.personal_email': {
        'label': 'Personal email', 'kind': 'email', 'max_length': 150,
        'required': True},
    'students.aadhaar_number': {
        'label': 'Aadhaar number', 'kind': 'aadhaar', 'max_length': 12},
    'students.permanent_address': {
        'label': 'Permanent address', 'kind': 'text'},
    'students.emergency_contact_name': {
        'label': 'Emergency contact name', 'kind': 'text', 'max_length': 150},
    'students.emergency_contact_mobile': {
        'label': 'Emergency contact mobile', 'kind': 'text', 'max_length': 20},

    # -- academic_details ---------------------------------------------------
    'academic_details.university_name': {
        'label': 'University', 'kind': 'text', 'max_length': 200},
    'academic_details.college_name': {
        'label': 'College', 'kind': 'text', 'max_length': 200,
        'required': True},
    'academic_details.degree_program': {
        'label': 'Degree programme', 'kind': 'text', 'max_length': 100},
    'academic_details.branch_name': {
        'label': 'Branch', 'kind': 'text', 'max_length': 100},
    'academic_details.current_semester': {
        'label': 'Semester', 'kind': 'text', 'max_length': 20},
    'academic_details.grading_system': {
        'label': 'Grading system', 'kind': 'enum',
        'choices': ('CGPA', 'Percentage')},
    'academic_details.current_score': {
        'label': 'Score', 'kind': 'decimal'},

    # -- applications -------------------------------------------------------
    # BY NAME, not by id. The dashboard's department control is a select of
    # department NAMES -- no screen in the portal has ever held a
    # department_id -- so the endpoint resolves the name against the
    # departments table rather than making the frontend fetch a lookup it
    # does not otherwise need.
    'applications.department': {
        'label': 'Department', 'kind': 'fk_name', 'table': 'departments'},
    'applications.duration_weeks': {
        'label': 'Duration (weeks)', 'kind': 'int', 'allowed': (4, 6, 8)},
    # Ward applications supersede the capacity matrix: they are admitted
    # regardless of the department's remaining seats and do not consume one.
    # So correcting this flag moves a seat in or out of the count, which is
    # why it carries the same status lock department does.
    'applications.is_ward': {
        'label': 'Ward application', 'kind': 'bool'},

    # -- joining_details ----------------------------------------------------
    'joining_details.actual_date_of_joining': {
        'label': 'Actual date of joining', 'kind': 'date'},
    'joining_details.allotted_sub_department_id': {
        'label': 'Sub-department', 'kind': 'fk', 'table': 'sub_departments'},
}


TABLE_ORDER = ('students', 'academic_details', 'applications',
               'joining_details')


# FIELDS THAT STOP BEING EDITABLE PART-WAY THROUGH THE PIPELINE
#
# Department feeds cycle_department_capacities. Moving an application
# between departments consumes a seat in the new one and releases a seat in
# the old, which is a defensible correction while the candidate is still on
# paper and an untrue one once they have physically joined and been posted
# to a sub-department under that department's head.
#
# The lock therefore covers Joined and EVERYTHING AFTER IT, not Joined
# alone: an application at Pending Dispatch has joined just as firmly as
# one at Joined, and a lock naming a single status would quietly lapse the
# moment the record moved on.
#
# 'Rejected' is deliberately absent. A rejected application holds no seat
# and is posted nowhere, so there is nothing for a department change to
# falsify. A rollback to Submitted also lifts the lock by definition, which
# is the intended escape hatch: an admin who genuinely must re-department a
# joined intern rolls the application back first, and that rollback is
# itself audited and destructive enough to be a deliberate act.
_POST_JOINING_STATUSES = frozenset({
    'Joined', 'Pending Certificate', 'Pending Dispatch', 'Completed',
})

FIELD_STATUS_LOCKS = {
    'applications.department': _POST_JOINING_STATUSES,
    # is_ward decides whether this application occupies a seat at all, so it
    # falsifies the same count department does and is locked for the same
    # reason. Remove this line if ward corrections should stay available
    # after joining.
    'applications.is_ward': _POST_JOINING_STATUSES,
}


_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_AADHAAR_RE = re.compile(r'^\d{12}$')


def split_key(field_key):
    """'students.full_name' -> ('students', 'full_name')."""
    table, _, field = field_key.partition('.')
    return table, field


def is_editable(field_key):
    """True if this field may be corrected by an administrator at all."""
    return field_key in FIELDS


def label_for(field_key):
    """Human-readable name, for error text and the audit ledger."""
    spec = FIELDS.get(field_key)
    return spec['label'] if spec else field_key


def locked_by_status(field_key, status):
    """True if this field cannot be edited while the application sits at
    this status. Pure lookup: the caller supplies the status it already
    read.
    """
    locked = FIELD_STATUS_LOCKS.get(field_key)
    return bool(locked) and status in locked


def normalise(field_key, raw):
    """Validate and convert one submitted value.

    Returns the value ready to assign to the model attribute. Raises
    OverrideFieldError with a message fit to show an admin.

    An empty string, a string of spaces, and None all mean CLEAR THIS FIELD
    and all normalise to None, except where the column is NOT NULL, in
    which case clearing is refused. Distinguishing "left blank" from
    "explicitly emptied" is the caller's job: only send keys the admin
    actually touched.
    """
    spec = FIELDS.get(field_key)
    if spec is None:
        # Should be unreachable: the endpoint rejects unknown keys before
        # reaching here. Kept as a guard so a future caller cannot smuggle
        # an arbitrary column through by calling normalise() directly.
        raise OverrideFieldError(field_key, 'This field cannot be edited.')

    if isinstance(raw, str):
        raw = raw.strip()

    # A False checkbox is a VALUE, not a blank. Without this, unticking Ward
    # would fall into the clear-the-field branch below and write NULL.
    if spec['kind'] == 'bool' and isinstance(raw, bool):
        return 1 if raw else 0

    if raw is None or raw == '':
        if spec.get('required'):
            raise OverrideFieldError(field_key, 'This field cannot be blank.')
        return None

    kind = spec['kind']

    if kind in ('text', 'email', 'aadhaar'):
        value = str(raw)
        max_length = spec.get('max_length')
        if max_length and len(value) > max_length:
            raise OverrideFieldError(
                field_key, 'Must be %d characters or fewer.' % max_length)
        if kind == 'email' and not _EMAIL_RE.match(value):
            raise OverrideFieldError(field_key, 'Not a valid email address.')
        if kind == 'aadhaar' and not _AADHAAR_RE.match(value):
            raise OverrideFieldError(field_key, 'Must be exactly 12 digits.')
        return value

    if kind == 'enum':
        value = str(raw)
        if value not in spec['choices']:
            raise OverrideFieldError(
                field_key,
                'Must be one of: %s.' % ', '.join(spec['choices']))
        return value

    if kind == 'date':
        if isinstance(raw, datetime.datetime):
            return raw.date()
        if isinstance(raw, datetime.date):
            return raw
        try:
            return datetime.datetime.strptime(str(raw), '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise OverrideFieldError(
                field_key, 'Must be a date as YYYY-MM-DD.')

    if kind == 'int':
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise OverrideFieldError(field_key, 'Must be a whole number.')
        allowed = spec.get('allowed')
        if allowed and value not in allowed:
            # chk_app_duration in the schema refuses anything else, and it
            # refuses it with an IntegrityError rolling back the whole
            # transaction. Catch it here instead.
            raise OverrideFieldError(
                field_key,
                'Must be one of: %s.' % ', '.join(str(a) for a in allowed))
        return value

    if kind == 'decimal':
        try:
            value = decimal.Decimal(str(raw))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise OverrideFieldError(field_key, 'Must be a number.')
        # DECIMAL(5,2): at most three digits before the point.
        if value < 0 or value >= decimal.Decimal('1000'):
            raise OverrideFieldError(field_key, 'Out of range.')
        return value.quantize(decimal.Decimal('0.01'))

    if kind == 'bool':
        # A checkbox sends a real boolean; a form post sends a string. The
        # column is a TINYINT, so both end up as 1 or 0.
        if isinstance(raw, bool):
            return 1 if raw else 0
        text = str(raw).strip().lower()
        if text in ('true', '1', 'yes', 'on'):
            return 1
        if text in ('false', '0', 'no', 'off'):
            return 0
        raise OverrideFieldError(field_key, 'Must be true or false.')

    if kind == 'fk_name':
        # Returns the NAME. The caller resolves it to a row, because this
        # module holds no queries.
        return str(raw)

    if kind == 'fk':
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise OverrideFieldError(field_key, 'Not a valid selection.')

    raise OverrideFieldError(field_key, 'Unsupported field type.')


def check_score_against_scale(score, grading_system,
                              field_key='academic_details.current_score'):
    """Cross-field check, run AFTER the whole patch is merged.

    A CGPA of 87 and a percentage of 9.2 are both nonsense, but which one
    applies depends on grading_system -- which the SAME override may be
    changing in the same request. Checking it inside normalise() would test
    the new score against the OLD scale and reject a correction that fixes
    both together, which is precisely the correction an admin is most
    likely to be making.

    The database has no opinion here: DECIMAL(5,2) accepts both.
    """
    if score is None or grading_system is None:
        return

    ceiling = (decimal.Decimal('10') if grading_system == 'CGPA'
               else decimal.Decimal('100'))
    if decimal.Decimal(str(score)) > ceiling:
        raise OverrideFieldError(
            field_key,
            'A %s score cannot exceed %s.' % (grading_system, ceiling))