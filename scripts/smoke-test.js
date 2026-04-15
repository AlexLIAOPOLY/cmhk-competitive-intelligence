require('dotenv').config();

const { tavilySearch } = require('../src/tavily');
const { deepseekChat } = require('../src/deepseek');
const { readDb } = require('../src/db');

async function testTavily() {
  console.log('测试 Tavily API...');
  const result = await tavilySearch('Vodafone earnings OR annual results', { maxResults: 3 });
  console.log('✓ Tavily 连接成功');
  console.log(`  返回 ${result.results?.length || 0} 条结果`);
  if (result.results?.[0]) {
    console.log(`  示例标题: ${result.results[0].title}`);
    console.log(`  示例链接: ${result.results[0].url}`);
  }
}

async function testDeepSeek() {
  console.log('测试 DeepSeek API...');
  const response = await deepseekChat([
    {
      role: 'user',
      content: '请用一句话总结：Vodafone是全球领先的电信运营商之一。'
    }
  ]);
  console.log('✓ DeepSeek 连接成功');
  console.log(`  响应片段: ${response.substring(0, 80)}...`);
}

function testDatabase() {
  console.log('测试数据库...');
  const db = readDb();
  console.log('✓ 数据库读写正常');
  console.log(`  情报数: ${db.findings.length}`);
  console.log(`  报告数: ${db.reports.length}`);
  console.log(`  任务日志数: ${db.jobs.length}`);
}

async function runSmokeTest() {
  console.log('=== CMHK 竞对监测系统 - 连接与基础能力测试 ===\n');

  testDatabase();
  console.log();

  await testTavily();
  console.log();

  await testDeepSeek();
  console.log('\n✓ 基础能力测试通过。');
}

runSmokeTest().catch((error) => {
  const cause = error?.cause ? ` | cause: ${error.cause.code || ''} ${error.cause.message || ''}` : '';
  console.error(`✗ 测试失败: ${error.message}${cause}`);
  process.exit(1);
});
