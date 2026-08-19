"""
INTRANET IDENTITY PROVIDER  --  THE ONLY FILE DMRC IT NEEDS TO IMPLEMENT
==============================================================================

Read portal/identity/base.py first for the full contract.

Implement get_employee_code() below so it returns the employee code of the
signed-in user, then set this class as the provider in settings.py:

    IDENTITY_PROVIDER = 'portal.identity.intranet.IntranetIdentityProvider'

The returned value must match employees.employee_code. Return None if the
request carries no valid session -- the portal responds 401 in that case.

Four common intranet patterns are sketched below. Delete the ones that do not
apply and implement the one that does. Nothing else in the codebase should
need to be modified.
==============================================================================
"""

from .base import IdentityProvider


class IntranetIdentityProvider(IdentityProvider):

    is_development_provider = False

    def get_employee_code(self, request):
        raise NotImplementedError(
            "DMRC IT: implement get_employee_code() in "
            "portal/identity/intranet.py. See the patterns below."
        )

    # --------------------------------------------------------------------
    # PATTERN A -- Reverse proxy injects an identity header
    #
    # Common when this application sits behind Apache, nginx or IIS which
    # performs the authentication. SECURITY: the proxy must STRIP this header
    # from inbound client requests, otherwise a user can set it themselves and
    # impersonate anyone.
    #
    #     def get_employee_code(self, request):
    #         return request.headers.get('X-Employee-Id') or None
    # --------------------------------------------------------------------

    # --------------------------------------------------------------------
    # PATTERN B -- SAML or OpenID Connect single sign-on
    #
    # Using a library such as django-saml2-auth or mozilla-django-oidc, which
    # populates request.user after the assertion is validated. Map whichever
    # claim carries the payroll or employee number.
    #
    #     def get_employee_code(self, request):
    #         if not request.user.is_authenticated:
    #             return None
    #         return getattr(request.user, 'employee_id', None)
    # --------------------------------------------------------------------

    # --------------------------------------------------------------------
    # PATTERN C -- Shared session with the payslip application
    #
    # Where the payslip system and this portal share a session store or a
    # cookie on the same intranet domain. Validate the session server-side --
    # never trust a cookie value directly as an identity.
    #
    #     def get_employee_code(self, request):
    #         token = request.COOKIES.get('DMRC_SSO')
    #         if not token:
    #             return None
    #         return validate_with_payslip_service(token)   # returns code or None
    # --------------------------------------------------------------------

    # --------------------------------------------------------------------
    # PATTERN D -- LDAP or Active Directory
    #
    # Resolve the authenticated principal to a directory entry and read the
    # attribute holding the employee number (often employeeNumber or employeeID).
    #
    #     def get_employee_code(self, request):
    #         principal = request.META.get('REMOTE_USER')
    #         if not principal:
    #             return None
    #         return ldap_lookup_employee_number(principal)
    # --------------------------------------------------------------------
