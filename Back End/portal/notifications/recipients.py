"""WHO receives a notification. This is the only place that decides.

The rule depends on BOTH the notification type and the referral source, which is
exactly why it lives in one function instead of being repeated at each call site
in views.py. A call site says WHAT happened; this module says who hears about it.

    referral_source = 'Institutional'   a college referral
        Every notification goes to the CANDIDATE. There is no employee referrer
        on these records -- referrer_employee is NULL by design, and the schema
        comment on that column says so.

        The five referrer-facing types cannot legitimately occur here: their
        approved wording is addressed to a referrer and talks ABOUT the
        candidate in the third person ("ask the candidate to check their
        email"). Sending that text to the candidate would be nonsense, so it is
        treated as an error rather than rerouted.

    referral_source = 'Employee'        an ordinary employee referral
        Referrer-facing types go to applications.referrer_notification_email.
        Candidate-facing types go to students.personal_email.

TWO ADDRESS COLUMNS ONLY.

    applications.referrer_notification_email
        Typed by the referring employee on the Phase-1 form. The FORM makes it
        mandatory; the COLUMN is nullable. If it is ever absent on a record that
        needs it, the notification is recorded as Failed with a reason. It is
        never skipped silently.

    students.personal_email
        NOT NULL. Checked anyway -- a NOT NULL column still accepts an empty
        string in MySQL, and an empty To address is a send failure, not a crash.

employees.official_email is NEVER used for notifications. It is optional in the
DMRC directory and may be absent, and the addresses collected on the Phase-1
form are the ones the referrer actually asked us to write to.
"""

from collections import namedtuple

from .types import (
    ACADEMY_SCHEDULE,
    ACTIVE_TYPES,
    APPLICATION_APPROVED,
    APPLICATION_REJECTED,
    APPLICATION_SUBMITTED,
    COLLEGE_REFERRAL,
    COMPLETION_CERTIFICATE_ISSUED,
    JOINING_SCHEDULE,
    NO_SHOW,
    RETURNED_FOR_CORRECTION,
)

#: The literal stored in applications.referral_source for a college referral.
#: The column is ENUM('Employee', 'Institutional'); the model says max_length=13
#: only because that is the length of the longer value.
INSTITUTIONAL = 'Institutional'
EMPLOYEE = 'Employee'


REFERRER_TYPES = frozenset({
    APPLICATION_SUBMITTED,
    APPLICATION_APPROVED,
    APPLICATION_REJECTED,
    RETURNED_FOR_CORRECTION,
    NO_SHOW,
})

CANDIDATE_TYPES = frozenset({
    JOINING_SCHEDULE,
    ACADEMY_SCHEDULE,
    COMPLETION_CERTIFICATE_ISSUED,
    COLLEGE_REFERRAL,
})

# A type belongs to exactly one group. Checked at import time so a future edit
# that adds a type to one set and forgets the other fails on startup rather than
# at the moment HR clicks a button.
assert REFERRER_TYPES | CANDIDATE_TYPES == ACTIVE_TYPES, (
    'Every active notification type must be routed to exactly one recipient '
    'group. Update REFERRER_TYPES or CANDIDATE_TYPES in recipients.py.'
)
assert not (REFERRER_TYPES & CANDIDATE_TYPES)


class NotificationRoutingError(Exception):
    """The requested combination of type and application cannot be routed.

    This is a PROGRAMMING error, not a data problem -- a call site asking for a
    referrer-facing notification on an application that has no referrer. It is
    raised here so the rule stays strict, and caught in queue.py so a mistake in
    one view cannot roll back the HR action that triggered it.
    """


#: The outcome of routing.
#:
#:   email == a non-empty address, failure_reason is None   -> queue as Pending
#:   email == '', failure_reason explains why               -> record as Failed
#:
#: The empty string rather than None because notifications.recipient_email is
#: VARCHAR(150) NOT NULL. The row must still be written: an address we could not
#: find is precisely the thing that has to leave a trace.
Recipient = namedtuple('Recipient', ('email', 'failure_reason'))


