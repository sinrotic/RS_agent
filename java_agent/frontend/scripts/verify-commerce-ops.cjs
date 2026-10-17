// 页面 API 夹具验证；后台认证和代理安全由 Java/Node 测试及真实中间件验收覆盖。
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
async function main() {
  const port = 24696;
  const child = spawn(process.execPath, [path.resolve(__dirname, '../../deploy/remote/app/commerce_ops_console.mjs')], {
    windowsHide: true, env: { ...process.env, RS_COMMERCE_CONSOLE_PORT: String(port) },
  });
  let browser;
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('工作台未启动')), 5000);
      child.once('error', reject);child.stdout.once('data', () => { clearTimeout(timer);resolve(); });
    });
    browser = await chromium.launch({ headless: true, ...(process.env.RS_CHROMIUM_PATH ? { executablePath: process.env.RS_CHROMIUM_PATH } : {}) });
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    const errors = [];page.on('pageerror', error => errors.push(error.message));
    let recovered = false, action;
    await page.route('**/proxy/**', async route => {
      const request = route.request(), endpoint = new URL(request.url()).pathname;
      let body;
      if (request.method() === 'POST') {
        assert.equal(request.headers().authorization, 'Bearer fixture-writer');action = request.postDataJSON();recovered = true;body = null;
      } else if (endpoint.endsWith('/summary')) body = { pending: endpoint === '/proxy/seckill/summary' && recovered ? 0 : 1,
        reviewRequired: endpoint === '/proxy/seckill/summary' && recovered ? 0 : 1 };
      else if (endpoint === '/proxy/seckill') body = recovered ? [] : [{ eventId: 'original-event', status: 'REVIEW_REQUIRED', attempts: 10, lastError: '下游暂不可用' }];
      else if (endpoint === '/proxy/checkout') body = [{ orderId: 1001, status: 'PAID', phase: 'REVIEW_CONFIRM_STOCK', lastError: '库存核销待核对' }];
      else if (endpoint === '/proxy/payment') body = [{ orderId: 1002, status: 'REVIEW', lastError: '支付通知待核对' }];
      else body = [{ activity_id: 'activity', status: 'REVIEW', last_error: '库存划拨不足' }];
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByLabel('只读运维凭证').fill('fixture-reader');await page.getByLabel('写入运维凭证').fill('fixture-writer');
    await page.getByRole('button', { name: '刷新任务' }).click();await page.getByRole('status').getByText('查询完成').waitFor();
    assert.equal(await page.getByRole('button', { name: '恢复原任务' }).count(), 4);
    await page.getByRole('button', { name: '恢复原任务' }).first().click();
    await page.getByRole('status').getByText('请填写核对后的恢复原因').waitFor();assert.equal(action, undefined);
    await page.getByLabel('恢复原因').fill('下游服务已恢复，按原事件重试');
    await page.getByRole('button', { name: '恢复原任务' }).first().click();
    await page.getByRole('status').getByText('已恢复原任务', { exact: false }).waitFor();
    assert.deepEqual(action, { reason: '下游服务已恢复，按原事件重试' });assert.deepEqual(errors, []);
    const output = path.resolve(__dirname, '../../../outputs/commerce-allocation-optimization-20261011/operations-browser.png');
    await fs.mkdir(path.dirname(output), { recursive: true });await page.screenshot({ path: output, fullPage: true });
    console.log('运维工作台浏览器验证通过：四类异常查看、恢复原因必填、原任务重试与刷新');
  } finally { if (browser) await browser.close();child.kill(); }
}
main().catch(error => { console.error(error);process.exitCode = 1; });
