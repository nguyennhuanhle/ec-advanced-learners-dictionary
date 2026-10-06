<script lang="ts">
  // Màn hình chính: ô tìm + gợi ý, 3 chế độ, mục từ, lịch sử, danh sách từ, cài đặt, nguồn & giấy phép.
  // Lịch sử, danh sách, cài đặt nằm trong user.sqlite (Rust). Chữ giao diện qua t() (English mặc định / Tiếng Việt).
  import { onMount, tick } from "svelte";
  import Entry from "$lib/Entry.svelte";
  import ViEntryView from "$lib/ViEntry.svelte";
  import Icon from "$lib/Icon.svelte";
  import About from "$lib/About.svelte";
  import * as api from "$lib/api";
  import { cleanQuery, describeVia } from "$lib/api";
  import { DESKTOP_DOWNLOAD, IS_WEB, SITE_HOME, downloadText, persistStorage, pickSavePath } from "$lib/platform";
  import { writeClipboard } from "$lib/copy";
  import { initAnalytics } from "$lib/analytics";
  import { setOnlineVoices, speak, type Accent } from "$lib/speech";
  import { APP_NAME, dateLocale, t, tErr, ui, type UiLang } from "$lib/i18n.svelte";
  import type { DbStatus, EnEntry, HistoryRow, ListInfo, ListItem, LookupView, Mode, Source, Suggestion, Via, ViEntry } from "$lib/types";

  type Screen =
    | { kind: "home" }
    | { kind: "entry"; entry: EnEntry; via: Via | null; alsoVi: string | null }
    | { kind: "vi"; entry: ViEntry; alsoEn: string | null }
    | { kind: "choice"; query: string; words: string[]; lang: "en" | "vi" }
    | { kind: "none"; query: string; suggestions: { word: string; available: boolean }[] }
    | { kind: "sources"; list: Source[] }
    | { kind: "settings" };

  const SECTIONS: [string, "secPhrasal" | "secIdioms" | "secThes" | "secFamily" | "secTatoeba" | "secOrigin" | "secWikt" | "secNearby"][] = [
    ["phrasal", "secPhrasal"],
    ["idioms", "secIdioms"],
    ["thes", "secThes"],
    ["family", "secFamily"],
    ["tatoeba", "secTatoeba"],
    ["origin", "secOrigin"],
    ["wikt", "secWikt"],
    ["nearby", "secNearby"],
  ];

  let status = $state<DbStatus | null>(null);
  let mode = $state<Mode>("envi");
  let query = $state("");
  let suggestions = $state<Suggestion[]>([]);
  let sugOpen = $state(false);
  let sugIndex = $state(-1);
  let screen = $state<Screen>({ kind: "home" });
  let back = $state<string[]>([]);
  let fwd = $state<string[]>([]);
  let current = $state("");
  let historyRows = $state<HistoryRow[]>([]);
  let listInfos = $state<ListInfo[]>([]);
  let activeList = $state(0);
  let items = $state<ListItem[]>([]);
  let saved = $state(new Set<string>());
  let tab = $state<"history" | "lists">("history");
  let theme = $state<"auto" | "light" | "dark">("auto");
  let palette = $state<"classic" | "rose">("classic");
  let fontSize = $state(16);
  let accent = $state<Accent>("us");
  let closed = $state(new Set<string>(["wikt"]));
  let editing = $state<"" | "new" | "rename">("");
  let editName = $state("");
  let banner = $state("");
  let onlineVoices = $state(false); // bản web: cho dùng giọng đọc trực tuyến của trình duyệt (UC-W11)
  let copyManual = $state(""); // bản web: trình duyệt chặn clipboard → hiện chữ để người dùng tự chép
  let restoreInput: HTMLInputElement | undefined = $state();
  let toastAction = $state<{ label: string; run: () => void } | null>(null); // bản web: nút "Thử lại" trong thông báo lỗi mạng
  let sugLoading = $state(false); // bản web: mạng chậm → chỉ báo "đang tải" sau 300 ms (UC-W "Khi lỗi")
  let sideOpen = $state(false); // màn hình hẹp: lịch sử / danh sách mở thành ngăn kéo
  let pick = $state(""); // bản web, màn hình cảm ứng: từ đang được chọn → nút "Tra" nổi (UC-W02)
  let navIdx = $state(0); // bản web: vị trí trong lịch sử trình duyệt (nút lùi/tiến, UC-W03)
  let navMax = $state(0);
  let bannerReload = $state(false); // bản web: dải thông báo có nút "Tải lại" (UC-W10)
  let toast = $state("");
  let toastTimer: ReturnType<typeof setTimeout> | undefined;
  let sugTimer: ReturnType<typeof setTimeout> | undefined;
  let sugSeq = 0;
  let goSeq = 0; // lần tra mới nhất: kết quả về muộn của lần tra cũ không ghi đè (bản web tải dữ liệu qua mạng)
  let mainEl: HTMLElement | undefined = $state();
  let inputEl: HTMLInputElement | undefined = $state();

  const showVi = $derived(mode !== "en");
  const activeName = $derived(listInfos.find((l) => l.id === activeList)?.name ?? "");

  onMount(async () => {
    // bản web: Worker báo site đã đổi bản dữ liệu (UC-W10). Bản desktop không bao giờ phát sự kiện này.
    window.addEventListener("ecald-notice", (e) => {
      banner = tErr((e as CustomEvent<{ message: string }>).detail.message);
      bannerReload = true;
    });
    try {
      status = await api.dbStatus();
    } catch (e) {
      status = { ok: false, error: String(e), path: "", meta: {}, counts: {}, user_ok: false, user_error: String(e), user_path: null, user_notice: null };
    }
    if (status.user_ok) {
      const st = await api.settings();
      ui.lang = (st.ui_lang as UiLang) ?? (IS_WEB && navigator.language?.toLowerCase().startsWith("vi") ? "vi" : "en");
      theme = (st.theme as typeof theme) ?? "auto";
      palette = (st.palette as typeof palette) ?? "classic";
      mode = (st.mode as Mode) ?? "envi";
      fontSize = Number(st.font_size ?? 16) || 16;
      accent = (st.accent as Accent) ?? "us";
      if (st.closed !== undefined) closed = new Set(st.closed.split(",").filter(Boolean));
      activeList = Number(st.active_list ?? 0);
      onlineVoices = st.online_voices === "1";
      setOnlineVoices(onlineVoices);
      await refreshLists();
      await refreshHistory();
      if (IS_WEB) webStartup(st);
    } else if (status.user_error) {
      banner = t("userDbError", { e: tErr(status.user_error) });
    }
    if (status.user_notice) banner = tErr(status.user_notice);
    if (IS_WEB) webInit();
    // Chỉ khi phát triển: ?lang=vi&palette=rose&theme=dark&mode=envi&q=make (hoặc &screen=about) để chụp ảnh màn hình (không lưu vào cài đặt)
    if (import.meta.env.DEV) {
      const p = new URLSearchParams(location.search);
      if (p.get("lang")) ui.lang = p.get("lang") as UiLang;
      if (p.get("palette")) palette = p.get("palette") as typeof palette;
      if (p.get("theme")) theme = p.get("theme") as typeof theme;
      if (p.get("mode")) mode = p.get("mode") as Mode;
      if (p.get("q")) go(p.get("q")!, false);
      if (p.get("screen") === "about") showSources();
    }
    applyLook();
    window.speechSynthesis?.getVoices(); // nạp sẵn danh sách giọng
    inputEl?.focus();
  });

  /** Bản web: tham số ?lang=&theme= (UC-W04), địa chỉ "#" (UC-W03), nút "Tra" khi chọn từ trên màn hình cảm ứng (UC-W02). */
  function webInit() {
    initAnalytics(); // UC-W15: chỉ đếm lượt mở trang, không gửi phần "#…"
    const p = new URLSearchParams(location.search);
    const lang = p.get("lang");
    const th = p.get("theme");
    if (lang === "en" || lang === "vi") ui.lang = lang;
    if (th === "dark" || th === "light") theme = th;
    if (p.has("lang") || p.has("theme")) history.replaceState(history.state, "", location.pathname + location.hash);
    history.replaceState({ i: 0 }, "", location.href);
    window.addEventListener("popstate", (e) => {
      navIdx = (e.state as { i?: number } | null)?.i ?? navIdx + 1;
      navMax = Math.max(navMax, navIdx);
      routeFromHash();
    });
    if (location.hash.length > 2) routeFromHash();
    if (matchMedia("(pointer: coarse)").matches) {
      document.addEventListener("selectionchange", () => {
        const sel = window.getSelection();
        const w = sel?.toString().trim() ?? "";
        pick = w && w.length <= 40 && /^[\p{L}'-]+$/u.test(w) && sel?.anchorNode && mainEl?.contains(sel.anchorNode) ? w : "";
      });
    }
  }

  // ---------- bản web: địa chỉ "#/en/<từ>", "#/vi/<từ>", "#/q/<chuỗi>", "#/about", "#/settings" (UC-W03) ----------
  const enc = (w: string) => encodeURIComponent(w).replace(/%20/g, "+");
  const dec = (w: string) => decodeURIComponent(w.replace(/\+/g, "%20"));
  /** Ghi địa chỉ của màn hình vừa mở: thao tác của người dùng → mục mới trong lịch sử trình duyệt; còn lại → thay mục hiện tại. */
  function setHash(hash: string, push: boolean) {
    if (!IS_WEB) return;
    if (push && location.hash !== hash) {
      navIdx += 1;
      navMax = navIdx;
      history.pushState({ i: navIdx }, "", hash);
    } else history.replaceState({ i: navIdx }, "", hash);
  }
  function routeFromHash() {
    const h = location.hash.replace(/^#/, "");
    if (h.startsWith("/en/")) {
      if (mode === "vien") mode = "envi"; // mục tiếng Anh: không tra theo chiều Việt–Anh
      go(dec(h.slice(4)), false);
    } else if (h.startsWith("/vi/")) go(`vi:${dec(h.slice(4))}`, false);
    else if (h.startsWith("/q/")) go(dec(h.slice(3)), false);
    else if (h === "/about") showSources(false);
    else if (h === "/settings") showSettings(false);
    else {
      screen = { kind: "home" };
      current = "";
    }
  }

  /** Bản web: xin giữ dữ liệu lâu dài, nhắc sao lưu, đồng bộ khi quay lại tab (UC-W05, W07, "hai tab"). */
  function webStartup(st: Record<string, string>) {
    persistStorage();
    const n = listInfos.reduce((a, l) => a + l.count, 0);
    const last = Number(st.last_backup ?? 0);
    if (n >= 10 && Date.now() / 1000 - last > 30 * 86400) banner = t("backupReminder", { n });
    document.addEventListener("visibilitychange", async () => {
      if (document.visibilityState !== "visible" || !status?.user_ok) return;
      await refreshLists();
      await refreshHistory();
    });
  }

  function applyLook() {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    if (palette === "rose") root.setAttribute("data-palette", "rose");
    else root.removeAttribute("data-palette");
    root.style.setProperty("--base-size", `${fontSize}px`);
    root.lang = ui.lang;
  }

  async function saveSetting(key: string, value: string) {
    if (!status?.user_ok) return;
    try {
      await api.settingSet(key, value);
    } catch (e) {
      say(t("settingFailed", { e: tErr(e) }));
    }
  }

  function setUiLang(l: UiLang) {
    ui.lang = l;
    saveSetting("ui_lang", l);
    applyLook();
  }
  function cycleTheme() {
    theme = theme === "auto" ? "dark" : theme === "dark" ? "light" : "auto";
    saveSetting("theme", theme);
    applyLook();
  }
  function togglePalette() {
    palette = palette === "rose" ? "classic" : "rose";
    saveSetting("palette", palette);
    applyLook();
  }
  function setMode(m: Mode) {
    mode = m;
    saveSetting("mode", m);
  }
  function toggleVi() {
    setMode(mode === "en" ? "envi" : "en");
  }
  function setFont(px: number) {
    fontSize = Math.min(22, Math.max(13, px));
    saveSetting("font_size", String(fontSize));
    applyLook();
  }
  function setAccent(a: Accent) {
    accent = a;
    saveSetting("accent", a);
  }
  function toggleClosed(id: string) {
    const next = new Set(closed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    closed = next;
    saveSetting("closed", [...next].join(","));
  }

  function say(msg: string, ms = 4500, action: { label: string; run: () => void } | null = null) {
    toast = msg;
    toastAction = action;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = ""), ms);
  }

  // ---------- danh sách từ (U30) ----------
  async function refreshLists() {
    listInfos = await api.lists();
    if (!listInfos.some((l) => l.id === activeList)) activeList = listInfos[0]?.id ?? 0;
    await refreshItems();
  }
  async function refreshItems() {
    if (!activeList) return;
    items = await api.listItems(activeList);
    saved = new Set(items.map((i) => `${i.word}|${i.pos}|${i.sense}`));
  }
  async function selectList(id: number) {
    activeList = id;
    saveSetting("active_list", String(id));
    await refreshItems();
  }
  async function toggleSave(key: string, label: string) {
    if (!status?.user_ok) return say(t("userDbClosed"));
    try {
      const hit = items.find((i) => `${i.word}|${i.pos}|${i.sense}` === key);
      if (hit) {
        await api.itemRemove(hit.id);
        say(t("removedFrom", { name: activeName }));
      } else {
        const [word, pos, sense] = key.split("|");
        await api.itemAdd(activeList, word, pos ?? "", sense ?? "", label);
        say(t("savedTo", { name: activeName }));
      }
    } catch (e) {
      say(tErr(e));
    }
    await refreshLists();
  }
  async function removeItem(id: number) {
    await api.itemRemove(id);
    await refreshLists();
  }
  async function submitList() {
    try {
      if (editing === "new") {
        const id = await api.listCreate(editName);
        await refreshLists();
        await selectList(id);
        say(t("listCreated", { name: editName.trim() }));
      } else if (editing === "rename") {
        await api.listRename(activeList, editName);
        await refreshLists();
      }
      editing = "";
    } catch (e) {
      say(tErr(e)); // trùng tên, tên trống…
    }
  }
  async function deleteList() {
    const l = listInfos.find((x) => x.id === activeList);
    if (!l) return;
    if (!confirm(t("confirmDeleteList", { name: l.name, n: l.count }))) return;
    await api.listDelete(l.id);
    await refreshLists();
    say(t("listDeleted", { name: l.name }));
  }
  async function exportList() {
    const l = listInfos.find((x) => x.id === activeList);
    if (!l) return;
    if (!l.count) return say(t("listEmptyExport"));
    if (IS_WEB) return exportListWeb(l.id, l.name);
    const suggested = await api.defaultExportPath(l.name);
    const path = await pickSavePath(suggested);
    if (!path) return;
    try {
      const n = await api.exportCsv(l.id, path);
      say(t("exported", { n, path }), 7000);
    } catch (e) {
      say(tErr(e), 8000);
    }
  }

  /** UC-W06: CSV dựng trong Worker, trình duyệt tải về thư mục Tải về (UTF-8 có BOM để Excel đọc đúng tiếng Việt). */
  async function exportListWeb(id: number, name: string) {
    try {
      const r = await api.exportCsvText(id);
      const file = await api.defaultExportPath(name);
      const body = "\ufeff" + r.text + "\r\n";
      if (downloadText(file, body, "text/csv;charset=utf-8")) return say(t("exportedWeb", { n: r.rows, name: file }), 7000);
      // trình duyệt trong app (Zalo, Facebook…) không tải được file → chép nội dung CSV vào clipboard
      try {
        await navigator.clipboard.writeText(r.text);
        say(t("noDownload"), 9000);
      } catch {
        copyManual = r.text;
      }
    } catch (e) {
      say(tErr(e), 8000);
    }
  }

  // ---------- sao lưu / khôi phục / xoá (bản web, UC-W07, W08) ----------
  async function backupData() {
    try {
      const b = await api.userBackup();
      const d = new Date(b.exported_at * 1000);
      const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
      const file = `ecdict-backup-${ymd}.json`;
      if (!downloadText(file, JSON.stringify(b, null, 1), "application/json")) return say(t("noDownloadBackup"), 8000);
      if (banner === t("backupReminder", { n: listInfos.reduce((a, l) => a + l.count, 0) })) banner = "";
      say(t("backedUp", { name: file }), 7000);
    } catch (e) {
      say(tErr(e), 8000);
    }
  }
  async function restoreData(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    try {
      const r = await api.userRestore(await f.text());
      const st = await api.settings();
      onlineVoices = st.online_voices === "1";
      setOnlineVoices(onlineVoices);
      await refreshLists();
      await refreshHistory();
      say(t("restored", { lists: r.lists, items: r.items, history: r.history }), 8000);
    } catch (e) {
      say(t("restoreFailed", { e: tErr(e) }), 9000);
    }
  }
  async function clearAllData() {
    if (!confirm(t("confirmClearAll"))) return;
    try {
      await api.userClear();
      activeList = 0;
      await refreshLists();
      await refreshHistory();
      say(t("clearedAll"));
    } catch (e) {
      say(tErr(e), 8000);
    }
  }
  function setOnline(on: boolean) {
    onlineVoices = on;
    setOnlineVoices(on);
    saveSetting("online_voices", on ? "1" : "0");
  }

  // ---------- lịch sử (U29) ----------
  async function refreshHistory() {
    if (status?.user_ok) historyRows = await api.history(200);
  }
  async function remember(key: string, label: string, kind: "en" | "vi") {
    if (!status?.user_ok) return;
    await api.historyAdd(key, label, kind);
    await refreshHistory();
  }
  async function clearHistory() {
    if (!confirm(t("confirmClearHistory"))) return;
    await api.historyClear();
    await refreshHistory();
  }

  // ---------- tra cứu ----------
  function onInput() {
    sugOpen = true;
    sugIndex = -1;
    clearTimeout(sugTimer);
    const q = query;
    const seq = ++sugSeq;
    if (!cleanQuery(q)) {
      suggestions = [];
      return;
    }
    sugTimer = setTimeout(async () => {
      let r: Suggestion[];
      const slow = setTimeout(() => seq === sugSeq && (sugLoading = true), 300);
      try {
        r = await api.suggest(q, mode);
      } catch {
        return; // bản web mất mạng: giữ gợi ý đang có, lỗi sẽ báo khi bấm tra
      } finally {
        clearTimeout(slow);
        if (seq === sugSeq) sugLoading = false;
      }
      if (seq === sugSeq) suggestions = r; // bỏ kết quả cũ về muộn
    }, 60);
  }

  async function go(raw: string, push = true) {
    if (!status?.ok) return;
    let q = cleanQuery(raw.replace(/^vi:/, ""));
    if (!q) return; // ô trống / toàn ký tự đặc biệt: không làm gì
    if (q.length > 60 || /[.!?]\s/.test(raw)) {
      q = q.split(" ").slice(0, 3).join(" ");
      say(t("longQuery"));
    }
    query = "";
    suggestions = [];
    sugOpen = false;
    sugIndex = -1;
    sideOpen = false;
    pick = "";
    const key = raw.startsWith("vi:") ? `vi:${q}` : q;
    const seq = ++goSeq;
    let view: LookupView;
    let entry: EnEntry | ViEntry | null = null;
    try {
      view = await api.lookup(key, mode);
      if (view.kind === "en") entry = await api.getEntry(view.word);
      else if (view.kind === "vi") entry = await api.getViEntry(view.word);
    } catch (e) {
      // bản web: lỗi mạng / dữ liệu mới — giữ nguyên màn hình đang xem, không báo "không tìm thấy"; có nút Thử lại
      if (seq === goSeq) say(tErr(e), IS_WEB ? 30000 : 8000, IS_WEB ? { label: t("retry"), run: () => go(raw, push) } : null);
      return;
    }
    if (seq !== goSeq) return; // đã có lần tra mới hơn
    if (view.kind === "empty") return;
    if (!IS_WEB && push && current && current !== key) {
      back = [...back, current];
      fwd = [];
    }
    current = key;
    if (view.kind === "en") {
      if (!entry) {
        screen = { kind: "none", query: q, suggestions: [] };
        return;
      }
      screen = { kind: "entry", entry: entry as EnEntry, via: view.via, alsoVi: view.also_vi };
      remember(view.word, view.word, "en");
    } else if (view.kind === "vi") {
      if (!entry) {
        screen = { kind: "none", query: q, suggestions: [] };
        return;
      }
      screen = { kind: "vi", entry: entry as ViEntry, alsoEn: view.also_en };
      remember(`vi:${view.word}`, view.word, "vi");
    } else if (view.kind === "choice") {
      screen = { kind: "choice", query: view.query, words: view.words, lang: view.lang };
    } else {
      screen = { kind: "none", query: view.query, suggestions: view.suggestions };
    }
    setHash(view.kind === "en" ? `#/en/${enc(view.word)}` : view.kind === "vi" ? `#/vi/${enc(view.word)}` : `#/q/${enc(key)}`, push);
    await tick();
    mainEl?.scrollTo({ top: 0 });
  }

  async function showSources(push = true) {
    sideOpen = false;
    screen = { kind: "sources", list: await api.sources() };
    current = "";
    setHash("#/about", push);
  }
  function showSettings(push = true) {
    sideOpen = false;
    screen = { kind: "settings" };
    current = "";
    setHash("#/settings", push);
  }

  function goBack() {
    if (IS_WEB) return history.back(); // bản web: dùng lịch sử của trình duyệt (UC-W03, U09)
    if (!back.length) return;
    fwd = [current, ...fwd];
    const prev = back[back.length - 1];
    back = back.slice(0, -1);
    go(prev, false);
  }
  function goFwd() {
    if (IS_WEB) return history.forward();
    if (!fwd.length) return;
    back = [...back, current];
    const next = fwd[0];
    fwd = fwd.slice(1);
    go(next, false);
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "ArrowDown" && suggestions.length) {
      e.preventDefault();
      sugOpen = true;
      sugIndex = (sugIndex + 1) % suggestions.length;
    } else if (e.key === "ArrowUp" && suggestions.length) {
      e.preventDefault();
      sugIndex = (sugIndex - 1 + suggestions.length) % suggestions.length;
    } else if (e.key === "Enter") {
      e.preventDefault();
      const s = sugIndex >= 0 ? suggestions[sugIndex] : null;
      go(s ? s.key : query);
    } else if (e.key === "Escape") {
      sugOpen = false;
    }
  }

  function onGlobalKey(e: KeyboardEvent) {
    // bản web: Alt+←/→ là phím của chính trình duyệt, không gọi thêm lần nữa
    if (!IS_WEB && e.altKey && e.key === "ArrowLeft") goBack();
    if (!IS_WEB && e.altKey && e.key === "ArrowRight") goFwd();
    if ((e.ctrlKey && e.key.toLowerCase() === "l") || (e.key === "/" && document.activeElement !== inputEl && !(document.activeElement instanceof HTMLInputElement))) {
      e.preventDefault();
      inputEl?.focus();
    }
  }

  function onDbl(e: MouseEvent) {
    // UC-U08: nhấp đúp vào một từ trong mục từ để tra
    if ((e.target as HTMLElement).closest("input, button, select, textarea")) return;
    const sel = window.getSelection()?.toString().trim() ?? "";
    if (sel && /^[\p{L}'-]+$/u.test(sel)) go(sel);
  }

  function onSpeak(text: string, a: Accent) {
    const note = speak(text, a);
    if (note) say(note);
  }

  async function onCopy(clip: { html: string; text: string }, what: string) {
    try {
      await writeClipboard(clip.html, clip.text);
      say(t("copied", { what }));
    } catch (e) {
      if (IS_WEB) copyManual = clip.text; // UC-W: trình duyệt từ chối clipboard → hiện chữ để tự chép
      else say(t("copyFailed", { e: String(e) }));
    }
  }

  const fmt = (n: number | undefined) => (n ?? 0).toLocaleString(dateLocale());
  const when = (ts: number) => {
    const d = new Date(ts * 1000);
    const today = new Date();
    return d.toDateString() === today.toDateString()
      ? d.toLocaleTimeString(dateLocale(), { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString(dateLocale(), { day: "2-digit", month: "2-digit" });
  };
  const themeName = $derived(theme === "auto" ? t("themeSystem") : theme === "dark" ? t("themeDark") : t("themeLight"));
</script>

<svelte:head><title>{APP_NAME}</title></svelte:head>
<svelte:window onkeydown={onGlobalKey} />

<div class="app">
  <header class="topbar">
    <button class="icon-btn menu-btn" onclick={() => (sideOpen = !sideOpen)} title={t("menu")} aria-label={t("menu")} aria-expanded={sideOpen}><Icon name="history" /></button>
    <div class="brand">
      <img class="logo" src={palette === "rose" ? "/logo-rose.png" : "/logo-classic.png"} alt="" width="30" height="30" />
      <span class="name">EC Advanced Learners' Dictionary</span>
    </div>

    <div class="nav">
      <button class="icon-btn" disabled={IS_WEB ? navIdx === 0 : !back.length} onclick={goBack} title={t("back")}><Icon name="back" /></button>
      <button class="icon-btn" disabled={IS_WEB ? navIdx >= navMax : !fwd.length} onclick={goFwd} title={t("forward")}><Icon name="forward" /></button>
    </div>

    <div class="search">
      <span class="search-ic"><Icon name="search" /></span>
      <input
        bind:this={inputEl}
        bind:value={query}
        oninput={onInput}
        onkeydown={onKey}
        onblur={() => setTimeout(() => (sugOpen = false), 150)}
        placeholder={mode === "vien" ? t("searchPlaceholderVi") : IS_WEB ? t("searchPlaceholderWeb") : t("searchPlaceholder")}
        spellcheck="false"
        autocomplete="off"
        autocapitalize="off"
        inputmode="search"
        enterkeyhint="search"
        aria-label={t("searchLabel")}
        disabled={!status?.ok}
      />
      {#if query}
        <button class="clear" onclick={() => { query = ""; suggestions = []; }} title={t("clear")} aria-label={t("clear")}><Icon name="x" size={14} /></button>
      {/if}
      {#if sugOpen && sugLoading && !suggestions.length}
        <ul class="sugs"><li class="sug-loading">{t("loadingSugs")}</li></ul>
      {/if}
      {#if sugOpen && suggestions.length}
        <ul class="sugs" role="listbox">
          {#each suggestions as s, i}
            <li>
              <button
                class:active={i === sugIndex}
                onmousedown={(e) => {
                  e.preventDefault();
                  go(s.key);
                }}
              >
                <span class="s-label">{s.label}</span>
                {#if s.note}<span class="s-note" class:vi={s.key.startsWith("vi:")}>{s.key.startsWith("vi:") ? t("noteVi") : s.note}</span>{/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="modes" role="tablist" aria-label={t("modeLabel")}>
      <button class:on={mode === "en"} onclick={() => setMode("en")}>{t("modeEn")}</button>
      <button class:on={mode === "envi"} onclick={() => setMode("envi")}>{t("modeEnVi")}</button>
      <button class:on={mode === "vien"} onclick={() => setMode("vien")}>{t("modeViEn")}</button>
    </div>

    <div class="uilang" role="group" aria-label={t("uiLangTitle")} title={t("uiLangTitle")}>
      <button class:on={ui.lang === "en"} onclick={() => setUiLang("en")}>E</button>
      <button class:on={ui.lang === "vi"} onclick={() => setUiLang("vi")}>V</button>
    </div>

    <button
      class="icon-btn palette"
      onclick={togglePalette}
      title={palette === "rose" ? t("paletteToClassic") : t("paletteToRose")}
      aria-label={t("paletteLabel")}
    >
      <span class="swatch" class:rose={palette === "rose"}></span>
      <span class="theme-label">{palette === "rose" ? t("paletteRose") : t("paletteClassic")}</span>
    </button>

    <button class="icon-btn theme" onclick={cycleTheme} title={t("themeTitle", { v: themeName })}>
      <Icon name={theme === "dark" ? "moon" : "sun"} />
      <span class="theme-label">{theme === "auto" ? t("themeAuto") : theme === "dark" ? t("themeDark") : t("themeLight")}</span>
    </button>
    {#if IS_WEB}
      <!-- bản web (UC-W09): tải bản Windows dùng offline, về trang Edtech Corner — mở tab mới -->
      <a class="icon-btn" href={DESKTOP_DOWNLOAD} target="_blank" rel="noopener" title={t("downloadDesktop")} aria-label={t("downloadDesktop")}>
        <Icon name="download" /><span class="wide-label">{t("offlineShort")}</span>
      </a>
      <a class="icon-btn" href={SITE_HOME} target="_blank" rel="noopener" title={t("goSite")} aria-label={t("goSite")}>
        <Icon name="home" /><span class="wide-label">EdTech Corner</span>
      </a>
    {/if}
    <button class="icon-btn" onclick={() => showSettings()} title={t("settings")} aria-label={t("settings")}><Icon name="gear" /></button>
  </header>

  {#if sideOpen}<div class="side-bg" role="presentation" onclick={() => (sideOpen = false)}></div>{/if}
  <aside class="side" class:open={sideOpen}>
    <div class="tabs">
      <button class:on={tab === "history"} onclick={() => (tab = "history")}>{t("tabHistory")}</button>
      <button class:on={tab === "lists"} onclick={() => (tab = "lists")}>{t("tabLists")}</button>
    </div>
    <div class="side-list">
      {#if tab === "history"}
        {#if historyRows.length}
          {#each historyRows as h (h.key)}
            <button class:cur={current === h.key} onclick={() => go(h.key)} title={t("lookedUpAt", { t: when(h.ts) })}>
              <Icon name="history" size={13} /> {h.label}
              {#if h.kind === "vi"}<span class="tag-vi">{t("noteVi")}</span>{/if}
              <span class="ts">{when(h.ts)}</span>
            </button>
          {/each}
          <button class="danger" onclick={clearHistory}>{t("clearHistory")}</button>
        {:else}
          <p class="empty">{t("noHistory")}</p>
        {/if}
      {:else}
        <div class="list-bar">
          <select value={activeList} onchange={(e) => selectList(Number((e.target as HTMLSelectElement).value))} aria-label={t("chooseList")}>
            {#each listInfos as l (l.id)}<option value={l.id}>{l.name} ({l.count})</option>{/each}
          </select>
          <div class="list-tools">
            <button title={t("newList")} onclick={() => { editing = "new"; editName = ""; }}><Icon name="plus" size={14} /></button>
            <button title={t("rename")} onclick={() => { editing = "rename"; editName = activeName; }}><Icon name="pencil" size={14} /></button>
            <button title={t("exportCsv")} onclick={exportList}><Icon name="download" size={14} /></button>
            <button title={t("deleteList")} onclick={deleteList}><Icon name="trash" size={14} /></button>
          </div>
          {#if editing}
            <form class="list-edit" onsubmit={(e) => { e.preventDefault(); submitList(); }}>
              <input bind:value={editName} placeholder={editing === "new" ? t("newListName") : t("newName")} aria-label={t("listName")} />
              <button type="submit">{editing === "new" ? t("create") : t("save")}</button>
              <button type="button" onclick={() => (editing = "")}>{t("cancel")}</button>
            </form>
          {/if}
        </div>
        {#if items.length}
          {#each items as it (it.id)}
            <div class="item" class:gone={!it.exists}>
              <button onclick={() => it.exists && go(it.word)} disabled={!it.exists} title={it.exists ? "" : t("goneTitle")}>
                <Icon name="star-fill" size={12} /> {it.label}
              </button>
              {#if !it.exists}<span class="gone-note">{t("goneNote")}</span>{/if}
              <button class="x" title={t("removeFromList")} onclick={() => removeItem(it.id)}><Icon name="x" size={12} /></button>
            </div>
          {/each}
        {:else}
          <p class="empty">{t("emptyList", { name: activeName })}</p>
        {/if}
      {/if}
    </div>
    <button class="side-foot" onclick={() => showSources()}>{t("sourcesLink")}</button>
  </aside>

  <main class="main" bind:this={mainEl} ondblclick={onDbl}>
    <div class="content">
      {#if banner}
        <div class="notice warn">
          {banner}
          {#if bannerReload}<button class="k" onclick={() => location.reload()}>{t("reload")}</button>{/if}
          <button class="k" onclick={() => (banner = "")}>{t("close")}</button>
        </div>
      {/if}
      {#if !status}
        <p class="muted">{t("opening")}</p>
      {:else if !status.ok && IS_WEB}
        <section class="recover">
          <h1>{t("webDownTitle")}</h1>
          <p>{tErr(status.error)}</p>
          <p>{t("webDownHelp")}</p>
          <p>
            <button class="k" onclick={() => location.reload()}>{t("retry")}</button>
            <a class="k" href={DESKTOP_DOWNLOAD} target="_blank" rel="noopener">{t("downloadDesktop")}</a>
          </p>
        </section>
      {:else if !status.ok}
        <section class="recover">
          <h1>{t("recoverTitle")}</h1>
          <p>{tErr(status.error)}</p>
          <p class="muted">{t("recoverPath")} <code>{status.path}</code></p>
          <p>{t("recoverHelp")}</p>
        </section>
      {:else if screen.kind === "home"}
        <section class="home">
          <h1>{APP_NAME}</h1>
          <p>
            {t("homeStats", {
              headwords: fmt(status.counts.headwords),
              entries: fmt(status.counts.entries),
              vi: fmt(status.counts.vi_headwords),
              ai: fmt(status.counts.entries_ai),
              ver: status.meta.data_version,
            })}
          </p>
          <ul class="tips">
            <li>{t("tipForms")} <button class="k" onclick={() => go("went")}>went</button>,
              <button class="k" onclick={() => go("children")}>children</button>, <button class="k" onclick={() => go("better")}>better</button></li>
            <li>{t("tipSpelling")} <button class="k" onclick={() => go("recieve")}>recieve</button>,
              <button class="k" onclick={() => go("definately")}>definately</button></li>
            <li>{t("tipPhrases")} <button class="k" onclick={() => go("give up")}>give up</button>,
              <button class="k" onclick={() => go("by the way")}>by the way</button></li>
            <li>{t("tipVi")} <button class="k" onclick={() => go("vi:ngân hàng")}>ngân hàng</button>,
              <button class="k" onclick={() => go("vi:hoc sinh")}>hoc sinh</button>, <button class="k" onclick={() => go("vi:nha")}>nha</button></li>
            <li>{t("tipSave")}</li>
            <li>{t("tipDbl")}</li>
          </ul>
          <div class="home-words">
            {#each ["the", "get", "make", "take", "have", "go", "time", "people"] as w}
              <button class="big" onclick={() => go(w)}>{w}</button>
            {/each}
          </div>
          {#if IS_WEB}
            <p class="desktop-dl"><a href={DESKTOP_DOWNLOAD} target="_blank" rel="noopener">{t("downloadDesktop")}</a></p>
          {/if}
        </section>
      {:else if screen.kind === "entry"}
        {#if screen.via}<div class="notice">{describeVia(screen.via)}.</div>{/if}
        {#if screen.alsoVi}
          {@const v = screen.alsoVi}
          <div class="notice">{t("alsoInViEn")} <button class="k" onclick={() => go(`vi:${v}`)}>{v}</button></div>
        {/if}
        {#key screen.entry.word}
          <Entry
            entry={screen.entry}
            {showVi}
            {saved}
            {accent}
            {closed}
            onLookup={(w) => go(w)}
            {onSpeak}
            onToggleSave={toggleSave}
            onToggleVi={toggleVi}
            {onCopy}
          />
        {/key}
      {:else if screen.kind === "vi"}
        {#if mode !== "vien"}<div class="notice">{t("showingViEn")}</div>{/if}
        {#if screen.alsoEn}
          {@const w = screen.alsoEn}
          <div class="notice">{t("alsoInEnEn")} <button class="k" onclick={() => go(w)}>{w}</button></div>
        {/if}
        {#key screen.entry.word}
          <ViEntryView entry={screen.entry} onLookup={(w) => go(w)} {onSpeak} />
        {/key}
      {:else if screen.kind === "choice"}
        {@const lang = screen.lang}
        <section class="none">
          <h2>{lang === "vi" ? t("choiceVi", { q: screen.query }) : t("choiceEn", { q: screen.query })}</h2>
          <div class="home-words">
            {#each screen.words as k}<button class="big" onclick={() => go(lang === "vi" ? `vi:${k}` : k)}>{k}</button>{/each}
          </div>
        </section>
      {:else if screen.kind === "none"}
        <section class="none">
          <h2>{t("notFound", { q: screen.query })}</h2>
          {#if screen.suggestions.length}
            <p>{t("didYouMean")}</p>
            <div class="home-words">
              {#each screen.suggestions as s}<button class="big" onclick={() => go(s.word)}>{s.word}</button>{/each}
            </div>
          {:else}
            <p class="muted">{t("noSimilar")}</p>
          {/if}
        </section>
      {:else if screen.kind === "settings"}
        <section class="settings">
          <h1>{t("settings")}</h1>
          <div class="row">
            <div class="lab">{t("setUiLang")}</div>
            <div class="ctl seg">
              <button class:on={ui.lang === "en"} onclick={() => setUiLang("en")}>English</button>
              <button class:on={ui.lang === "vi"} onclick={() => setUiLang("vi")}>Tiếng Việt</button>
            </div>
          </div>
          <div class="row">
            <div class="lab">{t("setFont")}</div>
            <div class="ctl">
              <button class="step" onclick={() => setFont(fontSize - 1)} aria-label={t("smaller")}>A−</button>
              <input type="range" min="13" max="22" value={fontSize} oninput={(e) => setFont(Number((e.target as HTMLInputElement).value))} aria-label={t("setFont")} />
              <button class="step" onclick={() => setFont(fontSize + 1)} aria-label={t("larger")}>A+</button>
              <span class="val">{fontSize}px</span>
            </div>
          </div>
          <div class="row">
            <div class="lab">{t("setTheme")}</div>
            <div class="ctl seg">
              {#each [["auto", t("themeFollow")], ["light", t("themeLight")], ["dark", t("themeDark")]] as [v, label]}
                <button class:on={theme === v} onclick={() => { theme = v as typeof theme; saveSetting("theme", v); applyLook(); }}>{label}</button>
              {/each}
            </div>
          </div>
          <div class="row">
            <div class="lab">{t("setPalette")}</div>
            <div class="ctl seg">
              <button class:on={palette === "classic"} onclick={() => palette !== "classic" && togglePalette()}>{t("paletteClassicLong")}</button>
              <button class:on={palette === "rose"} onclick={() => palette !== "rose" && togglePalette()}>{t("paletteRoseLong")}</button>
            </div>
          </div>
          <div class="row">
            <div class="lab">{t("setAccent")}</div>
            <div class="ctl seg">
              <button class:on={accent === "uk"} onclick={() => setAccent("uk")}>{t("accentUk")}</button>
              <button class:on={accent === "us"} onclick={() => setAccent("us")}>{t("accentUs")}</button>
              <button class="test" onclick={() => onSpeak("The weather is lovely today.", accent)}>{t("tryVoice")}</button>
            </div>
          </div>
          {#if IS_WEB}
            <div class="row top">
              <div class="lab">{t("setOnlineVoices")}</div>
              <div class="ctl paths">
                <label><input type="checkbox" checked={onlineVoices} onchange={(e) => setOnline((e.target as HTMLInputElement).checked)} /> {t("onlineVoicesNote")}</label>
              </div>
            </div>
          {/if}
          <div class="row top">
            <div class="lab">{t("setOpenSections")}</div>
            <div class="ctl checks">
              {#each SECTIONS as [id, key]}
                <label><input type="checkbox" checked={!closed.has(id)} onchange={() => toggleClosed(id)} /> {t(key)}</label>
              {/each}
            </div>
          </div>
          <div class="row top">
            <div class="lab">{t("setData")}</div>
            <div class="ctl paths">
              <div>{t("dataDict")} <code>{status.path}</code> ({t("dataVersion", { v: status.meta.data_version })})</div>
              {#if IS_WEB}
                <div>{t("dataUser")} {status.user_path === "indexeddb" ? t("webStore_indexeddb") : t("webStore_memory")}</div>
                <div class="muted">{t("dataNoteWeb")}</div>
                <div class="data-btns">
                  <button onclick={backupData}>{t("backupBtn")}</button>
                  <button onclick={() => restoreInput?.click()}>{t("restoreBtn")}</button>
                  <input bind:this={restoreInput} type="file" accept=".json,application/json" hidden onchange={restoreData} />
                  <button class="danger" onclick={clearAllData}>{t("clearAllBtn")}</button>
                </div>
              {:else}
                <div>{t("dataUser")} <code>{status.user_path ?? "—"}</code></div>
                <div class="muted">{t("dataNote")}</div>
              {/if}
            </div>
          </div>
          <div class="row">
            <div class="lab">{t("setAbout")}</div>
            <div class="ctl"><button class="link" onclick={() => showSources()}>{t("sourcesLink")}</button></div>
          </div>
        </section>
      {:else if screen.kind === "sources"}
        <About sources={screen.list} {status} logo={palette === "rose" ? "/logo-rose.png" : "/logo-classic.png"} />
      {/if}
      {#if IS_WEB}
        <footer class="site-foot">
          {t("footData")} · <button class="k" onclick={() => showSources()}>{t("footAbout")}</button> ·
          <a href={SITE_HOME} target="_blank" rel="noopener">EdTech Corner</a>
        </footer>
      {/if}
    </div>
  </main>

  {#if pick}
    <button class="pick" onmousedown={(e) => e.preventDefault()} onclick={() => { const w = pick; window.getSelection()?.removeAllRanges(); go(w); }}>
      <Icon name="search" size={15} /> {t("lookUpSel", { w: pick })}
    </button>
  {/if}

  {#if toast}
    <div class="toast" role="status">
      {toast}
      {#if toastAction}
        <button
          class="toast-btn"
          onclick={() => {
            const run = toastAction?.run; // lấy hàm TRƯỚC khi xoá: giá trị trong template đọc lại toastAction
            toast = "";
            toastAction = null;
            run?.();
          }}>{toastAction.label}</button>
      {/if}
    </div>
  {/if}
  {#if copyManual}
    <div class="modal-bg" role="presentation" onclick={(e) => e.target === e.currentTarget && (copyManual = "")}>
      <div class="modal" role="dialog" aria-modal="true" aria-label={t("copyManualTitle")}>
        <h2>{t("copyManualTitle")}</h2>
        <p class="muted">{t("copyManualHint")}</p>
        <textarea readonly rows="10" onfocus={(e) => (e.target as HTMLTextAreaElement).select()}>{copyManual}</textarea>
        <div class="modal-foot"><button onclick={() => (copyManual = "")}>{t("closeBtn")}</button></div>
      </div>
    </div>
  {/if}
</div>

<style>
  .data-btns {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 6px;
  }
  .data-btns button {
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
    border-radius: 6px;
    padding: 5px 10px;
    font: inherit;
    font-size: 0.88rem;
    cursor: pointer;
  }
  .data-btns button.danger {
    color: #b3261e;
    border-color: currentColor;
  }
  .modal-bg {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: grid;
    place-items: center;
    z-index: 50;
    padding: 16px;
  }
  .modal {
    background: var(--surface);
    color: var(--ink);
    border-radius: 10px;
    padding: 16px 18px;
    width: min(640px, 100%);
    box-shadow: var(--shadow);
  }
  .modal h2 {
    margin: 0 0 6px;
    font-size: 1.1rem;
  }
  .modal textarea {
    width: 100%;
    box-sizing: border-box;
    font: 0.85rem var(--mono);
    background: var(--surface-2);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 8px;
  }
  .modal-foot {
    display: flex;
    justify-content: flex-end;
    margin-top: 10px;
  }
  .app {
    display: grid;
    grid-template-columns: 220px 1fr;
    grid-template-rows: auto 1fr;
    height: 100vh;
  }
  .topbar {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 10px 16px;
    background: var(--brand-bg, var(--brand));
    color: var(--brand-ink);
  }
  .swatch {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.8);
    background: linear-gradient(135deg, #0b3db8 50%, #0bbfcf 50%);
  }
  .swatch.rose {
    background: linear-gradient(135deg, #c2337f 50%, #7b45c9 50%);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 196px;
  }
  .logo {
    width: 30px;
    height: 30px;
    display: block;
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.25));
  }
  .name {
    font-weight: 600;
  }
  .nav {
    display: flex;
    gap: 4px;
  }
  .icon-btn {
    border: 0;
    background: rgba(255, 255, 255, 0.08);
    color: inherit;
    border-radius: 6px;
    height: 34px;
    min-width: 34px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    cursor: pointer;
    padding: 0 8px;
  }
  .icon-btn:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .theme-label {
    font-size: 0.8rem;
  }
  .search {
    position: relative;
    flex: 1;
    max-width: 620px;
  }
  .search input {
    width: 100%;
    height: 38px;
    border-radius: 8px;
    border: 0;
    padding: 0 36px 0 36px;
    font-size: 1rem;
    background: var(--surface);
    color: var(--ink);
    outline: none;
  }
  .search input:focus {
    box-shadow: 0 0 0 3px rgba(95, 183, 204, 0.45);
  }
  .search-ic {
    position: absolute;
    left: 11px;
    top: 11px;
    color: var(--ink-3);
    display: grid;
  }
  .clear {
    position: absolute;
    right: 8px;
    top: 9px;
    border: 0;
    background: none;
    color: var(--ink-3);
    cursor: pointer;
    display: grid;
    padding: 2px;
  }
  .sugs {
    position: absolute;
    top: 42px;
    left: 0;
    right: 0;
    list-style: none;
    margin: 0;
    padding: 4px;
    background: var(--surface);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
    z-index: 20;
  }
  .sugs button {
    width: 100%;
    display: flex;
    justify-content: space-between;
    border: 0;
    background: none;
    padding: 7px 10px;
    border-radius: 6px;
    cursor: pointer;
    text-align: left;
  }
  .sugs button.active,
  .sugs button:hover {
    background: var(--accent-soft);
  }
  .s-label {
    font-weight: 600;
  }
  .s-note {
    color: var(--ink-3);
    font-size: 0.85rem;
  }
  .modes {
    display: flex;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 3px;
  }
  .modes button {
    border: 0;
    background: none;
    color: inherit;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.88rem;
    opacity: 0.8;
  }
  .modes button.on {
    background: var(--brand-ink);
    color: var(--brand);
    opacity: 1;
    font-weight: 600;
  }

  .side {
    background: var(--surface);
    border-right: 1px solid var(--line);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .tabs {
    display: flex;
    border-bottom: 1px solid var(--line);
  }
  .tabs button {
    flex: 1;
    border: 0;
    background: none;
    padding: 9px 4px;
    font-size: 0.82rem;
    cursor: pointer;
    color: var(--ink-2);
    border-bottom: 2px solid transparent;
  }
  .tabs button.on {
    color: var(--ink);
    font-weight: 600;
    border-bottom-color: var(--accent);
  }
  .side-list {
    overflow: auto;
    padding: 6px 8px 16px;
  }
  .side-list button {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    border: 0;
    background: none;
    text-align: left;
    padding: 4px 8px;
    border-radius: 5px;
    cursor: pointer;
    color: var(--ink);
  }
  .side-list button:hover {
    background: var(--surface-2);
  }
  .side-list button.cur {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }
  .side-list .danger {
    color: #b3412f;
    margin-top: 8px;
    font-size: 0.85rem;
  }
  .empty {
    color: var(--ink-3);
    font-size: 0.88rem;
    padding: 8px;
  }

  .main {
    overflow: auto;
    min-width: 0;
  }
  .content {
    max-width: 1040px;
    padding: 22px 28px 40px;
    margin: 0 auto;
  }
  .notice {
    background: var(--accent-soft);
    color: var(--ink);
    border-radius: 8px;
    padding: 8px 14px;
    margin-bottom: 12px;
    font-size: 0.92rem;
  }
  .k {
    border: 0;
    background: none;
    color: var(--accent);
    font-weight: 600;
    cursor: pointer;
    padding: 0;
    text-decoration: underline;
  }
  .home h1 {
    font-family: var(--serif);
    margin: 4px 0 8px;
  }
  .tips {
    color: var(--ink-2);
    padding-left: 1.2em;
  }
  .tips li {
    margin: 4px 0;
  }
  .home-words {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
  }
  .big {
    border: 1px solid var(--line);
    background: var(--surface);
    border-radius: 8px;
    padding: 8px 16px;
    font-family: var(--serif);
    font-size: 1.1rem;
    cursor: pointer;
    color: var(--ink);
    box-shadow: var(--shadow);
  }
  .big:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .none h2 {
    font-family: var(--serif);
  }
  .muted {
    color: var(--ink-3);
  }
  .s-note.vi {
    color: var(--vi);
  }
  .tag-vi {
    margin-left: auto;
    font-size: 0.65rem;
    color: var(--vi);
  }
  .side-foot {
    margin-top: auto;
    border: 0;
    border-top: 1px solid var(--line);
    background: none;
    padding: 10px 14px;
    text-align: left;
    color: var(--ink-3);
    font-size: 0.82rem;
    cursor: pointer;
  }
  .side-foot:hover {
    color: var(--accent);
  }
  .recover h1 {
    font-family: var(--serif);
  }
  .recover code {
    font-family: var(--mono);
    font-size: 0.85rem;
  }
  .icon-btn.palette,
  .icon-btn.theme {
    padding: 0 10px;
  }
  .ts {
    margin-left: auto;
    font-size: 0.7rem;
    color: var(--ink-3);
  }
  .list-bar {
    padding: 6px 4px 8px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 6px;
  }
  .list-bar select {
    width: 100%;
    padding: 5px 6px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.88rem;
  }
  .list-tools {
    display: flex;
    gap: 2px;
    margin-top: 4px;
  }
  .side-list .list-tools button {
    width: auto;
    padding: 4px 7px;
    color: var(--ink-2);
  }
  .list-edit {
    display: flex;
    gap: 4px;
    margin-top: 6px;
  }
  .list-edit input {
    flex: 1;
    min-width: 0;
    padding: 4px 6px;
    border: 1px solid var(--accent);
    border-radius: 5px;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.85rem;
  }
  .side-list .list-edit button {
    width: auto;
    padding: 4px 6px;
    font-size: 0.8rem;
    border: 1px solid var(--line);
  }
  .item {
    display: flex;
    align-items: center;
  }
  .item > button:first-child {
    flex: 1;
    min-width: 0;
  }
  .side-list .item .x {
    width: auto;
    padding: 4px;
    color: var(--ink-3);
    visibility: hidden;
  }
  .item:hover .x,
  .item.gone .x {
    visibility: visible;
  }
  .item.gone > button:first-child {
    color: var(--ink-3);
    text-decoration: line-through;
  }
  .gone-note {
    font-size: 0.65rem;
    color: #b3412f;
    white-space: nowrap;
  }
  .notice.warn {
    background: var(--gw-soft);
  }
  .settings h1 {
    font-family: var(--serif);
  }
  .settings .row {
    display: grid;
    grid-template-columns: 200px 1fr;
    gap: 16px;
    align-items: center;
    padding: 14px 0;
    border-bottom: 1px solid var(--line);
  }
  .settings .row.top {
    align-items: start;
  }
  .settings .lab {
    font-weight: 600;
  }
  .settings .ctl {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .settings .seg button,
  .settings .step {
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
  }
  .settings .seg button.on {
    background: var(--accent);
    color: var(--surface);
    border-color: var(--accent);
  }
  .settings .seg .test {
    margin-left: 8px;
    color: var(--accent);
  }
  .settings .link {
    border: none;
    background: none;
    padding: 0;
    color: var(--accent);
    font: inherit;
    cursor: pointer;
    text-decoration: underline;
  }
  .settings .val {
    color: var(--ink-3);
    font-size: 0.9rem;
  }
  .settings .checks {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px 18px;
  }
  .settings .paths {
    flex-direction: column;
    align-items: start;
    font-size: 0.88rem;
    gap: 4px;
  }
  .settings code {
    font-family: var(--mono);
    font-size: 0.82rem;
    word-break: break-all;
  }
  .uilang {
    display: flex;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 3px;
  }
  .uilang button {
    border: 0;
    background: none;
    color: inherit;
    width: 26px;
    height: 28px;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 700;
    font-size: 0.82rem;
    opacity: 0.75;
  }
  .uilang button.on {
    background: var(--brand-ink);
    color: var(--brand);
    opacity: 1;
  }
  .name {
    white-space: nowrap;
  }
  .toast {
    position: fixed;
    bottom: 18px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--ink);
    color: var(--bg);
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 0.9rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
    z-index: 50;
    max-width: 90vw;
  }

  .menu-btn {
    display: none;
  }
  a.icon-btn {
    text-decoration: none;
  }
  .wide-label {
    font-size: 0.8rem;
    white-space: nowrap;
  }
  /* nhãn chữ cạnh hai nút liên kết chỉ hiện khi thanh trên cùng đủ rộng */
  @media (max-width: 1679px) {
    .wide-label {
      display: none;
    }
  }
  .sug-loading {
    padding: 7px 10px;
    color: var(--ink-3);
    font-size: 0.88rem;
  }
  .toast-btn {
    margin-left: 10px;
    border: 1px solid currentColor;
    background: none;
    color: inherit;
    border-radius: 5px;
    padding: 2px 10px;
    font: inherit;
    cursor: pointer;
  }
  .site-foot {
    margin-top: 32px;
    padding-top: 10px;
    border-top: 1px solid var(--line);
    font-size: 0.8rem;
    color: var(--ink-3);
  }
  .site-foot a {
    color: inherit;
  }
  .desktop-dl {
    margin-top: 18px;
  }
  .desktop-dl a {
    color: var(--accent);
    font-weight: 600;
  }
  .pick {
    position: fixed;
    left: 50%;
    bottom: calc(18px + env(safe-area-inset-bottom));
    transform: translateX(-50%);
    z-index: 45;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 0;
    border-radius: 999px;
    padding: 10px 18px;
    background: var(--accent);
    color: #fff;
    font: inherit;
    font-weight: 600;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
    white-space: nowrap;
    max-width: calc(100vw - 32px);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .side-bg {
    display: none;
  }
  .main {
    touch-action: manipulation;
  }

  @media (max-width: 860px) {
    .app {
      grid-template-columns: 1fr;
      height: 100dvh;
    }
    .brand .name,
    .theme-label {
      display: none;
    }
    .brand {
      min-width: 0;
    }
    /* lịch sử / danh sách: ngăn kéo trượt từ trái (trước đây bị ẩn hẳn trên màn hình hẹp) */
    .menu-btn {
      display: inline-flex;
    }
    .side {
      position: fixed;
      top: 0;
      left: 0;
      bottom: 0;
      width: min(300px, 86vw);
      z-index: 41;
      transform: translateX(-102%);
      transition: transform 0.18s ease-out;
      box-shadow: 4px 0 24px rgba(0, 0, 0, 0.2);
    }
    .side.open {
      transform: none;
    }
    .side-bg {
      display: block;
      position: fixed;
      inset: 0;
      z-index: 40;
      background: rgba(0, 0, 0, 0.35);
    }
  }

  /* thanh trên cùng chật dần: bỏ chữ cạnh nút giao diện, rồi bỏ tên app cạnh logo */
  @media (max-width: 1440px) {
    .theme-label {
      display: none;
    }
  }
  @media (max-width: 1024px) {
    .brand .name {
      display: none;
    }
    .brand {
      min-width: 0;
    }
  }

  /* điện thoại, máy tính bảng dọc (UC-W02): thanh trên cùng nhiều hàng, ô tìm cả chiều ngang, nút đủ lớn để chạm */
  @media (max-width: 900px) {
    .topbar {
      flex-wrap: wrap;
      gap: 8px;
      padding: 8px 10px;
    }
    .nav,
    .icon-btn.palette {
      display: none;
    }
    .brand {
      flex: 1;
    }
    .search {
      order: 10;
      flex-basis: 100%;
      max-width: none;
    }
    .search input {
      height: 42px;
      font-size: 16px; /* < 16px thì iOS tự phóng to khi gõ */
    }
    .modes {
      order: 11;
      flex-basis: 100%;
    }
    .modes button {
      flex: 1;
      padding: 8px 4px;
    }
    .icon-btn {
      height: 38px;
      min-width: 38px;
    }
    .content {
      padding: 14px 14px 72px;
    }
    .sugs button {
      padding: 10px 10px;
    }
    .side-list button {
      padding: 9px 10px;
    }
    .settings .row {
      grid-template-columns: 1fr;
      gap: 8px;
    }
    .settings .ctl {
      flex-wrap: wrap;
    }
  }
</style>
