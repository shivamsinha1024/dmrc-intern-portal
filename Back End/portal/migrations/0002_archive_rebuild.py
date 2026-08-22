"""Archive rebuild: everything the archived record drawer needs.

WHY THIS IS RAW SQL RATHER THAN CreateModel / AddField
------------------------------------------------------
Every model in portal/models.py is declared `managed = False`, so Django will
not emit schema for them. AddField would be recorded in the migration history
and change nothing in the database. The statements below are therefore written
out, and Intern_Portal.sql is updated to match so a database built from scratch
and a database migrated in place end up identical.

WHY ONE ALTER PER COLUMN
------------------------
TiDB rejects multiple schema changes in a single ALTER TABLE on older versions
("Unsupported multi schema change"). One statement per column is slower to read
but runs on every version DMRC might have deployed, which matters more for a
migration that will be run once, by somebody who did not write it.

WHAT THIS FIXES
---------------
Beyond the new columns, this closes a real data loss. The five certificate and
clearance columns already existed in archived_applications and were NEVER
WRITTEN by archive_cycle_records -- so every intern who actually completed was
archived with no evaluation, no project title, and no record of who signed
their certificate. Archiving is irreversible, so that data was destroyed at
closure rather than merely hidden. The columns are extended here; views.py is
what starts populating them.

Records archived BEFORE this migration cannot be repaired: the live rows they
were copied from are gone. Those records will show these fields blank.
"""

from django.db import migrations


# --- archived_applications: the fields the live drawer displays ---------------
#
# The archived record is now shown through the SAME drawer as a live
# application, so every field that drawer reads has to survive archiving.
ARCHIVED_APPLICATION_COLUMNS = [
    # The candidate. All seven were discarded at closure; the drawer's whole
    # personal block rendered blank on an archived record.
    ('student_salutation', 'VARCHAR(10) NULL'),
    ('student_fathers_name', 'VARCHAR(150) NULL'),
    ('student_gender', 'VARCHAR(6) NULL'),
    ('student_date_of_birth', 'DATE NULL'),
    ('student_permanent_address', 'TEXT NULL'),
    ('student_emergency_contact_name', 'VARCHAR(150) NULL'),
    ('student_emergency_contact_mobile', 'VARCHAR(20) NULL'),

    # The referrer's post and unit as they were. An employee is promoted or
    # transferred and the directory moves with them; the record of who
    # sponsored this candidate must not.
    ('referrer_designation', 'VARCHAR(100) NULL'),
    ('referrer_department', 'VARCHAR(100) NULL'),

    # What the referrer ASKED for, as against what HR granted. The gap between
    # the two is the record of a scheduling decision somebody made.
    ('requested_date_of_joining', 'DATE NULL'),

    # Offer letter and handover. The two hard-copy declarations are PHYSICAL
    # documents -- nothing is uploaded, so the tick is the only evidence they
    # were collected.
    ('offer_letter_signed_by_designation', 'VARCHAR(100) NULL'),
    ('hardcopy_undertaking_received', 'BOOLEAN NOT NULL DEFAULT FALSE'),
    ('hardcopy_attendance_received', 'BOOLEAN NOT NULL DEFAULT FALSE'),
    ('handover_completed_at', 'DATETIME NULL'),

    # Clearance and certificate.
    ('attendance_record_verified', 'BOOLEAN NOT NULL DEFAULT FALSE'),
    ('project_report_verified', 'BOOLEAN NOT NULL DEFAULT FALSE'),
    ('certificate_signed_by_designation', 'VARCHAR(100) NULL'),

    # Dispatch. 'Pending' is a real answer: the certificate was issued but the
    # email was never sent. After closure this is the only place it survives.
    ('certificate_dispatched_at', 'DATETIME NULL'),
    ('certificate_email_status', 'VARCHAR(7) NULL'),

    # What HR-APP wrote when returning an application. For a rejected candidate
    # this is often the clearest statement of what went wrong.
    ('form_correction_remarks', 'TEXT NULL'),
]

