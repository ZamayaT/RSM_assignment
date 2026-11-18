import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { api, ApiError, type Participant, type Trip } from "../api";

const ASSIGNABLE = ["editor", "viewer"];

export default function Participants() {
  const { id = "" } = useParams();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [participants, setParticipants] = useState<Participant[] | null>(null);
  const [lostAccess, setLostAccess] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ severity: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const [username, setUsername] = useState("");
  const [newRole, setNewRole] = useState("viewer");
  const [usernameError, setUsernameError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      const [t, list] = await Promise.all([api.getTrip(id), api.listParticipants(id)]);
      setTrip(t);
      setParticipants(list);
      setLoadError(null);
      setLostAccess(false);
    } catch (e) {
      const error = e as ApiError;
      if (error.status === 404) setLostAccess(true);
      else setLoadError(error.message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // Username search while typing (small delay so the API is not called on every key press).
  useEffect(() => {
    const query = username.trim();
    if (!query) {
      setSuggestions([]);
      return;
    }
    const timer = setTimeout(() => {
      api
        .searchUsers(query)
        .then((users) => setSuggestions(users.map((u) => u.username)))
        .catch(() => setSuggestions([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [username]);

  const isOrganizer = trip?.role === "organizer";

  // Runs a change; the list is only updated from the server's answer (a reload), never optimistically.
  async function act(action: () => Promise<unknown>, success: string): Promise<boolean> {
    setBusy(true);
    setNotice(null);
    try {
      await action();
      await load();
      setNotice({ severity: "success", text: success });
      return true;
    } catch (e) {
      const error = e as ApiError;
      if (error.status === 404) {
        // Access to the trip was lost, or the participant is already gone: the reload shows the true state.
        await load();
        setNotice({ severity: "error", text: "That participant or trip is no longer available. The list was refreshed." });
      } else if (error.status === 403) {
        await load();
        setNotice({ severity: "error", text: "You are no longer allowed to do this. Your role may have changed." });
      } else if (error.status === 400 && error.fields.username) {
        setUsernameError(error.fields.username);
      } else {
        setNotice({ severity: "error", text: error.message });
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    setUsernameError(null);
    const ok = await act(() => api.addParticipant(id, username, newRole), `Added ${username.trim()}.`);
    if (ok) {
      setUsername("");
      setSuggestions([]);
    }
  }

  if (lostAccess)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>
          This trip is not available to you (it may have been removed from your trips).
        </Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (loadError)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (!trip || !participants) return <CircularProgress aria-label="Loading participants" />;

  const existing = new Set(participants.map((p) => p.username));

  return (
    <Stack spacing={2} sx={{ maxWidth: 640 }}>
      <Typography variant="h5">Participants – {trip.name}</Typography>
      {!isOrganizer && <Alert severity="info">Only the organizer can add, change or remove participants.</Alert>}
      {notice && <Alert severity={notice.severity}>{notice.text}</Alert>}

      {isOrganizer && (
        <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
          <Autocomplete
            freeSolo
            fullWidth
            options={suggestions.filter((name) => !existing.has(name))}
            inputValue={username}
            onInputChange={(_, value) => {
              setUsername(value);
              setUsernameError(null);
            }}
            renderInput={(params) => (
              <TextField {...params} label="Username" error={usernameError !== null} helperText={usernameError} />
            )}
          />
          <Select value={newRole} onChange={(e) => setNewRole(e.target.value)} aria-label="Role for new participant">
            {ASSIGNABLE.map((r) => (
              <MenuItem key={r} value={r}>{r}</MenuItem>
            ))}
          </Select>
          <Button variant="contained" onClick={add} disabled={busy || !username.trim()} sx={{ height: 56 }}>
            Add
          </Button>
        </Stack>
      )}

      <Stack divider={<Box sx={{ borderBottom: 1, borderColor: "divider" }} />}>
        {participants.map((p) => (
          <Stack key={p.userId} direction="row" spacing={2} sx={{ alignItems: "center", py: 1 }}>
            <Box sx={{ flexGrow: 1 }}>
              <Typography>{p.displayName}</Typography>
              <Typography variant="body2" color="text.secondary">{p.username}</Typography>
            </Box>
            {isOrganizer && p.role !== "organizer" ? (
              <>
                <Select
                  size="small"
                  value={p.role}
                  disabled={busy}
                  onChange={(e) =>
                    act(() => api.changeRole(id, p.userId, e.target.value), `${p.username} is now ${e.target.value}.`)
                  }
                  aria-label={`Role of ${p.username}`}
                >
                  {ASSIGNABLE.map((r) => (
                    <MenuItem key={r} value={r}>{r}</MenuItem>
                  ))}
                </Select>
                <Button
                  color="error"
                  disabled={busy}
                  onClick={() => act(() => api.removeParticipant(id, p.userId), `Removed ${p.username}.`)}
                >
                  Remove
                </Button>
              </>
            ) : (
              <Chip label={p.role} />
            )}
          </Stack>
        ))}
      </Stack>
      <Box>
        <Button component={RouterLink} to={`/trips/${id}`}>Back to trip</Button>
      </Box>
    </Stack>
  );
}
