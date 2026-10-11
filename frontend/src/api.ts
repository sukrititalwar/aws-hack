import type { StyleSpecification } from "maplibre-gl";
import type { BusImpact, DrainMetrics, DrainRow, Hotspot, LivePosts, LonLat, Mode, PlaceKind, PredictiveRouteResult, RainIndia, Report, RouteResult, SavedPlace, SimPayload, Spot, Vehicle, Weather } from "./types";

const API_ENV = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
// Opened from a phone on the same Wi-Fi (http://<laptop-ip>:5173)? "localhost" would mean the phone itself, so use the page's host.
export const API = API_ENV.replace(/^(https?:\/\/)(localhost|127\.0\.0\.1)(?=[:/]|$)/, (m, scheme, host) =>
  typeof location !== "undefined" && location.hostname !== host && !/^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? `${scheme}${location.hostname}` : m);
export const PREDICTIVE_ROUTE_ENABLED =
  (import.meta.env.VITE_PREDICTIVE_ROUTE_ENABLED as string | undefined) === "true";
export const CITIES: Record<string, { label: string; hi: string; center: LonLat }> = {
  delhi: { label: "Delhi", hi: "दिल्ली", center: [77.232, 28.61] },
  gurugram: { label: "Gurugram", hi: "गुरुग्राम", center: [77.05, 28.46] },
  kochi: { label: "Kochi", hi: "कोच्चि", center: [76.29, 9.98] },
  thiruvananthapuram: { label: "Thiruvananthapuram", hi: "तिरुवनंतपुरम", center: [76.95, 8.5] },
  mumbai: { label: "Mumbai", hi: "मुंबई", center: [72.8475, 19.105] },
};
/** Current city; App calls setCity() when the user switches. */
export let CITY = (import.meta.env.VITE_CITY as string | undefined) ?? "delhi";
export function setCity(c: string) {
  CITY = c;
}
export const WHATSAPP_NUMBER = (import.meta.env.VITE_WHATSAPP_NUMBER as string | undefined) ?? "";
export const WHATSAPP_JOIN = (import.meta.env.VITE_WHATSAPP_JOIN as string | undefined) ?? "";

/** Set by auth.ts: returns a fresh ID token (refreshing it if needed) or null when signed out. */
let tokenProvider: (() => Promise<string | null>) | null = null;
export function setTokenProvider(fn: (() => Promise<string | null>) | null) {
  tokenProvider = fn;
}

