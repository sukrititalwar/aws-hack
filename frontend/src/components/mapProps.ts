import type { Lang } from "../i18n";
import type { CoverageArea, Hotspot, LonLat, RainCity, RouteResult, Spot, Vehicle } from "../types";
import type { UserLocation } from "../util";

/** What every map engine (MapLibre / Google Maps) receives from the app. */
export interface MapProps {
  center: LonLat;
  spots: Spot[];
  hotspots: Hotspot[];
  vehicle: Vehicle;
  lang: Lang;
  route: RouteResult | null;
  altRoute?: GeoJSON.LineString | null;
  from?: LonLat | null;
  to?: LonLat | null;
  picking: boolean;
  dark: boolean;
  coverage?: CoverageArea[] | null;
  onSpot: (s: Spot) => void;
  onHotspot: (h: Hotspot) => void;
  onPick: (p: LonLat) => void;
  /** Cities to draw as rain dots (the "where is it raining" view). */
  rainPoints?: RainCity[] | null;
  onRainPoint?: (c: RainCity) => void;
  /** [west, south, east, north] to fit (e.g. all of India). Back to null = return to the city view. */
  viewBounds?: [number, number, number, number] | null;
  /** Real-time device location from GPS. */
  userLocation?: UserLocation | null;
  /** Whether the map camera should auto-follow the user's live position (Google Maps navigation mode). */
  followUser?: boolean;
}
