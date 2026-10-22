<script lang="ts">
  // Khối Ví dụ theo cách dùng (UC-U46–U49): lọc câu theo vị trí/dạng của từ và độ dài; chép một câu hoặc cả lượt lọc,
  // dạng thường hoặc đục lỗ. Câu thật từ Tatoeba / Wikipedia, máy chọn tự động.
  import Icon from "./Icon.svelte";
  import type { Usage, UsageEx } from "./types";
  import type { Accent } from "./speech";
  import { ROLES, label, lenOk, sentencesClip, sourceName, split, uniq, type LenFilter } from "./usage";
  import { t } from "./i18n.svelte";

  let {
    usage,
    word,
    accent,
    onCopy,
    onSpeak,
  }: {
    usage: Usage;
    word: string;
    accent: Accent;
    onCopy: (clip: { html: string; text: string }, what: string) => void;
    onSpeak: (text: string, accent: Accent) => void;
  } = $props();

  const byRole = (pos: string, role: string) =>
    usage.examples.filter((e) => e.kind === "role" && e.pos === pos && e.key === role);
  const corpusN = (pos: string, role: string) => usage.roles.find((r) => r.pos === pos && r.role === role)?.n ?? 0;

  const groups = $derived(
    Object.entries(ROLES)
      .map(([pos, rows]) => ({ pos, rows: rows.map((row) => ({ row, n: byRole(pos, row[0]).length })) }))
      .filter((g) => g.rows.some((r) => r.n)),
  );

  let role = $state<Record<string, string>>({});
  let len = $state<LenFilter>("any");
  // mặc định: vị trí gặp nhiều nhất trong corpus (trong các vị trí có câu)
  const current = (pos: string, rows: { row: [string, string, string]; n: number }[]) =>
    role[pos] ??
    rows.filter((r) => r.n).sort((x, y) => corpusN(pos, y.row[0]) - corpusN(pos, x.row[0]))[0]?.row[0] ??
    "";
  const shown = (pos: string, r: string): UsageEx[] => uniq(byRole(pos, r)).filter((e) => lenOk(e, len));

  const LENS: [LenFilter, "lenAny" | "lenShort" | "lenMid" | "lenLong"][] = [
    ["any", "lenAny"],
    ["short", "lenShort"],
    ["mid", "lenMid"],
    ["long", "lenLong"],
  ];
</script>

<div class="lens" role="group" aria-label={t("lenLabel")}>
  <span class="lab">{t("lenLabel")}</span>
  {#each LENS as [k, key]}
    <button class="chip" class:on={len === k} onclick={() => (len = k)}>{t(key)}</button>
  {/each}
</div>

{#each groups as g}
  {@const cur = current(g.pos, g.rows)}
  {@const list = shown(g.pos, cur)}
  {#if groups.length > 1}<h3><span class="pos">{g.pos}</span></h3>{/if}
  <div class="roles" role="group" aria-label={t("roleLabel")}>
    {#each g.rows as r}
      <button
        class="chip"
        class:on={cur === r.row[0]}
        disabled={!r.n}
        title={r.n ? t("roleTitle", { n: corpusN(g.pos, r.row[0]).toLocaleString() }) : t("roleNone")}
        onclick={() => (role = { ...role, [g.pos]: r.row[0] })}
      >
        {label(r.row)} <span class="cnt">{r.n}</span>
      </button>
    {/each}
  </div>
  {#if list.length}
    <ul class="ulist">
      {#each list as ex}
        {@const [pre, hit, post] = split(ex)}
        <li>
          <span class="ex-en">{pre}<strong>{hit}</strong>{post}</span>
          <span class="src">— {sourceName(ex.source)}</span>
          <span class="tools">
            <button class="tool" title={t("voiceExample")} aria-label={t("voiceExample")} onclick={() => onSpeak(ex.text, accent)}>
              <Icon name="speaker" size={14} />
            </button>
            <button class="tool" title={t("copySentence")} aria-label={t("copySentence")} onclick={() => onCopy(sentencesClip([ex], false), t("oneSentence"))}>
              <Icon name="copy" size={14} />
            </button>
            <button class="tool gap" title={t("copyGapTitle")} onclick={() => onCopy(sentencesClip([ex], true), t("oneGap"))}>___</button>
          </span>
        </li>
      {/each}
    </ul>
    <div class="bulk">
      <button class="chip" onclick={() => onCopy(sentencesClip(list, false), t("nSentences", { n: list.length }))}>
        <Icon name="copy" size={13} /> {t("copyAllShown", { n: list.length })}
      </button>
      <button class="chip" onclick={() => onCopy(sentencesClip(list, true), t("nGaps", { n: list.length }))}>
        ___ {t("copyAllGap")}
      </button>
    </div>
  {:else}
    <p class="muted">{t("noneForFilter")}</p>
  {/if}
{/each}

<style>
  h3 {
    margin: 12px 0 4px;
    font-size: 1rem;
  }
  .pos {
    font-style: italic;
    font-weight: 600;
    color: var(--accent);
  }
  .lens,
  .roles,
  .bulk {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    margin: 4px 0 6px;
  }
  .lab {
    font-size: 0.8rem;
    color: var(--ink-3);
  }
  .chip {
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink-2);
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 0.82rem;
    cursor: pointer;
    display: inline-flex;
    gap: 5px;
    align-items: center;
  }
  .chip.on {
    color: var(--accent);
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .chip:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .cnt {
    font-size: 0.72rem;
    color: var(--ink-3);
  }
  .ulist {
    margin: 4px 0 0;
    padding-left: 1.2em;
  }
  .ulist li {
    margin: 4px 0;
  }
  .ex-en {
    font-style: italic;
  }
  .src {
    font-size: 0.78rem;
    color: var(--ink-3);
  }
  .tools {
    display: inline-flex;
    gap: 1px;
    vertical-align: -3px;
    margin-left: 4px;
  }
  .tool {
    border: 0;
    background: none;
    color: var(--ink-3);
    cursor: pointer;
    padding: 2px 3px;
    display: inline-grid;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 700;
  }
  .tool:hover {
    background: var(--surface-2);
    color: var(--ink);
  }
  .muted {
    color: var(--ink-3);
    font-size: 0.88rem;
  }
</style>
