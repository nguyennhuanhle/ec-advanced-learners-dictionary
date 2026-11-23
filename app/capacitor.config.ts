// App Android (PLAN-android, UC-A01…): Capacitor 8 gói bản build Android của giao diện web (build-android/, có sẵn dữ liệu trong data/).
// App iOS (PLAN-ios, UC-I01…): cùng cách, bản build iOS (build-ios/). `cap sync ios` phải chạy với CAP_WEBDIR=build-ios
// (pipeline/build_ios.py đặt sẵn) — Capacitor chỉ có một webDir cho mọi nền tảng.
import type { CapacitorConfig } from "@capacitor/cli";
// @ts-ignore -- không có @types/node
import process from "node:process";

const config: CapacitorConfig = {
  // mã gói trên Google Play — KHÔNG ĐỔI được sau khi lên Play (người dùng chốt 2026-10-07)
  appId: "com.edtechcorner.dictionary",
  appName: "EC Eng-Vie Dictionary",
  webDir: process.env.CAP_WEBDIR === "build-ios" ? "build-ios" : "build-android",
  server: {
    // Origin của WebView = https://localhost. IndexedDB (lịch sử, danh sách, cài đặt) gắn với origin này:
    // KHÔNG ĐỔI hostname / androidScheme ở bản sau, nếu không người dùng mất dữ liệu (PLAN-android mục 6; build_android.py kiểm).
    hostname: "localhost",
    androidScheme: "https",
    // iOS: origin = capacitor://localhost. KHÔNG ĐỔI ở bản sau (PLAN-ios mục 6; build_ios.py kiểm).
    iosScheme: "capacitor",
  },
  ios: {
    // nội dung tràn dưới tai thỏ/thanh Home; CSS dùng chung đệm bằng env(safe-area-inset-*) (cần viewport-fit=cover, build_ios.py chèn)
    contentInset: "never",
  },
  // webContentsDebuggingEnabled để mặc định: Capacitor chỉ bật gỡ lỗi WebView ở bản debug (kiểm bằng DevTools qua adb, UC-AM02)
  plugins: {
    SystemBars: {
      // "css": WebView ≥ 140 + viewport-fit=cover → tràn viền, CSS đệm bằng env(safe-area-inset-*);
      // WebView cũ hơn → Capacitor đệm WebView từ phía Android (vùng thanh hệ thống lấy màu windowBackground của theme)
      insetsHandling: "css",
      initialViewportFitValueHint: "cover",
    },
    App: {
      // nút Back do giao diện bật/tắt lúc chạy (PLAN-android mục 7): mặc định để hệ thống xử lý (predictive back)
      disableBackButtonHandler: true,
    },
  },
};

export default config;
