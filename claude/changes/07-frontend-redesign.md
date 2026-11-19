# Change 07 — Frontend redesign

Status: Complete

## Goal
Apply the simple visual design in `RSM assignment simple design.pdf` to every view built so far, without losing any feature or behavior. One theme (Montserrat, a blue and orange palette) and three layouts: a full-screen **user selection**, a **My trips** card list, and a **trip workspace**. The workspace has a fixed general-info card on the left and a tabbed, scrollable section card on the right (Itinerary, Bookings, Budget, Participants and Search). Later views (Documents, Assistant) plug into the same layout as new tabs. This is frontend only: the backend, the API and all tests stay unchanged.

## Priority rule
**Keeping every current feature matters more than matching the PDF exactly.** The PDF is inspiration, not a 1:1 spec. If the design leaves no room for an existing action, state, message or piece of information, keep the feature and adapt the design: add a button, a line of text, a tab or a scroll area. Never drop or hide the feature. The only removals are the ones listed under "Allowed removals" below. Each one is replaced by something that does the same job.

## Features to preserve (checklist for every task)
Everything below works today and must still work, for the same roles, after the change:
- **Session**: list seeded users and sign in by clicking one; the session survives a reload; signing out is possible (now through the header title); backend status indicator on the start page; protected routes send a user who is not logged in to the start page.
- **My trips**: the user's trips with name, dates, destinations and role; empty state; loading and error states; any user can create a trip.
- **Create/edit trip**: all fields (name, destinations from the supported list, dates, travelers, budget, notes); per-field validation errors; nothing reported as saved unless it was saved; the "Trip saved" confirmation; the version-based conflict dialog with re-apply/discard; edit only for organizer and editor.
- **Trip overview data** (now the left card): dates, destinations, travelers, budget, current total with estimated and confirmed parts, remaining or over budget, itinerary item and warning counts, booking counts by status, notes, the user's role; "Trip not found" for non-participants.
- **Participants**: list with roles; search users by username; add as editor or viewer; change role; remove; organizer only (read-only for editor and viewer); errors shown.
- **Search**: category, destination, origin (transport only), date window and travelers with defaults, optional supplier; results with title, supplier, schedule, price, availability, restrictions, "searched at" and "quote valid until"; labeled as estimates; complete, partial (a warning per supplier), empty and failed states; "Add to itinerary" for organizer and editor only; the link to the itinerary after adding.
- **Itinerary**: items in order with schedule, destination, cost and status label (estimate, expired quote, booking pending, confirmed, failed, unknown); per-item warnings; remove, reorder, refresh price and book (organizer/editor only, refused for booked items); "Saved" feedback and the conflict dialog; the visible explanation of the simplified scheduling rules.
- **Budget**: itemized table (item, category, amount, estimate or confirmed); estimated, confirmed and combined totals; remaining or over budget; the rounding rule note.
- **Booking confirmation dialog**: current quote next to the saved estimate, highlighted differences, availability and restrictions, explicit "Confirm booking", unavailable offers cannot be confirmed, errors explained.
- **Bookings**: one row per attempt with status, accepted price and timestamps; automatic polling while any attempt is live, restored after reload; "Check again", "Retry", "Choose another offer"; "Outcome unresolved" and "Taking longer than expected" messages; the summary of next steps when results are mixed; the booking counters.
- **Permissions in the UI**: viewers see no write actions anywhere; editors cannot manage participants; every backend refusal (`401`, `403`, `404`, `409`) is still shown as a clear message.

## Allowed removals (replaced, not lost)
- Each section's own page title, plus its "Back to trip", "Back to My trips" and cross-section buttons: replaced by the header and the tab bar. Section-specific links that start an action stay, for example "Choose another offer" going to the Search tab, and "View itinerary" after adding a search result.
- The "Switch user" button: replaced by clicking the header title.
- The separate Trip overview page: its content moves into the left card.

## Design reference (from the PDF)
- **Font**: Montserrat. Bold for titles, names and buttons; regular for body text.
- **Colors**:
  - `#185075` (dark blue): header bar, cards, primary text on white.
  - `#427ea6` (mid blue): page background and list rows inside cards.
  - `#f57b31` (orange): main actions ("+ New Trip", "Edit Trip"), the active nav link and the app title on the start page.
  - `#ffffff` (white): text on blue, the selected tab pill, role pills and user buttons.
