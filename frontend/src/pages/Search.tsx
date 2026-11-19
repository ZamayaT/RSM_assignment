import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type Itinerary,
  type Offer,
  type SearchInput,
  type SearchOptions,
  type SearchResult,
  type Trip,
} from "../api";
import ConflictDialog, { type PendingChange } from "../ConflictDialog";import { stamp } from "../format";
import { useTripWorkspace } from "../tripContext";

type SortKey = "price" | "start" | "supplier";

function sortOffers(offers: Offer[], key: SortKey): Offer[] {
  const by: Record<SortKey, (a: Offer, b: Offer) => number> = {
    price: (a, b) => Number(a.price.amount) - Number(b.price.amount),
    start: (a, b) => new Date(a.startsAt).getTime() - new Date(b.startsAt).getTime(),
    supplier: (a, b) => a.providerId.localeCompare(b.providerId),
  };
  return [...offers].sort(by[key]);
}

export default function Search() {
  const { id = "" } = useParams();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [options, setOptions] = useState<SearchOptions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [category, setCategory] = useState("accommodation");
  const [destination, setDestination] = useState("");
  const [origin, setOrigin] = useState("");
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [travelers, setTravelers] = useState("1");
  const [providerId, setProviderId] = useState("");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [sortKey, setSortKey] = useState<SortKey>("price");
  const [itineraryVersion, setItineraryVersion] = useState(1);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [adding, setAdding] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ change: PendingChange; latest: Itinerary; offerId: string } | null>(null);
  const [reapplying, setReapplying] = useState(false);
  const lastInput = useRef<SearchInput | null>(null);
  const latestRun = useRef(0);
  const workspace = useTripWorkspace();

  useEffect(() => {
    Promise.all([api.getTrip(id), api.searchOptions(), api.itinerary(id)])
      .then(([t, o, it]) => {
        setTrip(t);
        setOptions(o);
        syncItinerary(it);
        setDestination(t.destinations[0] ?? "");
        setStartsOn(t.startDate);
        setEndsOn(t.endDate);
        setTravelers(String(t.travelers));
      })
      .catch((e: ApiError) => setLoadError(e.status === 404 ? "Trip not found." : e.message));
  }, [id]);

  function syncItinerary(it: Itinerary) {
    setItineraryVersion(it.version);
    setAdded(new Set(it.items.map((i) => i.offerId)));
  }

  // Sends one add. Only the server's answer decides what the page says; nothing is assumed saved.
  async function addOffer(offer: Offer, version: number, fromDialog = false) {
    const change: PendingChange = {
      description: `Add “${offer.title}” (${offer.providerId}) to the itinerary.`,
      apply: (v) => api.addToItinerary(id, offer.id, v),
    };
    setAdding(offer.id);
    setNotes((n) => ({ ...n, [offer.id]: { ok: true, text: "" } }));
    try {
      const updated = await change.apply(version);
      syncItinerary(updated);
      setConflict(null);
      setNotes((n) => ({ ...n, [offer.id]: { ok: true, text: "Added to the itinerary." } }));
      workspace.refresh();
    } catch (e) {
      const error = e as ApiError;
      if (error.status === 409 && error.latestState) {
        syncItinerary(error.latestState.itinerary);
        setConflict({ change, latest: error.latestState.itinerary, offerId: offer.id });
        return;
      }
      if (error.code === "ALREADY_IN_ITINERARY") setAdded((a) => new Set(a).add(offer.id));
      setConflict(null);
      setNotes((n) => ({ ...n, [offer.id]: { ok: false, text: error.fields.offerId ?? error.message } }));
      if (fromDialog) api.itinerary(id).then(syncItinerary).catch(() => undefined);
    } finally {
      setAdding(null);
      setReapplying(false);
    }
  }

  async function run(input: SearchInput) {
    const thisRun = ++latestRun.current;
    lastInput.current = input;
    setLoading(true);
    setResult(null);
    setFailure(null);
    setFieldErrors({});
    try {
      const found = await api.search(id, input);
      if (thisRun === latestRun.current) setResult(found);
    } catch (e) {
      if (thisRun !== latestRun.current) return;
      const error = e as ApiError;
      if (error.status === 400) setFieldErrors(error.fields);
      else setFailure(error.message);
    } finally {
      if (thisRun === latestRun.current) setLoading(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    run({
      category,
      destination,
      origin: category === "transport" ? origin || undefined : undefined,
      startsOn: startsOn || undefined,
      endsOn: endsOn || undefined,
      travelers: travelers ? Number(travelers) : undefined,
      providerId: providerId || undefined,
    });
  }

  if (loadError)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (!trip || !options) return <CircularProgress aria-label="Loading search" />;

  const err = (field: string) => ({ error: field in fieldErrors, helperText: fieldErrors[field] });
  const sorted = result ? sortOffers(result.offers, sortKey) : [];
  const canEdit = trip.role === "organizer" || trip.role === "editor";

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Results are estimates from suppliers. They are not bookings and prices are not guaranteed.
      </Alert>

      <Box component="form" onSubmit={submit} noValidate>
        <Stack spacing={2}>
          {/* Fields fill the card's width: as many columns as fit, at least 200px each. */}
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
            <TextField select label="Category" value={category} onChange={(e) => setCategory(e.target.value)} fullWidth {...err("category")}>
              {options.categories.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
            </TextField>
            <TextField select label="Destination" value={destination} onChange={(e) => setDestination(e.target.value)} fullWidth {...err("destination")}>
              {trip.destinations.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
            </TextField>
            {category === "transport" && (
              <TextField select label="Origin" value={origin} onChange={(e) => setOrigin(e.target.value)} required fullWidth {...err("origin")}>
                {options.origins.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
              </TextField>
            )}
            <TextField select label="Supplier" value={providerId} onChange={(e) => setProviderId(e.target.value)} fullWidth {...err("providerId")}>
              <MenuItem value="">Any supplier</MenuItem>
              {options.suppliers.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
            </TextField>
            <TextField label="From" type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} fullWidth {...err("startsOn")} />
            <TextField label="To" type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} fullWidth {...err("endsOn")} />
            <TextField label="Travelers" type="number" value={travelers} onChange={(e) => setTravelers(e.target.value)} fullWidth {...err("travelers")} />
          </Box>
          <Stack direction="row" spacing={2}>
            <Button type="submit" variant="contained" disabled={loading}>{loading ? "Searching…" : "Search"}</Button>
            <Button variant="outlined" component={RouterLink} to={`/trips/${trip.id}/itinerary`}>View itinerary</Button>
          </Stack>
        </Stack>
      </Box>

      {loading && <CircularProgress aria-label="Searching" />}

      {failure && (
        <Alert
          severity="error"
          action={<Button color="inherit" size="small" onClick={() => lastInput.current && run(lastInput.current)}>Try again</Button>}
        >
          The search failed: {failure}
        </Alert>
      )}

      {result && (
        <Stack spacing={2}>
          {result.warnings.map((w) => (
            <Alert key={w.providerId} severity="warning">
              Partial results — {w.message}
            </Alert>
          ))}
          {result.offers.length === 0 ? (
            <Alert severity="info">
              {result.state === "partial" ? "No offers from the suppliers that answered." : "No offers match this search."}
            </Alert>
          ) : (
            <>
              <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
                <Typography color="text.secondary" sx={{ flexGrow: 1 }}>
                  {result.offers.length} offer(s) · searched at {stamp(result.searchedAt)}
                </Typography>
                <TextField select size="small" label="Sort by" value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)} sx={{ minWidth: 160 }}>
                  <MenuItem value="price">Price</MenuItem>
                  <MenuItem value="start">Start time</MenuItem>
                  <MenuItem value="supplier">Supplier</MenuItem>
                </TextField>
              </Stack>
              <Box sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Offer</TableCell>
                      <TableCell>Supplier</TableCell>
                      <TableCell>Schedule</TableCell>
                      <TableCell align="right">Price (USD)</TableCell>
                      <TableCell>Availability</TableCell>
                      <TableCell>Quote valid until</TableCell>
                      {canEdit && <TableCell>Itinerary</TableCell>}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {sorted.map((o) => (
                      <TableRow key={o.id} sx={o.available ? undefined : { opacity: 0.6 }}>
                        <TableCell>
                          <Typography variant="body2">{o.title}</Typography>
                          <Typography variant="caption" color="text.secondary">{o.description}</Typography>
                        </TableCell>
                        <TableCell>{o.providerId}</TableCell>
                        <TableCell>{stamp(o.startsAt)} → {stamp(o.endsAt)}</TableCell>
                        <TableCell align="right">≈ {o.price.amount}</TableCell>
                        <TableCell>
                          {o.available ? <Chip size="small" color="success" label="Available" /> : <Chip size="small" label="Unavailable" />}
                        </TableCell>
                        <TableCell>{stamp(o.validUntil)}</TableCell>
                        {canEdit && (
                          <TableCell>
                            {added.has(o.id) ? (
                              <Chip size="small" variant="outlined" label="In itinerary" />
                            ) : (
                              <Button
                                size="small"
                                variant="outlined"
                                disabled={adding !== null || !o.available}
                                onClick={() => addOffer(o, itineraryVersion)}
                              >
                                {adding === o.id ? "Adding…" : "Add to itinerary"}
                              </Button>
                            )}
                            {notes[o.id]?.text && (
                              <Typography variant="caption" color={notes[o.id].ok ? "success.main" : "error"} sx={{ display: "block" }}>
                                {notes[o.id].text}
                              </Typography>
                            )}
                          </TableCell>
                        )}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            </>
          )}
        </Stack>
      )}
      {conflict && (
        <ConflictDialog
          change={conflict.change}
          latest={conflict.latest}
          busy={reapplying}
          onDiscard={() => setConflict(null)}
          onReapply={() => {
            const offer = result?.offers.find((o) => o.id === conflict.offerId);
            if (!offer) return setConflict(null);
            setReapplying(true);
            void addOffer(offer, conflict.latest.version, true);
          }}
        />
      )}
    </Stack>
  );
}
