require('dotenv').config();
const { ensureProxySupport } = require('./network');

const DS_API_KEY = process.env.DS_API_KEY;
const DS_MODEL = process.env.DS_MODEL || 'deepseek-chat';
const DS_TIMEOUT_MS = Number(process.env.DS_TIMEOUT_MS || 30000);

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

async function deepseekChat(messages, temperature = 0.2, options = {}) {
  ensureProxySupport();

  if (!DS_API_KEY) {
    throw new Error('缺少 DS_API_KEY');
  }

  const timeoutMs = Number(options.timeoutMs || DS_TIMEOUT_MS);
  const controller = new AbortController();
  const unbindExternal = bindExternalAbort(controller, options.signal);
  const timeout = setTimeout(() => controller.abort(new Error('request-timeout')), timeoutMs);

  try {
    const response = await fetch('https://api.deepseek.com/chat/completions', {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${DS_API_KEY}`
      },
      body: JSON.stringify({
        model: DS_MODEL,
        messages,
        temperature,
        stream: false
      })
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`DeepSeek 请求失败: ${response.status} ${text}`);
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content;

    if (!content) {
      throw new Error('DeepSeek 返回内容为空');
    }

    return content;
  } catch (error) {
    if (error.name === 'AbortError') {
      if (options.signal?.aborted) {
        const abortError = new Error('DeepSeek 请求已中止');
        abortError.code = 'REQUEST_ABORTED';
        throw abortError;
      }
      throw new Error(`DeepSeek 请求超时（>${timeoutMs}ms）`);
    }
    throw error;
  } finally {
    unbindExternal();
    clearTimeout(timeout);
  }
}

async function deepseekChatStream(messages, temperature = 0.2, options = {}) {
  ensureProxySupport();

  if (!DS_API_KEY) {
    throw new Error('缺少 DS_API_KEY');
  }

  const timeoutMs = Number(options.timeoutMs || DS_TIMEOUT_MS);
  const controller = new AbortController();
  const unbindExternal = bindExternalAbort(controller, options.signal);
  const timeout = setTimeout(() => controller.abort(new Error('request-timeout')), timeoutMs);

  try {
    const response = await fetch('https://api.deepseek.com/chat/completions', {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${DS_API_KEY}`
      },
      body: JSON.stringify({
        model: DS_MODEL,
        messages,
        temperature,
        stream: true
      })
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`DeepSeek 请求失败: ${response.status} ${text}`);
    }

    if (!response.body) {
      throw new Error('DeepSeek 流式返回为空');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let pending = '';
    let full = '';

    const parseLine = (line) => {
      const trimmed = String(line || '').trim();
      if (!trimmed || !trimmed.startsWith('data:')) return;
      const payload = trimmed.slice(5).trim();
      if (!payload || payload === '[DONE]') return;

      try {
        const parsed = JSON.parse(payload);
        const delta = parsed.choices?.[0]?.delta?.content;
        if (!delta) return;
        full += delta;
        if (typeof options.onDelta === 'function') {
          options.onDelta(delta);
        }
      } catch {
        // Ignore malformed stream line.
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      pending += decoder.decode(value, { stream: true });
      let idx = pending.indexOf('\n');
      while (idx >= 0) {
        const line = pending.slice(0, idx);
        pending = pending.slice(idx + 1);
        parseLine(line);
        idx = pending.indexOf('\n');
      }
    }

    if (pending.trim()) {
      parseLine(pending);
    }

    if (!full) {
      throw new Error('DeepSeek 流式内容为空');
    }

    return full;
  } catch (error) {
    if (error.name === 'AbortError') {
      if (options.signal?.aborted) {
        const abortError = new Error('DeepSeek 请求已中止');
        abortError.code = 'REQUEST_ABORTED';
        throw abortError;
      }
      throw new Error(`DeepSeek 请求超时（>${timeoutMs}ms）`);
    }
    throw error;
  } finally {
    unbindExternal();
    clearTimeout(timeout);
  }
}

module.exports = { deepseekChat, deepseekChatStream };
