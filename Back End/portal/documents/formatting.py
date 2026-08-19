"""
Presentation rules shared by every document this portal generates.

The portal STORES everything in upper case -- that is a deliberate convention
running through the schema, the seed data and both dashboards, and nothing here
changes it. But an official letter reading "APPROVAL HAS BEEN GRANTED FOR MS.
PRIYA SHARMA, A B.TECH STUDENT AT DELHI TECHNOLOGICAL UNIVERSITY" reads as
shouting. So the conversion to ordinary capitalisation happens HERE, at the
moment of printing, and only for the letter.

The one exception is sub-department names. 'GM/HR/O&M' is a post designation,
not a phrase, and title-casing it to 'Gm/Hr/O&M' would be wrong. Those stay
exactly as stored.
"""

import re
from datetime import timedelta


# ------------------------------------------------------------------------------
# TEXT
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# WHY THERE IS NO TITLE-CASING HERE
#
# An earlier version converted stored values to ordinary capitalisation for the
# letter: 'PRIYA SHARMA' -> 'Priya Sharma'. It was removed.
#
# The problem is acronyms. Plain title case turns 'ASSISTANT HR MANAGER' into
# 'Assistant Hr Manager', 'IIT DELHI' into 'Iit Delhi' and 'BCA' into 'Bca' --
# all wrong, and all ordinary values in this portal. Fixing that needs a list of
# every acronym DMRC might ever store, which is a list nobody can finish. A
# missing entry produces a wrong-looking official letter, and no one would
# notice until it had been handed to somebody.
#
# So the portal prints what it stores, exactly as it stores it. The convention
# is already upper case throughout the schema, the seed data and both
# dashboards, and the letter now simply follows it. Nothing can be mangled by a
# rule that guessed wrong, because there is no rule.
#
# The only value the portal chooses rather than fetches is the salutation, which
# is written 'Mr.' or 'Ms.' as the letter format shows.
# ------------------------------------------------------------------------------


def as_stored(text):
    """Pass a value through untouched. Used for sub-department names.

    Exists as a named function so the intent is visible at the call site: a
    field printed this way is a deliberate exception, not one somebody forgot
    to convert.
    """
    return '' if text is None else str(text).strip()


def salutation_for(stored_value, gender=None):
    """Return 'Mr.' or 'Ms.' for the letter.

    The Phase-1 form collects this and the server requires it before an
    application can reach the pipeline, so in practice it is always present.
    Gender is consulted only as a fallback for records created before that
    requirement existed. Returning '' is preferable to guessing: the letter
    then reads "approval has been granted for Priya Sharma", which is correct,
    merely less formal.
    """
    value = (stored_value or '').strip().lower().rstrip('.')
    if value in ('mr', 'mister'):
        return 'Mr.'
    if value in ('ms', 'miss', 'mrs'):
        return 'Ms.'

    fallback = (gender or '').strip().lower()
    if fallback == 'male':
        return 'Mr.'
    if fallback == 'female':
        return 'Ms.'
    return ''


# ------------------------------------------------------------------------------
# DATES
# ------------------------------------------------------------------------------

def format_date(value):
    """DD-MM-YYYY, the format DMRC uses."""
    if value is None:
        return ''
    return value.strftime('%d-%m-%Y')


def completion_date(start_date, duration_weeks):
    """The last day of the internship, INCLUSIVE.

    A 4-week internship starting 01-01-2026 ends 28-01-2026, not 29-01. The
    intern serves 28 days; the 29th is the day after they finish.

    Returns None if either input is missing, so a caller can tell "not yet
    known" apart from a date, rather than receiving a silently wrong one.
    """
    if not start_date or not duration_weeks:
        return None
    return start_date + timedelta(days=(int(duration_weeks) * 7) - 1)


def duration_phrase(duration_weeks):
    """'4 weeks'. Singular is impossible here -- the schema permits 4, 6 or 8."""
    if not duration_weeks:
        return ''
    return f"{int(duration_weeks)} weeks"


def subject_line(duration_weeks, session_term, application_year):
    """'4 weeks internship at DMRC Winter 2026'."""
    parts = [duration_phrase(duration_weeks), 'internship at DMRC']
    if session_term:
        # Stored as 'Winter' / 'Summer' already, so it needs no conversion.
        parts.append(as_stored(session_term))
    if application_year:
        parts.append(str(application_year))
    return ' '.join(p for p in parts if p)


def reference_line(application_code):
    """'No. DMRC/PERS/Internship/DMRC-2026W-001'.

    The ticket goes in the slot the format shows as [year]. It is what makes
    one letter distinguishable from another; a bare year would be identical on
    every letter issued that season.
    """
    return f"No. DMRC/PERS/Internship/{as_stored(application_code) or '—'}"


# ------------------------------------------------------------------------------
# PRONOUNS
#
# The completion certificate refers to the intern six times: "has completed
# his/her internship", "he/she successfully worked", "His/Her approach",
# "he/she was found to be", "wishes him/her success", "his/her future
# endeavors".
#
# Gender is a mandatory field on the application, so the portal chooses rather
# than printing the slashed form -- a certificate that reads "she successfully
# worked on the project" is simply better than one that makes the reader pick.
#
# When gender is missing or is something these three forms cannot express, the
# SLASHED form comes back. That is the honest answer: the certificate stays
# correct and merely reads a little more formally, which is far better than
# guessing and calling somebody by the wrong pronoun on an official document
# they will keep.
# ------------------------------------------------------------------------------

PRONOUNS = {
    'male':   {'subject': 'he',  'object': 'him', 'possessive': 'his'},
    'female': {'subject': 'she', 'object': 'her', 'possessive': 'her'},
}

_SLASHED = {'subject': 'he/she', 'object': 'him/her', 'possessive': 'his/her'}


def pronouns_for(gender):
    """Return {'subject', 'object', 'possessive'} plus capitalised variants."""
    forms = PRONOUNS.get((gender or '').strip().lower(), _SLASHED)
    resolved = dict(forms)
    for key, value in forms.items():
        # 'his' -> 'His', and 'his/her' -> 'His/Her': each part capitalised, so
        # the slashed fallback still reads correctly at the start of a sentence.
        resolved[key + '_cap'] = '/'.join(part.capitalize() for part in value.split('/'))
    return resolved