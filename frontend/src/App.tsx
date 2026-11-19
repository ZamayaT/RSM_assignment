import { AppBar, Box, Button, ButtonBase, SvgIcon, Toolbar, Tooltip, Typography } from "@mui/material";
import { Link as RouterLink, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { RequireUser, SessionProvider, useSession } from "./session";
import Participants from "./pages/Participants";
import Bookings from "./pages/Bookings";
import BudgetView from "./pages/BudgetView";
import Itinerary from "./pages/Itinerary";
import Search from "./pages/Search";
import TripForm from "./pages/TripForm";
import TripWorkspace from "./pages/TripWorkspace";
import TripsList from "./pages/TripsList";
import UserSelect from "./pages/UserSelect";
import { BRAND } from "./theme";

function Header() {
  const { user, signOut } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // The title is the way to change user: it ends the session and returns to the user selection.
  function toUserSelection() {
    signOut();
    navigate("/");
  }

  return (
    <AppBar position="static">
      <Toolbar sx={{ minHeight: { xs: 72, md: 96 }, px: { xs: 2, md: 4 }, gap: 2 }}>
        <Tooltip title="Sign out and choose another user">
          <ButtonBase
            onClick={toUserSelection}
            aria-label="Travel Planning Platform: sign out and choose another user"
            sx={{ borderRadius: 2, px: 1, py: 0.5, textAlign: "left" }}
          >
            <Typography variant="h6" component="span" sx={{ lineHeight: 1.25, maxWidth: 220 }}>
              Travel Planning Platform
            </Typography>
          </ButtonBase>
        </Tooltip>
        <Box sx={{ flexGrow: 1 }} />
        <Button
          component={RouterLink}
          to="/trips"
          aria-current={pathname === "/trips" ? "page" : undefined}
          sx={{ fontWeight: 500, fontSize: "1.1rem", color: pathname === "/trips" ? `${BRAND.orange} !important` : undefined }}
        >
          My trips
        </Button>
        <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", ml: { xs: 1, md: 4 } }}>
          <SvgIcon aria-hidden sx={{ fontSize: 32 }}>
            <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4m0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4" />
          </SvgIcon>
          <Typography sx={{ fontWeight: 700, fontSize: "1.1rem" }}>{user?.displayName}</Typography>
        </Box>
      </Toolbar>
    </AppBar>
  );
}

// Signed-in pages: header on top, content below. On wide screens the content area scrolls under a fixed header.
function MainLayout() {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh", height: { md: "100vh" } }}>
      <Header />
      <Box component="main" sx={{ flex: 1, minHeight: 0, overflow: { md: "auto" }, p: { xs: 2, md: 3 } }}>
        <Outlet />
      </Box>
    </Box>
  );
}

export default function App() {
  return (
    <SessionProvider>
      <Routes>
        <Route path="/" element={<UserSelect />} />
        <Route element={<RequireUser><MainLayout /></RequireUser>}>
          <Route path="/trips" element={<TripsList />} />
          <Route path="/trips/new" element={<TripForm />} />
          <Route path="/trips/:id/edit" element={<TripForm />} />
          <Route path="/trips/:id" element={<TripWorkspace />}>
            <Route index element={<Navigate to="itinerary" replace />} />
            <Route path="itinerary" element={<Itinerary />} />
            <Route path="bookings" element={<Bookings />} />
            <Route path="budget" element={<BudgetView />} />
            <Route path="participants" element={<Participants />} />
            <Route path="search" element={<Search />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SessionProvider>
  );
}
