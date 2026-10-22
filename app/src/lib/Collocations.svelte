<script lang="ts">
  // Khối Kết hợp từ (UC-U43): cụm theo mẫu hợp với từ loại; bấm một cụm để xem câu ví dụ chứa đúng cụm đó.
  import type { Usage } from "./types";
  import { PATTERNS, label, sourceName, split } from "./usage";
  import { t } from "./i18n.svelte";

  let { usage, word }: { usage: Usage; word: string } = $props();

  const groups = $derived(
    Object.entries(PATTERNS)
      .map(([pos, rows]) => ({
        pos,
        pats: rows
          .map((row) => ({ row, items: usage.colls.filter((c) => c.pos === pos && c.pattern === row[0]) }))
          .filter((g) => g.items.length),
      }))
      .filter((g) => g.pats.length),
  );

  let sel = $state(""); // "pos|mẫu|cụm"
  const exOf = (pos: string, pattern: string, display: string) =>
    usage.examples.find((e) => e.pos === pos && e.kind === "coll" && e.key === `${pattern}|${display}`);
</script>

{#each groups as g}
  {#if groups.length > 1}<h3><span class="pos">{g.pos}</span></h3>{/if}
  {#each g.pats as p}
    {@const open = p.items.find((c) => sel === `${g.pos}|${p.row[0]}|${c.display}`)}
    <div class="cg">
      <div class="pat">{label(p.row, word)}</div>
      <div class="items">
        {#each p.items as c, i}
          {@const key = `${g.pos}|${p.row[0]}|${c.display}`}
          {#if i}<span class="sep">·</span>{/if}
          <button class="ci" class:on={sel === key} title={t("collTitle", { n: c.n.toLocaleString() })} onclick={() => (sel = sel === key ? "" : key)}>
            {c.display}
          </button>
        {/each}
      </div>
      {#if open}
        {@const ex = exOf(g.pos, p.row[0], open.display)}
        <p class="cex">
          {#if ex}
            {@const [pre, hit, post] = split(ex)}
            <span class="ex-en">{pre}<strong>{hit}</strong>{post}</span> <span class="src">— {sourceName(ex.source)}</span>
          {:else}
            <span class="muted">{t("collNoEx")}</span>
          {/if}
        </p>
      {/if}
    </div>
  {/each}
{/each}

<style>
  h3 {
    margin: 10px 0 2px;
    font-size: 1rem;
  }
  .pos {
    font-style: italic;
    font-weight: 600;
    color: var(--accent);
  }
  .cg {
    padding: 6px 0;
    border-bottom: 1px dashed var(--line);
  }
  .pat {
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: var(--gw);
  }
  .items {
    line-height: 1.7;
  }
  .ci {
    border: 0;
    background: none;
    padding: 0 1px;
    font: inherit;
    color: var(--ink);
    cursor: pointer;
    border-radius: 3px;
  }
  .ci:hover,
  .ci.on {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .sep {
    color: var(--ink-3);
    margin: 0 5px;
  }
  .cex {
    margin: 4px 0 2px 1em;
  }
  .ex-en {
    font-style: italic;
  }
  .src,
  .muted {
    font-size: 0.8rem;
    color: var(--ink-3);
  }
</style>
