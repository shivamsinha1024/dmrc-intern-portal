"""Send queued notifications.

    python manage.py send_notifications

One pass, then exit -- meant for cron. A crashed run costs nothing: the rows it
did not reach are still Pending and the next run picks them up. A long-running
process that dies stays dead.

    */5 * * * * cd '/path/to/Back End' && /path/to/python manage.py send_notifications >> /path/to/logs/cron.log 2>&1

FAILED ROWS ARE NOT RETRIED.

A row marked Failed stays Failed. The commonest cause is a missing address,
which will fail identically forever, and an automatic retry turns one bad row
into thousands of log lines. Failures are for a person to look at:

    SELECT notification_id, notification_type, recipient_email,
           failure_reason, queued_at, processed_at
    FROM notifications
    WHERE delivery_status = 'Failed'
    ORDER BY queued_at DESC;

To send one again after fixing the cause, re-trigger the action in the portal.
That queues a fresh row rather than resurrecting the old one, so the record of
what went wrong survives.

WHERE THE EMAIL GOES

EMAIL_MODE in .env decides. 'console' prints to the terminal and sends nothing,
which is how the whole flow is tested with no mail server in existence; 'smtp'
hands the message to a real relay. No relay detail appears in this file.

Note that in console mode every message is reported as Sent, because the backend
accepted it. That is correct -- the row records what this system did with the
message -- but it means a Sent row in development means printed, not delivered.
The production check in settings.py refuses to start a deployed server in
console mode for exactly this reason.
"""

import logging
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand
from django.utils import timezone

from portal.models import Applications, Notifications
from portal.notifications import types as ntypes

logger = logging.getLogger('portal')


# =============================================================================
# ATTACHMENTS
#
# Two of the nine carry files. Neither path is stored on the notification row:
# both are resolved HERE, at send time.
#
# For the certificate that is essential. store_generated_document() demotes the
# previous version to is_current = NULL and quarantines the file, so a path
# captured when the row was queued can point at a file that has since moved. The
# only safe read is the current one, at the moment of sending.
# =============================================================================

#: The completion certificate is located through views.certificate_type(),
#: the same helper the dispatch and correction-approval endpoints use. Keeping
#: one resolver means a rename in the catalogue is a one-line change there
#: rather than a silent divergence here -- and models.py is explicit that
#: documents are keyed by doc_type_id everywhere precisely so renaming is safe.
#:
#: For reference, the catalogue currently holds doc_type_id 810010,
#: 'COMPLETION CERTIFICATE' -- one of only two rows with
#: is_system_generated = 1, alongside 'OFFER LETTER' (810009).

#: Fixed PDFs sent with the joining instructions. The same files for every
#: candidate, every time -- nothing per-application about them.
#:
#: They live in portal/static_attachments/, which is committed to Git.
#: media/, generated_documents/, protected_documents/ and signatures/ are all
#: gitignored, so a file placed in any of those would simply not exist on the
#: deployment server.
#:
#: HR has not supplied the real documents yet. When they do, drop them in that
#: directory and correct the names HERE -- this list is the only place they
#: appear.
STATIC_ATTACHMENTS = (
    'Student_Information_Format.pdf',
    'List_of_Documents_Required_for_Joining.pdf',
)

STATIC_ATTACHMENT_DIR = Path(settings.BASE_DIR) / 'portal' / 'static_attachments'

#: Which types carry the fixed PDFs above.
#:
#: College Referral is here because it is the type whose APPROVED WORDING says
#: "For convenience, we have attached:" and then lists them. Joining Schedule's
#: wording mentions no attachment. See the note in the handover -- this is worth
#: confirming with HR, because attaching files to an email that does not mention
#: them, or omitting them from one that does, are both wrong.
STATIC_ATTACHMENT_TYPES = frozenset({ntypes.COLLEGE_REFERRAL})


class AttachmentError(Exception):
    """A file this email must carry could not be produced."""


