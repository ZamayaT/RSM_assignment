import { Alert, Box, Button, CircularProgress, Paper, Tab, Tabs, Typography, useMediaQuery, type Theme } from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink, Outlet, useLocation, useParams } from "react-router-dom";
import { api, ApiError, type Bookings, type Budget, type Itinerary, type Trip, type TripDocument } from "../api";
import { isLiveAttempt, isLiveDocument, stamp } from "../format";
import RoleChip from "../RoleChip";
import { TripWorkspaceContext } from "../tripContext";

const SECTIONS = [
  { path: "itinerary", label: "Itinerary" },
  { path: "budget", label: "Budget" },
  { path: "bookings", label: "Bookings" },
  { path: "documents", label: "Documents" },
  { path: "search", label: "Search" },
  { path: "participants", label: "Participants" },
  { path: "assistant", label: "Assistant" },
];

const SUMMARY_POLL_MS = 5000;

const DOCUMENT_STATUS_TEXT: Record<string, string> = {
  waiting: "waiting",
  in_progress: "in progress",
  complete: "complete",
  failed: "failed",
};

function Info({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: 1, fontWeight: 600 }}>
        {label}
      </Typography>
      <Typography sx={{ whiteSpace: "pre-wrap" }}>{value}</Typography>
    </Box>
  );
}

