"""Remove seven columns nothing reads or writes.

Each was audited across views.py, models.py, urls.py, permissions.py,
serializers.py, admin.py, identity/* and documents/*, and against both front-end
files. None appears anywhere. The database was checked before this was written
and every one of them was empty, so nothing is lost by dropping them.

WHAT GOES, AND WHY
------------------
joining_details.reporting_time
joining_details.reporting_officer_id
joining_details.assigned_room_location
joining_details.documents_to_carry
    Joining instructions from an earlier design -- what time to arrive, who to
    report to, which room, what to bring. The offer letter cannot print any of
    it: the builders in documents/ receive a plain context dictionary, and that
    dictionary carries the application code, dates, course, college, duration,
    sub-department and signatory, and nothing else. The letter is addressed to
    the Head of Department in any case, not to the candidate.

applications.approved_by_user_id
    A second home for a fact already recorded better elsewhere. Who approved an
    application lives in application_status_history, with the timestamp and the
    remarks beside it. This column was never once populated.

applications.doj_reschedule_expires_at
archived_applications.doj_reschedule_expires_at
    A deadline for a rescheduled joining date. The one-reschedule rule is
    enforced entirely through doj_reschedules_count, and no expiry concept
    exists anywhere in the design -- only the counting half was ever built. The
    archived copy goes with the live one: an archive field recording something
    the system has no concept of is worse than no field at all.

WHAT STAYS
----------
roles.permissions_level and document_types.max_size_mb are equally unread, and
are deliberately kept. See the note at the foot of this file.

FOREIGN KEYS COME OFF FIRST
---------------------------
Two of these columns carry named constraints -- fk_joining_officer and
fk_app_approver -- and a column cannot be dropped while a foreign key still
references it.

TiDB only began enforcing foreign keys in v6.6; before that it PARSED them and
silently ignored them. This database is v8.5.3, where they are real, so the
constraints should exist. But a database first built on an older version and
upgraded since would not have them, and dropping a constraint that is not there
fails the migration and rolls the whole thing back.

So each drop is guarded by a look in information_schema and skipped if the
constraint is absent. That runs correctly either way, and needs nobody to know
which version the database was originally created on.
"""

from django.db import migrations


# --- Foreign keys ------------------------------------------------------------
# (table, constraint name, the column it protects)
FOREIGN_KEYS = [
    ('joining_details', 'fk_joining_officer', 'reporting_officer_id'),
    ('applications', 'fk_app_approver', 'approved_by_user_id'),
]

# --- Columns -----------------------------------------------------------------
# (table, column, the definition needed to put it back)
COLUMNS = [
    ('joining_details', 'reporting_time', 'TIME NULL'),
    ('joining_details', 'reporting_officer_id', 'INT NULL'),
    ('joining_details', 'assigned_room_location', 'VARCHAR(100) NULL'),
    ('joining_details', 'documents_to_carry', 'TEXT NULL'),
    ('applications', 'approved_by_user_id', 'INT NULL'),
    ('applications', 'doj_reschedule_expires_at', 'TIMESTAMP NULL'),
    ('archived_applications', 'doj_reschedule_expires_at', 'TIMESTAMP NULL'),
]


def drop_foreign_keys(apps, schema_editor):
    """Drop each constraint, but only where it actually exists.

    Written as Python rather than as RunSQL because the decision has to be made
    against the live database. A plain ALTER would fail on any database whose
    foreign keys were never really created.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        for table, name, _column in FOREIGN_KEYS:
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                WHERE CONSTRAINT_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                  AND CONSTRAINT_NAME = %s
                  AND CONSTRAINT_TYPE = 'FOREIGN KEY'
                """,
                [table, name],
            )
            if cursor.fetchone()[0]:
                cursor.execute(f"ALTER TABLE {table} DROP FOREIGN KEY {name};")


def restore_foreign_keys(apps, schema_editor):
    """Put the constraints back, for a reversal.

    Only meaningful once the columns have been restored, which the reverse of
    the operations below does first -- Django runs a reversal in reverse order.
    """
    connection = schema_editor.connection
    references = {
        'fk_joining_officer': ('employees', 'employee_id'),
        'fk_app_approver': ('users', 'user_id'),
    }
    with connection.cursor() as cursor:
        for table, name, column in FOREIGN_KEYS:
            target_table, target_column = references[name]
            cursor.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                f"FOREIGN KEY ({column}) "
                f"REFERENCES {target_table}({target_column});"
            )


def _build_column_operations():
    """One ALTER per column.

    TiDB rejects multiple schema changes in a single ALTER TABLE on older
    versions. One statement per column is slower to read but runs anywhere,
    which matters more for a migration run once by somebody who did not write
    it. Same reasoning as 0002.
    """
    operations = []
    for table, column, definition in COLUMNS:
        operations.append(migrations.RunSQL(
            f"ALTER TABLE {table} DROP COLUMN {column};",
            f"ALTER TABLE {table} ADD COLUMN {column} {definition};",
        ))
    return operations


