// SwarmGen presentation deck. Dark theme, matches the UI.
// Run:  node build_deck.js
// Outputs: SwarmGen_Deck.pptx
//
// 12 slides, ~7 minute talk pace.

const pptxgen = require("pptxgenjs");
const path = require("path");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";       // 13.333" x 7.5"
pres.author = "Sudarshan Sridhar";
pres.title = "SwarmGen";

// ---------- design tokens (match the dark UI) ------------------------------
const C = {
  canvas:  "0A0A0C",
  surface: "18181B",
  surface2:"22222A",
  ink:     "FAFAFA",
  steel:   "A1A1AA",
  whisper: "71717A",
  quiet:   "52525B",
  hairline:"2A2A30",
  accent:  "10B981",
  accent_d:"047857",
  danger:  "EF4444",
};

const F = {
  display: "Aptos Display",
  body:    "Aptos",
  mono:    "Consolas",
};

const SLIDE_W = 13.333;
const SLIDE_H = 7.5;
const TOTAL = 12;

let slideIdx = 0;

// ---------- helpers ---------------------------------------------------------
function makeSlide() {
  slideIdx++;
  const slide = pres.addSlide();
  slide.background = { color: C.canvas };
  // Top eyebrow strip
  slide.addText("SWARMGEN", {
    x: 0.5, y: 0.32, w: 4, h: 0.3,
    fontFace: F.mono, fontSize: 9, charSpacing: 4,
    color: C.whisper, bold: true,
    margin: 0,
  });
  // Slide number bottom-right
  slide.addText(String(slideIdx).padStart(2, "0") + " / " + String(TOTAL).padStart(2, "0"), {
    x: SLIDE_W - 1.6, y: SLIDE_H - 0.5, w: 1.2, h: 0.3,
    fontFace: F.mono, fontSize: 9, charSpacing: 3,
    color: C.whisper, align: "right",
    margin: 0,
  });
  // top hairline
  slide.addShape(pres.ShapeType.line, {
    x: 0.5, y: 0.7, w: SLIDE_W - 1, h: 0,
    line: { color: C.hairline, width: 0.5 },
  });
  return slide;
}

function sectionLabel(slide, text) {
  // small "0X / name" on the left, JetBrains Mono / Consolas
  slide.addText(text, {
    x: 0.5, y: 0.95, w: 6, h: 0.3,
    fontFace: F.mono, fontSize: 11, charSpacing: 5,
    color: C.steel, bold: false,
    margin: 0,
  });
}

function title(slide, text, opts = {}) {
  slide.addText(text, {
    x: 0.5, y: 1.4, w: SLIDE_W - 1, h: 1.5,
    fontFace: F.display, fontSize: opts.size || 44,
    color: C.ink, bold: true,
    valign: "top",
    margin: 0,
    paraSpaceAfter: 6,
    ...opts,
  });
}

function paragraph(slide, text, opts = {}) {
  slide.addText(text, {
    fontFace: F.body, fontSize: 16,
    color: C.steel,
    valign: "top",
    margin: 0,
    paraSpaceAfter: 8,
    ...opts,
  });
}

function statBox(slide, x, y, w, h, value, label, sub, accent = false) {
  // surface background
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h,
    fill: { color: C.surface },
    line: { color: C.hairline, width: 0.5 },
    rectRadius: 0.08,
  });
  slide.addText(value, {
    x: x + 0.25, y: y + 0.22, w: w - 0.5, h: h * 0.55,
    fontFace: F.mono, fontSize: 40,
    color: accent ? C.accent : C.ink,
    bold: false, charSpacing: -2,
    valign: "top", margin: 0,
  });
  slide.addText(label, {
    x: x + 0.25, y: y + h * 0.55 + 0.05, w: w - 0.5, h: 0.3,
    fontFace: F.mono, fontSize: 10, charSpacing: 4,
    color: C.steel, bold: false, margin: 0,
  });
  if (sub) {
    slide.addText(sub, {
      x: x + 0.25, y: y + h * 0.55 + 0.4, w: w - 0.5, h: 0.4,
      fontFace: F.body, fontSize: 11,
      color: C.whisper, margin: 0,
    });
  }
}

function chartBackground(slide, x, y, w, h) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h,
    fill: { color: C.surface }, line: { color: C.hairline, width: 0.5 },
    rectRadius: 0.08,
  });
}

