from django.urls import path
from .views import (
    SubmitApplicationView, HROmniQueueAPIView, HRApplicationActionAPIView, 
    HRAuditLedgerAPIView, IAMUserAPIView, AdminCycleAPIView, AdminConfigAPIView, 
    UniversalExportAPIView, HRDocumentOverrideAPIView, CurrentUserAPIView,
    ApplicationDraftAPIView, DraftDocumentAPIView, PortalBootstrapAPIView,
    SecureDocumentView, CollegeReferralAPIView, HRArchiveAPIView,
    HRArchiveRecordAPIView,
    SignatureAPIView, SignatureImageView, OfferLetterAPIView,
    OfferLetterCorrectionAPIView, OfferHandoverAPIView,
    DMRASessionAPIView, ClearanceAPIView, CertificateAPIView,
    CertificateCorrectionAPIView, CertificateDispatchAPIView
)

urlpatterns = [
    path('api/me/', CurrentUserAPIView.as_view(), name='current-user'),
    # Referrer-uploaded documents are served ONLY through here: role-checked,
    # link expires, inline only, and every access is logged.
    #
    # Documents the portal GENERATES now come through here too. They are served
    # differently -- downloaded rather than watermarked, because HR-OPS has to
    # print them -- but they are no longer reachable by URL. Storing them under
    # /media/ meant every link would have 404'd on the intranet, where DEBUG is
    # off and Django serves nothing from that directory.
    path('api/documents/view/', SecureDocumentView.as_view(), name='document-view'),
    path('api/portal/bootstrap/', PortalBootstrapAPIView.as_view(), name='portal-bootstrap'),
    path('api/apply/', SubmitApplicationView.as_view(), name='apply'),
    path('api/drafts/', ApplicationDraftAPIView.as_view(), name='drafts'),
    path('api/drafts/document/', DraftDocumentAPIView.as_view(), name='draft-document'),
    path('api/hr/queue/', HROmniQueueAPIView.as_view(), name='hr-queue'),
    # The College Referrals pipeline: institutional intake, scheduling,
    # completion and merge. Records here are deliberately absent from
    # /api/hr/queue/ until they are marked as arrived.
    path('api/college-referrals/', CollegeReferralAPIView.as_view(), name='college-referrals'),
    path('api/hr/action/', HRApplicationActionAPIView.as_view(), name='hr-action'),
    # Applications belonging to closed cycles. Filtered, sorted and PAGED on
    # the server: a cycle holds hundreds or thousands of records, and the screen
    # used to fetch and serialise every one of them to draw twenty-five.
    path('api/hr/archives/', HRArchiveAPIView.as_view(), name='hr-archives'),
    # ONE archived record, in the shape the live drawer consumes. Separate
    # because it is the expensive half -- documents, requirements, timeline and
    # academic details -- and building that for a whole cycle just in case one
    # record was opened is what made the archive screen unusable.
    path('api/hr/archives/record/', HRArchiveRecordAPIView.as_view(), name='hr-archive-record'),
    path('api/hr/documents/override/', HRDocumentOverrideAPIView.as_view(), name='hr-doc-override'),

    # ==========================================================================
    # SIGNATURE AUTHORITY
    #
    # An HR-APP's signature is stamped onto every offer letter they issue, so
    # replacing one needs a SYS-ADMIN's approval. The image endpoint is the only
    # way to see a signature: they are stored outside every served directory,
    # because a signature that can be downloaded is a signature that can be
    # reused on anything.
    # ==========================================================================
    path('api/signatures/', SignatureAPIView.as_view(), name='signatures'),
    path('api/signatures/image/', SignatureImageView.as_view(), name='signature-image'),

    # ==========================================================================
    # OFFER LETTERS
    #
    #   /issue/       HR-APP signs and issues, one application or twenty
    #   /file/        HR-OPS downloads the signed PDF, or an UNSIGNED Word copy
    #   /correction/  HR-OPS uploads a corrected PDF; HR-APP approves or returns
    #   /handover/    HR-OPS confirms the hard copies and the intern joins
    #
    # The Word copy carries no signature by design: it is downloaded as a matter
    # of routine, and a signature inside a Word file can be lifted in three
    # clicks. A corrected letter gets its signature when HR-APP approves it.
    # ==========================================================================
    path('api/offer-letters/issue/', OfferLetterAPIView.as_view(), name='offer-letter-issue'),
    path('api/offer-letters/file/', OfferLetterAPIView.as_view(), name='offer-letter-file'),
    path('api/offer-letters/correction/', OfferLetterCorrectionAPIView.as_view(), name='offer-letter-correction'),
    path('api/offer-letters/handover/', OfferHandoverAPIView.as_view(), name='offer-letter-handover'),

    # ==========================================================================
    # THE CLEARANCE STAGE AND THE COMPLETION CERTIFICATE
    #
    #   /dmra-session/            HR-OPS schedules the Academy session. SET ONCE:
    #                             the candidate is told this date, so it locks.
    #   /clearance/               PATCH saves progress as it arrives over days;
    #                             POST submits for review, or rejects on an
    #                             Unsatisfactory evaluation.
    #   /certificates/issue/      HR-APP signs and issues, one or many. PATCH
    #                             returns the clearance to HR-OPS with a reason.
    #   /certificates/file/       view the signed PDF, or the UNSIGNED Word copy
    #   /certificates/correction/ HR-APP uploads a corrected PDF and re-approves
    #                             it -- both ends the same person, deliberately
    #   /certificates/dispatch/   sends it to the candidate and closes the
    #                             internship. The email is recorded as PENDING
    #                             until the mail engine exists.
    # ==========================================================================
    path('api/dmra-session/', DMRASessionAPIView.as_view(), name='dmra-session'),
    path('api/clearance/', ClearanceAPIView.as_view(), name='clearance'),
    path('api/certificates/issue/', CertificateAPIView.as_view(), name='certificate-issue'),
    path('api/certificates/file/', CertificateAPIView.as_view(), name='certificate-file'),
    path('api/certificates/correction/', CertificateCorrectionAPIView.as_view(), name='certificate-correction'),
    path('api/certificates/dispatch/', CertificateDispatchAPIView.as_view(), name='certificate-dispatch'),

    path('api/audit-ledger/', HRAuditLedgerAPIView.as_view(), name='audit-ledger'),
    path('api/admin/iam/', IAMUserAPIView.as_view(), name='admin-iam'),
    path('api/admin/cycles/', AdminCycleAPIView.as_view(), name='admin-cycles'),
    path('api/admin/configs/', AdminConfigAPIView.as_view(), name='admin-configs'),
    path('api/admin/export/', UniversalExportAPIView.as_view(), name='admin-export'),
]