# PLAN — study-buddy

A local web app that turns study notes into flashcards and quizzes. Every card is tied to a
verbatim quote from the notes, and reviews are scheduled with SM-2.

Status: **approved and built.** The six decisions in section 15 were taken as recommended.
Changes made during the build:

- Grounding normalisation also ignores Markdown `**` and backticks (section 6).
- Use cases live in one module, `app/services.py`, between the web layer and the pure modules.
- Routes are split into `routes_pages.py`, `routes_decks.py` and `routes_study.py`; deck and notes
  deletion use `POST .../delete` forms, and a generation run has its own page, `/runs/{id}`.
- The typed quiz only counts an exact match when the expected answer contains a digit.
- Offline generation allows up to two extra definition cards per passage, so glossary lists are not cut short.

## 1. Environment (inspected 2026-10-12)

| Item | Finding | Consequence |
|---|---|---|
| Python | 3.11.9 | Target 3.11 locally, in CI and in Docker |
| Global packages | fastapi 0.95 / pydantic 1.10 (old) | Use a project `.venv`; never the global install |
| Internet | PyPI reachable | Can install and pin real versions |
| git | 2.49, identity `Omkar210404`, default branch `main` | Repo initialised in `study-buddy/` |
| Docker | not installed | Dockerfile cannot be built here; it is verified by a CI job after the first push |
| `gh` CLI | not installed | I cannot create the GitHub repo or push; you do that, the badge URL assumes `Omkar210404/study-buddy` |
| Browsers | Chrome, Edge, and a Playwright Chromium cache | Screenshots via Playwright (dev-only dependency) |
| Anki | not installed | CSV export is unit-tested for format; a real Anki import cannot be confirmed here |

Pins: same versions as my other two repos where they overlap (fastapi 0.143.0, uvicorn 0.54.0,
pydantic 2.14.0, pydantic-settings 2.15.0, httpx 0.28.1, Jinja2 3.1.6, pytest 9.1.1), plus
SQLAlchemy 2.0.x, pypdf 6.x and python-multipart at whatever exact version the venv resolves.

## 2. Architecture

```
upload / paste ──> ingestion ──> passages ──> generation ──> card drafts ──> grounding ──> storage
                   (extract,                  (offline | LLM)                validator      (SQLite)
                    split)                                                                     │
                                                              web layer (FastAPI + Jinja2 + HTMX)
                                                              review (SM-2) · quiz · progress · export
```

Each box is its own package with no imports from the web layer. The scheduler, validator,
splitter, offline generator, distractor picker and similarity check are pure functions: no
database, no clock, no network. "Today" is always passed in, so tests control the date.

## 3. Data model (SQLite via SQLAlchemy 2.0, sync sessions)

| Table | Columns that matter |
|---|---|
| `decks` | id, name, description, created_at |
| `sources` | id, deck_id, title, kind (`paste`/`txt`/`md`/`pdf`), filename, **text** (the canonical extracted text), created_at |
| `passages` | id, source_id, ordinal, section_title (nullable), text, **start_char, end_char** (offsets into `sources.text`), page (PDF only) |
| `cards` | id, deck_id, passage_id (nullable), kind (`cloze`/`definition`/`qa`), origin (`offline`/`llm`), front, back, **supporting_quote**, **source_passage** (text snapshot), quote_start, quote_end, SM-2 state: ease_factor, interval_days, repetitions, due_date, lapses, last_reviewed_at; created_at, updated_at |
| `tags`, `card_tags` | tag name; many-to-many join |
| `reviews` | id, card_id (nullable), deck_id, reviewed_at, review_date, rating 1–4, scheduled (bool), ease/interval before and after |
| `quiz_attempts` | id, card_id (nullable), deck_id, mode (`mc`/`typed`), correct, similarity, answered_at |
| `generation_runs` | id, deck_id, source_id, mode, provider, model, proposed, accepted, rejected, created_at |
| `rejected_cards` | id, run_id, passage_id, raw_json, reason |

Decisions:
- **Invariant: no card is saved without passing the grounding validator.** Offline cards pass
  by construction but go through the same function, so there is one code path.
- The card keeps a **snapshot** of the passage, so it stays verifiable after its source is deleted.
- `reviews` and `quiz_attempts` keep `deck_id` and survive card deletion, so history is not rewritten.
- Uploaded files are parsed in memory; only the extracted text is stored. The original file is not kept.
  `data/` (database) and `uploads/` are git-ignored either way.
- No manual "new blank card" form: it would break the grounding invariant. Cards can be edited
  and deleted. Editing the quote re-runs the validator against the stored passage.

## 4. Ingestion and passage splitting

- **Extract**: `.txt` / `.md` decoded as UTF-8 (fallback cp1252); PDF via `pypdf` page by page.
  A PDF with almost no extractable text is refused with: *"This looks like a scanned PDF.
  Study Buddy reads text PDFs only and does not do OCR."* Encrypted PDFs are refused too.
  Limits: 5 MB, 200 pages.
