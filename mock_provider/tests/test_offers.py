"""Search and get-offer behavior against the seeded fixtures (run inside the container)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import failures
from app.clock import get_clock
from app.db import get_engine
from app.main import app
from app.models import Offer
from app.offers import destination_tz

AUTH = {"Authorization": "Bearer travel-demo-token"}
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_failures():
    failures.clear_all()
    yield
    failures.clear_all()


def _window(destination):
    """Widest destination-local date window covering every fixture offer of that destination."""
    with Session(get_engine()) as session:
        rows = session.scalars(select(Offer).where(func.lower(Offer.destination) == destination.lower())).all()
        if not rows:  # unknown destination: any window will do
            return _window("Lisbon")
    tz = destination_tz(rows[0].destination)
    return (
        min(r.starts_at.astimezone(tz).date() for r in rows).isoformat(),
        max(r.ends_at.astimezone(tz).date() for r in rows).isoformat(),
    )


def _search(**overrides):
    starts, ends = _window(overrides.get("destination", "Lisbon"))
    body = {"category": "accommodation", "destination": "Lisbon", "startsOn": starts, "endsOn": ends, "travelers": 2}
    body.update(overrides)
    return client.post("/v1/offers/search", json=body, headers=AUTH)


# ---- search: results --------------------------------------------------------------------------------

def test_complete_search_returns_offers_from_all_suppliers():
    response = _search()
    assert response.status_code == 200
    body = response.json()
    assert body["partial"] is False and body["warnings"] == []
    assert body["searchedAt"]
    assert {o["providerId"] for o in body["offers"]} == {"supplier-alamo", "supplier-boots", "supplier-croc"}
    for offer in body["offers"]:
        assert offer["category"] == "accommodation" and offer["destination"] == "Lisbon"
        assert offer["travelers"] == 2
        assert Decimal(offer["price"]["amount"]) > 0 and offer["price"]["currency"] == "USD"
        assert "origin" not in offer


def test_destination_matching_is_case_insensitive():
    assert _search(destination="lIsBoN").json()["offers"] == _search().json()["offers"]


def test_transport_requires_origin_and_matches_it_case_insensitively():
    assert _search(category="transport").status_code == 400
    response = _search(category="transport", origin="new YORK")
    offers = response.json()["offers"]
    assert offers and {o["origin"] for o in offers} == {"New York"}
    assert {o["providerId"] for o in offers} == {"supplier-alamo", "supplier-boots"}


def test_provider_id_limits_the_search():
    offers = _search(providerId="supplier-boots").json()["offers"]
    assert offers and {o["providerId"] for o in offers} == {"supplier-boots"}


def test_supplier_without_the_category_returns_empty_complete_result():
    body = _search(category="transport", origin="London", providerId="supplier-croc").json()
    assert body["offers"] == [] and body["partial"] is False


def test_unknown_supplier_is_bad_request():
    assert _search(providerId="supplier-z").status_code == 400


def test_empty_result_is_complete():
    body = _search(destination="Atlantis").json()
    assert body == {"offers": [], "partial": False, "warnings": [], "searchedAt": body["searchedAt"]}


def test_window_must_contain_the_offer():
    starts, _ = _window("Lisbon")
    far_past = (datetime.fromisoformat(starts) - timedelta(days=30)).date().isoformat()
    assert _search(startsOn=far_past, endsOn=far_past).json()["offers"] == []


def test_offers_are_returned_in_destination_local_time():
    offer = _search(destination="Paris").json()["offers"][0]
    assert offer["startsAt"].endswith(("+01:00", "+02:00"))
    assert offer["validUntil"].endswith("Z")


# ---- search: party size -----------------------------------------------------------------------------

def test_party_without_exact_quote_gets_the_next_larger_quote():
    offers = _search(travelers=3).json()["offers"]
    assert offers and {o["travelers"] for o in offers} == {4}
    assert {o["providerId"] for o in offers} == {"supplier-alamo", "supplier-boots", "supplier-croc"}


def test_party_larger_than_any_quote_gets_nothing():
    assert _search(travelers=5).json()["offers"] == []


def test_exact_quote_is_preferred():
    assert {o["travelers"] for o in _search(travelers=1).json()["offers"]} == {1}


# ---- search: validation -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides",
    [
        {"travelers": 0},
        {"travelers": 21},
        {"travelers": "2"},
        {"travelers": 2.5},
        {"startsOn": "2031-01-02", "endsOn": "2031-01-01"},
        {"startsOn": "not-a-date"},
        {"category": "cruise"},
        {"destination": ""},
        {"extra": 1},
    ],
)
def test_invalid_search_input_is_bad_request(overrides):
    response = _search(**overrides)
    assert response.status_code == 400 and response.json()["code"] == "BAD_REQUEST"


def test_search_requires_a_token():
    assert client.post("/v1/offers/search", json={}).status_code == 401


# ---- search: supplier failures ----------------------------------------------------------------------

def test_partial_result_lists_a_warning_for_each_failed_supplier():
    failures.set_failure("supplier-boots", "timeout")
    failures.set_failure("supplier-croc", "unavailable")
    body = _search().json()
    assert body["partial"] is True
    assert {o["providerId"] for o in body["offers"]} == {"supplier-alamo"}
    assert {(w["providerId"], w["code"]) for w in body["warnings"]} == {
        ("supplier-boots", "PROVIDER_TIMEOUT"),
        ("supplier-croc", "PROVIDER_UNAVAILABLE"),
    }


def test_all_suppliers_failing_is_503():
    for supplier in ("supplier-alamo", "supplier-boots", "supplier-croc"):
        failures.set_failure(supplier, "unavailable")
    response = _search()
    assert response.status_code == 503 and response.json()["code"] == "PROVIDER_UNAVAILABLE"


def test_single_rate_limited_supplier_is_429_with_retry_after():
    failures.set_failure("supplier-boots", "rate_limited", retry_after=7)
    response = _search(providerId="supplier-boots")
    assert response.status_code == 429 and response.json()["code"] == "RATE_LIMITED"
    assert response.headers["Retry-After"] == "7"


def test_single_unavailable_supplier_is_503():
    failures.set_failure("supplier-boots", "unavailable")
    assert _search(providerId="supplier-boots").status_code == 503


def test_every_supplier_rate_limited_is_503_not_429():
    for supplier in ("supplier-alamo", "supplier-boots", "supplier-croc"):
        failures.set_failure(supplier, "rate_limited")
    assert _search().status_code == 503


# ---- get offer --------------------------------------------------------------------------------------

def _any_offer(**filters):
    with Session(get_engine()) as session:
        return session.scalars(select(Offer).filter_by(**filters).limit(1)).one()


def test_get_offer_returns_current_quote():
    stored = _any_offer(available=True)
    # Make sure the quote is not expired, so the read is a plain one.
    with Session(get_engine()) as session:
        session.get(Offer, stored.id).valid_until = get_clock().now() + timedelta(days=1)
        session.commit()
    response = client.get(f"/v1/offers/{stored.id}", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == stored.id and body["revision"] == stored.revision and body["available"] is True


def test_get_unavailable_offer_is_returned_with_available_false():
    stored = _any_offer(available=False)
    body = client.get(f"/v1/offers/{stored.id}", headers=AUTH).json()
    assert body["id"] == stored.id and body["available"] is False


def test_get_unknown_offer_is_404():
    response = client.get("/v1/offers/does-not-exist", headers=AUTH)
    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


def test_get_offer_requires_a_token():
    assert client.get("/v1/offers/anything").status_code == 401


def _insert_expired_offer(offer_id):
    now = get_clock().now()
    with Session(get_engine()) as session:
        session.add(
            Offer(
                id=offer_id, provider_id="supplier-alamo", category="activity", title="Expiry test", description="d",
                destination="Rome", starts_at=now + timedelta(days=5), ends_at=now + timedelta(days=5, hours=2),
                travelers=2, price_amount=Decimal("10.00"), currency="USD", revision="r1", available=True,
                valid_until=now - timedelta(minutes=1), updated_at=now,
            )
        )
        session.commit()


def _delete_offer(offer_id):
    with Session(get_engine()) as session:
        session.delete(session.get(Offer, offer_id))
        session.commit()


def test_expired_quote_is_refreshed_with_new_revision_once():
    offer_id = "test-expired-get"
    _insert_expired_offer(offer_id)
    try:
        first = client.get(f"/v1/offers/{offer_id}", headers=AUTH).json()
        assert first["revision"] == "r2"
        assert datetime.fromisoformat(first["validUntil"]) > get_clock().now()
        second = client.get(f"/v1/offers/{offer_id}", headers=AUTH).json()
        assert second["revision"] == "r2" and second["validUntil"] == first["validUntil"]
    finally:
        _delete_offer(offer_id)


def test_search_refreshes_expired_quotes():
    offer_id = "test-expired-search"
    _insert_expired_offer(offer_id)
    try:
        now = get_clock().now()
        day = (now + timedelta(days=5)).astimezone(destination_tz("Rome")).date()
        offers = _search(
            category="activity", destination="Rome", providerId="supplier-alamo",
            startsOn=(day - timedelta(days=1)).isoformat(), endsOn=(day + timedelta(days=1)).isoformat(),
        ).json()["offers"]
        match = [o for o in offers if o["id"] == offer_id]
        assert match and match[0]["revision"] == "r2"
        assert datetime.fromisoformat(match[0]["validUntil"]) > now
    finally:
        _delete_offer(offer_id)


def test_get_offer_of_failing_supplier_follows_the_failure_mode():
    stored = _any_offer(provider_id="supplier-boots")
    failures.set_failure("supplier-boots", "unavailable")
    assert client.get(f"/v1/offers/{stored.id}", headers=AUTH).status_code == 503
    failures.set_failure("supplier-boots", "rate_limited", retry_after=3)
    response = client.get(f"/v1/offers/{stored.id}", headers=AUTH)
    assert response.status_code == 429 and response.headers["Retry-After"] == "3"


# ---- restrictions (the contract's optional Offer.restrictions) --------------------------------------

def test_every_offer_carries_restrictions_as_a_list_and_some_state_none():
    from app.fixtures import RESTRICTIONS

    body = _search().json()
    assert body["offers"] and all(isinstance(o["restrictions"], list) for o in body["offers"])
    assert any(o["restrictions"] for o in body["offers"])
    assert all(any(not options for options in RESTRICTIONS[category]) for category in RESTRICTIONS)  # each category has an offer with none


def test_get_offer_returns_its_restrictions_and_an_offer_without_them_has_an_empty_list(make_offer):
    with_restrictions = make_offer(restrictions=["Minimum age 18"])
    without = make_offer(restrictions=[])
    assert client.get(f"/v1/offers/{with_restrictions}", headers=AUTH).json()["restrictions"] == ["Minimum age 18"]
    assert client.get(f"/v1/offers/{without}", headers=AUTH).json()["restrictions"] == []


def test_restrictions_follow_the_catalogue_rule_and_survive_a_control_change(make_offer):
    from app.fixtures import restrictions_for

    stored = _any_offer(available=True)
    assert list(stored.restrictions) == restrictions_for(stored.id, stored.category)
    offer_id = make_offer(restrictions=["Photo ID required at check-in"])
    client.post(f"/control/offers/{offer_id}", json={"price": "120.50"})
    assert client.get(f"/v1/offers/{offer_id}", headers=AUTH).json()["restrictions"] == ["Photo ID required at check-in"]
