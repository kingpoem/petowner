from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = f"{settings.SITE_NAME} · 运营后台"
admin.site.site_title = f"{settings.SITE_NAME} 运营后台"
admin.site.index_title = "运营看板"
admin.site.site_url = "/"

urlpatterns = [
    path("", include("apps.security.urls")),
    path("", include("apps.payments.urls")),
    path("admin/", admin.site.urls),
    path("", include("apps.web.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
