from django.db.models import (
    Case,
    Exists,
    IntegerField,
    OuterRef,
    Prefetch,
    Subquery,
    Value,
    When,
)
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny

from apps.catalog.models import (
    Category,
    Collection,
    CollectionProduct,
    Product,
    ProductMedia,
    ProductVariant,
)
from apps.catalog.permissions import CanManageCatalog
from apps.catalog.serializers import (
    CategorySerializer,
    CollectionSummarySerializer,
    ProductDetailSerializer,
    ProductSerializer,
    StaffProductSerializer,
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


COLLECTION_EXAMPLE = OpenApiExample(
    "Halloween 2026",
    value={
        "name": "Halloween 2026",
        "slug": "halloween-2026",
        "description": "Blankets and pillows for the season.",
    },
    response_only=True,
)


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=CollectionSummarySerializer(many=True),
            description="The store's active collections in name order.",
            examples=[COLLECTION_EXAMPLE],
        ),
        **STORE_ERRORS,
    },
)
class CollectionListView(StoreScopedMixin, generics.ListAPIView):
    permission_classes = [AllowAny]
    pagination_class = None
    serializer_class = CollectionSummarySerializer
    queryset = Collection.objects.none()

    def get_queryset(self):
        return Collection.objects.filter(
            store_id=self.request.store.id,
            is_active=True,
        ).order_by("name")


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

