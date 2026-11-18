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
import { useEffect, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { api, ApiError, type Budget } from "../api";

export default function BudgetView() {
  const { id = "" } = useParams();
  const [budget, setBudget] = useState<Budget | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.budget(id).then(setBudget).catch((e: ApiError) => setError(e.status === 404 ? "Trip not found." : e.message));
  }, [id]);

  if (error)
    return (
      <Box>
        <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
        <Button component={RouterLink} to="/trips">Back to My trips</Button>
      </Box>
    );
  if (!budget) return <CircularProgress aria-label="Loading budget" />;

  const over = budget.overBudget;
  const remaining = over ? budget.remaining.replace("-", "") : budget.remaining;

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Budget (USD)</Typography>
        <Button component={RouterLink} to={`/trips/${id}/itinerary`}>Itinerary</Button>
        <Button component={RouterLink} to={`/trips/${id}`}>Back to trip</Button>
      </Stack>

      <Alert severity={over ? "error" : "success"}>
        {over ? `Over budget by ${remaining} USD.` : `${remaining} USD remaining of the ${budget.budget} USD budget.`}
      </Alert>

      {budget.lines.length === 0 ? (
        <Alert severity="info">No items yet. Add offers from Search to see their costs here.</Alert>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Item</TableCell>
                <TableCell>Category</TableCell>
                <TableCell align="right">Amount (USD)</TableCell>
                <TableCell>Kind</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {budget.lines.map((line) => (
                <TableRow key={line.itemId}>
                  <TableCell>{line.title}</TableCell>
                  <TableCell>{line.category}</TableCell>
                  <TableCell align="right">{line.amount ?? "—"}</TableCell>
                  <TableCell>
                    <Chip size="small" variant="outlined" label={line.kind === "estimate" ? "Estimate" : "Confirmed"} />
                    {line.expired && <Chip size="small" color="warning" label="Expired quote" sx={{ ml: 1 }} />}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      <Table size="small" sx={{ maxWidth: 420 }}>
        <TableBody>
          <TableRow><TableCell>Estimated total</TableCell><TableCell align="right">{budget.estimatedTotal}</TableCell></TableRow>
          <TableRow><TableCell>Confirmed total</TableCell><TableCell align="right">{budget.confirmedTotal}</TableCell></TableRow>
          <TableRow><TableCell><strong>Combined total</strong></TableCell><TableCell align="right"><strong>{budget.combinedTotal}</strong></TableCell></TableRow>
          <TableRow><TableCell>Trip budget</TableCell><TableCell align="right">{budget.budget}</TableCell></TableRow>
          <TableRow>
            <TableCell>{over ? "Over budget by" : "Remaining"}</TableCell>
            <TableCell align="right">{remaining}</TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <Typography variant="body2" color="text.secondary">
        Each amount is the offer's total price for the party as quoted when it was added; it is an estimate, not a booking,
        and is not multiplied by travelers. Totals are exact sums to the cent (any result with more decimals is rounded
        half-up to the cent). Items without a price are left out of the totals. Expired quotes still count but are flagged.
      </Typography>
    </Stack>
  );
}
