import { BACKEND_URL } from "./config";

export interface User {
  id: string;
  username: string;
  displayName: string;
}

export interface Trip {
  id: string;
  name: string;
  destinations: string[];
  startDate: string;
  endDate: string;
  travelers: number;
  budget: string; // decimal string with two fractional digits
  notes: string | null;
  version: number;
  role: string;
  createdAt: string;
  updatedAt: string;
}

export interface TripInput {
  name: string;
  destinations: string[];
  startDate: string;
  endDate: string;
  travelers: number;
  budget: string;
  notes: string | null;
}

export interface Participant {
  userId: string;
  username: string;
  displayName: string;
  role: string;
}

export interface SearchOptions {
  categories: string[];
  origins: string[];
  suppliers: string[];
}

export interface SearchInput {
  category: string;
  destination: string;
  origin?: string;
  startsOn?: string;
  endsOn?: string;
  travelers?: number;
  providerId?: string;
}

export interface Offer {
  id: string;
  providerId: string;
  category: string;
  title: string;
  description: string;
  destination: string;
  origin: string | null;
  startsAt: string;
  endsAt: string;
  travelers: number;
  price: { amount: string; currency: string };
  revision: string;
  available: boolean;
  validUntil: string;
}

export interface SearchResult {
  state: "complete" | "partial" | "empty";
  offers: Offer[];
  warnings: { providerId: string; code: string; message: string }[];
  searchedAt: string;
}

export type ItemStatus = "estimate" | "expired_quote" | "booking_pending" | "confirmed" | "failed" | "unknown";

export interface ItineraryWarning {
  code: string;
  message: string;
}

export interface ItineraryItem {
  id: string;
  offerId: string;
  providerId: string;
  category: string;
  title: string;
  description: string;
  destination: string;
  origin: string | null;
  startsAt: string | null;
  endsAt: string | null;
  travelers: number;
  price: { amount: string; currency: string } | null;
  acceptedPrice: { amount: string; currency: string } | null; // set once the booking is confirmed
  revision: string;
  available: boolean;
  validUntil: string | null;
  status: ItemStatus;
  warnings: ItineraryWarning[];
  addedAt: string;
}

export interface Itinerary {
  version: number;
  items: ItineraryItem[];
}

export interface BudgetLine {
  itemId: string;
  title: string;
  category: string;
  amount: string | null;
  kind: "estimate" | "confirmed";
  expired: boolean;
  status: ItemStatus;
}

export interface Budget {
  currency: string;
  lines: BudgetLine[];
  estimatedTotal: string;
  confirmedTotal: string;
  combinedTotal: string;
  budget: string;
  remaining: string; // negative when over budget
  overBudget: boolean;
}

export interface Money {
  amount: string;
  currency: string;
}

export interface QuoteTerms {
  price: Money;
  revision: string;
  available: boolean;
  validUntil: string | null;
  expired: boolean;
}

// The provider's current terms next to what the itinerary saved.
export interface Quote {
  itemId: string;
  saved: QuoteTerms;
  current: QuoteTerms;
  changes: ("price" | "revision" | "availability" | "expired")[];
  description: string; // the provider's current description, including its conditions
  bookable: boolean;
  reason: string | null;
}

export type AttemptStatus = "initiated" | "pending" | "confirmed" | "failed" | "unknown";

export interface BookingAttempt {
  id: string;
  itemId: string;
  itemTitle: string;
  status: AttemptStatus;
  offerId: string;
  requestedPrice: Money;
  acceptedPrice: Money | null;
  providerBookingId: string | null;
  failure: { code: string; message: string } | null;
  unresolved: boolean;
  takingLonger: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface Bookings {
  attempts: BookingAttempt[]; // newest first
  counts: { pending: number; confirmed: number; failed: number; unknown: number };
}

// Latest saved state returned with an itinerary version conflict.
export interface LatestState {
  trip: Trip;
  itinerary: Itinerary;
}

export type DocumentStatus = "waiting" | "in_progress" | "complete" | "failed";

export interface TripDocument {
  id: string;
  tripId: string;
  status: DocumentStatus;
  tripVersion: number; // the trip version the document was generated from
  requestedBy: { id: string; displayName: string } | null;
  snapshotAt: string;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  sizeBytes: number | null;
  failureMessage: string | null;
  attempts: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
    public latest?: Trip,
    public latestState?: LatestState,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

// --- session (token + user kept in localStorage) ---

export interface Session {
  token: string;
  user: User;
}

const SESSION_KEY = "session";

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session | null): void {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    // Storage unavailable: the session just won't survive a reload.
  }
}

// Called on any 401 so the app can return to the user selection.
let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

// --- requests ---

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = loadSession()?.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the server. Please try again.");
  }

  if (response.status === 204) return undefined as T;
  if (response.ok) return (await response.json()) as T;
  throw await toApiError(response);
}

