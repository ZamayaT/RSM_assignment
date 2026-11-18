import { Alert, CircularProgress } from "@mui/material";
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

  if (state === "loading") return <CircularProgress aria-label="Checking backend" />;
  if (state === "ok") return <Alert severity="success">Backend status: ok</Alert>;
  return <Alert severity="error">Backend status: unreachable</Alert>;
}