# --- The one view that referenced a dropped column ---------------------------
#
# vw_hr_application_status_tracker selects doj_reschedule_expires_at from BOTH
# applications and archived_applications.
#
# This is the part that would have caused trouble on deployment. Dropping a
# column a view depends on does NOT fail: the ALTER succeeds, the view survives,
# and it breaks silently -- every SELECT against it then returns "View
# references invalid table(s) or column(s)". Nothing in the portal reads these
# views, so the application would have carried on working perfectly while
# whoever connects Excel or a reporting tool to the database found one of the
# five views dead, with no obvious cause and no error at migration time.
#
# So the view is dropped BEFORE the columns and rebuilt after, in this same
# migration. The definition below matches Intern_Portal.sql exactly, minus the
# dropped column.
#
# The other four views were checked and none of them references any of the seven
# columns.
DROP_STATUS_TRACKER_VIEW = "DROP VIEW IF EXISTS vw_hr_application_status_tracker;"

REBUILD_STATUS_TRACKER_VIEW = """
CREATE OR REPLACE VIEW vw_hr_application_status_tracker AS
SELECT
    a.application_id AS id, s.full_name, a.status, a.referral_source, a.is_waitlisted, a.is_no_show,
    a.is_ward AS is_employee_ward, a.is_resubmitted,
    a.doj_reschedules_count,
    a.referrer_notification_email,
    d.department_name, a.created_at,
    'Live' AS record_source, ic.application_year AS report_year, ic.session_term AS cycle_name
FROM applications a
JOIN students s ON a.student_id = s.student_id
JOIN departments d ON a.department_id = d.department_id
JOIN internship_cycles ic ON a.cycle_id = ic.cycle_id
UNION ALL
SELECT
    original_application_id AS id, student_name AS full_name, status, referral_source, is_waitlisted, is_no_show,
    is_employee_ward, is_resubmitted,
    doj_reschedules_count,
    referrer_notification_email,
    department_name, created_at,
    'Archived' AS record_source, archived_year AS report_year, session_term AS cycle_name
FROM archived_applications;
"""

# The original definition, for a reversal. Valid again only once the columns
# have been restored, which is why it is the LAST operation below: Django runs a
# reversal in reverse order, so on the way back this runs after the columns
# return.
RESTORE_STATUS_TRACKER_VIEW = """
CREATE OR REPLACE VIEW vw_hr_application_status_tracker AS
SELECT
    a.application_id AS id, s.full_name, a.status, a.referral_source, a.is_waitlisted, a.is_no_show,
    a.is_ward AS is_employee_ward, a.is_resubmitted,
    a.doj_reschedule_expires_at, a.doj_reschedules_count,
    a.referrer_notification_email,
    d.department_name, a.created_at,
    'Live' AS record_source, ic.application_year AS report_year, ic.session_term AS cycle_name
FROM applications a
JOIN students s ON a.student_id = s.student_id
JOIN departments d ON a.department_id = d.department_id
JOIN internship_cycles ic ON a.cycle_id = ic.cycle_id
UNION ALL
SELECT
    original_application_id AS id, student_name AS full_name, status, referral_source, is_waitlisted, is_no_show,
    is_employee_ward, is_resubmitted,
    doj_reschedule_expires_at, doj_reschedules_count,
    referrer_notification_email,
    department_name, created_at,
    'Archived' AS record_source, archived_year AS report_year, session_term AS cycle_name
FROM archived_applications;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0002_archive_rebuild'),
    ]

    # ORDER MATTERS, and it is not the obvious one.
    #
    #   1. drop the view that depends on a doomed column
    #   2. drop the foreign keys protecting two of the columns
    #   3. drop the columns
    #   4. rebuild the view without the dropped column
    #
    # The view is removed FIRST rather than repaired afterwards, because engines
    # disagree about step 3 while a dependent view exists. MySQL and TiDB allow
    # it and leave the view silently broken; SQLite refuses the ALTER outright.
    # Taking the view out of the way first behaves identically everywhere and
    # does not depend on knowing which engine is underneath.
    #
    # Reversing runs these backwards, so the ORIGINAL view is recreated last --
    # by which point the columns it names are back.
    operations = [
        migrations.RunSQL(DROP_STATUS_TRACKER_VIEW,
                          RESTORE_STATUS_TRACKER_VIEW),
        migrations.RunPython(drop_foreign_keys, restore_foreign_keys),
    ] + _build_column_operations() + [
        migrations.RunSQL(REBUILD_STATUS_TRACKER_VIEW,
                          DROP_STATUS_TRACKER_VIEW),
    ]