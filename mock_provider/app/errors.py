"""Contract error format: {code, message, requestId, details?} for every error the mock returns."""
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

BAD_REQUEST_MESSAGE = "Invalid request parameters or body."


class ApiError(Exception):
    """Raise anywhere in a handler or dependency to return a contract error."""

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
    body = {"code": code, "message": message, "requestId": _request_id(request)}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status_code, headers=headers)


def install_error_handling(app: FastAPI) -> None:
    """Attach the request-id middleware and the handlers that map framework errors to the contract format."""

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
        errors = [
            {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
            for error in exc.errors()
        ]
        return error_response(request, 400, "BAD_REQUEST", BAD_REQUEST_MESSAGE, {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return error_response(request, 404, "NOT_FOUND", "No visible record exists for the supplied identifier.")
        return error_response(request, exc.status_code, "BAD_REQUEST", BAD_REQUEST_MESSAGE, headers=exc.headers)