// ============================================================================
// SLIDE 1 — TITLE
// ============================================================================
{
  const s = pres.addSlide();
  slideIdx = 1;
  s.background = { color: C.canvas };

  // big eyebrow
  s.addText("CIS 589  ·  EDGE COMPUTING  ·  SPRING 2026", {
    x: 0.7, y: 0.7, w: 12, h: 0.4,
    fontFace: F.mono, fontSize: 11, charSpacing: 6,
    color: C.whisper, bold: false, margin: 0,
  });

  // huge title
  s.addText([
    { text: "Stable Diffusion,\n", options: { color: C.ink } },
    { text: "across ", options: { color: C.ink } },
    { text: "edges.", options: { color: C.accent, italic: true } },
  ], {
    x: 0.7, y: 1.3, w: 12, h: 3.5,
    fontFace: F.display, fontSize: 86, bold: true,
    charSpacing: -2, valign: "top",
    margin: 0,
  });

  // sub
  s.addText(
    "SD-Turbo, partitioned across three heterogeneous edge devices. " +
    "The Pi cannot fit the full pipeline alone. The swarm makes it a participant.",
    {
      x: 0.7, y: 5.0, w: 11.5, h: 1.0,
      fontFace: F.body, fontSize: 18,
      color: C.steel, margin: 0,
      paraSpaceAfter: 4,
    }
  );

  // attribution
  s.addText("Sudarshan Sridhar  ·  Varun Patel", {
    x: 0.7, y: 6.5, w: 12, h: 0.35,
    fontFace: F.mono, fontSize: 11, charSpacing: 3,
    color: C.steel, margin: 0,
  });
  s.addText("github.com/sudarshan-sridhar/swarmgen", {
    x: 0.7, y: 6.85, w: 12, h: 0.35,
    fontFace: F.mono, fontSize: 11, charSpacing: 1,
    color: C.whisper, margin: 0,
  });

  // accent dot
  s.addShape(pres.ShapeType.ellipse, {
    x: SLIDE_W - 1.0, y: 0.7, w: 0.18, h: 0.18,
    fill: { color: C.accent }, line: { color: C.accent },
  });
  slideIdx = 1;
}

// ============================================================================
// SLIDE 2 — PROBLEM (hero stat)
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "01 / problem");
  title(s, "A Pi can't run SD-Turbo.\nThe full pipeline doesn't fit.");

  // Hero comparison: 2358 MB peak vs 1845 MB physical
  statBox(s, 0.7,  4.0, 4.0, 2.2, "2358", "PIPELINE PEAK · MB", "what SD-Turbo needs end-to-end", false);
  statBox(s, 4.85, 4.0, 4.0, 2.2, "1845", "PI PHYSICAL · MB",  "Raspberry Pi 4B total RAM",        false);
  statBox(s, 9.0,  4.0, 3.6, 2.2, "−513", "SHORTFALL · MB",     "the Pi never gets there alone",   true);

  // explainer
  s.addText(
    "Diffusion models hover just outside the envelope of small edge devices. " +
    "You can't swap your way out. It's a hard ceiling.",
    {
      x: 0.7, y: 3.1, w: 12, h: 0.8,
      fontFace: F.body, fontSize: 16, color: C.steel,
      margin: 0, paraSpaceAfter: 6,
    }
  );
}

// ============================================================================
// SLIDE 3 — SOLUTION (the split)
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "02 / solution");
  title(s, "Split it across three devices.\nEach one holds only what it can run.");

  // Three role boxes
  const roleY = 4.0, roleH = 2.6, roleW = 3.8, gap = 0.35;
  const boxes = [
    { x: 0.7,                   role: "CLIP",  dev: "pc · CPU laptop",     stat: "120M params" , color: C.steel },
    { x: 0.7 + roleW + gap,     role: "UNet",  dev: "loq · RTX 5060",       stat: "865M params · 4 steps" , color: C.accent },
    { x: 0.7 + 2*(roleW + gap), role: "VAE",   dev: "pi · Pi 4B (1.8 GB)", stat: "80M params" , color: C.steel },
  ];
  for (const b of boxes) {
    s.addShape(pres.ShapeType.roundRect, {
      x: b.x, y: roleY, w: roleW, h: roleH,
      fill: { color: C.surface }, line: { color: C.hairline, width: 0.5 },
      rectRadius: 0.1,
    });
    // small dot
    s.addShape(pres.ShapeType.ellipse, {
      x: b.x + 0.3, y: roleY + 0.35, w: 0.16, h: 0.16,
      fill: { color: b.color }, line: { color: b.color },
    });
    s.addText(b.role.toUpperCase(), {
      x: b.x + 0.6, y: roleY + 0.25, w: roleW - 1, h: 0.4,
      fontFace: F.display, fontSize: 26, color: C.ink, bold: true,
      charSpacing: -1, margin: 0,
    });
    s.addText(b.dev, {
      x: b.x + 0.3, y: roleY + 1.1, w: roleW - 0.6, h: 0.4,
      fontFace: F.mono, fontSize: 13, color: C.steel,
      charSpacing: 1, margin: 0,
    });
    s.addText(b.stat, {
      x: b.x + 0.3, y: roleY + 1.55, w: roleW - 0.6, h: 0.4,
      fontFace: F.mono, fontSize: 12, color: C.whisper,
      charSpacing: 1, margin: 0,
    });
  }

  // arrows between role cards
  for (let i = 0; i < 2; i++) {
    const ax = 0.7 + roleW + i * (roleW + gap) - 0.06;
    s.addShape(pres.ShapeType.rightArrow, {
      x: ax, y: roleY + roleH/2 - 0.12, w: 0.34, h: 0.24,
      fill: { color: C.accent }, line: { color: C.accent },
    });
  }

  // bottom note
  s.addText(
    "Putting UNet on the GPU isn't a cheat. The claim is per-device memory reduction, not GPU offload.",
    {
      x: 0.7, y: 6.85, w: 12, h: 0.4,
      fontFace: F.body, fontSize: 13, color: C.whisper,
      italic: true, margin: 0,
    }
  );
}

