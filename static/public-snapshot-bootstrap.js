(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const root = new URL(document.baseURI.includes("/static/") ? "../" : "./", document.baseURI);
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
    ["/api/subscriptions", "static-data/subscriptions.json"],
    ["/api/auth/admin/users", "static-data/organization-users.json"],
    ["/api/auth/admin/audit", "static-data/organization-audit.json"],
  ]);
  const lookupRoutes = new Map([
    ["/api/crawl-run-log", ["static-data/crawl-run-details.json", "details"]],
    ["/api/task-run-log", ["static-data/task-run-details.json", "details"]],
  ]);
  const inlineRoutes = new Map([
    ["/api/auth/me", {
      ok: true,
      authenticated: true,
      user: {
        name: "公开快照",
        role: "VIEWER",
        roleLabel: "只读",
        permissions: { modules: {
          dashboard: true, monitoring: true, competitor: true, news: true,
          weekly: true, performance: true, review: true, log: true, fault: true,
          subscriptions: true, ai: true, organization: true,
        } },
      },
    }],
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
    document.querySelectorAll("#subscriptionAdmin button, #subscriptionAdmin input, #subscriptionAdmin select").forEach((item) => {
      item.disabled = true;
      item.setAttribute("aria-disabled", "true");
    });
    document.querySelectorAll('[data-workspace-panel="competitor"] button, [data-workspace-panel="competitor"] input, [data-workspace-panel="competitor"] select').forEach((item) => {
      item.disabled = true;
      item.setAttribute("aria-disabled", "true");
    });
    document.querySelectorAll("#organizationAdmin [data-directory-open], #organizationAdmin [data-delete-user], #organizationAdmin .organization-save-bar").forEach((item) => {
      item.hidden = true;
      item.setAttribute("aria-hidden", "true");
    });
    document.querySelectorAll("#organizationAdmin [data-role], #organizationAdmin [data-status], #organizationAdmin [data-module]").forEach((item) => {
      item.disabled = true;
      item.setAttribute("aria-disabled", "true");
    });
    const competitorInsight = document.querySelector("#competitorInsight");
    const competitorInsightList = competitorInsight?.querySelector("[data-competitor-insight-list]");
    const fixedCompetitorInsights = [
      "稳定。HKBN两年均为0.907百万户，HKT由1.474升至1.488百万户，差距从约0.567扩至约0.581百万户，显示头部集中态势微幅强化。",
      "HKBN规模持平且动能停滞，HKT以约1.488百万户保持领先并延续微增，两者位置稳固，但HKBN的零增长可能反映其客户获取或留存承压。",
      "HKT的规模优势扩大或强化其网络投入与变现基础，HKBN持平则可能限制其规模竞争弹性，对客户留存策略的依赖度上升；数据锚点为2025年HKBN 0.907百万户。",
    ];
    const renderedCompetitorInsight = competitorInsightList
      ? Array.from(competitorInsightList.querySelectorAll("li span")).map((item) => item.textContent).join("")
      : "";
    if (competitorInsightList && renderedCompetitorInsight !== fixedCompetitorInsights.join("")) {
      competitorInsight.classList.remove("is-loading", "is-streaming");
      competitorInsight.classList.add("is-ai");
      competitorInsight.setAttribute("aria-busy", "false");
      const insightStatus = competitorInsight.querySelector("[data-competitor-insight-status]");
      if (insightStatus) insightStatus.hidden = true;
      const insightBadge = competitorInsight.querySelector("[data-competitor-insight-badge]");
      if (insightBadge) insightBadge.textContent = "COMPETITIVE INSIGHT";
      competitorInsightList.replaceChildren(...fixedCompetitorInsights.map((copy, index) => {
        const item = document.createElement("li");
        const label = document.createElement("b");
        const text = document.createElement("span");
        label.textContent = ["竞争格局", "公司定位", "业务含义"][index];
        text.textContent = copy;
        item.append(label, text);
        return item;
      }));
    }
    ["weekly", "performance"].forEach((kind) => {
      const reportPanel = document.querySelector(`[data-workspace-panel="${kind}"]`);
      const latestReportRow = reportPanel?.querySelector('.workspace-report-host .file-row[data-path]');
      if (latestReportRow && reportPanel.querySelector('[data-report-preview].is-placeholder') && !reportPanel.dataset.publicAutoPreviewed) {
        reportPanel.dataset.publicAutoPreviewed = "true";
        latestReportRow.click();
      }
    });
  }
  function startPrivateControlLock() {
    lockPrivateControls();
    if (document.documentElement) {
      new MutationObserver(lockPrivateControls).observe(document.documentElement, { childList: true, subtree: true });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startPrivateControlLock, { once: true });
  } else {
    startPrivateControlLock();
  }
})();
