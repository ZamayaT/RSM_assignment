from fastapi import APIRouter, Depends

from app.auth import get_caller

# Every contract operation is added to this router, so all of them require a valid token.
# Authentication runs before request validation, so a bad token always wins over a bad body.
v1_router = APIRouter(prefix="/v1", dependencies=[Depends(get_caller)])
