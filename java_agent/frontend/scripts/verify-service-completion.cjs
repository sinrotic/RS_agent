// 浏览器夹具验证用户流程；真实部署验收仍由 remote smoke 负责。
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const baseURL = process.env.RS_E2E_BASE_URL || 'http://127.0.0.1:5173';
  let stream;
  let interrupts = 0;
  let created = 0;
  let deleted = 0;
  let deletionBatches = 0;
  let reversed = 0;
  let feedbackEvents = 0;
  const receivedTurns = [];
  const restoredBlock = { type: 'a2ui', messages: [
    { version: 'v0.9', createSurface: { surfaceId: 'retry-result', catalogId: 'urn:rs-agent:a2ui:shopping:v1' } },
    { version: 'v0.9', updateComponents: { surfaceId: 'retry-result', components: [
      { id: 'root', component: 'Text', text: '已恢复的交互界面' },
    ] } },
  ] };
  let preferences = [{ item_id: 'item-1', state: 'like', category: '背包', brand: '测试品牌', feedback_event_id: 'feedback-1', preference_version: 1 }];
  const fixture = http.createServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache',
      'Access-Control-Allow-Origin': baseURL, 'Access-Control-Allow-Credentials': 'true' });
    response.write('event: started\ndata: {"request_id":"running-request"}\n\n');
    stream = response;
    let body = '';
    request.on('data', data => { body += data; });
    request.on('end', () => {
      receivedTurns.push(JSON.parse(body).context.client_turn_id);
      if (receivedTurns.length === 2) {
        response.write(`event: answer_block\ndata: ${JSON.stringify(restoredBlock)}\n\n`);
        response.end();
      } else if (receivedTurns.length === 3) {
        response.end(`event: done\ndata: ${JSON.stringify({ done: true, finish_reason: 'FINAL_ANSWER', response: {
          request_id: 'retry-request', session_id: 'session-existing', profile_user_id: 'profile', turn_index: 2,
          assistant_message: '已经恢复的本轮回答', card_set_id: 'cards-retry', recommended_items: [{ item_id: 'item-1', title: '测试通勤背包', category: '背包', score: 1, reason: '通勤' }], answer_blocks: [restoredBlock],
          degradation_reasons: ['recommendation_unavailable'],
        } })}\n\n`);
      } else if (receivedTurns.length === 4) {
        response.end();
      } else if (receivedTurns.length === 5) {
        response.end(`event: done\ndata: ${JSON.stringify({ done: true, finish_reason: 'FINAL_ANSWER', response: {
          request_id: 'feedback-retry', session_id: 'session-existing', profile_user_id: 'profile', turn_index: 3,
          assistant_message: '反馈之后的推荐已恢复', recommended_items: [], answer_blocks: [],
        } })}\n\n`);
      } else if (receivedTurns.length === 6 || receivedTurns.length === 7) {
        const ended = receivedTurns.length === 7;
        response.end(`event: error\ndata: ${JSON.stringify({ status: ended ? 410 : 409,
          error_code: ended ? 'SESSION_ENDED' : 'TURN_CONFLICT', retryable: false })}\n\n`);
      }
    });
  });
  await new Promise(resolve => fixture.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true,
    ...(process.env.RS_CHROMIUM_PATH ? { executablePath: process.env.RS_CHROMIUM_PATH } : {}) });
  try {
    const context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem('rs_profile_user_id', 'profile');
      localStorage.setItem('rs_chat_session:real:profile', 'session-existing');
    });
    const session = id => ({ sessionId: id, accountId: 'account', profileUserId: 'profile', entryScene: 'agent_chat',
      status: 'ACTIVE', startedAt: '2026-10-10T09:00:00', lastActiveAt: '2026-10-10T09:00:00' });
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      let result = {};
      if (path === '/api/auth/me') result = { accountId: 'account', profileUserId: 'profile', username: '测试账号' };
      else if (path === '/api/sessions' && request.method() === 'POST') { created += 1; result = session('session-new'); }
      else if (path === '/api/sessions') result = [session('session-existing'), session('session-new')];
      else if (path.startsWith('/api/sessions/')) result = session(path.split('/').pop());
      else if (path.endsWith('/history')) result = { session_id: path.split('/')[4], turns: [{
        request_id: 'old-request', turn_index: 1, user_message: '我需要通勤背包', assistant_message: '已经保存的推荐建议',
        recommended_item_ids: [], answer_blocks: [], finish_reason: 'FINAL_ANSWER', card_set_id: '',
      }] };
      else if (path === '/api/agent/chat/stream') return route.continue({ url: `http://127.0.0.1:${fixture.address().port}/stream` });
      else if (path.endsWith('/interrupt')) {
        interrupts += 1; result = { interrupted: true };
        if (stream) stream.end('event: interrupted\ndata: {"reason":"user_stop"}\n\n');
      }
      else if (path === '/api/recommend/preferences/items/item-1' && request.method() === 'DELETE') {
        deletionBatches += 1;
        if (deletionBatches === 2) {
          assert.equal(await page.getByText('此商品的偏好已删除。', { exact: true }).count(), 0, '剩余历史删除前不能显示成功');
          preferences = [];
        }
        result = { feedback_id: `delete-${deletionBatches}`, accepted: true, application_status: 'APPLIED',
          operation_complete: deletionBatches === 2, preference_version: deletionBatches + 2 };
      }
      else if (path === '/api/recommend/preferences' && request.method() === 'DELETE') { deleted += 1; preferences = [];
        result = { preference_version: 2, items: [], operation_complete: true, operations: [] }; }
      else if (path === '/api/recommend/preferences') result = { preference_version: 1, items: preferences };
      else if (path === '/api/recommend/feedback/reversal') {
        reversed += 1; preferences = []; result = { feedback_id: 'reversal', accepted: true, application_status: 'APPLIED', preference_version: 2 };
      }
      else if (path === '/api/recommend/feedback/event') {
        feedbackEvents += 1; result = { feedback_id: 'saved-feedback', accepted: true, application_status: 'APPLIED', preference_version: 2 };
      }
      else if (path === '/api/recommend/feedback/exposure') result = { accepted: true, application_status: 'NOT_APPLICABLE' };
      else if (path === '/api/catalog/items/batch') result = [{ item_id: 'item-1', title: '测试通勤背包', category: '背包' }];
      else throw new Error(`Unexpected fixture request: ${request.method()} ${path}`);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(result) });
    });
    await page.goto('/chat');
    await page.getByText('已经保存的推荐建议', { exact: true }).waitFor();
    assert.equal(created, 0, '恢复会话不能新建 Session');
    await page.reload();
    await page.getByText('已经保存的推荐建议', { exact: true }).waitFor();
    assert.equal(created, 0, '刷新不能丢失会话');
    await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill('继续讨论尺寸');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByRole('button', { name: '停止生成', exact: true }).click();
    await page.getByText('生成已停止', { exact: false }).waitFor();
    assert.equal(interrupts, 1, '停止按钮必须调用服务端中断接口');
    await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill('恢复这轮结果');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByRole('button', { name: '重试原消息', exact: true }).click();
    await page.getByText('已经恢复的本轮回答', { exact: true }).waitFor();
    await page.getByText('已恢复的交互界面', { exact: true }).waitFor();
    await page.getByText('推荐服务暂时不可用', { exact: false }).waitFor();
    assert.equal(receivedTurns[1], receivedTurns[2], '断线重试必须复用 client_turn_id');
    assert.notEqual(await page.getByRole('heading', { name: '智能推荐对话助手' }).evaluate(
      element => getComputedStyle(element.closest('[class*="bg-linear-to-"]')).backgroundImage), 'none', '升级工具链后保留渐变样式');
    if (process.env.RS_E2E_ARTIFACT_DIR) {
      await fs.mkdir(process.env.RS_E2E_ARTIFACT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.RS_E2E_ARTIFACT_DIR, 'chat-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, '窄屏不能被顶部导航撑宽');
      await page.screenshot({ path: path.join(process.env.RS_E2E_ARTIFACT_DIR, 'chat-mobile.png'), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
    await page.getByRole('button', { name: '喜欢，找相似', exact: true }).click();
    await page.getByText('反馈已保存，本轮结果未确认', { exact: false }).waitFor({ timeout: 5000 });
    await page.getByRole('button', { name: '重试原消息', exact: true }).click();
    await page.getByText('反馈之后的推荐已恢复', { exact: true }).waitFor();
    assert.equal(feedbackEvents, 1, '重试生成不能重复提交已应用的反馈');
    assert.equal(receivedTurns[3], receivedTurns[4], '反馈生成重试必须复用 client_turn_id');
    await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill('冲突消息');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByText('本轮尚无确认结果', { exact: false }).waitFor();
    assert.equal(await page.getByRole('button', { name: '重试原消息', exact: true }).count(), 0, '409 不能盲目重试');
    await page.getByRole('button', { name: '刷新历史', exact: true }).waitFor();
    await page.getByPlaceholder('输入您的细化购买需求或调整指令...').fill('过期消息');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByText('会话已结束，请新建对话', { exact: false }).waitFor();
    assert.equal(await page.getByPlaceholder('输入您的细化购买需求或调整指令...').isDisabled(), true);
    await page.getByRole('button', { name: '我的偏好', exact: true }).click();
    await page.getByText('测试通勤背包', { exact: true }).waitFor();
    await page.getByRole('button', { name: '撤销最近反馈' }).click();
    await page.getByText('暂无明确商品偏好', { exact: false }).waitFor();
    assert.equal(reversed, 1);
    preferences = [{ item_id: 'item-1', state: 'dislike', feedback_event_id: 'feedback-2' }];
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByText('测试通勤背包', { exact: true }).waitFor();
    await page.getByRole('button', { name: '删除商品偏好', exact: true }).click();
    await page.getByText('此商品的偏好已删除。', { exact: true }).waitFor();
    assert.equal(deletionBatches, 2, '需要继续处理尚未删除的历史偏好');
    preferences = [{ item_id: 'item-1', state: 'dislike', feedback_event_id: 'feedback-3' }];
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByText('测试通勤背包', { exact: true }).waitFor();
    await page.getByRole('button', { name: '清空偏好', exact: true }).click();
    assert.equal(deleted, 0, '清空需要页面内确认');
    await page.getByRole('button', { name: '确认清空', exact: true }).click();
    await page.getByText('推荐偏好已清空。', { exact: true }).waitFor();
    assert.equal(deleted, 1);
    assert.deepEqual(errors, []);
    console.log('PASS browser: 历史恢复、刷新续聊、服务端中断、原消息重试、A2UI 恢复、降级提示、反馈保存后生成重试、409 禁止盲重试、410 只读、反馈撤销、偏好分批删除和偏好清空');
  } finally {
    stream?.end();
    await browser.close();
    await new Promise(resolve => fixture.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
