import { Alert, Box, Button, CircularProgress, List, ListItem, ListItemButton, ListItemText, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api, ApiError, type User } from "../api";
import BackendStatus from "../BackendStatus";
import { useSession } from "../session";

export default function UserSelect() {
  const { user, signIn } = useSession();
  const navigate = useNavigate();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.users().then(setUsers).catch((e: ApiError) => setError(e.message));
  }, []);

  if (user) return <Navigate to="/trips" replace />;

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
    <Box>
      <Typography variant="h5" gutterBottom>
        Choose a user
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {!users && !error && <CircularProgress aria-label="Loading users" />}
      {users && (
        <List sx={{ maxWidth: 360 }}>
          {users.map((u) => (
            <ListItem key={u.id} disablePadding>
              <ListItemButton onClick={() => choose(u.username)}>
                <ListItemText primary={u.displayName} secondary={u.username} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}
      {error && <Button onClick={() => window.location.reload()}>Retry</Button>}
      <Box sx={{ mt: 4, maxWidth: 360 }}>
        <BackendStatus />
      </Box>
    </Box>
  );
}
