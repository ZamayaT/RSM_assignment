"""Itinerary status and warnings: pure functions, no database."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.itinerary_rules import (
    DESTINATION_NOT_IN_TRIP,
    EXPIRED_QUOTE,
    MISSING_PRICE,
    MISSING_SCHEDULE,
    OUTSIDE_TRIP_DATES,
    SCHEDULE_CONFLICT,
    STATUS_ESTIMATE,
    STATUS_EXPIRED,
    ItemFacts,
    TripFacts,
    evaluate,
)

NOW = datetime(2030, 1, 10, 9, 0, tzinfo=timezone.utc)
TRIP = TripFacts(date(2030, 1, 10), date(2030, 1, 20), ("Lisbon", "Rome"))


def at(day: int, hour: int = 0, tz=timezone.utc) -> datetime:
    return datetime(2030, 1, day, hour, tzinfo=tz)


def item(id, category="activity", start=None, end=None, destination="Lisbon", price="10.00", valid_until="future"):
    return ItemFacts(
        id=id,
        title=f"item {id}",
        category=category,
        destination=destination,
        starts_at=start,
        ends_at=end,
        price_amount=None if price is None else Decimal(price),
        valid_until=NOW + timedelta(hours=1) if valid_until == "future" else valid_until,
    )


def codes(result, id):
    return [w.code for w in result[id].warnings]


def test_clean_item_is_an_estimate_without_warnings():
    result = evaluate([item("a", start=at(12, 10), end=at(12, 12))], TRIP, NOW)

    assert result["a"].status == STATUS_ESTIMATE and result["a"].warnings == []


def test_overlapping_items_conflict_on_both_sides():
    a = item("a", start=at(12, 10), end=at(12, 12))
    b = item("b", category="transport", start=at(12, 11), end=at(12, 13))

    result = evaluate([a, b], TRIP, NOW)

    assert codes(result, "a") == [SCHEDULE_CONFLICT] and codes(result, "b") == [SCHEDULE_CONFLICT]
    assert "item b" in result["a"].warnings[0].message


def test_end_equal_to_start_is_not_a_conflict():
    a = item("a", start=at(12, 10), end=at(12, 12))
    b = item("b", start=at(12, 12), end=at(12, 14))

    assert SCHEDULE_CONFLICT not in codes(evaluate([a, b], TRIP, NOW), "a")


def test_times_are_compared_as_utc_instants_across_offsets():
    plus_two = timezone(timedelta(hours=2))
    a = item("a", start=at(12, 10), end=at(12, 12))  # 10:00-12:00 UTC
    b = item("b", start=at(12, 13, plus_two), end=at(12, 14, plus_two))  # 11:00-12:00 UTC
    c = item("c", start=at(12, 14, plus_two), end=at(12, 15, plus_two))  # 12:00-13:00 UTC

    result = evaluate([a, b, c], TRIP, NOW)

    assert SCHEDULE_CONFLICT in codes(result, "b")
    assert SCHEDULE_CONFLICT not in codes(result, "c")


def test_accommodation_may_overlap_activities_and_transport():
    stay = item("stay", category="accommodation", start=at(12, 15), end=at(15, 11))
    activity = item("act", start=at(13, 10), end=at(13, 12))
    flight = item("fly", category="transport", start=at(12, 8), end=at(12, 16))

    result = evaluate([stay, activity, flight], TRIP, NOW)

    assert all(SCHEDULE_CONFLICT not in codes(result, i) for i in ("stay", "act", "fly"))


def test_two_overlapping_accommodations_conflict():
    one = item("one", category="accommodation", start=at(12, 15), end=at(15, 11))
    two = item("two", category="accommodation", start=at(14, 15), end=at(17, 11))

    result = evaluate([one, two], TRIP, NOW)

    assert SCHEDULE_CONFLICT in codes(result, "one") and SCHEDULE_CONFLICT in codes(result, "two")


def test_expired_quote_changes_status_and_warns():
    expired = item("a", start=at(12), end=at(13), valid_until=NOW - timedelta(seconds=1))
    still_valid = item("b", start=at(14), end=at(15), valid_until=NOW)

    result = evaluate([expired, still_valid], TRIP, NOW)

    assert result["a"].status == STATUS_EXPIRED and EXPIRED_QUOTE in codes(result, "a")
    assert result["b"].status == STATUS_ESTIMATE and EXPIRED_QUOTE not in codes(result, "b")


def test_missing_schedule_and_price_are_flagged():
    result = evaluate([item("a", price=None, valid_until=None)], TRIP, NOW)

    assert set(codes(result, "a")) == {MISSING_SCHEDULE, MISSING_PRICE}


def test_item_without_schedule_never_conflicts():
    a = item("a")
    b = item("b", start=at(12, 10), end=at(12, 12))

    assert SCHEDULE_CONFLICT not in codes(evaluate([a, b], TRIP, NOW), "b")


def test_outside_trip_dates_uses_the_utc_date():
    before = item("before", start=at(9, 10), end=at(9, 11))
    after = item("after", start=at(20, 10), end=at(21, 1))
    inside = item("inside", start=at(10, 0), end=at(20, 23))

    result = evaluate([before, after, inside], TRIP, NOW)

    assert OUTSIDE_TRIP_DATES in codes(result, "before") and OUTSIDE_TRIP_DATES in codes(result, "after")
    assert OUTSIDE_TRIP_DATES not in codes(result, "inside")


def test_destination_not_in_trip_is_flagged():
    result = evaluate([item("a", destination="Paris", start=at(12), end=at(13))], TRIP, NOW)

    assert codes(result, "a") == [DESTINATION_NOT_IN_TRIP]


# --- booking states ---


def booked(id, booking, **kwargs):
    return ItemFacts(**{**item(id, **kwargs).__dict__, "booking": booking})


def test_booking_states_set_the_item_status():
    result = evaluate(
        [
            booked("a", "initiated"),
            booked("b", "pending"),
            booked("c", "confirmed"),
            booked("d", "failed"),
            booked("e", "unknown"),
        ],
        TRIP,
        NOW,
    )

    assert [result[i].status for i in "abcde"] == ["booking_pending", "booking_pending", "confirmed", "failed", "unknown"]


def test_live_booking_drops_the_expired_quote_warning_but_failed_keeps_it():
    expired = NOW - timedelta(hours=1)
    result = evaluate(
        [booked("a", "confirmed", valid_until=expired), booked("b", "failed", valid_until=expired), item("c", valid_until=expired)],
        TRIP,
        NOW,
    )

    assert EXPIRED_QUOTE not in codes(result, "a")
    assert result["b"].status == "failed" and EXPIRED_QUOTE in codes(result, "b")
    assert result["c"].status == STATUS_EXPIRED
