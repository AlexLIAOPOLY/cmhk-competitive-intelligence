require('dotenv').config();

const { spawn } = require('child_process');

const port = Number(process.env.E2E_PORT || 3130);
const baseUrl = `http://127.0.0.1:${port}`;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(path, options = {}, timeoutMs = 180000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${baseUrl}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      }
    });

    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = { ok: false, error: '响应不是JSON' };
    }

    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }

    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForServer(maxWaitMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    try {
      const health = await requestJson('/api/health', {}, 5000);
      if (health.ok) return;
    } catch {
      await sleep(1000);
    }
  }
  throw new Error('服务启动超时');
}

function ensureEnvKeys() {
  if (!process.env.DS_API_KEY) {
    throw new Error('缺少 DS_API_KEY，无法执行真实端到端测试');
  }
  if (!process.env.TAVILY_API_KEY) {
    throw new Error('缺少 TAVILY_API_KEY，无法执行真实端到端测试');
  }
}

async function runE2E() {
  ensureEnvKeys();

  console.log('=== CMHK 竞对监测系统 - 端到端测试（真实API） ===');

  const child = spawn('node', ['server.js'], {
    env: {
      ...process.env,
      PORT: String(port),
      SCAN_SCHEDULE: process.env.SCAN_SCHEDULE || '*/30 * * * *'
    },
    stdio: ['ignore', 'pipe', 'pipe']
  });

  child.stdout.on('data', (buf) => {
    process.stdout.write(`[server] ${buf}`);
  });
  child.stderr.on('data', (buf) => {
    process.stderr.write(`[server-err] ${buf}`);
  });

  const stopServer = () => {
    if (!child.killed) {
      child.kill('SIGTERM');
    }
  };

  process.on('exit', stopServer);
  process.on('SIGINT', () => {
    stopServer();
    process.exit(130);
  });

  try {
    await waitForServer();

    console.log('\n1) 获取系统状态');
    const status = await requestJson('/api/status');
    console.log(`   ✓ 当前情报 ${status.findingCount} 条，报告 ${status.reportCount} 份`);

    console.log('2) 执行全量扫描（真实抓取+智能提炼）');
    const scan = await requestJson('/api/scan/run', { method: 'POST' }, 900000);
    console.log(`   ✓ 扫描完成：写入 ${scan.result.totalWritten} 条（新增 ${scan.result.inserted}）`);

    console.log('3) 拉取情报列表并校验');
    const findings = await requestJson('/api/findings?limit=20');
    if (!findings.items.length) {
      throw new Error('扫描后情报列表为空');
    }
    console.log(`   ✓ 情报列表返回 ${findings.items.length} 条`);

    console.log('4) 生成竞对动态周报');
    const weekly = await requestJson('/api/reports/weekly/generate', { method: 'POST' }, 240000);
    console.log(`   ✓ 周报生成成功：${weekly.report.id}`);

    console.log('5) 生成行业趋势研判报告');
    const trend = await requestJson('/api/reports/trends/generate', { method: 'POST' }, 240000);
    console.log(`   ✓ 趋势报告生成成功：${trend.report.id}`);

    console.log('6) 查询报告列表与任务日志');
    const reports = await requestJson('/api/reports?limit=10');
    const jobs = await requestJson('/api/jobs?limit=20');

    if (!reports.items.length) {
      throw new Error('报告列表为空');
    }
    if (!jobs.items.length) {
      throw new Error('任务日志为空');
    }

    const hasWeekly = reports.items.some((item) => item.type === 'weekly');
    const hasTrend = reports.items.some((item) => item.type === 'trend');
    if (!hasWeekly || !hasTrend) {
      throw new Error('报告列表缺少周报或趋势报告');
    }

    console.log(`   ✓ 报告 ${reports.items.length} 份，任务日志 ${jobs.items.length} 条`);
    console.log('\n✓ 端到端测试通过。');
  } finally {
    stopServer();
    await sleep(1000);
  }
}

runE2E().catch((error) => {
  console.error(`\n✗ 端到端测试失败: ${error.message}`);
  process.exit(1);
});
