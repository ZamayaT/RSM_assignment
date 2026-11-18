import { Box, CircularProgress, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { BACKEND_URL } from "./config";

type State = "loading" | "ok" | "error";

export default function BackendStatus() {
  const [state, setState] = useState<State>("loading");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${BACKEND_URL}/health`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then((body: { status?: string }) => setState(body.status === "ok" ? "ok" : "error"))
      .catch((error) => {
        if (error?.name !== "AbortError") setState("error");
      });
    return () => controller.abort();
  }, []);

  if (state === "loading") return <CircularProgress size={20} color="inherit" aria-label="Checking backend" />;
  const ok = state === "ok";
  return (
    <Typography variant="body2" role="status" sx={{ display: "flex", alignItems: "center", gap: 1, color: "text.secondary" }}>
      <Box component="span" sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: ok ? "success.main" : "error.main" }} />
      Backend status: {ok ? "ok" : "unreachable"}
    </Typography>
  );
}
