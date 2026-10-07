// Google Analytics cho bản web (UC-W15): CHỈ đếm lượt mở trang. Không bao giờ gửi từ đang tra:
//  - địa chỉ gửi cho Google = origin + pathname, bỏ phần "#…" (nơi chứa từ tra, vd. #/en/bank);
//  - không gửi sự kiện nào cho thao tác tra / lưu / danh sách / cài đặt;
//  - trong GA4 phải tắt "Page changes based on browser history events" (Enhanced measurement), nếu không GA tự gửi
//    lượt xem mỗi lần địa chỉ "#" đổi.
// Nạp gtag.js bằng code (không có script nội tuyến trong HTML) → CSP chỉ cần thêm tên miền của Google (svelte.config.js).
// Bản desktop không bao giờ gọi (IS_WEB false lúc build).

import { IS_ANDROID, IS_WEB } from "./platform";

const GA_ID = "G-RK9PZGW7J9";

type Gtag = (...args: unknown[]) => void;

export function initAnalytics(): void {
  // app Android không có analytics (UC-A "Không thể"); CSP bản Android cũng không cho nguồn của Google
  if (!IS_WEB || IS_ANDROID || import.meta.env.DEV) return;
  // xem thử trên máy (web-preview.py) không tính lượt
  if (/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)) return;
  const w = window as unknown as { dataLayer: unknown[]; gtag: Gtag };
  w.dataLayer = w.dataLayer || [];
  // gtag cần đẩy đúng đối tượng `arguments`, không phải mảng
  w.gtag = function () {
    // eslint-disable-next-line prefer-rest-params
    w.dataLayer.push(arguments);
  };
  const strip = (u: string) => u.split("#")[0];
  w.gtag("js", new Date());
  w.gtag("config", GA_ID, {
    page_location: location.origin + location.pathname,
    page_referrer: strip(document.referrer),
  });
  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`;
  document.head.appendChild(s);
}