// ============================================================================
// SLIDE 4 — ARCHITECTURE
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "03 / architecture");
  title(s, "Coordinator on loq, async HTTP, mDNS discovery.");

  // Coordinator box top
  const cx = 5.5, cy = 3.4, cw = 3.0, ch = 0.95;
  s.addShape(pres.ShapeType.roundRect, {
    x: cx, y: cy, w: cw, h: ch,
    fill: { color: C.accent }, line: { color: C.accent },
    rectRadius: 0.1,
  });
  s.addText("COORDINATOR", {
    x: cx, y: cy + 0.1, w: cw, h: 0.4,
    fontFace: F.display, fontSize: 16, color: C.canvas, bold: true,
    align: "center", charSpacing: 2, margin: 0,
  });
  s.addText("loq · async + httpx + zeroconf", {
    x: cx, y: cy + 0.5, w: cw, h: 0.35,
    fontFace: F.mono, fontSize: 11, color: C.canvas,
    align: "center", margin: 0,
  });

  // Three workers below
  const wY = 5.4, wH = 1.4, wW = 3.6;
  const workers = [
    { x: 0.7,       label: "WORKER · CLIP",  detail: "pc · 192.168.1.39:8001" },
    { x: 0.7 + 4.0, label: "WORKER · UNET",  detail: "loq · 192.168.1.16:8002" },
    { x: 0.7 + 8.0, label: "WORKER · VAE",   detail: "pi · 192.168.1.185:8003" },
  ];
  for (const w of workers) {
    s.addShape(pres.ShapeType.roundRect, {
      x: w.x, y: wY, w: wW, h: wH,
      fill: { color: C.surface }, line: { color: C.hairline, width: 0.75 },
      rectRadius: 0.1,
    });
    s.addText(w.label, {
      x: w.x + 0.25, y: wY + 0.2, w: wW - 0.5, h: 0.4,
      fontFace: F.display, fontSize: 14, color: C.ink, bold: true,
      charSpacing: 2, margin: 0,
    });
    s.addText(w.detail, {
      x: w.x + 0.25, y: wY + 0.7, w: wW - 0.5, h: 0.35,
      fontFace: F.mono, fontSize: 11, color: C.steel,
      charSpacing: 1, margin: 0,
    });
    // pulse dot
    s.addShape(pres.ShapeType.ellipse, {
      x: w.x + wW - 0.45, y: wY + 0.32, w: 0.13, h: 0.13,
      fill: { color: C.accent }, line: { color: C.accent },
    });
  }

  // arrows from coordinator to each worker
  for (const w of workers) {
    s.addShape(pres.ShapeType.line, {
      x: cx + cw / 2, y: cy + ch,
      w: (w.x + wW / 2) - (cx + cw / 2), h: wY - (cy + ch),
      line: { color: C.hairline, width: 1.0 },
    });
  }

  // Sidecar: fallback note
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.7, y: 7.0, w: 12, h: 0.42,
    fill: { color: C.surface }, line: { color: C.hairline, width: 0.5 },
    rectRadius: 0.06,
  });
  s.addText([
    { text: "FALLBACK   ", options: { color: C.accent, fontFace: F.mono, fontSize: 10, charSpacing: 4, bold: true } },
    { text: "loq also loads VAE on the GPU (165 MB VRAM). When pi dies, retry routes here in ~250 ms.", options: { color: C.steel, fontFace: F.body, fontSize: 11 } },
  ], {
    x: 0.85, y: 7.04, w: 11.7, h: 0.4,
    margin: 0, valign: "middle",
  });
}

