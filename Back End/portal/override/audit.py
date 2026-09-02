"""
Audit writes for Admin Mode.

Back End/portal/override/audit.py

MATCHES AN EXISTING CONVENTION. Everything about the shape below was taken
from the writers already in views.py (_audit, record_application_event,
AdminConfigAPIView) rather than designed here. Three of those choices are
worth stating, because two of them look like mistakes and neither is safe
to "fix" from this module:

  1. old_value / new_value are JSONField, and every existing writer passes
     json.dumps() into them. The stored value is therefore a JSON string
     containing JSON, and a read returns str, not dict.
     serialize_audit_row() is built for exactly that. A row written as a
     bare dict would be the only row in the table its own reader could not
     parse.

  2. The ledger screen and the export both render ONE field per row, taken
     from "remarks" via serialize_audit_row()'s final else branch.
     Structured keys are invisible to them. So the readable sentence goes
     in "remarks" and the structured detail sits beside it: the screen
     stays correct with no changes, and the forensic detail is still there
     for anyone querying the column directly.

  3. A 'Document' row is named by its TICKET, not its document id --
     serialize_audit_row() reads payload.get('application') and falls back
     to "Document #<id>" when it is absent. So every document row written
     here carries the application_code.

If the double-encoding is ever corrected, it must be corrected for every
writer and for the reader in one change. Not here, and not for one
endpoint.

DUPLICATION, ON PURPOSE
_write() below repeats the eight lines of views._audit(). Importing it
would make portal.override depend on portal.views while views.py imports
portal.override, which is a circular import. Eight duplicated lines is the
cheaper of the two problems, and it is the same trade-off
notifications/rerender.py already makes with _safe_subject().
"""

import json
import logging

from django.db import transaction

from portal.models import SystemAuditLogs
from portal.override import fields as field_specs

logger = logging.getLogger(__name__)


# action_type is VARCHAR(100). Existing values are SCREAMING_SNAKE
# ('RULES_UPDATE', 'DOCUMENT_SUPERSEDED', 'DOCUMENT_GENERATED',
# 'SIGNATURE_REJECTED', 'SYSTEM_OVERRIDE') or a bare status string.
#
# 'SYSTEM_OVERRIDE' is deliberately NOT reused. It already means god-mode
# status forcing in HRApplicationActionAPIView, and the two would be
# indistinguishable on the ledger screen -- which is precisely the question
# an auditor is asking when they filter that column.
#
# All three are uppercase, which matters: serialize_audit_row() treats an
# action_type equal to its own .upper() as a non-status event, and routes
# it to the "remarks" branch these functions write to.
ACTION_FIELD_CORRECTION = 'ADMIN_FIELD_CORRECTION'
ACTION_STATUS_ROLLBACK = 'ADMIN_STATUS_ROLLBACK'
ACTION_DOCUMENT_QUARANTINED = 'ADMIN_DOCUMENT_QUARANTINED'

# CapCase singular, matching 'Application', 'Document', 'SubDepartment'.
# Both are already handled explicitly by serialize_audit_row(); a third,
# invented entity type would fall through to its generic branch and render
# as "<Type> Configuration", which describes neither.
ENTITY_APPLICATION = 'Application'
ENTITY_DOCUMENT = 'Document'


def _write(actor, action, entity_type, entity_id,
           old_value=None, new_value=None):
    """One ledger row, in the house shape. Never raises.

    The nested atomic() is what makes a failed audit write survivable
    inside the endpoint's own transaction: without it, a broken INSERT here
    would poison the outer transaction and take the correction down with
    it. The ledger must not be able to veto the action it is recording --
    but a failure must not vanish either, hence the log line rather than a
    bare pass.
    """
    try:
        with transaction.atomic():
            SystemAuditLogs.objects.create(
                actor_user=actor,
                role_name=getattr(
                    getattr(actor, 'role', None), 'role_name', 'SYS-ADMIN'),
                action_type=action,
                target_entity_type=entity_type,
                target_entity_id=entity_id,
                old_value=json.dumps(old_value) if old_value is not None else None,
                new_value=json.dumps(new_value) if new_value is not None else None,
            )
    except Exception as audit_error:
        logger.error("AUDIT WRITE FAILED (%s): %s",
                     type(audit_error).__name__, audit_error)


def _display(value):
    """Render a value for the remark sentence."""
    if value is None or value == '':
        return '(blank)'
    return str(value)


def log_field_correction(actor, application, field_key, old, new, reason):
    """One row per corrected field.

    ONE ROW PER FIELD, not one per request. The requirement is that the
    ledger names the field, the old value and the new value; the screen
    shows one remark per row, so a single row covering nine fields would
    collapse to one sentence and lose eight of them. Nine rows sharing a
    timestamp and a reason read correctly line by line, and match the
    granularity DOCUMENT_SUPERSEDED already uses.

    `reason` is mandatory and is repeated on every row of the request. A
    reader filtering to one field must see why that field changed without
    having to go and find its siblings.
    """
    label = field_specs.label_for(field_key)
    _write(
        actor,
        ACTION_FIELD_CORRECTION,
        ENTITY_APPLICATION,
        application.pk,
        old_value={
            "field": field_key,
            "label": label,
            "value": old if old is None else str(old),
        },
        new_value={
            # Read by the ledger screen and the export. Everything else in
            # this dict is invisible to both.
            "remarks": "%s: %s -> %s. Reason: %s" % (
                label, _display(old), _display(new), reason),
            "field": field_key,
            "label": label,
            "value": new if new is None else str(new),
            "reason": reason,
            "application": application.application_code,
        },
    )


def log_status_rollback(actor, application, previous_status, new_status,
                        reason, cleared_fields, quarantined_documents):
    """One row for the whole status reset.

    A reset is a single decision with a single reason, unlike a field
    correction where each field was a separate judgement. The columns it
    clears are its consequences rather than its content, so they are listed
    inside the row rather than split across dozens of them.
    """
    _write(
        actor,
        ACTION_STATUS_ROLLBACK,
        ENTITY_APPLICATION,
        application.pk,
        old_value={
            "status": previous_status,
            "cleared_fields": sorted(cleared_fields),
            "quarantined_documents": list(quarantined_documents),
        },
        new_value={
            "remarks": "Reset from %s to %s. %d field(s) cleared, "
                       "%d generated document(s) quarantined. Reason: %s" % (
                           previous_status, new_status, len(cleared_fields),
                           len(quarantined_documents), reason),
            "status": new_status,
            "reason": reason,
            "application": application.application_code,
        },
    )


def log_document_quarantined(actor, document, doc_type_name, application_code,
                             quarantined_to, reason):
    """One row per generated document removed by a rollback.

    Separate from the rollback row and keyed to the DOCUMENT, so a query
    asking what happened to a particular file finds it under its own entity
    id -- exactly as DOCUMENT_SUPERSEDED already allows.

    application_code is passed in rather than read from the row: a
    Documents instance cannot reach its ticket without another query, and
    serialize_audit_row() needs it to name this event by ticket instead of
    by row number.
    """
    _write(
        actor,
        ACTION_DOCUMENT_QUARANTINED,
        ENTITY_DOCUMENT,
        document.document_id,
        old_value={
            "doc_type": doc_type_name,
            "version": document.version,
            "file_path": str(document.file_path),
        },
        new_value={
            "remarks": "%s v%s quarantined by administrative rollback. "
                       "Reason: %s" % (doc_type_name, document.version, reason),
            "application": application_code,
            "quarantined_to": quarantined_to,
            "reason": reason,
        },
    )