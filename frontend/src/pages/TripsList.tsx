import { Alert, Box, Button, Chip, CircularProgress, List, ListItem, ListItemButton, ListItemText, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, ApiError, type Trip } from "../api";

export default function TripsList() {
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listTrips().then(setTrips).catch((e: ApiError) => setError(e.message));
  }, []);

  return (
    <Box>
      <Stack direction="row" sx={{ mb: 2, alignItems: "center", justifyContent: "space-between" }}>
        <Typography variant="h5">My trips</Typography>
        <Button variant="contained" component={RouterLink} to="/trips/new">
          Create trip
        </Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {!trips && !error && <CircularProgress aria-label="Loading trips" />}
      {trips && trips.length === 0 && (
        <Alert severity="info">You have no trips yet. Create your first trip to get started.</Alert>
      )}
      {trips && trips.length > 0 && (
        <List>
          {trips.map((trip) => (
            <ListItem key={trip.id} disablePadding divider>
              <ListItemButton component={RouterLink} to={`/trips/${trip.id}`}>
                <ListItemText
                  primary={trip.name}
                  secondary={`${trip.startDate} – ${trip.endDate} · ${trip.destinations.join(", ")}`}
                />
                <Chip label={trip.role} size="small" />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
}
