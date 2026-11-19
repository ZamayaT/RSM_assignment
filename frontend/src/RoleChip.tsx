import { Chip } from "@mui/material";
import { BRAND } from "./theme";

// The user's role on a trip, as a white pill (design reference).
export default function RoleChip({ role }: { role: string }) {
  return (
    <Chip
      size="small"
      label={role}
      sx={{ bgcolor: BRAND.white, color: BRAND.dark, fontWeight: 700, px: 1, textTransform: "capitalize" }}
    />
  );
}