COLLECTION_PARAMETER = OpenApiParameter(
    "collection",
    location=OpenApiParameter.QUERY,
    required=False,
    description=(
        "Only products in the active collection with this slug, in the collection's curated order."
    ),
    examples=[
        OpenApiExample(
            "Halloween 2026",
            value="halloween-2026",
            request_only=True,
        )
    ],
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


def product_images(store_id):
    """The store's product images, with the main image first."""
    return (
        ProductMedia.objects.active()
        .filter(media__store_id=store_id)
        .select_related("media", "variant")
        .annotate(
            role_order=Case(
                When(role=ProductMedia.Role.MAIN, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("product_id", "role_order", "position", "pk")
    )


def main_product_images():
    """The main image of each product, for a summary that shows one."""
    return (
        ProductMedia.objects.active()
        .filter(role=ProductMedia.Role.MAIN)
        .select_related("media", "variant")
    )


def active_variants():
    """The active variants a product response returns, with their product loaded."""
    return (
        ProductVariant.objects.filter(is_active=True)
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
        .prefetch_related(Prefetch("variants", queryset=active_variants()))
        .distinct()
    )


def with_active_collections(queryset, store_id):
    """Prefetch the store's active collections that a product detail returns."""
    memberships = CollectionProduct.objects.visible_in_store(store_id)
    return queryset.prefetch_related(Prefetch("collection_memberships", queryset=memberships))


def with_images(queryset, store_id):
    """Prefetch the store's images that a product detail returns."""
    return queryset.prefetch_related(Prefetch("product_media", queryset=product_images(store_id)))


@extend_schema(
    parameters=[
        STORE_HEADER_PARAMETER,
        CATEGORY_PARAMETER,
        COLLECTION_PARAMETER,
        SEARCH_PARAMETER,
    ],
    responses={
        200: OpenApiResponse(
            response=ProductSerializer(many=True),
            description=(
                "A page of the store's visible products, newest first or in the "
                "collection's curated order."
            ),
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
        store_id = self.request.store.id
        queryset = visible_products(store_id)

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category__slug=category)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__unaccent__icontains=search)

        collection = self.request.query_params.get("collection")
        if collection:
            positions = CollectionProduct.objects.filter(
                product_id=OuterRef("pk"),
                collection__store_id=store_id,
                collection__slug=collection,
                collection__is_active=True,
            ).values("position")[:1]
            queryset = (
                queryset.annotate(
                    collection_position=Subquery(positions, output_field=IntegerField())
                )
                .filter(collection_position__isnull=False)
                .order_by("collection_position", "id")
            )
            return queryset

        return queryset.order_by("-created_at", "-id")


PRODUCT_IMAGE_EXAMPLE = {
    "url": "https://media.example.com/stores/1/media/abc123.jpg",
    "thumbnail_url": "https://media.example.com/stores/1/media/renditions/abc123-320w-v1.webp",
    "medium_url": "https://media.example.com/stores/1/media/renditions/abc123-800w-v1.webp",
    "role": "main",
    "position": 1,
    "alt_text": "Blue flannel blanket with a moon pattern",
    "width": 1200,
    "height": 800,
    "variant": None,
}

PRODUCT_DETAIL_EXAMPLE = OpenApiExample(
    "Product detail",
    value={
        **PRODUCT_EXAMPLE,
        "description": "Sublimated flannel blanket.",
        "collections": [
            {
                "name": "Halloween 2026",
                "slug": "halloween-2026",
                "description": "Blankets and pillows for the season.",
            }
        ],
        "images": [PRODUCT_IMAGE_EXAMPLE],
    },
    response_only=True,
)


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=ProductDetailSerializer,
            description=(
                "One visible product with its attributes, active collections and active variants."
            ),
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
        store_id = self.request.store.id
        return with_images(with_active_collections(visible_products(store_id), store_id), store_id)

    def get_object(self):
        product = self.get_queryset().filter(slug=self.kwargs["slug"]).first()
        if product is None:
            raise NotFound("No visible product matches this slug.")
        return product


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
        "product": {
            "name": "Frazada Térmica",
            "slug": "frazada-termica",
            "main_image": PRODUCT_IMAGE_EXAMPLE,
        },
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
        return (
            active_variants()
            .filter(
                store_id=self.request.store.id,
                product__is_active=True,
                product__category__is_active=True,
            )
            .prefetch_related(Prefetch("product__product_media", queryset=main_product_images()))
        )

    def get_object(self):
        sku = self.kwargs["sku"]
        variant = self.get_queryset().filter(sku__iexact=sku).first()
        if variant is None:
            raise NotFound("No visible variant matches this SKU.")
        return variant


NEEDS_MAIN_IMAGE_PARAMETER = OpenApiParameter(
    "needs_main_image",
    location=OpenApiParameter.QUERY,
    required=False,
    type=bool,
    description=(
        "With true, only products without an active main image; with false, only products with one."
    ),
)

STAFF_PRODUCT_PAGE_EXAMPLE = OpenApiExample(
    "Staff product page",
    value={
        "id": 12,
        "name": "Frazada Térmica",
        "slug": "frazada-termica",
        "category": {"name": "Frazada", "slug": "frazada"},
        "needs_main_image": False,
        "main_image": PRODUCT_IMAGE_EXAMPLE,
    },
    response_only=True,
)


def has_active_main_image():
    """A product's active main image, as an Exists subquery for filtering."""
    return Exists(
        ProductMedia.objects.filter(
            product_id=OuterRef("pk"),
            role=ProductMedia.Role.MAIN,
            is_active=True,
        )
    )


def staff_products(store_id):
    """The store's active products with the active main image the photo workflow needs."""
    return (
        Product.objects.filter(store_id=store_id, is_active=True)
        .select_related("category")
        .prefetch_related(
            Prefetch(
                "product_media",
                queryset=main_product_images().filter(media__store_id=store_id),
            )
        )
    )


STAFF_PRODUCT_ERRORS = {
    **STORE_ERRORS,
    **problem_response(
        401,
        ("not_authenticated", "Authentication credentials were not provided."),
        ("token_invalid", "Given token not valid for any token type"),
    ),
    **problem_response(
        403,
        ("permission_denied", CanManageCatalog.message),
    ),
}


@extend_schema(
    parameters=[
        STORE_HEADER_PARAMETER,
        CATEGORY_PARAMETER,
        SEARCH_PARAMETER,
        NEEDS_MAIN_IMAGE_PARAMETER,
    ],
    responses={
        200: OpenApiResponse(
            response=StaffProductSerializer(many=True),
            description=(
                "A page of the store's active products with their active main image, for the "
                "photo workflow."
            ),
            examples=[STAFF_PRODUCT_PAGE_EXAMPLE],
        ),
        **STAFF_PRODUCT_ERRORS,
    },
)
class StaffProductListView(StoreScopedMixin, generics.ListAPIView):
    store_permission_classes = [CanManageCatalog]
    serializer_class = StaffProductSerializer
    queryset = Product.objects.none()

    def get_queryset(self):
        store_id = self.request.store.id
        queryset = staff_products(store_id)

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category__slug=category)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__unaccent__icontains=search)

        needs_main_image = self.request.query_params.get("needs_main_image")
        if needs_main_image is not None:
            normalized = needs_main_image.lower()
            if normalized == "true":
                queryset = queryset.filter(~has_active_main_image())
            elif normalized == "false":
                queryset = queryset.filter(has_active_main_image())
            else:
                raise ValidationError({"needs_main_image": ["Use true or false."]})

        return queryset.order_by("name", "id")


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=StaffProductSerializer,
            description=(
                "One of the store's active products with its active main image, for the photo "
                "workflow."
            ),
            examples=[STAFF_PRODUCT_PAGE_EXAMPLE],
        ),
        **STAFF_PRODUCT_ERRORS,
        **problem_response(
            404,
            ("not_found", "No active product matches this id in this store."),
        ),
    },
)
class StaffProductDetailView(StoreScopedMixin, generics.RetrieveAPIView):
    store_permission_classes = [CanManageCatalog]
    serializer_class = StaffProductSerializer
    queryset = Product.objects.none()

    def get_queryset(self):
        return staff_products(self.request.store.id)

    def get_object(self):
        product = self.get_queryset().filter(pk=self.kwargs["pk"]).first()
        if product is None:
            raise NotFound("No active product matches this id in this store.")
        return product