// ============================================================================
// SLIDE 5 — DEVICES
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "04 / devices");
  title(s, "Locked specs. No emulation, real hardware.");

  // Three columns, side by side
  const dev = [
    {
      name: "loq",
      role: "UNet (+VAE fb)",
      port: "8002",
      ip:   "192.168.1.16",
      cpu:  "20 logical cores",
      ram:  "32 GB",
      gpu:  "RTX 5060 · 8 GB VRAM",
      torch:"2.12.0+cu128",
      os:   "Windows 11",
      accent: true,
    },
    {
      name: "pc",
      role: "CLIP",
      port: "8001",
      ip:   "192.168.1.39",
      cpu:  "Intel i5-1035G1 · 4c/8t",
      ram:  "12 GB",
      gpu:  "Intel UHD (no CUDA)",
      torch:"2.4.1+cpu",
      os:   "Windows 11",
      accent: false,
    },
    {
      name: "pi",
      role: "VAE",
      port: "8003",
      ip:   "192.168.1.185",
      cpu:  "ARM Cortex-A72 · 4c",
      ram:  "1.8 GB",
      gpu:  "—",
      torch:"2.9.1+cpu",
      os:   "Debian 13 (trixie)",
      accent: false,
    },
  ];
  const cardY = 3.4, cardH = 3.6, cardW = 4.0, gap = 0.2;
  for (let i = 0; i < dev.length; i++) {
    const d = dev[i];
    const x = 0.7 + i * (cardW + gap);
    s.addShape(pres.ShapeType.roundRect, {
      x, y: cardY, w: cardW, h: cardH,
      fill: { color: C.surface }, line: { color: d.accent ? C.accent : C.hairline, width: d.accent ? 1.0 : 0.5 },
      rectRadius: 0.1,
    });
    // big name
    s.addText(d.name, {
      x: x + 0.3, y: cardY + 0.2, w: cardW - 0.6, h: 0.6,
      fontFace: F.display, fontSize: 36, color: C.ink, bold: true,
      charSpacing: -1, margin: 0,
    });
    s.addText(d.role + "  ·  port " + d.port, {
      x: x + 0.3, y: cardY + 0.85, w: cardW - 0.6, h: 0.35,
      fontFace: F.mono, fontSize: 11, color: d.accent ? C.accent : C.steel,
      charSpacing: 1, margin: 0,
    });
    // hairline divider
    s.addShape(pres.ShapeType.line, {
      x: x + 0.3, y: cardY + 1.3, w: cardW - 0.6, h: 0,
      line: { color: C.hairline, width: 0.5 },
    });
    // facts as 2-col grid
    const facts = [
      ["IP",    d.ip],
      ["CPU",   d.cpu],
      ["RAM",   d.ram],
      ["GPU",   d.gpu],
      ["TORCH", d.torch],
      ["OS",    d.os],
    ];
    for (let j = 0; j < facts.length; j++) {
      const [k, v] = facts[j];
      const fy = cardY + 1.5 + j * 0.32;
      s.addText(k, {
        x: x + 0.3, y: fy, w: 1.0, h: 0.32,
        fontFace: F.mono, fontSize: 9, color: C.whisper,
        charSpacing: 4, margin: 0,
      });
      s.addText(v, {
        x: x + 1.2, y: fy, w: cardW - 1.5, h: 0.32,
        fontFace: F.mono, fontSize: 11, color: C.ink,
        margin: 0,
      });
    }
  }
}

