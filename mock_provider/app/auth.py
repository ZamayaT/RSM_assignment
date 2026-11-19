from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import ApiError

# Demo tokens. The token string itself identifies the caller, which scopes booking visibility and
# idempotency. Token issuance is out of scope.
DEMO_TOKENS = frozenset({"travel-demo-token", "other-demo-token"})

_bearer = HTTPBearer(auto_error=False, description="Demo token: travel-demo-token or other-demo-token")


def get_caller(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Return the caller id for a valid bearer token; otherwise 401 UNAUTHORIZED."""
    if credentials is None or credentials.credentials not in DEMO_TOKENS:
        raise ApiError(
            401,
            "UNAUTHORIZED",
            "The provider token is missing or invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