- **Shapes**: large rounded corners on cards (~24px), pill-shaped buttons, tabs and chips. Flat, with no shadows.
- **Start page**: full dark-blue screen, centered orange title "Travel Planning Platform", a white subtitle, and the users as white rounded buttons with dark-blue text, wrapped in rows.
- **Header** (after login): dark-blue bar with the bold white title on the left, then "My trips" (orange when active, white otherwise) and the bold username on the right.
- **My trips**: one large dark-blue card with the "My Trips" title and an orange "+ New Trip" pill. Each trip is a mid-blue rounded row: bold name, dates under it, a white role pill top right, destinations bottom right.
- **Trip workspace**: the left card shows the trip name, dates, general info and an orange "Edit Trip" button at the bottom. On the right, a pill tab bar (selected tab = white pill) sits above a dark-blue card. **Only the section card scrolls; the header, the left card and the tabs stay fixed.**

## Scope
- Frontend (`frontend/`) only: theme, layout shell, restyled views and the new trip workspace layout.
- `PROJECT.md`: update section 4 (main views follow the new layout), section 8 (theme decision) and section 10 (insert this change and renumber the later ones).
- `README.md`: only if setup changes (for example, a new npm dependency installed by the image build).

## Out of scope
- Backend, API, database, worker and mock: no changes. Every backend test must still pass unchanged.
- New features or new data. The design's "General info" uses only data the API already returns.
- Documents and Assistant views (built in their own changes, as new tabs in this layout).
- Dark/light mode switching, animations, a custom icon set, responsive polish beyond "usable on a narrow screen".
- Frontend automated tests (documented limit in `PROJECT.md` section 11); checked manually in the browser.
- `assignment/` is read-only reference.

