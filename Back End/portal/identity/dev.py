"""
DEVELOPMENT IDENTITY PROVIDER

Stands in for the DMRC intranet login while building and demonstrating the
portal on a local machine. NOT FOR PRODUCTION -- it trusts a request header,
which means anyone able to reach the server could impersonate any employee.

Resolution order:
  1. The X-DMRC-Employee request header, if present. This is what the role
     switcher in the HR dashboard sends, so a developer can move between
     SYS-ADMIN, HR-APP and HR-OPS without a real login.
  2. settings.DEV_DEFAULT_EMPLOYEE_CODE, so requests made without the header
     (curl, a browser address bar, an unmodified page) still resolve to a
     usable identity instead of failing.

Replaced by portal/identity/intranet.py on the DMRC network. See base.py.
"""

from django.conf import settings

from .base import IdentityProvider


class DevIdentityProvider(IdentityProvider):

    is_development_provider = True

    HEADER = 'X-DMRC-Employee'

    QUERY_PARAM = 'emp'

    def get_employee_code(self, request):
        supplied = request.headers.get(self.HEADER)
        if supplied and supplied.strip():
            return supplied.strip()

        # A document opened in a NEW TAB is a plain browser navigation: it
        # carries no custom header, so identity would fall back to the default
        # employee and the role check would be meaningless in development.
        # The query parameter keeps dev behaviour honest. It is ignored in
        # production, where identity comes from the intranet session.
        from_query = request.GET.get(self.QUERY_PARAM)
        if from_query and from_query.strip():
            return from_query.strip()

        return getattr(settings, 'DEV_DEFAULT_EMPLOYEE_CODE', None)