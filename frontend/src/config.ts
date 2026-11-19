// Backend URL comes from configuration (VITE_BACKEND_URL), never hardcoded in components.
export const BACKEND_URL: string =
  import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8000";

// The assistant's "Tools used" list is shown unless VITE_SHOW_ASSISTANT_TOOLS=false.
export const SHOW_ASSISTANT_TOOLS: boolean = import.meta.env.VITE_SHOW_ASSISTANT_TOOLS !== "false";
