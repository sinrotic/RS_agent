import assert from 'node:assert/strict';
import { randomUUID, createHmac } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';

const base='http://127.0.0.1:24488';
const hosts={order:24491,inventory:24492,payment:24493,seckill:24494,promotion:24495,recommend:24403};
const env=process.env, phase=process.argv[2]||'load', metrics=new Map();
const keepAlive=setInterval(()=>{},1000); // fetch 超时/连接重建期间也保持进程存活。
const checkpoint=env.RS_IT_PRIVATE_STATE;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function request(url,body,token,expected,extra={}) {
  const start=performance.now(), method=body===undefined?'GET':'POST';
  const response=await fetch(url,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`} : {}),...extra},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
  const key=method+' '+new URL(url).pathname.replace(/\/\d+(?=\/|$)/g,'/:id').replace(/[a-f0-9]{8}-[a-f0-9-]{27,}/g,':uuid');
  const metric=metrics.get(key)||{latencies:[],statuses:{}};metric.latencies.push(performance.now()-start);metric.statuses[response.status]=(metric.statuses[response.status]||0)+1;metrics.set(key,metric);
  if(expected!==undefined) {assert.equal(response.status,expected,key);return;}
  assert.ok(response.ok,`${key}: HTTP ${response.status}`);const text=await response.text();return text?JSON.parse(text):null;
}
const api=(path,user,body,expected,extra)=>request(base+path,body,user?.accessToken,expected,extra);
const admin=(service,path,body,expected,read=false)=>request(`http://127.0.0.1:${hosts[service]}${path}`,body,read?env.RS_COMMERCE_OPS_READ_TOKEN:env.RS_COMMERCE_OPS_WRITE_TOKEN,expected);
async function wait(read,done,label) {
  const until=Date.now()+120000;
  while(Date.now()<until) {const result=await read();if(done(result))return result;await sleep(250);}
  throw new Error(`${label} 未在期限内完成`);
}
const date=ms=>new Date(ms).toISOString().replace('Z','');
async function account() {
  const username='commerce_'+randomUUID().slice(0,12),password='Test!'+randomUUID();
  await api('/api/auth/register',null,{username,password,nickname:'交易联调',bindStrategy:'selected',profileUserId:'it-profile'});
  const user=await api('/api/auth/login',null,{username,password});
  const me=await api('/api/auth/me',user);assert.equal(me.accountId,user.accountId);return user;
}
async function order(user,couponId=null) {
  const input={requestId:randomUUID(),itemId:'it-item',skuId:'it-sku',quantity:1,couponId};
  const created=await api('/api/checkout/orders',user,input);
  assert.equal((await api('/api/checkout/orders',user,input)).orderId,created.orderId);
  return wait(()=>api(`/api/checkout/orders/${created.orderId}`,user),value=>value.status==='WAITING_PAYMENT','锁库存/锁券');
}
function signature(provider,transaction,id,amount,payload) {
  const hmac=createHmac('sha256',env.RS_PAYMENT_MOCK_CALLBACK_SECRET);
  for(const field of [provider,transaction,String(id),String(amount),payload]) {const bytes=Buffer.from(field),length=Buffer.alloc(4);length.writeUInt32BE(bytes.length);hmac.update(length);hmac.update(bytes);}
  return hmac.digest('hex');
}
async function pay(user,value) {
  await api('/api/payments/prepay',user,{orderId:value.orderId,amount:value.totalAmount,provider:'mock'});
  const transaction='it-'+value.orderId,payload='{"paid":true}';
  const body={providerTransactionId:transaction,orderId:value.orderId,amount:value.totalAmount,rawPayload:payload,signature:signature('mock',transaction,value.orderId,value.totalAmount,payload)};
  await api('/callback/payments/mock',null,{...body,signature:'forged'},401);
  await api('/callback/payments/mock',null,body);await api('/callback/payments/mock',null,body);
  return wait(()=>api(`/api/checkout/orders/${value.orderId}`,user),v=>v.status==='PAID'&&v.phase==='DONE','支付确认');
}
async function refund(user,value,scenario='SUCCESS') {
  const body={requestId:randomUUID(),reason:'隔离联调整单退款',scenario};
  const first=await api(`/api/checkout/orders/${value.orderId}/refunds`,user,body);
  assert.equal((await api(`/api/checkout/orders/${value.orderId}/refunds`,user,body)).refundId,first.refundId);
  if(scenario==='DECLINED') {
    await wait(()=>api(`/api/checkout/orders/${value.orderId}/refund`,user),v=>v.status==='REVIEW_REQUIRED','拒绝退款进入核对');
    await admin('order',`/internal/checkout/refunds/${first.refundId}/retry`,{reason:'联调确认后恢复同一退款号'});
  }
  const done=await wait(()=>api(`/api/checkout/orders/${value.orderId}/refund`,user),v=>v.status==='REFUNDED','持久退款补偿');
  assert.equal(done.amount,value.totalAmount);assert.equal(done.refundId,first.refundId);
  assert.equal((await api(`/api/checkout/orders/${value.orderId}`,user)).status,'REFUNDED');return done;
}
async function cycle(user,couponId,scenario) {const value=await pay(user,await order(user,couponId));await refund(user,value,scenario);return value.orderId;}
async function pages(path,user,key,cursorName) {
  const values=[];let cursor;
  do {const page=await api(`${path}?limit=2${cursor?`&${cursorName}=${encodeURIComponent(cursor)}`:''}`,user);values.push(...page.items.map(x=>x[key]));assert.notEqual(page.nextCursor,cursor||'');cursor=page.nextCursor;}while(cursor);
  assert.equal(new Set(values).size,values.length);return values;
}
async function seckill(users,prefix) {
  const activityId=prefix+'-'+randomUUID();
  await admin('seckill','/internal/seckill/activities',{activityId,itemId:'it-item',skuId:'it-sku',totalQuantity:2,startsAt:date(Date.now()-1000),endsAt:date(Date.now()+300000)});
  await wait(()=>api(`/api/seckill/activities/${activityId}`,users[0]),v=>v.status==='ACTIVE','活动划拨');
  const results=await Promise.all(users.map(async user=>{const input={requestId:randomUUID(),itemId:'it-item',skuId:'it-sku',quantity:1};const result=await api(`/api/seckill/activities/${activityId}/submit`,user,input);assert.equal((await api(`/api/seckill/activities/${activityId}/submit`,user,input)).requestId,result.requestId);return {user,...result};}));
  const orders=[];
  for(const result of results) {
    const current=await api(`/api/seckill/activities/${activityId}`,result.user);if(!current.participation)continue;
    const outcome=await wait(()=>api(`/api/seckill/requests/${current.participation.requestId}`,result.user),v=>!!v.orderId,'异步消费建单');
    const value=await wait(()=>api(`/api/checkout/orders/${outcome.orderId}`,result.user),v=>v.status==='WAITING_PAYMENT','秒杀锁活动库存');
    await pay(result.user,value);await refund(result.user,value);
    await wait(()=>api(`/api/seckill/requests/${current.participation.requestId}`,result.user),v=>v.status==='REFUNDED','秒杀退款事件');
    const replay=await api(`/api/seckill/activities/${activityId}/submit`,result.user,{requestId:randomUUID(),itemId:'it-item',skuId:'it-sku',quantity:1});assert.equal(replay.orderId,outcome.orderId,'退款不恢复限购资格');orders.push(value.orderId);
  }
  assert.equal(orders.length,2,'限量活动不能超卖');return orders;
}
try {
  if(phase==='load') {
    assert.ok(env.RS_COMMERCE_SERVICE_TOKEN&&env.RS_PAYMENT_MOCK_CALLBACK_SECRET);
    await api('/api/checkout/orders/page',null,undefined,401);
    await admin('inventory','/internal/inventory/management/stocks',undefined,undefined,true);
    const users=await Promise.all(Array.from({length:Math.max(4,Number(env.RS_IT_CLIENTS||4))},account));
    const campaignId='it-'+randomUUID(),campaign={campaignId,title:'联调限量满减',itemId:'it-item',totalQuantity:users.length,remainingQuantity:users.length,minimumAmount:2000,discountAmount:500,startsAt:date(Date.now()-1000),endsAt:date(Date.now()+3600000),expiresAt:date(Date.now()+7200000)};
    await admin('promotion','/internal/promotions/campaigns',campaign);await admin('promotion','/internal/promotions/campaigns',campaign);
    const coupons=await Promise.all(users.map(async user=>{const body={requestId:randomUUID()};const coupon=await api(`/api/promotions/campaigns/${campaignId}/claim`,user,body);assert.equal((await api(`/api/promotions/campaigns/${campaignId}/claim`,user,body)).couponId,coupon.couponId);return coupon.couponId;}));
    const outsider=await account();await api(`/api/promotions/campaigns/${campaignId}/claim`,outsider,{requestId:randomUUID()},409);
    const privateState={users,coupons};await writeFile(checkpoint,JSON.stringify(privateState),{mode:0o600});
    await seckill(users,'initial');
    const protectedOrder=await order(users[0]);await api(`/api/checkout/orders/${protectedOrder.orderId}`,users[1],undefined,404,{'X-Account-Id':users[0].accountId});
    await api(`/api/checkout/orders/${protectedOrder.orderId}/cancel`,users[0],{});
    metrics.clear();const started=performance.now(),until=Date.now()+Number(env.RS_IT_DURATION||60)*1000,completed=[];
    await Promise.all(users.map(async (user,index)=>{let count=0;do {completed.push(await cycle(user,coupons[index],count++===0?(index===0?'DECLINED':index===1?'RESPONSE_LOST':'SUCCESS'):'SUCCESS'));}while(Date.now()<until);}));
    const durationMs=performance.now()-started,loadMetrics=structuredClone([...metrics]);
    for(let i=0;i<users.length;i++) {const wallet=await api('/api/promotions/coupons/page',users[i]);assert.equal(wallet.items.find(c=>c.couponId===coupons[i]).status,'AVAILABLE');const found=await pages('/api/checkout/orders/page',users[i],'orderId','beforeId');assert.ok(found.length>1);await pages('/api/promotions/coupons/page',users[i],'couponId','afterId');}
    const receipt={requestId:randomUUID(),skuId:'it-sku',itemId:'it-item',type:'RECEIPT',quantity:2,expectedVersion:null,reason:'验证入库账本'};
    await admin('inventory','/internal/inventory/management/adjustments',receipt);await admin('inventory','/internal/inventory/management/adjustments',receipt);
    const stock=(await admin('inventory','/internal/inventory/management/stocks',undefined,undefined,true)).items[0];
    assert.equal(stock.available_stock,202);
    await admin('inventory','/internal/inventory/management/adjustments',{requestId:randomUUID(),skuId:'it-sku',itemId:'it-item',type:'STOCKTAKE',quantity:200,expectedVersion:stock.version,reason:'验证盘点账本'});
    const reconciled=await admin('inventory','/internal/inventory/management/reconciliations',{});assert.ok(reconciled.every(row=>row.healthy));
    assert.equal((await admin('inventory','/internal/inventory/management/reconciliations',undefined,undefined,true)).length,0);
    await wait(()=>admin('order','/internal/checkout/events',undefined,undefined,true),v=>v.length===0,'交易事实完整交付');
    const report={timestamp:new Date().toISOString(),gatewayAuthentication:true,middleware:'MYSQL_REDIS_THREE_BROKER_KAFKA',durationMs,clients:users.length,completedOrders:completed.length,completedOrderTps:completed.length/(durationMs/1000),requestQps:loadMetrics.reduce((sum,[,m])=>sum+m.latencies.length,0)/(durationMs/1000),gatewayRateLimitPerMinute:100000,mockMoneyMoved:false,scenarios:['DUPLICATE_PAYMENT_CALLBACK','FORGED_CALLBACK','OWNER_HEADER_SPOOF','LIMITED_COUPON','SECKILL_FULL_REFUND','REFUND_DECLINED_RETRY','REFUND_RESPONSE_LOST','SEEK_PAGINATION'],routes:loadMetrics.map(([route,m])=>{const sorted=m.latencies.toSorted((a,b)=>a-b);return {route,requests:sorted.length,p95Ms:sorted[Math.ceil(sorted.length*.95)-1],p99Ms:sorted[Math.ceil(sorted.length*.99)-1],statuses:m.statuses};}),note:'低内存闭环持续联调，不代表峰值容量；资金渠道为 Mock。请求指标包含轮询和重复/拒绝回调，统计窗口为持续闭环阶段。'};
    await writeFile(env.RS_IT_REPORT,JSON.stringify(report,null,2));console.log(JSON.stringify({completedOrders:report.completedOrders,durationMs,completedOrderTps:report.completedOrderTps}));
  } else {
    const {users,coupons}=JSON.parse(await readFile(checkpoint,'utf8'));
    for(const user of users) assert.equal((await api('/api/auth/me',user)).accountId,user.accountId);
    if(phase==='broker-down') await seckill(users,'broker-down');
    else await cycle(users[0],coupons[0]);
    await wait(()=>admin('order','/internal/checkout/events',undefined,undefined,true),v=>v.length===0,'切换后交易事实交付');
    console.log(JSON.stringify({phase,passed:true}));
  }
} finally {clearInterval(keepAlive);}
