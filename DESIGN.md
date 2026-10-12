# DESIGN — study-buddy

The app should feel like a tidy desk with one index card on it, not like a control panel.

## Principles

1. **One thing at a time.** Each screen has one main job and one primary button.
2. **The card is the hero.** Card text is the largest thing on any screen that shows a card.
3. **Paper, not chrome.** Warm off-white background, thin rules, no boxes inside boxes, no shadows
   heavier than a sheet of paper lying on a desk.
4. **Show the source.** Wherever an answer is shown, its supporting quote is shown with it.
5. **Quiet numbers.** Counts are written into sentences ("12 cards due today"). No grid of stat tiles.

## What it must not be

No sidebar, no dark admin dashboard, no KPI tile grid, no dense data tables with zebra stripes,
no gradient buttons, no icon-only navigation, no charts library.

## Colour tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#f6f1e7` | `#1f1c18` | page background |
| `--card` | `#fffdf8` | `#2a2621` | cards, forms |
| `--ink` | `#2b2620` | `#ece4d6` | text |
| `--ink-soft` | `#6b6256` | `#a99e8c` | secondary text |
| `--rule` | `#e0d6c3` | `#3d362d` | borders, dividers |
| `--accent` | `#2e6a5e` | `#7fbfae` | links, primary button, focus ring |
| `--accent-ink` | `#ffffff` | `#17201d` | text on accent |
| `--mark` | `#fbe9a8` | `#5a4b17` | highlighted supporting quote |
| `--again` | `#b0503a` | `#e08a73` | Again, errors, rejected |
| `--hard` | `#a8762a` | `#d9ab5f` | Hard, warnings |
| `--good` | `#2e6a5e` | `#7fbfae` | Good, accepted |
| `--easy` | `#3a6a9e` | `#8bb4e0` | Easy |

Dark mode is a dim, warm version of the same desk. It follows `prefers-color-scheme` and can be
forced with the toggle in the header (stored in `localStorage`, applied as `data-theme` on `<html>`).

## Type

- Card and reading text: `"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif`.
- Controls, labels, navigation: `system-ui, "Segoe UI", Roboto, sans-serif`.
- System fonts only. The page makes no request to any other host.
- Card front: `clamp(1.35rem, 1rem + 2vw, 2rem)`, line-height 1.4. Body 1.0625rem, line-height 1.6.
- Small caps style labels (0.75rem, letter-spaced, `--ink-soft`) name the parts of a card:
  QUESTION, ANSWER, FROM YOUR NOTES.

## Layout

- One centred column, max 44rem, 1rem side padding on phones.
- Header: wordmark on the left, four text links (Today, Decks, Progress, Privacy), theme toggle.
  On narrow screens the links wrap under the wordmark; nothing is hidden behind a menu.
- Spacing scale: 0.25, 0.5, 0.75, 1, 1.5, 2, 3 rem.
- Radius 10px on cards, 8px on buttons. One soft shadow, cards only.
- Tap targets at least 44px high.

## Screens

- **Today** — a sentence with the due count, one "Start review" button, then the decks as a plain list.
- **Deck (study view)** — deck title, three actions (Review, Quiz, Add notes), search box, tag
  chips, then cards as a list: front, answer, and the quote in a highlighted line.
- **Review** — the header collapses to "Leave" and a thin progress line. One card, centred.
  Front first; Space (or tap) flips it. The back shows the answer, the supporting quote marked
  inside its passage, and the section it came from. Four rating buttons in a row (2 × 2 on
  phones), each with its key number and the next interval ("Good · 6 days").
- **Quiz** — same card frame; options are full-width buttons, or one text field for typed answers.
  Feedback states the similarity score in plain words.
- **Generation report** — "18 cards added, 3 rejected", then the rejected cards with the reason
  and the quote that could not be found.
- **Progress** — due today, a 30-day strip of thin bars (server-rendered, labelled with counts),
  retention by deck written as "31 of 36 remembered (86%)".
- **Privacy** — plain text: what is stored, what leaves the machine in each mode, current mode.

## Interaction

- Keyboard: Space flips, 1–4 rate, in quiz 1–4 pick an option, Enter submits. Shortcuts are
  printed under the card and are off while a text field has focus.
- HTMX swaps only the card area; the page does not reload between cards.
- Visible focus ring (2px `--accent`, 2px offset) on everything focusable.
- `prefers-reduced-motion`: the flip becomes an instant swap.
- Colour is never the only signal: rating buttons and report rows carry words too.

## Mode honesty

A small line under the header of every generation screen states the active mode:
"Offline mode — nothing leaves this computer" or "LLM mode — passages you generate from are sent
to *host*". Cards made by the mock provider are tagged "mock".
