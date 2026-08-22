# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class AcademicDetails(models.Model):
    academic_id = models.AutoField(primary_key=True)
    application = models.ForeignKey('Applications', models.DO_NOTHING)
    university_name = models.CharField(max_length=200, blank=True, null=True)
    # Mandatory on the preliminary intake form: for a college referral the
    # institution stands in place of the employee referrer.
    college_name = models.CharField(max_length=200)
    degree_program = models.CharField(max_length=100, blank=True, null=True)
    branch_name = models.CharField(max_length=100, blank=True, null=True)
    current_semester = models.CharField(max_length=20, blank=True, null=True)
    grading_system = models.CharField(max_length=10, blank=True, null=True)
    current_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'academic_details'


class ApplicationStatusHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    application = models.ForeignKey('Applications', models.DO_NOTHING)
    changed_by_user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    previous_status = models.CharField(max_length=50, blank=True, null=True)
    new_status = models.CharField(max_length=25)
    remarks = models.TextField(blank=True, null=True)
    changed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'application_status_history'


class ApplicationDrafts(models.Model):
    """Server-side wizard draft, owned by the referring employee.

    Partial by nature, so the form state lives in a JSON payload rather than in
    constrained columns. Ownership is by employee, which is what lets a referrer
    resume on any machine. Deleted once the draft becomes a real application.
    """
    draft_id = models.AutoField(primary_key=True)
    owner_employee = models.ForeignKey('Employees', models.CASCADE, db_column='owner_employee_id')
    cycle = models.ForeignKey('InternshipCycles', models.CASCADE, blank=True, null=True)
    candidate_name = models.CharField(max_length=150, blank=True, null=True)
    payload = models.JSONField()
    current_step = models.IntegerField(default=1)
    highest_step = models.IntegerField(default=1)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'application_drafts'


