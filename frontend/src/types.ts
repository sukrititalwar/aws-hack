export type Vehicle = "pedestrian" | "bicycle" | "scooter" | "auto" | "car" | "suv" | "bus" | "ambulance";
export type Verdict = "GO" | "RISKY" | "NO_GO";
export type LonLat = [number, number];
export type Mode = "live" | "demo";

export interface VehicleVerdict {
  vehicle: Vehicle;
  verdict: Verdict;
  label_en: string;
  label_hi: string;
  why: string;
  why_hi: string;
}

export interface Report {
  reportId: string;
  city: string;
  mode: Mode;
  lat: number;
  lon: number;
  place?: string;
  status: "analysing" | "live" | "rejected" | "stale" | "cleared" | "error";
  rejection_reason?: string;
  createdAt: number;
  ts: number;
  depth_low?: number;
  depth_high?: number;
  confidence?: "low" | "medium" | "high";
  image_quality?: string;
  flowing_water?: boolean;
  hazards?: string[];
  danger?: boolean;
  reasoning?: string;
  reasoning_hi?: string;
  reference_objects?: { object: string; observation: string; implied_depth_cm: number }[];
  location_type?: string;
  verdicts?: Record<Vehicle, VehicleVerdict>;
  votes?: { still?: number; cleared?: number; wrong?: number };
  photoUrl?: string;
  source_type?: string;
  source_url?: string;
  source_label?: string;
  source_platform?: string;
  closure?: boolean;
}

export interface Spot {
  spotId: string;
  lat: number;
  lon: number;
  place?: string | null;
  depth_low: number;
  depth_high: number;
  confidence: string;
  hazards: string[];
  danger: boolean;
  verdicts: Record<Vehicle, Verdict>;
  reportCount: number;
  reportIds: string[];
  sources: string[];
  firstReported: number;
  lastUpdated: number;
  ageMin: number;
  faded: boolean;
  status: string;
  predicted?: boolean;
  rainPast3h?: number;
  rainNow?: number;
  source_url?: string;
  source_urls?: string[];
  verification?: "predicted" | "single_report" | "confirmed" | "official";
}

export interface Hotspot {
  hotspotId: string;
  name: string;
  name_hi?: string;
  lat: number;
  lon: number;
  kind: string;
  risk: "normal" | "likely_flooded_soon" | "flooding_likely_now";
  rainPast3h?: number;
  rainNow?: number;
  rainNext3h?: number;
  source_url?: string;
  osm_match?: string;
  verified?: boolean;
}

export interface Weather {
  rainNow: number;
  rainPast3h: number;
  rainNext3h: number;
  maxRainNowAtHotspots: number;
  hotspotsAtRisk: number;
  updatedAt: number;
  source: string;
}

export interface CompareRow {
  vehicle: Vehicle;
  status: "usual" | "usual_with_care" | "detour" | "stuck";
  usual_km: number;
  usual_min: number;
  safe_km: number | null;
  safe_min: number | null;
  extra_min: number;
  blocking: string[];
  risky: string[];
  note: string;
  geometry: { type: "LineString"; coordinates: LonLat[] } | null;
}

export interface BusImpact {
  routes_known: number;
  affected: { ref: string; name: string; operator: string; worst: Verdict;
    spots: { spotId: string; place?: string; depth_high: number; bus: Verdict; pedestrian: Verdict; predicted: boolean }[] }[];
}

export interface RouteLeg {
  geometry: { type: "LineString"; coordinates: LonLat[] };
  distance_m: number;
  duration_min: number;
  spots_on_route: { spotId: string; verdict: Verdict; place?: string; depth_high: number; lon: number; lat: number }[];
}

export interface RouteResult {
  vehicle: Vehicle;
  normal: RouteLeg | null;
  safe: RouteLeg | null;
  avoided_spots: RouteLeg["spots_on_route"];
  extra_min: number;
  note: string;
  snap_m: [number, number];
  compare?: CompareRow[];
}
