from fastapi import APIRouter, Depends

from app.auth import get_caller
from app.bookings_routes import router as bookings_router
from app.offers_routes import router as offers_router

# Every contract operation is added to this router, so all of them require a valid token.
# Authentication runs before request validation, so a bad token always wins over a bad body.
v1_router = APIRouter(prefix="/v1", dependencies=[Depends(get_caller)])
v1_router.include_router(offers_router)
v1_router.include_router(bookings_router)