class Applications(models.Model):
    application_id = models.AutoField(primary_key=True)
    application_code = models.CharField(unique=True, max_length=50, blank=True, null=True)
    dmrc_reference_code = models.CharField(unique=True, max_length=50, blank=True, null=True)
    student = models.ForeignKey('Students', models.DO_NOTHING)
    referral_source = models.CharField(max_length=13)
    referrer_employee = models.ForeignKey('Employees', models.DO_NOTHING, blank=True, null=True)
    referrer_notification_email = models.CharField(max_length=150, blank=True, null=True)
    # Optional at intake: a college does not always say which department a
    # candidate is aimed at. Required by the Phase-1 form before submission.
    department = models.ForeignKey('Departments', models.DO_NOTHING, blank=True, null=True)
    cycle = models.ForeignKey('InternshipCycles', models.DO_NOTHING)
    # Chosen in the full application form, not at intake.
    duration_weeks = models.IntegerField(blank=True, null=True)
    is_ward = models.IntegerField(blank=True, null=True)
    accepted_declarations = models.IntegerField(blank=True, null=True)
    # approved_by_user was REMOVED: a second home for a fact already recorded
    # better elsewhere. Who approved an application lives in
    # ApplicationStatusHistory, with the timestamp and remarks beside it.
    form_correction_remarks = models.TextField(blank=True, null=True)
    # 'Invalid Document' | 'No Show' | 'Withdrawn' | 'Other' |
    # 'Unsatisfactory Evaluation'. The last closes an internship that was
    # actually served but failed its mentor's assessment -- without it that
    # person is filed identically to a candidate rejected months earlier for a
    # bad photograph.
    rejection_category = models.CharField(max_length=26, blank=True, null=True)
    approval_reference_id = models.CharField(max_length=100, blank=True, null=True)
    is_admin_escalated = models.IntegerField(blank=True, null=True)

    # --- Offer letter issuance ---
    # offer_letter_issued_at is the "Dated:" printed on the letter. Stored
    # rather than computed, so a reprint next month still shows the date it was
    # signed.
    #
    # offer_letter_signature_path freezes the exact signature image used at the
    # moment of signing. Without it, an officer changing their signature would
    # silently alter every letter ever reprinted -- including letters signed by
    # somebody who has since left.
    offer_letter_issued_at = models.DateTimeField(blank=True, null=True)
    offer_letter_signed_by_user = models.ForeignKey(
        'Users', models.DO_NOTHING, blank=True, null=True,
        db_column='offer_letter_signed_by_user_id',
        related_name='offer_letters_signed',
    )
    offer_letter_signature_path = models.CharField(max_length=500, blank=True, null=True)

    # --- The mentor's evaluation and clearance checklist ---
    # 'Unsatisfactory' ends the internship WITHOUT a certificate: the
    # certificate's wording is unconditionally complimentary and there is no
    # honest version of it for a failed assessment. The application is rejected
    # under its own category instead.
    #
    # approval_reference_id above is THE FILE NUMBER, typed at Submit for Final
    # Review. Stored and shown in the drawer, never printed on the certificate.
    mentor_evaluation_result = models.CharField(max_length=14, blank=True, null=True)
    mentor_evaluation_remarks = models.TextField(blank=True, null=True)
    attendance_record_verified = models.IntegerField(default=0)
    project_report_verified = models.IntegerField(default=0)
    # Printed on the certificate, in quotation marks.
    project_report_title = models.CharField(max_length=255, blank=True, null=True)
    clearance_submitted_at = models.DateTimeField(blank=True, null=True)

    # --- Certificate issuance ---
    # The same three fields as the offer letter, for the same reasons: the issue
    # date is stored rather than computed so a reprint shows the date it was
    # signed, and the signature path is frozen at signing so a later change of
    # signature cannot silently alter a certificate already issued.
    certificate_issued_at = models.DateTimeField(blank=True, null=True)
    certificate_signed_by_user = models.ForeignKey(
        'Users', models.DO_NOTHING, blank=True, null=True,
        db_column='certificate_signed_by_user_id',
        related_name='certificates_signed',
    )
    certificate_signature_path = models.CharField(max_length=500, blank=True, null=True)

    # --- Dispatch ---
    # 'Pending' | 'Sent' | 'Failed'. Dispatching records the certificate as
    # issued to the candidate with the email OWED, so the pipeline completes
    # without the portal claiming to have sent a message it never sent.
    certificate_dispatched_at = models.DateTimeField(blank=True, null=True)
    certificate_email_status = models.CharField(max_length=7, blank=True, null=True)

    # --- Handover confirmation ---
    # The two hard-copy declarations HR-OPS collects on the intern's first day
    # before marking them Joined. These are physical documents: nothing is
    # uploaded, so the tick IS the record.
    hardcopy_undertaking_received = models.IntegerField(default=0)
    hardcopy_attendance_received = models.IntegerField(default=0)
    handover_completed_at = models.DateTimeField(blank=True, null=True)

    status = models.CharField(max_length=25, blank=True, null=True)
    is_waitlisted = models.IntegerField(blank=True, null=True)
    is_no_show = models.IntegerField(blank=True, null=True)
    is_resubmitted = models.IntegerField(blank=True, null=True)
    # TRUE while a Rejected application is parked with the referrer awaiting a
    # correction or no-show response. Cleared when the referrer resubmits.
    awaiting_referrer_action = models.IntegerField(default=0)
    # doj_reschedule_expires_at was REMOVED: no expiry concept exists in the
    # design. The one-reschedule rule runs entirely off the count below.
    doj_reschedules_count = models.IntegerField()
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'applications'


class ArchivedAcademicDetails(models.Model):
    archive_academic_id = models.AutoField(primary_key=True)
    original_application_id = models.IntegerField()
    university_name = models.CharField(max_length=200, blank=True, null=True)
    college_name = models.CharField(max_length=200)
    degree_program = models.CharField(max_length=100, blank=True, null=True)
    branch_name = models.CharField(max_length=100, blank=True, null=True)
    current_semester = models.CharField(max_length=20, blank=True, null=True)
    grading_system = models.CharField(max_length=20, blank=True, null=True)
    current_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'archived_academic_details'


