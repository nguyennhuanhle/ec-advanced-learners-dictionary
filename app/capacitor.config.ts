// App Android (PLAN-android, UC-A01…): Capacitor 8 gói bản build Android của giao diện web (build-android/, có sẵn dữ liệu trong data/).
import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  // mã gói trên Google Play — KHÔNG ĐỔI được sau khi lên Play (người dùng chốt 2026-10-07)
  appId: "com.edtechcorner.dictionary",
  appName: "EC Eng-Vie Dictionary",
  webDir: "build-android",
  server: {
    // Origin của WebView = https://localhost. IndexedDB (lịch sử, danh sách, cài đặt) gắn với origin này:
    // KHÔNG ĐỔI hostname / androidScheme ở bản sau, nếu không người dùng mất dữ liệu (PLAN-android mục 6; build_android.py kiểm).
    hostname: "localhost",
    androidScheme: "https",
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
