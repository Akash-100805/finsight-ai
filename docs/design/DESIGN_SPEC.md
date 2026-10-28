# FinSight AI web app: design spec

This is the visual source of truth for `services/web`. Two kinds of reference sit alongside it:

- **`screens/*.png`** show what each screen looks like (rendered at 1440 px wide). Match these.
- **`source/*.dc.html`** are the design's source files. Each one is HTML markup plus a small class that supplies the sample data.
  - Read them for structure, copy, spacing and inline styles.
  - They are **not** runnable as-is. `{{…}}`, `<sc-for>` and `<sc-if>` are template syntax: `sc-for` repeats its children and `sc-if` shows them conditionally.
  - Rebuild each screen as React components; don't embed these files.

The sample data in the designs (holdings, prices, the "[Headline from the news feed]" placeholders) is illustrative only. The app shows real data from the API.

## Tokens

### Colours

| Token | Hex | Use |
|---|---|---|
| `bg` | `#0A0E0D` | Page background |
| `surface` | `#0F1513` | Cards, panels, table bodies |
| `surface-2` | `#0D1211` | Alternate band (landing sections, evidence panel) |
| `surface-3` | `#16201D` | Row dividers, selected row, skeleton blocks |
| `border` | `#1C2724` | 1 px card and section borders, hairline grids |
| `border-strong` | `#2A3834` | Inputs, secondary buttons, chips |
| `text` | `#E6EDEA` | Primary text |
| `text-2` | `#C3D0CB` | Body copy inside cards |
| `muted` | `#A9BAB4` | Secondary copy |
| `subtle` | `#8A9C96` | Labels, meta. **Minimum for text on `bg`** |
| `faint` | `#6F817B` | Placeholders, disabled only (not body text) |
| `accent` | `#2DD4A7` | Primary actions, positive signals, "worth a closer look" |
| `accent-hover` | `#6EE7C5` | Link hover |
| `accent-ink` | `#06110E` | Text on accent buttons |
| `warn` | `#F0A35E` | Negative signals, "watch". This is orange, not red (colour-blind safe against teal) |
| `neutral-bar` | `#3A4A45` | Neutral signal bars, "not flagged" outline |

### Type

All three fonts are on Google Fonts; self-host them with `@fontsource`.

- **Chakra Petch** (500/600/700): headings, logo wordmark, card titles. Letter-spacing −0.01em on large headings.
- **DM Sans** (400/500/600): body, buttons, form labels.
- **JetBrains Mono** (400/500): every number (₹ amounts, percentages, scores, quantities, timers), tickers, and eyebrow labels.
  - Eyebrow labels are 12–13 px uppercase with letter-spacing 0.08–0.12em, e.g. `STEP 1 OF 2 · BUILD`.

Scale:

| Element | Size |
|---|---|
| Hero | `clamp(40px, 5.4vw, 68px)` |
| Page title | 34–36 px |
| Section title | 40 px (landing) / 18 px (app panels) |
| Card title | 26 px |
| Body | 15–16 px |
| Labels | 12–13 px |

### Shape and depth

- Corner radius is **2 px** everywhere. The look is rectilinear.
- **No drop shadows.** Separate things with 1 px borders and the surface steps.
- Hairline grids: a container with `background: border` and `gap: 1px`, with children on `surface`. Used for the stat strips and "How it works".
- The focus ring is a 2 px `accent` outline with −1 px offset.
- Touch targets are at least 44 px.

### Components

- **Primary button:** `accent` background, `accent-ink` text, 600 weight, 48–52 px tall.
- **Secondary button:** transparent, 1 px `border-strong`.
- **Pill or label:** mono 12 px uppercase, 1 px border plus text in the same colour (`accent` or `warn`), 4×8 px padding.
- **Signal bar:** a 5–6 px track in `border`, filled with `accent` (positive), `warn` (negative) or `neutral-bar`. The text label sits above it (e.g. "Leaning negative") in the matching colour. Never show raw per-article sentiment numbers.
- **Stat tile:** label 12 px `subtle` uppercase, value 20–30 px mono.

## Motion

Honour `prefers-reduced-motion`; under it, show the end state immediately.

- `rise`: opacity 0→1 and translateY 18 px→0, 600 ms, `cubic-bezier(.2,.7,.2,1)`.
- `fade`: opacity 0→1, 600 ms ease-out.
- `bar`: scaleX 0→1 from the left, 700 ms ease-out.
- `slide`: opacity 0→1 and translateX 24 px→0, 600 ms ease-out.

**Results reveal choreography** (Results screen, on first load of a finished run). *n* is the number of cards and *s* the stagger, 180 ms by default:

| Time | What appears |
|---|---|
| t = 0 | Headline `fade` |
| +350 ms | Run-facts strip `fade` |
| +700 ms | Action cards `rise`, staggered by *s*. Each card's signal bars `bar` 300 ms after the card, 90 ms apart |
| +700 ms + *n*·*s* + 200 ms | Evidence panel `slide` and "not shortlisted" `fade` |
| 300 ms after that | Disclaimer and next-step bar `fade` |

**Running screen:** the stage list advances from real backend progress, not a timer. The active stage's dot pulses (opacity 1↔0.35, 1.2 s), done stages fill `accent`, and the result placeholders shimmer.

## Copy rules (non-negotiable)

- Insights, not advice. Never use "buy", "sell", "hold", "trim", "hedge", "target price" or "stop loss" in UI copy.
- The disclaimer is visible on every app screen and in the landing footer: *"Insights, not investment advice. FinSight AI is not a SEBI-registered investment adviser."*
- Evidence items are labelled **SOURCE HEADLINE**, with publisher and age.
- The sector-view chip shows the provider the run actually used: "Sector view: TKG (provisional)" or "Sector view: TKG-lite".
- Format ₹ amounts in Indian grouping (`₹1,39,750`). Show $ for US holdings.
