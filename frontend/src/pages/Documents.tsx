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
import { api, ApiError, type DocumentStatus, type Trip, type TripDocument } from "../api";
import { isLiveDocument, stamp } from "../format";
import { useTripWorkspace } from "../tripContext";

const POLL_MS = 3000;

const CHIP: Record<DocumentStatus, { label: string; color: "default" | "info" | "success" | "error" }> = {
  waiting: { label: "Waiting", color: "default" },
  in_progress: { label: "In progress", color: "info" },
  complete: { label: "Complete", color: "success" },
  failed: { label: "Failed", color: "error" },
};

function explain(d: TripDocument): string {
  switch (d.status) {
    case "waiting":
      return "Queued. The document will start soon; you can keep using the app and this page updates by itself.";
    case "in_progress":
      return "Being generated in the background. This page updates by itself.";
    case "complete":
      return d.sizeBytes === null ? "Ready to download." : `Ready to download (${Math.max(1, Math.round(d.sizeBytes / 1024))} KB).`;
    default:
      return `${d.failureMessage ?? "The document could not be generated."} Use Retry to generate it again from the same trip data.`;
  }
}

// Says whether the newest document is current with the trip plan (the trip version it was generated from).
function freshnessOf(latest: TripDocument | undefined, tripVersion: number): { severity: "success" | "info" | "warning"; text: string } | null {
  if (!latest) return null;
  if (latest.status === "failed")
    return { severity: "warning", text: "The latest document could not be generated, so there is no up-to-date document yet. Use Retry." };
  if (latest.tripVersion < tripVersion)
    return {
      severity: "warning",
      text: `The latest document is out of date: it was generated from trip version ${latest.tripVersion} and the trip is now at version ${tripVersion}. A new document must be generated to include the latest changes.`,
    };
  if (latest.status !== "complete")
    return { severity: "info", text: `The latest document is being generated from the current trip (version ${latest.tripVersion}).` };
  return {
    severity: "success",
    text: `The latest document is up to date with the trip plan (version ${latest.tripVersion}). Booking status changes after it was generated are not reflected; generate a new one to refresh them.`,
  };
}

function saveFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function Documents() {
  const { id = "" } = useParams();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [docs, setDocs] = useState<TripDocument[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ severity: "info" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // "generate" or a document id (download / retry)
  const loading = useRef(false);
  const wasLive = useRef(false);
  const workspace = useTripWorkspace();

  const reload = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    try {
      // The trip is read again so "the trip has changed" stays accurate while this page is open.
      const [t, d] = await Promise.all([api.getTrip(id), api.documents(id)]);
      setTrip(t);
      setDocs(d);
    } catch (e) {
      setLoadError((e as ApiError).status === 404 ? "Trip not found." : (e as ApiError).message);
    } finally {
      loading.current = false;
    }
  }, [id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Keep updating while any document is waiting or in progress; this also resumes after a page reload.
  const anyLive = docs?.some(isLiveDocument) ?? false;
  useEffect(() => {
    if (!anyLive) return;
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyLive, reload]);

  // When a generation finishes, the left card shows the new latest status.
  useEffect(() => {
    if (wasLive.current && !anyLive) workspace.refresh();
    wasLive.current = anyLive;
  }, [anyLive, workspace]);

  async function generate() {
    setBusy("generate");
    setNotice(null);
    try {
      await api.requestDocument(id);
      await reload();
    } catch (e) {
      setNotice({ severity: "error", text: (e as ApiError).message });
    } finally {
      setBusy(null);
      workspace.refresh();
    }
  }

  async function retry(d: TripDocument) {
    setBusy(d.id);
    setNotice(null);
    try {
      await api.retryDocument(id, d.id);
    } catch (e) {
      setNotice({ severity: "error", text: (e as ApiError).message });
    } finally {
      await reload();
      setBusy(null);
      workspace.refresh();
    }
  }

  async function download(d: TripDocument) {
    setBusy(d.id);
    setNotice(null);
    try {
      const file = await api.downloadDocument(id, d.id);
      saveFile(file.blob, file.filename);
    } catch (e) {
      const err = e as ApiError;
      setNotice({
        severity: err.code === "DOCUMENT_UNAVAILABLE" ? "error" : "info",
        text: err.code === "DOCUMENT_UNAVAILABLE" ? `This document cannot be downloaded: ${err.message}` : err.message,
      });
      await reload();
      workspace.refresh();
    } finally {
      setBusy(null);
    }
  }

  if (loadError)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (!trip || !docs) return <CircularProgress aria-label="Loading documents" />;

  const canEdit = trip.role === "organizer" || trip.role === "editor";
  const freshness = freshnessOf(docs[0], trip.version);

  return (
    <Stack spacing={2}>
      {freshness && <Alert severity={freshness.severity}>{freshness.text}</Alert>}
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 220 }}>
          A document is a PDF summary of the itinerary, costs and booking statuses as they are when you generate it. Later
          changes do not alter it.
        </Typography>
        {canEdit && (
          <Button variant="contained" disabled={busy === "generate" || anyLive} onClick={() => void generate()}>
            {busy === "generate" ? "Requesting…" : "Generate document"}
          </Button>
        )}
      </Box>
      {canEdit && anyLive && (
        <Typography variant="caption" color="text.secondary">
          A document is being generated. You can request another one when it finishes.
        </Typography>
      )}
      {notice && <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.text}</Alert>}

      {docs.length === 0 ? (
        <Alert severity="info">No documents yet.{canEdit ? " Use “Generate document” to create the first one." : ""}</Alert>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Requested by</TableCell>
                <TableCell>Requested at</TableCell>
                <TableCell>Trip version</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>What it means</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {docs.map((d) => {
                const chip = CHIP[d.status];
                const outdated = trip.version > d.tripVersion;
                return (
                  <TableRow key={d.id}>
                    <TableCell>{d.requestedBy?.displayName ?? "(unknown user)"}</TableCell>
                    <TableCell>{stamp(d.snapshotAt)}</TableCell>
                    <TableCell>
                      {d.tripVersion}
                      {outdated && (
                        <Typography variant="caption" color="warning.main" sx={{ display: "block" }}>
                          The trip has changed since this document
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip size="small" color={chip.color} label={chip.label} />
                    </TableCell>
                    <TableCell>{explain(d)}</TableCell>
                    <TableCell>
                      {d.status === "complete" && (
                        <Button size="small" variant="outlined" disabled={busy === d.id} onClick={() => void download(d)}>
                          {busy === d.id ? "Downloading…" : "Download"}
                        </Button>
                      )}
                      {d.status === "failed" && canEdit && (
                        <Button size="small" variant="contained" disabled={busy === d.id || anyLive} onClick={() => void retry(d)}>
                          {busy === d.id ? "Retrying…" : "Retry"}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Box>
      )}
    </Stack>
  );
}
