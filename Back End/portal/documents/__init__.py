"""
Document generation for the DMRC internship portal.

Everything the portal PRODUCES as a file lives here -- currently the offer
letter, with the completion certificate to follow.

Nothing in this package imports a model, reads the database or touches Django
settings. Each builder takes a plain dictionary and returns bytes. That is a
deliberate boundary:

  * the layout can be checked by running preview_offer_letter.py, with no
    database, no server and no application on file;
  * deciding WHETHER a letter may be issued is a server question, and stays in
    views.py where the other gates live;
  * drawing the letter is a layout question, and stays here.

    from .documents.offer_letter import (
        build_offer_letter_pdf, build_offer_letter_docx,
    )
"""
