from django.contrib import admin
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve as serve_media

from .views import frontend_app, system_version


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/system/version/", system_version),
    path("api/", include("quality.urls")),
]

if settings.SERVE_MEDIA_FILES:
    urlpatterns.append(
        re_path(
            r"^media/(?P<path>.*)$",
            serve_media,
            {"document_root": settings.MEDIA_ROOT},
        )
    )

urlpatterns.append(
    re_path(r"^(?!api/|admin/|static/|media/).*$", frontend_app)
)
