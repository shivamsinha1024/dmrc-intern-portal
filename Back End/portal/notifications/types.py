"""The notification types this portal actually sends.

The `notifications.notification_type` column is an ENUM of fifteen values. Nine
are in use; the other six are catalogue entries reserved for later. Only the
nine appear here, so a typo at a call site fails immediately rather than
producing a row the database rejects at INSERT time.

DO NOT add a name here that is not already in the ENUM. And when a new type is
eventually needed, APPEND it to the ENUM in DB/Intern_Portal.sql -- never insert
it mid-list. MySQL stores an ENUM as a number counting from the left, so an
insertion silently re-labels every row already stored.
"""

# --- Sent to the referring employee -----------------------------------------
APPLICATION_SUBMITTED = 'Application Submitted'
APPLICATION_APPROVED = 'Application Approved'
APPLICATION_REJECTED = 'Application Rejected'
RETURNED_FOR_CORRECTION = 'Returned for Correction'
NO_SHOW = 'No Show'

# --- Sent to the candidate ---------------------------------------------------
JOINING_SCHEDULE = 'Joining Schedule'
ACADEMY_SCHEDULE = 'Academy Schedule'
COMPLETION_CERTIFICATE_ISSUED = 'Completion Certificate Issued'
COLLEGE_REFERRAL = 'College Referral'


ACTIVE_TYPES = frozenset({
    APPLICATION_SUBMITTED,
    APPLICATION_APPROVED,
    APPLICATION_REJECTED,
    RETURNED_FOR_CORRECTION,
    NO_SHOW,
    JOINING_SCHEDULE,
    ACADEMY_SCHEDULE,
    COMPLETION_CERTIFICATE_ISSUED,
    COLLEGE_REFERRAL,
})


#: Which pair of template files holds the wording for each type.
#:
#: portal/templates/notifications/<slug>.subject.txt
#: portal/templates/notifications/<slug>.body.txt
#:
#: Kept as an explicit map rather than derived from the type name, so renaming a
#: template file is a one-line change here and cannot silently break at runtime.
TEMPLATE_SLUGS = {
    APPLICATION_SUBMITTED: 'application_submitted',
    APPLICATION_APPROVED: 'application_approved',
    APPLICATION_REJECTED: 'application_rejected',
    RETURNED_FOR_CORRECTION: 'returned_for_correction',
    NO_SHOW: 'no_show',
    JOINING_SCHEDULE: 'joining_schedule',
    ACADEMY_SCHEDULE: 'academy_schedule',
    COMPLETION_CERTIFICATE_ISSUED: 'completion_certificate_issued',
    COLLEGE_REFERRAL: 'college_referral',
}


# --- delivery_status values, matching the ENUM on the column -----------------
STATUS_PENDING = 'Pending'
STATUS_SENT = 'Sent'
STATUS_FAILED = 'Failed'
