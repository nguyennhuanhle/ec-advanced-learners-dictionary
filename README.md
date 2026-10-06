# EC Advanced Learners' Dictionary

An offline English–English, English–Vietnamese and Vietnamese–English learner's dictionary for Windows, built from open data.
Từ điển Anh–Anh, Anh–Việt, Việt–Anh dùng offline trên Windows, dựng hoàn toàn từ dữ liệu mở.

**Download / Tải về:** [latest release (Windows installer)](../../releases/latest)

By Le Nguyen Nhu Anh (Lê Nguyễn Như Anh), [Edtech Corner](https://edtechcorner.com).

## Features

- 136,000+ English headwords and 116,000+ Vietnamese headwords; works fully offline, no account, sends nothing.
- Learner layer for the 20,000 most frequent words: simple definitions, guidewords, grammar codes, CEFR level per sense,
  examples with Vietnamese translations (drafted by AI from Wiktionary and always labelled **AI**). The full Wiktionary text is kept alongside.
- IPA (UK/US) with Windows text-to-speech, inflected forms (went → go), spelling suggestions, Vietnamese search with or without diacritics.
- Synonyms and opposites (Open English WordNet), real English–Vietnamese sentence pairs (Tatoeba), word origin, phrasal verbs and idioms.
- Word lists, history, CSV export (Excel / Anki / Quizlet), rich-text copy for Word; English or Vietnamese interface; light/dark; two colour schemes.

## Data sources

Wiktionary (English and Vietnamese editions, via Wiktextract / kaikki.org), Open English WordNet, CEFR-J Vocabulary Profile,
Octanove Vocabulary Profile, Tatoeba, ECDICT (frequency ranks and fallback IPA only). The full list with licences and attribution is in
[`pipeline/sources.toml`](pipeline/sources.toml) and on the app's About page.

## Licence

See [`LICENSE`](LICENSE). In short:

- **App** — © 2026 Le Nguyen Nhu Anh, Edtech Corner. Free of charge: you may install, use and share the unmodified installer free of charge;
  you may not sell it, remove its credits or distribute modified versions without permission. Provided "as is", without warranty.
  The name and logo belong to Edtech Corner. (The installer shows the same terms from `app/src-tauri/LICENSE.txt`.)
- **Dictionary data** — Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0), because most source data uses that licence;
  Tatoeba sentences CC BY 2.0 FR, Open English WordNet CC BY 4.0, ECDICT MIT. The app licence does not limit your rights under these data licences.

## Building from source

Requirements: Python 3.12, Node.js, Rust (stable), Windows.

```bash
python pipeline/fetch.py          # download the open sources (checksums in pipeline/sources.lock)
python pipeline/tier_stats.py     # rank the core 20,000 words
python pipeline/enrich.py prepare --top 20000   # batch plan for the core words (no AI call)
python pipeline/enrich.py run --workers 4       # optional: AI learner layer (needs agy, see below)
python pipeline/build_db.py       # build data/build/dict-core.sqlite
python pipeline/pack.py           # quality gate + data pack
python pipeline/pack.py --license-txt
npm --prefix app install
npm --prefix app run tauri build  # NSIS installer in app/src-tauri/target/release/bundle/nsis/
```

The AI learner layer (`pipeline/enrich.py run`) needs the Antigravity CLI (`agy`) with access to Gemini. If you skip it, the
dictionary shows the Wiktionary text only, and the quality gate in `pack.py` (examples, Vietnamese meanings) will not pass. Project notes (in Vietnamese): `use-cases.md`, `PLAN.md`, `PLAN-web.md`.
