from django.urls import path

from . import views

app_name = "security"

urlpatterns = [
    path("account/captcha/", views.captcha_image, name="captcha"),
    path("account/sms/send/", views.send_sms_code, name="send_sms"),
]
