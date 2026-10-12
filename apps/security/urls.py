from django.urls import path

from . import views

app_name = "security"

# 需挂载在 admin.site.urls 之前：后台的兜底路由会吞掉 admin/ 下的未知路径
urlpatterns = [
    path("account/captcha/", views.captcha_image, name="captcha"),
    path("account/sms/send/", views.send_sms_code, name="send_sms"),
    path("admin/2fa/", views.two_factor_setup, name="2fa_setup"),
    path("admin/2fa/verify/", views.two_factor_verify, name="2fa_verify"),
    path("admin/2fa/disable/", views.two_factor_disable, name="2fa_disable"),
]