class ArchivedApplications(models.Model):
    archive_id = models.AutoField(primary_key=True)
    original_application_id = models.IntegerField()
    application_code = models.CharField(max_length=50, blank=True, null=True)
    dmrc_reference_code = models.CharField(max_length=50, blank=True, null=True)
    # THE CANDIDATE, IN FULL. An archived record is shown through the SAME
    # drawer as a live application, so every field that drawer displays has to
    # survive archiving. The seven added here used to be discarded at closure.
    student_salutation = models.CharField(max_length=10, blank=True, null=True)
    student_name = models.CharField(max_length=150)
    student_fathers_name = models.CharField(max_length=150, blank=True, null=True)
    student_gender = models.CharField(max_length=6, blank=True, null=True)
    student_date_of_birth = models.DateField(blank=True, null=True)
    student_email = models.CharField(max_length=150)
    student_mobile = models.CharField(max_length=20, blank=True, null=True)
    student_aadhaar = models.CharField(max_length=12, blank=True, null=True)
    student_permanent_address = models.TextField(blank=True, null=True)
    student_emergency_contact_name = models.CharField(max_length=150, blank=True, null=True)
    student_emergency_contact_mobile = models.CharField(max_length=20, blank=True, null=True)
    college_name = models.CharField(max_length=200)
    # A referral rejected before its form was filled archives with these blank.
    branch_name = models.CharField(max_length=100, blank=True, null=True)
    grading_system = models.CharField(max_length=20, blank=True, null=True)
    current_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    department_name = models.CharField(max_length=100, blank=True, null=True)
    allotted_sub_department = models.CharField(max_length=100, blank=True, null=True)
    session_term = models.CharField(max_length=20)
    application_year = models.IntegerField()
    duration_weeks = models.IntegerField(blank=True, null=True)
    status = models.CharField(max_length=50)
    is_waitlisted = models.IntegerField(blank=True, null=True)
    is_no_show = models.IntegerField(blank=True, null=True)
    is_employee_ward = models.IntegerField(blank=True, null=True)
    referral_source = models.CharField(max_length=50, blank=True, null=True)
    referrer_name = models.CharField(max_length=150, blank=True, null=True)
    referrer_employee_code = models.CharField(max_length=50, blank=True, null=True)
    # The referrer's post and unit AS THEY WERE. An employee is promoted or
    # transferred and the directory moves with them; the record of who
    # sponsored this candidate must not.
    referrer_designation = models.CharField(max_length=100, blank=True, null=True)
    referrer_department = models.CharField(max_length=100, blank=True, null=True)
    referrer_notification_email = models.CharField(max_length=150, blank=True, null=True)
    # Three dates. REQUESTED is what the referrer asked for, ALLOTTED is what HR
    # granted, ACTUAL is when they walked in. A candidate scheduled and then
    # rejected never joined, so actual is empty while the date they were told to
    # report on still matters -- and the gap between the first two is the record
    # of a scheduling decision somebody made.
    requested_date_of_joining = models.DateField(blank=True, null=True)
    allotted_date_of_joining = models.DateField(blank=True, null=True)
    actual_date_of_joining = models.DateField(blank=True, null=True)
    dmra_session_date = models.DateField(blank=True, null=True)
    dmra_attended = models.IntegerField(blank=True, null=True)
    date_of_completion = models.DateField(blank=True, null=True)
    rejection_category = models.CharField(max_length=50, blank=True, null=True)
    # The signer is kept by NAME rather than as a link to Users, for the reason
    # ArchivedStatusHistory keeps its actors that way: staff leave and accounts
    # are removed, but an archived letter must still say who signed it.
    offer_letter_issued_at = models.DateTimeField(blank=True, null=True)
    offer_letter_signed_by_name = models.CharField(max_length=150, blank=True, null=True)
    offer_letter_signed_by_designation = models.CharField(max_length=100, blank=True, null=True)
    # HANDOVER. The two hard-copy declarations collected on the first day. These
    # are physical documents: nothing is uploaded, so the tick IS the record and
    # it has to survive closure or the archive cannot answer whether they were
    # ever collected.
    hardcopy_undertaking_received = models.BooleanField(default=False)
    hardcopy_attendance_received = models.BooleanField(default=False)
    handover_completed_at = models.DateTimeField(blank=True, null=True)
    # The clearance record and who signed the certificate, kept by NAME for the
    # reason every archived actor is: staff leave and accounts are removed, but
    # an archived certificate must still say who signed it.
    #
    # THESE EXISTED AND WERE NEVER WRITTEN. archive_cycle_records populated the
    # offer-letter fields and skipped these, so every intern who completed was
    # archived with no evaluation, no project title and no record of who signed
    # their certificate -- destroyed at closure, not merely hidden.
    mentor_evaluation_result = models.CharField(max_length=20, blank=True, null=True)
    mentor_evaluation_remarks = models.TextField(blank=True, null=True)
    project_report_title = models.CharField(max_length=255, blank=True, null=True)
    attendance_record_verified = models.BooleanField(default=False)
    project_report_verified = models.BooleanField(default=False)
    certificate_issued_at = models.DateTimeField(blank=True, null=True)
    certificate_signed_by_name = models.CharField(max_length=150, blank=True, null=True)
    certificate_signed_by_designation = models.CharField(max_length=100, blank=True, null=True)
    # DISPATCH. 'Pending' is a real answer: the certificate was issued but the
    # email was never sent. After closure this is the only place that survives.
    certificate_dispatched_at = models.DateTimeField(blank=True, null=True)
    certificate_email_status = models.CharField(max_length=7, blank=True, null=True)
    # What HR-APP wrote when returning an application. For a rejected candidate
    # this is often the clearest statement of what went wrong.
    form_correction_remarks = models.TextField(blank=True, null=True)
    approval_reference_id = models.CharField(max_length=100, blank=True, null=True)
    is_admin_escalated = models.IntegerField(blank=True, null=True)
    is_resubmitted = models.IntegerField(blank=True, null=True)
    # doj_reschedule_expires_at was REMOVED: no expiry concept exists in the
    # design. The one-reschedule rule runs entirely off the count below.
    doj_reschedules_count = models.IntegerField()
    archived_year = models.IntegerField()
    created_at = models.DateTimeField()
    archived_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'archived_applications'


