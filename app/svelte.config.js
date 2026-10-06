// Tauri doesn't have a Node.js server to do proper SSR
// so we use adapter-static with a fallback to index.html to put the site in SPA mode
// See: https://svelte.dev/docs/kit/single-page-apps
// See: https://v2.tauri.app/start/frontend/sveltekit/ for more info
import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
// @ts-expect-error type error without @types/node package
import process from "node:process";

// Bản web (VITE_TARGET=web, đặt bởi vite.config.js khi `npm run build:web`): ra build-web/, gốc "/"
// (tên miền con dictionary.edtechcorner.com), CSP chế độ hash (SvelteKit tự thêm hash cho script khởi động nội tuyến).
// Bản desktop: giữ nguyên như trước (build/, CSP do tauri.conf.json đặt).
const WEB = process.env.VITE_TARGET === "web";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: WEB
    ? {
        adapter: adapter({ pages: "build-web", assets: "build-web", fallback: "index.html" }),
        csp: {
          mode: "hash",
          directives: {
            "default-src": ["self"],
            "script-src": ["self"],
            "connect-src": ["self"],
            "worker-src": ["self"],
            "img-src": ["self", "data:"],
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