// ============================================================================
// SLIDE 6 — LATENCY COMPARISON (chart)
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "05 / latency");
  title(s, "We don't beat a single GPU. We said we wouldn't.");

  // Chart background card
  chartBackground(s, 0.7, 3.2, 8.0, 4.0);

  const chartData = [{
    name: "ms / image",
    labels: ["1-dev baseline", "3-dev (loq VAE fb)", "3-dev (Pi VAE)"],
    values: [380, 1097, 147615],
  }];
  s.addChart(pres.ChartType.bar, chartData, {
    x: 0.85, y: 3.35, w: 7.7, h: 3.7,
    barDir: "col",
    chartColors: [C.accent],
    plotArea: { fill: { color: C.surface } },
    chartArea: { fill: { color: C.surface } },
    catAxisLabelColor: C.steel,
    catAxisLabelFontSize: 11,
    catAxisLabelFontFace: F.body,
    valAxisLabelColor: C.steel,
    valAxisLabelFontSize: 10,
    valAxisLabelFontFace: F.mono,
    valAxisLogScaleBase: 10,
    valAxisLineColor: C.hairline,
    catAxisLineColor: C.hairline,
    valGridLine: { style: "solid", color: C.hairline, size: 0.25 },
    showLegend: false,
    showValue: true,
    dataLabelColor: C.ink,
    dataLabelFontFace: F.mono,
    dataLabelFontSize: 10,
    dataLabelPosition: "outEnd",
  });

  // Side stats
  const sx = 9.0;
  statBox(s, sx, 3.2,  3.6, 1.85, "380",     "MS · BASELINE",        "single-device on RTX 5060 fp16", false);
  statBox(s, sx, 5.25, 3.6, 1.85, "147 615", "MS · WITH PI",         "Pi VAE dominates the pipeline",  true);
}

// ============================================================================
// SLIDE 7 — MEMORY (the headline)
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "06 / memory · the headline");
  title(s, "Pi 1226 MB. Pipeline 2358 MB.\nThe swarm makes the impossible run.");

  chartBackground(s, 0.7, 3.0, 12, 3.7);
  const memData = [{
    name: "peak RSS · MB",
    labels: ["1-dev baseline\n(loq full pipeline)",
             "3-dev swarm\nloq UNet+VAE",
             "3-dev swarm\npc CLIP",
             "3-dev swarm\npi VAE"],
    values: [2358, 2080, 1398, 1226],
  }];
  s.addChart(pres.ChartType.bar, memData, {
    x: 0.85, y: 3.15, w: 11.7, h: 3.4,
    barDir: "col",
    chartColors: ["6B7280", "3B82F6", "A1A1AA", C.accent],
    plotArea: { fill: { color: C.surface } },
    chartArea: { fill: { color: C.surface } },
    catAxisLabelColor: C.steel,
    catAxisLabelFontSize: 10,
    catAxisLabelFontFace: F.body,
    valAxisLabelColor: C.steel,
    valAxisLabelFontSize: 10,
    valAxisLabelFontFace: F.mono,
    valAxisLineColor: C.hairline,
    catAxisLineColor: C.hairline,
    valGridLine: { style: "solid", color: C.hairline, size: 0.25 },
    showLegend: false,
    showValue: true,
    dataLabelColor: C.ink,
    dataLabelFontFace: F.mono,
    dataLabelFontSize: 11,
    dataLabelPosition: "outEnd",
    barGapWidthPct: 50,
  });

  // call-out: Pi physical RAM line + label
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.7, y: 6.85, w: 12, h: 0.5,
    fill: { color: "1A0F0F" },
    line: { color: C.danger, width: 0.5 },
    rectRadius: 0.06,
  });
  s.addText([
    { text: "PI CEILING   ", options: { color: C.danger, fontFace: F.mono, fontSize: 10, charSpacing: 4, bold: true } },
    { text: "1845 MB physical RAM. The 2358 MB pipeline does not fit. The 1226 MB VAE-only does.",
      options: { color: C.steel, fontFace: F.body, fontSize: 12 } },
  ], {
    x: 0.9, y: 6.9, w: 11.7, h: 0.42,
    margin: 0, valign: "middle",
  });
}

