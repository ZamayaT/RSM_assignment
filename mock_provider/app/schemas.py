"""Typed request and response models for the contract (field names follow the contract's camelCase)."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal["transport", "accommodation", "activity"]


class Money(BaseModel):
    amount: str = Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{2}$")
    currency: Literal["USD"]


class OfferOut(BaseModel):
    id: str
    providerId: str
    category: Category
    title: str
    description: str
    destination: str
    origin: str | None = None
    startsAt: datetime
    endsAt: datetime
    travelers: int
    price: Money
    revision: str
    available: bool
    validUntil: datetime
    restrictions: list[str] = Field(default_factory=list)  # always a list; empty when the supplier states none


class SupplierWarning(BaseModel):
    providerId: str
    code: Literal["PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT", "RATE_LIMITED"]
    message: str


class SearchResponse(BaseModel):
    offers: list[OfferOut]
    partial: bool
    warnings: list[SupplierWarning]
    searchedAt: datetime


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    destination: str = Field(min_length=1, max_length=200)
    origin: str | None = Field(default=None, min_length=1, max_length=200)
    startsOn: date
    endsOn: date
    travelers: Annotated[int, Field(strict=True, ge=1, le=20)]
    providerId: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _check_rules(self):
        if self.category == "transport" and self.origin is None:
            raise ValueError("origin is required for transport searches")
        if self.startsOn > self.endsOn:
            raise ValueError("startsOn must be on or before endsOn")
        return self


class CreateBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clientReference: str = Field(min_length=1, max_length=128)
    offerId: str = Field(min_length=1, max_length=128)
    expectedOfferRevision: str = Field(min_length=1)
    expectedPrice: Money


class BookingFailure(BaseModel):
    code: str
    message: str


class BookingOut(BaseModel):
    id: str
    clientReference: str
    offer: OfferOut
    status: Literal["pending", "confirmed", "failed"]
    createdAt: datetime
    updatedAt: datetime
    failure: BookingFailure | None = None
