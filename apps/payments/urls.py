from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("pay/checkout/<int:payment_id>/", views.checkout, name="checkout"),
    path("pay/checkout/<int:payment_id>/qr.png", views.qr_image, name="qr"),
    path("pay/sandbox/<int:payment_id>/", views.sandbox_pay, name="sandbox"),
    path("pay/return/<int:payment_id>/", views.return_pay, name="return"),
    path("pay/notify/<str:method>/", views.notify, name="notify"),
]
