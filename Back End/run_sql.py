"""
Execute a .sql file against the project database using Django's own connection.

Useful when the `mysql` command line client is not installed locally, which
makes `manage.py dbshell` unavailable. Credentials are read from settings.py,
so nothing needs to be retyped or stored anywhere.

Place this file next to manage.py and run:

    python3 run_sql.py ../DB/seed_dev_data.sql

Statements execute inside a single transaction. If any statement fails the
whole file is rolled back, so a partially applied script cannot be left behind.
"""

import os
import re
import sys

import django
from django.db import connection, transaction


def load_statements(path):
    """Read a .sql file and return its executable statements.

    Strips `--` line comments and skips USE statements, since Django is
    already connected to the correct database.
    """
    with open(path, 'r', encoding='utf-8') as handle:
        raw = handle.read()

    without_comments = '\n'.join(
        line for line in raw.splitlines()
        if not line.strip().startswith('--')
    )

    statements = []
    for chunk in without_comments.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        if re.match(r'^USE\s', chunk, re.IGNORECASE):
            continue
        statements.append(chunk)
    return statements


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 run_sql.py <path-to-file.sql>")
        return 1

    sql_path = sys.argv[1]
    if not os.path.exists(sql_path):
        print(f"File not found: {sql_path}")
        return 1

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dmrc_core.settings')
    django.setup()

    statements = load_statements(sql_path)
    print(f"Running {len(statements)} statement(s) from {sql_path}\n")

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                for index, statement in enumerate(statements, start=1):
                    preview = ' '.join(statement.split())[:70]
                    cursor.execute(statement)
                    print(f"  [{index}/{len(statements)}] OK  {preview}...")
    except Exception as error:
        print(f"\nFAILED -- everything was rolled back, the database is unchanged.\n\n{error}")
        return 1

    print("\nDone. All statements committed successfully.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