async function call<T>(path: string, init?: RequestInit & { timeoutMs?: number; auth?: boolean }): Promise<T> {
  if (!API) throw new Error("VITE_API_URL is not set. Copy frontend/.env.example to .env.local.");
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), init?.timeoutMs ?? 20000);
  try {
    const extra: Record<string, string> = {};
    if (init?.auth) {
      const tok = tokenProvider ? await tokenProvider() : null;
      if (!tok) throw new Error("Please sign in first.");
      extra.Authorization = `Bearer ${tok}`;
    }
    const r = await fetch(API + path, {
      ...init,
      signal: ctrl.signal,
      headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...extra, ...(init?.headers as Record<string, string> | undefined) },
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || data.message || `Request failed (${r.status})`);
    return data as T;
  } catch (e) {
    // Say what actually went wrong instead of a bare "Failed to fetch" / "aborted".
    if (e instanceof DOMException && e.name === "AbortError") throw new Error("The server took too long to answer. Please try again.");
    if (e instanceof TypeError) throw new Error("Can't reach the server. Check your connection and try again.");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

const sleepMs = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const api = {
  uploadUrl: (b: { lat: number; lon: number; place?: string; deviceId: string; exifTime?: number }) =>
    call<{ reportId: string; uploadUrl: string; fields: Record<string, string> }>("/reports/upload-url", {
      method: "POST",
      body: JSON.stringify({ ...b, city: CITY }),
    }),

  /** Presigned POST straight to S3, retried on network errors and 5xx (3 attempts). */
  async uploadPhoto(url: string, fields: Record<string, string>, blob: Blob) {
    let last = "";
    for (let attempt = 0; attempt < 3; attempt++) {
      if (attempt) await sleepMs(attempt * 1500);
      try {
        const fd = new FormData();
        Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
        fd.append("file", blob, "photo.jpg"); // file must be the last field
        const r = await fetch(url, { method: "POST", body: fd });
        if (r.ok) return;
        const xml = await r.text().catch(() => "");
        const code = /<Code>([^<]+)<\/Code>/.exec(xml)?.[1];
        last = `Upload failed (${r.status}${code ? " " + code : ""})`;
        if (r.status < 500) break; // 4xx: retrying will not help (expired link, too large, wrong type)
      } catch {
        last = "Upload failed: no connection";
      }
    }
    throw new Error(last + ". Please try again.");
  },

  report: (id: string) => call<Report>(`/reports/${id}`),

  // ---- DrainReady ----
  drainUploadUrl: (b: { lat: number; lon: number; note?: string; deviceId: string }) =>
    call<{ reportId: string; uploadUrl: string; fields: Record<string, string> }>("/drains/upload-url", {
      method: "POST", body: JSON.stringify({ ...b, city: CITY }) }),
  drains: (all = false) => call<{ drains: DrainRow[] }>(`/drains?city=${CITY}${all ? "&status=all" : ""}`),
  drain: (id: string) => call<DrainRow>(`/drains/${id}`),
  drainMetrics: () => call<DrainMetrics>(`/drains/metrics?city=${CITY}`),
  // ---- signed-in user: saved addresses ----
  places: () => call<{ places: SavedPlace[] }>("/me/places", { auth: true }),
  addPlace: (b: { label: string; kind: PlaceKind; lat: number; lon: number; address?: string; city?: string }) =>
    call<{ place: SavedPlace; replaced: string[] }>("/me/places", { method: "POST", body: JSON.stringify(b), auth: true }),
  deletePlace: (id: string) => call<{ ok: boolean }>(`/me/places/${id}`, { method: "DELETE", auth: true }),

  retryDrain: (id: string, deviceId: string) =>
    call<{ ok: boolean }>(`/drains/${id}/retry`, { method: "POST", body: JSON.stringify({ deviceId }) }),
  confirmDrain: (id: string, decision: "clear" | "reject", token: string, note?: string) =>
    call<{ ok: boolean }>(`/drains/${id}/confirm`, { method: "POST", body: JSON.stringify({ decision, note }), headers: { "x-admin-token": token } }),
  assignDrain: (id: string, worker: string, token: string) =>
    call<{ ok: boolean }>(`/drains/${id}/assign`, { method: "POST", body: JSON.stringify({ worker }), headers: { "x-admin-token": token } }),
  afterUrl: (id: string, token: string) =>
    call<{ uploadUrl: string; fields: Record<string, string> }>(`/drains/${id}/after-url`, { method: "POST", body: "{}", headers: { "x-admin-token": token } }),

  spots: (mode: Mode, at?: number) =>
    call<{ spots: Spot[]; now: number }>(`/spots?city=${CITY}&mode=${mode}${at ? `&at=${Math.round(at)}` : ""}`),

  /** Live rainfall at ~50 Indian cities (Open-Meteo, cached 5 min server-side). */
  rainIndia: () => call<RainIndia>("/rain/india", { timeoutMs: 25000 }),
  /** Recent public posts and news about rain / waterlogging in a city (any city in the India list). */
  rainPosts: (city: string) => call<LivePosts>(`/rain/india/posts?city=${city}`, { timeoutMs: 30000 }),


  /** DEMO storm snapshot at time `at` (made-up values, never real reports). */
  simulation: (at?: number) => call<SimPayload>(`/simulation${at ? `?at=${Math.round(at)}` : ""}`),

  hotspots: () => call<{ hotspots: Hotspot[]; weather: Weather | null }>(`/hotspots?city=${CITY}`),

  busImpact: (mode: Mode, at?: number) =>
    call<BusImpact>(`/bus-impact?city=${CITY}&mode=${mode}${at ? `&at=${Math.round(at)}` : ""}`),


  vote: (id: string, type: "still_flooded" | "cleared" | "wrong", deviceId: string) =>
    call<{ votes: Report["votes"] }>(`/reports/${id}/vote`, { method: "POST", body: JSON.stringify({ type, deviceId }) }),

  route: (from: LonLat, to: LonLat, vehicle: Vehicle, mode: Mode, at?: number) =>
    call<RouteResult>("/route", {
      method: "POST",
      body: JSON.stringify({ from, to, vehicle, city: CITY, mode, compare: true, at: mode !== "live" ? Math.round(at ?? 0) : undefined }),
      timeoutMs: 15000,
    }),

  predictiveRoute: (from: LonLat, to: LonLat, vehicle: Vehicle) =>
    call<PredictiveRouteResult>("/predictive-route", {
      method: "POST",
      body: JSON.stringify({ from, to, vehicle, city: CITY, mode: "live" }),
      timeoutMs: 25000,
    }),

  subscribe: (b: { contact: string; vehicle: Vehicle; name: string; route: { type: "LineString"; coordinates: LonLat[] } }) =>
    call<{ subId: string; note: string }>("/subscriptions", { method: "POST", body: JSON.stringify(b) }),
};

/* ---------- Amazon Location Service ---------- */
const LOC_KEY = import.meta.env.VITE_LOCATION_API_KEY as string | undefined;
const LOC_REGION = (import.meta.env.VITE_LOCATION_REGION as string | undefined) ?? "ap-south-1";
export const hasLocationKey = !!LOC_KEY;

export function mapStyle(dark: boolean): string | StyleSpecification {
  if (LOC_KEY) {
    return `https://maps.geo.${LOC_REGION}.amazonaws.com/v2/styles/Standard/descriptor?key=${LOC_KEY}&color-scheme=${dark ? "Dark" : "Light"}`;
  }
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution: "© OpenStreetMap contributors",
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  };
}

/** Amazon Location Places v2 geocode, biased to a position. */
export async function geocode(text: string, bias: LonLat): Promise<{ title: string; pos: LonLat }[]> {
  if (!LOC_KEY) return nominatim(text, bias);
  const r = await fetch(`https://places.geo.${LOC_REGION}.amazonaws.com/v2/geocode?key=${LOC_KEY}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ QueryText: text, BiasPosition: bias, MaxResults: 5, Filter: { IncludeCountries: ["IND"] } }),
  });
  if (!r.ok) return [];
  const data = await r.json();
  return (data.ResultItems ?? []).map((i: { Title: string; Position: LonLat }) => ({ title: i.Title, pos: i.Position }));
}

/** Free place search (OpenStreetMap Nominatim) used when no Amazon Location key is set. Light use only: callers debounce. */
async function nominatim(text: string, bias: LonLat): Promise<{ title: string; pos: LonLat }[]> {
  const d = 0.6;
  const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&countrycodes=in&q=${encodeURIComponent(text)}`
    + `&viewbox=${bias[0] - d},${bias[1] + d},${bias[0] + d},${bias[1] - d}`;
  try {
    const r = await fetch(url, { headers: { "Accept-Language": "en" } });
    if (!r.ok) return [];
    const rows = (await r.json()) as { display_name: string; lon: string; lat: string }[];
    return rows.map((i) => ({ title: i.display_name, pos: [Number(i.lon), Number(i.lat)] as LonLat }));
  } catch {
    return [];
  }
}
