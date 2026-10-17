// 已部署前端 + 真实鉴权/模型/业务服务。禁止 HTTP 夹具或替换 Agent 响应。
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

async function main() {
  const baseURL = process.env.RS_E2E_BASE_URL || 'http://127.0.0.1:18289';
  assert.ok(process.env.RS_E2E_PRIVATE_FILE && process.env.RS_E2E_OUTPUT, '需要私有验收凭证和证据输出路径');
  const users = JSON.parse(fs.readFileSync(process.env.RS_E2E_PRIVATE_FILE, 'utf8'));
  const account = users.at(-1);
  const output = path.resolve(process.env.RS_E2E_OUTPUT);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const evidence = { base_url: baseURL, mock: false, http_interception: false, cases: [], page_errors: [],
    started_at_utc: new Date().toISOString() };
  const save = () => fs.writeFileSync(output, JSON.stringify(evidence, null, 2));
  const browser = await chromium.launch({ headless: true,
    ...(process.env.RS_CHROMIUM_PATH ? { executablePath: process.env.RS_CHROMIUM_PATH } : {}) });
  const page = await browser.newPage({ baseURL, viewport: { width: 1440, height: 1100 } });
  page.setDefaultTimeout(240000);
  page.on('pageerror', error => evidence.page_errors.push(error.message));
  try {
    const index = await fetch(baseURL + '/');
    assert.equal(index.status, 200);
    evidence.deployed_index_sha256 = crypto.createHash('sha256').update(await index.text()).digest('hex');
    if (process.env.RS_E2E_INDEX_SHA256) assert.equal(evidence.deployed_index_sha256, process.env.RS_E2E_INDEX_SHA256);
    await page.addInitScript(() => {
      localStorage.setItem('rs_agent_use_mock', 'false');
      window.__a2uiNetwork = [];
      const original = window.fetch;
      window.fetch = async (...args) => {
        const url = String(args[0]);
        const response = await original(...args);
        if (url.includes('/agent/chat/stream') || url.includes('/catalog/items/batch')) {
          const record = { url, status: response.status };
          if (url.includes('/agent/chat/stream') && typeof args[1]?.body === 'string') {
            const request = JSON.parse(args[1].body);
            record.session_id = request.session_id;
            record.client_turn_id = request.client_turn_id;
          }
          window.__a2uiNetwork.push(record);
          // 只观察真实响应的 clone，不修改请求、响应或模型输出。
          (async () => {
            const reader = response.clone().body.getReader();
            const decoder = new TextDecoder();
            record.body = '';
            try {
              for (;;) {
                const chunk = await reader.read();
                if (chunk.done) break;
                record.body += decoder.decode(chunk.value, { stream: true });
              }
              record.body += decoder.decode();
            } catch (error) {
              record.read_error = error.message;
            } finally {
              record.complete = true;
            }
          })();
        }
        return response;
      };
    });
    await page.goto('/chat');
    await page.getByPlaceholder('输入用户名').fill(account.username);
    await page.getByPlaceholder('输入账户密码').fill(account.password);
    await page.getByRole('button', { name: '安全登录', exact: true }).click();
    await page.getByRole('button', { name: 'Agent 对话助手', exact: true }).waitFor();
    if (!(await page.getByRole('heading', { name: '智能推荐对话助手' }).count()))
      await page.getByRole('button', { name: 'Agent 对话助手', exact: true }).click();
    await page.getByText('会话连接成功！', { exact: false }).waitFor();
    const definitions = [
      { name: 'no-ui', query: '推荐鼠标' },
      { name: 'model-ui', query: process.env.RS_A2UI_UI_QUERY || '推荐5款鼠标，用 A2UI 商品卡片展示本轮推荐结果。加载 a2ui-interface 后调用 emit_ui，创建 mouse-cards-1 界面，目录为 urn:rs-agent:a2ui:shopping:v1，根组件是 ProductCards，layout 使用 list。只需展示商品，不需要知识检索或原因解释，不要调用 rag_agent 或 call_agent。商品ID只用本轮候选，最后调用 emit_final_answer 给一句简短说明。' },
    ].filter(value => !process.env.RS_A2UI_CASES || process.env.RS_A2UI_CASES.split(',').includes(value.name));
    for (const definition of definitions) {
      await page.getByRole('button', { name: '新建对话', exact: true }).click();
      await page.getByText('会话连接成功！', { exact: false }).waitFor();
      await page.evaluate(() => { window.__a2uiNetwork = []; });
      const sample = { name: definition.name, query: definition.query, start_epoch_ms: Date.now(), passed: false };
      evidence.cases.push(sample); save();
      console.log('开始真实验收:', definition.name);
      await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill(definition.query);
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await page.waitForFunction(() => window.__a2uiNetwork.some(record => record.url.includes('/agent/chat/stream') && record.complete));
      const stream = await page.evaluate(() => window.__a2uiNetwork.find(record => record.url.includes('/agent/chat/stream')));
      sample.stream_status = stream.status;
      sample.session_id = stream.session_id;
      sample.client_turn_id = stream.client_turn_id;
      sample.stream_read_error = stream.read_error;
      sample.events = [];
      let eventName = '';
      for (const line of stream.body.split(/\r?\n/)) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        if (line.startsWith('data:')) sample.events.push({ event: eventName, data: JSON.parse(line.slice(5).trim()) });
      }
      sample.final_response = sample.events.find(event => event.event === 'done')?.data.response;
      sample.end_epoch_ms = Date.now(); sample.elapsed_ms = sample.end_epoch_ms - sample.start_epoch_ms;
      save();
      assert.equal(stream.status, 200);
      assert.equal(sample.events.some(event => event.event === 'error'), false, '真实 Agent 返回错误');
      assert.ok(sample.final_response, 'SSE 未返回完成响应');
      assert.ok(sample.final_response.recommended_items.length > 0, '必须返回真实商品，不把空界面当成功');
      await page.getByText('推荐已更新！', { exact: false }).waitFor();
      await page.waitForFunction(() => window.__a2uiNetwork.some(record => record.url.includes('/catalog/items/batch') && record.complete));
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const rendered = await page.evaluate(() => ({
        catalog: JSON.parse(window.__a2uiNetwork.find(record => record.url.includes('/catalog/items/batch')).body),
        cards: Array.from(document.querySelectorAll('[data-recommend-item-id]')).map(card => ({
          item_id: card.dataset.recommendItemId,
          surface_id: card.closest('[data-a2ui-surface-id]')?.dataset.a2uiSurfaceId,
          title_label: card.querySelector('button[aria-label]')?.getAttribute('aria-label'),
          text: card.textContent,
        })),
        mock_flag: localStorage.getItem('rs_agent_use_mock'),
      }));
      Object.assign(sample, rendered); save();
      assert.equal(rendered.mock_flag, 'false');
      const expectedIds = sample.final_response.recommended_items.map(item => item.item_id);
      assert.deepEqual(rendered.catalog.map(item => item.item_id).sort(), [...expectedIds].sort());
      assert.ok(rendered.cards.length > 0);
      assert.equal(new Set(rendered.cards.map(card => card.item_id)).size, rendered.cards.length, '商品卡片重复');
      for (const card of rendered.cards) {
        assert.ok(expectedIds.includes(card.item_id), '不得展示业务服务未提供的商品');
        assert.ok(card.surface_id, '商品必须经 A2UI 渲染');
        const detail = rendered.catalog.find(item => item.item_id === card.item_id);
        assert.ok(card.title_label.includes(detail.title), '商品标题必须来自真实目录服务');
        if (typeof detail.price === 'number') assert.ok(card.text.includes(`$${detail.price.toFixed(2)}`));
      }
      const uiBlocks = (sample.final_response.answer_blocks || []).filter(block => block.type === 'a2ui');
      sample.model_ui_block_count = uiBlocks.length;
      if (definition.name === 'no-ui') {
        assert.equal(uiBlocks.length, 0, '本例必须覆盖模型未输出 A2UI');
        assert.deepEqual(rendered.cards.map(card => card.item_id).sort(), [...expectedIds].sort());
        assert.ok(rendered.cards.every(card => card.surface_id.startsWith('rs-business-display')));
      } else {
        assert.ok(uiBlocks.length > 0, '模型没有真正输出 A2UI');
        assert.ok(uiBlocks.some(block => block.messages.some(message => message.updateComponents?.components
          .some(component => component.component === 'ProductCards'))), '模型必须输出商品组件描述');
        assert.ok(rendered.cards.every(card => !card.surface_id.startsWith('rs-business-display')),
          '模型 UI 验收不能靠默认业务界面代替');
      }
      await page.screenshot({ path: output.replace(/\.json$/, `-${definition.name}.png`), fullPage: true });
      const idsBeforeReload = rendered.cards.map(card => card.item_id);
      await page.reload();
      await page.waitForFunction(ids => {
        const cards = Array.from(document.querySelectorAll('[data-recommend-item-id]'));
        return cards.length === ids.length && cards.every((card, index) => card.dataset.recommendItemId === ids[index]);
      }, idsBeforeReload);
      sample.restored_cards = await page.locator('[data-recommend-item-id]').evaluateAll(cards => cards.map(card => ({
        item_id: card.dataset.recommendItemId, surface_id: card.closest('[data-a2ui-surface-id]')?.dataset.a2uiSurfaceId,
      })));
      assert.deepEqual(sample.restored_cards.map(card => card.surface_id), rendered.cards.map(card => card.surface_id));
      sample.passed = true; save();
      console.log('PASS', definition.name, 'cards=', rendered.cards.length, 'model_ui_blocks=', uiBlocks.length, 'elapsed_ms=', sample.elapsed_ms);
    }
    assert.deepEqual(evidence.page_errors, []);
    evidence.passed = true;
  } catch (error) {
    evidence.passed = false;
    evidence.failure = error.message;
    evidence.failed_network = await page.evaluate(() => window.__a2uiNetwork).catch(() => []);
    await page.screenshot({ path: output.replace(/\.json$/, '-failure.png'), fullPage: true }).catch(() => undefined);
    throw error;
  } finally {
    evidence.finished_at_utc = new Date().toISOString(); save();
    if (await page.getByTitle('退出登录', { exact: true }).count())
      await page.getByTitle('退出登录', { exact: true }).click().catch(() => undefined);
    await browser.close();
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
