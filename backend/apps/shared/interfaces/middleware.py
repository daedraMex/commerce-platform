class StoreHeaderMiddleware:
    """Expose the raw X-Store header on the request without validating it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.store_slug = request.headers.get("X-Store")
        return self.get_response(request)
