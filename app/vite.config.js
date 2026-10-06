import { defineConfig } from "vite";
import { sveltekit } from "@sveltejs/kit/vite";
// @ts-expect-error type error without @types/node package
import process from "node:process";
// @ts-expect-error type error without @types/node package
import { readFileSync } from "node:fs";
const host = process.env.TAURI_DEV_HOST;
const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Bản web (dictionary.edtechcorner.com): `npm run build:web` (= vite build --mode web) hoặc VITE_TARGET=web.
  // Không đặt gì → bản desktop như cũ. svelte.config.js đọc process.env.VITE_TARGET để chọn thư mục ra + CSP.
  const target = mode === "web" || process.env.VITE_TARGET === "web" ? "web" : "desktop";
  process.env.VITE_TARGET = target;
  return {
  plugins: [sveltekit()],
  // hằng số lúc build: nhánh không dùng bị loại khỏi bundle (bản web không có plugin Tauri, bản desktop không có Worker)
  define: {
    "import.meta.env.VITE_TARGET": JSON.stringify(target),
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(pkg.version),
  },
  worker: { format: "es" },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || "127.0.0.1",
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
  };
});
