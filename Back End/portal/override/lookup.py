"""
Application lookup for Admin Mode, with an archive-aware 404.

Back End/portal/override/lookup.py

Hard-closing a cycle DELETES its applications after copying them into the
archive tables. There is no is_archived flag to test: an archived
application is simply gone from `applications`, and every child row went
with it on cascade.

So the plain 404 an admin would otherwise get is TRUE but useless. It reads
as "no such application" when the truth is "this application exists, it is
closed, and it can be read in the archive but never edited". The second
lookup below costs one indexed query, and only on the miss path.
"""

from portal.models import Applications, ArchivedApplications


class ApplicationNotFound(Exception):
    """No application by this id, live or archived."""


class ApplicationArchived(Exception):
    """The application exists but has been archived by cycle closure.

    Carries the archive row so the endpoint can name the cycle and the
    ticket in its message. An admin looking at a stale browser tab wants to
    know WHICH closed record they are pointed at, not merely that they are
    pointed at one.
    """

    def __init__(self, archived):
        self.archived = archived
        super().__init__('Application has been archived.')


def get_live_application(application_id):
    """Return the live Applications row, or raise.

    Every Admin Mode endpoint starts here. Nothing else in this package
    should call Applications.objects.get() directly, so the archived case
    cannot be handled in one endpoint and forgotten in another.

    A malformed id (None, '', 'abc') raises ApplicationNotFound rather than
    propagating a ValueError, so the caller has one exception to catch for
    "there is nothing here to edit".
    """
    try:
        application_id = int(application_id)
    except (TypeError, ValueError):
        raise ApplicationNotFound()

    try:
        return Applications.objects.get(pk=application_id)
    except Applications.DoesNotExist:
        pass

    archived = ArchivedApplications.objects.filter(
        original_application_id=application_id).first()
    if archived is not None:
        raise ApplicationArchived(archived)

    raise ApplicationNotFound()

def get_live_application_by_ticket(ticket):
    """Same as get_live_application, keyed by application_code.

    The dashboard is ticket-based throughout -- no screen has ever held a
    numeric application_id -- so the endpoint accepts either. The archive
    fallback matters even more here: a ticket is what an administrator
    reads off a printed letter or an email, so a stale one is the likeliest
    thing to be typed at this endpoint.
    """
    ticket = (ticket or '').strip()
    if not ticket:
        raise ApplicationNotFound()

    application = Applications.objects.filter(application_code=ticket).first()
    if application is not None:
        return application

    archived = ArchivedApplications.objects.filter(
        application_code=ticket).first()
    if archived is not None:
        raise ApplicationArchived(archived)

    raise ApplicationNotFound()