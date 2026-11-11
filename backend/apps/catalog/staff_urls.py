from django.urls import path

from apps.catalog.views import StaffProductListView

urlpatterns = [
    path("products/", StaffProductListView.as_view(), name="staff-product-list"),
]