// ============================================================================
// SLIDE 8 — FAULT RECOVERY
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "07 / fault tolerance");
  title(s, "Kill the Pi mid-flight. Image still completes.");

  // Timeline
  chartBackground(s, 0.7, 3.4, 12, 1.6);
  // segments
  const totalMs = 5615;
  const segs = [
    { ms: 3563, label: "CLIP",  via: "pc",  color: C.steel },
    { ms: 1792, label: "UNET",  via: "loq", color: "3B82F6" },
    { ms: 250,  label: "VAE",   via: "loq (fallback)", color: C.accent },
  ];
  let curX = 0.85;
  const tlW = 11.7;
  for (const seg of segs) {
    const w = (seg.ms / totalMs) * tlW;
    s.addShape(pres.ShapeType.rect, {
      x: curX, y: 3.95, w, h: 0.5,
      fill: { color: seg.color }, line: { color: C.canvas, width: 0.5 },
    });
    if (w > 0.6) {
      s.addText(seg.label + "\n" + seg.ms + " ms · " + seg.via, {
        x: curX, y: 3.95, w, h: 0.5,
        fontFace: F.mono, fontSize: 9, color: C.canvas,
        align: "center", valign: "middle", bold: true, margin: 0,
      });
    }
    curX += w;
  }
  // kill marker at t=1000 ms
  const killX = 0.85 + (1000 / totalMs) * tlW;
  s.addShape(pres.ShapeType.line, {
    x: killX, y: 3.6, w: 0, h: 1.2,
    line: { color: C.danger, width: 1.5, dashType: "dash" },
  });
  s.addText("kill Pi at t = 1000 ms", {
    x: killX - 1.3, y: 3.45, w: 2.6, h: 0.3,
    fontFace: F.mono, fontSize: 10, color: C.danger,
    align: "center", margin: 0, charSpacing: 1, bold: true,
  });

  // Stat boxes
  statBox(s, 0.7,  5.4, 3.85, 1.7,  "5.6 s",  "TOTAL TIME",        "with fault recovery", true);
  statBox(s, 4.7,  5.4, 3.85, 1.7,  "250 ms", "VAE ON LOQ",        "fp16 GPU fallback",   false);
  statBox(s, 8.7,  5.4, 4.0,  1.7,  "vs 147 s","WITHOUT FALLBACK", "Pi VAE alone",         false);
}

// ============================================================================
// SLIDE 9 — BATCH THROUGHPUT
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "08 / batch · pipeline parallelism");
  title(s, "Pipeline parallelism only helps when stages are balanced.");

  chartBackground(s, 0.7, 3.0, 7.5, 4.0);
  const tput = [{
    name: "img / min",
    labels: ["3-dev (loq VAE)", "3-dev (Pi VAE)"],
    values: [87.6, 0.41],
  }];
  s.addChart(pres.ChartType.bar, tput, {
    x: 0.85, y: 3.15, w: 7.2, h: 3.7,
    barDir: "col",
    chartColors: [C.accent],
    plotArea: { fill: { color: C.surface } },
    chartArea: { fill: { color: C.surface } },
    catAxisLabelColor: C.steel,
    catAxisLabelFontSize: 11,
    catAxisLabelFontFace: F.body,
    valAxisLabelColor: C.steel,
    valAxisLabelFontSize: 10,
    valAxisLabelFontFace: F.mono,
    valAxisLineColor: C.hairline,
    catAxisLineColor: C.hairline,
    valAxisLogScaleBase: 10,
    valGridLine: { style: "solid", color: C.hairline, size: 0.25 },
    showLegend: false,
    showValue: true,
    dataLabelColor: C.ink,
    dataLabelFontFace: F.mono,
    dataLabelFontSize: 11,
    dataLabelPosition: "outEnd",
  });

  // Right column: explanation + ratio
  s.addText([
    { text: "Steady-state throughput is bounded by the slowest stage.\n", options: { color: C.steel, fontSize: 14, fontFace: F.body, breakLine: true } },
    { text: "\n", options: { breakLine: true } },
    { text: "Pi VAE: ", options: { color: C.whisper, fontSize: 12, fontFace: F.mono, charSpacing: 2 } },
    { text: "140 s\n", options: { color: C.danger, fontSize: 14, fontFace: F.mono, breakLine: true } },
    { text: "Loq VAE: ", options: { color: C.whisper, fontSize: 12, fontFace: F.mono, charSpacing: 2 } },
    { text: "0.16 s\n", options: { color: C.accent, fontSize: 14, fontFace: F.mono, breakLine: true } },
    { text: "\n", options: { breakLine: true } },
    { text: "Pipeline parallelism cannot save you when one stage is 850× slower.",
      options: { color: C.steel, fontSize: 13, fontFace: F.body, italic: true } },
  ], {
    x: 8.5, y: 3.4, w: 4.2, h: 4.0,
    margin: 0, valign: "top",
    paraSpaceAfter: 4,
  });
}

