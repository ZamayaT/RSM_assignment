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

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
    public latest?: Trip,
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

  if (response.ok) return (await response.json()) as T;

  let data: { code?: string; message?: string; details?: { fields?: Record<string, string>; latest?: Trip } } = {};
  try {
    data = await response.json();
  } catch {
    // Non-JSON error body: fall back to the generic message below.
  }
  if (response.status === 401) unauthorizedHandler?.();
  throw new ApiError(
    response.status,
    data.code ?? "ERROR",
    data.message ?? `Request failed (${response.status}).`,
    data.details?.fields,
    data.details?.latest,
  );
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
};
