// Backend URL comes from configuration (VITE_BACKEND_URL), never hardcoded in components.
export const BACKEND_URL: string =
  import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8000";
