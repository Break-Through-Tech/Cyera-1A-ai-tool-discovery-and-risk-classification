from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_HTTP_ERROR_CODES = {
    404: ("not_found", "Resource not found."),
    405: ("method_not_allowed", "Method not allowed."),
}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return body


def register_error_handlers(app: FastAPI) -> None:
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
