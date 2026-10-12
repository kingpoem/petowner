from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("v1/health/", views.health, name="health"),
    path("v1/rooms/availability/", views.rooms_availability, name="rooms_availability"),
    path("v1/rooms/calendar/", views.rooms_calendar, name="rooms_calendar"),
    path("v1/quotes/", views.quotes, name="quotes"),
    path("v1/bookings/", views.bookings_create, name="bookings_create"),
    path("v1/orders/", views.orders_list, name="orders_list"),
    path("v1/orders/<str:order_no>/", views.orders_detail, name="orders_detail"),
    path("v1/orders/<str:order_no>/cancel/", views.orders_cancel, name="orders_cancel"),
    path("v1/orders/<str:order_no>/care-records/", views.orders_care, name="orders_care"),
    path("v1/orders/<str:order_no>/care-digest/", views.orders_care_digest, name="orders_care_digest"),
    path("v1/orders/<str:order_no>/reviews/", views.orders_review, name="orders_review"),
    path("v1/waitlist/", views.waitlist_create, name="waitlist_create"),
    path("v1/waitlist/<int:pk>/", views.waitlist_cancel, name="waitlist_cancel"),
    path("v1/staff/orders/<str:order_no>/check-in/", views.staff_check_in, name="staff_check_in"),
    path("v1/staff/orders/<str:order_no>/check-out/", views.staff_check_out, name="staff_check_out"),
    path("v1/staff/orders/<str:order_no>/care-records/", views.staff_care, name="staff_care"),
    path("v1/staff/orders/<str:order_no>/collect/", views.staff_collect, name="staff_collect"),
    path("v1/invoices/", views.invoices_create, name="invoices_create"),
    path("v1/invoices/<int:pk>/pdf/", views.invoices_pdf, name="invoices_pdf"),
]