class ArchivedDocuments(models.Model):
    """A document belonging to an archived application.

    The FILE stays where it was on disk, under PROTECTED_DOCUMENT_ROOT; only its
    path is recorded here. original_document_id is what lets the secure viewer
    resolve an existing link after the live Documents row has been deleted.
    """
    archive_doc_id = models.AutoField(primary_key=True)
    original_application_id = models.IntegerField()
    original_document_id = models.IntegerField(blank=True, null=True)
    application_code = models.CharField(max_length=50, blank=True, null=True)
    is_system_generated = models.BooleanField(default=False)
    # A PLAIN NUMBER, deliberately not a foreign key: the type may since have
    # been disabled or deleted and that may not make this record unreadable.
    # Carried because the drawer matches a file to its requirement slot by a key
    # built from this id -- with only the NAME stored, an archived record showed
    # every requirement as unsupplied while the file sat right there.
    doc_type_id = models.IntegerField(blank=True, null=True)
    doc_type_name = models.CharField(max_length=100)
    file_path = models.CharField(max_length=500)
    # Mirrors documents.version so an archived record still shows which revision
    # of a document was the live one when the application was closed.
    version = models.IntegerField(default=1)
    is_manually_overridden = models.IntegerField(blank=True, null=True)
    verification_status = models.CharField(max_length=50, blank=True, null=True)
    hr_remarks = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'archived_documents'


# ------------------------------------------------------------------------------
# COLLEGE REFERRALS -- no model, and none is needed.
#
# An earlier design held institutional candidates in a `college_referral_drafts`
# table until their details were complete. That model has been REMOVED along
# with its table, because a record living outside `applications` can have
# neither a timeline (application_status_history is keyed to an application) nor
# a ticket number -- and the finished design requires both from the moment of
# intake, plus the ability to appear in the main pipeline's Rejected list.
#
# A college referral is therefore an ORDINARY Applications row from the outset:
#
#     referral_source = 'Institutional'    (referrer_employee is None)
#     status          = 'Intake Draft' -> 'Pending Arrival' -> 'Ready for Merge'
#
# On arrival it joins the main pipeline at 'Pending Offer Letter' and behaves
# exactly like an employee referral thereafter.
# ------------------------------------------------------------------------------


