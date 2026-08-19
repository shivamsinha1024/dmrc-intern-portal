"""
Move referrer-uploaded documents out of MEDIA_ROOT into PROTECTED_DOCUMENT_ROOT.

Until now every uploaded document sat under media/ and was served as a static
file, meaning anyone who knew or guessed a URL could fetch a candidate's Aadhaar
or photograph with no login at all. Protected storage sits outside MEDIA_ROOT so
Django's static handler cannot reach it; the only way in is the authenticated
viewer endpoint, which checks the caller's role and logs every access.

Run once, from the Back End folder, after applying the new code:

    python3 migrate_protected_documents.py

Safe to re-run: files already moved are skipped. System-GENERATED documents
(offer letters, certificates) are deliberately left in media/ because they exist
to be printed and circulated.
"""

import os
import shutil
import sys

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dmrc_core.settings')
django.setup()

from pathlib import Path                      # noqa: E402
from django.conf import settings              # noqa: E402
from portal.models import Documents           # noqa: E402


def main():
    media = Path(settings.MEDIA_ROOT)
    protected = Path(settings.PROTECTED_DOCUMENT_ROOT)
    protected.mkdir(parents=True, exist_ok=True)

    moved = skipped = missing = generated = 0

    for document in Documents.objects.select_related('doc_type').all():
        if not document.file_path:
            continue

        # Generated output stays public: it is meant to be circulated.
        if getattr(document.doc_type, 'is_system_generated', 0):
            generated += 1
            continue

        relative = str(document.file_path)
        source = media / relative
        destination = protected / relative

        if destination.exists():
            skipped += 1
            continue

        if not source.exists():
            missing += 1
            print(f"  missing on disk, skipped: {relative}")
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved += 1
        print(f"  moved: {relative}")

    print("\nSummary")
    print(f"  moved to protected storage : {moved}")
    print(f"  already protected          : {skipped}")
    print(f"  generated, left in media   : {generated}")
    print(f"  missing on disk            : {missing}")

    if moved:
        print("\nThese files are no longer reachable by URL. They can only be opened")
        print("through the application drawer, by a user whose role permits it, and")
        print("every view is now recorded in the audit ledger.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
