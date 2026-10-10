import { Ambulance, Bike, Bus, Car, CarFront, Check, CircleHelp, Footprints, TriangleAlert, X, type LucideProps } from "lucide-react";
import type { Vehicle } from "./types";

// Lucide has no scooter or auto-rickshaw, so these two are drawn in the same 24px / 2px-stroke style.
function Svg({ size = 20, strokeWidth = 2, children, ...rest }: LucideProps & { children: React.ReactNode }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      {children}
    </svg>
  );
}

export const Scooter = (p: LucideProps) => (
  <Svg {...p}>
    <circle cx="5.5" cy="17.5" r="2.5" />
    <circle cx="18.5" cy="17.5" r="2.5" />
    <path d="M8 17.5h6.5L17 5" />
    <path d="M15 5h4" />
    <path d="M4 12.5h6l2 5" />
  </Svg>
);

export const AutoRickshaw = (p: LucideProps) => (
  <Svg {...p}>
    <path d="M3 16V9a4 4 0 0 1 4-4h8l5 6v5" />
    <path d="M14 5v6h6" />
    <path d="M3 11h11" />
    <circle cx="7" cy="17" r="2" />
    <circle cx="17" cy="17" r="2" />
  </Svg>
);

const VEHICLE_ICON: Record<Vehicle, React.ComponentType<LucideProps>> = {
  pedestrian: Footprints,
  bicycle: Bike,
  scooter: Scooter,
  auto: AutoRickshaw,
  car: Car,
  suv: CarFront,
  bus: Bus,
  ambulance: Ambulance,
};

export function VehicleIcon({ v, size = 20, ...rest }: { v: Vehicle } & LucideProps) {
  const I = VEHICLE_ICON[v];
  return <I size={size} aria-hidden {...rest} />;
}

/** Icon for a verdict category class (go / risky / nogo) or "?" for requires-inspection. Always paired with a word. */
export function VerdictIcon({ cls, glyph, size = 16 }: { cls: string; glyph?: string; size?: number }) {
  if (glyph === "?") return <CircleHelp size={size} aria-hidden />;
  if (cls === "go") return <Check size={size} strokeWidth={2.5} aria-hidden />;
  if (cls === "risky") return <TriangleAlert size={size} aria-hidden />;
  return <X size={size} strokeWidth={2.5} aria-hidden />;
}
