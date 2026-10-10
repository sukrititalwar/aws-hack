import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { mapStyle } from "../api";
import { VERDICT_UI, vehicleInfo, type Lang } from "../i18n";
import type { Hotspot, LonLat, RouteResult, Spot, Vehicle } from "../types";

interface Props {
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
  onSpot: (s: Spot) => void;
  onHotspot: (h: Hotspot) => void;
  onPick: (p: LonLat) => void;
  onReady?: (m: maplibregl.Map) => void;
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

// Lucide paths (check, x, cloud-rain, shield, message-circle) as strings, because markers are plain DOM.
const svg = (body: string, size = 16) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const PIN_GLYPH: Record<string, string> = {
  go: svg('<path d="M20 6 9 17l-5-5"/>'),
  nogo: svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
  risky: "!",
  inspect: "?",
};
const BADGE = {
  rain: svg('<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M16 14v6"/><path d="M8 14v6"/><path d="M12 16v6"/>', 11),
  official: svg('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>', 11),
  social: svg('<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>', 11),
};
const dark = () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

export default function MapView(p: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const spotMarkers = useRef<maplibregl.Marker[]>([]);
  const hotMarkers = useRef<maplibregl.Marker[]>([]);
  const pinMarkers = useRef<maplibregl.Marker[]>([]);
  const cb = useRef(p);
  cb.current = p;

  // ---- init once ----
  useEffect(() => {
    const m = new maplibregl.Map({
      container: el.current!,
      style: mapStyle(dark()),
      center: p.center,
      zoom: 13.5,
      attributionControl: { compact: true },
    });
    if (typeof mapStyle(false) !== "string" && dark()) el.current!.classList.add("osm-dark");
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    m.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: true }), "bottom-right");
    m.on("load", () => {
      m.addSource("route-normal", { type: "geojson", data: EMPTY });
      m.addSource("route-safe", { type: "geojson", data: EMPTY });
      m.addSource("route-alt", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "route-normal", type: "line", source: "route-normal",
        paint: { "line-color": "#94a3b8", "line-width": 5, "line-dasharray": [1.5, 1.2], "line-opacity": 0.9 },
        layout: { "line-cap": "round" } });
      m.addLayer({ id: "route-safe-casing", type: "line", source: "route-safe",
        paint: { "line-color": "#ffffff", "line-width": 9 }, layout: { "line-cap": "round", "line-join": "round" } });
      m.addLayer({ id: "route-safe", type: "line", source: "route-safe",
        paint: { "line-color": "#2563eb", "line-width": 6 }, layout: { "line-cap": "round", "line-join": "round" } });
      m.addLayer({ id: "route-alt", type: "line", source: "route-alt",
        paint: { "line-color": "#16a34a", "line-width": 5, "line-dasharray": [2, 1] }, layout: { "line-cap": "round" } });
      cb.current.onReady?.(m);
      drawRoute();
      drawAlt();
    });
    m.on("click", (e) => {
      if (cb.current.picking) cb.current.onPick([e.lngLat.lng, e.lngLat.lat]);
    });
    map.current = m;
    return () => m.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- spot pins: colour + glyph + label, recoloured for the selected vehicle ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    spotMarkers.current.forEach((x) => x.remove());
    spotMarkers.current = p.spots.map((s) => {
      const v = s.verdicts[p.vehicle];
      // A GO we are not sure about is drawn as "?" (requires inspection), never as a green tick.
      const unsure = v === "GO" && !!s.needs_inspection;
      const ui = unsure ? { cls: "risky", glyph: "?", en: "Requires inspection", hi: "" } : VERDICT_UI[v];
      const size = Math.min(30 + (s.reportCount - 1) * 6, 54);
      const btn = document.createElement("button");
      btn.className = `pin ${ui.cls}${s.faded ? " faded" : ""}${s.danger ? " danger" : ""}${s.predicted ? " predicted" : ""}`;
      btn.style.width = btn.style.height = `${size}px`;
      const badge = s.predicted ? BADGE.rain : s.sources.includes("official") ? BADGE.official : s.sources.includes("social") ? BADGE.social : "";
      btn.innerHTML = `<span>${unsure ? PIN_GLYPH.inspect : PIN_GLYPH[ui.cls]}</span>${s.reportCount > 1 ? `<b>${s.reportCount}</b>` : ""}${badge ? `<i>${badge}</i>` : ""}`;
      const veh = vehicleInfo(p.vehicle);
      btn.setAttribute("aria-label", `${s.place ?? "Flooded spot"}: ${s.predicted ? "predicted from rain, " : ""}about ${s.depth_high} cm. ${veh.en}: ${ui.en}.`);
      btn.onclick = (e) => {
        e.stopPropagation();
        cb.current.onSpot(s);
      };
      return new maplibregl.Marker({ element: btn }).setLngLat([s.lon, s.lat]).addTo(m);
    });
  }, [p.spots, p.vehicle]);

  // ---- chronic hotspots: hollow rings ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    hotMarkers.current.forEach((x) => x.remove());
    hotMarkers.current = p.hotspots.map((h) => {
      const d = document.createElement("button");
      d.className = `ring${h.risk === "likely_flooded_soon" ? " soon" : h.risk === "flooding_likely_now" ? " now" : ""}`;
      d.setAttribute("aria-label", `${h.name}: usually floods in heavy rain${h.risk !== "normal" ? " (rain warning)" : ""}`);
      d.title = p.lang === "hi" ? h.name_hi ?? h.name : h.name;
      d.onclick = (e) => {
        e.stopPropagation();
        cb.current.onHotspot(h);
      };
      return new maplibregl.Marker({ element: d }).setLngLat([h.lon, h.lat]).addTo(m);
    });
  }, [p.hotspots, p.lang]);

  // ---- from/to pins ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    pinMarkers.current.forEach((x) => x.remove());
    pinMarkers.current = [];
    ([["from", p.from], ["to", p.to]] as const).forEach(([kind, pos]) => {
      if (!pos) return;
      const d = document.createElement("div");
      d.className = `endpoint ${kind}`;
      d.textContent = kind === "from" ? "A" : "B";
      pinMarkers.current.push(new maplibregl.Marker({ element: d }).setLngLat(pos).addTo(m));
    });
  }, [p.from, p.to]);

  // ---- routes ----
  function drawRoute() {
    const m = map.current;
    if (!m || !m.getSource("route-safe")) return;
    const r = cb.current.route;
    const feat = (g?: GeoJSON.LineString | null): GeoJSON.FeatureCollection =>
      g ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: g }] } : EMPTY;
    const sameAsNormal = r?.safe && r?.normal && r.safe.distance_m === r.normal.distance_m;
    (m.getSource("route-normal") as maplibregl.GeoJSONSource).setData(feat(sameAsNormal ? null : r?.normal?.geometry));
    (m.getSource("route-safe") as maplibregl.GeoJSONSource).setData(feat(r?.safe?.geometry));
    const g = r?.safe?.geometry ?? r?.normal?.geometry;
    if (g && g.coordinates.length > 1) {
      const b = new maplibregl.LngLatBounds();
      g.coordinates.forEach((c) => b.extend(c as LonLat));
      r?.normal?.geometry.coordinates.forEach((c) => b.extend(c as LonLat));
      // Keep the route clear of the toolbar and of the panel (side panel on desktop, bottom sheet on phones).
      const wide = window.innerWidth >= 760;
      m.fitBounds(b, { padding: { top: 130, bottom: wide ? 40 : Math.round(window.innerHeight * 0.6) + 20, left: 40, right: wide ? 440 : 40 }, duration: 700 });
    }
  }
  useEffect(drawRoute, [p.route]);

  function drawAlt() {
    const m = map.current;
    const src = m?.getSource("route-alt") as maplibregl.GeoJSONSource | undefined;
    const g = cb.current.altRoute;
    src?.setData(g ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: g }] } : EMPTY);
  }
  useEffect(drawAlt, [p.altRoute]);

  // Re-centre when the city changes.
  useEffect(() => {
    map.current?.jumpTo({ center: p.center, zoom: 13 });
  }, [p.center[0], p.center[1]]);

  useEffect(() => {
    map.current?.getCanvas().style.setProperty("cursor", p.picking ? "crosshair" : "");
  }, [p.picking]);

  return <div ref={el} className="map" />;
}
