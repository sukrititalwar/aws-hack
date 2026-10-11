import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, CITY } from "./api";
import { useAuth } from "./auth";
import type { PlaceKind, SavedPlace } from "./types";

interface Ctx {
  places: SavedPlace[];
  loading: boolean;
  error: string;
  add: (b: { label: string; kind: PlaceKind; lat: number; lon: number; address?: string }) => Promise<void>;
  remove: (id: string) => Promise<void>;
  reload: () => void;
}
const PlacesCtx = createContext<Ctx>({ places: [], loading: false, error: "", add: async () => undefined, remove: async () => undefined, reload: () => undefined });
export const usePlaces = () => useContext(PlacesCtx);

/** Saved addresses of the signed-in user (empty and idle when signed out). */
export function PlacesProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [places, setPlaces] = useState<SavedPlace[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(() => {
    if (!user) { setPlaces([]); setError(""); return; }
    setLoading(true);
    api.places().then((r) => { setPlaces(r.places); setError(""); }).catch((e) => setError(String(e.message ?? e))).finally(() => setLoading(false));
  }, [user]);
  useEffect(reload, [reload]);

  const add: Ctx["add"] = useCallback(async (b) => {
    const r = await api.addPlace({ ...b, city: CITY });
    setPlaces((cur) => [...cur.filter((p) => !r.replaced.includes(p.placeId)), r.place]
      .sort((a, c) => ["home", "work", "other"].indexOf(a.kind) - ["home", "work", "other"].indexOf(c.kind) || a.createdAt - c.createdAt));
  }, []);
  const remove: Ctx["remove"] = useCallback(async (id) => {
    await api.deletePlace(id);
    setPlaces((cur) => cur.filter((p) => p.placeId !== id));
  }, []);

  const value = useMemo(() => ({ places, loading, error, add, remove, reload }), [places, loading, error, add, remove, reload]);
  return <PlacesCtx.Provider value={value}>{children}</PlacesCtx.Provider>;
}
