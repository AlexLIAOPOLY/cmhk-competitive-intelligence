#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const SOURCE_URL = process.env.CMHK_INTELLIGENCE_SOURCE_URL || "http://127.0.0.1:8765/";
const OUTPUT_DIR = path.resolve(
  process.env.CMHK_INTELLIGENCE_SNAPSHOT_DIR
    || path.join(ROOT, "web", "static", "intelligence-public"),
);
const CHROME_PATH = process.env.CMHK_CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const TARGET_TABS = [
  ["local", "月费区间"],
  ["international", "投入强度"],
  ["cloud", "增长趋势"],
  ["macro", "流量需求"],
];

function cleanDirectory(directory) {
  fs.rmSync(directory, { recursive: true, force: true });
  fs.mkdirSync(path.join(directory, "assets"), { recursive: true });
  fs.mkdirSync(path.join(directory, "assets", "logo"), { recursive: true });
  fs.mkdirSync(path.join(directory, "assets", "executive-dashboard"), { recursive: true });
}

function staticOverrides() {
  return `
html, body { width: 100%; min-width: 0; min-height: 100%; margin: 0; background: #061724; }
body.dashboard-page { overflow-x: hidden; }
.app-shell { min-height: 100vh; }
.header-runtime-status, .strategy-ticker-header, .strategy-ticker-footer { display: none !important; }
.strategy-ticker { min-height: 104px; }
.strategy-ticker-list { min-height: 104px; }
.intelligence-command-board { min-height: calc(100vh - 154px); }
.static-snapshot .intelligence-scroll-label-track { animation-play-state: running !important; }
.static-snapshot .header-tools button { cursor: default; }
.static-snapshot .ai-insight-label { pointer-events: none; cursor: default; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
`;
}

async function fetchAsset(context, url, destination) {
  const response = await context.request.get(url);
  if (!response.ok()) {
    throw new Error(`Asset request failed (${response.status()}): ${url}`);
  }
  fs.writeFileSync(destination, await response.body());
}

