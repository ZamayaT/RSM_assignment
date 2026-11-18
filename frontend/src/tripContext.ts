import { createContext, useContext } from "react";

// Shared by the trip workspace and its sections: a section calls refresh() after a write so the
// general-info card (totals, counters, role) is never stale.
export interface TripWorkspaceValue {
  refresh: () => void;
}

export const TripWorkspaceContext = createContext<TripWorkspaceValue>({ refresh: () => undefined });

export const useTripWorkspace = (): TripWorkspaceValue => useContext(TripWorkspaceContext);
