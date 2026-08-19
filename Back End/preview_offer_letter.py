"""
OFFER LETTER LAYOUT PREVIEW

Generates a sample offer letter from invented data so the layout can be checked
without a database, a running server, or a real application on file.

    cd "Back End"
    python3 preview_offer_letter.py

Writes two files into the folder you run it from:

    preview_offer_letter.pdf    what HR-OPS prints
    preview_offer_letter.docx   what HR-OPS edits when it needs correcting

The letter is drawn in full, letterhead included, and prints on plain A4.

WHAT TO CHECK, in order of how likely it is to be wrong:

  1. THE LOGO. The one bundled in portal/documents/assets/dmrc_logo.png was
     lifted from the format DMRC supplied and is only 120x120 pixels -- fine on
     screen, soft in print. Replace it with the higher-resolution
     dmrc-logo.png from the Front End folder, keeping the same filename.

  2. The letterhead spacing. If the rule crowds the address or the body sits
     too close beneath it, adjust HEADER_TOP_MM and CONTENT_TOP_MM near the top
     of portal/documents/offer_letter.py.

  3. The photograph box, top right. Position and size are PHOTO_BOX_*.

  4. The signature: size and position are SIGNATURE_*.

  5. That the Word file has NO signature on it, though it does have the
     letterhead and the photograph. That is deliberate -- a signature inside a
     downloadable Word file can be lifted and reused on anything.

To preview with your own images, drop a photo and a signature beside this
script named sample_photo.jpg and sample_signature.png. Neither is required;
without them the photo box prints empty and the signature line prints bare,
which is exactly what a real letter does when either is missing.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portal.documents.formatting import completion_date, salutation_for
from portal.documents.offer_letter import (
    build_offer_letter_docx, build_offer_letter_pdf,
)


def build_sample_context():
    """Invented data, stored the way the portal really stores it: UPPER CASE.

    That matters -- the letter's conversion to ordinary capitalisation is one
    of the things this preview exists to check.
    """
    start = date(2026, 1, 5)
    weeks = 4

    photo = 'sample_photo.jpg' if os.path.exists('sample_photo.jpg') else None
    signature = ('sample_signature.png'
                 if os.path.exists('sample_signature.png') else None)

    return {
        'application_code': 'DMRC-2026W-001',
        'issued_on': date(2026, 1, 5),
        'salutation': salutation_for('Ms.'),
        'candidate_name': 'PRIYA SHARMA',
        'course': 'B.TECH',
        'college': 'DELHI TECHNOLOGICAL UNIVERSITY',
        'duration_weeks': weeks,
        'sub_department': 'ED/IT',
        'start_date': start,
        'end_date': completion_date(start, weeks),
        'session_term': 'Winter',
        'application_year': 2026,
        'signatory_name': 'REENA VERMA',
        'signatory_designation': 'ASSISTANT HR MANAGER',
        'photo_path': photo,
        'signature_path': signature,
    }


def main():
    context = build_sample_context()

    with open('preview_offer_letter.pdf', 'wb') as handle:
        handle.write(build_offer_letter_pdf(context))

    with open('preview_offer_letter.docx', 'wb') as handle:
        handle.write(build_offer_letter_docx(context))

    print('Wrote preview_offer_letter.pdf')
    print('Wrote preview_offer_letter.docx')
    print()
    print('Sample data used:')
    for key in ('application_code', 'candidate_name', 'sub_department',
                'start_date', 'end_date'):
        print(f'  {key:20} {context[key]}')
    print()
    print(f'  photograph           {context["photo_path"] or "(none - box prints empty)"}')
    print(f'  signature            {context["signature_path"] or "(none - line prints bare)"}')
    print()
    print('Open the PDF and check the letterhead, then print one on plain A4.')


if __name__ == '__main__':
    main()
