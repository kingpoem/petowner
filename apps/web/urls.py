from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("rooms/", views.room_list, name="room_list"),
    path("rooms/<int:pk>/", views.room_detail, name="room_detail"),
    path("pages/<slug:name>/", views.page, name="page"),
    path("account/register/", views.register, name="register"),
    path("account/login/", views.LoginView.as_view(), name="login"),
    path("account/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/profile/", views.profile, name="profile"),
    path("account/password/", views.PasswordChangeView.as_view(), name="password_change"),
    path("account/password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("account/password/reset/sent/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("account/password/reset/sms/", views.password_reset_sms, name="password_reset_sms"),
    path(
        "account/password/reset/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("account/password/reset/done/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("me/", views.dashboard, name="dashboard"),
    path("me/loyalty/", views.loyalty_center, name="loyalty"),
    path("me/pets/", views.pet_list, name="pet_list"),
    path("me/pets/new/", views.pet_form, name="pet_create"),
    path("me/pets/<int:pk>/edit/", views.pet_form, name="pet_edit"),
    path("me/pets/<int:pk>/delete/", views.pet_delete, name="pet_delete"),
    path("me/orders/", views.order_list, name="order_list"),
    path("me/orders/<str:order_no>/", views.order_detail, name="order_detail"),
    path("me/orders/<str:order_no>/pay/", views.order_pay, name="order_pay"),
    path("me/orders/<str:order_no>/cancel/", views.order_cancel, name="order_cancel"),
    path("me/orders/<str:order_no>/change/", views.order_reschedule, name="order_reschedule"),
    path("me/orders/<str:order_no>/review/", views.order_review, name="order_review"),
    path("me/orders/<str:order_no>/invoice/", views.order_invoice, name="order_invoice"),
    path("book/", views.booking_create, name="booking_create"),
    path("book/quote/", views.quote_preview, name="quote_preview"),
    path("me/waitlist/", views.waitlist_create, name="waitlist_create"),
    path("me/waitlist/<int:pk>/cancel/", views.waitlist_cancel, name="waitlist_cancel"),
    path("me/notifications/", views.notification_list, name="notifications"),
    path("me/notifications/<int:pk>/", views.notification_open, name="notification_open"),
    path("me/notifications/read-all/", views.notification_read_all, name="notification_read_all"),
]
