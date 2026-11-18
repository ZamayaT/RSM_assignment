import { Alert, Box, Button, Chip, CircularProgress, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink, useLocation, useParams } from "react-router-dom";
import { api, ApiError, type Budget, type Itinerary, type Trip } from "../api";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography sx={{ whiteSpace: "pre-wrap" }}>{value}</Typography>
    </Box>
  );
}

export default function TripOverview() {
  const { id = "" } = useParams();
  const location = useLocation();
  const justSaved = (location.state as { saved?: boolean } | null)?.saved;
  const [trip, setTrip] = useState<Trip | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The summary is optional: if it cannot be loaded the rest of the overview still works.
  const [budget, setBudget] = useState<Budget | null>(null);
  const [itinerary, setItinerary] = useState<Itinerary | null>(null);

  useEffect(() => {
    setTrip(null);
    setError(null);
    setBudget(null);
    setItinerary(null);
    api.getTrip(id).then(setTrip).catch((e: ApiError) => setError(e.status === 404 ? "Trip not found." : e.message));
    api.budget(id).then(setBudget).catch(() => undefined);
    api.itinerary(id).then(setItinerary).catch(() => undefined);
  }, [id]);

  if (error)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (!trip) return <CircularProgress aria-label="Loading trip" />;

  const canEdit = trip.role === "organizer" || trip.role === "editor";

  return (
    <Stack spacing={2}>
      {justSaved && <Alert severity="success">Trip saved.</Alert>}
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>{trip.name}</Typography>
        <Chip label={trip.role} />
        {canEdit && (
          <Button variant="contained" component={RouterLink} to={`/trips/${trip.id}/edit`}>
            Edit
          </Button>
        )}
      </Stack>
      <Row label="Dates" value={`${trip.startDate} – ${trip.endDate}`} />
      <Row label="Destinations" value={trip.destinations.join(", ")} />
      <Row label="Travelers" value={String(trip.travelers)} />
      <Row label="Budget (USD)" value={trip.budget} />
      {budget && (
        <Row
          label="Estimated total (USD)"
          value={`${budget.estimatedTotal} — ${
            budget.overBudget ? `over budget by ${budget.remaining.replace("-", "")}` : `${budget.remaining} remaining`
          }`}
        />
      )}
      {itinerary && (
        <Row
          label="Itinerary"
          value={`${itinerary.items.length} item(s), ${itinerary.items.reduce((n, i) => n + i.warnings.length, 0)} warning(s)`}
        />
      )}
      {trip.notes && <Row label="Notes" value={trip.notes} />}
      <Stack direction="row" spacing={2}>
        <Button variant="contained" component={RouterLink} to={`/trips/${trip.id}/search`}>Search</Button>
        <Button component={RouterLink} to={`/trips/${trip.id}/itinerary`}>Itinerary</Button>
        <Button component={RouterLink} to={`/trips/${trip.id}/budget`}>Budget</Button>
        <Button component={RouterLink} to={`/trips/${trip.id}/participants`}>Participants</Button>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Stack>
    </Stack>
  );
}
