require('dotenv').config();
const { ensureProxySupport } = require('./network');

const TAVILY_API_KEY = process.env.TAVILY_API_KEY;
const TAVILY_TIMEOUT_MS = Number(process.env.TAVILY_TIMEOUT_MS || 15000);

function bindExternalAbort(controller, signal) {
  if (!signal) {
    return () => {};
  }

  if (signal.aborted) {
    controller.abort(signal.reason || new Error('external-aborted'));
    return () => {};
  }

  const onAbort = () => {
    controller.abort(signal.reason || new Error('external-aborted'));
  };
  signal.addEventListener('abort', onAbort, { once: true });
  return () => signal.removeEventListener('abort', onAbort);
}

async function tavilySearch(query, options = {}) {
  ensureProxySupport();

  if (!TAVILY_API_KEY) {
    throw new Error('缺少 TAVILY_API_KEY');
  }

  const maxResults = Number(options.maxResults || process.env.MAX_RESULTS_PER_QUERY || 8);
  const timeoutMs = Number(options.timeoutMs || TAVILY_TIMEOUT_MS);
  const searchDepth = String(options.searchDepth || 'advanced');
  const topic = String(options.topic || 'news');
  const includeRawContent = Boolean(options.includeRawContent);
  const includeDomains = Array.isArray(options.includeDomains)
    ? options.includeDomains.map((item) => String(item || '').trim()).filter(Boolean).slice(0, 20)
    : [];
  const excludeDomains = Array.isArray(options.excludeDomains)
    ? options.excludeDomains.map((item) => String(item || '').trim()).filter(Boolean).slice(0, 20)
    : [];

  const controller = new AbortController();
  const unbindExternal = bindExternalAbort(controller, options.signal);
  const timeout = setTimeout(() => controller.abort(new Error('request-timeout')), timeoutMs);

  try {
    const response = await fetch('https://api.tavily.com/search', {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        api_key: TAVILY_API_KEY,
        query,
        search_depth: searchDepth,
        max_results: maxResults,
        include_answer: false,
        include_raw_content: includeRawContent,
        topic,
        include_domains: includeDomains,
        exclude_domains: excludeDomains
      })
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Tavily 请求失败: ${response.status} ${text}`);
    }

    const data = await response.json();
    if (!Array.isArray(data.results)) {
      throw new Error('Tavily 返回结构异常：缺少 results 数组');
    }

    return data;
  } catch (error) {
    if (error.name === 'AbortError') {
      if (options.signal?.aborted) {
        const abortError = new Error('Tavily 请求已中止');
        abortError.code = 'REQUEST_ABORTED';
        throw abortError;
      }
      throw new Error(`Tavily 请求超时（>${timeoutMs}ms）`);
    }
    throw error;
  } finally {
    unbindExternal();
    clearTimeout(timeout);
  }
}

module.exports = { tavilySearch };
