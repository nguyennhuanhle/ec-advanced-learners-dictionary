<script lang="ts">
  // Mục từ tiếng Anh theo cấu trúc từ điển cho người học (UC-U11..U23).
  // Chữ giao diện qua t() (English / Tiếng Việt); nội dung từ điển giữ nguyên ngôn ngữ của nó.
  import Badge from "./Badge.svelte";
  import Icon from "./Icon.svelte";
  import type { Block, EnEntry, LearnerSense, WiktSense } from "./types";
  import { entryClip, senseClip } from "./copy";
  import type { Accent } from "./speech";
  import { t, ui } from "./i18n.svelte";
  import { IS_WEB } from "./platform";

  let {
    entry,
    showVi,
    saved,
    onLookup,
    onSpeak,
    onToggleSave,
    onToggleVi,
    onCopy,
    onShare,
    accent = "us",
    closed = new Set<string>(),
  }: {
    entry: EnEntry;
    showVi: boolean;
    saved: Set<string>;
    onLookup: (w: string) => void;
    onSpeak: (text: string, accent: Accent) => void;
    onToggleSave: (key: string, label: string) => void;
    onToggleVi: () => void;
    onCopy: (clip: { html: string; text: string }, what: string) => void;
    /** app Android (UC-A06): chia sẻ link bản web của mục từ; không truyền = không hiện nút */
    onShare?: () => void;
    accent?: Accent;
    closed?: Set<string>;
  } = $props();

  // tên từ loại tiếng Việt là một phần của lớp nghĩa Việt (hiện khi bật VI), không phải chữ giao diện
  const POS_VI: Record<string, string> = {
    noun: "danh từ",
    verb: "động từ",
    adj: "tính từ",
    adv: "trạng từ",
    prep: "giới từ",
    conj: "liên từ",
    pron: "đại từ",
    det: "từ hạn định",
    intj: "thán từ",
    num: "số từ",
    phrase: "cụm từ",
    prep_phrase: "cụm giới từ",
    particle: "tiểu từ",
    proverb: "tục ngữ",
    prefix: "tiền tố",
    suffix: "hậu tố",
  };

  const TYPE_VI: Record<string, string> = { phrasal_verb: "cụm động từ", idiom: "thành ngữ", phrase: "cụm từ" };
  const TYPE_EN: Record<string, string> = { phrasal_verb: "phrasal verb", idiom: "idiom", phrase: "phrase" };

  const FORM_VI: Record<string, string> = {
    plural: "số nhiều",
    past: "quá khứ",
    participle: "phân từ",
    present: "hiện tại",
    "third-person": "ngôi 3",
    singular: "số ít",
    comparative: "so sánh hơn",
    superlative: "so sánh nhất",
  };
  const FORM_EN: Record<string, string> = { "third-person": "3rd person" };

  const forms = $derived(
    new Set([entry.word, ...entry.blocks.flatMap((b) => b.forms.map((f) => f.form))].map((x) => x.toLowerCase())),
  );

  function parts(text: string): { t: string; hit: boolean }[] {
    // Tô đậm từ đang tra (và các dạng biến đổi) trong ví dụ, không dùng {@html}.
    const out: { t: string; hit: boolean }[] = [];
    const re = /([\p{L}'’-]+)/gu;
    let last = 0;
    for (const m of text.matchAll(re)) {
      const i = m.index ?? 0;
      if (i > last) out.push({ t: text.slice(last, i), hit: false });
      out.push({ t: m[0], hit: forms.has(m[0].toLowerCase()) });
      last = i + m[0].length;
    }
    if (last < text.length) out.push({ t: text.slice(last), hit: false });
    return out;
  }

  // Nhãn dạng biến đổi theo cách ghi của từ điển cho người học (gộp các tag của Wiktionary thành một tên)
  const FORM_NAMES: [string[], string, string][] = [
    [["third-person", "singular", "present"], "3rd person", "ngôi 3 số ít"],
    [["participle", "present"], "-ing form", "dạng -ing"],
    [["participle", "past"], "past participle", "quá khứ phân từ"],
    [["past"], "past tense", "quá khứ"],
    [["plural"], "plural", "số nhiều"],
    [["comparative"], "comparative", "so sánh hơn"],
    [["superlative"], "superlative", "so sánh nhất"],
  ];
  function formLabel(tags: string[]): string {
    const set = new Set(tags);
    const hit = FORM_NAMES.find(([need]) => need.every((x) => set.has(x)));
    if (hit) return ui.lang === "vi" ? hit[2] : hit[1];
    const map = ui.lang === "vi" ? FORM_VI : FORM_EN;
    return tags.map((x) => map[x] ?? x).join(" ");
  }

  const knownSet = $derived(new Set(entry.known));
  const has = (w: string) => knownSet.has(w);
  // Wiktionary ghi âm r bằng ɹ; từ điển cho người học ghi r.
  const ipa = (s: string) => s.replace(/ɹ/g, "r");
  const nearby = $derived(entry.nearby);
  const anyAi = $derived(entry.blocks.some((b) => b.senses.length));
  const etym = $derived(entry.blocks.find((b) => b.etymology)?.etymology ?? "");
  const thesaurusBlocks = $derived(entry.blocks.filter((b) => b.thesaurus.length || b.antonyms.length));

  const sections = $derived([
    ...entry.blocks.map((b, i) => ({
      id: `pos-${i}`,
      label: (ui.lang === "vi" ? TYPE_VI : TYPE_EN)[b.entry_type] ?? b.pos,
      sub: b.senses.map((s) => s.guideword ?? "").filter(Boolean),
    })),
    ...(entry.phrasal_verbs.length ? [{ id: "phrasal", label: t("secPhrasal"), sub: [] }] : []),
    ...(entry.idioms.length ? [{ id: "idioms", label: t("secIdioms"), sub: [] }] : []),
    ...(thesaurusBlocks.length ? [{ id: "thes", label: t("secThes"), sub: [] }] : []),
    ...(entry.family.length ? [{ id: "family", label: t("secFamily"), sub: [] }] : []),
    ...(entry.tatoeba.length ? [{ id: "tatoeba", label: t("secTatoeba"), sub: [] }] : []),
    ...(etym ? [{ id: "origin", label: t("secOrigin"), sub: [] }] : []),
    ...(anyAi ? [{ id: "wikt", label: t("secWikt"), sub: [] }] : []),
    { id: "nearby", label: t("secNearby"), sub: [] },
  ]);

  // khối phụ mặc định mở/đóng theo Cài đặt; người dùng bấm tiêu đề để đổi cho mục đang xem
  let open = $state<Record<string, boolean>>({});
  const isOpen = (id: string) => open[id] ?? !closed.has(id);
  function toggle(id: string) {
    open = { ...open, [id]: !isOpen(id) };
  }

  const wordKey = $derived(`${entry.word}||`);
  const senseLabel = (b: Block, s: LearnerSense | WiktSense, n: number) =>
    `${entry.word} · ${("guideword" in s && s.guideword) || b.pos} ${n}`;

  function jump(id: string) {
    if (!isOpen(id)) open = { ...open, [id]: true };
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
</script>

{#snippet wordLink(w: string)}
  {#if has(w)}
    <button class="wlink" onclick={() => onLookup(w)}>{w}</button>
  {:else}
    <span class="wplain" title={t("notInDict")}>{w}</span>
  {/if}
{/snippet}

{#snippet speakBtn(text: string, a: Accent, label: string)}
  <button class="speak" title={t("listen", { v: label })} aria-label={t("listen", { v: label })} onclick={() => onSpeak(text, a)}>
    <Icon name="speaker" />
  </button>
{/snippet}

{#snippet fold(id: string, title: string, sub: string)}
  <h2>
    <button class="fold" onclick={() => toggle(id)} aria-expanded={isOpen(id)}>
      <span class="chev" class:shut={!isOpen(id)}>▾</span> {title}{#if sub}<small>{sub}</small>{/if}
    </button>
  </h2>
{/snippet}

<div class="layout">
  {#if IS_WEB && sections.length > 1}
    <!-- màn hình hẹp (bản web, UC-W02): mục lục khối thu thành một thanh chọn dính đầu trang -->
    <select class="toc-select" aria-label={t("inThisEntry")} onchange={(e) => { const el = e.target as HTMLSelectElement; if (el.value) jump(el.value); el.value = ""; }}>
      <option value="">{t("inThisEntry")}…</option>
      {#each sections as s}<option value={s.id}>{s.label}</option>{/each}
    </select>
  {/if}
  <article class="entry">
    <header class="head">
      <div class="title-row">
        <h1 class="hw">{entry.word}</h1>
        {#if entry.band}<Badge kind="band" text={entry.band} title={t("bandTitle")} />{/if}
        <button
          class="save-word"
          class:on={saved.has(wordKey)}
          title={saved.has(wordKey) ? t("unsaveWordTitle") : t("saveWordTitle")}
          onclick={() => onToggleSave(wordKey, entry.word)}
        >
          <Icon name={saved.has(wordKey) ? "star-fill" : "star"} />
          {saved.has(wordKey) ? t("savedWord") : t("saveWord")}
        </button>
        <button class="copy-word" title={t("copyEntryTitle")} onclick={() => onCopy(entryClip(entry, showVi), entry.word)}>
          <Icon name="copy" /> {t("copy")}
        </button>
        {#if onShare}
          <button class="copy-word" title={t("shareEntryTitle")} onclick={onShare}><Icon name="share" /> {t("shareEntry")}</button>
        {/if}
        <button class="vi-toggle" class:on={showVi} title={showVi ? t("viOnTitle") : t("viOffTitle")} onclick={onToggleVi}>
          VI
        </button>
      </div>
      <!-- nút nghe UK/US luôn có (giọng máy đọc được mọi từ); phiên âm chỉ hiện khi có. Phiên âm dự phòng của ECDICT là kiểu Anh
           nên chỉ gắn cho UK — mục chỉ có ECDICT thì dòng US không có phiên âm nhưng vẫn có nút nghe. -->
      <div class="ipa-row">
        <span class="ipa"><span class="acc">UK</span> {#if entry.ipa.uk}{ipa(entry.ipa.uk)}{/if} {@render speakBtn(entry.word, "uk", t("voiceUk"))}</span>
        <span class="ipa"><span class="acc">US</span> {#if entry.ipa.us}{ipa(entry.ipa.us)}{/if} {@render speakBtn(entry.word, "us", t("voiceUs"))}</span>
      </div>
    </header>

    {#each entry.blocks as b, bi (b.pos)}
      <section class="block" id="pos-{bi}">
        <div class="block-head">
          <span class="pos">{b.pos}</span>
          {#if showVi && POS_VI[b.pos]}<span class="pos-vi">{POS_VI[b.pos]}</span>{/if}
          {#if TYPE_EN[b.entry_type]}<span class="etype">{showVi ? TYPE_VI[b.entry_type] : TYPE_EN[b.entry_type]}</span>{/if}
          {#if b.cefr}<Badge kind="cefr" text={b.cefr} title={t("cefrWordTitle")} />{/if}
          {#if b.forms.length}
            <span class="forms">
              ({#each b.forms as f, i}{#if i}{", "}{/if}<span class="flabel">{formLabel(f.tags)}</span> <b>{f.form}</b>{/each})
            </span>
          {/if}
          <span class="grow"></span>
          {#if b.model}
            <Badge kind="ai" text="AI" title={t("aiTitle", { m: b.model })} />
          {:else}
            <span class="srcnote" title={t("wiktOnlyTitle")}>{t("wiktOnly")}</span>
          {/if}
        </div>

        {#if showVi && !b.senses.length}
          {#if b.vi_block.length}
            <div class="viblock">
              <div class="viblock-title">{t("viBlockTitle")} <small>{t("viBlockSub")}</small></div>
              <ol>
                {#each b.vi_block as g}<li>{g}</li>{/each}
              </ol>
            </div>
          {:else if !b.wiktionary.some((w) => w.vi)}
            <p class="novi">{t("noVi")}</p>
          {/if}
        {/if}

        <ol class="senses">
          {#each b.senses as s, si}
            {@const key = `${entry.word}|${b.pos}|${si}`}
            <li class="sense">
              <div class="sense-head">
                <span class="num">{si + 1}</span>
                {#if s.guideword}<span class="gw">{s.guideword}</span>{/if}
                {#if s.cefr}<Badge kind="cefr" text={s.cefr} title={t("cefrSenseTitle")} />{/if}
                {#if s.grammar}<span class="gram">{s.grammar}</span>{/if}
                {#if s.labels}<span class="labels">{s.labels}</span>{/if}
                <span class="sense-tools">
                  <button class="tool" title={t("copySenseTitle")} onclick={() => onCopy(senseClip(entry, b, s, si + 1, showVi), t("sense", { n: si + 1 }))}>
                    <Icon name="copy" size={14} />
                  </button>
                  <button
                    class="tool save-sense"
                    class:on={saved.has(key)}
                    title={saved.has(key) ? t("unsaveSenseTitle") : t("saveSenseTitle")}
                    onclick={() => onToggleSave(key, senseLabel(b, s, si + 1))}
                  >
                    <Icon name={saved.has(key) ? "star-fill" : "star"} />
                  </button>
                </span>
              </div>
              <p class="def">{s.definition}</p>
              {#if showVi && s.vi}
                <p class="vi"><span class="vi-tag">VI</span>{s.vi}</p>
              {/if}
              {#if s.examples.length}
                <ul class="examples">
                  {#each s.examples as ex}
                    <li>
                      <span class="ex-en">
                        {#each parts(ex.en) as p}{#if p.hit}<strong>{p.t}</strong>{:else}{p.t}{/if}{/each}
                      </span>
                      {@render speakBtn(ex.en, accent, t("voiceExample"))}
                      {#if showVi && ex.vi}<span class="ex-vi">{ex.vi}</span>{/if}
                    </li>
                  {/each}
                </ul>
              {/if}
            </li>
          {:else}
            {#each b.wiktionary as w, wi}
              {@const key = `${entry.word}|${b.pos}|w${wi}`}
              <li class="sense">
                <div class="sense-head">
                  <span class="num">{wi + 1}</span>
                  {#if w.grammar}<span class="gram">{w.grammar}</span>{/if}
                  {#if w.labels}<span class="labels">{w.labels}</span>{/if}
                  <span class="sense-tools">
                    <button class="tool" title={t("copySenseTitle")} onclick={() => onCopy(senseClip(entry, b, w, wi + 1, showVi), t("sense", { n: wi + 1 }))}>
                      <Icon name="copy" size={14} />
                    </button>
                    <button
                      class="tool save-sense"
                      class:on={saved.has(key)}
                      title={saved.has(key) ? t("unsaveSenseTitle") : t("saveSenseTitle")}
                      onclick={() => onToggleSave(key, senseLabel(b, w, wi + 1))}
                    >
                      <Icon name={saved.has(key) ? "star-fill" : "star"} />
                    </button>
                  </span>
                </div>
                <p class="def">{w.gloss}</p>
                {#if showVi && w.vi}
                  <p class="vi"><span class="vi-tag">VI</span>{w.vi}<span class="vi-src">{t("viTableSrc")}</span></p>
                {/if}
                {#if w.examples.length}
                  <ul class="examples">
                    {#each w.examples as ex}
                      <li>
                        <span class="ex-en">
                          {#each parts(ex) as p}{#if p.hit}<strong>{p.t}</strong>{:else}{p.t}{/if}{/each}
                        </span>
                        {@render speakBtn(ex, accent, t("voiceExample"))}
                      </li>
                    {/each}
                  </ul>
                {/if}
              </li>
            {/each}
          {/each}
        </ol>

        {#if showVi && b.senses.length && b.vi_block.length}
          <details class="more">
            <summary>{t("viBlockMore", { n: b.vi_block.length })}</summary>
            <ol class="plain">
              {#each b.vi_block as g}<li>{g}</li>{/each}
            </ol>
          </details>
        {/if}
        {#if showVi && b.translations.length}
          <details class="more">
            <summary>{t("otherTranslations", { n: b.translations.length })}</summary>
            <ul class="plain">
              {#each b.translations as tr}<li><span class="wtags">{tr.header}</span> {tr.words}</li>{/each}
            </ul>
          </details>
        {/if}
      </section>
    {/each}

    {#if entry.phrasal_verbs.length}
      <section class="extra" id="phrasal">
        {@render fold("phrasal", t("secPhrasal"), "")}
        {#if isOpen("phrasal")}
          <ul class="phrases">
            {#each entry.phrasal_verbs as p}
              <li>{@render wordLink(p.phrase)} <span class="gloss">{p.gloss}</span></li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if entry.idioms.length}
      <section class="extra" id="idioms">
        {@render fold("idioms", t("secIdioms"), "")}
        {#if isOpen("idioms")}
          <ul class="phrases">
            {#each entry.idioms as p}
              <li>{@render wordLink(p.phrase)} <span class="gloss">{p.gloss}</span></li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if thesaurusBlocks.length}
      <section class="extra" id="thes">
        {@render fold("thes", t("secThes"), "")}
        {#if isOpen("thes")}
          {#each thesaurusBlocks as b}
            <h3><span class="pos">{b.pos}</span></h3>
            <ul class="thes">
              {#each b.thesaurus as g}
                <li>
                  <div class="syn">
                    {#each g.members as m, i}{#if i}<span class="sep">·</span>{/if}{@render wordLink(m)}{/each}
                    {#if !g.members.length}<span class="muted">{t("noSynonyms")}</span>{/if}
                  </div>
                  <div class="gdef">
                    {g.definition}{#if g.hypernym.length}<span class="hyper">{t("hypernym", { w: g.hypernym.join(", ") })}</span>{/if}
                  </div>
                </li>
              {/each}
            </ul>
            {#if b.antonyms.length}
              <p class="ant"><span class="lab">{t("opposites")}</span> {#each b.antonyms as a, i}{#if i}, {/if}{@render wordLink(a)}{/each}</p>
            {/if}
          {/each}
        {/if}
      </section>
    {/if}

    {#if entry.family.length}
      <section class="extra" id="family">
        {@render fold("family", t("secFamily"), "")}
        {#if isOpen("family")}
          <div class="chips">
            {#each entry.family as w}<span class="chip">{@render wordLink(w)}</span>{/each}
          </div>
        {/if}
      </section>
    {/if}

    {#if entry.tatoeba.length}
      <section class="extra" id="tatoeba">
        {@render fold("tatoeba", t("secTatoeba"), t("secTatoebaSub"))}
        {#if isOpen("tatoeba")}
          <ul class="examples bilingual">
            {#each entry.tatoeba as ex}
              <li>
                <span class="ex-en">
                  {#each parts(ex.en) as p}{#if p.hit}<strong>{p.t}</strong>{:else}{p.t}{/if}{/each}
                </span>
                {@render speakBtn(ex.en, accent, t("voiceSentence"))}
                <span class="ex-vi">{ex.vi}</span>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if etym}
      <section class="extra" id="origin">
        {@render fold("origin", t("secOrigin"), "")}
        {#if isOpen("origin")}
          <p class="etym">{etym}</p>
        {/if}
      </section>
    {/if}

    {#if anyAi}
      <section class="extra" id="wikt">
        {@render fold("wikt", t("secWikt"), t("secWiktSub"))}
        {#if isOpen("wikt")}
          {#each entry.blocks.filter((x) => x.senses.length) as b}
            <details class="more">
              <summary><span class="pos">{b.pos}</span> · {t("wiktSenses", { n: b.wiktionary.length })}</summary>
              <ol class="plain">
                {#each b.wiktionary as w}
                  <li>
                    {#if w.grammar || w.labels}<span class="wtags">{[w.grammar, w.labels].filter(Boolean).join(" ")}</span>{/if}
                    {w.gloss}
                    {#each w.examples as x}<div class="wex">{x}</div>{/each}
                  </li>
                {/each}
              </ol>
            </details>
          {/each}
        {/if}
      </section>
    {/if}

    <section class="extra" id="nearby">
      {@render fold("nearby", t("secNearby"), "")}
      {#if isOpen("nearby")}
        <div class="chips">
          {#each nearby as w}<span class="chip">{@render wordLink(w)}</span>{/each}
        </div>
      {/if}
    </section>

    <footer class="src">{t("entryFoot")}</footer>
  </article>

  <nav class="toc" aria-label={t("inThisEntry")}>
    <div class="toc-title">{t("inThisEntry")}</div>
    {#each sections as s}
      <button class="toc-item" onclick={() => jump(s.id)}>{s.label}</button>
      {#if s.sub.length}
        <div class="toc-sub">
          {#each s.sub as g, i}<button onclick={() => jump(s.id)}>{i + 1}. {g}</button>{/each}
        </div>
      {/if}
    {/each}
  </nav>
</div>

<style>
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 210px;
    gap: 28px;
    align-items: start;
  }
  .entry {
    min-width: 0;
  }
  .head {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 18px 22px 14px;
    box-shadow: var(--shadow);
  }
  .title-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .hw {
    font-family: var(--serif);
    font-size: 2.4rem;
    font-weight: 700;
    margin: 0;
    color: var(--brand);
    letter-spacing: -0.01em;
  }
  :global(:root[data-theme="dark"]) .hw {
    color: var(--ink);
  }
  @media (prefers-color-scheme: dark) {
    :global(:root:not([data-theme="light"])) .hw {
      color: var(--ink);
    }
  }
  .save-word {
    margin-left: auto;
    display: inline-flex;
    gap: 6px;
    align-items: center;
    border: 1px solid var(--line);
    background: var(--surface);
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 0.85rem;
    cursor: pointer;
    color: var(--ink-2);
  }
  .save-word.on {
    color: var(--gw);
    border-color: var(--gw);
    background: var(--gw-soft);
  }
  .ipa-row {
    display: flex;
    gap: 22px;
    margin-top: 6px;
    flex-wrap: wrap;
  }
  .ipa {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: var(--sans);
    color: var(--ink-2);
  }
  .acc {
    font-size: 0.7rem;
    font-weight: 700;
    color: var(--ink-3);
  }
  .speak {
    border: 0;
    background: var(--accent-soft);
    color: var(--accent);
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: inline-grid;
    place-items: center;
    cursor: pointer;
    padding: 0;
    flex: none;
  }
  .speak:hover {
    filter: brightness(0.95);
  }
  .examples .speak {
    width: 20px;
    height: 20px;
    vertical-align: -4px;
    margin-left: 4px;
    background: transparent;
  }

  .block {
    margin-top: 22px;
  }
  .block-head {
    display: flex;
    align-items: baseline;
    gap: 10px;
    border-bottom: 2px solid var(--brand);
    padding-bottom: 6px;
    flex-wrap: wrap;
  }
  .pos {
    font-style: italic;
    font-weight: 600;
    color: var(--accent);
    font-size: 1.05rem;
  }
  .pos-vi {
    color: var(--vi);
    font-size: 0.9rem;
  }
  .etype {
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--accent);
    border: 1px solid var(--accent);
    border-radius: 4px;
    padding: 0.1em 0.45em;
  }
  .forms {
    color: var(--ink-2);
    font-size: 0.9rem;
  }
  .flabel {
    color: var(--ink-3);
    font-size: 0.8rem;
  }
  .grow {
    flex: 1;
  }
  .srcnote {
    font-size: 0.7rem;
    color: var(--ink-3);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 0.15em 0.45em;
  }
  .vi-toggle {
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink-3);
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
  }
  .vi-toggle.on {
    color: var(--vi);
    border-color: var(--vi);
    background: var(--vi-soft);
  }
  .viblock {
    margin: 10px 0 2px;
    background: var(--vi-soft);
    border-radius: 8px;
    padding: 8px 14px;
  }
  .viblock-title {
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--vi);
  }
  .viblock-title small {
    font-weight: 400;
    color: var(--ink-3);
    margin-left: 6px;
  }
  .viblock ol {
    margin: 4px 0;
    padding-left: 1.4em;
  }
  .vi-src {
    font-size: 0.7rem;
    font-weight: 400;
    color: var(--ink-3);
    margin-left: 8px;
  }
  .bilingual {
    margin-left: 0;
  }
  .novi {
    margin: 8px 0 0;
    font-size: 0.88rem;
    color: var(--ink-3);
    font-style: italic;
  }

  .senses {
    list-style: none;
    padding: 0;
    margin: 6px 0 0;
  }
  .sense {
    padding: 12px 0 12px;
    border-bottom: 1px solid var(--line);
  }
  .sense-head {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .num {
    font-weight: 700;
    color: var(--ink);
    min-width: 1.2em;
  }
  .gw {
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--gw);
    background: var(--gw-soft);
    padding: 0.25em 0.55em;
    border-radius: 4px;
  }
  .gram {
    font-family: var(--mono);
    font-size: 0.8rem;
    color: var(--ink-2);
  }
  .labels {
    font-style: italic;
    color: var(--ink-3);
    font-size: 0.88rem;
  }
  .sense-tools {
    margin-left: auto;
    display: inline-flex;
    gap: 2px;
  }
  .tool {
    border: 0;
    background: none;
    color: var(--ink-3);
    cursor: pointer;
    padding: 3px;
    display: inline-grid;
    border-radius: 4px;
  }
  .tool:hover {
    background: var(--surface-2);
    color: var(--ink);
  }
  .save-sense.on {
    color: var(--gw);
  }
  .copy-word {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    border: 1px solid var(--line);
    background: var(--surface);
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 0.85rem;
    cursor: pointer;
    color: var(--ink-2);
  }
  .copy-word:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
  .fold {
    border: 0;
    background: none;
    padding: 0;
    font: inherit;
    color: inherit;
    cursor: pointer;
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    text-align: left;
  }
  .chev {
    display: inline-block;
    font-size: 0.8em;
    color: var(--ink-3);
    transition: transform 0.15s;
  }
  .chev.shut {
    transform: rotate(-90deg);
  }
  .def {
    margin: 6px 0 0 1.95em;
    font-size: 1.02rem;
  }
  .vi {
    margin: 4px 0 0 1.95em;
    color: var(--vi);
    font-weight: 600;
  }
  .vi-tag {
    font-size: 0.66rem;
    font-weight: 700;
    color: var(--vi);
    background: var(--vi-soft);
    border-radius: 3px;
    padding: 0.15em 0.4em;
    margin-right: 8px;
    vertical-align: 2px;
  }
  .examples {
    margin: 6px 0 0 1.95em;
    padding-left: 1.1em;
  }
  .examples li {
    margin: 3px 0;
  }
  .ex-en {
    font-style: italic;
    color: var(--ink);
  }
  .ex-en strong {
    font-style: italic;
  }
  .ex-vi {
    display: block;
    color: var(--ink-2);
    font-size: 0.92rem;
  }

  .more {
    margin-top: 10px;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 8px 14px;
  }
  .more summary {
    cursor: pointer;
    color: var(--ink-2);
    font-size: 0.92rem;
  }
  .plain {
    margin: 8px 0 4px;
    padding-left: 1.4em;
    color: var(--ink-2);
    font-size: 0.94rem;
  }
  .wtags {
    font-size: 0.75rem;
    color: var(--ink-3);
    margin-right: 6px;
  }
  .wex {
    font-style: italic;
    color: var(--ink-3);
  }

  .extra {
    margin-top: 28px;
  }
  h2 {
    font-family: var(--serif);
    font-size: 1.25rem;
    margin: 0 0 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--line);
  }
  h2 small {
    font-family: var(--sans);
    font-weight: 400;
    font-size: 0.8rem;
    color: var(--ink-3);
    margin-left: 6px;
  }
  h3 {
    margin: 10px 0 2px;
    font-size: 1rem;
  }
  .phrases {
    list-style: none;
    padding: 0;
    margin: 0;
    columns: 2;
    column-gap: 28px;
  }
  .phrases li {
    break-inside: avoid;
    padding: 5px 0;
  }
  .gloss {
    display: block;
    color: var(--ink-2);
    font-size: 0.9rem;
  }
  .thes {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .thes li {
    padding: 6px 0;
    border-bottom: 1px dashed var(--line);
  }
  .sep {
    color: var(--ink-3);
    margin: 0 6px;
  }
  .gdef {
    color: var(--ink-3);
    font-size: 0.88rem;
  }
  .hyper {
    color: var(--ink-3);
  }
  .ant .lab {
    color: var(--ink-3);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chip {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 2px 10px;
  }
  .etym {
    color: var(--ink-2);
    margin: 0;
  }
  .wlink {
    border: 0;
    background: none;
    padding: 0;
    color: var(--accent);
    font-weight: 600;
    cursor: pointer;
  }
  .wlink:hover {
    text-decoration: underline;
  }
  .wplain {
    color: var(--ink);
    font-weight: 600;
  }
  .chip .wplain,
  .syn .wplain {
    font-weight: 400;
    color: var(--ink-2);
  }
  .muted {
    color: var(--ink-3);
  }
  .src {
    margin: 36px 0 12px;
    font-size: 0.8rem;
    color: var(--ink-3);
  }

  .toc {
    position: sticky;
    top: 12px;
    font-size: 0.88rem;
    border-left: 2px solid var(--line);
    padding-left: 12px;
    max-height: calc(100vh - 120px);
    overflow: auto;
  }
  .toc-title {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ink-3);
    margin-bottom: 6px;
  }
  .toc button {
    display: block;
    border: 0;
    background: none;
    padding: 3px 0;
    text-align: left;
    cursor: pointer;
    color: var(--ink-2);
    width: 100%;
  }
  .toc-item {
    font-weight: 600;
    color: var(--ink) !important;
  }
  .toc-sub button {
    padding-left: 10px;
    font-size: 0.8rem;
  }
  .toc button:hover {
    color: var(--accent) !important;
  }

  .toc-select {
    display: none;
  }
  @media (max-width: 980px) {
    .layout {
      grid-template-columns: 1fr;
    }
    .toc {
      display: none;
    }
    .toc-select {
      display: block;
      position: sticky;
      top: 0;
      z-index: 5;
      width: 100%;
      margin-bottom: 10px;
      padding: 8px 10px;
      font: inherit;
      font-size: 0.95rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
    }
    .phrases {
      columns: 1;
    }
  }
</style>
