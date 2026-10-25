"""RFC 9457 problem details for every API error (ADR-0014)."""

from http import HTTPStatus

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.shared.domain.exceptions import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)

DOMAIN_ERROR_STATUS = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
}

CODE_BY_STATUS = {
    status.HTTP_400_BAD_REQUEST: "validation_error",
    status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
}


def problem_details_exception_handler(exc, context):
    domain_status = _domain_error_status(exc)
    if domain_status is not None:
        return _problem_details(domain_status, code=exc.code, detail=exc.message)

    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.ValidationError):
        return _problem_details(
            response.status_code,
            code="validation_error",
            detail="Validation failed.",
            errors=_validation_errors(exc.detail),
        )

    return _problem_details(
        response.status_code,
        code=_code_for(exc, response.status_code),
        detail=_detail_from(response.data),
    )


def _domain_error_status(exc):
    if not isinstance(exc, DomainError):
        return None

    for error_class in type(exc).__mro__:
        if error_class in DOMAIN_ERROR_STATUS:
            return DOMAIN_ERROR_STATUS[error_class]
    return None


def _code_for(exc, status_code):
    if isinstance(exc, exceptions.NotAuthenticated):
        return "not_authenticated"
    if isinstance(exc, exceptions.AuthenticationFailed):
        return "token_invalid"
    return CODE_BY_STATUS.get(status_code, "error")


def _detail_from(data):
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    if isinstance(data, list):
        return "; ".join(str(item) for item in data)
    return str(data)


def _validation_errors(detail, field=None):
    if isinstance(detail, dict):
        for key, value in detail.items():
            child_field = key if field is None else f"{field}.{key}"
            yield from _validation_errors(value, child_field)
    elif isinstance(detail, (list, tuple)):
        for item in detail:
            yield from _validation_errors(item, field)
    else:
        yield {
            "field": field or "non_field_errors",
            "code": getattr(detail, "code", "invalid"),
            "detail": str(detail),
        }


def _problem_details(status_code, *, code, detail, errors=None):
    body = {
        "type": "about:blank",
        "title": _title_for(status_code),
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    if errors is not None:
        body["errors"] = list(errors)
    return Response(body, status=status_code, content_type="application/problem+json")


def _title_for(status_code):
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"
