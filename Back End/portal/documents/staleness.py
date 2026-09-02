"""Deciding which system-generated documents an Admin Mode edit makes stale.

WHAT "STALE" MEANS

A document goes stale when a field actually PRINTED on it (or that decides
its content, like gender choosing pronouns) is edited after issuance. It's a
warning, not a lock: HR-OPS can still download a stale document -- they may
need to see exactly what was handed to the candidate.

THE FIELD MAP

Copied directly from the project brief, which derives it from the context
dictionaries in offer_letter.py and certificate.py and says not to re-derive
it. A field not listed here can never make either document stale.

WHY THIS TOUCHES NEITHER THE DATABASE NOR A MODEL

Same boundary as offer_letter.py, certificate.py and formatting.py: pure
functions in, pure values out. The function that actually queries and
updates `documents` is an orchestrator, like queue.py -- it belongs next to
the rest of the Admin Mode code, not here. See the note at the bottom.
"""

from collections import defaultdict

from .formatting import format_date

KIND_OFFER_LETTER = 'offer_letter'
KIND_CERTIFICATE = 'certificate'

#: CONFIRM THESE against document_types.type_name -- everything else here is
#: independent of the exact strings; only this needs fixing if I guessed wrong.
DOCUMENT_TYPE_NAMES = {
    KIND_OFFER_LETTER: 'OFFER LETTER',
    KIND_CERTIFICATE:  'COMPLETION CERTIFICATE',
}

# Key: 'table.field', matching the brief's own notation exactly.
# joining_details.allotted_sub_department_id is written here as
# .allotted_sub_department, the Django field name for the same column.
FIELD_MAP = {
    'students.full_name':                      {KIND_OFFER_LETTER, KIND_CERTIFICATE},
    'students.salutation':                      {KIND_OFFER_LETTER, KIND_CERTIFICATE},
    'students.gender':                          {KIND_CERTIFICATE},
    'academic_details.college_name':            {KIND_OFFER_LETTER, KIND_CERTIFICATE},
    'academic_details.degree_program':          {KIND_OFFER_LETTER},
    'applications.duration_weeks':              {KIND_OFFER_LETTER, KIND_CERTIFICATE},
    'joining_details.actual_date_of_joining':   {KIND_OFFER_LETTER, KIND_CERTIFICATE},
    'joining_details.allotted_sub_department':  {KIND_OFFER_LETTER, KIND_CERTIFICATE},
    'applications.project_report_title':        {KIND_CERTIFICATE},
}

#: Human labels, used only to build stale_reason text.
FIELD_LABELS = {
    'students.full_name':                      'Candidate name',
    'students.salutation':                     'Salutation',
    'students.gender':                         'Gender',
    'academic_details.college_name':           'College',
    'academic_details.degree_program':         'Degree programme',
    'applications.duration_weeks':             'Internship duration',
    'joining_details.actual_date_of_joining':  'Date of joining',
    'joining_details.allotted_sub_department': 'Posted sub-department',
    'applications.project_report_title':       'Project title',
}


def relevant_changes_by_kind(changes):
    """Split every edit an admin made into what matters to each document.

    `changes`: {'table.field': (old_display, new_display)} for EVERYTHING
    changed in this save, not pre-filtered. old/new must already be
    display-ready strings (dates formatted, foreign keys resolved to a
    name) -- this module doesn't know which fields are dates or foreign
    keys, only which ones matter.

    Returns {kind: {'table.field': (old, new)}}, one entry per kind with at
    least one relevant change. A kind with none is simply absent.
    """
    result = defaultdict(dict)
    for field_key, values in changes.items():
        for kind in FIELD_MAP.get(field_key, ()):
            result[kind][field_key] = values
    return dict(result)


def affected_document_kinds(changes):
    """Just the set of kinds touched -- for a caller that only needs to
    know whether to look at documents at all.
    """
    return set(relevant_changes_by_kind(changes).keys())


def describe_changes(field_changes, admin_display_name, when):
    """Build the stale_reason text for one document.

    field_changes: {'table.field': (old, new)}, already filtered to ONE
    kind, e.g. relevant_changes_by_kind(changes)[KIND_CERTIFICATE].
    when: typically the same timestamp written to stale_since.

    Returns a plain string. The caller still truncates it to 500 characters
    before saving -- this doesn't know the column width, only the wording.
    """
    def shown(value):
        return value if value not in (None, '') else '(blank)'

    clauses = [
        f"{FIELD_LABELS.get(key, key)} changed from {shown(old)} to {shown(new)}"
        for key, (old, new) in field_changes.items()
    ]
    return (
        '; '.join(clauses)
        + f' (corrected by {admin_display_name} on {format_date(when)}).'
    )


# ---------------------------------------------------------------------------
# WHAT IS DELIBERATELY NOT HERE
#
# Finding the current, system-generated Documents rows for an application and
# writing stale_since/stale_reason onto them needs current_documents() (so
# this stays consistent with the one rule the codebase already enforces --
# never read `documents` without going through it) and confirmation of what
# store_generated_document() does on reissue. Both live in views.py. Once I
# can see them this becomes a short function, maybe 15 lines, that calls
# relevant_changes_by_kind() above and then does the actual .update().
# ---------------------------------------------------------------------------