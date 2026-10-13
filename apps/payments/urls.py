from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("pay/sandbox/<int:payment_id>/", views.sandbox_pay, name="sandbox"),
]
