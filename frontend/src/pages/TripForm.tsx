import { Alert, Autocomplete, Button, CircularProgress, Paper, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState, type FormEvent } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type Trip } from "../api";
interface FormValues {
  name: string;
  destinations: string[];
  startDate: string;
  endDate: string;
  travelers: string;
  budget: string;
  notes: string;
}

const EMPTY: FormValues = { name: "", destinations: [], startDate: "", endDate: "", travelers: "1", budget: "", notes: "" };

function fromTrip(trip: Trip): FormValues {
  return {
    name: trip.name,
    destinations: trip.destinations,
    startDate: trip.startDate,
    endDate: trip.endDate,
    travelers: String(trip.travelers),
    budget: trip.budget,
    notes: trip.notes ?? "",
  };
}

export default function TripForm() {
  const { id } = useParams();
  const editing = id !== undefined;
  const navigate = useNavigate();

  const [values, setValues] = useState<FormValues>(EMPTY);
  const [version, setVersion] = useState(0);
  const [destinations, setDestinations] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Trip | null>(null);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    const tripLoad = editing ? api.getTrip(id) : Promise.resolve(null);
    Promise.all([api.destinations(), tripLoad])
      .then(([list, trip]) => {
        setDestinations(list);
        if (trip) {
          setValues(fromTrip(trip));
          setVersion(trip.version);
        }
      })
      .catch((e: ApiError) => setLoadError(e.status === 404 ? "Trip not found." : e.message))
      .finally(() => setLoading(false));
  }, [editing, id]);

  function set<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
    setFieldErrors((current) => {
      const { [key]: _removed, ...rest } = current;
      return rest;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    setFieldErrors({});
    setConflict(null);
    const input = {
      name: values.name,
      destinations: values.destinations,
      startDate: values.startDate,
      endDate: values.endDate,
      travelers: Number(values.travelers),
      budget: values.budget.trim(),
      notes: values.notes || null,
    };
    try {
      // Success is only reported after the server confirmed the save.
      const saved = editing ? await api.updateTrip(id, input, version) : await api.createTrip(input);
      navigate(`/trips/${saved.id}/itinerary`, { state: { saved: true } });
    } catch (e) {
      const error = e as ApiError;
      if (error.status === 400) {
        setFieldErrors(error.fields);
        setFormError("Please fix the highlighted fields. Nothing was saved.");
      } else if (error.status === 409 && error.latest) {
        setConflict(error.latest);
      } else {
        setFormError(error.message);
      }
    } finally {
      setSaving(false);
    }
  }

  function reloadLatest() {
    if (!conflict) return;
    setValues(fromTrip(conflict));
    setVersion(conflict.version);
    setConflict(null);
  }

  const card = { borderRadius: "24px", p: { xs: 3, md: 5 }, maxWidth: 680, mx: "auto" };

  if (loading) return <CircularProgress color="inherit" aria-label="Loading form" />;
  if (loadError)
    return (
      <Paper sx={card}>
        <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>
        <Button variant="contained" component={RouterLink} to="/trips">Back to My trips</Button>
      </Paper>
    );

  const err = (field: string) => ({ error: field in fieldErrors, helperText: fieldErrors[field] });

  return (
    <Paper component="form" onSubmit={submit} noValidate sx={card}>
      <Typography variant="h4" component="h1" sx={{ mb: 3 }}>
        {editing ? "Edit Trip" : "New Trip"}
      </Typography>
      <Stack spacing={2}>
        {conflict && (
          <Alert severity="warning" action={<Button color="inherit" size="small" onClick={reloadLatest}>Reload latest</Button>}>
            This trip was changed by someone else. Your changes were not saved.
          </Alert>
        )}
        {formError && <Alert severity="error">{formError}</Alert>}
        <TextField label="Name" value={values.name} onChange={(e) => set("name", e.target.value)} required {...err("name")} />
        <Autocomplete
          multiple
          options={destinations}
          value={values.destinations}
          onChange={(_, value) => set("destinations", value)}
          renderInput={(params) => <TextField {...params} label="Destinations" required {...err("destinations")} />}
        />
        <Stack direction="row" spacing={2}>
          <TextField
            label="Start date"
            type="date"
            value={values.startDate}
            onChange={(e) => set("startDate", e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
            required
            fullWidth
            {...err("startDate")}
          />
          <TextField
            label="End date"
            type="date"
            value={values.endDate}
            onChange={(e) => set("endDate", e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
            required
            fullWidth
            {...err("endDate")}
          />
        </Stack>
        <Stack direction="row" spacing={2}>
          <TextField
            label="Travelers"
            type="number"
            value={values.travelers}
            onChange={(e) => set("travelers", e.target.value)}
            required
            fullWidth
            {...err("travelers")}
          />
          <TextField
            label="Budget (USD)"
            value={values.budget}
            onChange={(e) => set("budget", e.target.value)}
            placeholder="1500.00"
            required
            fullWidth
            {...err("budget")}
          />
        </Stack>
        <TextField
          label="Preferences / notes"
          value={values.notes}
          onChange={(e) => set("notes", e.target.value)}
          multiline
          minRows={3}
          {...err("notes")}
        />
        <Stack direction="row" spacing={2}>
          <Button type="submit" variant="contained" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button variant="outlined" component={RouterLink} to={editing ? `/trips/${id}` : "/trips"} disabled={saving}>
            Cancel
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}
