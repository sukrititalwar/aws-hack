import { useState } from "react";
import { hasGoogleMaps } from "../googleMaps";
import GoogleMapView from "./GoogleMapView";
import MapView from "./MapView";
import type { MapProps } from "./mapProps";

/**
 * Google Maps when VITE_GOOGLE_MAPS_API_KEY is set, otherwise the Amazon Location / OpenStreetMap map.
 * If Google cannot load or rejects the key, the app switches to the other map and says why, so the
 * map is never just blank.
 */
export default function MapRoot(props: MapProps) {
  const [engine, setEngine] = useState<"google" | "osm">(hasGoogleMaps ? "google" : "osm");
  const [why, setWhy] = useState("");
  if (engine === "google") {
    return <GoogleMapView {...props} onFail={(msg) => { console.warn("Google Maps unavailable:", msg); setWhy(msg); setEngine("osm"); }} />;
  }
  return (
    <>
      <MapView {...props} />
      {why && <button className="mapnote" onClick={() => setWhy("")} title="Dismiss">Showing the backup map. {why}</button>}
    </>
  );
}