class CycleDepartmentCapacities(models.Model):
    capacity_id = models.AutoField(primary_key=True)
    cycle = models.ForeignKey('InternshipCycles', models.DO_NOTHING)
    department = models.ForeignKey('Departments', models.DO_NOTHING)
    max_capacity = models.IntegerField()
    seats_occupied = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'cycle_department_capacities'
        unique_together = (('cycle', 'department'),)


class CycleDocumentRequirements(models.Model):
    """One document, as configured FOR ONE CYCLE.

    DMRC runs concurrent cycles, so a document's mandatory flag, enabled flag
    and accepted formats all belong here rather than on DocumentTypes. The
    columns of the same name on DocumentTypes are the catalogue DEFAULT applied
    when a document is first added to a cycle; changing them must never alter a
    cycle that is already configured.
    """
    requirement_id = models.AutoField(primary_key=True)
    cycle = models.ForeignKey('InternshipCycles', models.DO_NOTHING)
    doc_type = models.ForeignKey('DocumentTypes', models.DO_NOTHING)
    is_mandatory = models.IntegerField(blank=True, null=True)
    is_enabled = models.BooleanField(default=True)
    allowed_extensions = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cycle_document_requirements'
        unique_together = (('cycle', 'doc_type'),)


class CycleJoiningDates(models.Model):
    date_id = models.AutoField(primary_key=True)
    cycle = models.ForeignKey('InternshipCycles', models.DO_NOTHING)
    allowed_doj = models.DateField()
    is_active = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cycle_joining_dates'
        unique_together = (('cycle', 'allowed_doj'),)


class CycleSubDepartments(models.Model):
    mapping_id = models.AutoField(primary_key=True)
    cycle = models.ForeignKey('InternshipCycles', models.DO_NOTHING)
    sub_department = models.ForeignKey('SubDepartments', models.DO_NOTHING)
    is_active = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cycle_sub_departments'
        unique_together = (('cycle', 'sub_department'),)


class Departments(models.Model):
    department_id = models.AutoField(primary_key=True)
    department_name = models.CharField(unique=True, max_length=100)

    class Meta:
        managed = False
        db_table = 'departments'


class DocumentTypes(models.Model):
    doc_type_id = models.AutoField(primary_key=True)
    type_name = models.CharField(unique=True, max_length=100)
    allowed_extensions = models.CharField(max_length=100, blank=True, null=True)
    max_size_mb = models.IntegerField(blank=True, null=True)
    is_system_generated = models.IntegerField(blank=True, null=True)
    is_active = models.IntegerField(blank=True, null=True)
    # Shipped with the portal: may be enabled or disabled, never deleted.
    is_core = models.IntegerField(default=0)
    # Collecting this document needs explicit applicant consent (Aadhaar).
    # The consent checkbox and the Aadhaar number field both follow this flag.
    requires_consent = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'document_types'


class ApplicationDocumentRequirements(models.Model):
    """Per-application snapshot of the document rules, frozen at submission.

    An application is judged against the rules in force when it was submitted,
    not the rules as they stand today. doc_type_name is stored alongside the FK
    so the record stays readable if a custom document type is later deleted.
    """
    requirement_id = models.AutoField(primary_key=True)
    application = models.ForeignKey('Applications', models.CASCADE)
    doc_type = models.ForeignKey('DocumentTypes', models.SET_NULL, blank=True, null=True)
    doc_type_name = models.CharField(max_length=100)
    allowed_extensions = models.CharField(max_length=100, default='.pdf,.jpg,.jpeg')
    is_mandatory = models.IntegerField(default=1)
    requires_consent = models.IntegerField(default=0)
    display_order = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'application_document_requirements'


