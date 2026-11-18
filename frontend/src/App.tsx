import { AppBar, Button, Container, Toolbar, Typography } from "@mui/material";
import { Link as RouterLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { RequireUser, SessionProvider, useSession } from "./session";
import Participants from "./pages/Participants";
import Bookings from "./pages/Bookings";
import BudgetView from "./pages/BudgetView";
import Itinerary from "./pages/Itinerary";
import Search from "./pages/Search";
import TripForm from "./pages/TripForm";
import TripOverview from "./pages/TripOverview";
import TripsList from "./pages/TripsList";
import UserSelect from "./pages/UserSelect";

function AppBarContent() {
  const { user, signOut } = useSession();
  const navigate = useNavigate();

  return (
    <AppBar position="static">
      <Toolbar>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Travel Planning Platform
        </Typography>
        {user && (
          <>
            <Button color="inherit" component={RouterLink} to="/trips">
              My trips
            </Button>
            <Typography sx={{ mx: 2 }}>{user.displayName}</Typography>
            <Button
              color="inherit"
              onClick={() => {
                signOut();
                navigate("/");
              }}
            >
              Switch user
            </Button>
          </>
        )}
      </Toolbar>
    </AppBar>
  );
}

export default function App() {
  return (
    <SessionProvider>
      <AppBarContent />
      <Container sx={{ py: 4 }}>
        <Routes>
          <Route path="/" element={<UserSelect />} />
          <Route path="/trips" element={<RequireUser><TripsList /></RequireUser>} />
          <Route path="/trips/new" element={<RequireUser><TripForm /></RequireUser>} />
          <Route path="/trips/:id" element={<RequireUser><TripOverview /></RequireUser>} />
          <Route path="/trips/:id/participants" element={<RequireUser><Participants /></RequireUser>} />
          <Route path="/trips/:id/search" element={<RequireUser><Search /></RequireUser>} />
          <Route path="/trips/:id/itinerary" element={<RequireUser><Itinerary /></RequireUser>} />
          <Route path="/trips/:id/budget" element={<RequireUser><BudgetView /></RequireUser>} />
          <Route path="/trips/:id/bookings" element={<RequireUser><Bookings /></RequireUser>} />
          <Route path="/trips/:id/edit" element={<RequireUser><TripForm /></RequireUser>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Container>
    </SessionProvider>
  );
}
