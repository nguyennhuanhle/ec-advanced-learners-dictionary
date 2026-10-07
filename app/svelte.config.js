// Tauri doesn't have a Node.js server to do proper SSR
// so we use adapter-static with a fallback to index.html to put the site in SPA mode
// See: https://svelte.dev/docs/kit/single-page-apps
// See: https://v2.tauri.app/start/frontend/sveltekit/ for more info
import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
// @ts-ignore -- không có @types/node (hoặc có, kéo theo bởi @capacitor/cli)
import process from "node:process";

// Bản web (VITE_TARGET=web, đặt bởi vite.config.js khi `npm run build:web`): ra build-web/, gốc "/"
// (tên miền con dictionary.edtechcorner.com), CSP chế độ hash (SvelteKit tự thêm hash cho script khởi động nội tuyến).
// Bản desktop: giữ nguyên như trước (build/, CSP do tauri.conf.json đặt).
const WEB = process.env.VITE_TARGET === "web";
// Bản Android (Capacitor): cùng code web, ra build-android/ (webDir của capacitor.config.ts), CSP chỉ nguồn của app —
// không Google Analytics, không nguồn ngoài nào (UC-A "Không thể"; bản release còn bỏ cả quyền INTERNET).
const ANDROID = process.env.VITE_ANDROID === "1";
const GA_SCRIPT = ANDROID ? [] : ["https://www.googletagmanager.com"];
const GA_CONNECT = ANDROID
  ? []
  : ["https://*.google-analytics.com", "https://*.analytics.google.com", "https://*.googletagmanager.com"];
const GA_IMG = ANDROID ? [] : ["https://*.google-analytics.com", "https://*.googletagmanager.com"];

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: WEB
    ? {
        adapter: ANDROID
          ? adapter({ pages: "build-android", assets: "build-android", fallback: "index.html" })
          : adapter({ pages: "build-web", assets: "build-web", fallback: "index.html" }),
        csp: {
          mode: "hash",
          directives: {
            "default-src": ["self"],
            // Google Analytics (UC-W15): gtag.js + gửi lượt xem; không thêm script nội tuyến nào
            "script-src": ["self", ...GA_SCRIPT],
            "connect-src": ["self", ...GA_CONNECT],
            "worker-src": ["self"],
            "img-src": ["self", "data:", ...GA_IMG],
            "style-src": ["self", "unsafe-inline"],
            "object-src": ["none"],
            "base-uri": ["self"],
            "form-action": ["none"],
          },
        },
      }
    : {
        adapter: adapter({
          fallback: "index.html",
        }),
      },
};

export default config;
