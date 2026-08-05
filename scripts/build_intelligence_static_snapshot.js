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
  ["international", "领先差距"],
  ["cloud", "增长趋势"],
  ["macro", "流量需求"],
];

function cleanDirectory(directory) {
  fs.rmSync(directory, { recursive: true, force: true });
  fs.mkdirSync(path.join(directory, "assets"), { recursive: true });
  fs.mkdirSync(path.join(directory, "assets", "logo"), { recursive: true });
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
.static-snapshot [role="button"], .static-snapshot button, .static-snapshot a {
  cursor: default !important;
  pointer-events: none !important;
}
.static-snapshot .intelligence-scroll-label-track { animation-play-state: paused !important; }
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

    const fragments = await page.evaluate(() => {
      const clone = (selector) => {
        const node = document.querySelector(selector);
        if (!node) throw new Error(`Missing snapshot element: ${selector}`);
        const copy = node.cloneNode(true);
        copy.querySelectorAll("script, [hidden]").forEach((item) => item.remove());
        copy.querySelectorAll("a").forEach((item) => item.removeAttribute("href"));
        copy.querySelectorAll("[tabindex]").forEach((item) => item.removeAttribute("tabindex"));
        copy.querySelectorAll('[role="button"]').forEach((item) => item.setAttribute("aria-disabled", "true"));
        return copy.outerHTML;
      };
      return {
        header: clone(".brand-bar"),
        ticker: clone(".strategy-ticker"),
        board: clone("#intelligenceBoard"),
        styleHref: document.querySelector('link[href*="styles.css"]')?.href || "",
      };
    });
    if (!fragments.styleHref) throw new Error("Unable to resolve runtime stylesheet");

    const styleResponse = await context.request.get(fragments.styleHref);
    if (!styleResponse.ok()) throw new Error(`Stylesheet request failed: ${styleResponse.status()}`);
    const css = (await styleResponse.text())
      .replaceAll('url("/static/assets/', 'url("./assets/')
      .replaceAll("url('/static/assets/", "url('./assets/");
    fs.writeFileSync(path.join(OUTPUT_DIR, "styles.css"), `${css}\n${staticOverrides()}\n`);

    const assets = [
      ["china-mobile-blue-logo.png", "china-mobile-blue-logo.png"],
      ["executive-intelligence-bg-v2.webp", "executive-intelligence-bg-v2.webp"],
      ["mobile-intelligence-bg.png", "mobile-intelligence-bg.png"],
      ["mobile-blue-network-banner.png", "mobile-blue-network-banner.png"],
      ["logo/xiaojing-ai-logo-mark.png", "logo/xiaojing-ai-logo-mark.png"],
    ];
    for (const [sourceName, targetName] of assets) {
      const url = new URL(`/static/assets/${sourceName}`, SOURCE_URL).toString();
      await fetchAsset(context, url, path.join(OUTPUT_DIR, "assets", targetName));
    }

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
</head>
<body class="dashboard-page static-snapshot">
  <main class="app-shell">
    ${fragments.header.replaceAll('/static/assets/', './assets/')}
    <section class="console-shell">
      <section class="operations" aria-label="四库竞争情报驾驶舱">
        <section class="insight-board" aria-label="四库竞争情报态势看板">
          ${fragments.ticker}
          ${fragments.board}
        </section>
      </section>
    </section>
  </main>
</body>
</html>\n`;
    fs.writeFileSync(path.join(OUTPUT_DIR, "index.html"), content);
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
