import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
const phase = process.argv[2], id = process.env.RS_IT_FAULT_ACTIVITY_ID;
assert.ok(id);
const hosts = { seckill: 'http://127.0.0.1:24294', order: 'http://127.0.0.1:24291', inventory: 'http://127.0.0.1:24292' };
async function api(service, path, account, body) {
  const response = await fetch(hosts[service] + path, { method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Account-Id': account || 'fault-reader', Authorization: `Bearer ${process.env.RS_COMMERCE_OPS_WRITE_TOKEN}` },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(10000) });
  assert.ok(response.ok, `${path}: HTTP ${response.status}`);const raw = await response.text();return raw ? JSON.parse(raw) : null;
}
async function wait(read, predicate, label) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    try { const result = await read(); if (predicate(result)) return result; } catch { /* 重启期间允许接口暂不可达。 */ }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error(`${label} 超时`);
}
const activityPath = `/api/seckill/activities/${id}`;
const result = account => api('seckill', `/api/seckill/requests/${account}`, account);
async function submit(account) {
  const payload = { requestId: account, itemId: 'it-item', skuId: 'it-sku', quantity: 1 };
  const first = await api('seckill', activityPath + '/submit', account, payload);
  assert.equal((await api('seckill', activityPath + '/submit', account, payload)).requestId, account);
  return first;
}
async function resolveAndCancel(account) {
  const accepted = await wait(() => result(account), value => !!value.orderId, '恢复后消费');
  const path = `/api/checkout/orders/${accepted.orderId}`;
  await wait(() => api('order', path, account), value => value.status === 'WAITING_PAYMENT', '恢复后锁库');
  await api('order', path + '/cancel', account, {});
  await wait(() => api('order', path, account), value => value.phase === 'DONE', '释放库存');
  await wait(() => result(account), value => value.status === 'CANCELED', '恢复后对账');
  assert.equal((await submit(account)).orderId, accepted.orderId);
  return accepted.orderId;
}
async function kafkaProbe() {
  const response = await fetch(hosts.seckill + '/actuator/prometheus');assert.ok(response.ok);return response.text();
}
// AbortSignal.timeout 的计时器不保持 Node 进程存活；停机期间仍须等待网络超时并重试。
const keepAlive = setInterval(() => {}, 1000);
try {
if (phase === 'prepare') {
  await api('seckill', '/internal/seckill/activities', null, { activityId: id, itemId: 'it-item', skuId: 'it-sku', totalQuantity: 2,
    startsAt: new Date(Date.now() - 1000).toISOString().replace('Z', ''), endsAt: new Date(Date.now() + 300000).toISOString().replace('Z', '') });
  await wait(() => api('seckill', activityPath), value => value.status === 'ACTIVE', '故障活动划拨');
} else if (phase === 'consumer-down') {
  assert.equal((await submit('fault-consumer')).status, 'PROCESSING');
  assert.equal((await result('fault-consumer')).orderId, null);
  assert.equal((await api('seckill', activityPath)).remainingQuantity, 1);
} else if (phase === 'consumer-recovered') {
  await resolveAndCancel('fault-consumer');
  assert.equal((await api('seckill', activityPath)).remainingQuantity, 2);
} else if (phase === 'broker-down') {
  assert.equal((await submit('fault-broker')).status, 'PROCESSING');
  await wait(() => api('seckill', '/internal/seckill/tasks/summary'), value => value.unpublished >= 1, '持久待发布事件');
  await wait(kafkaProbe, text => /rs_commerce_kafka_probe_success 0(?:\.0)?\s/.test(text), 'Kafka 故障监控');
  assert.equal((await result('fault-broker')).orderId, null);
  assert.equal((await api('seckill', activityPath)).remainingQuantity, 1);
} else if (phase === 'broker-recovered') {
  const orderId = await resolveAndCancel('fault-broker');
  const pool = await api('inventory', `/internal/inventory/activities/${id}`);
  assert.equal(pool.available_quantity, 2); assert.equal(pool.reserved_quantity, 0);
  assert.equal((await api('seckill', activityPath)).remainingQuantity, 2);
  await wait(kafkaProbe, text => /rs_commerce_kafka_probe_success 1(?:\.0)?\s/.test(text)
    && /rs_commerce_kafka_consumer_lag 0(?:\.0)?\s/.test(text) && /rs_commerce_kafka_dead_letter_records 0(?:\.0)?\s/.test(text), 'Kafka 消费与监控恢复');
  await writeFile(process.env.RS_IT_FAULT_REPORT, JSON.stringify({ mode: 'REAL_MYSQL_REDIS_KAFKA', activityId: id,
    consumerStopAndServiceRestart: true, brokerOutageAndRecovery: true, kafkaProbeDetectedFailure: true,
    uniqueFinalOrderId: orderId, finalPool: pool, quotaRecovered: true, violations: [] }, null, 2));
} else throw new Error('故障阶段不合法');
console.log(`故障阶段 ${phase} 通过`);
} finally { clearInterval(keepAlive); }
