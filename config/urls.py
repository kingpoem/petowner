from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.admin_auth import patch_auth_admin
from config.admin_nav import patch_admin_nav

admin.site.site_header = f"{settings.SITE_NAME} · 运营后台"
admin.site.site_title = f"{settings.SITE_NAME} 运营后台"
admin.site.index_title = "寄养订单"
admin.site.site_url = "/"
admin.site.enable_nav_sidebar = False  # 只用顶栏导航，不显示左侧栏
patch_admin_nav()
patch_auth_admin()

urlpatterns = [
    path("", include("apps.security.urls")),
    path("", include("apps.payments.urls")),
    path("", include("apps.hospitality.urls")),
    path("admin/", admin.site.urls),
    path("", include("apps.web.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "config.views.page_not_found"
handler500 = "config.views.server_error"