- **Canonical text**: line endings normalised; for PDFs, hyphenated line breaks joined and
  wrapped lines unwrapped. This cleaned text is what is stored, and all offsets point into it.
- **Sections**: Markdown `#` headings; for plain text, conservative heuristics (underlined
  with `===`/`---`, numbered `1.2 Title`, short ALL-CAPS line).
- **Passages**: paragraph blocks under a section. Short ones (< ~200 chars) merge with the next
  one in the same section; long ones (> ~1200 chars) split at sentence boundaries.
- **Tested invariant**: `source.text[start_char:end_char] == passage.text` for every passage.

## 5. Card generation

### 5a. Offline mode (default, no key, nothing leaves the machine)

- **Definition cards** from sentence patterns: `X is a/an/the …`, `X are …`, `X refers to …`,
  `X is defined as …`, `X means …`, `X stands for …`, `… is called X`, `… known as X`, and
  glossary lines (`**Term**: …`, `Term — …`). X must be 1–5 words and not a pronoun
  (It/This/These/There…). Front: "What is X?"; back: the definition clause; quote: the whole sentence.
- **Cloze cards**: score candidate terms (1–3 word phrases, stopwords removed) by term
  frequency in the source × how concentrated they are in few passages, with boosts for bold or
  code-formatted terms, heading terms, acronyms and numbers with units. Per passage, take the
  top sentences and blank one term each. Front: sentence with `_____`; back: the term; quote:
  the original sentence.
- Guards: sentence 6–40 words, at most 3 cards per passage, no cloze on a sentence that already
  produced a definition card, duplicates dropped, ties broken by position so output is deterministic.

### 5b. LLM mode (optional)

- Provider layer adapted (copied, not imported) from my other repos: `LLMProvider` ABC,
  `OpenAICompatibleProvider` (httpx, `/chat/completions`, `response_format: json_object`, typed
  errors for auth / rate limit / timeout / 5xx, small retry wrapper), `MockProvider`.
