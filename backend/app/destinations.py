from fastapi import APIRouter

# Destinations the provider mock supports; the frontend reads them from the API.
SUPPORTED_DESTINATIONS = ("Lisbon", "Paris", "Rome")

router = APIRouter()


@router.get("/destinations")
def list_destinations() -> list[str]:
    return list(SUPPORTED_DESTINATIONS)
