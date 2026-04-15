const { setGlobalDispatcher, EnvHttpProxyAgent } = require('undici');

let initialized = false;

function normalizeProxyEnv() {
  if (!process.env.HTTP_PROXY && process.env.http_proxy) {
    process.env.HTTP_PROXY = process.env.http_proxy;
  }
  if (!process.env.HTTPS_PROXY && process.env.https_proxy) {
    process.env.HTTPS_PROXY = process.env.https_proxy;
  }
  if (!process.env.ALL_PROXY && process.env.all_proxy) {
    process.env.ALL_PROXY = process.env.all_proxy;
  }
  if (!process.env.NO_PROXY && process.env.no_proxy) {
    process.env.NO_PROXY = process.env.no_proxy;
  }
}

function ensureProxySupport() {
  if (initialized) return;
  initialized = true;

  normalizeProxyEnv();

  const hasProxy = Boolean(
    process.env.HTTP_PROXY || process.env.HTTPS_PROXY || process.env.ALL_PROXY
  );

  if (!hasProxy) return;

  try {
    setGlobalDispatcher(new EnvHttpProxyAgent());
  } catch (error) {
    // 代理配置失败时保持默认直连，避免影响本地接口调用
    console.warn(`proxy setup skipped: ${error.message}`);
  }
}

module.exports = {
  ensureProxySupport
};
