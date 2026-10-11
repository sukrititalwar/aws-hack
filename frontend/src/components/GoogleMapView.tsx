import { useEffect, useRef, useState } from "react";
import { DARK_STYLE, domOverlay, loadGoogleMaps } from "../googleMaps";
import type { LonLat } from "../types";
import type { MapProps } from "./mapProps";
import { endpointElement, hotspotElement, rainElement, spotElement, userLocationElement } from "./markers";

interface Props extends MapProps {
  /** Called if Google cannot be used (load failure, rejected key); the app then falls back to the other map. */
  onFail: (why: string) => void;
}

const ll = ([lon, lat]: LonLat): google.maps.LatLngLiteral => ({ lat, lng: lon });

/** Dashed line: Google polylines have no dash option, so repeat a tiny symbol along an invisible line. */
function dashed(color: string, scale: number, repeat: string, z: number): google.maps.Polyline {
  return new google.maps.Polyline({
    strokeOpacity: 0, zIndex: z, clickable: false,
    icons: [{ icon: { path: "M 0,-1 0,1", strokeOpacity: 0.9, strokeColor: color, strokeWeight: 4, scale }, offset: "0", repeat }],
  });
}
const solid = (color: string, weight: number, z: number) =>
  new google.maps.Polyline({ strokeColor: color, strokeWeight: weight, strokeOpacity: 1, zIndex: z, clickable: false });

