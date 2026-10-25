"""OpenAPI declarations shared by every endpoint."""

PROBLEM_DETAILS_SCHEMA = {
    "type": "object",
    "description": "RFC 9457 problem details returned by every API error (ADR-0014).",
    "required": ["type", "title", "status", "detail", "code"],
    "properties": {
        "type": {
            "type": "string",
            "description": "Problem type URI. Always `about:blank` for now.",
            "example": "about:blank",
        },
        "title": {
            "type": "string",
            "description": "Short human-readable summary of the problem.",
            "example": "Not Found",
        },
        "status": {
            "type": "integer",
            "description": "HTTP status code.",
            "example": 404,
        },
        "detail": {
            "type": "string",
            "description": "Human-readable explanation of this occurrence.",
            "example": "No resource matches this route.",
        },
        "code": {
            "type": "string",
            "description": "Stable snake_case code to branch on.",
            "example": "not_found",
        },
        "errors": {
            "type": "array",
            "description": "Field-level errors, present on validation failures.",
            "items": {
                "type": "object",
                "required": ["field", "code", "detail"],
                "properties": {
                    "field": {"type": "string"},
                    "code": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}

PROBLEM_DETAILS_COMPONENTS = {"schemas": {"ProblemDetails": PROBLEM_DETAILS_SCHEMA}}
