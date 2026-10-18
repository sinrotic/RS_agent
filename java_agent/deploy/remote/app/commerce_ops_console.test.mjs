import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('工作台限制代理路由、保留角色校验并阻止跨站恢复', async () => {
  let received;
  const reader = 'r'.repeat(32), writer = 'w'.repeat(32);
  const upstream = createServer(async (request, response) => {
    const auth = request.headers.authorization;
    if (request.method === 'POST' && auth !== `Bearer ${writer}`) { response.writeHead(403); response.end(); return; }
    let body = ''; for await (const chunk of request) body += chunk;
    received = { path: request.url, auth, body: body ? JSON.parse(body) : null };
    response.writeHead(200, { 'Content-Type': 'application/json' }); response.end('[]');
  });
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  const reservation = createServer();await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port; await new Promise(resolve => reservation.close(resolve));
  const host = `http://127.0.0.1:${port}`, base = `http://127.0.0.1:${upstream.address().port}`;
  const child = spawn(process.execPath, [fileURLToPath(new URL('commerce_ops_console.mjs', import.meta.url))], {
    env: { ...process.env, RS_COMMERCE_CONSOLE_PORT: String(port), RS_ORDER_INTERNAL_URL: base, RS_INVENTORY_INTERNAL_URL: base, RS_PROMOTION_INTERNAL_URL: base },
  });
  let logs = '';
  try {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('工作台未启动')), 5000);
      child.once('error', reject);
      child.stdout.on('data', chunk => { logs += chunk; clearTimeout(timeout); resolve(); });
    });
    const page = await fetch(host);assert.equal(page.status, 200);assert.match(page.headers.get('content-security-policy'), /frame-ancestors 'none'/);
    await fetch(host + '/proxy/checkout', { headers: { Authorization: `Bearer ${reader}` } });
    assert.equal(received.auth, `Bearer ${reader}`); assert.equal(received.path, '/internal/checkout/tasks');
    const path = host + '/proxy/checkout/10/retry';
    const options = { method: 'POST', headers: { Authorization: `Bearer ${writer}`, 'Content-Type': 'application/json', Origin: 'https://untrusted.example' },
      body: JSON.stringify({ operatorId: 'forged', reason: '已核对库存' }) };
    assert.equal((await fetch(path, options)).status, 403);
    options.headers.Origin = host; options.headers.Authorization = `Bearer ${reader}`;
    assert.equal((await fetch(path, options)).status, 403);
    options.headers.Authorization = `Bearer ${writer}`;
    assert.equal((await fetch(path, options)).status, 200);
    assert.deepEqual(received.body, { reason: '已核对库存' });
    assert.equal((await fetch(host + '/proxy/checkout/../orders')).status, 404);
    assert.equal((await fetch(host + '/proxy/checkout/summary', options)).status, 405);
    assert.match(await (await fetch(host+'/manage')).text(), /库存入库与盘点/);
    await fetch(host+'/manage/api/stocks?afterId=sku-a&limit=20',{headers:{Authorization:`Bearer ${reader}`}});
    assert.equal(received.path,'/internal/inventory/management/stocks?afterId=sku-a&limit=20');
    assert.equal((await fetch(host+'/manage/api/stocks?host=evil')).status,400);
    assert.equal((await fetch(host+'/manage/api/stocks/adjust',{...options,headers:{...options.headers,Origin:'https://untrusted.example'}})).status,403);
    assert.equal((await fetch(host+'/manage/api/stocks/adjust',options)).status,200);
    assert.deepEqual(received.body,{reason:'已核对库存'});
    assert.equal(received.path,'/internal/inventory/management/adjustments');
    await fetch(host+'/manage/api/events/order%3A1%3APAID/recommend/retry',options);
    assert.equal(received.path,'/internal/checkout/events/order%3A1%3APAID/recommend/retry');
    assert.ok(!logs.includes(reader) && !logs.includes(writer));
  } finally { child.kill(); await new Promise(resolve => upstream.close(resolve)); }
});