/** Same app, Google Maps basemap. Pins, routes and coverage outlines match the MapLibre version. */
export default function GoogleMapView(p: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<google.maps.Map | null>(null);
  const [ready, setReady] = useState(false);
  const cb = useRef(p);
  cb.current = p;

  const spotOv = useRef<google.maps.OverlayView[]>([]);
  const hotOv = useRef<google.maps.OverlayView[]>([]);
  const pinOv = useRef<google.maps.OverlayView[]>([]);
  const rainOv = useRef<google.maps.OverlayView[]>([]);
  const hadBounds = useRef(false);
  const meOv = useRef<google.maps.OverlayView | null>(null);
  const lines = useRef<{ normal: google.maps.Polyline; casing: google.maps.Polyline; safe: google.maps.Polyline; alt: google.maps.Polyline } | null>(null);
  const cover = useRef<(google.maps.Rectangle | google.maps.Polyline)[]>([]);

  // ---- load the API and create the map once ----
  useEffect(() => {
    let dead = false;
    const onAuth = () => cb.current.onFail("Google rejected the API key (wrong key, restricted to another site, or billing is off).");
    window.addEventListener("google-maps-auth-failed", onAuth);
    loadGoogleMaps()
      .then(() => {
        if (dead || !el.current) return;
        const m = new google.maps.Map(el.current, {
          center: ll(cb.current.center), zoom: 14, disableDefaultUI: true, zoomControl: true,
          zoomControlOptions: { position: google.maps.ControlPosition.RIGHT_CENTER },
          gestureHandling: "greedy", clickableIcons: false, keyboardShortcuts: true,
          styles: cb.current.dark ? DARK_STYLE : [{ featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] }],
        });
        m.addListener("click", (e: google.maps.MapMouseEvent) => {
          if (cb.current.picking && e.latLng) cb.current.onPick([e.latLng.lng(), e.latLng.lat()]);
        });
        // "my location" control
        const btn = document.createElement("button");
        btn.className = "gm-locate";
        btn.setAttribute("aria-label", "My location");
        btn.title = "My location";
        btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="2" x2="5" y1="12" y2="12"/><line x1="19" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="5"/><line x1="12" x2="12" y1="19" y2="22"/><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/></svg>';
        btn.onclick = () => navigator.geolocation?.getCurrentPosition((pos) => {
          const at: LonLat = [pos.coords.longitude, pos.coords.latitude];
          m.panTo(ll(at));
          m.setZoom(16);
          meOv.current?.setMap(null);
          const dot = document.createElement("div");
          dot.className = "me-dot";
          meOv.current = domOverlay(m, dot, at, 5);
        }, () => undefined, { enableHighAccuracy: true, timeout: 8000 });
        m.controls[google.maps.ControlPosition.RIGHT_CENTER].push(btn);
        lines.current = { normal: dashed("#94a3b8", 3, "14px", 1), casing: solid("#ffffff", 9, 2), safe: solid("#2563eb", 6, 3), alt: dashed("#16a34a", 3, "16px", 4) };
        Object.values(lines.current).forEach((l) => l.setMap(m));
        map.current = m;
        document.documentElement.dataset.map = "google";
        setReady(true);
      })
      .catch((e) => !dead && cb.current.onFail(e instanceof Error ? e.message : String(e)));
    return () => {
      dead = true;
      window.removeEventListener("google-maps-auth-failed", onAuth);
      delete document.documentElement.dataset.map;
      [...spotOv.current, ...hotOv.current, ...pinOv.current, ...rainOv.current, meOv.current].forEach((o) => o?.setMap(null));
      if (lines.current) Object.values(lines.current).forEach((l) => l.setMap(null));
      cover.current.forEach((c) => c.setMap(null));
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const padding = () => {
    // Keep the route clear of the toolbar and of the panel (side panel on desktop, bottom sheet on phones).
    const wide = window.innerWidth >= 760;
    return { top: 130, bottom: wide ? 40 : Math.round(window.innerHeight * 0.6) + 20, left: 40, right: wide ? 440 : 40 };
  };

  // ---- spot pins ----
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    spotOv.current.forEach((o) => o.setMap(null));
    spotOv.current = p.spots.map((s) => domOverlay(m, spotElement(s, p.vehicle, (x) => cb.current.onSpot(x)), [s.lon, s.lat], 3));
  }, [ready, p.spots, p.vehicle]);

  // ---- chronic hotspots ----
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    hotOv.current.forEach((o) => o.setMap(null));
    hotOv.current = p.hotspots.map((h) => domOverlay(m, hotspotElement(h, p.lang, (x) => cb.current.onHotspot(x)), [h.lon, h.lat], 2));
  }, [ready, p.hotspots, p.lang]);

  // ---- rain dots + "show all of India" view ----
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    rainOv.current.forEach((o) => o.setMap(null));
    rainOv.current = (p.rainPoints ?? []).map((c) => domOverlay(m, rainElement(c, (x) => cb.current.onRainPoint?.(x)), [c.lon, c.lat], 2));
  }, [ready, p.rainPoints]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    if (p.viewBounds) {
      const [w, s, e, n] = p.viewBounds;
      const wide = window.innerWidth >= 760;
      m.fitBounds({ west: w, south: s, east: e, north: n }, { top: 130, bottom: wide ? 40 : Math.round(window.innerHeight * 0.5) + 10, left: 20, right: wide ? 440 : 20 });
      hadBounds.current = true;
    } else if (hadBounds.current) {
      hadBounds.current = false;
      m.setCenter(ll(cb.current.center));
      m.setZoom(13);
    }
  }, [ready, p.viewBounds]);

  // ---- A / B markers ----
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    pinOv.current.forEach((o) => o.setMap(null));
    pinOv.current = (([["from", p.from], ["to", p.to]] as const)
      .filter(([, pos]) => !!pos)
      .map(([kind, pos]) => domOverlay(m, endpointElement(kind), pos as LonLat, 4)));
  }, [ready, p.from, p.to]);

  // ---- live user GPS location marker & camera follow ----
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    meOv.current?.setMap(null);
    meOv.current = null;
    if (!p.userLocation) return;
    const { pos, heading } = p.userLocation;
    meOv.current = domOverlay(m, userLocationElement(heading), pos, 5);
    if (p.followUser) {
      m.panTo(ll(pos));
      if (p.navigating) {
        m.setZoom(17);
        m.setTilt(45);
        if (heading != null && !isNaN(heading)) m.setHeading(heading);
      }
    }
  }, [ready, p.userLocation, p.followUser, p.navigating]);

  // ---- routes ----
  useEffect(() => {
    const m = map.current, L = lines.current;
    if (!ready || !m || !L) return;
    const r = p.route;
    const path = (g?: GeoJSON.LineString | null) => (g ? g.coordinates.map((c) => ll(c as LonLat)) : []);
    const same = r?.safe && r?.normal && r.safe.distance_m === r.normal.distance_m;
    L.normal.setPath(same ? [] : path(r?.normal?.geometry));
    L.casing.setPath(path(r?.safe?.geometry));
    L.safe.setPath(path(r?.safe?.geometry));
    const g = r?.safe?.geometry ?? r?.normal?.geometry;
    if (g && g.coordinates.length > 1) {
      const b = new google.maps.LatLngBounds();
      g.coordinates.forEach((c) => b.extend(ll(c as LonLat)));
      r?.normal?.geometry.coordinates.forEach((c) => b.extend(ll(c as LonLat)));
      m.fitBounds(b, padding());
    }
  }, [ready, p.route]);

  useEffect(() => {
    const L = lines.current;
    if (ready && L) L.alt.setPath(p.altRoute ? p.altRoute.coordinates.map((c) => ll(c as LonLat)) : []);
  }, [ready, p.altRoute]);

  // ---- areas we have road data for ----
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    cover.current.forEach((c) => c.setMap(null));
    const areas = p.coverage ?? [];
    cover.current = areas.flatMap(({ bbox: [w, s, e, n] }) => {
      const ring = [{ lat: s, lng: w }, { lat: s, lng: e }, { lat: n, lng: e }, { lat: n, lng: w }, { lat: s, lng: w }];
      const fill = new google.maps.Rectangle({ bounds: { south: s, west: w, north: n, east: e }, strokeOpacity: 0, fillColor: "#2563eb", fillOpacity: 0.07, clickable: false, map: m });
      const edge = dashed("#2563eb", 2, "12px", 1);
      edge.setPath(ring);
      edge.setMap(m);
      return [fill, edge];
    });
    if (areas.length) {
      const b = new google.maps.LatLngBounds();
      areas.forEach(({ bbox: [w, s, e, n] }) => { b.extend({ lat: s, lng: w }); b.extend({ lat: n, lng: e }); });
      m.fitBounds(b, padding());
    }
  }, [ready, p.coverage]);

  // ---- light / dark, city change, picking cursor ----
  useEffect(() => {
    map.current?.setOptions({ styles: p.dark ? DARK_STYLE : [{ featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] }] });
  }, [ready, p.dark]);
  useEffect(() => {
    map.current?.setCenter(ll(p.center));
    map.current?.setZoom(13);
  }, [ready, p.center[0], p.center[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    map.current?.setOptions({ draggableCursor: p.picking ? "crosshair" : null });
  }, [ready, p.picking]);

  return <div ref={el} className="map gmap" />;
}
