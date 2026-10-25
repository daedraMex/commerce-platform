# The X-Store header is read by middleware, enforced by DRF, and resolved behind a port

Store-scoped endpoints identify their store with the `X-Store` header, but the Store model only arrives in Phase 3. The middleware only reads the header and attaches it to the request; it never rejects a request, because a response returned from Django middleware bypasses the DRF exception handler and would not be an RFC 9457 problem details response (ADR-0014). Store-scoped views opt in through a DRF class that raises domain exceptions: `store_header_missing` when the header is absent and `store_header_invalid` when the slug is malformed, both 400. Turning the header into a store goes through a `StoreResolver` port: in Phase 2 it only validates the slug format, and in Phase 3 it is replaced by an implementation that looks the store up and adds `store_not_found`, without touching the views.

## Considered Options

- Reject in the middleware: rejected, because the error would skip the problem details format and the middleware cannot know cleanly which views are store-scoped.
- Wait until Phase 3 to build the header handling: rejected, because Phase 2 fixes the API foundation and store-scoped views need a stable opt-in from the start.
