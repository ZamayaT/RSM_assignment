"""One JSON error shape for every error: {code, message, requestId, details}."""
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "VERSION_CONFLICT",
}


class ApiError(Exception):
    """Raise anywhere in a handler or dependency to return the standard error body."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or f"req-{uuid.uuid4().hex}"


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"code": code, "message": message, "requestId": _request_id(request), "details": details}
    headers = headers or ({"WWW-Authenticate": "Bearer"} if status_code == 401 else None)
    return JSONResponse(body, status_code=status_code, headers=headers)


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = f"req-{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for error in exc.errors():
            # Drop the "body"/"query" prefix; keep the first message per field.
            path = ".".join(str(part) for part in error["loc"][1:]) or "body"
            fields.setdefault(path, error["msg"].removeprefix("Value error, "))
        return error_response(request, 400, "VALIDATION_ERROR", "Some fields are invalid.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        code = _CODES.get(exc.status_code, "ERROR")
        return error_response(request, exc.status_code, code, str(exc.detail))