class Command(BaseCommand):
    help = 'Send Pending rows from the notifications table, once, then exit.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Maximum rows to attempt. Defaults to '
                 'NOTIFICATION_SEND_BATCH_SIZE in settings.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be sent and change nothing. Useful for '
                 'checking a queue without committing to delivery.',
        )

    def handle(self, *args, **options):
        limit = options['limit'] or getattr(
            settings, 'NOTIFICATION_SEND_BATCH_SIZE', 50)
        dry_run = options['dry_run']

        rows = list(
            Notifications.objects
            .filter(delivery_status=ntypes.STATUS_PENDING)
            .select_related('application', 'application__student')
            .order_by('queued_at', 'notification_id')[:limit]
        )

        if not rows:
            self.stdout.write('0 sent, 0 failed, 0 skipped (queue empty).')
            return

        if dry_run:
            for row in rows:
                self.stdout.write(
                    f'  would send #{row.notification_id} '
                    f'{row.notification_type} -> {row.recipient_email}'
                )
            self.stdout.write(f'Dry run: {len(rows)} would be attempted.')
            return

        sent = failed = skipped = 0

        # One connection for the whole batch rather than one per message. On a
        # relay that rate-limits connections, opening fifty is a good way to be
        # throttled or blocked.
        connection = get_connection()
        try:
            connection.open()
        except Exception as exc:
            # The relay is unreachable. Do NOT mark the batch Failed -- nothing
            # is wrong with these rows and they should go out on the next run.
            logger.error('Could not open a mail connection: %s', exc)
            self.stderr.write(
                f'0 sent, 0 failed, {len(rows)} skipped '
                f'(mail server unreachable: {exc})'
            )
            return

        try:
            for row in rows:
                outcome = self._send_one(row, connection)
                if outcome == 'sent':
                    sent += 1
                elif outcome == 'failed':
                    failed += 1
                else:
                    skipped += 1
        finally:
            try:
                connection.close()
            except Exception:
                logger.warning('Mail connection did not close cleanly.',
                               exc_info=True)

        summary = f'{sent} sent, {failed} failed, {skipped} skipped.'
        self.stdout.write(summary)
        logger.info('send_notifications: %s', summary)

    # -- one row --------------------------------------------------------------

    def _send_one(self, row, connection):
        address = (row.recipient_email or '').strip()
        if not address:
            self._mark_failed(
                row,
                'No recipient address on the row. It should have been recorded '
                'as Failed when queued; this row was Pending with an empty '
                'address, which means it was written by something other than '
                'queue_notification().',
            )
            return 'failed'

        try:
            attachments = self._attachments_for(row)
        except AttachmentError as exc:
            # Never send one of these without its file. An "enclosed" letter
            # that is not enclosed is worse than a message that did not arrive.
            self._mark_failed(row, str(exc))
            return 'failed'

        message = EmailMessage(
            subject=row.subject,
            body=row.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[address],
            connection=connection,
        )
        for path in attachments:
            message.attach_file(str(path))

        try:
            message.send(fail_silently=False)
        except Exception as exc:
            # Everything the relay can object to lands here: an unknown
            # recipient, a From address it will not accept, a message over its
            # size limit, a timeout because it is internal-only and this host is
            # not. The reason is recorded on the row rather than inferred.
            self._mark_failed(row, f'{type(exc).__name__}: {exc}')
            return 'failed'

        self._mark_sent(row)
        return 'sent'

    def _attachments_for(self, row):
        """Absolute paths of the files this row must carry. May be empty."""
        if row.notification_type == ntypes.COMPLETION_CERTIFICATE_ISSUED:
            return [self._certificate_path(row)]

        if row.notification_type in STATIC_ATTACHMENT_TYPES:
            paths = []
            for name in STATIC_ATTACHMENTS:
                path = STATIC_ATTACHMENT_DIR / name
                if not path.is_file():
                    raise AttachmentError(
                        f'Required attachment {name!r} is not in '
                        f'{STATIC_ATTACHMENT_DIR}. The file is committed to '
                        f'Git; if this is a deployment, the directory was not '
                        f'copied across.'
                    )
                paths.append(path)
            return paths

        return []

    def _certificate_path(self, row):
        """The live completion certificate for this row's application.

        Imported from views.py rather than reimplemented. current_document()
        filters is_current=1, which is the whole point: a superseded certificate
        has been quarantined and reading it would resurrect a document HR
        replaced.

        The import is inside the function on purpose. views.py is large and
        imports a great deal; doing this at module level would make the import
        cost apply to every management command, and risks an import cycle if
        views.py ever imports from this package.
        """
        from portal.views import (certificate_type, current_document,
                                  stored_document_path)

        application = row.application
        if application is None:
            raise AttachmentError(
                'The notification has no application, so its certificate '
                'cannot be found. notifications.application_id is NULL.'
            )

        doc_type = certificate_type()
        if doc_type is None:
            raise AttachmentError(
                'views.certificate_type() found no completion certificate row '
                'in document_types. The catalogue should hold one with '
                'is_system_generated = 1.'
            )

        document = current_document(application, doc_type)
        if document is None:
            raise AttachmentError(
                f'No current completion certificate for application '
                f'{application.application_id} '
                f'({application.application_code or "no code"}). Either it was '
                f'never generated, or the only version is superseded or '
                f'awaiting approval.'
            )

        path = Path(stored_document_path(document))
        if not path.is_file():
            raise AttachmentError(
                f'The certificate for application {application.application_id} '
                f'is recorded as document {document.document_id} but the file '
                f'is not on disk at {path}.'
            )

        # The certificate exists in two forms. build_completion_certificate_pdf()
        # produces the signed one; build_completion_certificate_docx() produces
        # an editable copy WITHOUT the signature, for corrections. HR's wording
        # says "Your digitally signed internship completion letter is enclosed",
        # so sending the unsigned Word file would make the email untrue.
        #
        # uq_doc_current permits only one live document per (application,
        # doc_type), so this should be unreachable -- which is exactly why it is
        # worth failing on rather than trusting.
        if path.suffix.lower() != '.pdf':
            raise AttachmentError(
                f'The current COMPLETION CERTIFICATE for application '
                f'{application.application_id} is {path.name}, not a PDF. The '
                f'email promises a digitally signed letter, and the .docx copy '
                f'is generated without the signature.'
            )
        return path

    # -- writing the outcome back ---------------------------------------------
    #
    # Both use .update() on a queryset rather than .save() on the instance, so
    # the statement touches only the columns named. Nothing else on the row can
    # be disturbed by a stale in-memory copy.
    #
    # queued_at is deliberately NOT written. It was checked against the live
    # schema: the column is `timestamp DEFAULT CURRENT_TIMESTAMP` with no
    # ON UPDATE clause, so an UPDATE that does not name it leaves it alone. Had
    # it carried MySQL's implicit ON UPDATE CURRENT_TIMESTAMP, marking a row
    # Sent would have silently rewritten the time it was queued -- destroying
    # the one field that shows how long the queue took.

    def _mark_sent(self, row):
        Notifications.objects.filter(pk=row.pk).update(
            delivery_status=ntypes.STATUS_SENT,
            processed_at=timezone.now(),
            failure_reason=None,
        )
        self._sync_certificate_status(row, ntypes.STATUS_SENT)
        logger.info(
            'Sent notification %s (%s) to %s.',
            row.notification_id, row.notification_type, row.recipient_email,
        )

    def _mark_failed(self, row, reason):
        Notifications.objects.filter(pk=row.pk).update(
            delivery_status=ntypes.STATUS_FAILED,
            processed_at=timezone.now(),
            failure_reason=reason[:500],
        )
        self._sync_certificate_status(row, ntypes.STATUS_FAILED)
        logger.warning(
            'Notification %s (%s) to %s failed: %s',
            row.notification_id, row.notification_type,
            row.recipient_email, reason,
        )

    def _sync_certificate_status(self, row, status):
        """Keep applications.certificate_email_status in step.

        CertificateDispatchAPIView sets it to 'Pending' and nothing has ever
        moved it since -- that is the gap this command closes. HR's dashboard
        and the archive filter both read that column, so if it and the
        notification row disagree, the screen HR looks at is the one that lies.
        """
        if row.notification_type != ntypes.COMPLETION_CERTIFICATE_ISSUED:
            return
        if row.application_id is None:
            return
        Applications.objects.filter(pk=row.application_id).update(
            certificate_email_status=status,
        )