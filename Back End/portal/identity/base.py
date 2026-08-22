"""
IDENTITY PROVIDER CONTRACT
==============================================================================

This portal does NOT authenticate anyone. It stores no passwords and runs no
login screen. Identity is supplied by DMRC's existing employee login system
(the "payslip login"); this portal only decides what an already-identified
employee is allowed to do here.

    DMRC payslip login  ->  WHO the person is        (identity)
    This portal         ->  WHAT they may do here    (authorisation)

------------------------------------------------------------------------------
FOR THE DMRC IT TEAM
------------------------------------------------------------------------------
Integrating this portal with the intranet requires implementing exactly ONE
method: IdentityProvider.get_employee_code(). Nothing else in the codebase
needs to change.

  1. Open portal/identity/intranet.py.
  2. Implement get_employee_code() so it returns the employee code of the
     signed-in user, using whatever mechanism the intranet provides -- SAML or
     OIDC assertion, LDAP/Active Directory lookup, a shared session cookie, or
     a header injected by the reverse proxy in front of this application.
  3. In settings.py, change IDENTITY_PROVIDER to point at that class.

The returned value must match employees.employee_code in the database. That
column is the single join key between this portal and the DMRC employee
directory.

Return None for an unauthenticated request; the portal will respond 401.

------------------------------------------------------------------------------
REQUIREMENTS ON THE RETURNED VALUE
------------------------------------------------------------------------------
STRIP SURROUNDING WHITESPACE. The lookup is an exact match on
employees.employee_code, so a trailing space -- easily picked up from an LDAP
attribute or a proxy header -- matches nothing, and every affected employee
receives a 401 with no indication why. Return code.strip(), or None if what is
left is empty.

Case does not matter. The schema uses a case-insensitive collation
(utf8mb4_unicode_ci), so 'emp-4471' and 'EMP-4471' resolve to the same row.

The FORMAT must match what is loaded into the employees table. Whatever the
directory calls an employee -- a payroll number, a staff code, something with a
prefix -- the same string must appear in both places. If the login returns
'40255' while the directory export loaded 'E40255', nothing matches and no
employee can use the portal.

------------------------------------------------------------------------------
BEFORE THIS RUNS ON THE NETWORK
------------------------------------------------------------------------------
The `employees` table must be populated from the DMRC employee directory. This
portal never creates employee records -- it only reads them. On an empty table
every request is refused with 401, including the Phase 1 referral portal.

The `users` table must contain at least one SYS-ADMIN row, inserted directly
into the database. The screen that provisions dashboard accounts requires the
caller to hold the SYS-ADMIN role already, so the first one cannot be created
through the interface.

------------------------------------------------------------------------------
AUTHORISATION MODEL
------------------------------------------------------------------------------
Once an employee code is resolved, the portal looks it up in two tables:

  employees  -- every DMRC employee known to this portal. Any employee with a
                valid identity may use the Phase 1 referral portal.

  users      -- dashboard accounts. A row here grants access to the HR
                dashboard with the role named by users.role_id. Employees
                WITHOUT a row here cannot reach the dashboard at all. This is
                the default for all staff, and is intentional.

Role assignment is therefore a deliberate administrative act performed by a
SYS-ADMIN, not something inherited from the intranet.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    """Resolved identity for one request.

    employee -- Employees row, or None if the code matched no known employee.
    user     -- Users row, or None if this employee has no dashboard account.
    role     -- 'SYS-ADMIN' | 'HR-APP' | 'HR-OPS', or None for staff without
                dashboard access.
    """
    employee_code: str
    employee: object = None
    user: object = None
    role: str = None

    @property
    def is_known_employee(self):
        return self.employee is not None

    @property
    def has_dashboard_access(self):
        return self.user is not None and self.role is not None


class IdentityProvider:
    """Base contract. Subclass this and implement get_employee_code()."""

    #: Set False on production implementations. Controls whether the portal
    #: exposes developer affordances such as the role switcher.
    is_development_provider = False

    def get_employee_code(self, request):
        """Return the employee code of the signed-in user, or None.

        Strip surrounding whitespace before returning. Must not raise for an
        unauthenticated request -- return None instead.
        """
        raise NotImplementedError(
            "Implement get_employee_code(). See portal/identity/base.py for the "
            "integration contract."
        )