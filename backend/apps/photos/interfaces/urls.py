from django.urls import path

from apps.photos.interfaces.views import (
    StaffPhotoApplyView,
    StaffPhotoDetailView,
    StaffPhotoDiscardView,
    StaffPhotoLinksView,
    StaffPhotoPreviewView,
    StaffPhotoRedoView,
    StaffPhotoRemoveView,
    StaffPhotoRetryView,
    StaffPhotoUploadView,
    StaffProductImageOrderView,
    StaffProductImagesView,
)

urlpatterns = [
    path(
        "products/<int:pk>/images/",
        StaffProductImagesView.as_view(),
        name="staff-product-images",
    ),
    path(
        "products/<int:pk>/images/order/",
        StaffProductImageOrderView.as_view(),
        name="staff-product-image-order",
    ),
    path("photos/", StaffPhotoUploadView.as_view(), name="staff-photo-upload"),
    path("photos/<int:pk>/", StaffPhotoDetailView.as_view(), name="staff-photo-detail"),
    path(
        "photos/<int:pk>/preview/",
        StaffPhotoPreviewView.as_view(),
        name="staff-photo-preview",
    ),
    path("photos/<int:pk>/apply/", StaffPhotoApplyView.as_view(), name="staff-photo-apply"),
    path("photos/<int:pk>/links/", StaffPhotoLinksView.as_view(), name="staff-photo-links"),
    path("photos/<int:pk>/redo/", StaffPhotoRedoView.as_view(), name="staff-photo-redo"),
    path(
        "photos/<int:pk>/remove/",
        StaffPhotoRemoveView.as_view(),
        name="staff-photo-remove",
    ),
    path("photos/<int:pk>/retry/", StaffPhotoRetryView.as_view(), name="staff-photo-retry"),
    path(
        "photos/<int:pk>/discard/",
        StaffPhotoDiscardView.as_view(),
        name="staff-photo-discard",
    ),
]
