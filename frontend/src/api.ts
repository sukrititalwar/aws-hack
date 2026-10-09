import type { StyleSpecification } from "maplibre-gl";
import type { BusImpact, Hotspot, LonLat, Mode, Report, RouteResult, Spot, Vehicle, Weather } from "./types";

export const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
export const CITIES: Record<string, { label: string; hi: string; center: LonLat }> = {
  delhi: { label: "Delhi", hi: "दिल्ली", center: [77.232, 28.61] },
  gurugram: { label: "Gurugram", hi: "गुरुग्राम", center: [77.05, 28.46] },
  kochi: { label: "Kochi", hi: "कोच्चि", center: [76.29, 9.98] },
  mumbai: { label: "Mumbai", hi: "मुंबई", center: [72.8475, 19.105] },
};
/** Current city; App calls setCity() when the user switches. */
export let CITY = (import.meta.env.VITE_CITY as string | undefined) ?? "delhi";
export function setCity(c: string) {
  CITY = c;
}
export const WHATSAPP_NUMBER = (import.meta.env.VITE_WHATSAPP_NUMBER as string | undefined) ?? "";
export const WHATSAPP_JOIN = (import.meta.env.VITE_WHATSAPP_JOIN as string | undefined) ?? "";

async function call<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  if (!API) throw new Error("VITE_API_URL is not set. Copy frontend/.env.example to .env.local.");
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), init?.timeoutMs ?? 20000);
  try {
    const r = await fetch(API + path, {
      ...init,
      signal: ctrl.signal,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
    return data as T;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  uploadUrl: (b: { lat: number; lon: number; place?: string; deviceId: string; exifTime?: number }) =>
    call<{ reportId: string; uploadUrl: string; fields: Record<string, string> }>("/reports/upload-url", {
      method: "POST",
      body: JSON.stringify({ ...b, city: CITY }),
    }),

  /** Presigned POST straight to S3. */
  async uploadPhoto(url: string, fields: Record<string, string>, blob: Blob) {
    const fd = new FormData();
    Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
    fd.append("file", blob, "photo.jpg"); // file must be the last field
    const r = await fetch(url, { method: "POST", body: fd });
    if (!r.ok) throw new Error(`Upload failed (${r.status})`);
  },

  report: (id: string) => call<Report>(`/reports/${id}`),

  spots: (mode: Mode, at?: number) =>
    call<{ spots: Spot[]; now: number }>(`/spots?city=${CITY}&mode=${mode}${at ? `&at=${Math.round(at)}` : ""}`),

  hotspots: () => call<{ hotspots: Hotspot[]; weather: Weather | null }>(`/hotspots?city=${CITY}`),

  busImpact: (mode: Mode, at?: number) =>
    call<BusImpact>(`/bus-impact?city=${CITY}&mode=${mode}${at ? `&at=${Math.round(at)}` : ""}`),

  timeline: () => call<{ start: number | null; end: number | null; reports: Report[] }>(`/demo/timeline?city=${CITY}`),

  vote: (id: string, type: "still_flooded" | "cleared" | "wrong", deviceId: string) =>
    call<{ votes: Report["votes"] }>(`/reports/${id}/vote`, { method: "POST", body: JSON.stringify({ type, deviceId }) }),

  route: (from: LonLat, to: LonLat, vehicle: Vehicle, mode: Mode, at?: number) =>
    call<RouteResult>("/route", {
      method: "POST",
      body: JSON.stringify({ from, to, vehicle, city: CITY, mode, compare: true, at: mode === "demo" ? Math.round(at ?? 0) : undefined }),
      timeoutMs: 15000,
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
  if (!LOC_KEY) return [];
  const r = await fetch(`https://places.geo.${LOC_REGION}.amazonaws.com/v2/geocode?key=${LOC_KEY}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ QueryText: text, BiasPosition: bias, MaxResults: 5, Filter: { IncludeCountries: ["IND"] } }),
  });
  if (!r.ok) return [];
  const data = await r.json();
  return (data.ResultItems ?? []).map((i: { Title: string; Position: LonLat }) => ({ title: i.Title, pos: i.Position }));
}