## Decisions
- **Language** (Confirmed (developer)): all UI text is English, nothing in Spanish. The start page subtitle is "Select a user to sign in" (the PDF's Spanish text is only a placeholder).
- **Users on the start page**: the PDF shows sample names (Alicia, Clara, ...). The buttons show the seeded users' `displayName` from the API, with no hard-coded names.
- **Font loading** (Confirmed (developer)): Montserrat is self-hosted with the npm dependency `@fontsource/montserrat` (weights 400, 600, 700), imported in `main.tsx`. It works offline inside Docker and keeps startup reproducible. Fallback stack: `Montserrat, "Helvetica Neue", Arial, sans-serif`.
- **One MUI theme, no CSS framework**: `createTheme` with `palette.mode: "dark"` (so MUI text, inputs, tables, dividers and dialogs default to light-on-dark), `background.default #427ea6`, `background.paper #185075`, `primary #f57b31` with dark-blue `contrastText`, `secondary #427ea6`, Montserrat typography, `shape.borderRadius` and component overrides (`MuiButton` pill, `MuiPaper` rounded and flat, `MuiChip` pill, `MuiTabs` pill). The pages get their look from the theme, so their logic barely changes.
- **Workspace routing keeps today's URLs**: `/trips/:id` becomes a layout route (left card, tab bar, `<Outlet/>` in the right card). Its children, in tab order, are `itinerary`, `budget`, `bookings`, `search` and `participants`. `/trips/:id` redirects to `/trips/:id/itinerary`. The selected tab comes from the URL, so reload, back/forward and existing links keep working. `/trips/:id/edit` and `/trips/new` stay full pages that use one centered card.
- **Search is a tab** (Confirmed (developer)): the PDF shows four tabs, but Search is an existing view that every role can use, so it becomes a fifth tab ("Search"). Its "Add to itinerary" result is unchanged.
- **Left card content (general info)**: role pill, dates, destinations, travelers, budget versus current total (estimated/confirmed, remaining or over budget), itinerary warning count, booking counts by status, and notes. This is everything the current Trip overview shows (`PROJECT.md` 4.4). "Edit Trip" is shown only to organizers and editors, as today.
- **Left card stays current**: the workspace loads trip, budget, itinerary and bookings for the card and shares a `refresh()` function with its sections through a small React context (each section still loads its own data). Sections call `refresh()` after a write (add/remove/reorder, refresh price, book, check again, participant changes), so the counters never go stale. No new library.
- **Sections lose their own chrome**: the per-page title, "Back to trip", "Back to My trips" and cross-links (for example, "Budget" inside Itinerary) are removed, because the tabs and header replace them. Each section keeps its own loading, error, empty, conflict and permission states.
- **Fixed layout**: on screens of at least `md` width, the workspace fills the viewport height under the header. The left card and tab bar do not scroll; the section card has `overflow: auto`. On narrow screens the cards stack vertically and the page scrolls normally, so nothing becomes unreachable.
- **Changing user** (Confirmed (developer)): there is no "Switch user" button or menu. Clicking the "Travel Planning Platform" title in the header ends the session (clears the stored token) and returns to the user selection page, where another user can be chosen. The start page (`/`) is always shown, even when a session is stored; choosing a user replaces it. The username in the header is plain text, with a person icon above it.
- **Backend status**: the existing `BackendStatus` indicator stays on the start page, as a small line under the user buttons.

## Recommendations (Confirmed (developer): all implemented)
- **Readable contrast**: in the PDF, dates and destinations use `#185075` text on the `#427ea6` rows, which is hard to read (contrast ratio about 2.3:1). Use white at about 80% opacity for secondary text on blue instead. Dark-blue text stays on white or orange only.
- **Status colors stay distinct from the brand orange**: status chips (estimate, expired quote, pending, confirmed, failed, unknown) and alerts keep separate, clearly different colors, for example green for confirmed, red for failed, amber for pending/unknown and grey for estimate. A warning should never look like an orange action button. Status labels always include the text, never color alone.
- **Dialogs and tables**: the booking confirmation dialog, the conflict dialog and the budget/bookings tables use the dark card surface with white text. Highlighted differences (changed price or availability) use a visible outline or background, not only color.
- **Visible focus and keyboard**: tabs, pill buttons and trip rows keep a visible focus ring (white outline) and stay reachable with the keyboard. Trip rows are links, not click-only boxes.
- **Clearly disabled controls**: on blue, disabled buttons need a visible style so viewers can tell an action is unavailable, not broken.
- **Theme in one file**: put all colors and shapes in `frontend/src/theme.ts`, so later views (Documents, Assistant) get the style automatically and there are no hard-coded colors in pages.

## Tasks

### Theme and shell
- [x] 1.1 Add Montserrat (`@fontsource/montserrat`, weights 400/600/700) and `frontend/src/theme.ts` with the palette, typography and component overrides above (pill buttons/chips/tabs, rounded flat cards, readable secondary text, distinct status colors, visible focus and disabled styles); wrap the app in `ThemeProvider` in `main.tsx`.
- [x] 1.2 Header: dark-blue bar; the bold "Travel Planning Platform" title on the left is a link that signs out and returns to the user selection page; "My trips" link (orange when active) and the bold username (plain text) on the right. The "Switch user" button is removed. The header is hidden on the start page.

### Pages
- [x] 2.1 User selection: full-screen dark-blue page, centered orange title, white subtitle "Select a user to sign in", seeded users as white rounded buttons in wrapped rows, error/retry and loading states, backend status line.
- [x] 2.2 My trips: one large card with "My Trips" and an orange "+ New Trip" pill; each trip is a mid-blue rounded row link (name, dates, role pill, destinations); restyled loading, error and empty states.
- [x] 2.3 Create/edit trip: the existing form inside one centered card in the new style; per-field validation, "saved" feedback and the conflict dialog keep working.

### Trip workspace
- [x] 3.1 Workspace layout route for `/trips/:id`: trip context (`refresh()` for the info card's trip, budget, itinerary and bookings), left general-info card with "Edit Trip" for organizer/editor, pill tab bar (Itinerary, Budget, Bookings, Search, Participants) bound to the URL, right section card with its own scroll, redirect from `/trips/:id` to the Itinerary tab, and trip-level "not found"/error state. Remove the old `TripOverview` page.
- [x] 3.2 Move Itinerary, Bookings, Budget, Participants and Search into the section card: remove their duplicated title and navigation buttons, call `refresh()` after writes, and keep their loading, error, empty, conflict, polling and role-based states.
- [x] 3.3 Restyle the booking confirmation dialog, the conflict dialog, tables, status chips and alerts so they are readable on the dark surface, with differences highlighted by more than color alone.
- [x] 3.4 Narrow-screen fallback: the cards stack vertically and the page scrolls; tabs scroll horizontally if needed.

### Documentation and checks
- [x] 4.1 Update `PROJECT.md`: section 4 (layout: user selection, My trips, trip workspace with tabs; Trip overview becomes the left card), section 8.1/8.2 (theme decision: Montserrat, palette, MUI theme), section 10 (insert this change as 7, renumber Documents to 8, MCP and assistant to 9, Delivery to 10) and rename the planned change files accordingly. Update `README.md` only if setup changed.
- [x] 4.2 Manual pass in the browser with each role (organizer, editor, viewer, non-participant URL): go through the "Features to preserve" checklist item by item and every acceptance criterion of changes 2 to 6 in the new layout; report any item that could not be checked. Run `npm run build` (type check) and the backend test suite (`docker compose exec backend pytest`) to confirm nothing outside the frontend changed. Then `docker compose down`.

## Acceptance criteria
- Every item in "Features to preserve" works for the same roles as before; nothing was removed except the "Allowed removals".
- Every page uses Montserrat and the PDF palette; no page shows the default MUI look.
- The start page matches the PDF layout, in English, and signing in as any seeded user opens My trips. Clicking the header title from any page signs out and returns to the start page, where a different user can be chosen. No "Switch user" button exists.
- My trips shows each trip as a rounded row with name, dates, destinations and role pill; "+ New Trip" opens the form.
- Opening a trip shows the left general-info card and the tab bar; the Itinerary tab is selected by default. Only the section card scrolls on a desktop-size window.
- Reloading `/trips/:id/bookings` (or any other tab URL) opens that tab; the browser back button moves between tabs.
- All features from changes 2 to 6 still work from the new layout: create/edit with validation and conflict dialog, participants by role, search with complete/partial/empty/failed states, add/remove/reorder/refresh price, booking with confirmation, Bookings polling and "Check again", the budget with estimate and confirmed totals.
- After a write in any tab (for example a booking or removing an item), the left card's counters and totals update without a reload.
- On a trip where they are a viewer, a user sees no "Edit Trip", add/remove/reorder, refresh price, book, check again or participant-management actions (they can still create their own trips); an editor's Participants tab is read-only; a non-participant sees the "not found" state.
- Status labels and alerts are distinguishable from the orange action buttons and readable on blue; secondary text on blue rows is readable (no dark-blue on mid-blue text).
- Tabs, buttons and trip rows show a visible focus ring and work with the keyboard; disabled actions look clearly disabled.
- Changed terms in the booking confirmation dialog are highlighted by more than color alone.
- On a narrow window everything stays reachable by scrolling.
- `npm run build` succeeds; the backend tests pass unchanged; `assignment/` is untouched.

## Implementation notes
- The workspace context shares only `refresh()`. Each section still loads its own data exactly as before, so its loading, error and polling behavior is unchanged. While any booking can still change, the workspace also refreshes the left card every 5 s.
- No planned change files existed beyond 06, so nothing needed renaming. `README.md` was updated where it described "Switch user".
- Revisions after the first review (Confirmed (developer)):
  - Alerts are filled: light status color with dark text, instead of the near-black dark-mode default.
  - Every button has an em-based corner radius that scales with its size, and centered text.
  - The Search form fills the card's width in a responsive grid.
  - The tabs share the bar equally (they scroll on very narrow screens).
  - `/` always shows the user selection (the home page), even with a stored session.
  - A person icon sits above the username in the header (inline SVG, no icon dependency).
  - Tab order: Itinerary, Budget, Bookings, Search, Participants.
  - The Participants tab fills the section card's width, and the workspace is split about 25% (info card, at least 300px) / 75% (section card).
  - The date inputs stay the browser's native ones (a custom date picker was tried and reverted, so no extra dependency), and the text keeps MUI's default size.
- 4.2 status: `npm run build` passes and the backend suite passes (222 tests). The manual browser pass per role was done by the developer later.

## Technologies implemented
- **`@fontsource/montserrat`** (npm): self-hosted Montserrat font (weights 400/600/700) imported in `main.tsx`, so the font works offline inside Docker.
