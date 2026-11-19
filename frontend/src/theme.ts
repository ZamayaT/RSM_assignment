import { createTheme } from "@mui/material";

// Brand colors from the design reference. All colors live here; pages use theme tokens, not hex values.
export const BRAND = {
  dark: "#185075", // header, cards, text on white
  mid: "#427ea6", // page background, rows inside cards
  orange: "#f57b31", // main actions and active navigation
  white: "#ffffff",
};

// Secondary text on blue: white with some transparency (dark blue on mid blue is not readable).
const SOFT_WHITE = "rgba(255, 255, 255, 0.82)";
const FOCUS_RING = { outline: `2px solid ${BRAND.white}`, outlineOffset: 2 };

export const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: BRAND.orange, contrastText: BRAND.dark },
    secondary: { main: BRAND.mid, contrastText: BRAND.white },
    background: { default: BRAND.mid, paper: BRAND.dark },
    text: { primary: BRAND.white, secondary: SOFT_WHITE },
    divider: "rgba(255, 255, 255, 0.2)",
    // Status colors are kept clearly apart from the brand orange (amber, green, red, light blue).
    success: { main: "#66bb6a" },
    error: { main: "#ff7b7b" },
    warning: { main: "#ffd54f" },
    info: { main: "#81d4fa" },
  },
  typography: {
    fontFamily: 'Montserrat, "Helvetica Neue", Arial, sans-serif',
    h2: { fontWeight: 700 },
    h3: { fontWeight: 700 },
    h4: { fontWeight: 700 },
    h5: { fontWeight: 700 },
    h6: { fontWeight: 700 },
    subtitle1: { fontWeight: 600 },
    subtitle2: { fontWeight: 700 },
    button: { fontWeight: 700, textTransform: "none" },
  },
  shape: { borderRadius: 12 },
  components: {
    MuiCssBaseline: {
      styleOverrides: { body: { backgroundColor: BRAND.mid } },
    },
    MuiButtonBase: {
      styleOverrides: { root: { "&.Mui-focusVisible": FOCUS_RING } },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          // Radius in em scales with the button's size: a pill on one line, a rounded box on taller buttons.
          borderRadius: "1.25em",
          paddingLeft: 18,
          paddingRight: 18,
          textAlign: "center",
          justifyContent: "center",
          "&.Mui-focusVisible": FOCUS_RING,
          // Disabled actions stay visible but are clearly unavailable.
          "&.Mui-disabled": { color: "rgba(255, 255, 255, 0.5)" },
          // Orange is reserved for main (contained) actions; secondary actions are white on blue.
          variants: [
            { props: { variant: "text", color: "primary" }, style: { color: BRAND.white } },
            { props: { variant: "outlined", color: "primary" }, style: { color: BRAND.white, borderColor: "rgba(255, 255, 255, 0.6)" } },
          ],
        },
        contained: { "&.Mui-disabled": { backgroundColor: "rgba(255, 255, 255, 0.14)" } },
      },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { backgroundImage: "none" } },
    },
    MuiDialog: {
      styleOverrides: { paper: { borderRadius: 24, backgroundColor: BRAND.dark } },
    },
    MuiChip: {
      styleOverrides: { root: { borderRadius: 999, fontWeight: 600 } },
    },
    // Filled alerts: light status color with dark text (the dark-mode default is a near-black background).
    MuiAlert: {
      defaultProps: { variant: "filled" },
      styleOverrides: { root: { borderRadius: 12, fontWeight: 500 } },
    },
    MuiAppBar: {
      defaultProps: { elevation: 0, color: "transparent" },
      styleOverrides: { root: { backgroundColor: BRAND.dark, backgroundImage: "none" } },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderBottomColor: "rgba(255, 255, 255, 0.15)" },
        head: { fontWeight: 700 },
      },
    },
    MuiTabs: {
      styleOverrides: { indicator: { display: "none" } },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          minHeight: 40,
          textTransform: "none",
          fontWeight: 500,
          fontSize: "1rem",
          color: BRAND.white,
          "&.Mui-selected": { backgroundColor: BRAND.white, color: BRAND.dark },
          "&.Mui-focusVisible": { outline: `2px solid ${BRAND.orange}`, outlineOffset: -2 },
        },
      },
    },
  },
});
