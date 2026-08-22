from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# ==============================================================================
# THE DJANGO ADMIN IS DELIBERATELY NOT ROUTED
#
# This portal authenticates nobody. It has no login screen and stores no
# passwords: identity comes from DMRC's employee login, and authorisation is
# decided from the `users` table on every request.
#
# Django's built-in admin contradicts that. It is a username-and-password login
# form backed by django.contrib.auth, with its own accounts that have nothing to
# do with the employee directory. Nothing in this project uses it -- every
# administrative function lives in the HR dashboard under the SYS-ADMIN role --
# so exposing a second, parallel way in would be an unmanaged authentication
# surface for no benefit.
#
# To re-enable it for local debugging, uncomment the import and the path below
# and create a superuser with `python manage.py createsuperuser`. Do not leave
# it routed on a deployed server.
#
#     from django.contrib import admin
#     path('admin/', admin.site.urls),
# ==============================================================================

urlpatterns = [
    path('', include('portal.urls')),
]

# --- UNLOCK MEDIA SERVING FOR LOCAL DEVELOPMENT ---
#
# Django serves MEDIA_ROOT only while DEBUG is on. That is why uploaded
# documents, generated letters and signature images are all stored OUTSIDE
# MEDIA_ROOT and reached through the audited, role-checked viewer endpoint
# instead -- see the storage sections in settings.py. Nothing a user needs
# depends on the line below.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)