def is_institutional(application):
    """True if this application came from a college rather than an employee."""
    return (application.referral_source or '').strip() == INSTITUTIONAL


def resolve_recipient(application, notification_type):
    """Return the Recipient for this application and notification type.

    Raises NotificationRoutingError for a combination that cannot occur.
    """
    if notification_type not in ACTIVE_TYPES:
        raise NotificationRoutingError(
            f'{notification_type!r} is not one of the nine notification types '
            f'this portal sends. See portal/notifications/types.py.'
        )

    if is_institutional(application):
        if notification_type in REFERRER_TYPES:
            raise NotificationRoutingError(
                f'{notification_type!r} is addressed to a referring employee, '
                f'but application {application.application_id} has '
                f"referral_source='Institutional' and therefore no referrer. "
                f'A college referral cannot produce this notification.'
            )
        return _candidate_address(application)

    if notification_type in REFERRER_TYPES:
        return _referrer_address(application)

    return _candidate_address(application)


def _referrer_address(application):
    # A referrer who has LEFT DMRC is not written to. Confirmed with HR.
    #
    # employees.is_active is FALSE for a leaver, and identity resolution already
    # honours it, so they cannot use either portal. But the address below is a
    # string stored on the application, independent of the employees table, so
    # nothing else would consult their status.
    #
    # Recorded as Failed rather than skipped, and the distinction matters: a
    # departed referrer means NOBODY is watching that application. The candidate
    # they referred is still in the pipeline with no one following it up, and a
    # silent skip would leave that invisible. The row is the only thing saying so.
    #
    # Employees.is_active is BooleanField(default=True) -- models.py line 531 --
    # so it can only hold TRUE or FALSE. NULL is nonetheless read as ACTIVE
    # below, because the other five is_active columns in models.py are NULLABLE
    # IntegerFields and this one could one day be changed to match. A plain
    # `not employee.is_active` would then treat NULL as a departure and silently
    # stop emailing a referrer who is still here -- and a referrer who never
    # hears about their own candidate is a worse failure than a leaver getting
    # one last message.
    #
    # Employees.is_active, NOT Users.is_active (line 699). Those are separate
    # flags: a referrer could have a deactivated portal login while still
    # working at DMRC. HR's decision was about people who have LEFT.
    employee = getattr(application, 'referrer_employee', None)
    is_active = getattr(employee, 'is_active', None) if employee else None
    if employee is not None and is_active is not None and not is_active:
        return Recipient(
            email='',
            failure_reason=(
                'The referring employee has left DMRC. '
                f'{getattr(employee, "full_name", None) or "The referrer"} is '
                f'inactive in the employee directory, so application '
                f'{application.application_id} '
                f'({application.application_code or "no code"}) has nobody to '
                'notify. The candidate is still in the pipeline and needs '
                'reassigning or following up by hand.'
            ),
        )

    address = (application.referrer_notification_email or '').strip()
    if not address:
        return Recipient(
            email='',
            failure_reason=(
                'No referrer address on the application. '
                'applications.referrer_notification_email is empty for '
                f'application {application.application_id} '
                f'({application.application_code or "no code"}). The Phase-1 '
                'form requires it, so this record predates that rule or was '
                'created another way. Fill the column and re-trigger the '
                'action to send this notification.'
            ),
        )
    return Recipient(email=address, failure_reason=None)


def _candidate_address(application):
    student = application.student
    address = (student.personal_email or '').strip() if student else ''
    if not address:
        return Recipient(
            email='',
            failure_reason=(
                'No candidate address. students.personal_email is empty for '
                f'application {application.application_id} '
                f'({application.application_code or "no code"}). The column is '
                'NOT NULL, so this is an empty string rather than a missing '
                'row. Correct the student record and re-trigger the action.'
            ),
        )
    return Recipient(email=address, failure_reason=None)