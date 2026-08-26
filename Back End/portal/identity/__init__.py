"""
Identity resolution for the DMRC internship portal.

Views should import from this package only -- never from a concrete provider.
That indirection is what lets DMRC IT swap the development provider for their
intranet integration by changing one settings value.

    from .identity import get_identity

    identity = get_identity(request)
    identity.employee_code        # 'EMP-ADM-001'
    identity.employee             # Employees row, or None
    identity.user                 # Users row, or None
    identity.role                 # 'SYS-ADMIN' | 'HR-APP' | 'HR-OPS' | None

See base.py for the integration contract.
"""

from django.conf import settings
from django.utils.module_loading import import_string

from .base import Identity, IdentityProvider

_provider_cache = None


def get_provider():
    """Instantiate the configured provider once and reuse it."""
    global _provider_cache
    if _provider_cache is None:
        path = getattr(
            settings, 'IDENTITY_PROVIDER',
            'portal.identity.dev.DevIdentityProvider'
        )
        _provider_cache = import_string(path)()
    return _provider_cache


def is_development_identity():
    """True when the active provider is a development stand-in.

    Drives whether the portal exposes developer affordances such as the role
    switcher, so those cannot appear on the intranet by accident.
    """
    return getattr(get_provider(), 'is_development_provider', False)


def get_identity(request):
    """Resolve a request to an Identity, or None if unauthenticated.

    Attaches the result to request.identity so repeated calls within one
    request do not re-query the database.
    """
    cached = getattr(request, 'identity', None)
    if cached is not None:
        return cached

    code = get_provider().get_employee_code(request)
    if not code:
        return None

    # Defensive strip. The contract in base.py requires providers to return a
    # trimmed code, but the lookup below is an exact match -- a trailing space
    # picked up from an LDAP attribute or a proxy header would match nothing and
    # refuse the employee with no indication why. Cheap insurance against a bug
    # that would be expensive to find.
    code = code.strip()
    if not code:
        return None

    # Imported here rather than at module scope: this package is imported by
    # settings-dependent code paths before the app registry is ready.
    from ..models import Employees, Users

    # is_active=False means the employee has left DMRC. They are never deleted
    # -- referral history depends on the row surviving -- so this flag is what
    # withdraws their access. A departed employee resolves to no employee at
    # all and is refused with a 401, exactly as an unknown code is.
    #
    # This only affects who may USE the portal. Records naming that employee,
    # including applications they referred, are reached by foreign key and are
    # unaffected.
    employee = (Employees.objects
                .filter(employee_code=code, is_active=True)
                .select_related('department')
                .first())

    user = None
    role = None
    if employee is not None:
        user = (Users.objects
                .filter(employee=employee, is_active=True)
                .select_related('role')
                .first())
        if user is not None and user.role is not None:
            role = user.role.role_name

    identity = Identity(employee_code=code, employee=employee, user=user, role=role)
    request.identity = identity
    return identity


__all__ = ['Identity', 'IdentityProvider', 'get_identity', 'get_provider',
           'is_development_identity']