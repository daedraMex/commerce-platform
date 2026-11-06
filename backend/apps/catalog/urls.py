from django.urls import path

from apps.catalog.views import (
    CategoryListView,
    CollectionListView,
    ProductDetailView,
    ProductListView,
    VariantLookupView,
)

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="catalog-category-list"),
    path("collections/", CollectionListView.as_view(), name="catalog-collection-list"),
    path("products/", ProductListView.as_view(), name="catalog-product-list"),
    path(
        "products/<slug:slug>/",
        ProductDetailView.as_view(),
        name="catalog-product-detail",
    ),
    path(
        "variants/<str:sku>/",
        VariantLookupView.as_view(),
        name="catalog-variant-lookup",
    ),
]
