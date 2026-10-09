import exifr from "exifr";
import type { Lang } from "./i18n";

/** Anonymous per-install ID for rate limiting and one-vote-per-device. */
export function deviceId(): string {
  try {
    let id = localStorage.getItem("deviceId");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("deviceId", id);
    }
    return id;
  } catch {
    return "anon-" + Math.random().toString(36).slice(2, 12);
  }
}

export function stored<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}
export function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
}

/** Read EXIF time before resizing (canvas re-encode strips EXIF). */
export async function photoTime(file: File): Promise<number | undefined> {
  try {
    const e = await exifr.parse(file, ["DateTimeOriginal", "CreateDate"]);
    const d: Date | undefined = e?.DateTimeOriginal || e?.CreateDate;
    return d ? Math.round(d.getTime() / 1000) : undefined;
  } catch {
    return undefined;
  }
}

/** Resize to <= 1568 px on the long side (Bedrock's sweet spot) and encode as JPEG. */
export async function resizeImage(file: File, maxSide = 1568): Promise<Blob> {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" } as ImageBitmapOptions);
  const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bmp.width * scale);
  canvas.height = Math.round(bmp.height * scale);
  canvas.getContext("2d")!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return new Promise((res, rej) => canvas.toBlob((b) => (b ? res(b) : rej(new Error("encode failed"))), "image/jpeg", 0.85));
}

export function getPosition(timeoutMs = 8000): Promise<[number, number]> {
  return new Promise((res, rej) => {
    if (!navigator.geolocation) return rej(new Error("no geolocation"));
    navigator.geolocation.getCurrentPosition(
      (p) => res([p.coords.longitude, p.coords.latitude]),
      rej,
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 60000 },
    );
  });
}

export function speak(text: string, lang: Lang) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang === "hi" ? "hi-IN" : "en-IN";
  speechSynthesis.speak(u);
}

export function fmtTime(epoch: number) {
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true,
  });
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
