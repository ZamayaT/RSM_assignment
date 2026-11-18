import { Alert, Box, Button, Chip, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { api, ApiError, type Itinerary as ItineraryData, type ItineraryItem, type Trip } from "../api";
import ConflictDialog, { type PendingChange } from "../ConflictDialog";
import { stamp } from "../format";

interface Notice {
  severity: "success" | "error" | "info";
  text: string;
}

export default function Itinerary() {
  const { id = "" } = useParams();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [itinerary, setItinerary] = useState<ItineraryData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [conflict, setConflict] = useState<{ change: PendingChange; latest: ItineraryData } | null>(null);

  useEffect(() => {
    Promise.all([api.getTrip(id), api.itinerary(id)])
      .then(([t, it]) => {
        setTrip(t);
        setItinerary(it);
      })
      .catch((e: ApiError) => setLoadError(e.status === 404 ? "Trip not found." : e.message));
  }, [id]);

  // Runs one change. "Saved" is only shown after the server confirmed it.
  async function perform(change: PendingChange, version: number) {
    setBusy(true);
    setNotice(null);
    try {
      setItinerary(await change.apply(version));
      setConflict(null);
      setNotice({ severity: "success", text: "Saved." });
    } catch (e) {
      const error = e as ApiError;
      if (error.status === 409 && error.latestState) {
        setItinerary(error.latestState.itinerary);
        setConflict({ change, latest: error.latestState.itinerary });
      } else {
        setConflict(null);
        setNotice({
          severity: "error",
          text:
            error.status === 404 || error.fields.itemIds
              ? "Your change could not be applied because the itinerary has changed. Showing the latest version."
              : error.message,
        });
        api.itinerary(id).then(setItinerary).catch(() => undefined);
      }
    } finally {
      setBusy(false);
    }
  }

  if (loadError)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (!trip || !itinerary) return <CircularProgress aria-label="Loading itinerary" />;

  const canEdit = trip.role === "organizer" || trip.role === "editor";
  const items = itinerary.items;

  function remove(item: ItineraryItem) {
    void perform(
      { description: `Remove “${item.title}” from the itinerary.`, apply: (v) => api.removeFromItinerary(id, item.id, v) },
      itinerary!.version,
    );
  }

  function move(index: number, delta: -1 | 1) {
    const ids = items.map((i) => i.id);
    const target = index + delta;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    void perform(
      {
        description: `Move “${items[index].title}” ${delta < 0 ? "up" : "down"} to position ${target + 1}.`,
        apply: (v) => api.reorderItinerary(id, ids, v),
      },
      itinerary!.version,
    );
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Itinerary — {trip.name}</Typography>
        <Button component={RouterLink} to={`/trips/${id}/budget`}>Budget</Button>
        {canEdit && <Button variant="contained" component={RouterLink} to={`/trips/${id}/search`}>Search</Button>}
        <Button component={RouterLink} to={`/trips/${id}`}>Back to trip</Button>
      </Stack>

      <Alert severity="info">
        <strong>How scheduling is checked (simplified).</strong> Times are compared as UTC instants. Two items conflict when
        their time ranges overlap (an end equal to the next start is fine); a stay may overlap activities and transport,
        but two overlapping stays conflict. We also flag missing schedule or price, expired quotes, items outside the trip
        dates, and destinations not on the trip. Travel time and opening hours are not checked. All prices are estimates,
        not bookings.
      </Alert>

      {notice && <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.text}</Alert>}

      {items.length === 0 ? (
        <Alert severity="info">
          The itinerary is empty.{canEdit ? " Use Search and “Add to itinerary” to plan the trip." : ""}
        </Alert>
      ) : (
        <Stack spacing={1.5}>
          {items.map((item, index) => (
            <Paper key={item.id} variant="outlined" sx={{ p: 2 }}>
              <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
                <Typography color="text.secondary" sx={{ minWidth: 24 }}>{index + 1}.</Typography>
                <Box sx={{ flexGrow: 1 }}>
                  <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                    <Typography variant="subtitle1">{item.title}</Typography>
                    <Chip size="small" label={item.category} />
                    {item.status === "expired_quote" ? (
                      <Chip size="small" color="warning" label="Expired quote" />
                    ) : (
                      <Chip size="small" variant="outlined" label="Estimate" />
                    )}
                  </Stack>
                  <Typography variant="body2" color="text.secondary">{item.description}</Typography>
                  <Typography variant="body2">
                    {item.destination}
                    {item.origin ? ` (from ${item.origin})` : ""} · {stamp(item.startsAt)} → {stamp(item.endsAt)}
                  </Typography>
                  <Typography variant="body2">
                    {item.price ? `≈ ${item.price.amount} ${item.price.currency}` : "No price"} · {item.providerId} · quote valid
                    until {stamp(item.validUntil)}
                  </Typography>
                  {item.warnings.map((w, n) => (
                    <Alert key={n} severity="warning" sx={{ mt: 1, py: 0 }}>{w.message}</Alert>
                  ))}
                </Box>
                {canEdit && (
                  <Stack direction="row" spacing={0.5}>
                    <Button size="small" disabled={busy || index === 0} onClick={() => move(index, -1)} aria-label={`Move ${item.title} up`}>
                      Up
                    </Button>
                    <Button size="small" disabled={busy || index === items.length - 1} onClick={() => move(index, 1)} aria-label={`Move ${item.title} down`}>
                      Down
                    </Button>
                    <Button size="small" color="error" disabled={busy} onClick={() => remove(item)}>
                      Remove
                    </Button>
                  </Stack>
                )}
              </Stack>
            </Paper>
          ))}
        </Stack>
      )}

      {conflict && (
        <ConflictDialog
          change={conflict.change}
          latest={conflict.latest}
          busy={busy}
          onDiscard={() => {
            setConflict(null);
            setNotice({ severity: "info", text: "Your change was discarded. Showing the latest itinerary." });
          }}
          onReapply={() => void perform(conflict.change, conflict.latest.version)}
        />
      )}
    </Stack>
  );
}
