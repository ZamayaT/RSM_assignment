// Timestamps are shown as the provider sent them (with their offset); the UI never judges expiry itself.
export const stamp = (iso: string | null): string =>
  iso === null ? "—" : iso.replace("T", " ").replace(/\.\d+/, "").replace(/Z$/, " UTC");

// "supplier-alamo" is shown as "Supplier Alamo" (the provider only sends the identifier).
export const supplierName = (id: string): string =>
  id.split("-").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");

// Item status labels (what the itinerary and the budget show next to each item).
export const STATUS_LABELS: Record<string, { label: string; color: "default" | "info" | "success" | "warning" | "error" }> = {
  estimate: { label: "Estimate", color: "default" },
  expired_quote: { label: "Expired quote", color: "warning" },
  booking_pending: { label: "Booking pending", color: "info" },
  confirmed: { label: "Confirmed", color: "success" },
  failed: { label: "Failed", color: "error" },
  unknown: { label: "Unknown outcome", color: "warning" },
};

// Restrictions as the provider states them; an empty list is shown as such, never as "no restrictions apply".
export const restrictionsText = (restrictions: string[]): string =>
  restrictions.length === 0 ? "None stated by the provider" : restrictions.join("; ");

// An item with one of these statuses has a booking that blocks removing or re-pricing it.
export const LIVE_ITEM_STATUSES = ["booking_pending", "unknown", "confirmed"];

// A booking attempt whose outcome can still change on its own (pages keep refreshing it).
export const isLiveAttempt = (a: { status: string; unresolved: boolean }): boolean =>
  a.status === "initiated" || a.status === "pending" || (a.status === "unknown" && !a.unresolved);

// A document that the worker has not finished yet (pages keep refreshing it).
export const isLiveDocument = (d: { status: string }): boolean => d.status === "waiting" || d.status === "in_progress";

// A random id for one booking decision. Falls back when crypto.randomUUID is unavailable (non-secure context).
export function newIntentId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 3) | 8).toString(16);
  });
}
