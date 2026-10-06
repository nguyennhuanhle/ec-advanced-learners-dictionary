<script lang="ts">
  // Mục Việt–Anh (UC-U24): các từ tiếng Anh tương ứng, bấm để mở mục Anh-Anh.
  import Badge from "./Badge.svelte";
  import Icon from "./Icon.svelte";
  import type { ViEntry } from "./types";
  import type { Accent } from "./speech";
  import { t } from "./i18n.svelte";

  let {
    entry,
    onLookup,
    onSpeak,
  }: {
    entry: ViEntry;
    onLookup: (w: string) => void;
    onSpeak: (text: string, accent: Accent) => void;
  } = $props();

  const SRC: Record<string, () => string> = { ai: () => t("srcAi"), wiktionary: () => t("srcTable"), viwikt: () => t("srcViwikt") };

  // gom theo từ tiếng Anh, giữ thứ tự (đã xếp theo nguồn rồi tần suất)
  const groups = $derived.by(() => {
    const m = new Map<string, { word: string; pos: string; hits: typeof entry.en }>();
    for (const h of entry.en) {
      const k = `${h.headword}|${h.pos}`;
      if (!m.has(k)) m.set(k, { word: h.headword, pos: h.pos, hits: [] });
      m.get(k)!.hits.push(h);
    }
    return [...m.values()];
  });
</script>

<article class="vi-entry">
  <header class="head">
    <div class="title-row">
      <h1 class="hw">{entry.word}</h1>
      <span class="dir">{t("dirViEn")}</span>
      <button class="speak" title={t("listenVi")} aria-label={t("listenVi")} onclick={() => onSpeak(entry.word, "vi")}>
        <Icon name="speaker" />
      </button>
    </div>
  </header>

  {#if groups.length}
    <section>
      <h2>{t("enEquivalents")}</h2>
      <ul class="eq">
        {#each groups as g}
          <li>
            <div class="eq-head">
              <button class="wlink" onclick={() => onLookup(g.word)}>{g.word}</button>
              <span class="pos">{g.pos}</span>
            </div>
            {#each g.hits as h}
              <div class="eq-sense">
                {#if h.guideword}<span class="gw">{h.guideword}</span>{/if}
                <span class="def">{h.definition}</span>
                {#if h.source === "ai"}
                  <Badge kind="ai" text="AI" title={t("aiViTitle")} />
                {:else}
                  <span class="src">{SRC[h.source]?.() ?? h.source}</span>
                {/if}
              </div>
            {/each}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if entry.wikt.length}
    <section>
      <h2>{t("wiktViEn")} <small>{t("original")}</small></h2>
      {#each entry.wikt as w}
        <div class="wk">
          <span class="pos">{w.pos}</span>
          <ol>
            {#each w.glosses as g}<li>{g}</li>{/each}
          </ol>
        </div>
      {/each}
    </section>
  {/if}

  {#if entry.tatoeba.length}
    <section>
      <h2>{t("secTatoeba")} <small>Tatoeba</small></h2>
      <ul class="tato">
        {#each entry.tatoeba as ex}
          <li>
            <span class="t-vi">{ex.vi}</span>
            <span class="t-en">{ex.en}</span>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <footer class="src-foot">{t("viFoot")}</footer>
</article>

<style>
  .head {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 18px 22px;
    box-shadow: var(--shadow);
  }
  .title-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .hw {
    font-family: var(--serif);
    font-size: 2.2rem;
    margin: 0;
  }
  .dir {
    font-size: 0.8rem;
    color: var(--vi);
    background: var(--vi-soft);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
  }
  .speak {
    border: 0;
    background: var(--accent-soft);
    color: var(--accent);
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: inline-grid;
    place-items: center;
    cursor: pointer;
  }
  section {
    margin-top: 24px;
  }
  h2 {
    font-family: var(--serif);
    font-size: 1.2rem;
    border-bottom: 1px solid var(--line);
    padding-bottom: 4px;
  }
  h2 small {
    font-family: var(--sans);
    font-weight: 400;
    font-size: 0.8rem;
    color: var(--ink-3);
    margin-left: 6px;
  }
  .eq {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .eq li {
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
  }
  .eq-head {
    display: flex;
    gap: 10px;
    align-items: baseline;
  }
  .wlink {
    border: 0;
    background: none;
    padding: 0;
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--accent);
    cursor: pointer;
  }
  .wlink:hover {
    text-decoration: underline;
  }
  .pos {
    font-style: italic;
    color: var(--ink-2);
  }
  .eq-sense {
    margin: 4px 0 0 0.2em;
    color: var(--ink-2);
    display: flex;
    gap: 8px;
    align-items: baseline;
    flex-wrap: wrap;
  }
  .gw {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--gw);
    background: var(--gw-soft);
    padding: 0.2em 0.5em;
    border-radius: 4px;
  }
  .src {
    font-size: 0.7rem;
    color: var(--ink-3);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 0.1em 0.4em;
  }
  .wk ol {
    margin: 4px 0 10px;
    color: var(--ink-2);
  }
  .tato {
    list-style: none;
    padding: 0;
  }
  .tato li {
    padding: 6px 0;
    border-bottom: 1px dashed var(--line);
  }
  .t-vi {
    display: block;
  }
  .t-en {
    display: block;
    font-style: italic;
    color: var(--ink-2);
    font-size: 0.92rem;
  }
  .src-foot {
    margin-top: 30px;
    font-size: 0.8rem;
    color: var(--ink-3);
  }
</style>