// ============================================================================
// SLIDE 10 — UI SCREENSHOT TIME (recreated mockup)
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "09 / ui");
  title(s, "Live demo. One HTML file, no build step.");

  // Mock browser frame
  const fx = 0.7, fy = 2.4, fw = 12, fh = 4.7;
  s.addShape(pres.ShapeType.roundRect, {
    x: fx, y: fy, w: fw, h: fh,
    fill: { color: C.canvas }, line: { color: C.hairline, width: 1 },
    rectRadius: 0.1,
  });
  // browser dots
  ["EF4444","F59E0B","10B981"].forEach((c, i) => {
    s.addShape(pres.ShapeType.ellipse, {
      x: fx + 0.2 + i * 0.22, y: fy + 0.2, w: 0.15, h: 0.15,
      fill: { color: c }, line: { color: c },
    });
  });
  s.addText("localhost:7860", {
    x: fx + 1.2, y: fy + 0.16, w: 6, h: 0.25,
    fontFace: F.mono, fontSize: 9, color: C.whisper, margin: 0,
  });

  // Hero
  s.addText("Stable diffusion, across edges.", {
    x: fx + 0.4, y: fy + 0.8, w: fw - 0.8, h: 0.7,
    fontFace: F.display, fontSize: 28, color: C.ink, bold: true,
    charSpacing: -1, margin: 0,
  });

  // Two-col content row
  const colY = fy + 1.7;
  // controls col
  s.addShape(pres.ShapeType.roundRect, {
    x: fx + 0.4, y: colY, w: 4.6, h: 2.6,
    fill: { color: C.surface }, line: { color: C.hairline, width: 0.5 },
    rectRadius: 0.08,
  });
  s.addText("01 / CONTROL", {
    x: fx + 0.55, y: colY + 0.15, w: 4.4, h: 0.3,
    fontFace: F.mono, fontSize: 9, color: C.whisper, charSpacing: 4, margin: 0,
  });
  s.addText("a watercolor painting of a lighthouse at dusk", {
    x: fx + 0.55, y: colY + 0.55, w: 4.4, h: 0.6,
    fontFace: F.body, fontSize: 11, color: C.ink, margin: 0,
  });
  // generate button mock
  s.addShape(pres.ShapeType.roundRect, {
    x: fx + 0.55, y: colY + 1.4, w: 1.7, h: 0.5,
    fill: { color: C.accent }, line: { color: C.accent }, rectRadius: 0.08,
  });
  s.addText("generate", {
    x: fx + 0.55, y: colY + 1.45, w: 1.7, h: 0.4,
    fontFace: F.body, fontSize: 12, color: C.canvas, bold: true,
    align: "center", valign: "middle", margin: 0,
  });
  s.addShape(pres.ShapeType.roundRect, {
    x: fx + 2.4, y: colY + 1.4, w: 2.4, h: 0.5,
    fill: { color: C.surface2 }, line: { color: C.danger, width: 0.5 }, rectRadius: 0.08,
  });
  s.addText("kill Pi VAE worker", {
    x: fx + 2.4, y: colY + 1.45, w: 2.4, h: 0.4,
    fontFace: F.body, fontSize: 11, color: C.danger,
    align: "center", valign: "middle", margin: 0,
  });

  // image col
  s.addShape(pres.ShapeType.roundRect, {
    x: fx + 5.2, y: colY, w: 6.4, h: 2.6,
    fill: { color: C.surface }, line: { color: C.hairline, width: 0.5 },
    rectRadius: 0.08,
  });
  s.addText("03 / OUTPUT", {
    x: fx + 5.35, y: colY + 0.15, w: 6.2, h: 0.3,
    fontFace: F.mono, fontSize: 9, color: C.whisper, charSpacing: 4, margin: 0,
  });
  s.addText("[ generated image ]", {
    x: fx + 5.2, y: colY + 0.5, w: 6.4, h: 2.0,
    fontFace: F.mono, fontSize: 11, color: C.quiet,
    align: "center", valign: "middle", margin: 0,
  });

  // Workers strip below
  const wrkY = fy + fh - 0.65;
  s.addText("ALIVE   alive   alive       ·       loq   pc   pi", {
    x: fx + 0.4, y: wrkY, w: fw - 0.8, h: 0.3,
    fontFace: F.mono, fontSize: 10, color: C.accent,
    charSpacing: 3, margin: 0,
  });

  // Caption
  s.addText("Bricolage Grotesque + JetBrains Mono. Tailwind from CDN. Vanilla JS. Polls /api/workers every 2 s.", {
    x: 0.7, y: 7.15, w: 12, h: 0.3,
    fontFace: F.body, fontSize: 12, color: C.whisper, italic: true, margin: 0,
  });
}

