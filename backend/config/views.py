from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def system_version(request):
    return JsonResponse(
        {
            "environment": settings.APP_ENV,
            "version": settings.APP_VERSION,
        }
    )


@require_GET
def frontend_app(request):
    index_path = settings.FRONTEND_DIST_DIR / "index.html"
    if not index_path.is_file():
        raise Http404("Frontend build is not available.")
    response = FileResponse(index_path.open("rb"), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
