import { Alert, Box, Button, ButtonBase, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, ApiError, type Trip } from "../api";
import RoleChip from "../RoleChip";

export default function TripsList() {
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listTrips().then(setTrips).catch((e: ApiError) => setError(e.message));
  }, []);

  return (
    <Paper sx={{ borderRadius: "24px", p: { xs: 2.5, md: 5 }, maxWidth: 1200, mx: "auto", minHeight: { md: "100%" } }}>
      <Stack direction="row" sx={{ mb: 3, alignItems: "center", justifyContent: "space-between", gap: 2 }}>
        <Typography variant="h4" component="h1">My Trips</Typography>
        <Button variant="contained" size="large" component={RouterLink} to="/trips/new" sx={{ fontSize: "1.1rem", px: 3 }}>
          + New Trip
        </Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {!trips && !error && <CircularProgress color="inherit" aria-label="Loading trips" />}
      {trips && trips.length === 0 && (
        <Alert severity="info">You have no trips yet. Create your first trip to get started.</Alert>
      )}
      {trips && trips.length > 0 && (
        <Stack component="ul" spacing={2.5} sx={{ listStyle: "none", m: 0, p: 0 }}>
          {trips.map((trip) => (
            <Box component="li" key={trip.id}>
              <ButtonBase
                component={RouterLink}
                to={`/trips/${trip.id}`}
                sx={{
                  width: "100%",
                  display: "flex",
                  flexWrap: "wrap",
                  justifyContent: "space-between",
                  alignItems: "flex-end",
                  gap: 1,
                  textAlign: "left",
                  bgcolor: "secondary.main",
                  borderRadius: "24px",
                  px: { xs: 2.5, md: 4 },
                  py: 2,
                  "&:hover": { bgcolor: "rgba(66, 126, 166, 0.8)" },
                }}
              >
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="h5" component="h2">{trip.name}</Typography>
                  <Typography color="text.secondary">{trip.startDate} – {trip.endDate}</Typography>
                </Box>
                <Stack spacing={1} sx={{ alignItems: { xs: "flex-start", sm: "flex-end" } }}>
                  <RoleChip role={trip.role} />
                  <Typography color="text.secondary">{trip.destinations.join(", ")}</Typography>
                </Stack>
              </ButtonBase>
            </Box>
          ))}
        </Stack>
      )}
    </Paper>
  );
}