// ============================================================================
// SLIDE 11 — IMPLEMENTATION FACTS
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "10 / implementation");
  title(s, "About 1500 lines of Python + a single HTML file.");

  const facts = [
    { val: "5",     unit: "files", desc: "worker.py · coordinator.py · api.py · protocol.py · index.html" },
    { val: "1500",  unit: "lines", desc: "of Python · same code runs on Linux ARM, Windows CPU, Windows CUDA" },
    { val: "0",     unit: "containers", desc: "no Docker · no Ray · no Kubernetes · plain venvs" },
    { val: "3",     unit: "endpoints / worker", desc: "/health · /heartbeat · /run_stage · plus /admin/die for fault tests" },
  ];
  const fy = 3.4, fh = 0.8, gap = 0.15;
  for (let i = 0; i < facts.length; i++) {
    const f = facts[i];
    const y = fy + i * (fh + gap);
    s.addShape(pres.ShapeType.roundRect, {
      x: 0.7, y, w: 12, h: fh,
      fill: { color: C.surface }, line: { color: C.hairline, width: 0.5 },
      rectRadius: 0.08,
    });
    s.addText(f.val, {
      x: 0.95, y: y + 0.05, w: 1.6, h: fh - 0.1,
      fontFace: F.mono, fontSize: 32, color: C.accent, bold: false,
      align: "left", valign: "middle", margin: 0, charSpacing: -2,
    });
    s.addText(f.unit.toUpperCase(), {
      x: 2.6, y: y + 0.18, w: 2.5, h: 0.3,
      fontFace: F.mono, fontSize: 10, color: C.whisper,
      charSpacing: 4, margin: 0,
    });
    s.addText(f.desc, {
      x: 2.6, y: y + 0.45, w: 9.8, h: 0.32,
      fontFace: F.body, fontSize: 12, color: C.steel, margin: 0,
    });
  }

  s.addText(
    "Vanilla Python, FastAPI, asyncio, zeroconf, httpx. Threadpool inference so the event loop stays free.",
    {
      x: 0.7, y: 7.0, w: 12, h: 0.3,
      fontFace: F.body, fontSize: 12, color: C.whisper, italic: true, margin: 0,
    }
  );
}

// ============================================================================
// SLIDE 12 — CONCLUSION
// ============================================================================
{
  const s = makeSlide();
  sectionLabel(s, "11 / conclusion");
  title(s, "Heterogeneous swarms enable, they don't accelerate.");

  // Three key takeaways
  const ts = [
    {
      head: "Memory partitioning works",
      body: "Pi peaks at 1226 MB during VAE decode, comfortably under its 1.8 GB ceiling. Single-device peak is 2358 MB and would not fit.",
    },
    {
      head: "Fault recovery is fast",
      body: "Heartbeat + transport-level retry routes the failed stage to a fallback in about 250 ms. Image still completes.",
    },
    {
      head: "Throughput is gated by the slowest stage",
      body: "Pipeline parallelism doesn't deliver linear speedup when one stage is 850× slower than the others. Honest finding.",
    },
  ];
  for (let i = 0; i < ts.length; i++) {
    const t = ts[i];
    const y = 3.3 + i * 1.15;
    // accent dot
    s.addShape(pres.ShapeType.ellipse, {
      x: 0.7, y: y + 0.18, w: 0.16, h: 0.16,
      fill: { color: C.accent }, line: { color: C.accent },
    });
    s.addText(t.head, {
      x: 1.0, y, w: 11.5, h: 0.45,
      fontFace: F.display, fontSize: 22, color: C.ink, bold: true,
      charSpacing: -0.5, margin: 0,
    });
    s.addText(t.body, {
      x: 1.0, y: y + 0.5, w: 11.5, h: 0.55,
      fontFace: F.body, fontSize: 13, color: C.steel, margin: 0,
    });
  }

  // bottom: github link as CTA
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.7, y: 6.8, w: 12, h: 0.55,
    fill: { color: C.surface }, line: { color: C.accent, width: 0.75 },
    rectRadius: 0.08,
  });
  s.addText([
    { text: "CODE   ", options: { color: C.accent, fontFace: F.mono, fontSize: 11, charSpacing: 4, bold: true } },
    { text: "github.com/sudarshan-sridhar/swarmgen", options: { color: C.ink, fontFace: F.mono, fontSize: 14 } },
    { text: "       PAPER   ", options: { color: C.accent, fontFace: F.mono, fontSize: 11, charSpacing: 4, bold: true } },
    { text: "paper/paper.tex", options: { color: C.ink, fontFace: F.mono, fontSize: 14 } },
  ], {
    x: 0.95, y: 6.85, w: 11.7, h: 0.45,
    valign: "middle", margin: 0,
  });
}

// ============================================================================
// SAVE
// ============================================================================
const outPath = path.join(__dirname, "SwarmGen_Deck.pptx");
pres.writeFile({ fileName: outPath }).then(p => {
  console.log("wrote " + p);
}).catch(err => {
  console.error("error:", err);
  process.exit(1);
});
