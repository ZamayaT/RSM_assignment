import { AppBar, Box, Button, Container, Toolbar, Typography } from "@mui/material";
import BackendStatus from "./BackendStatus";

// Navigation placeholder: real views are added in later changes.
const NAV_ITEMS = ["My trips"];

export default function App() {
  return (
    <>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Travel Planning Platform
          </Typography>
          {NAV_ITEMS.map((item) => (
            <Button key={item} color="inherit" disabled>
              {item}
            </Button>
          ))}
        </Toolbar>
      </AppBar>
      <Container sx={{ py: 4 }}>
        <Box>
          <BackendStatus />
        </Box>
      </Container>
    </>
  );
}
