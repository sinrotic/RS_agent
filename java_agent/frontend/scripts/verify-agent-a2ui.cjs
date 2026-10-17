// HTTP 夹具验证统一 A2UI 展示；不替代真实模型/服务的部署验收。
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.RS_CHROMIUM_PATH ? { executablePath: process.env.RS_CHROMIUM_PATH } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
    const errors = [], requests = [], feedback = [], exposures = [];
    let failCatalog = false;
    const catalog = [
      { item_id: 'item-1', title: '目录服务通勤背包', category: '背包', price: 55, store_name: '业务店铺' },
      { item_id: 'item-2', title: '目录服务旅行背包', category: '背包', price: 65, store_name: '业务店铺' },
    ];
    const items = catalog.map(item => ({ item_id: item.item_id, title: '业务推荐摘要', category: '背包',
      score: 0.8, reason: '业务推荐理由' }));
    const histories = { 'session-existing': [{ request_id: 'old-request', turn_index: 1,
      user_message: '之前的背包需求', assistant_message: '旧历史没有 A2UI',
      recommended_item_ids: items.map(item => item.item_id),
      answer_blocks: [{ type: 'product_cards', card_set_id: 'old-delivery' }],
      finish_reason: 'FINAL_ANSWER', card_set_id: 'old-delivery' }] };
    const session = id => ({ sessionId: id, accountId: 'account', profileUserId: 'profile',
      entryScene: 'agent_chat', status: 'ACTIVE', startedAt: '2026-10-11T09:00:00', lastActiveAt: '2026-10-11T09:00:00' });
    const uiBlock = messages => ({ type: 'a2ui', messages });
    const update = components => ({ version: 'v0.9', updateComponents: { surfaceId: 'model-shopping', components } });
    const cards = itemIds => ({ id: 'root', component: 'ProductCards', itemIds, layout: 'grid' });
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem('rs_profile_user_id', 'profile');
      localStorage.setItem('rs_chat_session:real:profile', 'session-existing');
    });
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const request = route.request(), endpoint = new URL(request.url()).pathname;
      let result = {};
      if (endpoint === '/api/auth/me') result = { accountId: 'account', profileUserId: 'profile', username: '测试账号' };
      else if (endpoint === '/api/sessions' && request.method() === 'POST') {
        histories['session-new'] = []; result = session('session-new');
      } else if (endpoint === '/api/sessions') result = Object.keys(histories).map(session);
      else if (endpoint.startsWith('/api/sessions/')) result = session(endpoint.split('/').pop());
      else if (endpoint.endsWith('/history')) {
        const id = endpoint.split('/')[4]; result = { session_id: id, turns: histories[id] || [] };
      } else if (endpoint === '/api/catalog/items/batch') {
        if (failCatalog) return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
        result = catalog.filter(item => request.postDataJSON().item_ids.includes(item.item_id));
      } else if (endpoint === '/api/recommend/feedback/exposure') {
        exposures.push(request.postDataJSON()); result = { accepted: true, application_status: 'NOT_APPLICABLE' };
      } else if (endpoint === '/api/recommend/feedback/event') {
        feedback.push(request.postDataJSON()); result = { feedback_id: 'feedback', accepted: true, application_status: 'APPLIED' };
      } else if (endpoint === '/api/agent/chat/stream') {
        const input = request.postDataJSON(); requests.push(input);
        assert.ok(input.context.a2ui_state.every(surface => !surface.surfaceId.startsWith('rs-business-display')),
          '默认业务界面不能混入模型状态回传');
        const query = input.user_message;
        let blocks = [], recommended = items;
        if (query === '旧卡片') blocks = [
          { type: 'product_cards', item_ids: ['item-2', 'item-1', 'unknown'], layout: 'grid' },
          { type: 'followup_question', content: '您更喜欢哪个背包？' },
          { type: 'comparison_table', content: '业务对比文字' },
        ];
        else if (query === '模型卡片') blocks = [uiBlock([
          { version: 'v0.9', createSurface: { surfaceId: 'model-shopping', catalogId: 'urn:rs-agent:a2ui:shopping:v1' } },
          update([cards(['item-2'])]),
        ])];
        else if (query === '改成表单') blocks = [uiBlock([
          update([
            { id: 'root', component: 'Column', children: ['query', 'submit'] },
            { id: 'query', component: 'TextField', label: '界面需求', value: { path: '/query' } },
            { id: 'submit-label', component: 'Text', text: '提交界面需求' },
            { id: 'submit', component: 'Button', child: 'submit-label', action: {
              event: { name: 'submit_query', context: { query: { path: '/query' } } },
            } },
          ]),
          { version: 'v0.9', updateDataModel: { surfaceId: 'model-shopping', value: { query: '' } } },
        ])];
        else if (query === '表单需求') { recommended = [items[0]]; blocks = [uiBlock([update([cards(['item-1'])])])]; }
        else if (query === '未知商品') { recommended = [items[0]]; blocks = [uiBlock([update([cards(['unknown'])])])]; }
        else if (query === '坏UI') { blocks = [uiBlock([
          { version: 'v0.9', createSurface: { surfaceId: 'invalid', catalogId: 'unsupported' } },
        ])]; }
        else if (query === '空推荐') recommended = [];
        else if (query === '目录降级') { recommended = [items[0]]; failCatalog = true; }
        const delivery = `delivery-${requests.length}`;
        const response = { request_id: `request-${requests.length}`, session_id: input.session_id,
          profile_user_id: 'profile', card_set_id: delivery, turn_index: histories[input.session_id].length + 1,
          assistant_message: `${query}已完成`, recommended_items: recommended, answer_blocks: blocks };
        histories[input.session_id].push({ request_id: response.request_id, turn_index: response.turn_index,
          user_message: query, assistant_message: response.assistant_message, card_set_id: delivery,
          finish_reason: 'FINAL_ANSWER', recommended_item_ids: recommended.map(item => item.item_id), answer_blocks: blocks });
        const events = [ ['started', { request_id: response.request_id }],
          ...blocks.map(block => ['answer_block', block]), ['done', { done: true, response }] ];
        return route.fulfill({ contentType: 'text/event-stream', body: events.map(([event, payload]) =>
          `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`).join('') });
      } else throw new Error(`未配置夹具: ${request.method()} ${endpoint}`);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(result) });
    });

    const productCards = page.locator('[data-recommend-item-id]');
    const assertCards = async expected => {
      await page.waitForFunction(ids => {
        const cards = Array.from(document.querySelectorAll('[data-recommend-item-id]'));
        return cards.length === ids.length && cards.every((card, index) => card.dataset.recommendItemId === ids[index]);
      }, expected);
      assert.deepEqual(await productCards.evaluateAll(cards => cards.map(card => card.dataset.recommendItemId)), expected);
      assert.ok(await productCards.evaluateAll(cards => cards.every(card => card.closest('[data-a2ui-surface-id]'))),
        '全部商品卡片都必须从 A2UI 界面渲染');
    };
    const send = async query => {
      const completion = page.getByText(`${query}已完成`, { exact: true });
      const previous = await completion.count();
      await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill(query);
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await completion.nth(previous).waitFor();
    };

    await page.goto(`${process.env.RS_E2E_BASE_URL || 'http://127.0.0.1:5173'}/chat`);
    await page.getByText('旧历史没有 A2UI', { exact: true }).waitFor();
    await assertCards(['item-1', 'item-2']);
    await productCards.first().getByText('$55.00', { exact: true }).waitFor();
    await page.waitForRequest(request => request.url().endsWith('/feedback/exposure'), { timeout: 5000 });
    assert.ok(exposures.every(value => value.request_id === 'old-delivery' && value.session_id === 'session-existing'));
    await page.reload();
    await assertCards(['item-1', 'item-2']);
    await send('无UI'); await assertCards(['item-1', 'item-2']);
    assert.deepEqual(requests.at(-1).context.a2ui_state, []);
    await send('旧卡片'); await assertCards(['item-2', 'item-1']);
    await page.getByText('您更喜欢哪个背包？', { exact: true }).waitFor();
    await page.getByText('业务对比文字', { exact: true }).waitFor();
    await productCards.first().getByRole('button', { name: '喜欢，找相似', exact: true }).click();
    await page.getByText('推荐已更新！', { exact: false }).waitFor();
    assert.equal(feedback.length, 1);
    assert.equal(feedback[0].request_id, 'delivery-2');
    assert.equal(feedback[0].item_id, 'item-2');
    await send('模型卡片'); await assertCards(['item-2']);
    assert.equal(await page.locator('[data-a2ui-surface-id="rs-business-display"]').count(), 0);
    await send('坏UI'); await assertCards(['item-1', 'item-2']);
    await send('无UI'); await assertCards(['item-1', 'item-2']);
    assert.deepEqual(requests.at(-1).context.a2ui_state[0].components.find(value => value.id === 'root').itemIds, ['item-2']);
    await send('改成表单'); await assertCards(['item-1', 'item-2']);
    await send('无UI'); await assertCards(['item-1', 'item-2']);
    await page.getByLabel('界面需求').fill('表单需求');
    await page.getByRole('button', { name: '提交界面需求', exact: true }).click();
    await page.getByText('表单需求已完成', { exact: true }).waitFor();
    await assertCards(['item-1']);
    assert.equal(requests.at(-1).context.a2ui_state[0].data.query, '表单需求');
    await send('未知商品'); await assertCards(['item-1']);
    assert.equal(await page.locator('[data-recommend-item-id="unknown"]').count(), 0);
    await send('坏UI'); await assertCards(['item-1', 'item-2']);
    await page.getByText('交互界面暂时无法显示', { exact: false }).waitFor();
    await send('目录降级'); await assertCards(['item-1']);
    await page.getByText('商品详情暂时无法加载', { exact: false }).waitFor();
    await productCards.first().getByText('业务推荐摘要', { exact: true }).waitFor();
    failCatalog = false;
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await productCards.first().getByText('目录服务通勤背包', { exact: true }).waitFor();
    if (process.env.RS_E2E_ARTIFACT_DIR) {
      await fs.mkdir(process.env.RS_E2E_ARTIFACT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.RS_E2E_ARTIFACT_DIR, 'agent-a2ui.png'), fullPage: true });
    }
    await send('空推荐'); await assertCards([]);
    await page.locator('[data-a2ui-surface-id]').getByText('暂无对话推荐商品', { exact: false }).waitFor();
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    await page.getByText('会话ID: session-new', { exact: false }).waitFor();
    assert.equal(await page.locator('[data-a2ui-surface-id="model-shopping"]').count(), 0);
    await send('无UI'); await assertCards(['item-1', 'item-2']);
    assert.deepEqual(requests.at(-1).context.a2ui_state, []);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('PASS A2UI 浏览器夹具：旧历史恢复、无模型UI、旧回答块、模型UI去重/跨Turn兜底、表单状态隔离/回传、未知商品、坏UI、目录降级/重试、空结果、新Session、反馈/曝光归因和窄屏');
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
