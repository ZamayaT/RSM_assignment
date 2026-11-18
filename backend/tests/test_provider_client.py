"""Provider client against a stubbed HTTP transport (no network, no database)."""
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
