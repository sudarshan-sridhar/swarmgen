# Design System: SwarmGen

## 1. Visual Theme & Atmosphere

A clinical, instrument-panel interface for a distributed inference research demo.
Density `4` (Daily App Balanced) tipping toward `7` in the workers panel where
data is dense and structural. Variance `5` (Offset Asymmetric) — the controls
sit narrower on the left, the generated image gets the wider canvas on the
right. Motion `3` (Static Restrained) — this is a research tool, not a
landing page, so motion is reserved for status changes (pulse on alive
indicators, fade on stage results) and tactile press feedback. The atmosphere
is **measured engineering**: thin lines, neutral surfaces, monospace numerics,
and a single confident accent for the success state.

The UI must feel like reading a flight recorder, not a marketing page.

## 2. Color Palette & Roles

- **Canvas Surface** `#FAFAFA` — Page background (zinc-50)
- **Card Surface** `#FFFFFF` — Container fill, generated-image frame
- **Charcoal Ink** `#18181B` — Primary text, headings, primary button fill (zinc-950)
- **Muted Steel** `#52525B` — Secondary copy, helper text, eyebrow labels (zinc-600)
- **Whisper Steel** `#71717A` — Tertiary metadata, table column headers (zinc-500)
- **Hairline Border** `#E4E4E7` — 1px borders, table dividers (zinc-200)
- **Live Emerald** `#10B981` — Single accent: alive worker, success states, focus ring
- **Failure Crimson** `#B91C1C` — Reserved exclusively for the kill button + DEAD status
- **Soft Crimson** `#FEE2E2` — Hover background for the kill button only
- **Code Wash** `#F4F4F5` — Inline code/metric chip background (zinc-100)

Maximum 1 accent (Emerald). Crimson is *not* a second accent — it appears only in two places (kill button, DEAD status) and is functionally a warning, not decoration. No purple, no neon, no gradients.

## 3. Typography Rules

- **Display** Geist (Google Font), weight 600, `tracking: -0.02em`, leading-none.
  Page title 28px. No oversize H1s.
- **Body** Geist, weight 400, line-height 1.55, max 65ch.
- **Eyebrow labels** Geist, weight 500, 11px, uppercase, `letter-spacing: 0.12em`,
  Whisper Steel color. Sits above each section in lieu of a bold heading.
- **Mono** Geist Mono — for: ms timings, byte counts, host:port, RSS values,
  status pills. Always with `font-variant-numeric: tabular-nums` so digits
  don't jiggle.
- **Banned** `Inter`, all generic serifs, system-default sans for premium
  contexts. No serif fonts anywhere in this dashboard.

Hierarchy is built with **weight + color**, not size. The page title and the
eyebrow labels live two type-weights apart but only ~17px apart in size.

## 4. Component Stylings

### Hero (page header)
- Left-aligned, no centered marketing block.
- Title `SwarmGen` (28px, weight 600).
- Two-line description in Muted Steel, 14px, max 65ch. **No tagline filler**
  ("Elevate", "Unleash", "Seamless" all banned).

### Eyebrow section labels
- Replace generic component labels (`gr.Textbox(label="prompt")`).
- Used above prompt, output, per-stage timing, and workers table.

### Buttons
- **Primary (`generate`)** — Charcoal Ink fill, white text, weight 600,
  no shadow, 14px radius. On `:active` translate-y(1px) — physical push.
- **Secondary (`kill Pi VAE worker`)** — White fill, Failure Crimson text,
  Soft Crimson border. Hover fills Soft Crimson at 100%. **Never ghost-glow.**
- No third button style. No icon buttons.

### Inputs
- Textarea: 3 lines, no internal label, eyebrow label sits above.
- Sliders: thin track, no pill-shaped values, `:focus` ring in Live Emerald.

### Tables (workers + per-stage)
- 1px Hairline Border between rows. **No card boxing per row.**
- Column headers in Whisper Steel, 10.5px uppercase, `letter-spacing: 0.05em`.
- All numeric columns right-aligned, monospace, tabular numerics.
- ALIVE pill: Live Emerald text, weight 600. DEAD pill: Failure Crimson, weight 600.
- Workers table replaces card-per-worker stack. Density wins here.

### Image frame (output)
- Pure white surface, 12px radius, 1px Hairline Border.
- No drop shadow. No "powered by" footer.

### Per-stage timing card
- Three rows (CLIP / UNET / VAE), monospace, right-aligned ms and bytes,
  the resolving worker host:port in muted color on the right.

## 5. Layout Principles

- Container: `max-width: 1280px`, centered, 24px horizontal padding.
- Two-column upper split: controls `2fr` left, output `3fr` right (the image is
  the big reward — it earns the bigger half).
- Workers table spans full width below the split — it's the "ECG strip" of the
  whole system.
- Vertical rhythm: 24px between sections, 18px between an eyebrow label and
  its block.
- No 3-column equal-card grid. The split is asymmetric on purpose.

## 6. Motion & Interaction

- Hard rule: motion only confirms or signals state, it doesn't decorate.
- `:active` on every button: `transform: translateY(1px)` for tactile push.
- `:focus` on inputs: 2px Live Emerald ring, no glow.
- Workers table refreshes every 2 seconds via `gr.Timer`. The diff is
  silent — no animation, the values just update. (A pulsing dot on ALIVE
  workers is permitted but not required; if added, use CSS keyframes only,
  not JS.)
- Per-stage timing populates in one paint after generation completes. No
  staggered entrance — this is a flight recorder, not a product tour.
- **Banned**: framer-motion, GSAP, scroll-jacking, parallax, hover lift,
  card tilt, gradient sheen.

## 7. Anti-Patterns (Banned)

- Emojis anywhere in the UI text or copy.
- `Inter` font.
- Pure `#000000`. Use Charcoal Ink (`#18181B`).
- Neon/outer-glow `box-shadow`.
- Oversaturated accents. Live Emerald and Failure Crimson are the only colors
  with chroma above 30; everything else is desaturated zinc.
- Gradient-text headlines.
- Custom mouse cursors.
- Overlapping/floating elements stacked over the image.
- 3-column equal feature card row.
- Generic names: "John Doe", "Acme", "Nexus".
- Fake round numbers in placeholders. `42` for seed is fine (canonical).
- Filler UI text: "Scroll to explore", "Swipe down", chevrons.
- "Powered by Gradio" footer (we hide it).
- Marketing copy: "Elevate", "Seamless", "Unleash", "Next-Gen".

## 8. Gradio reality check (constraints we accept)

This UI ships in Gradio because Python-side integration with the coordinator
matters more than pixel control. The following design intents from above are
**not fully achievable** in Gradio without rewriting the frontend in a real
framework:

- True spring physics on buttons (Gradio uses CSS transitions only).
- Skeletal loaders matching exact layout — Gradio has its own loading state.
- Inline image typography in the hero — markdown can't host inline rounded photos.
- Custom focus ring without `!important` overrides on every input class.

Gradio's component HTML changes between versions, so any deeply nested
selector (`.svelte-xxxx > div > input`) is fragile. We deliberately style
through `elem_id` / `elem_classes` and a small set of stable global selectors
(`button`, `table`, `.gradio-container`).

If a future version of this project drops Gradio for a custom HTML/JS
frontend, this DESIGN.md is the spec to lift wholesale.
