from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

admin.site.site_header = f"{settings.SITE_NAME} · 门店后台"
admin.site.site_title = f"{settings.SITE_NAME} 门店后台"
admin.site.index_title = "门店功能"
admin.site.site_url = "/"
admin.site.enable_nav_sidebar = False

urlpatterns = [
    path("", include("apps.security.urls")),
    path("", include("apps.payments.urls")),
    # 门店后台（原 Django Admin）
    path("store/", admin.site.urls),
    # 兼容旧 /admin/ 地址
    re_path(r"^admin/(?P<path>.*)$", RedirectView.as_view(url="/store/%(path)s", permanent=False)),
    path("", include("apps.web.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
