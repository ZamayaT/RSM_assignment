import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { api, ApiError, type BookingAttempt, type Bookings as BookingsData, type Trip } from "../api";
import BookDialog from "../BookDialog";
import { stamp } from "../format";

const POLL_MS = 3000;

const CHIP: Record<string, { label: string; color: "default" | "info" | "success" | "warning" | "error" }> = {
  initiated: { label: "Pending", color: "info" },
  pending: { label: "Pending", color: "info" },
  confirmed: { label: "Confirmed", color: "success" },
  failed: { label: "Failed", color: "error" },
  unknown: { label: "Unknown", color: "warning" },
};

// An attempt the page keeps refreshing: the outcome can still change on its own.
const isLive = (a: BookingAttempt) =>
  a.status === "initiated" || a.status === "pending" || (a.status === "unknown" && !a.unresolved);

function explain(a: BookingAttempt): string {
  switch (a.status) {
    case "initiated":
    case "pending":
      return a.takingLonger
        ? "Taking longer than expected. The booking is still pending with the provider; nothing is lost, and this page keeps updating."
        : "The booking is in progress. This page updates by itself.";
    case "confirmed":
      return `Booked at the accepted price of ${a.acceptedPrice?.amount} ${a.acceptedPrice?.currency}.`;
    case "failed":
      return `${a.failure?.message ?? "The booking failed."} Nothing was booked.`;
    default:
      return a.unresolved
        ? "Outcome unresolved: we could not reach the provider to find out what happened. It is not marked failed or confirmed. Use Check again once the provider is back."
        : "We did not get an answer from the provider, so we are checking what really happened. This is not a failure and nothing will be booked twice.";
  }
}

export default function Bookings() {
  const { id = "" } = useParams();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [data, setData] = useState<BookingsData | null>(null);
  const [items, setItems] = useState<{ id: string; title: string }[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [retry, setRetry] = useState<{ id: string; title: string } | null>(null);
  const loading = useRef(false);

  const reload = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    try {
      setData(await api.bookings(id));
    } catch (e) {
      setLoadError((e as ApiError).status === 404 ? "Trip not found." : (e as ApiError).message);
    } finally {
      loading.current = false;
    }
  }, [id]);

  useEffect(() => {
    api.getTrip(id).then(setTrip).catch((e: ApiError) => setLoadError(e.status === 404 ? "Trip not found." : e.message));
    api.itinerary(id).then((it) => setItems(it.items.map((i) => ({ id: i.id, title: i.title })))).catch(() => undefined);
    void reload();
  }, [id, reload]);

  // Keep updating while any attempt can still change; this also resumes after a page reload.
  const anyLive = data?.attempts.some(isLive) ?? false;
  useEffect(() => {
    if (!anyLive) return;
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyLive, reload]);

  async function check(attempt: BookingAttempt) {
    setChecking(attempt.id);
    setNotice(null);
    try {
      const updated = await api.checkBooking(id, attempt.id);
      if (updated.status === attempt.status && updated.status !== "confirmed" && updated.status !== "failed") {
        setNotice("Still no final answer from the provider. Nothing was booked twice; try again later.");
      }
      await reload();
    } catch (e) {
      setNotice((e as ApiError).message);
    } finally {
      setChecking(null);
    }
  }

  if (loadError)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (!trip || !data) return <CircularProgress aria-label="Loading bookings" />;

  const canEdit = trip.role === "organizer" || trip.role === "editor";
  const { confirmed, failed, unknown, pending } = data.counts;
  const latestPerItem = new Set<string>();
  const latestIds = new Set(
    data.attempts.filter((a) => (latestPerItem.has(a.itemId) ? false : (latestPerItem.add(a.itemId), true))).map((a) => a.id),
  );
  const stillThere = (itemId: string) => items.some((i) => i.id === itemId);

  let summary: { severity: "success" | "info" | "warning"; text: string } | null = null;
  if (confirmed > 0 && failed + unknown + pending === 0) {
    summary = { severity: "success", text: `All ${confirmed} booking(s) are confirmed.` };
  } else if (confirmed > 0) {
    summary = {
      severity: "warning",
      text:
        `${confirmed} item(s) are confirmed and stay booked. ` +
        [
          failed > 0 ? `${failed} failed: nothing was booked for them; retry with fresh terms or choose another offer.` : "",
          unknown > 0 ? `${unknown} have an unknown outcome: we are checking with the provider (not a failure).` : "",
          pending > 0 ? `${pending} are still pending and update automatically.` : "",
        ]
          .filter(Boolean)
          .join(" "),
    };
  } else if (failed + unknown + pending > 0) {
    summary = { severity: "info", text: "No item is confirmed yet. Each item's next step is shown below." };
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Bookings — {trip.name}</Typography>
        <Button component={RouterLink} to={`/trips/${id}/itinerary`}>Itinerary</Button>
        <Button component={RouterLink} to={`/trips/${id}/budget`}>Budget</Button>
        <Button component={RouterLink} to={`/trips/${id}`}>Back to trip</Button>
      </Stack>

      {summary && <Alert severity={summary.severity}>{summary.text}</Alert>}
      {notice && <Alert severity="info" onClose={() => setNotice(null)}>{notice}</Alert>}

      {data.attempts.length === 0 ? (
        <Alert severity="info">
          No bookings yet.{canEdit ? " Use “Book” on an itinerary item." : ""}
        </Alert>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Item</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Price (USD)</TableCell>
                <TableCell>Times</TableCell>
                <TableCell>What it means</TableCell>
                {canEdit && <TableCell>Next step</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {data.attempts.map((a) => {
                const chip = CHIP[a.status];
                const latest = latestIds.has(a.id);
                return (
                  <TableRow key={a.id}>
                    <TableCell>{a.itemTitle || "(removed item)"}</TableCell>
                    <TableCell>
                      <Chip size="small" color={chip.color} label={chip.label} />
                      {a.unresolved && <Chip size="small" color="warning" variant="outlined" label="Outcome unresolved" sx={{ ml: 1 }} />}
                      {a.takingLonger && <Chip size="small" variant="outlined" label="Taking longer than expected" sx={{ ml: 1 }} />}
                    </TableCell>
                    <TableCell>
                      {a.acceptedPrice ? `${a.acceptedPrice.amount} (accepted)` : `${a.requestedPrice.amount} (requested)`}
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" sx={{ display: "block" }}>Started {stamp(a.createdAt)}</Typography>
                      <Typography variant="caption" sx={{ display: "block" }}>Updated {stamp(a.updatedAt)}</Typography>
                    </TableCell>
                    <TableCell>{explain(a)}</TableCell>
                    {canEdit && (
                      <TableCell>
                        {(a.status === "initiated" || a.status === "pending" || a.status === "unknown") && (
                          <Button size="small" disabled={checking === a.id} onClick={() => void check(a)}>
                            {checking === a.id ? "Checking…" : "Check again"}
                          </Button>
                        )}
                        {a.status === "failed" && latest && stillThere(a.itemId) && (
                          <Stack direction="row" spacing={1}>
                            <Button size="small" variant="contained" onClick={() => setRetry({ id: a.itemId, title: a.itemTitle })}>
                              Retry
                            </Button>
                            <Button size="small" component={RouterLink} to={`/trips/${id}/search`}>
                              Choose another offer
                            </Button>
                          </Stack>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Box>
      )}

      {retry && (
        <BookDialog
          tripId={id}
          item={retry}
          onClose={() => setRetry(null)}
          onBooked={() => {
            setRetry(null);
            void reload();
          }}
        />
      )}
    </Stack>
  );
}