# --- Indexes -----------------------------------------------------------------
#
# archived_applications had NONE, while all four of its child tables had them.
# That was survivable while the archive screen loaded a whole cycle into the
# browser and filtered it there. Filtering now happens in SQL, across every year
# DMRC has ever run, so without these each filter is a full scan of the largest
# table in the database -- and the archive gets slower every year in a way
# nothing in testing would reveal.
INDEXES = [
    ('archived_applications', 'idx_arch_app_cycle',
     '(session_term, application_year)'),
    ('archived_applications', 'idx_arch_app_cycle_status',
     '(session_term, application_year, status)'),
    ('archived_applications', 'idx_arch_app_code', '(application_code)'),
    ('archived_applications', 'idx_arch_app_original',
     '(original_application_id)'),
    ('archived_applications', 'idx_arch_app_department', '(department_name)'),
    ('archived_applications', 'idx_arch_app_doj', '(actual_date_of_joining)'),
    ('archived_applications', 'idx_arch_app_completion', '(date_of_completion)'),
    # Read on every drawer open. Without it, opening one archived record scans
    # the whole table.
    ('archived_academic_details', 'idx_arch_acad_app',
     '(original_application_id)'),
    ('archived_documents', 'idx_arch_doc_app', '(original_application_id)'),
]


def _add_column(table, column, definition):
    return (
        f"ALTER TABLE {table} ADD COLUMN {column} {definition};",
        f"ALTER TABLE {table} DROP COLUMN {column};",
    )


def _build_operations():
    operations = []

    for column, definition in ARCHIVED_APPLICATION_COLUMNS:
        forward, backward = _add_column('archived_applications', column, definition)
        operations.append(migrations.RunSQL(forward, backward))

    # doc_type_id on both document tables.
    #
    # A PLAIN NUMBER, deliberately not a foreign key: the type may since have
    # been disabled or deleted, and none of that may make an archived record
    # unreadable. It is here because the drawer matches a file to its
    # requirement slot by a key built from this id. With only the NAME stored,
    # an archived record showed every requirement as unsupplied while the file
    # sat right there.
    for table in ('archived_documents', 'archived_document_requirements'):
        forward, backward = _add_column(table, 'doc_type_id', 'INT NULL')
        operations.append(migrations.RunSQL(forward, backward))

    for table, name, columns in INDEXES:
        operations.append(migrations.RunSQL(
            f"CREATE INDEX {name} ON {table} {columns};",
            f"DROP INDEX {name} ON {table};",
        ))

    return operations


# --- The archived joining calendar -------------------------------------------
#
# The archive's Date of Joining filter marks three kinds of day: approved and
# used, approved but never used, and used but NEVER approved. The third is why
# this table exists -- HR may allot ANY date when scheduling, including one
# outside the approved calendar, and after closure this is the only way to see
# that an exception was made.
#
# A SNAPSHOT, not a link. Archiving does not delete internship_cycles or
# cycle_joining_dates -- it only sets is_active = 0 -- so the live rows do
# survive today and could be read instead. They are copied for the reason every
# archived table copies rather than links: a future tidy-up of old cycle rows
# would blank this calendar while the records it describes sat there intact.
CREATE_ARCHIVED_JOINING_DATES = """
CREATE TABLE IF NOT EXISTS archived_cycle_joining_dates (
    archive_doj_id INT AUTO_INCREMENT PRIMARY KEY,
    session_term VARCHAR(20) NOT NULL,
    application_year INT NOT NULL,
    allowed_doj DATE NOT NULL,
    was_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_arch_doj_cycle (session_term, application_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

DROP_ARCHIVED_JOINING_DATES = "DROP TABLE IF EXISTS archived_cycle_joining_dates;"


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(CREATE_ARCHIVED_JOINING_DATES,
                          DROP_ARCHIVED_JOINING_DATES),
    ] + _build_operations()