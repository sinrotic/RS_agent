// 真实浏览器与网络，计时截止到回答、商品 hydration 和 React 提交完成。
const { chromium } = require('../../../java_agent/frontend/node_modules/playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const users = JSON.parse(fs.readFileSync(process.env.RS_E2E_PRIVATE_FILE, 'utf8'));
const route = process.env.RS_E2E_ROUTE || 'fast';
const count = Number(process.env.RS_E2E_COUNT || 3);
const output = process.env.RS_E2E_OUTPUT;

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  const evidence = { route, query: '推荐鼠标', mock: false, samples: [], page_errors: [] };
  try {
    const context = await browser.newContext({ baseURL: 'http://127.0.0.1:18289',
      viewport: { width: 1440, height: 1050 }, extraHTTPHeaders: { 'X-E2E-Route': route } });
    const page = await context.newPage(); page.setDefaultTimeout(180000);
    page.on('pageerror', error => evidence.page_errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem('rs_agent_use_mock', 'false');
      window.__measure = [];
      const fetchOriginal = window.fetch;
      window.fetch = async (...args) => {
        const url = String(args[0]); const start = performance.now();
        const response = await fetchOriginal(...args);
        if (url.includes('/agent/chat/stream') || url.includes('/catalog/items/batch')) {
          const value = { url, start, status: response.status }; window.__measure.push(value);
          // 只观察真实响应的 clone，不修改交给应用的数据。
          response.clone().text().then(text => { value.end = performance.now(); value.body = text; });
        }
        return response;
      };
    });
    await page.goto('/chat');
    await page.getByPlaceholder('输入用户名').fill(users[0].username);
    await page.getByPlaceholder('输入账户密码').fill(users[0].password);
    await page.getByRole('button', { name: '安全登录', exact: true }).click();
    await page.getByRole('button', { name: 'Agent 对话助手', exact: true }).waitFor();
    if (!(await page.getByRole('heading', { name: '智能推荐对话助手' }).count()))
      await page.getByRole('button', { name: 'Agent 对话助手', exact: true }).click();
    await page.getByText('会话连接成功！', { exact: false }).waitFor();
    for (let i = 0; i < count; i++) {
      if (i) {
        await page.getByRole('button', { name: '新建对话', exact: true }).click();
        await page.getByText('会话连接成功！', { exact: false }).waitFor();
      }
      await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill('推荐鼠标');
      await page.evaluate(() => { window.__measure = []; window.__turnStart = performance.now(); });
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await page.getByText('推荐已更新！', { exact: false }).waitFor();
      await page.waitForFunction(() => window.__measure.some(v => v.url.includes('/catalog/items/batch') && v.end));
      const result = await page.evaluate(async () => {
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const complete = performance.now();
        const stream = window.__measure.find(v => v.url.includes('/agent/chat/stream'));
        const catalog = window.__measure.find(v => v.url.includes('/catalog/items/batch'));
        const data = stream.body.split('\n').filter(v => v.startsWith('data:'))
          .map(v => JSON.parse(v.substring(5))).find(v => v.response)?.response;
        const cards = [...document.querySelectorAll('[data-recommend-item-id]')].map(v => ({
          item_id: v.getAttribute('data-recommend-item-id'),
          title: v.querySelector('button[aria-label]')?.getAttribute('aria-label'),
          image_url: v.querySelector('img')?.getAttribute('src') || null,
        }));
        return { complete_render_ms: complete - window.__turnStart, agent_sse_ms: stream.end-stream.start,
          catalog_ms: catalog.end-catalog.start, catalog: JSON.parse(catalog.body), cards,
          final_response: data, mock_flag: localStorage.getItem('rs_agent_use_mock') };
      });
      assert.equal(result.mock_flag, 'false'); assert.equal(result.cards.length, 5);
      assert(result.final_response?.assistant_message);
      const expected = result.final_response.recommended_items.map(v => v.item_id).sort();
      assert.deepEqual(result.cards.map(v => v.item_id).sort(), expected);
      assert.deepEqual(result.catalog.map(v => v.item_id).sort(), expected);
      result.index = i; evidence.samples.push(result);
      console.log(route, 'browser', i, Math.round(result.complete_render_ms), 'ms');
      fs.writeFileSync(output, JSON.stringify(evidence, null, 2));
    }
    await page.screenshot({ path: output.replace(/\.json$/, '.png'), fullPage: true });
  } finally { await browser.close(); fs.writeFileSync(output, JSON.stringify(evidence, null, 2)); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