// Trip workspace: general info on the left, the selected section (a tab bound to the URL) on the right.
// On wide screens only the section card scrolls.
export default function TripWorkspace() {
  const { id = "" } = useParams();
  const location = useLocation();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The summary is optional: if a part cannot be loaded the rest of the workspace still works.
  const [budget, setBudget] = useState<Budget | null>(null);
  const [itinerary, setItinerary] = useState<Itinerary | null>(null);
  const [bookings, setBookings] = useState<Bookings | null>(null);
  const [documents, setDocuments] = useState<TripDocument[] | null>(null);
  const [saved, setSaved] = useState(false);
  const wide = useMediaQuery((t: Theme) => t.breakpoints.up("sm"));

  const refresh = useCallback(() => {
    api
      .getTrip(id)
      .then(setTrip)
      .catch((e: ApiError) =>
        setError(e.status === 404 ? "Trip not found. It does not exist or you are not a participant of it." : e.message),
      );
    api.budget(id).then(setBudget).catch(() => undefined);
    api.itinerary(id).then(setItinerary).catch(() => undefined);
    api.bookings(id).then(setBookings).catch(() => undefined);
    api.documents(id).then(setDocuments).catch(() => undefined);
  }, [id]);

  useEffect(() => {
    setTrip(null);
    setError(null);
    setBudget(null);
    setItinerary(null);
    setBookings(null);
    setDocuments(null);
    refresh();
  }, [refresh]);

  // "Trip saved." after the edit form; it can be dismissed.
  useEffect(() => {
    if ((location.state as { saved?: boolean } | null)?.saved) setSaved(true);
  }, [location.state]);

  // Booking outcomes can change on their own (worker); keep the counters and totals current meanwhile.
  const anyLive = (bookings?.attempts.some(isLiveAttempt) ?? false) || (documents?.some(isLiveDocument) ?? false);
  useEffect(() => {
    if (!anyLive) return;
    const timer = setInterval(refresh, SUMMARY_POLL_MS);
    return () => clearInterval(timer);
  }, [anyLive, refresh]);

  const context = useMemo(() => ({ refresh }), [refresh]);
  const section = SECTIONS.find((s) => location.pathname.endsWith(`/${s.path}`))?.path ?? false;

  if (error)
    return (
      <Paper sx={{ borderRadius: "24px", p: 4, maxWidth: 640, mx: "auto" }}>
        <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
        <Button variant="contained" component={RouterLink} to="/trips">Back to My trips</Button>
      </Paper>
    );
  if (!trip) return <CircularProgress color="inherit" aria-label="Loading trip" />;

  const canEdit = trip.role === "organizer" || trip.role === "editor";

  return (
    <TripWorkspaceContext.Provider value={context}>
      <Box sx={{ display: "flex", flexDirection: { xs: "column", md: "row" }, gap: 3, height: { md: "100%" } }}>
        <Paper
          component="aside"
          aria-label="Trip information"
          sx={{
            borderRadius: "24px",
            p: { xs: 3, md: 4 },
            // About 25% / 75% with the section card; never narrower than 300px.
            width: { md: "25%" },
            minWidth: { md: 300 },
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            gap: 2,
            overflow: { md: "auto" },
          }}
        >
          <Box sx={{ textAlign: "center" }}>
            <Typography variant="h4" component="h1" sx={{ wordBreak: "break-word" }}>{trip.name}</Typography>
            <Typography sx={{ fontSize: "1.2rem", mt: 1 }}>{trip.startDate} – {trip.endDate}</Typography>
            <Box sx={{ mt: 1.5 }}><RoleChip role={trip.role} /></Box>
          </Box>
          {saved && <Alert severity="success" onClose={() => setSaved(false)}>Trip saved.</Alert>}
          <Info label="Destinations" value={trip.destinations.join(", ")} />
          <Info label="Travelers" value={String(trip.travelers)} />
          <Info label="Budget (USD)" value={trip.budget} />
          {budget && (
            <Info
              label="Current total (USD)"
              value={`${budget.combinedTotal} (${budget.estimatedTotal} estimated + ${budget.confirmedTotal} confirmed)\n${
                budget.overBudget ? `Over budget by ${budget.remaining.replace("-", "")}` : `${budget.remaining} remaining`
              }`}
            />
          )}
          {itinerary && (
            <Info
              label="Itinerary"
              value={`${itinerary.items.length} item(s), ${itinerary.items.reduce((n, i) => n + i.warnings.length, 0)} warning(s)`}
            />
          )}
          {bookings && (
            <Info
              label="Bookings"
              value={`${bookings.counts.confirmed} confirmed, ${bookings.counts.pending} pending, ${bookings.counts.unknown} unknown, ${bookings.counts.failed} failed`}
            />
          )}
          {documents && (
            <Info
              label="Documents"
              value={
                documents.length === 0
                  ? "None generated yet"
                  : `Latest: ${DOCUMENT_STATUS_TEXT[documents[0].status]}
Trip version ${documents[0].tripVersion}, ${stamp(documents[0].createdAt)}`
              }
            />
          )}
          {trip.notes && <Info label="Notes" value={trip.notes} />}
          {canEdit && (
            <Box sx={{ mt: "auto", pt: 2, textAlign: "center" }}>
              <Button variant="contained" size="large" component={RouterLink} to={`/trips/${trip.id}/edit`} sx={{ fontSize: "1.1rem", px: 5 }}>
                Edit Trip
              </Button>
            </Box>
          )}
        </Paper>

        <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", gap: 2 }}>
          <Paper sx={{ borderRadius: 999, p: 0.75, flexShrink: 0 }}>
            {/* Tabs share the bar equally; on narrow screens they scroll instead of shrinking. */}
            <Tabs
              value={section}
              variant={wide ? "fullWidth" : "scrollable"}
              scrollButtons="auto"
              allowScrollButtonsMobile
              aria-label="Trip sections"
              sx={{ minHeight: 40, "& .MuiTabs-flexContainer": { gap: 1 } }}
            >
              {SECTIONS.map((s) => (
                <Tab key={s.path} value={s.path} label={s.label} component={RouterLink} to={`/trips/${trip.id}/${s.path}`} />
              ))}
            </Tabs>
          </Paper>
          <Paper
            component="section"
            aria-label={SECTIONS.find((s) => s.path === section)?.label}
            sx={{ borderRadius: "24px", p: { xs: 2, md: 3 }, flex: 1, minHeight: 0, overflow: { md: "auto" } }}
          >
            <Outlet />
          </Paper>
        </Box>
      </Box>
    </TripWorkspaceContext.Provider>
  );
}