async function main() {
  cleanDirectory(OUTPUT_DIR);
  const browser = await chromium.launch({
    headless: true,
    executablePath: CHROME_PATH,
  });
  try {
    const context = await browser.newContext({ viewport: { width: 2048, height: 1050 } });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(SOURCE_URL, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForSelector("#intelligenceDomainGrid .intelligence-domain", { timeout: 30_000 });
    await page.waitForFunction(
      () => document.querySelectorAll("#intelligenceDomainGrid .intelligence-domain").length === 4,
      null,
      { timeout: 30_000 },
    );

    for (const [domainId, label] of TARGET_TABS) {
      const button = page.locator(
        `[data-intelligence-domain-id="${domainId}"][data-intelligence-focus]`,
        { hasText: label },
      ).first();
      if (await button.count()) {
        await button.click();
      }
    }
    await page.waitForTimeout(250);

    const intelligenceResponse = await context.request.get(
      new URL("/api/executive-intelligence", SOURCE_URL).toString(),
    );
    if (!intelligenceResponse.ok()) {
      throw new Error(`Intelligence payload request failed: ${intelligenceResponse.status()}`);
    }
    const intelligencePayload = await intelligenceResponse.json();
    const scrubRuntimeAddresses = (value) => {
      if (Array.isArray(value)) {
        value.forEach(scrubRuntimeAddresses);
        return;
      }
      if (!value || typeof value !== "object") return;
      delete value.intelligence_source_url;
      Object.values(value).forEach(scrubRuntimeAddresses);
    };
    scrubRuntimeAddresses(intelligencePayload);
    const payloadText = JSON.stringify(intelligencePayload);
    if (/127\.0\.0\.1|localhost|10\.0\.|192\.168\.|file:\/\//i.test(payloadText)) {
      throw new Error("Refusing to publish an intelligence payload with internal addresses");
    }

    const fragments = await page.evaluate(() => {
      const clone = (selector) => {
        const node = document.querySelector(selector);
        if (!node) throw new Error(`Missing snapshot element: ${selector}`);
        const copy = node.cloneNode(true);
        copy.querySelectorAll("script").forEach((item) => item.remove());
        copy.querySelectorAll("a").forEach((item) => {
          const href = item.getAttribute("href") || "";
          if (!/^https?:\/\//i.test(href)) item.removeAttribute("href");
        });
        copy.querySelectorAll("[tabindex]").forEach((item) => item.removeAttribute("tabindex"));
        copy.querySelectorAll("[data-intelligence-insight-refresh]").forEach((item) => {
          item.removeAttribute("data-intelligence-insight-refresh");
          item.setAttribute("disabled", "");
          item.setAttribute("aria-disabled", "true");
        });
        return copy.outerHTML;
      };
      return {
        header: clone(".brand-bar"),
        ticker: clone(".strategy-ticker"),
        board: clone("#intelligenceBoard"),
        drawer: clone("#intelligenceDrawerBackdrop"),
        styleHref: document.querySelector('link[href*="styles.css"]')?.href || "",
        leadershipStyleHref: document.querySelector('link[href*="leadership-board.css"]')?.href || "",
      };
    });
    if (!fragments.styleHref) throw new Error("Unable to resolve runtime stylesheet");

    const styleResponse = await context.request.get(fragments.styleHref);
    if (!styleResponse.ok()) throw new Error(`Stylesheet request failed: ${styleResponse.status()}`);
    const css = (await styleResponse.text())
      .replaceAll('url("/static/assets/', 'url("./assets/')
      .replaceAll("url('/static/assets/", "url('./assets/");
    fs.writeFileSync(
      path.join(OUTPUT_DIR, "styles.css"),
      `${css.trimEnd()}\n${staticOverrides().trim()}\n`,
    );
    if (fragments.leadershipStyleHref) {
      const leadershipResponse = await context.request.get(fragments.leadershipStyleHref);
      if (!leadershipResponse.ok()) throw new Error(`Leadership stylesheet request failed: ${leadershipResponse.status()}`);
      const leadershipCss = (await leadershipResponse.text())
        .replaceAll('url("/static/assets/', 'url("./assets/')
        .replaceAll("url('/static/assets/", "url('./assets/");
      fs.writeFileSync(
        path.join(OUTPUT_DIR, "leadership-board.css"),
        `${leadershipCss.trimEnd()}\n${staticOverrides().trim()}\n`,
      );
    }

    const appSource = fs.readFileSync(path.join(ROOT, "web", "static", "app.js"), "utf8");
    const boardStart = appSource.indexOf("/* Four-domain executive intelligence board:");
    const boardEnd = appSource.indexOf("/* Strategic briefing ticker:", boardStart);
    if (boardStart < 0 || boardEnd < 0) throw new Error("Unable to isolate intelligence interaction module");
    let boardScript = appSource.slice(boardStart, boardEnd);
    const runtimeFetch = 'fetch("/api/executive-intelligence", { cache: "no-store" })';
    const staticFetch = 'Promise.resolve({ ok: true, json: () => Promise.resolve(window.CMHK_STATIC_INTELLIGENCE) })';
    if (!boardScript.includes(runtimeFetch)) throw new Error("Intelligence API call shape changed; snapshot build stopped");
    boardScript = boardScript.replace(runtimeFetch, staticFetch);
    const refreshStart = boardScript.indexOf("  async function refreshFocusInsight(");
    const refreshEnd = boardScript.indexOf("\n  function renderDrawer(", refreshStart);
    if (refreshStart < 0 || refreshEnd < 0) throw new Error("Unable to isolate runtime-only insight refresh");
    boardScript = boardScript.slice(0, refreshStart)
      + "  function refreshFocusInsight() {}\n"
      + boardScript.slice(refreshEnd);
    boardScript = boardScript.replace(
      "window.setInterval(() => refreshIntelligencePayload(false), 60000);",
      "window.setInterval(() => {}, 60000);",
    );
    const staticPayload = JSON.stringify(intelligencePayload)
      .replaceAll("<", "\\u003c")
      .replaceAll(">", "\\u003e")
      .replaceAll("&", "\\u0026");
    const tickerScript = `
(() => {
  const list = document.getElementById("strategyTickerList");
  const track = list?.querySelector(".strategy-ticker-track");
  if (!list || !track) return;
  let paused = false;
  let offset = 0;
  let last = performance.now();
  const speed = 42;
  const firstSet = Array.from(track.children).filter((item) => !item.classList.contains("strategy-ticker-clone"));
  const loopWidth = () => firstSet.reduce((total, item) => total + item.getBoundingClientRect().width, 0);
  const tick = (now) => {
    const elapsed = Math.min(48, now - last);
    last = now;
    if (!paused) {
      offset -= speed * elapsed / 1000;
      const width = loopWidth();
      if (width > 0 && -offset >= width) offset += width;
      track.style.transform = \`translate3d(\${offset}px, 0, 0)\`;
    }
    requestAnimationFrame(tick);
  };
  ["pointerenter", "focusin", "touchstart"].forEach((eventName) => list.addEventListener(eventName, () => { paused = true; }));
  ["pointerleave", "focusout", "touchend"].forEach((eventName) => list.addEventListener(eventName, () => { paused = false; }));
  requestAnimationFrame(tick);
})();
`;
    fs.writeFileSync(
      path.join(OUTPUT_DIR, "intelligence.js"),
      `window.CMHK_STATIC_INTELLIGENCE = ${staticPayload};\n${boardScript}\n${tickerScript}`,
    );

    const assets = [
      ["china-mobile-blue-logo.png", "china-mobile-blue-logo.png"],
      ["executive-intelligence-bg-v2.webp", "executive-intelligence-bg-v2.webp"],
      ["competitive-intelligence-radar-v3.webp", "competitive-intelligence-radar-v3.webp"],
      ["mobile-intelligence-bg.png", "mobile-intelligence-bg.png"],
      ["mobile-blue-network-banner.png", "mobile-blue-network-banner.png"],
      ["logo/xiaojing-ai-logo-mark.png", "logo/xiaojing-ai-logo-mark.png"],
      ["executive-dashboard/network-hong-kong.webp", "executive-dashboard/network-hong-kong.webp"],
      ["executive-dashboard/enterprise-cloud.webp", "executive-dashboard/enterprise-cloud.webp"],
      ["executive-dashboard/financial-technology-grid.webp", "executive-dashboard/financial-technology-grid.webp"],
    ];
    for (const [sourceName, targetName] of assets) {
      const url = new URL(`/static/assets/${sourceName}`, SOURCE_URL).toString();
      await fetchAsset(context, url, path.join(OUTPUT_DIR, "assets", targetName));
    }

    const localizeAssets = (value) => value.replaceAll("/static/assets/", "./assets/");
    const content = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="robots" content="noindex, nofollow">
  <title>中国移动香港｜四库竞争情报驾驶舱</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="./styles.css">
  <link rel="stylesheet" href="./leadership-board.css?v=10">
</head>
<body class="dashboard-page static-snapshot">
  <main class="app-shell">
    ${localizeAssets(fragments.header)}
    <section class="console-shell">
      <section class="operations" aria-label="四库竞争情报驾驶舱">
        <section class="insight-board" aria-label="四库竞争情报态势看板">
          ${localizeAssets(fragments.ticker)}
          ${localizeAssets(fragments.board)}
          ${localizeAssets(fragments.drawer)}
        </section>
      </section>
    </section>
  </main>
  <script src="./intelligence.js?v=2"></script>
</body>
</html>\n`;
    fs.writeFileSync(path.join(OUTPUT_DIR, "index.html"), content.replace(/[ \t]+$/gm, ""));
    fs.writeFileSync(path.join(OUTPUT_DIR, ".nojekyll"), "");

    if (errors.length) {
      throw new Error(`Runtime page errors: ${errors.join(" | ")}`);
    }
    process.stdout.write(JSON.stringify({
      status: "built",
      source_url: SOURCE_URL,
      output_dir: OUTPUT_DIR,
      domains: 4,
    }) + "\n");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
