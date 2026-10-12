from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("", views.board, name="board"),
    path("sw.js", views.service_worker, name="sw"),
    path("orders/<int:pk>/check-in/", views.check_in, name="check_in"),
    path("orders/<int:pk>/check-out/", views.check_out, name="check_out"),
    path("orders/<int:pk>/collect/", views.collect, name="collect"),
    path("orders/<int:pk>/care/", views.care_record, name="care"),
]
