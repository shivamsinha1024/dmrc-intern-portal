"""
The DB-writing half of stale-document detection.

Back End/portal/override/documents.py

documents/staleness.py decides WHICH documents a change affects and what
the reason text says. This module decides which rows to write it to. The
split keeps staleness.py pure, like the rest of portal/documents/, and
keeps the only queries in this feature inside portal/override/.
"""

from portal.documents import staleness
from portal.models import Documents


def mark_stale_documents(application, changes, admin_display_name, when):
    """Flag every system-generated document a correction has outdated.

    WARNS, DOES NOT BLOCK. HR-OPS can still download a stale document: it
    is a true record of what was actually issued, and refusing to serve it
    would hide the very discrepancy the flag exists to announce.

    Reissuing clears the flag with no code here. store_generated_document()
    demotes the stale row to is_current NULL and inserts a fresh row with
    both columns unset, so the live document is never stale by accident.

    `changes` is the endpoint's {field_key: (old, new)} dict, keyed exactly
    as staleness.FIELD_MAP is.

    Returns the rows touched, for the response payload.
    """
    by_kind = staleness.relevant_changes_by_kind(changes)
    touched = []

    for kind, field_changes in by_kind.items():
        if not field_changes:
            continue

        row = Documents.objects.filter(
            application=application,
            doc_type__type_name=staleness.DOCUMENT_TYPE_NAMES[kind],
            doc_type__is_system_generated=1,
            is_current=1,
        ).first()

        if row is None:
            # Nothing issued yet, so nothing to outdate. This is the common
            # case for an early-pipeline correction and not an error: an
            # application at Submitted has no offer letter to make stale.
            #
            # is_current=1 also excludes rows at is_pending_approval=1,
            # which is correct -- a corrected letter awaiting HR-APP is not
            # the official document and is not what anyone is downloading.
            continue

        reason = staleness.describe_changes(
            field_changes, admin_display_name, when)[:500]

        # stale_since keeps its ORIGINAL value across repeated corrections.
        # It answers "how long has this document been wrong", and resetting
        # it on the second correction would restart that clock and make a
        # document that has been wrong for a month look freshly flagged.
        #
        # stale_reason IS replaced: the newest description is written
        # against the current state of the record and subsumes the older
        # one.
        row.stale_since = row.stale_since or when
        row.stale_reason = reason
        row.save(update_fields=['stale_since', 'stale_reason'])
        touched.append(row)

    return touched