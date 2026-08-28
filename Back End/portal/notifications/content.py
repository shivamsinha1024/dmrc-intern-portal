"""Turning an application into the subject and body of one email.

HR'S WORDING IS NOT IN THIS FILE. It is in portal/templates/notifications/, one
subject file and one body file per type, and this module only supplies the
values that fill the square brackets. Anyone editing the copy edits a template;
nobody edits Python to change a sentence.

WHEN THE TEXT IS BUILT

The body is composed HERE, at queue time, and stored in notifications.message.
That column is NOT NULL and it is what HR reads when investigating, so the row
has to carry the words that were actually sent.

Attachments are the opposite -- they are resolved at SEND time, in the
management command, because a file path captured at queue time can point at a
document that has since been superseded and quarantined.

MISSING DATA IS A FAILURE, NOT A BLANK

Every type declares the context keys it cannot be sent without. A Joining
Schedule with no allotted date of joining would otherwise render as
"Reporting Date: " followed by nothing, which is worse than not sending at all.
So the notification is recorded as Failed with a reason instead.
"""

from django.template.loader import render_to_string

from .types import (
    ACADEMY_SCHEDULE,
    APPLICATION_APPROVED,
    APPLICATION_REJECTED,
    APPLICATION_SUBMITTED,
    COLLEGE_REFERRAL,
    COMPLETION_CERTIFICATE_ISSUED,
    JOINING_SCHEDULE,
    NO_SHOW,
    RETURNED_FOR_CORRECTION,
    TEMPLATE_SLUGS,
)

#: HR asked for DD-MM-YYYY everywhere. Matches safe_extract_time() in views.py.
DATE_FORMAT = '%d-%m-%Y'

#: Used when referrer_employee is absent. The greeting is computed whole rather
#: than as a name slotted into "Dear Ms/Shri ___", because the fallback is a
#: different greeting, not a different name. Rendering "Dear Ms/Shri ," or
#: "Dear Ms/Shri None," is not an option.
NEUTRAL_GREETING = 'Dear Sir/Madam,'


#: Context keys that must be present and non-empty before a type may be sent.
#: A key not listed here may legitimately be blank.
REQUIRED_CONTEXT = {
    APPLICATION_SUBMITTED: ('candidate_display_name', 'application_code'),
    APPLICATION_APPROVED: ('candidate_display_name', 'application_code'),
    APPLICATION_REJECTED: ('candidate_display_name', 'application_code'),
    RETURNED_FOR_CORRECTION: ('application_code', 'correction_remarks'),
    NO_SHOW: ('candidate_display_name', 'application_code', 'joining_date'),
    JOINING_SCHEDULE: ('candidate_display_name', 'joining_date'),
    ACADEMY_SCHEDULE: ('candidate_display_name', 'academy_date'),
    COMPLETION_CERTIFICATE_ISSUED: ('candidate_display_name',),
    COLLEGE_REFERRAL: ('candidate_display_name', 'joining_date'),
}

#: A one-line note stored in notifications.message when the body could not be
#: composed at all. The row is Failed and will never be sent; failure_reason
#: carries the explanation. Deliberately bracketed and unmistakable, so nobody
#: reading the table mistakes it for something a candidate received.
UNCOMPOSED_MESSAGE = '[NOT COMPOSED - see failure_reason]'


def build_context(application):
    """Everything the nine templates can refer to, for one application."""
    student = application.student

    return {
        'referrer_greeting': _referrer_greeting(application),
        'candidate_display_name': _candidate_display_name(student),
        'application_code': (application.application_code or '').strip(),
        'correction_remarks': (application.form_correction_remarks or '').strip(),
        'joining_date': _format_date(_joining_field(application, 'allotted_date_of_joining')),
        'academy_date': _format_date(_joining_field(application, 'dmra_session_date')),
    }


def missing_context(notification_type, context):
    """Return the required keys that are empty, in template order."""
    return [
        key for key in REQUIRED_CONTEXT.get(notification_type, ())
        if not (context.get(key) or '').strip()
    ]


def render_subject(notification_type, context):
    """The subject line. Trimmed to one line and to the column width.

    notifications.subject is VARCHAR(150). None of HR's approved subjects
    contains a placeholder, so none of them can grow -- but a template edited
    later might, and a subject that overflows would either be truncated by MySQL
    or reject the whole INSERT depending on server mode. Trimming here makes the
    behaviour the same either way.
    """
    slug = TEMPLATE_SLUGS[notification_type]
    rendered = render_to_string(f'notifications/{slug}.subject.txt', context)
    # A subject cannot contain a newline: a header break is how header injection
    # works, and the template file ends with one regardless.
    single_line = ' '.join(rendered.split())
    return single_line[:150]


def render_body(notification_type, context):
    """The plain-text body, exactly as it will be sent."""
    slug = TEMPLATE_SLUGS[notification_type]
    rendered = render_to_string(f'notifications/{slug}.body.txt', context)
    return rendered.strip() + '\n'


# --- internals ---------------------------------------------------------------

def _referrer_greeting(application):
    """"Dear Ms/Shri <name>," or the neutral fallback.

    referrer_employee is NULL only on institutional records today, and those
    never produce a referrer-facing notification -- so in principle the fallback
    is unreachable. It exists because that is an invariant of the current code,
    not of the database, and an email beginning "Dear Ms/Shri None," is not an
    acceptable way to find out it has changed.
    """
    employee = getattr(application, 'referrer_employee', None)
    name = (getattr(employee, 'full_name', '') or '').strip() if employee else ''
    if not name:
        return NEUTRAL_GREETING
    return f'Dear Ms/Shri {name},'


def _candidate_display_name(student):
    """The candidate's name with their salutation, if they gave one.

    students.salutation is nullable -- an institutional record starts
    half-collected -- so the gap closes silently rather than rendering
    "Dear  Ravi Kumar," with a double space.
    """
    if student is None:
        return ''
    salutation = (student.salutation or '').strip()
    full_name = (student.full_name or '').strip()
    return f'{salutation} {full_name}'.strip() if salutation else full_name


def _joining_field(application, field_name):
    """Read a field off the JoiningDetails row, if there is one.

    JoiningDetails is a OneToOne on Applications, so it may not exist yet. That
    is not an error here -- it becomes one only if the type in question requires
    the value, which REQUIRED_CONTEXT decides.
    """
    try:
        joining = application.joiningdetails
    except Exception:
        return None
    return getattr(joining, field_name, None)


def _format_date(value):
    if not value:
        return ''
    return value.strftime(DATE_FORMAT)
