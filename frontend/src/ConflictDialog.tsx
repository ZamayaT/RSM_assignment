import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import type { Itinerary } from "./api";
import { stamp } from "./format";

// A refused change that the user can send again on top of the latest saved version.
export interface PendingChange {
  description: string;
  apply: (version: number) => Promise<Itinerary>;
}

interface Props {
  change: PendingChange;
  latest: Itinerary;
  busy: boolean;
  onReapply: () => void;
  onDiscard: () => void;
}

export default function ConflictDialog({ change, latest, busy, onReapply, onDiscard }: Props) {
  return (
    <Dialog open maxWidth="md" fullWidth aria-labelledby="conflict-title">
      <DialogTitle id="conflict-title">Someone else saved first</DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 2 }}>
          The itinerary changed while you were working, so your change was <strong>not saved</strong>. Nothing was
          overwritten.
        </Alert>
        <Stack direction={{ xs: "column", md: "row" }} spacing={3}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="subtitle2">Your change (not saved)</Typography>
            <Typography sx={{ mt: 1 }}>{change.description}</Typography>
          </Box>
          <Box sx={{ flex: 1 }}>
            <Typography variant="subtitle2">Latest saved itinerary</Typography>
            {latest.items.length === 0 ? (
              <Typography color="text.secondary" sx={{ mt: 1 }}>No items.</Typography>
            ) : (
              <List dense>
                {latest.items.map((item, index) => (
                  <ListItem key={item.id} disableGutters>
                    <ListItemText
                      primary={`${index + 1}. ${item.title}`}
                      secondary={`${stamp(item.startsAt)} · ${item.price ? `≈ ${item.price.amount} USD` : "no price"}`}
                    />
                  </ListItem>
                ))}
              </List>
            )}
          </Box>
        </Stack>
        <Typography color="text.secondary" sx={{ mt: 2 }}>
          <strong>Re-apply</strong> sends your change again on top of the latest itinerary (it is checked again).{" "}
          <strong>Discard</strong> drops your change and shows the latest itinerary.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onDiscard} disabled={busy}>Discard</Button>
        <Button variant="contained" onClick={onReapply} disabled={busy}>
          {busy ? "Applying…" : "Re-apply"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