class Documents(models.Model):
    document_id = models.AutoField(primary_key=True)
    application = models.ForeignKey(Applications, models.DO_NOTHING)
    doc_type = models.ForeignKey(DocumentTypes, models.DO_NOTHING)
    file_path = models.CharField(max_length=500)
    # --- Versioning ---
    # is_current is deliberately NULLable: 1 = the single live document for this
    # (application, doc_type); NULL = superseded. The DB index uq_doc_current
    # relies on NULLs being distinct to permit many superseded rows but only one
    # live row. NEVER read documents without filtering is_current=1 -- use
    # current_documents() / supersede_document() in views.py.
    version = models.IntegerField(default=1)
    is_current = models.IntegerField(blank=True, null=True, default=1)
    superseded_at = models.DateTimeField(blank=True, null=True)
    is_manually_overridden = models.IntegerField(blank=True, null=True)
    verification_status = models.CharField(max_length=8, blank=True, null=True)
    hr_remarks = models.TextField(blank=True, null=True)

    # --- The correction loop ---
    # A corrected offer letter uploaded by HR-OPS must NOT become the official
    # document until HR-APP approves it. That state is neither current nor
    # superseded, so it gets its own flag, NULLable for exactly the same reason
    # is_current is:
    #
    #   is_pending_approval = 1     awaiting HR-APP's decision (is_current NULL)
    #   is_pending_approval = NULL  everything else
    #
    # uq_doc_pending then permits at most ONE pending upload per document per
    # application, enforced by the database rather than by trust.
    #
    # NEVER treat a pending row as live: it must not appear in the document
    # vault, in the archive, or anywhere a document is read for its content.
    is_pending_approval = models.IntegerField(blank=True, null=True, default=None)
    uploaded_by_user = models.ForeignKey(
        'Users', models.DO_NOTHING, blank=True, null=True,
        db_column='uploaded_by_user_id', related_name='documents_uploaded',
    )
    reviewed_by_user = models.ForeignKey(
        'Users', models.DO_NOTHING, blank=True, null=True,
        db_column='reviewed_by_user_id', related_name='documents_reviewed',
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    # HR-APP's mandatory reason when sending a corrected letter back. Kept apart
    # from hr_remarks, which belongs to document VERIFICATION during the Phase-1
    # check and answers a different question.
    approval_remarks = models.TextField(blank=True, null=True)

    uploaded_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'documents'


class Employees(models.Model):
    """Mirrors the DMRC employee directory.

    Every field here must be obtainable from the intranet, because that is where
    these rows come from. There is deliberately no salutation: DMRC IT confirmed
    the directory does not hold one. Students DO have a salutation -- the
    candidate types it into the Phase-1 form -- and that is a different field.
    """
    employee_id = models.AutoField(primary_key=True)
    employee_code = models.CharField(unique=True, max_length=50)
    full_name = models.CharField(max_length=150)
    designation = models.CharField(max_length=100)
    department = models.ForeignKey(Departments, models.DO_NOTHING)
    official_email = models.CharField(unique=True, max_length=150)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'employees'


class InternshipCycles(models.Model):
    cycle_id = models.AutoField(primary_key=True)
    session_term = models.CharField(max_length=6)
    application_year = models.IntegerField()
    application_start_date = models.DateField()
    application_end_date = models.DateField()
    is_active = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'internship_cycles'
        unique_together = (('session_term', 'application_year'),)


class JoiningDetails(models.Model):
    joining_id = models.AutoField(primary_key=True)
    application = models.OneToOneField(Applications, models.DO_NOTHING)
    # An employee referrer REQUESTS a date; HR ALLOTS one for a college
    # referral, so this stays empty for institutional records.
    requested_doj = models.DateField(blank=True, null=True)
    allotted_date_of_joining = models.DateField(blank=True, null=True)
    allotted_sub_department = models.ForeignKey('SubDepartments', models.DO_NOTHING, blank=True, null=True)
    # REMOVED: reporting_time, reporting_officer, assigned_room_location and
    # documents_to_carry -- joining instructions from an earlier design. The
    # document builders receive a plain context dictionary that never carried
    # any of them, and the offer letter is addressed to the Head of Department
    # rather than to the candidate.
    actual_date_of_joining = models.DateField(blank=True, null=True)
    dmra_session_date = models.DateField(blank=True, null=True)
    dmra_attended = models.IntegerField(blank=True, null=True)
    date_of_completion = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'joining_details'


class Notifications(models.Model):
    notification_id = models.AutoField(primary_key=True)
    application = models.ForeignKey(Applications, models.DO_NOTHING, blank=True, null=True)
    notification_type = models.CharField(max_length=29)
    recipient_email = models.CharField(max_length=150)
    subject = models.CharField(max_length=150)
    message = models.TextField()
    delivery_status = models.CharField(max_length=7, blank=True, null=True)
    queued_at = models.DateTimeField(blank=True, null=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'notifications'


class Roles(models.Model):
    role_id = models.AutoField(primary_key=True)
    role_name = models.CharField(unique=True, max_length=50)
    permissions_level = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'roles'


class Students(models.Model):
    """A candidate. Most fields are optional AT THE DATABASE LEVEL only.

    An employee referral always arrives complete -- the Phase-1 form refuses to
    submit with anything blank. A COLLEGE referral does not: it begins as a
    preliminary record holding only what the institution sent, and is completed
    later when HR corresponds with the candidate.

    Completeness is enforced by the submission form and, for institutional
    records, by the merge check on the server. Do NOT reinstate these as
    required fields -- doing so makes a half-collected candidate impossible to
    store, which is the whole state the College Referrals section manages.

    full_name and personal_email are mandatory on the preliminary form, so they
    stay required here too.
    """
    student_id = models.AutoField(primary_key=True)
    salutation = models.CharField(max_length=10, blank=True, null=True)
    full_name = models.CharField(max_length=150)
    fathers_name = models.CharField(max_length=150, blank=True, null=True)
    gender = models.CharField(max_length=6, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    personal_email = models.CharField(max_length=150)
    aadhaar_number = models.CharField(max_length=12, blank=True, null=True)
    permanent_address = models.TextField(blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True, null=True)
    emergency_contact_mobile = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'students'


class SubDepartments(models.Model):
    sub_department_id = models.AutoField(primary_key=True)
    sub_department_name = models.CharField(unique=True, max_length=100)
    is_global_active = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'sub_departments'


class SystemAuditLogs(models.Model):
    log_id = models.BigAutoField(primary_key=True)
    actor_user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    role_name = models.CharField(max_length=50, blank=True, null=True)
    action_type = models.CharField(max_length=100)
    target_entity_type = models.CharField(max_length=50)
    target_entity_id = models.IntegerField()
    old_value = models.JSONField(blank=True, null=True)
    new_value = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'system_audit_logs'


class Users(models.Model):
    user_id = models.AutoField(primary_key=True)
    role = models.ForeignKey(Roles, models.DO_NOTHING)
    employee = models.OneToOneField(Employees, models.DO_NOTHING)
    username = models.CharField(unique=True, max_length=100)
    email = models.CharField(unique=True, max_length=150)
    # --- Signature authority ---
    # An HR-APP's signature is stamped onto every offer letter they issue, so
    # replacing one is an administrative act rather than a preference:
    #
    #   HR-APP uploads     -> pending_signature_path set, status 'Pending'
    #   SYS-ADMIN approves -> pending becomes active, pending cleared
    #   SYS-ADMIN rejects  -> pending cleared and quarantined, reason recorded
    #
    # The ACTIVE signature keeps working throughout: an officer waiting on a
    # decision carries on issuing letters with their existing one.
    #
    # Both paths are relative to SIGNATURE_ROOT, which sits outside MEDIA_ROOT.
    # A signature reachable by URL is a signature that can be lifted and reused.
    active_signature_path = models.CharField(max_length=500, blank=True, null=True)
    pending_signature_path = models.CharField(max_length=500, blank=True, null=True)
    signature_approval_status = models.CharField(max_length=8, blank=True, null=True)
    signature_uploaded_at = models.DateTimeField(blank=True, null=True)
    signature_activated_at = models.DateTimeField(blank=True, null=True)
    signature_reviewed_at = models.DateTimeField(blank=True, null=True)
    # Self-referencing: the reviewer is another user, always a SYS-ADMIN.
    signature_reviewed_by_user = models.ForeignKey(
        'self', models.DO_NOTHING, blank=True, null=True,
        db_column='signature_reviewed_by_user_id', related_name='signatures_reviewed',
    )
    # A SYS-ADMIN must say why when refusing a signature.
    signature_rejection_reason = models.TextField(blank=True, null=True)
    is_active = models.IntegerField(blank=True, null=True)
    status_updated_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'users'

class ArchivedStatusHistory(models.Model):
    """The timeline of an archived application.

    Hard-closing a cycle deletes its applications, and ApplicationStatusHistory
    cascades with them -- so without this the timeline would be destroyed by
    archiving. For a college referral rejected before its form was ever filled,
    the timeline is the only record of what happened.

    The actor is stored by name and role rather than as a link to Users: staff
    leave and accounts are removed, but an archived decision must still say who
    took it.
    """
    archive_history_id = models.AutoField(primary_key=True)
    original_application_id = models.IntegerField()
    application_code = models.CharField(max_length=50, blank=True, null=True)
    previous_status = models.CharField(max_length=50, blank=True, null=True)
    new_status = models.CharField(max_length=50)
    changed_by_name = models.CharField(max_length=150, blank=True, null=True)
    changed_by_role = models.CharField(max_length=50, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    changed_at = models.DateTimeField(blank=True, null=True)
    archived_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'archived_status_history'


class ArchivedDocumentRequirements(models.Model):
    """What an archived application was ASKED to supply.

    Distinct from ArchivedDocuments, which records what was actually supplied.
    Without both, the archive cannot tell "this cycle never asked for a
    recommendation letter" from "it was asked for and the candidate declined".

    Holds the document NAME, never a link to DocumentTypes: the type may since
    have been disabled, reconfigured or deleted, and none of that may alter the
    record of what this candidate was asked for.
    """
    archive_requirement_id = models.AutoField(primary_key=True)
    original_application_id = models.IntegerField()
    application_code = models.CharField(max_length=50, blank=True, null=True)
    # Same reasoning as ArchivedDocuments.doc_type_id: a plain number, never a
    # link, carried so the drawer can pair a requirement with the file that
    # satisfied it. The NAME below remains the thing displayed.
    doc_type_id = models.IntegerField(blank=True, null=True)
    doc_type_name = models.CharField(max_length=100)
    allowed_extensions = models.CharField(max_length=100, blank=True, null=True)
    is_mandatory = models.BooleanField(default=True)
    requires_consent = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    was_supplied = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'archived_document_requirements'


class ArchivedCycleJoiningDates(models.Model):
    """The joining dates an administrator APPROVED for a cycle, frozen at close.

    The archive's Date of Joining filter is the same calendar used everywhere
    else in the portal, and it marks three kinds of day:

        approved and used        a normal intake date
        approved, never used     offered, nobody was allotted it
        used but NEVER approved  an exception was made for that candidate

    The third is why this table exists. HR may allot ANY date when scheduling,
    including one outside the approved calendar, and after closure this is the
    only way to see that it happened.

    A SNAPSHOT, not a link. Archiving does not delete internship_cycles or
    cycle_joining_dates -- it only sets is_active = 0 -- so the live rows do
    survive today. They are copied anyway, for the reason every archived table
    copies rather than links: a future tidy-up of old cycle rows would blank
    this calendar while the records it describes sat there perfectly intact.

    was_enabled records whether the date was still active at closure. A date an
    administrator WITHDREW mid-cycle can still have people allotted to it, so
    dropping the withdrawn ones would misreport those candidates as exceptions.
    """
    archive_doj_id = models.AutoField(primary_key=True)
    session_term = models.CharField(max_length=20)
    application_year = models.IntegerField()
    allowed_doj = models.DateField()
    was_enabled = models.BooleanField(default=True)
    archived_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'archived_cycle_joining_dates'