- Config only from env: `LLM_PROVIDER` (`none` default / `openai_compatible` / `mock`),
  `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `MOCK_LLM_MODE`. The key is never shown, logged or stored.
- One request per passage, concurrency 2, at most 20 passages per run (free-tier friendly).
  The model returns `{"cards": [{"question", "answer", "quote"}]}` with the instruction that
  `quote` must be copied character-for-character from the passage.
- Parsing: tolerate code fences, then Pydantic. The envelope is validated first, then **each
  card separately**, so one bad card does not sink the batch. Invalid JSON: one retry, then the
  passage is reported as `invalid_json`.
- **MockProvider** modes: `good` (real verbatim quotes), `fake_quotes` (quotes that are not in
  the passage), `mixed`, `invalid_json`; plus a `responses` queue for tests. Deterministic, no
  network. Anything it produces is labelled "mock" in the UI.

## 6. Grounding validator

Pure function: `validate(question, answer, quote, passage_text) -> GroundingResult`.

1. **Normalise** both quote and passage: Unicode NFKC, curly quotes → straight, en/em dash → `-`,
   every whitespace run → one space, strip wrapping quote marks. Markdown `**` and backticks are
   ignored (added during the build: models drop them when quoting, and no word is affected).
   **Case-sensitive.** No fuzzy matching.
2. Reject `quote_too_short` (< 12 chars or < 3 words) and `quote_too_long` (> 300 chars).
3. Reject `quote_not_found` unless the normalised quote is a substring of the normalised passage.
   A quote with `...` in the middle fails; that is intended.
4. Reject `duplicate` if the same normalised question already exists in the run or the deck.
5. On success, map the match back to offsets in the **original** passage and store that exact
   substring as the supporting quote. The stored quote is always the source's own text, not the
   model's retyping, and the card back highlights it inside the passage.

Rejections are saved per run and shown in a generation report (count, reason, the rejected card).

Honest limit, stated in the app and README: the check proves the quote **exists in your notes**.
It does not prove the answer follows from the quote. That is why the quote is on the card back.

## 7. SM-2 details

State per card: ease factor `EF` (start 2.5, floor 1.3), `repetitions` n (start 0), `interval` in
days. New cards are due on the day they are created.

Buttons map to SM-2 quality: **Again = 2, Hard = 3, Good = 4, Easy = 5**.

```
EF' = max(1.3, EF + 0.1 − (5 − q) × (0.08 + (5 − q) × 0.02))     # Again −0.32, Hard −0.14, Good 0, Easy +0.10
if q < 3:  n = 0, interval = 1
else:      interval = 1 if n == 0, 6 if n == 1, else round_half_up(interval × EF');  n = n + 1
due = today + interval
```

Hand-calculated example used as a test (new card, EF 2.5):

| Rating | EF after | n after | interval |
|---|---|---|---|
| Good | 2.50 | 1 | 1 |
| Good | 2.50 | 2 | 6 |
| Good | 2.50 | 3 | 15 |
| Hard | 2.36 | 4 | 35 (15 × 2.36 = 35.4) |
| Again | 2.04 | 0 | 1 |
| Easy | 2.14 | 1 | 1 |

Session rules:
- Daily queue = cards with `due_date <= today`, oldest first, with at most `NEW_CARDS_PER_DAY`
  (default 20) never-reviewed cards per day so a fresh 80-card deck does not flood the queue.
- A card rated Again comes back at the end of the same session. Those repeat ratings are logged
  with `scheduled = false` and do **not** change EF or interval; only the first rating of a due
  card moves the schedule.
- Pure SM-2, no Anki extras (no learning steps, fuzz or easy bonus). Hard and Good differ only
  through the ease factor. The README says so.

## 8. Quiz

- **Multiple choice**: correct answer = the card's back; 3 distractors from other cards' answers
  in the same deck. Excluded: answers equal to the correct one after normalisation, duplicates,
  and anything that already appears in the question text. Preference: same card kind and similar
  length. Seeded `random.Random`, so tests are deterministic. A deck with too few distinct
  answers gets fewer options (minimum 2) or a clear "not enough cards yet" message.
- **Typed answer**: normalise (casefold, strip punctuation, collapse spaces, drop a leading
  a/an/the) → exact match is correct; otherwise `difflib.SequenceMatcher` ratio ≥ 0.85 counts as
  correct and the score is shown. The expected answer is always shown next to what was typed,
  with an "I was right / I was wrong" override. Called a "similarity check" everywhere, never grading by AI.
- Quiz results are logged in `quiz_attempts` and do **not** change the SM-2 schedule.

## 9. Pages and routes

| Route | Purpose |
|---|---|
| `GET /` | Today: due counts per deck, start review, mode/privacy indicator |
| `GET /decks`, `POST /decks`, `GET /decks/{id}`, `POST /decks/{id}/edit`, `DELETE /decks/{id}` | Deck list and study view (cards, sources, search, tag and kind filters) |
| `GET /decks/{id}/cards?q=&tag=` | HTMX partial: live search |
| `GET /decks/{id}/import`, `POST /decks/{id}/sources` | Paste or upload notes |
| `GET /sources/{id}`, `DELETE /sources/{id}` | Passages with section titles and positions |
| `POST /sources/{id}/generate` | Run offline or LLM generation → report with accepted and rejected cards |
| `GET /cards/{id}/edit`, `PUT /cards/{id}`, `DELETE /cards/{id}` | HTMX inline edit / delete |
| `GET /review`, `GET /decks/{id}/review`, `GET /review/next`, `POST /review/{card_id}/rate` | Distraction-free review, HTMX card swap |
| `GET /decks/{id}/quiz?mode=mc\|typed`, `POST /quiz/answer` | Quiz |
| `GET /progress` | Due today, reviews per day (30 days), retention by deck, quiz accuracy |
| `GET /decks/{id}/export.csv` | Anki export |
| `GET /privacy` | What is stored, what is sent where in each mode, which provider host is configured |
| `POST /demo/load-sample` | Create the sample deck from the bundled notes |
| `GET /health` | Docker healthcheck |

- **Retention** = of the scheduled reviews of cards that had been reviewed before, the share not
  rated Again. Shown with its counts ("31 of 36"), and as "not enough reviews yet" when empty.
- **Anki CSV**: `Front, Back, Tags`, UTF-8, Basic note type, Anki file headers (`#separator`,
  `#html:true`, `#tags column:3`). Back = answer + the supporting quote. Tag spaces → underscores.
  Scheduling state is not exported (Anki's text import cannot take it).
- **Safety**: Jinja autoescape on (notes are untrusted text); a same-origin check on every
  state-changing request (a local app is still reachable from other browser tabs); binds to
  127.0.0.1 by default; upload size limit.
- **No outside requests from the page**: HTMX is vendored in `static/`, fonts are system fonts.
  A CDN call would contradict the "nothing leaves the machine" claim.

## 10. Design direction (DESIGN.md is the first file written after approval)

Warm paper background, one muted accent, system serif for card text at large size, system sans
for controls. The review screen shows only the card, a thin progress line and the four rating
buttons. Space flips, 1–4 rate. Single column down to 360 px. Dark mode through
`prefers-color-scheme` plus a manual toggle, as a dim warm theme rather than a black dashboard.
No sidebar, no stat tiles grid, no data-table chrome.

## 11. File layout

```
study-buddy/
  app/
    main.py  config.py  errors.py  schemas.py
    ingestion/   extract.py  splitter.py
    generation/  terms.py  offline.py  llm.py  prompts.py
    grounding/   normalise.py  validator.py
    llm/         base.py  openai_compatible.py  mock.py  factory.py  structured.py
    scheduler/   sm2.py  queue.py
    quiz/        distractors.py  similarity.py
    storage/     db.py  models.py  repo.py  stats.py
    export/      anki_csv.py
    web/         routes_decks.py  routes_sources.py  routes_cards.py  routes_review.py
                 routes_quiz.py  routes_progress.py  deps.py
                 templates/   static/ (app.css, app.js, htmx.min.js)
  sample_notes/networking-basics.md      # original synthetic notes written for this repo
  scripts/      seed_demo.py  take_screenshots.py
  tests/
  docs/screenshots/
  DESIGN.md  PLAN.md  README.md  LICENSE  Dockerfile  .dockerignore
  .github/workflows/ci.yml  .env.example  .gitignore
  requirements.txt  requirements-dev.txt  pyproject.toml
```

## 12. Tests (pytest, no internet)

An autouse fixture blocks outbound sockets, so a test that tries the network fails loudly.

| File | Covers |
|---|---|
| `test_splitter.py` | Markdown and plain-text sections, merge/split thresholds, offset invariant |
| `test_extract.py` | txt/md decoding, a hand-built text PDF, blank PDF refused as scanned |
| `test_offline_generation.py` | each definition pattern, pronoun rejection, cloze term choice, determinism, every card on the sample notes passes grounding |
| `test_grounding.py` | accepts real quotes (incl. whitespace and curly-quote differences), rejects fake, elided, too-short, too-long and duplicate; offsets map back to the original text |
| `test_llm_generation.py` | mock `good` / `fake_quotes` / `mixed` / `invalid_json`, per-card schema failures, retry on bad JSON, rejection report |
| `test_openai_compatible.py` | payload and error mapping through `httpx.MockTransport` |
| `test_sm2.py` | the table in section 7, the EF floor, Again resets, repeat ratings do not reschedule |
| `test_queue.py` | due selection, new-card limit, Again returns in the session |
| `test_distractors.py` | never the correct answer, no duplicates, same deck only, small-deck behaviour, seeded |
| `test_similarity.py` | exact, close, wrong, article and punctuation handling |
| `test_anki_csv.py` | headers, quoting, newlines, tags, Unicode |
| `test_stats.py` | due today, reviews per day, retention from a known history |
| `test_routes.py` | TestClient: create deck → import → generate → review → rate → quiz → progress → export, edit/delete, search, cross-origin POST refused |

## 13. Commit plan (small commits, no co-author or session lines)

plan + gitignore → DESIGN.md → scaffold + config → storage models → ingestion → splitter →
grounding validator → offline generation → provider layer + mock → LLM generation → SM-2 →
queue → quiz → Anki export → stats → web: decks/import → web: generate report → web: review →
web: quiz → web: progress/privacy → sample notes + demo loader → CI → Dockerfile → README + screenshots.

## 14. Risks

| Risk | Handling |
|---|---|
| Offline cards are mechanical and sometimes awkward | Conservative patterns, cap per passage, easy edit/delete, stated in limitations |
| PDF text extraction varies by file (columns, headers, ligatures) | Clean-up pass, clear errors, stated in limitations |
| LLMs retype quotes slightly and get rejected | Intended; normalisation covers whitespace and typographic quotes only; rejections are reported |
| Free-tier rate limits and slow runs | One passage per call, concurrency 2, 20-passage cap, retry on 429 |
| No real LLM key in this environment | LLM path is proven with the mock and `MockTransport` only; README will say a live run was not done unless you provide a key |
| Docker cannot be built here | CI builds the image and checks `/health`; README says it was not built locally |
| Anki import cannot be confirmed here | Format follows Anki's text-import rules and is unit-tested; README says the import itself is untested until you try it |
| Playwright version may not match the cached browser | Fall back to headless Edge/Chrome screenshots |

## 15. Decisions I need from you

1. **Progress screenshot.** A fresh install has one day of history, so the chart is nearly
   empty. Recommended: `scripts/seed_demo.py` replays a fixed-seed rating pattern through the
   real scheduler over 14 past days, and the README caption says the history is simulated.
   Alternative: screenshot only what I really click through today.
2. **Again = quality 2** (ease −0.32), or the harsher quality 1 (ease −0.54)? Recommended: 2.
3. **Quiz does not change the schedule.** Recommended as planned; say so if you want quiz
   answers to count as reviews.
4. **Case-sensitive quote matching.** Recommended: strict. Looser matching accepts more LLM
   cards but weakens the claim.
5. **SQLAlchemy 2.0** over plain `sqlite3`. Recommended: SQLAlchemy.
6. **Repo name for the CI badge**: `Omkar210404/study-buddy`?
