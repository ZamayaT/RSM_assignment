"""Search evaluation: does the application's search return relevant, honest results? Deterministic, no model.

    docker compose exec backend python -m evals.search

Each case runs the application's own search code (`run_search`, the same code behind the REST endpoint and the
assistant's `search_options` tool) against the real provider mock over HTTP, and checks the result against rules:
every offer satisfies the query, the offers we know exist are present, a party size without an exact quote gets the
next larger one, a failing supplier gives partial results with a warning while the other offers are kept, and an
impossible query is empty or refused with a clear reason. Only supplier failures are set (and cleared again) through
the mock's control interface; nothing else in the mock or the application database is touched.

Exit status: 0 when every case passes, 1 otherwise.
"""
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx

from app.config import get_settings
from app.errors import ApiError
from app.search import SearchIn, run_search

TODAY = date.today()
# The trip the queries are asked for: the three destinations, a year of dates (fixtures start about a month ahead).
TRIP = SimpleNamespace(
    destinations=["Lisbon", "Paris", "Rome"],
    start_date=TODAY,
    end_date=TODAY + timedelta(days=365),
    travelers=2,
)
MOCK = get_settings().provider_base_url.removesuffix("/v1")


@dataclass
class Case:
    id: str
    what: str
    query: dict[str, Any]
    expect_state: str | None = None  # complete, partial or empty
    expect_error: str | None = None  # an ApiError code (the application refuses or the provider fails)
    min_offers: int = 0
    must_include: tuple[str, ...] = ()  # offer ids that exist in the fixtures
    title_prefixes: tuple[str, ...] = ()  # each must start the title of at least one offer (kinds of activity)
    failing_suppliers: dict[str, str] = field(default_factory=dict)  # supplier -> failure mode
    checks: tuple[Callable[[dict, Any], str | None], ...] = ()  # (query, offer) -> problem text or None


# ---- rules every offer must satisfy ----------------------------------------------------------------------


def matches_category(q: dict, o) -> str | None:
    return None if o.category == q["category"] else f"{o.id}: category {o.category}"


def matches_destination(q: dict, o) -> str | None:
    return None if o.destination.lower() == q["destination"].lower() else f"{o.id}: destination {o.destination}"


def fits_party(q: dict, o) -> str | None:
    wanted = q.get("travelers") or TRIP.travelers
    return None if o.travelers >= wanted else f"{o.id}: quote for {o.travelers} traveler(s), wanted {wanted}"


def next_larger_quote(q: dict, o) -> str | None:
    return None if o.travelers == 4 else f"{o.id}: expected the quote for 4 travelers, got {o.travelers}"


def inside_window(q: dict, o) -> str | None:
    starts, ends = q.get("startsOn") or TRIP.start_date, q.get("endsOn") or TRIP.end_date
    if o.startsAt.date() < starts - timedelta(days=1) or o.endsAt.date() > ends + timedelta(days=1):
        return f"{o.id}: {o.startsAt.date()} to {o.endsAt.date()} is outside {starts} to {ends}"
    return None


def from_origin(q: dict, o) -> str | None:
    return None if (o.origin or "").lower() == q["origin"].lower() else f"{o.id}: origin {o.origin}"


def only_supplier(q: dict, o) -> str | None:
    return None if o.providerId == q["providerId"] else f"{o.id}: supplier {o.providerId}"


def usd_with_cents(q: dict, o) -> str | None:
    ok = o.price.currency == "USD" and len(o.price.amount.split(".")[-1]) == 2 and Decimal(o.price.amount) >= 0
    return None if ok else f"{o.id}: price {o.price.amount} {o.price.currency}"


def states_restrictions(q: dict, o) -> str | None:
    return None if isinstance(o.restrictions, list) else f"{o.id}: restrictions is not a list"


def has_quote_validity(q: dict, o) -> str | None:
    return None if o.validUntil and o.revision else f"{o.id}: no quote validity or revision"


BASE = (matches_category, matches_destination, usd_with_cents, states_restrictions, has_quote_validity)

