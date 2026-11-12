from django.urls import path

from apps.photos.interfaces.views import (
    StaffPhotoApplyView,
    StaffPhotoDetailView,
    StaffPhotoDiscardView,
    StaffPhotoPreviewView,
    StaffPhotoRedoView,
    StaffPhotoRetryView,
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
    path("photos/<int:pk>/apply/", StaffPhotoApplyView.as_view(), name="staff-photo-apply"),
    path("photos/<int:pk>/redo/", StaffPhotoRedoView.as_view(), name="staff-photo-redo"),
    path("photos/<int:pk>/retry/", StaffPhotoRetryView.as_view(), name="staff-photo-retry"),
    path(
        "photos/<int:pk>/discard/",
        StaffPhotoDiscardView.as_view(),
        name="staff-photo-discard",
    ),
]
