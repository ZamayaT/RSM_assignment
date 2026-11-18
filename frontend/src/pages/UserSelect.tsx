import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type User } from "../api";
import BackendStatus from "../BackendStatus";
import { useSession } from "../session";
import { BRAND } from "../theme";

export default function UserSelect() {
  // The start page is always shown at "/", even with a stored session: choosing a user replaces it.
  const { signIn } = useSession();
  const navigate = useNavigate();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.users().then(setUsers).catch((e: ApiError) => setError(e.message));
  }, []);

  async function choose(username: string) {
    setError(null);
    try {
      signIn(await api.login(username));
      navigate("/trips");
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  return (
    <Box
      component="main"
      sx={{
        minHeight: "100vh",
        bgcolor: "background.paper",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        px: 2,
        py: 6,
      }}
    >
      <Typography variant="h2" component="h1" sx={{ color: "primary.main", fontSize: { xs: "2.4rem", md: "3.75rem" }, maxWidth: 560 }}>
        Travel Planning Platform
      </Typography>
      <Typography variant="h5" component="p" sx={{ fontWeight: 400, mt: 5, mb: 5 }}>
        Select a user to sign in
      </Typography>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {!users && !error && <CircularProgress color="inherit" aria-label="Loading users" />}
      {users && (
        <Stack direction="row" useFlexGap sx={{ flexWrap: "wrap", justifyContent: "center", gap: { xs: 2, md: 4 }, maxWidth: 720 }}>
          {users.map((u) => (
            <Button
              key={u.id}
              onClick={() => choose(u.username)}
              sx={{
                bgcolor: BRAND.white,
                color: `${BRAND.dark} !important`,
                px: 3,
                py: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                lineHeight: 1.2,
                "&:hover": { bgcolor: "rgba(255, 255, 255, 0.85)" },
              }}
            >
              <Box component="span" sx={{ fontSize: "1.5rem", fontWeight: 500 }}>{u.displayName}</Box>
              <Box component="span" sx={{ fontSize: "0.8rem", fontWeight: 500, opacity: 0.75 }}>@{u.username}</Box>
            </Button>
          ))}
        </Stack>
      )}
      {error && <Button variant="outlined" onClick={() => window.location.reload()} sx={{ mt: 2 }}>Retry</Button>}
      <Box sx={{ mt: 6 }}>
        <BackendStatus />
      </Box>
    </Box>
  );
}
