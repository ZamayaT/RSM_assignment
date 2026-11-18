import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type BookingAttempt, type Quote } from "./api";
import { newIntentId, stamp } from "./format";

interface Props {
  tripId: string;
  item: { id: string; title: string };
  onClose: () => void;
  onBooked: (attempt: BookingAttempt) => void;
}

// Shows the provider's current terms next to the saved estimate. Only "Confirm booking" books, and it sends the
// revision and price shown here. One intent id per opening, so a repeated click or retry never books twice.
export default function BookDialog({ tripId, item, onClose, onBooked }: Props) {
  const intentId = useRef(newIntentId());
  const [quote, setQuote] = useState<Quote | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.quote(tripId, item.id).then(setQuote).catch((e: ApiError) => setLoadError(e.message));
  }, [tripId, item.id]);

  async function confirm() {
    if (!quote || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const attempt = await api.book(tripId, {
        itemId: item.id,
        intentId: intentId.current,
        expectedRevision: quote.current.revision,
        expectedPrice: quote.current.price,
      });
      onBooked(attempt);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 0) {
        setError("We could not confirm whether the booking was sent. Pressing Confirm again is safe: it will not book twice.");
      } else if (err.code === "BOOKING_EXISTS") {
        setError("This item already has a booking in progress or confirmed. See the Bookings view.");
      } else {
        setError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const changed = (key: Quote["changes"][number]) => quote?.changes.includes(key) ?? false;
  const mark = (on: boolean) => (on ? { backgroundColor: "warning.light", fontWeight: 600 } : {});

  return (
    <Dialog open maxWidth="sm" fullWidth aria-labelledby="book-title" onClose={submitting ? undefined : onClose}>
      <DialogTitle id="book-title">Book “{item.title}”</DialogTitle>
      <DialogContent>
        {loadError && <Alert severity="error">{loadError}</Alert>}
        {!quote && !loadError && <CircularProgress aria-label="Checking current terms" />}
        {quote && (
          <>
            <Typography sx={{ mb: 1 }}>
              These are the provider's terms right now. Nothing is booked until you confirm them.
            </Typography>
            {quote.changes.some((c) => c !== "expired") && (
              <Alert severity="warning" sx={{ mb: 1 }}>
                The offer changed since it was saved. Review the highlighted terms before confirming.
              </Alert>
            )}
            {quote.reason && <Alert severity="error" sx={{ mb: 1 }}>{quote.reason}</Alert>}
            <Typography variant="body2" sx={{ mb: 1 }}>
              <strong>Conditions:</strong> {quote.description} Simulated booking: no payment, cancellation or refund.
            </Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell />
                  <TableCell>Saved estimate</TableCell>
                  <TableCell>Current terms (what you book)</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                <TableRow>
                  <TableCell>Price</TableCell>
                  <TableCell>{quote.saved.price.amount} {quote.saved.price.currency}</TableCell>
                  <TableCell sx={mark(changed("price"))}>{quote.current.price.amount} {quote.current.price.currency}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Availability</TableCell>
                  <TableCell>{quote.saved.available ? "Available" : "Sold out"}</TableCell>
                  <TableCell sx={mark(changed("availability"))}>{quote.current.available ? "Available" : "Sold out"}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Quote revision</TableCell>
                  <TableCell>{quote.saved.revision}</TableCell>
                  <TableCell sx={mark(changed("revision"))}>{quote.current.revision}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Quote valid until</TableCell>
                  <TableCell>{stamp(quote.saved.validUntil)}</TableCell>
                  <TableCell sx={mark(changed("expired"))}>{stamp(quote.current.validUntil)}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </>
        )}
        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>Cancel</Button>
        <Button variant="contained" onClick={() => void confirm()} disabled={!quote || !quote.bookable || submitting}>
          {submitting ? "Booking…" : "Confirm booking"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
