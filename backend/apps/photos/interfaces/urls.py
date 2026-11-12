from django.urls import path

from apps.photos.interfaces.views import (
    StaffPhotoDetailView,
    StaffPhotoPreviewView,
    StaffPhotoUploadView,
)

urlpatterns = [
    path("photos/", StaffPhotoUploadView.as_view(), name="staff-photo-upload"),
    path("photos/<int:pk>/", StaffPhotoDetailView.as_view(), name="staff-photo-detail"),
    path(
        "photos/<int:pk>/preview/",
        StaffPhotoPreviewView.as_view(),
        name="staff-photo-preview",
    ),
]
