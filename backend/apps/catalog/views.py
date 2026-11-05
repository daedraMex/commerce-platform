import unicodedata

from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny

from apps.catalog.models import Category, Product, ProductVariant
from apps.catalog.serializers import (
    CategorySerializer,
    ProductDetailSerializer,
    ProductSerializer,
    VariantLookupSerializer,
)
from apps.shared.interfaces.views import StoreScopedMixin
from config.schema import problem_response

STORE_HEADER_PARAMETER = OpenApiParameter(
    "X-Store",
    location=OpenApiParameter.HEADER,
    required=True,
    description="Slug of the store the request is scoped to, such as home.",
)

CATEGORY_EXAMPLE = OpenApiExample(
    "Frazada",
    value={
        "name": "Frazada",
        "slug": "frazada",
        "sku_code": "FRZ",
        "shape": "rectangle",
        "options": [
            {
                "code": "size",
                "label": "Size",
                "values": [
                    {
                        "code": "IND",
                        "label": "Individual / Personal / Viajera",
                        "width_cm": 110.0,
                        "height_cm": 160.0,
                    },
                    {
                        "code": "MAT",
                        "label": "Matrimonial",
                        "width_cm": 210.0,
                        "height_cm": 160.0,
                    },
                ],
            }
        ],
    },
    response_only=True,
)

STORE_ERRORS = problem_response(
    400,
    ("store_header_missing", "The X-Store header is required."),
    ("store_header_invalid", "The X-Store header is not a valid store slug."),
    ("store_not_found", "No active store matches the X-Store header."),
)


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=CategorySerializer(many=True),
            description="The store's active categories and their option definitions.",
            examples=[CATEGORY_EXAMPLE],
        ),
        **STORE_ERRORS,
    },
)
class CategoryListView(StoreScopedMixin, generics.ListAPIView):
    permission_classes = [AllowAny]
    pagination_class = None
    serializer_class = CategorySerializer
    queryset = Category.objects.none()

    def get_queryset(self):
        return Category.objects.filter(
            store_id=self.request.store.id,
            is_active=True,
        ).order_by("name")


CATEGORY_PARAMETER = OpenApiParameter(
    "category",
    location=OpenApiParameter.QUERY,
    required=False,
    description="Only products in the category with this slug.",
)

SEARCH_PARAMETER = OpenApiParameter(
    "search",
    location=OpenApiParameter.QUERY,
    required=False,
    description="Only products whose name contains this text, ignoring case and accents.",
)

PRODUCT_EXAMPLE = {
    "name": "Frazada Térmica",
    "slug": "frazada-termica",
    "category": {"name": "Frazada", "slug": "frazada"},
    "attributes": [
        {
            "code": "material",
            "label": "Material",
            "type": "text",
            "value": "Flannel premier",
        }
    ],
    "variants": [
        {
            "sku": "FRZ-00012-MAT",
            "options": [
                {
                    "code": "size",
                    "label": "Size",
                    "value": {
                        "code": "MAT",
                        "label": "Matrimonial",
                        "width_cm": 210.0,
                        "height_cm": 160.0,
                    },
                }
            ],
            "price": "499.00",
            "compare_at_price": "699.00",
        }
    ],
}

PRODUCT_PAGE_EXAMPLE = OpenApiExample(
    "Product page",
    value=PRODUCT_EXAMPLE,
    response_only=True,
)


def _without_accents(value):
    decomposed = unicodedata.normalize("NFKD", value)
    return decomposed.encode("ascii", "ignore").decode("ascii")


def active_variants(queryset=None):
    """The active variants a product response returns, with their product loaded."""
    queryset = ProductVariant.objects if queryset is None else queryset
    return (
        queryset.filter(is_active=True)
        .select_related("product", "product__category")
        .order_by("sku")
    )


def visible_products(store_id):
    """Active products of a store with an active category and a purchasable size."""
    return (
        Product.objects.filter(
            store_id=store_id,
            is_active=True,
            category__is_active=True,
            variants__is_active=True,
        )
        .select_related("category")
        .prefetch_related(Prefetch("variants", queryset=active_variants(ProductVariant.objects)))
        .distinct()
    )


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER, CATEGORY_PARAMETER, SEARCH_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=ProductSerializer(many=True),
            description="A page of the store's visible products, newest first.",
            examples=[PRODUCT_PAGE_EXAMPLE],
        ),
        **STORE_ERRORS,
    },
)
class ProductListView(StoreScopedMixin, generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductSerializer
    queryset = Product.objects.none()

    def get_queryset(self):
        queryset = visible_products(self.request.store.id)

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category__slug=category)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__unaccent__icontains=_without_accents(search))

        return queryset.order_by("-created_at", "-id")


PRODUCT_DETAIL_EXAMPLE = OpenApiExample(
    "Product detail",
    value={**PRODUCT_EXAMPLE, "description": "Sublimated flannel blanket."},
    response_only=True,
)


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=ProductDetailSerializer,
            description="One visible product with its attributes and active variants.",
            examples=[PRODUCT_DETAIL_EXAMPLE],
        ),
        **STORE_ERRORS,
        **problem_response(404, ("not_found", "No visible product matches this slug.")),
    },
)
class ProductDetailView(StoreScopedMixin, generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductDetailSerializer
    lookup_field = "slug"
    queryset = Product.objects.none()

    def get_queryset(self):
        return visible_products(self.request.store.id)


SKU_PARAMETER = OpenApiParameter(
    "sku",
    location=OpenApiParameter.PATH,
    required=True,
    description="Variant SKU, matched ignoring case.",
)

VARIANT_LOOKUP_EXAMPLE = OpenApiExample(
    "Matrimonial blanket",
    value={
        "sku": "FRZ-00012-MAT",
        "options": PRODUCT_EXAMPLE["variants"][0]["options"],
        "price": "499.00",
        "compare_at_price": "699.00",
        "product": {"name": "Frazada Térmica", "slug": "frazada-termica"},
    },
    response_only=True,
)


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER, SKU_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=VariantLookupSerializer,
            description="The visible variant and a summary of its product.",
            examples=[VARIANT_LOOKUP_EXAMPLE],
        ),
        **STORE_ERRORS,
        **problem_response(404, ("not_found", "No visible variant matches this SKU.")),
    },
)
class VariantLookupView(StoreScopedMixin, generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = VariantLookupSerializer
    lookup_url_kwarg = "sku"
    queryset = ProductVariant.objects.none()

    def get_queryset(self):
        return active_variants(ProductVariant.objects).filter(
            store_id=self.request.store.id,
            product__is_active=True,
            product__category__is_active=True,
        )

    def get_object(self):
        sku = self.kwargs["sku"]
        variant = self.get_queryset().filter(sku__iexact=sku).first()
        if variant is None:
            raise NotFound("No visible variant matches this SKU.")
        return variant
