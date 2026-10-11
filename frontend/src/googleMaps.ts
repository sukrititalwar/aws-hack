/**
 * Google Maps JavaScript API loader.
 *
 * Google's map tiles may only be shown through Google's own SDK (they cannot be used inside
 * MapLibre or another renderer), so this is a separate map implementation that MapRoot picks when
 * VITE_GOOGLE_MAPS_API_KEY is set. The key is public by nature (it ships in the page), so restrict it
 * in Google Cloud to your site's HTTP referrers and to the "Maps JavaScript API".
 */
export const GOOGLE_KEY = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined) ?? "";
export const hasGoogleMaps = !!GOOGLE_KEY;

let loading: Promise<void> | null = null;

export function loadGoogleMaps(): Promise<void> {
  if (!GOOGLE_KEY) return Promise.reject(new Error("No Google Maps API key is configured."));
  if (window.google?.maps) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const w = window as unknown as Record<string, unknown>;
    // Google calls this when the key is invalid, restricted to other sites, or billing is off.
    w.gm_authFailure = () => window.dispatchEvent(new Event("google-maps-auth-failed"));
    w.__gmapsInit = () => resolve();
    const timer = setTimeout(() => reject(new Error("Google Maps took too long to load.")), 15000);
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(GOOGLE_KEY)}&v=weekly&region=IN&callback=__gmapsInit`;
    s.async = true;
    s.onerror = () => { clearTimeout(timer); loading = null; reject(new Error("Google Maps could not be loaded (blocked or offline).")); };
    document.head.appendChild(s);
  });
  return loading;
}

/** Place a DOM element at a position on the map (the Maps JS API has no built-in HTML marker without a Map ID). */
export function domOverlay(map: google.maps.Map, el: HTMLElement, pos: [number, number], z = 1): google.maps.OverlayView {
  const wrap = document.createElement("div");
  wrap.style.cssText = `position:absolute;transform:translate(-50%,-50%);z-index:${z}`;
  wrap.appendChild(el);
  const ov = new google.maps.OverlayView();
  ov.onAdd = function () { this.getPanes()!.overlayMouseTarget.appendChild(wrap); };
  ov.draw = function () {
    const pt = this.getProjection()?.fromLatLngToDivPixel(new google.maps.LatLng(pos[1], pos[0]));
    if (pt) { wrap.style.left = `${pt.x}px`; wrap.style.top = `${pt.y}px`; }
  };
  ov.onRemove = function () { wrap.remove(); };
  ov.setMap(map);
  return ov;
}

/** Compact dark basemap style (Google's "night" look) for dark mode. */
export const DARK_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#1d2433" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#9aa4b8" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#1d2433" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#3a4560" }] },
  { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
  { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#183a2c" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#2c3750" }] },
  { featureType: "road.arterial", elementType: "geometry", stylers: [{ color: "#34415f" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#46557a" }] },
  { featureType: "transit", elementType: "labels", stylers: [{ visibility: "off" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#0e1a2e" }] },
];
