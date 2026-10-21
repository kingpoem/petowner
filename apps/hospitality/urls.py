from django.urls import path

from . import views

app_name = "hospitality"

urlpatterns = [
    path("services/", views.service_menu, name="services"),
]
