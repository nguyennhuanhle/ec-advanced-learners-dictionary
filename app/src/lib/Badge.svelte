<script lang="ts">
  // Nhãn CEFR (A1–C2), dải tần suất, nhãn AI.
  let { kind, text, title = "" }: { kind: "cefr" | "band" | "ai" | "pos"; text: string; title?: string } = $props();
  const level = $derived(kind === "cefr" ? text[0]?.toLowerCase() : "");
</script>

<span class="badge {kind} {level}" {title}>{text}</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    line-height: 1;
    padding: 0.28em 0.5em;
    border-radius: 4px;
    white-space: nowrap;
    vertical-align: middle;
  }
  .cefr {
    color: var(--on-level);
    background: var(--b);
  }
  .cefr.a {
    background: var(--a);
  }
  .cefr.c {
    background: var(--c);
  }
  .band {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .ai {
    color: var(--ai);
    border: 1px solid currentColor;
    background: transparent;
    padding: 0.2em 0.4em;
    font-size: 0.66rem;
  }
  .pos {
    color: var(--ink-2);
    background: var(--surface-2);
    font-style: italic;
    font-weight: 500;
  }
</style>
