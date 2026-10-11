export type Vehicle = "pedestrian" | "bicycle" | "scooter" | "ev_scooter" | "auto" | "car" | "suv" | "bus" | "ambulance";
export type Verdict = "GO" | "RISKY" | "NO_GO";
export type LonLat = [number, number];
export type Mode = "live" | "sim";

export type Category = "passable" | "potentially_unsafe" | "unsafe" | "requires_inspection";

export interface VehicleVerdict {
  vehicle: Vehicle;
  verdict: Verdict;
  category?: Category;
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
  needs_inspection?: boolean;
  inspection_reasons?: string[];
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
  needs_inspection?: boolean;
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
  simulated?: boolean;
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
  simulated?: boolean;
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
  spots_considered?: number;
  out_of_area?: boolean;
  checked_at?: number;
  coverage?: CoverageArea[];
}
export interface CoverageArea {
  name: string;
  bbox: [number, number, number, number];
}
export type Theme = "system" | "light" | "dark";

export type PlaceKind = "home" | "work" | "other";
export interface SavedPlace {
  placeId: string;
  label: string;
  kind: PlaceKind;
  address?: string;
  lat: number;
  lon: number;
  city?: string;
  createdAt: number;
}

export interface DrainRow {
  groupId: string;
  city: string;
  status: "open" | "assigned" | "cleared" | "analysing" | "rejected" | "error";
  lat: number;
  lon: number;
  severity: "partial" | "blocked" | null;
  /** How the photo was assessed: full AI, basic image labels (fallback), or nobody yet. */
  analysisMode?: "bedrock" | "rekognition_labels" | "manual";
  analysisError?: string | null;
  needsReview?: boolean;
  awaitingReview?: boolean;
  clearedBy?: "ai" | "manual" | null;
  blockage_type?: string | null;
  note?: string | null;
  firstReported: number;
  assignedTo?: string | null;
  clearedAt?: number | null;
  reportIds?: string[];
  reportCount: number;
  score: number;
  reasons: string[];
  urgent: boolean;
  rainNext24h: number;
  nearHotspot?: string | null;
  // detail only
  reasoning?: string;
  reasoning_hi?: string;
  rejection_reason?: string;
  photoUrl?: string;
  afterUrl?: string;
  afterNote?: string;
  clearanceVerified?: boolean;
}

export interface DrainMetrics {
  reported: number;
  open: number;
  assigned: number;
  cleared: number;
  cleared_ai_verified?: number;
  cleared_manual?: number;
  median_hours_to_clear: number | null;
  rain_forecast_cases: number;
  cleared_before_rain: number;
  repeat_blockages: number;
  basis: string;
}

export type RainLevel = "dry" | "light" | "moderate" | "heavy" | "extreme";
export interface RainCity {
  key: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  now: number;      // mm/h right now
  past3h: number;   // mm
  next6h: number;   // mm (forecast)
  level: RainLevel;
  supported: boolean;   // a fully live city in this app (road graph, hotspots, social ingest)
}
export interface RainIndia {
  updatedAt: number;
  cities: RainCity[];
  summary: { counts: Record<string, number>; raining: number; checked: number; headline: string; wettest: string[] };
  source: string;
}
export interface LivePost {
  id: string;
  text: string;
  ts: number;
  url: string | null;
  source: string;
  author: string;
  author_type: string;
  place?: string | null;
  simulated?: boolean;
}
export interface LivePosts {
  city: string;
  label: string;
  hours: number;
  posts: LivePost[];
  sources_checked: Record<string, number | string>;
  checkedAt: number;
}

/** The DEMO storm: every value is made up (see backend/common/simulation.py). */
export interface SimPayload {
  simulation: true;
  disclaimer: string;
  scenario: { city: string; area: string; start: number; end: number; name: string };
  now: number;
  spots: Spot[];
  weather: Weather;
  posts: LivePost[];
  drains: { groupId: string; note?: string; severity: string; status: string; reportCount: number; score: number; reasons: string[]; assignedTo?: string | null }[];
}