async function toApiError(response: Response): Promise<ApiError> {
  let data: {
    code?: string;
    message?: string;
    details?: { fields?: Record<string, string>; latest?: Trip | LatestState };
  } = {};
  try {
    data = await response.json();
  } catch {
    // Non-JSON error body: fall back to the generic message below.
  }
  if (response.status === 401) unauthorizedHandler?.();
  const latest = data.details?.latest;
  const isState = latest !== undefined && "itinerary" in latest;
  return new ApiError(
    response.status,
    data.code ?? "ERROR",
    data.message ?? `Request failed (${response.status}).`,
    data.details?.fields,
    isState ? undefined : (latest as Trip | undefined),
    isState ? (latest as LatestState) : undefined,
    data.details as Record<string, unknown> | undefined,
  );
}

// The PDF is fetched with the bearer token (never in the URL) and handed back as a file to save.
async function downloadFile(path: string): Promise<{ blob: Blob; filename: string }> {
  const token = loadSession()?.token;
  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the server. Please try again.");
  }
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.();
    throw await toApiError(response);
  }
  const match = /filename="?([^";]+)"?/.exec(response.headers.get("Content-Disposition") ?? "");
  return { blob: await response.blob(), filename: match?.[1] ?? "trip-document.pdf" };
}

export const api = {
  users: () => request<User[]>("/auth/users"),
  login: (username: string) => request<Session>("/auth/login", "POST", { username }),
  destinations: () => request<string[]>("/destinations"),
  listTrips: () => request<Trip[]>("/trips"),
  getTrip: (id: string) => request<Trip>(`/trips/${id}`),
  createTrip: (input: TripInput) => request<Trip>("/trips", "POST", input),
  updateTrip: (id: string, input: TripInput, version: number) =>
    request<Trip>(`/trips/${id}`, "PUT", { ...input, version }),
  searchOptions: () => request<SearchOptions>("/search/options"),
  search: (tripId: string, input: SearchInput) => request<SearchResult>(`/trips/${tripId}/search`, "POST", input),
  itinerary: (tripId: string) => request<Itinerary>(`/trips/${tripId}/itinerary`),
  addToItinerary: (tripId: string, offerId: string, version: number) =>
    request<Itinerary>(`/trips/${tripId}/itinerary`, "POST", { offerId, version }),
  removeFromItinerary: (tripId: string, itemId: string, version: number) =>
    request<Itinerary>(`/trips/${tripId}/itinerary/${itemId}?version=${version}`, "DELETE"),
  reorderItinerary: (tripId: string, itemIds: string[], version: number) =>
    request<Itinerary>(`/trips/${tripId}/itinerary/order`, "PUT", { itemIds, version }),
  quote: (tripId: string, itemId: string) => request<Quote>(`/trips/${tripId}/itinerary/${itemId}/quote`),
  refreshItem: (tripId: string, itemId: string, version: number) =>
    request<Itinerary>(`/trips/${tripId}/itinerary/${itemId}/refresh`, "POST", { version }),
  book: (tripId: string, body: { itemId: string; intentId: string; expectedRevision: string; expectedPrice: Money }) =>
    request<BookingAttempt>(`/trips/${tripId}/bookings`, "POST", body),
  bookings: (tripId: string) => request<Bookings>(`/trips/${tripId}/bookings`),
  checkBooking: (tripId: string, attemptId: string) =>
    request<BookingAttempt>(`/trips/${tripId}/bookings/${attemptId}/check`, "POST"),
  documents: (tripId: string) => request<TripDocument[]>(`/trips/${tripId}/documents`),
  requestDocument: (tripId: string) => request<TripDocument>(`/trips/${tripId}/documents`, "POST"),
  retryDocument: (tripId: string, documentId: string) =>
    request<TripDocument>(`/trips/${tripId}/documents/${documentId}/retry`, "POST"),
  downloadDocument: (tripId: string, documentId: string) => downloadFile(`/trips/${tripId}/documents/${documentId}/download`),
  budget: (tripId: string) => request<Budget>(`/trips/${tripId}/budget`),
  searchUsers: (query: string) => request<User[]>(`/users?query=${encodeURIComponent(query)}`),
  listParticipants: (tripId: string) => request<Participant[]>(`/trips/${tripId}/participants`),
  addParticipant: (tripId: string, username: string, role: string) =>
    request<Participant>(`/trips/${tripId}/participants`, "POST", { username, role }),
  changeRole: (tripId: string, userId: string, role: string) =>
    request<Participant>(`/trips/${tripId}/participants/${userId}`, "PUT", { role }),
  removeParticipant: (tripId: string, userId: string) =>
    request<void>(`/trips/${tripId}/participants/${userId}`, "DELETE"),
};
