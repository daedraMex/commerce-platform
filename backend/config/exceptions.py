"""RFC 9457 problem details for every API error (ADR-0014)."""

import logging
from http import HTTPStatus

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

from apps.shared.domain.exceptions import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)

logger = logging.getLogger(__name__)

INTERNAL_ERROR_DETAIL = "An unexpected error occurred."

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

CODE_OVERRIDES = {
    "authentication_failed": "token_invalid",
    "invalid": "validation_error",
    "token_not_valid": "token_invalid",
}


def problem_details_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        domain_status = _domain_error_status(exc)
        if domain_status is not None:
            return _problem_details(domain_status, code=exc.code, detail=exc.message)

        _log_exception("Unmapped domain error", exc)
        set_rollback()
        return _internal_error()

    response = exception_handler(exc, context)
    if response is None:
        _log_exception("Unhandled API exception", exc)
        set_rollback()
        return _internal_error()

    headers = _headers_from(response)
    if isinstance(exc, exceptions.ValidationError):
        return _problem_details(
            response.status_code,
            code=_code_for(exc, response.status_code),
            detail="Validation failed.",
            errors=_validation_errors(exc.detail),
            headers=headers,
        )

    return _problem_details(
        response.status_code,
        code=_code_for(exc, response.status_code),
        detail=_detail_from(response.data),
        headers=headers,
    )


def _domain_error_status(exc):
    for error_class in type(exc).__mro__:
        if error_class in DOMAIN_ERROR_STATUS:
            return DOMAIN_ERROR_STATUS[error_class]
    return None


def _code_for(exc, status_code):
    default_code = getattr(exc, "default_code", None)
    if default_code is not None:
        return CODE_OVERRIDES.get(default_code, default_code)
    return CODE_BY_STATUS.get(status_code, "internal_error")


def _headers_from(response):
    return {key: value for key, value in response.headers.items() if key.lower() != "content-type"}


def _log_exception(message, exc):
    logger.error(message, exc_info=(type(exc), exc, exc.__traceback__))


def _internal_error():
    return _problem_details(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        detail=INTERNAL_ERROR_DETAIL,
    )


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


def _problem_details(status_code, *, code, detail, errors=None, headers=None):
    body = {
        "type": "about:blank",
        "title": _title_for(status_code),
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    if errors is not None:
        body["errors"] = list(errors)
    return Response(
        body,
        status=status_code,
        headers=headers,
        content_type="application/problem+json",
    )


def _title_for(status_code):
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"
