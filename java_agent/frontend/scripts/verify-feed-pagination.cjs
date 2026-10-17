// 在已部署的真实前端上验证换批和反馈，不使用 Mock 数据。
// 需要 Playwright 和一个明确分配给验收使用的空闲画像。
// 可设置 RS_E2E_EVIDENCE_PATH 保存每批实际展示的标题、图片和请求游标。
const { chromium } = require(process.env.RS_PLAYWRIGHT_MODULE || 'playwright');
const { randomBytes } = require('node:crypto');
const assert = require('node:assert/strict');
const { mkdirSync, writeFileSync } = require('node:fs');
const { dirname } = require('node:path');

async function main() {
  const profile = process.env.RS_E2E_PROFILE_ID;
  assert(profile, '请通过 RS_E2E_PROFILE_ID 指定独立验收画像');
  const baseURL = process.env.RS_E2E_BASE_URL || 'http://127.0.0.1:18088';
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.RS_CHROMIUM_PATH ? { executablePath: process.env.RS_CHROMIUM_PATH } : {}),
  });
  const context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1050 } });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  const errors = [];
  const evidence = { captured_at: new Date().toISOString(), base_url: baseURL, batches: [] };
  page.on('pageerror', error => errors.push(error.message));
  let token;
  let feedbackId;
  let likeFeedbackId;
  const cardIds = () => page.locator('[data-recommend-item-id]').evaluateAll(
    cards => cards.map(card => card.getAttribute('data-recommend-item-id')),
  );
  const waitCards = ids => page.waitForFunction(expected => {
    const actual = [...document.querySelectorAll('[data-recommend-item-id]')]
      .map(card => card.getAttribute('data-recommend-item-id'));
    return actual.length === expected.length && expected.every(id => actual.includes(id));
  }, ids);
  const captureBatch = async (action, response, refreshToken) => {
    const cards = await page.locator('[data-recommend-item-id]').evaluateAll(nodes => nodes.map(card => ({
      item_id: card.getAttribute('data-recommend-item-id'),
      title: (card.querySelector('button[aria-label]')?.getAttribute('aria-label') || '')
        .replace(/^查看 /, '').replace(/ 详情$/, ''),
      image_url: card.querySelector('img')?.getAttribute('src') || null,
    })));
    evidence.batches.push({
      action, refresh_token: refreshToken, request_id: response?.request_id,
      source_tags: response?.items.map(item => ({ item_id: item.item_id, source_tags: item.source_tags })),
      cards,
    });
  };
  try {
    await page.goto('/');
    await page.getByRole('button', { name: '没有账户？创建画像账户' }).click();
    await page.getByPlaceholder('输入用户名').fill('paging_' + randomBytes(8).toString('hex'));
    await page.getByPlaceholder('输入账户密码').fill(randomBytes(24).toString('hex'));
    await page.locator('select').selectOption('selected');
    await page.getByPlaceholder('例如: user_12345').fill(profile);
    const registered = page.waitForResponse(response => response.url().endsWith('/api/auth/register'));
    await page.getByRole('button', { name: '绑定画像并注册' }).click();
    const registration = await registered;
    assert.equal(registration.status(), 200);
    token = (await registration.json()).accessToken;
    await page.locator('[data-recommend-item-id]').first().waitFor();
    evidence.mock_flag = await page.evaluate(() => localStorage.getItem('rs_agent_use_mock'));
    await captureBatch('initial');
    const firstPage = await cardIds();
    assert.equal(firstPage.length, 6);
    const seen = new Set(firstPage);
    let pageStart;
    let currentRequestId;
    for (let batch = 0; batch < 2; batch++) {
      const refreshed = page.waitForResponse(response => response.url().endsWith('/api/recommend/home/refresh'));
      await page.getByRole('button', { name: '换一批推荐' }).click();
      const response = await refreshed;
      assert.equal(response.status(), 200);
      pageStart = response.request().postDataJSON().refresh_token;
      assert(pageStart && pageStart !== 'rerecall_pool500', '换批必须发送实际游标');
      const result = await response.json();
      currentRequestId = result.request_id;
      const ids = result.items.map(item => item.item_id);
      await waitCards(ids);
      await captureBatch('different', result, pageStart);
      assert.equal(ids.length, 6);
      assert(ids.every(id => !seen.has(id)), '换批不能重复之前批次的商品');
      ids.forEach(id => seen.add(id));
    }
    console.log('PASS 连续三批共 18 个不同商品');
    const currentPage = await cardIds();
    const event = page.waitForResponse(response => response.url().endsWith('/api/recommend/feedback/event'));
    const reranked = page.waitForResponse(response => response.url().endsWith('/api/recommend/home/refresh'));
    await page.locator('[data-recommend-item-id]').first().getByRole('button', { name: '不感兴趣' }).click();
    const ack = await (await event).json();
    feedbackId = ack.feedback_id;
    assert(ack.accepted);
    const response = await reranked;
    assert.equal(response.request().postDataJSON().refresh_token,
      pageStart.startsWith('feed:') ? `rerank:${currentRequestId}` : pageStart,
      '反馈重排必须引用当前交付批次');
    const result = await response.json();
    const ids = result.items.map(item => item.item_id);
    await waitCards(ids);
    await captureBatch('dislike', result, response.request().postDataJSON().refresh_token);
    assert.equal(ids.length, 6);
    assert(!ids.includes(currentPage[0]), '不喜欢的商品必须被过滤');
    assert(ids.every(id => !firstPage.includes(id)), '反馈后不能跳回第一页');
    assert(result.applied_feedback_event_ids.includes(feedbackId));
    assert.deepEqual(errors, []);
    console.log('PASS 第三批反馈后过滤并补满，保持当前批次');
    const likeEvent = page.waitForResponse(response => response.url().endsWith('/api/recommend/feedback/event'));
    const similarResponse = page.waitForResponse(response => response.url().endsWith('/api/recommend/home/refresh'));
    await page.locator('[data-recommend-item-id]').first().getByRole('button', { name: '喜欢，找相似' }).click();
    const likeAck = await (await likeEvent).json();
    likeFeedbackId = likeAck.feedback_id;
    assert(likeAck.accepted);
    const similar = await similarResponse;
    assert.equal(similar.request().postDataJSON().refresh_token,
      result.next_cursor.startsWith('feed:') ? `similar:${result.request_id}` : pageStart,
      '喜欢找相似必须独立于换不同方向的游标');
    const related = await similar.json();
    await waitCards(related.items.map(item => item.item_id));
    await captureBatch('similar', related, similar.request().postDataJSON().refresh_token);
    assert(related.items.some(item => item.source_tags.some(tag => tag.startsWith('feedback_'))));
    assert(related.items.every(item => !ids.includes(item.item_id)), '找相似应返回新的商品');
    assert.deepEqual(errors, []);
    console.log('PASS 喜欢按钮触发重新召回，返回新的相关商品');
    if (process.env.RS_E2E_AGENT === 'true') {
      await page.getByRole('button', { name: 'Agent 对话助手' }).click();
      await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill('想买适合地铁通勤的头戴式降噪耳机，请根据商品证据用中文推荐。');
      const chatResponse = page.waitForResponse(response => response.url().endsWith('/api/agent/chat'), { timeout: 120000 });
      await page.getByRole('button', { name: '发送', exact: true }).click();
      const chatHttp = await chatResponse;
      assert.equal(chatHttp.status(), 200);
      const chat = await chatHttp.json();
      assert(chat.assistant_message && !chat.assistant_message.startsWith('已根据你的需求筛选商品，具体信息以商品目录'));
      assert(chat.recommended_items.length > 0 && chat.card_set_id);
      await page.waitForFunction(prefix => document.body.innerText.includes(prefix), chat.assistant_message.substring(0, 12));
      const streamResult = await page.evaluate(async ({ token, sessionId }) => {
        const response = await fetch('/api/agent/chat/stream', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ session_id: sessionId, user_message: '请把刚才的耳机选购建议概括为两点。', limit: 3, context: { scene: 'agent_chat' } }),
        });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let text = '', chunks = 0;
        for (;;) { const { value, done } = await reader.read(); if (done) break; text += decoder.decode(value, { stream: true }); chunks++; }
        return { status: response.status, text, chunks, contentType: response.headers.get('content-type') };
      }, { token, sessionId: chat.session_id });
      assert.equal(streamResult.status, 200);
      assert(streamResult.contentType.includes('text/event-stream'));
      assert(streamResult.text.includes('event: done') && !streamResult.text.includes('event: error'), streamResult.text);
      const trace = await context.request.get(`/api/agent/sessions/${chat.session_id}/turns`, { headers: { Authorization: 'Bearer ' + token } });
      assert.equal(trace.status(), 200);
      assert.equal((await trace.json()).turns.length, 2);
      evidence.agent = { card_set_id: chat.card_set_id, session_id: chat.session_id,
        item_ids: chat.recommended_items.map(item => item.item_id), sse_chunks: streamResult.chunks, turns: 2 };
      console.log('PASS 浏览器普通聊天得到模型回答，SSE 完成，两个轮次均可恢复查询；chunks=' + streamResult.chunks);
    }
    evidence.passed = true;
  } catch (error) {
    evidence.passed = false;
    evidence.failure = error.message;
    throw error;
  } finally {
    try {
      if (token) {
        const headers = { Authorization: 'Bearer ' + token };
        try {
          for (const eventId of [likeFeedbackId, feedbackId].filter(Boolean)) {
            const response = await context.request.post('/api/recommend/feedback/reversal', {
              headers, data: { feedback_event_id: eventId },
            });
            assert(response.ok(), '验收反馈撤销失败');
            assert((await response.json()).accepted);
          }
        } finally {
          await context.request.post('/api/auth/logout', { headers, data: {} });
        }
      }
    } finally {
      await browser.close();
      if (process.env.RS_E2E_EVIDENCE_PATH) {
        mkdirSync(dirname(process.env.RS_E2E_EVIDENCE_PATH), { recursive: true });
        writeFileSync(process.env.RS_E2E_EVIDENCE_PATH, JSON.stringify({ ...evidence, browser_errors: errors }, null, 2));
      }
    }
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
