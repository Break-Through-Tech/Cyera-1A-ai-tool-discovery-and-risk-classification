from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_HTTP_ERROR_CODES = {
    404: ("not_found", "Resource not found."),
    405: ("method_not_allowed", "Method not allowed."),
}


class AppError(Exception):
    """An application error rendered as the shared ``{code, message, details}`` body."""

    def __init__(
        self, status_code: int, code: str, message: str, details: Any = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Only location and error type: FastAPI's default body echoes the raw input.
        errors = [
            {"location": list(error["loc"]), "problem": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(
                "invalid_request", "The request is invalid.", {"errors": errors}
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code, message = _HTTP_ERROR_CODES.get(
            exc.status_code, ("http_error", "Request failed.")
        )
        return JSONResponse(
            status_code=exc.status_code, content=error_body(code, message)
        )
