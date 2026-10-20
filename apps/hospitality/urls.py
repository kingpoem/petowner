from django.urls import path

from . import views

app_name = "hospitality"

urlpatterns = [
    path("house/", views.house, name="house"),
    path("services/", views.service_menu, name="services"),
    path("membership/", views.membership, name="membership"),
    path("waitlist/", views.waitlist, name="waitlist"),
    path("me/pets/<int:pk>/health/", views.pet_health, name="pet_health"),
    path("me/pets/meds/<int:pk>/stop/", views.stop_medication, name="stop_medication"),
]
