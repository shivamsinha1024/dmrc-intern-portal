"""
COMPLETION CERTIFICATE LAYOUT PREVIEW

Generates a sample certificate from invented data, so the layout can be checked
without a database, a running server, or a real application on file.

    cd "Back End"
    python3 preview_completion_certificate.py

Writes two files into the folder you run it from:

    preview_completion_certificate.pdf    what HR-APP sends to the candidate
    preview_completion_certificate.docx   what HR-APP edits to correct it

WHAT TO CHECK:

  1. The PRONOUNS. The sample below is female, so the certificate should read
     "her internship", "she successfully worked", "Her approach", "wishes her
     success". Change GENDER to 'Male' and re-run to see the other set; set it
     to '' to see the slashed "his/her" fallback used when gender is missing.

  2. The letterhead, which is drawn by the SAME code as the offer letter. If it
     looks right on one it is right on both.

  3. That the Word file has NO signature on it, though it does have the
     letterhead. That is deliberate -- a signature inside a downloadable Word
     file can be lifted and reused on anything.

  4. That the FILE NUMBER does not appear. It is recorded against the
     application and shown in the drawer; DMRC does not print it here.

To preview with a real signature, drop an image beside this script named
sample_signature.png. Without it the signature line prints bare, which is
exactly what happens when an officer has no approved signature.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portal.documents.certificate import (
    build_completion_certificate_docx, build_completion_certificate_pdf,
)
from portal.documents.formatting import completion_date, salutation_for

GENDER = 'Female'


def build_sample_context():
    """Invented data, stored the way the portal really stores it: UPPER CASE."""
    start = date(2026, 1, 5)
    weeks = 4

    signature = ('sample_signature.png'
                 if os.path.exists('sample_signature.png') else None)

    return {
        'application_code': 'DMRC-2026W-001',
        'issued_on': date(2026, 2, 3),
        'salutation': salutation_for('Ms.', GENDER),
        'candidate_name': 'PRIYA SHARMA',
        'college': 'DELHI TECHNOLOGICAL UNIVERSITY',
        'sub_department': 'ED/IT',
        'start_date': start,
        # The SAME date the offer letter printed. On a real application this is
        # read from joining_details.date_of_completion, written when the offer
        # letter was issued -- never recalculated here.
        'end_date': completion_date(start, weeks),
        'project_title': 'AUTOMATED FARE COLLECTION GATE FAULT ANALYSIS',
        'gender': GENDER,
        'signatory_name': 'REENA ARORA',
        'signatory_designation': 'AM',
        'signature_path': signature,
    }


def main():
    context = build_sample_context()

    with open('preview_completion_certificate.pdf', 'wb') as handle:
        handle.write(build_completion_certificate_pdf(context))

    with open('preview_completion_certificate.docx', 'wb') as handle:
        handle.write(build_completion_certificate_docx(context))

    print('Wrote preview_completion_certificate.pdf')
    print('Wrote preview_completion_certificate.docx')
    print()
    print('Sample data used:')
    for key in ('application_code', 'candidate_name', 'gender',
                'sub_department', 'start_date', 'end_date', 'project_title'):
        print(f'  {key:20} {context[key]}')
    print()
    print(f'  signature            {context["signature_path"] or "(none - line prints bare)"}')
    print()
    print('Open the PDF and check the pronouns read correctly for this gender.')


if __name__ == '__main__':
    main()
