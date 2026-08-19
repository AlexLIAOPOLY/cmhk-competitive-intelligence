(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const root = new URL("./", document.baseURI);
  const snapshotRoutes = new Map([
    ["/api/status", "static-data/status.json"],
    ["/api/company-metrics", "static-data/company-metrics.json"],
    ["/api/executive-intelligence", "static-data/executive-intelligence.json"],
    ["/api/strategic-briefs", "strategic-briefs.json"],
    ["/api/project-incidents", "static-data/project-incidents.json"],
    ["/api/crawl-runs", "static-data/crawl-runs.json"],
    ["/api/task-runs", "static-data/task-runs.json"],
    ["/api/scheduler-overview", "static-data/scheduler-overview.json"],
    ["/api/news-review-sheet", "static-data/news-review-sheet.json"],
    ["/api/weekly-report-preview", "static-data/weekly-report-preview.json"],
  ]);
  const lookupRoutes = new Map([
    ["/api/crawl-run-log", ["static-data/crawl-run-details.json", "details"]],
    ["/api/task-run-log", ["static-data/task-run-details.json", "details"]],
  ]);
  const inlineRoutes = new Map([
    ["/api/agent-datasets", { ok: true, datasets: [] }],
    ["/api/agent-memory", { ok: true, memories: [] }],
    ["/api/agent-skills", { ok: true, skills: [] }],
    ["/api/agent-trace", { ok: true, events: [] }],
    ["/api/ai-config", { ok: true, config: { provider: "", base_url: "", model: "", has_api_key: false } }],
    ["/api/ai-models", { ok: true, models: [] }],
    ["/api/chat-starters", { ok: true, starters: [] }],
    ["/api/chat-threads", { ok: true, threads: [] }],
  ]);
  const snapshotCache = new Map();

  function jsonResponse(payload, status = 200) {
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  async function lookupSnapshot(route, requestUrl) {
    const [relative, collectionKey] = lookupRoutes.get(route);
    if (!snapshotCache.has(relative)) {
      snapshotCache.set(relative, nativeFetch(new URL(relative, root), { cache: "no-store" }).then((response) => response.json()));
    }
    const payload = await snapshotCache.get(relative);
    const id = requestUrl.searchParams.get("id") || "";
    const item = payload?.[collectionKey]?.[id];
    return item
      ? jsonResponse(item)
      : jsonResponse({ ok: false, error: "该历史记录未包含在公开快照中。" }, 404);
  }

  window.CMHK_PUBLIC_SNAPSHOT = Object.freeze({ readOnly: true });
  window.fetch = function publicSnapshotFetch(input, init = {}) {
    const requestUrl = new URL(typeof input === "string" ? input : input.url, window.location.href);
    const method = String(init.method || (typeof input !== "string" && input.method) || "GET").toUpperCase();
    if (requestUrl.origin === window.location.origin && requestUrl.pathname.startsWith("/static/")) {
      const relative = requestUrl.pathname.slice("/static/".length);
      return nativeFetch(new URL(`static/${relative}${requestUrl.search}`, root), init);
    }
    if (!requestUrl.pathname.startsWith("/api/")) return nativeFetch(input, init);
    const route = requestUrl.pathname;
    if (method === "GET" && snapshotRoutes.has(route)) {
      return nativeFetch(new URL(snapshotRoutes.get(route), root), { cache: "no-store" });
    }
    if (method === "GET" && lookupRoutes.has(route)) return lookupSnapshot(route, requestUrl);
    if (inlineRoutes.has(route) && (method === "GET" || route === "/api/ai-models")) {
      return Promise.resolve(jsonResponse(inlineRoutes.get(route)));
    }
    return Promise.resolve(jsonResponse({ ok: false, error: "公开网页是只读快照，请在 CMHK 内网主页执行此操作。" }, 403));
  };

  function lockPrivateControls() {
    document.body.classList.add("public-snapshot");
    document.querySelectorAll([
      "#crawlButtonSecondary", "#generateButtonSecondary", "#generatePerformanceButton",
      "#aiSettingsButton", "#composerUploadFileButton", "#composerUploadImageButton",
      "[data-generate-report]", "[data-intelligence-insight-refresh]",
      "[data-intelligence-relation-refresh]", "[data-refresh-fault]",
    ].join(",")).forEach((item) => {
      item.hidden = true;
      item.setAttribute("aria-hidden", "true");
    });
    document.querySelectorAll(".strategy-ticker-footer a").forEach((item) => item.hidden = true);
  }
  document.addEventListener("DOMContentLoaded", lockPrivateControls);
  new MutationObserver(lockPrivateControls).observe(document.documentElement, { childList: true, subtree: true });
})();
