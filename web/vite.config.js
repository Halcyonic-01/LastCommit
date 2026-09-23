import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { cpSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { createReadStream } from "node:fs";

const ROOT = resolve(__dirname, "..");
// forecast/ and geo/ live at the repo root — one source of truth, served here in dev,
// copied into dist at build. Never duplicated into web/public.
const DATA_DIRS = ["forecast", "geo"];

function repoData() {
  return {
    name: "repo-data",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url || "").split("?")[0]);
        const dir = DATA_DIRS.find((d) => url.startsWith(`/${d}/`));
        if (!dir) return next();
        const file = join(ROOT, url.replace(/^\/+/, ""));
        if (!file.startsWith(ROOT) || !existsSync(file)) return next();
        res.setHeader("Content-Type", url.endsWith(".geojson") ? "application/geo+json" : "application/json");
        createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      for (const d of DATA_DIRS) {
        const from = join(ROOT, d);
        if (existsSync(from)) cpSync(from, join(__dirname, "dist", d), { recursive: true });
      }
    },
  };
}

export default defineConfig({
  plugins: [
    react(),
    repoData(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      manifest: {
        name: "VarshaDrishti",
        short_name: "VarshaDrishti",
        description: "Monsoon onset and dry-spell advisories for Karnataka farmers",
        lang: "kn",
        theme_color: "#f4efe4",
        background_color: "#f4efe4",
        display: "standalone",
        start_url: "/",
        icons: [{ src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" }],
      },
      workbox: {
        // Precache the farmer shell only. The officer bundle is ~220 kB gzipped of
        // MapLibre — never push that down a 2G connection in the background.
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        // HazardMap bundles MapLibre and is now a separate chunk shared by Officer and
        // Replay (Vite hoists a module imported by two lazy chunks into its own) --
        // without excluding it too, the farmer's precache silently pulls in all of
        // MapLibre again through the back door.
        globIgnores: ["**/Officer-*", "**/Verify-*", "**/Replay-*", "**/HazardMap-*"],
        // the farmer's own area file and the index must survive going offline
        runtimeCaching: [
          {
            urlPattern: /\/forecast\/.*\.json$/,
            handler: "StaleWhileRevalidate",
            options: { cacheName: "forecast", expiration: { maxEntries: 40, maxAgeSeconds: 604800 } },
          },
          {
            urlPattern: /\/geo\/.*\.geojson$/,
            handler: "CacheFirst",
            options: { cacheName: "geo", expiration: { maxEntries: 8, maxAgeSeconds: 2592000 } },
          },
          {
            // photos are fetched on demand, then kept — the farmer's hero image
            // has to survive going offline in the field
            urlPattern: /\/photos\/.*\.webp$/,
            handler: "CacheFirst",
            options: { cacheName: "photos", expiration: { maxEntries: 12, maxAgeSeconds: 2592000 } },
          },
          {
            // Narration audio clips for offline playback in the field
            urlPattern: /\/(?:audio\/narration\/.*|.*narration.*\.wav|demo_crida\.wav)$/,
            handler: "CacheFirst",
            options: { cacheName: "narration-audio", expiration: { maxEntries: 60, maxAgeSeconds: 2592000 } },
          },
          {
            urlPattern: /^https:\/\/fonts\.(googleapis|gstatic)\.com\//,
            handler: "CacheFirst",
            options: { cacheName: "fonts", expiration: { maxEntries: 20, maxAgeSeconds: 31536000 } },
          },
        ],
      },
    }),
  ],
  // VITE_* vars live in the repo-root .env, same "one source of truth" as forecast/geo —
  // never a second copy in web/.env.
  envDir: ROOT,
  server: { port: Number(process.env.PORT) || 5173 },
});
