from django.urls import path

from apps.catalog.views import StaffProductDetailView, StaffProductListView

urlpatterns = [
    path("products/", StaffProductListView.as_view(), name="staff-product-list"),
    path(
        "products/<int:pk>/",
        StaffProductDetailView.as_view(),
        name="staff-product-detail",
    ),
]
