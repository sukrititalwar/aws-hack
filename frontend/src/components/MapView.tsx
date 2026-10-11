import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { mapStyle } from "../api";
import type { MapProps } from "./mapProps";
import { endpointElement, hotspotElement, rainElement, spotElement, userLocationElement } from "./markers";
import type { LonLat } from "../types";

interface Props extends MapProps {
  onReady?: (m: maplibregl.Map) => void;
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export default function MapView(p: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const spotMarkers = useRef<maplibregl.Marker[]>([]);
  const hotMarkers = useRef<maplibregl.Marker[]>([]);
  const pinMarkers = useRef<maplibregl.Marker[]>([]);
  const rainMarkers = useRef<maplibregl.Marker[]>([]);
  const userMarker = useRef<maplibregl.Marker | null>(null);
  const hadBounds = useRef(false);
  const cb = useRef(p);
  cb.current = p;

  // ---- init once ----
  useEffect(() => {
    const m = new maplibregl.Map({
      container: el.current!,
      style: mapStyle(p.dark),
      center: p.center,
      zoom: 13.5,
      attributionControl: { compact: true },
    });

    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    m.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: true }), "bottom-right");
    // Runs on the first load and again after every theme switch (setStyle drops our layers).
    m.on("style.load", () => {
      if (m.getSource("route-normal")) return;
      m.addSource("coverage", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "coverage-fill", type: "fill", source: "coverage", paint: { "fill-color": "#2563eb", "fill-opacity": 0.07 } });
      m.addLayer({ id: "coverage-line", type: "line", source: "coverage",
        paint: { "line-color": "#2563eb", "line-width": 2, "line-dasharray": [2, 2] } });
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
      drawRoute(false);
      drawAlt();
      drawCoverage(false);
    });
    m.once("load", () => cb.current.onReady?.(m));
    m.on("click", (e) => {
      if (cb.current.picking) cb.current.onPick([e.lngLat.lng, e.lngLat.lat]);
    });
    map.current = m;
    return () => { userMarker.current?.remove(); m.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- spot pins: colour + glyph + label, recoloured for the selected vehicle ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    spotMarkers.current.forEach((x) => x.remove());
    spotMarkers.current = p.spots.map((s) =>
      new maplibregl.Marker({ element: spotElement(s, p.vehicle, (x) => cb.current.onSpot(x)) }).setLngLat([s.lon, s.lat]).addTo(m));
  }, [p.spots, p.vehicle]);

  // ---- chronic hotspots: hollow rings ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    hotMarkers.current.forEach((x) => x.remove());
    hotMarkers.current = p.hotspots.map((h) =>
      new maplibregl.Marker({ element: hotspotElement(h, p.lang, (x) => cb.current.onHotspot(x)) }).setLngLat([h.lon, h.lat]).addTo(m));
  }, [p.hotspots, p.lang]);

  // ---- rain dots + "show all of India" view ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    rainMarkers.current.forEach((x) => x.remove());
    rainMarkers.current = (p.rainPoints ?? []).map((c) =>
      new maplibregl.Marker({ element: rainElement(c, (x) => cb.current.onRainPoint?.(x)) }).setLngLat([c.lon, c.lat]).addTo(m));
  }, [p.rainPoints]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    if (p.viewBounds) {
      const [w, s, e, n] = p.viewBounds;
      const wide = window.innerWidth >= 760;
      m.fitBounds([[w, s], [e, n]], { padding: { top: 130, bottom: wide ? 40 : Math.round(window.innerHeight * 0.5) + 10, left: 20, right: wide ? 440 : 20 }, duration: 700, maxZoom: 6 });
      hadBounds.current = true;
    } else if (hadBounds.current) {
      hadBounds.current = false;
      m.flyTo({ center: cb.current.center, zoom: 13, duration: 700 });
    }
  }, [p.viewBounds]);

  // ---- from/to pins ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    pinMarkers.current.forEach((x) => x.remove());
    pinMarkers.current = [];
    ([["from", p.from], ["to", p.to]] as const).forEach(([kind, pos]) => {
      if (!pos) return;
      pinMarkers.current.push(new maplibregl.Marker({ element: endpointElement(kind) }).setLngLat(pos).addTo(m));
    });
  }, [p.from, p.to]);

  // ---- live user GPS location marker & camera follow ----
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    if (!p.userLocation) {
      userMarker.current?.remove();
      userMarker.current = null;
      return;
    }
    const { pos, heading } = p.userLocation;
    if (!userMarker.current) {
      userMarker.current = new maplibregl.Marker({ element: userLocationElement(heading) })
        .setLngLat(pos)
        .addTo(m);
    } else {
      userMarker.current.setLngLat(pos);
      const el = userMarker.current.getElement();
      const headingEl = el.querySelector<HTMLDivElement>(".me-puck-heading");
      if (heading != null && !isNaN(heading)) {
        if (headingEl) {
          headingEl.style.transform = `rotate(${heading}deg)`;
        } else {
          const arr = document.createElement("div");
          arr.className = "me-puck-heading";
          arr.style.transform = `rotate(${heading}deg)`;
          el.insertBefore(arr, el.querySelector(".me-puck-dot"));
        }
      } else if (headingEl) {
        headingEl.remove();
      }
    }

    if (p.followUser) {
      m.easeTo({ center: pos, duration: 800 });
    }
  }, [p.userLocation, p.followUser]);

  function drawRoute(fit = true) {
    const m = map.current;
    if (!m || !m.getSource("route-safe")) return;
    const r = cb.current.route;
    const feat = (g?: GeoJSON.LineString | null): GeoJSON.FeatureCollection =>
      g ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: g }] } : EMPTY;
    const sameAsNormal = r?.safe && r?.normal && r.safe.distance_m === r.normal.distance_m;
    (m.getSource("route-normal") as maplibregl.GeoJSONSource).setData(feat(sameAsNormal ? null : r?.normal?.geometry));
    (m.getSource("route-safe") as maplibregl.GeoJSONSource).setData(feat(r?.safe?.geometry));
    const g = r?.safe?.geometry ?? r?.normal?.geometry;
    if (fit && g && g.coordinates.length > 1) {
      const b = new maplibregl.LngLatBounds();
      g.coordinates.forEach((c) => b.extend(c as LonLat));
      r?.normal?.geometry.coordinates.forEach((c) => b.extend(c as LonLat));
      // Keep the route clear of the toolbar and of the panel (side panel on desktop, bottom sheet on phones).
      const wide = window.innerWidth >= 760;
      m.fitBounds(b, { padding: { top: 130, bottom: wide ? 40 : Math.round(window.innerHeight * 0.6) + 20, left: 40, right: wide ? 440 : 40 }, duration: 700 });
    }
  }
  useEffect(() => drawRoute(), [p.route]);

  function drawAlt() {
    const m = map.current;
    const src = m?.getSource("route-alt") as maplibregl.GeoJSONSource | undefined;
    const g = cb.current.altRoute;
    src?.setData(g ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: g }] } : EMPTY);
  }
  useEffect(drawAlt, [p.altRoute]);

  // ---- areas we have road data for (shown when a trip falls outside them) ----
  function drawCoverage(fit = true) {
    const m = map.current;
    const src = m?.getSource("coverage") as maplibregl.GeoJSONSource | undefined;
    if (!m || !src) return;
    const areas = cb.current.coverage ?? [];
    src.setData({ type: "FeatureCollection", features: areas.map(({ name, bbox: [w, s, e, n] }) => ({
      type: "Feature", properties: { name },
      geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
    })) });
    if (fit && areas.length) {
      const b = new maplibregl.LngLatBounds();
      areas.forEach(({ bbox: [w, s, e, n] }) => { b.extend([w, s]); b.extend([e, n]); });
      const wide = window.innerWidth >= 760;
      m.fitBounds(b, { padding: { top: 130, bottom: wide ? 40 : Math.round(window.innerHeight * 0.6) + 20, left: 40, right: wide ? 440 : 40 }, duration: 700 });
    }
  }
  useEffect(() => drawCoverage(), [p.coverage]);

  // ---- light / dark map ----
  const firstTheme = useRef(true);
  useEffect(() => {
    if (typeof mapStyle(false) !== "string") el.current?.classList.toggle("osm-dark", p.dark);
    if (firstTheme.current) { firstTheme.current = false; return; }
    map.current?.setStyle(mapStyle(p.dark), { diff: false });
  }, [p.dark]);

  // Re-centre when the city changes.
  useEffect(() => {
    map.current?.jumpTo({ center: p.center, zoom: 13 });
  }, [p.center[0], p.center[1]]);

  useEffect(() => {
    map.current?.getCanvas().style.setProperty("cursor", p.picking ? "crosshair" : "");
  }, [p.picking]);

  return <div ref={el} className="map" />;
}
