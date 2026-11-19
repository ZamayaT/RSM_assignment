import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useRef, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { api, ApiError, type AssistantToolCall, type ChatMessage } from "../api";

const MAX_SENT = 20; // the backend accepts at most this many messages per question

interface Turn extends ChatMessage {
  toolCalls?: AssistantToolCall[];
  incomplete?: boolean;
}

const EXAMPLES = [
  "Recommend the cheapest accommodation that fits our budget.",
  "What could we do in the evenings? Keep it under what is left of the budget.",
  "Is anything in our itinerary a problem (conflicts, expired prices)?",
];

function ToolsUsed({ calls }: { calls: AssistantToolCall[] }) {
  return (
    <Accordion disableGutters variant="outlined" sx={{ mt: 1 }}>
      <AccordionSummary>
        <Typography variant="body2">
          Tools used ({calls.length})
          {calls.some((c) => !c.ok) ? " — some failed" : ""}
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1.5}>
          {calls.map((c, n) => (
            <Box key={n}>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                <Typography variant="subtitle2" sx={{ fontFamily: "monospace" }}>{c.name}</Typography>
                <Chip size="small" color={c.ok ? "success" : "error"} label={c.ok ? "ok" : "failed"} />
                {c.prefetched && <Chip size="small" variant="outlined" label="read automatically" />}
                <Typography variant="caption" color="text.secondary">{c.durationMs} ms</Typography>
              </Stack>
              <Typography variant="body2">{c.error ?? c.summary}</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", fontFamily: "monospace", wordBreak: "break-word" }}>
                {JSON.stringify(c.arguments)}
              </Typography>
              {c.result && (
                <Box
                  component="pre"
                  sx={{ m: 0, mt: 0.5, p: 1, maxHeight: 160, overflow: "auto", fontSize: 11, bgcolor: "action.hover", borderRadius: 1, whiteSpace: "pre-wrap", wordBreak: "break-word" }}
                >
                  {c.result}
                </Box>
              )}
            </Box>
          ))}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}

export default function Assistant() {
  const { id = "" } = useParams();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; code: string } | null>(null);
  const [lost, setLost] = useState<string | null>(null); // the trip itself cannot be read
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getTrip(id).catch((e: ApiError) => setLost(e.status === 404 ? "Trip not found." : e.message));
  }, [id]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [turns, busy]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const next: Turn[] = [...turns, { role: "user", content: question }];
    setTurns(next);
    setInput("");
    setError(null);
    setBusy(true);
    try {
      const history = next.slice(-MAX_SENT).map((t) => ({ role: t.role, content: t.content }));
      const answer = await api.askAssistant(id, history);
      setTurns([...next, { role: "assistant", content: answer.reply, toolCalls: answer.toolCalls, incomplete: answer.incomplete }]);
    } catch (e) {
      const err = e as ApiError;
      setError({ text: err.message, code: err.code });
      setInput(question); // nothing was answered: the question is kept so it can be sent again
      setTurns(turns);
    } finally {
      setBusy(false);
    }
  }

  if (lost)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{lost}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        The assistant is read-only: it reads this trip and searches current offers, then recommends. It cannot change the
        itinerary or book anything; you do that in the other tabs. Offers are estimates, not bookings. Your questions and
        the trip data it reads are sent to the configured model provider, so use test data only.
      </Alert>

      {turns.length === 0 && !busy && (
        <Box>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Try a question:</Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
            {EXAMPLES.map((q) => (
              <Chip key={q} label={q} variant="outlined" onClick={() => void send(q)} />
            ))}
          </Stack>
        </Box>
      )}

      <Stack spacing={2} aria-live="polite">
        {turns.map((t, n) => (
          <Box key={n} sx={{ alignSelf: t.role === "user" ? "flex-end" : "flex-start", maxWidth: "92%" }}>
            <Typography variant="caption" color="text.secondary">{t.role === "user" ? "You" : "Assistant"}</Typography>
            <Box
              sx={{
                p: 1.5,
                borderRadius: 2,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                bgcolor: t.role === "user" ? "action.selected" : "action.hover",
              }}
            >
              {t.content}
            </Box>
            {t.incomplete && (
              <Alert severity="warning" sx={{ mt: 1 }}>The assistant ran out of steps before it could answer. Try a narrower question.</Alert>
            )}
            {t.toolCalls && t.toolCalls.length > 0 && <ToolsUsed calls={t.toolCalls} />}
            {t.role === "assistant" && t.toolCalls && t.toolCalls.every((c) => !c.name.startsWith("search")) && (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                No search was made for this answer.
              </Typography>
            )}
          </Box>
        ))}
        {busy && (
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <CircularProgress size={18} aria-label="The assistant is working" />
            <Typography variant="body2" color="text.secondary">
              Reading the trip and searching offers… this can take up to a minute.
            </Typography>
          </Stack>
        )}
        <div ref={bottom} />
      </Stack>

      {error && (
        <Alert
          severity={error.code === "ASSISTANT_NOT_CONFIGURED" ? "info" : "error"}
          onClose={() => setError(null)}
        >
          {error.text}
        </Alert>
      )}

      <Stack direction="row" spacing={1} sx={{ alignItems: "flex-end" }}>
        <TextField
          fullWidth
          multiline
          maxRows={5}
          size="small"
          label="Ask about this trip"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value.slice(0, 4000))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(input);
            }
          }}
        />
        <Button variant="contained" disabled={busy || !input.trim()} onClick={() => void send(input)}>
          {busy ? "Thinking…" : "Ask"}
        </Button>
        {turns.length > 0 && (
          <Button disabled={busy} onClick={() => { setTurns([]); setError(null); }}>
            Clear
          </Button>
        )}
      </Stack>
    </Stack>
  );
}