CASES = [
    Case(
        "accommodation-lisbon",
        "accommodation in Lisbon for the trip's party",
        {"category": "accommodation", "destination": "Lisbon"},
        expect_state="complete",
        min_offers=3,
        must_include=("lisbon-accommodation-supplier-alamo-p2", "lisbon-accommodation-supplier-boots-p2", "lisbon-accommodation-supplier-croc-p2"),
        checks=(*BASE, fits_party, inside_window),
    ),
    Case(
        "transport-london-paris",
        "flights from London to Paris",
        {"category": "transport", "destination": "Paris", "origin": "London"},
        expect_state="complete",
        min_offers=2,
        must_include=("paris-transport-london-supplier-alamo-p2", "paris-transport-london-supplier-boots-p2"),
        checks=(*BASE, from_origin, fits_party, inside_window),
    ),
    Case(
        "activities-rome",
        "activities in Rome",
        {"category": "activity", "destination": "Rome"},
        expect_state="complete",
        min_offers=4,
        must_include=("rome-activity-supplier-boots-1-p2", "rome-activity-supplier-croc-2-p2"),
        checks=(*BASE, fits_party, inside_window),
    ),
    Case(
        "party-of-three-gets-the-next-larger-quote",
        "no quote exists for 3 travelers, so the quote for 4 is returned",
        {"category": "accommodation", "destination": "Rome", "travelers": 3},
        expect_state="complete",
        min_offers=3,
        checks=(*BASE, next_larger_quote),
    ),
    Case(
        "one-supplier-only",
        "limiting the search to one supplier",
        {"category": "accommodation", "destination": "Paris", "providerId": "supplier-boots"},
        expect_state="complete",
        min_offers=1,
        checks=(*BASE, only_supplier),
    ),
    Case(
        "date-window-without-offers-is-empty",
        "a window before any fixture offer: empty, not an error",
        {"category": "accommodation", "destination": "Lisbon", "startsOn": TODAY, "endsOn": TODAY + timedelta(days=2)},
        expect_state="empty",
    ),
    Case(
        "one-supplier-down-is-partial",
        "supplier-boots down: the other suppliers' offers are kept and the failure is reported",
        {"category": "accommodation", "destination": "Lisbon"},
        expect_state="partial",
        min_offers=2,
        failing_suppliers={"supplier-boots": "unavailable"},
        checks=(*BASE, lambda q, o: None if o.providerId != "supplier-boots" else f"{o.id}: offer from the failed supplier"),
    ),
    Case(
        "every-supplier-down-is-an-error",
        "all accommodation suppliers down: a failed search, never an empty-looking success",
        {"category": "accommodation", "destination": "Lisbon"},
        expect_error="PROVIDER_UNAVAILABLE",
        failing_suppliers={"supplier-alamo": "unavailable", "supplier-boots": "unavailable", "supplier-croc": "unavailable"},
    ),
    Case(
        "destination-outside-the-trip-is-refused",
        "a destination that is not part of the trip",
        {"category": "accommodation", "destination": "Berlin"},
        expect_error="VALIDATION_ERROR",
    ),
    Case(
        "transport-needs-an-origin",
        "transport without an origin",
        {"category": "transport", "destination": "Rome"},
        expect_error="VALIDATION_ERROR",
    ),
]


# The catalogue spreads offers over November 2026 to January 2027 (from the day after the mock's "today"): every
# month still ahead must return offers inside its own dates, for every kind of offer.
for _year, _month in ((2026, 11), (2026, 12), (2027, 1)):
    _first = max(date(_year, _month, 1), TODAY + timedelta(days=1))
    _last = date(_year + (_month == 12), _month % 12 + 1, 1) - timedelta(days=1)
    if (_last - _first).days < 7:
        continue  # that month is (nearly) over: nothing to expect
    _window = {"startsOn": _first, "endsOn": _last}
    for _query, _min in (
        ({"category": "accommodation", "destination": "Lisbon"}, 2),
        ({"category": "transport", "destination": "Paris", "origin": "London"}, 2),
        ({"category": "activity", "destination": "Rome"}, 3),
    ):
        CASES.append(
            Case(
                f"{_query['category']}-in-{_year}-{_month:02d}",
                f"{_query['category']} offers exist between {_first} and {_last}",
                {**_query, **_window},
                expect_state="complete",
                min_offers=_min,
                checks=(*BASE, fits_party, inside_window),
            )
        )

