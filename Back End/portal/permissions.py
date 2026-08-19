"""
Server-side role enforcement.

Authorisation is decided here, on the server, from the users table. The role
switcher in the dashboard is a development convenience only -- it changes which
identity the request claims, and the server then re-derives that identity's
real role from the database. A user cannot grant themselves a role by editing
anything in the browser.

Usage:

    class AdminCycleAPIView(APIView):
        @role_required('SYS-ADMIN')
        def post(self, request):
            actor = request.identity.user     # always populated here
            ...

Responses:
    401  no identity, or an employee code unknown to this portal
    403  a known employee with no dashboard account, or the wrong role
"""

from functools import wraps

from rest_framework import status
from rest_framework.response import Response

from .identity import get_identity

# Ordered most privileged first. Useful for messages and for any future
# "at least this level" checks.
ROLE_HIERARCHY = ['SYS-ADMIN', 'HR-APP', 'HR-OPS']

ALL_HR_ROLES = ('SYS-ADMIN', 'HR-APP', 'HR-OPS')


def employee_required(view_method):
    """Any employee known to this portal may proceed.

    Used for the Phase 1 referral portal, which is open to all DMRC staff and
    requires no dashboard account.
    """
    @wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        identity = get_identity(request)
        if identity is None:
            return Response(
                {"error": "Not signed in. Access this portal through the DMRC employee login."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        if not identity.is_known_employee:
            return Response(
                {"error": f"Employee '{identity.employee_code}' is not registered in this portal."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        return view_method(self, request, *args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    """Restrict an endpoint to specific dashboard roles."""
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(self, request, *args, **kwargs):
            identity = get_identity(request)

            if identity is None:
                return Response(
                    {"error": "Not signed in. Access this portal through the DMRC employee login."},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            if not identity.is_known_employee:
                return Response(
                    {"error": f"Employee '{identity.employee_code}' is not registered in this portal."},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            if not identity.has_dashboard_access:
                return Response(
                    {"error": "You do not have an HR dashboard account. "
                              "Contact a system administrator if you require access."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if identity.role not in allowed_roles:
                return Response(
                    {"error": f"This action requires one of: {', '.join(allowed_roles)}. "
                              f"Your role is {identity.role}."},
                    status=status.HTTP_403_FORBIDDEN
                )

            return view_method(self, request, *args, **kwargs)
        return wrapper
    return decorator
