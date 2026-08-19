"""
STAMPING A SIGNATURE ONTO AN UPLOADED PDF
==============================================================================

When HR-OPS corrects an offer letter, they edit the Word copy -- which carries
NO signature, deliberately, because a signature sitting inside a downloadable
Word file can be lifted in three clicks and pasted onto anything.

So the corrected PDF that comes back is unsigned. It gets its signature at the
moment HR-APP approves it, and that is what this module does.

------------------------------------------------------------------------------
WHY IT LOOKS FOR THE SIGNATORY'S NAME
------------------------------------------------------------------------------
The obvious approach -- stamp at fixed coordinates -- fails as soon as HR-OPS's
correction changes the length of anything above the signature block. Correcting
a degree name can reflow a paragraph, push the block down a line, and the
signature lands on the disclaimer.

So the page is searched for the signatory's printed name, which sits directly
below the signature line on every version of this letter, and the signature is
placed just above it. The block can move anywhere on the page and the signature
follows it.

If the name cannot be found -- an unusual font, a scanned page with no text
layer -- the signature is placed where the generated letter puts it and the
caller is told. A letter that says it is signed and is not would be worse than
either.
"""

import io
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

# Same geometry as the generated letter, used as the fallback position.
from .offer_letter import (
    MARGIN_RIGHT_MM, SIGNATURE_HEIGHT_MM, SIGNATURE_WIDTH_MM,
)

#: A run of underscores is how the Word copy draws the signature line.
_SIGNATURE_LINE = re.compile(r'_{6,}')


def _find_signature_anchor(page, signatory_name):
    """Locate where the signature belongs on one page.

    Returns (x_right, y_baseline) in PDF points, or None if this page carries
    neither the signatory's name nor a signature line.

    Prefers the underscore line when there is one, because that is literally
    where a signature goes; falls back to sitting above the printed name.
    """
    found = []

    def visitor(text, cm, tm, font_dict, font_size):
        # The position is the TEXT matrix combined with the GRAPHICS matrix, not
        # the text matrix alone.
        #
        # This mattered. Using tm by itself reported the signatory's name at
        # 14.7 points from the foot of the page rather than its real position,
        # because the generator wraps that block in a translation that lives in
        # cm. The signature was then stamped along the bottom edge, off the
        # visible area -- and, worse, the function reported that it had placed
        # it precisely, so nothing anywhere said the certificate was unsigned.
        #
        # Adding the two translations is correct for every unrotated page, which
        # is what these documents are. A rotated page would need the full matrix
        # product; the plausibility check below catches that case instead.
        if text and text.strip():
            x = (tm[4] or 0) + (cm[4] or 0)
            y = (tm[5] or 0) + (cm[5] or 0)
            found.append((text.strip(), x, y, font_size or 10.0))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return None

    wanted = (signatory_name or '').strip().upper()

    # A position at or near the foot of the page is not a signature block -- it
    # is a position that was read wrongly. pypdf reports zero for some text runs
    # depending on how the generator emitted them, and stamping on that would
    # put the signature in the bottom margin while reporting success.
    FLOOR = 40.0

    name_hit = line_hit = designation_hit = None
    for text, x, y, size in found:
        if y <= FLOOR:
            continue
        upper = text.upper()
        if wanted and wanted in upper:
            name_hit = (text, x, y, size)
        # The designation line, always the LAST line of the signature block and
        # always ending '/HR'. Kept as a second landmark because the name itself
        # is the run pypdf most often reports as zero.
        if upper.endswith('/HR') and designation_hit is None:
            designation_hit = (text, x, y, size)
        if _SIGNATURE_LINE.search(text):
            if line_hit is None or y > line_hit[2]:
                line_hit = (text, x, y, size)

    # In order of how directly each landmark locates the signature.
    if name_hit is not None:
        _, x, y, size = name_hit
        # Just above the name, clearing the line between them.
        return (None, y + (size * 1.4))
    if line_hit is not None:
        _, x, y, size = line_hit
        return (None, y + 2.0)
    if designation_hit is not None:
        _, x, y, size = designation_hit
        # Two lines up: the name sits between this and the signature.
        return (None, y + (size * 2.6))
    return None


def stamp_signature(pdf_bytes, signature_path, signatory_name):
    """Return (stamped_pdf_bytes, placed_precisely, failure).

    failure is None on success. When it is a string, NOTHING WAS STAMPED and the
    string says why -- the caller must refuse the approval rather than store an
    unsigned letter as the official signed one.

    That distinction is the whole point. An earlier version returned the
    original bytes on any problem, INCLUDING pypdf not being installed, so a
    missing library produced a letter that was approved, official, and blank
    where the signature should be, with nothing anywhere saying so.

    placed_precisely is a much softer signal: the signature WAS applied, but the
    signature block could not be located, so the fallback position was used and
    somebody should look at the result.
    """
    if not pdf_bytes:
        return pdf_bytes, False, "the uploaded file was empty"
    if not signature_path:
        return pdf_bytes, False, "no signature image was supplied"

    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        return pdf_bytes, False, (
            "the 'pypdf' library is not installed on this server. Run "
            "'pip3 install -r requirements.txt' from the Back End folder, "
            "then restart the server"
        )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return pdf_bytes, False, "the uploaded PDF has no pages"
    except Exception as unreadable:
        return pdf_bytes, False, "the uploaded PDF could not be read (%s)" % unreadable

    # The signature block is on the page carrying the signatory's name, which is
    # the last page for a one-page letter and still the right page if HR-OPS's
    # correction pushed the letter onto two.
    target_index = None
    anchor = None
    for index, page in enumerate(reader.pages):
        found = _find_signature_anchor(page, signatory_name)
        if found is not None:
            target_index, anchor = index, found
            break

    placed_precisely = anchor is not None
    if target_index is None:
        target_index = len(reader.pages) - 1

    page = reader.pages[target_index]
    try:
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
    except Exception:
        page_width, page_height = A4

    right_edge = page_width - (MARGIN_RIGHT_MM * mm)
    width = SIGNATURE_WIDTH_MM * mm
    height = SIGNATURE_HEIGHT_MM * mm

    if anchor is not None:
        baseline = anchor[1]
    else:
        # Where the generated letter puts it, measured from the bottom.
        baseline = page_height * 0.28

    left = right_edge - width
    bottom = baseline

    # Keep it on the page whatever the anchor said.
    bottom = max(2 * mm, min(bottom, page_height - height - 2 * mm))
    left = max(2 * mm, min(left, page_width - width - 2 * mm))

    try:
        overlay_buffer = io.BytesIO()
        overlay = pdf_canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))
        overlay.drawImage(
            signature_path, left, bottom, width=width, height=height,
            preserveAspectRatio=True, anchor='c', mask='auto',
        )
        overlay.showPage()
        overlay.save()
        overlay_buffer.seek(0)

        overlay_page = PdfReader(overlay_buffer).pages[0]
        page.merge_page(overlay_page)

        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)

        out = io.BytesIO()
        writer.write(out)
        return out.getvalue(), placed_precisely, None
    except Exception as stamping_error:
        return pdf_bytes, False, "the signature could not be drawn (%s)" % stamping_error