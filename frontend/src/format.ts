// Timestamps are shown as the provider sent them (with their offset); the UI never judges expiry itself.
export const stamp = (iso: string | null): string =>
  iso === null ? "—" : iso.replace("T", " ").replace(/\.\d+/, "").replace(/Z$/, " UTC");
