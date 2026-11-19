"""Provider client against a stubbed HTTP transport (no network, no database)."""
import json

import httpx
import pytest

from app import provider_client as provider

PARAMS = provider.SearchParams(
    category="accommodation", destination="Lisbon", startsOn="2030-01-01", endsOn="2030-01-10", travelers=2
)

OFFER = {
    "id": "o-1",
    "providerId": "supplier-a",
    "category": "accommodation",
    "title": "Stay",
    "description": "Three nights",
    "destination": "Lisbon",
    "startsAt": "2030-01-02T15:00:00+00:00",
    "endsAt": "2030-01-05T11:00:00+00:00",
    "travelers": 2,
    "price": {"amount": "120.00", "currency": "USD"},
    "revision": "r1",
    "available": True,
    "validUntil": "2030-01-01T10:00:00Z",
}


def stub(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def respond(status: int, json=None, headers=None, text=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status, text=text, headers=headers)
        return httpx.Response(status, json=json, headers=headers)

    return stub(handler)


def test_success_returns_typed_result_and_sends_token_and_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(
            200, json={"offers": [OFFER], "partial": False, "warnings": [], "searchedAt": "2030-01-01T09:00:00Z"}
        )

    result = provider.search_offers(PARAMS, stub(handler))

    assert result.partial is False and result.warnings == []
    assert result.offers[0].id == "o-1" and result.offers[0].price.amount == "120.00"
    assert seen["auth"].startswith("Bearer ") and seen["path"].endswith("/offers/search")
    assert b'"startsOn":"2030-01-01"' in seen["body"].replace(b" ", b"")
    assert b"origin" not in seen["body"]


def test_partial_result_keeps_offers_and_warnings():
    body = {
        "offers": [OFFER],
        "partial": True,
        "warnings": [{"providerId": "supplier-b", "code": "PROVIDER_UNAVAILABLE", "message": "down"}],
        "searchedAt": "2030-01-01T09:00:00Z",
    }

    result = provider.search_offers(PARAMS, respond(200, body))

    assert result.partial is True
    assert len(result.offers) == 1
    assert [w.providerId for w in result.warnings] == ["supplier-b"]


def test_400_carries_the_field_messages():
    body = {"code": "BAD_REQUEST", "details": {"errors": [{"field": "body.providerId", "message": "unknown supplier"}]}}

    with pytest.raises(provider.ProviderBadRequest) as caught:
        provider.search_offers(PARAMS, respond(400, body, {"X-Request-Id": "req-1"}))

    assert caught.value.fields == {"providerId": "unknown supplier"}
    assert caught.value.request_id == "req-1"


def test_429_carries_retry_after():
    with pytest.raises(provider.ProviderRateLimited) as caught:
        provider.search_offers(PARAMS, respond(429, {}, {"Retry-After": "7"}))

    assert caught.value.retry_after == 7


def test_429_without_retry_after():
    with pytest.raises(provider.ProviderRateLimited) as caught:
        provider.search_offers(PARAMS, respond(429, {}))

    assert caught.value.retry_after is None


def test_503_is_unavailable():
    with pytest.raises(provider.ProviderUnavailable):
        provider.search_offers(PARAMS, respond(503, {"code": "PROVIDER_UNAVAILABLE"}))


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(provider.ProviderTimeout):
        provider.search_offers(PARAMS, stub(handler))


def test_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(provider.ProviderUnreachable):
        provider.search_offers(PARAMS, stub(handler))


@pytest.mark.parametrize(
    "transport",
    [
        respond(200, text="not json"),
        respond(200, {"offers": "nope"}),
        respond(200, {"offers": [{"id": "x"}], "partial": False, "warnings": [], "searchedAt": "2030-01-01T09:00:00Z"}),
        respond(500, {"code": "ERROR"}),
        respond(401, {"code": "UNAUTHORIZED"}),
    ],
    ids=["not-json", "wrong-shape", "offer-missing-fields", "status-500", "status-401"],
)
def test_malformed_or_unexpected_response(transport):
    with pytest.raises(provider.ProviderMalformedResponse):
        provider.search_offers(PARAMS, transport)


# --- get_offer ---


def test_get_offer_returns_the_offer_and_encodes_the_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.raw_path.decode()
        return httpx.Response(200, json=OFFER)

    offer = provider.get_offer("a/b c", stub(handler))

    assert offer.id == "o-1" and offer.price.amount == "120.00"
    assert seen["path"].endswith("/offers/a%2Fb%20c")


def test_get_offer_unknown_id_is_not_found():
    with pytest.raises(provider.ProviderNotFound):
        provider.get_offer("nope", respond(404, {"code": "NOT_FOUND"}))


@pytest.mark.parametrize(
    "transport, error",
    [
        (respond(429, {}, {"Retry-After": "3"}), provider.ProviderRateLimited),
        (respond(503, {}), provider.ProviderUnavailable),
        (respond(200, {"id": "x"}), provider.ProviderMalformedResponse),
        (respond(500, {}), provider.ProviderMalformedResponse),
    ],
    ids=["429", "503", "wrong-shape", "500"],
)
def test_get_offer_failures_are_typed(transport, error):
    with pytest.raises(error):
        provider.get_offer("o-1", transport)


# ---- Bookings ----

BOOKING = {
    "id": "b-1",
    "clientReference": "trip-1-item-1-abc",
    "offer": {**OFFER, "restrictions": ["Non-refundable"]},
    "status": "pending",
    "createdAt": "2030-01-01T09:00:00Z",
    "updatedAt": "2030-01-01T09:00:00Z",
}
PRICE = provider.Money(amount="120.00", currency="USD")


def create(transport):
    return provider.create_booking("trip-1-item-1-abc", "o-1", "r1", PRICE, "booking-intent-1", transport)


def test_create_booking_sends_key_and_body_and_reports_new_vs_replay():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["Idempotency-Key"]
        seen["body"] = json.loads(request.read())
        return httpx.Response(seen.get("status", 201), json=BOOKING)

    created = create(stub(handler))
    assert created.replayed is False and created.booking.status == "pending"
    assert seen["key"] == "booking-intent-1"
    assert seen["body"] == {
        "clientReference": "trip-1-item-1-abc",
        "offerId": "o-1",
        "expectedOfferRevision": "r1",
        "expectedPrice": {"amount": "120.00", "currency": "USD"},
    }

    seen["status"] = 200
    assert create(stub(handler)).replayed is True


def test_failed_booking_carries_failure():
    failed = {**BOOKING, "status": "failed", "failure": {"code": "PAYMENT_DECLINED", "message": "Declined"}}
    booking = create(respond(201, failed)).booking
    assert booking.status == "failed" and booking.failure.code == "PAYMENT_DECLINED"


@pytest.mark.parametrize(
    "code, error",
    [
        ("OFFER_CHANGED", provider.ProviderOfferChanged),
        ("OFFER_UNAVAILABLE", provider.ProviderOfferUnavailable),
        ("REFERENCE_CONFLICT", provider.ProviderReferenceConflict),
        ("IDEMPOTENCY_CONFLICT", provider.ProviderIdempotencyConflict),
        ("SOMETHING_ELSE", provider.ProviderMalformedResponse),
    ],
)
def test_create_booking_conflicts_are_typed(code, error):
    with pytest.raises(error):
        create(respond(409, {"code": code, "message": "x", "requestId": "r"}))


@pytest.mark.parametrize(
    "transport, error",
    [
        (respond(400, {"details": {"errors": [{"field": "body.offerId", "message": "bad"}]}}), provider.ProviderBadRequest),
        (respond(429, {}, {"Retry-After": "2"}), provider.ProviderRateLimited),
        (respond(503, {}), provider.ProviderUnavailable),
        (respond(500, {}), provider.ProviderMalformedResponse),
        (respond(201, {"id": "x"}), provider.ProviderMalformedResponse),
        (respond(201, text="not json"), provider.ProviderMalformedResponse),
    ],
    ids=["400", "429", "503", "500", "wrong-shape", "not-json"],
)
def test_create_booking_failures_are_typed(transport, error):
    with pytest.raises(error):
        create(transport)


def test_create_booking_timeout_and_unreachable():
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(provider.ProviderTimeout):
        create(stub(timeout))
    with pytest.raises(provider.ProviderUnreachable):
        create(stub(down))


def test_get_booking_and_by_reference_paths_and_not_found():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json=BOOKING)

    assert provider.get_booking("b/1", stub(handler)).id == "b-1"
    assert provider.get_booking_by_reference("trip 1", stub(handler)).clientReference == "trip-1-item-1-abc"
    assert seen[0].endswith("/bookings/b%2F1") and seen[1].endswith("/bookings/by-reference/trip%201")

    with pytest.raises(provider.ProviderNotFound):
        provider.get_booking_by_reference("x", respond(404, {"code": "NOT_FOUND"}))
