import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { qrcode } from "vite-plugin-qrcode";
import basicSsl from "@vitejs/plugin-basic-ssl";

const useHttps = process.env.HTTPS === "true" || process.argv.includes("--https");

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  plugins: [
    react(),
    qrcode(),
    ...(useHttps ? [basicSsl()] : []),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "Can My Scooter Cross?",
        short_name: "ScooterCross",
        description: "Flood depth from a photo, a verdict for your vehicle, and a route around waterlogged roads and lanes.",
        theme_color: "#0b5cad",
        background_color: "#0e1726",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png}"],
        runtimeCaching: [
          {
            // Last-seen flood data stays available offline.
            urlPattern: ({ url }) => /\/(spots|hotspots|reports|demo\/timeline)/.test(url.pathname),
            handler: "NetworkFirst",
            options: { cacheName: "flood-data", networkTimeoutSeconds: 4, expiration: { maxEntries: 60, maxAgeSeconds: 86400 } },
          },
          {
            urlPattern: ({ url }) => url.hostname.includes("tile.openstreetmap.org") || url.hostname.startsWith("maps.geo."),
            handler: "StaleWhileRevalidate",
            options: { cacheName: "map-tiles", expiration: { maxEntries: 1500, maxAgeSeconds: 7 * 86400 } },
          },
        ],
      },
    }),
  ],
});