CASES.append(
    Case(
        "museum-and-food-tours",
        "museum and food places tours are offered in Paris",
        {"category": "activity", "destination": "Paris", "startsOn": TODAY + timedelta(days=1), "endsOn": TODAY + timedelta(days=45)},
        expect_state="complete",
        title_prefixes=("Museum tour", "Food places tour"),
        checks=(*BASE, fits_party, inside_window),
    )
)


# ---- runner ----------------------------------------------------------------------------------------------


def set_failures(modes: dict[str, str]) -> None:
    for supplier in ("supplier-alamo", "supplier-boots", "supplier-croc"):
        if supplier in modes:
            httpx.put(f"{MOCK}/control/suppliers/{supplier}/failure", json={"mode": modes[supplier]}, timeout=10).raise_for_status()
        else:
            httpx.delete(f"{MOCK}/control/suppliers/{supplier}/failure", timeout=10).raise_for_status()


def run_case(case: Case) -> list[str]:
    """The problems found for one case (empty when it passes)."""
    problems: list[str] = []
    set_failures(case.failing_suppliers)
    try:
        result = run_search(TRIP, SearchIn(**case.query), "eval")
    except ApiError as exc:
        if case.expect_error is None:
            return [f"unexpected error {exc.code}: {exc.message}"]
        reason = exc.code if exc.code == case.expect_error else None
        # The provider failure codes depend on the mapping; the rule is that it is an error with a message.
        if reason is None and case.expect_error == "PROVIDER_UNAVAILABLE" and exc.status_code in (429, 502, 503, 504):
            return []
        return [] if reason else [f"expected error {case.expect_error}, got {exc.code}"]
    if case.expect_error:
        return [f"expected error {case.expect_error}, but the search returned {result.state} with {len(result.offers)} offer(s)"]
    if case.expect_state and result.state != case.expect_state:
        problems.append(f"state is {result.state}, expected {case.expect_state}")
    if len(result.offers) < case.min_offers:
        problems.append(f"{len(result.offers)} offer(s), expected at least {case.min_offers}")
    ids = {o.id for o in result.offers}
    problems += [f"known offer {offer_id} is missing" for offer_id in case.must_include if offer_id not in ids]
    problems += [
        f"no offer titled '{prefix}...'" for prefix in case.title_prefixes if not any(o.title.startswith(prefix) for o in result.offers)
    ]
    if case.expect_state == "partial":
        warned = {w.providerId for w in result.warnings}
        if warned != set(case.failing_suppliers):
            problems.append(f"warnings for {sorted(warned)}, expected {sorted(case.failing_suppliers)}")
    elif result.warnings:
        problems.append(f"unexpected warnings: {[w.providerId for w in result.warnings]}")
    if not result.searchedAt:
        problems.append("no searchedAt (freshness) in the result")
    for offer in result.offers:
        for check in case.checks:
            problem = check(case.query, offer)
            if problem:
                problems.append(problem)
    return problems


def main() -> int:
    logging.getLogger("app").setLevel(logging.CRITICAL)  # the cases expect some provider failures: keep the output clean
    try:
        httpx.get(f"{MOCK}/health", timeout=5).raise_for_status()
    except httpx.HTTPError:
        print(f"The provider mock is not reachable at {MOCK}. Start the services first (docker compose up).")
        return 2
    results: list[tuple[Case, list[str]]] = []
    try:
        for case in CASES:
            results.append((case, run_case(case)))
    finally:
        set_failures({})  # never leave a supplier failing
    width = max(len(c.id) for c in CASES)
    for case, problems in results:
        print(f"[{'PASS' if not problems else 'FAIL'}] {case.id.ljust(width)}  {case.what}")
        for problem in problems[:5]:
            print(f"         - {problem}")
        if len(problems) > 5:
            print(f"         - ... and {len(problems) - 5} more")
    passed = sum(1 for _, problems in results if not problems)
    print(f"\n{passed}/{len(results)} cases passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
