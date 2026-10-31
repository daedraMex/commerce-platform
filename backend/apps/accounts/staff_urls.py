from django.urls import path

from apps.accounts.views import StaffMeView

urlpatterns = [
    path("me/", StaffMeView.as_view(), name="staff-me"),
]
