// 本地运维工作台：只绑定回环，凭证只留在浏览器内存，后端负责角色校验和审计身份。
import { createServer } from 'node:http';
const port = Number(process.env.RS_COMMERCE_CONSOLE_PORT || 18096);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('工作台端口不合法');
const hosts = { seckill: process.env.RS_SECKILL_INTERNAL_URL || 'http://127.0.0.1:18094',
  checkout: process.env.RS_ORDER_INTERNAL_URL || 'http://127.0.0.1:18091', payment: process.env.RS_PAYMENT_INTERNAL_URL || 'http://127.0.0.1:18093' };
const prefixes = { seckill: '/internal/seckill/tasks', checkout: '/internal/checkout/tasks', payment: '/internal/payment/notifications', allocation: '/internal/seckill/allocations' };
const html = String.raw`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>交易任务工作台</title><style>
body{background:#0f172a;color:#e2e8f0;font:15px system-ui;max-width:1200px;margin:36px auto;padding:0 24px}h1{font-size:28px}
input,button{font:inherit;padding:10px;border-radius:6px;border:1px solid #475569;background:#1e293b;color:inherit}input{width:270px}
button{cursor:pointer;background:#312e81}label{display:inline-flex;flex-direction:column;gap:8px;margin:0 14px 16px 0}p{color:#94a3b8}
table{width:100%;border-collapse:collapse;margin-bottom:26px}td,th{text-align:left;padding:12px;border-bottom:1px solid #334155;word-break:break-word}
.error{color:#fca5a5}.summary{color:#a5b4fc}#reason{width:420px}
</style><h1>交易任务工作台</h1><p>查看秒杀、订单、支付和活动库存异常。恢复操作沿用原业务请求，并记录认证操作人的身份与原因。</p>
<label>只读运维凭证<input id="read" type="password" autocomplete="off"></label><label>写入运维凭证<input id="write" type="password" autocomplete="off"></label>
<label>恢复原因<input id="reason" maxlength="255" placeholder="先核对根因，再填写恢复原因"></label><button id="refresh">刷新任务</button>
<p id="notice" role="status">凭证由部署管理员提供，本页面不保存凭证。</p><main id="tasks"></main>
<script>
const names={seckill:'秒杀请求',checkout:'订单工作流',payment:'支付通知',allocation:'活动库存划拨'};
const root=document.getElementById('tasks'),notice=document.getElementById('notice');
async function request(kind,suffix,write){
 const token=document.getElementById(write?'write':'read').value;
 const response=await fetch('/proxy/'+kind+suffix,{method:write?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
 body:write?JSON.stringify({reason:document.getElementById('reason').value}):undefined});
 if(!response.ok)throw new Error('HTTP '+response.status+'：'+(response.status===401?'运维凭证无效':response.status===403?'凭证没有写入权限':'接口暂不可用或任务状态不允许恢复'));
 const text=await response.text();return text?JSON.parse(text):null;
}
async function refresh(){
 root.replaceChildren();notice.textContent='正在查询…';notice.className='';
 const outcomes=await Promise.allSettled(Object.keys(names).map(async kind=>{
  const section=document.createElement('section'),heading=document.createElement('h2');heading.textContent=names[kind];section.append(heading);root.append(section);
  const [tasks,summary]=await Promise.all([request(kind,'',false),kind==='allocation'?Promise.resolve(null):request(kind,'/summary',false)]);
  const text=document.createElement('p');text.className='summary';text.textContent=summary?'未完成 '+summary.pending+' / 待核对 '+summary.reviewRequired:tasks.length+' 个未完成划拨/归还任务';section.append(text);
  const table=document.createElement('table');const header=document.createElement('tr');['任务标识','状态 / 阶段','错误原因','操作'].forEach(name=>{const th=document.createElement('th');th.textContent=name;header.append(th);});table.append(header);
  for(const task of tasks){
   const tr=document.createElement('tr');const id=task.eventId||task.orderId||task.activity_id;
   [id,(task.status||'')+' '+(task.phase||''),task.lastError||task.last_error||''].forEach(value=>{const td=document.createElement('td');td.textContent=String(value);tr.append(td);});
   const td=document.createElement('td');if(task.status==='REVIEW_REQUIRED'||task.status==='REVIEW'||(task.phase||'').startsWith('REVIEW_')){
    const button=document.createElement('button');button.textContent='恢复原任务';button.onclick=async()=>{
     if(!document.getElementById('reason').value.trim()){notice.textContent='请填写核对后的恢复原因';return;}button.disabled=true;
     try{await request(kind,'/'+encodeURIComponent(id)+'/retry',true);await refresh();notice.textContent='已恢复原任务，后续进度由后台处理';}
     catch(error){notice.textContent=error.message;notice.className='error';button.disabled=false;}
    };td.append(button);
   }else td.textContent='等待后台处理';tr.append(td);table.append(tr);
  }section.append(table);if(!tasks.length){const empty=document.createElement('p');empty.textContent='没有待核对或超龄任务';section.append(empty);}
 }));
 const failures=outcomes.filter(result=>result.status==='rejected');notice.textContent=failures.length?failures.map(result=>result.reason.message).join('；'):'查询完成';notice.className=failures.length?'error':'';
}
document.getElementById('refresh').onclick=refresh;
</script></html>`;
const server = createServer(async (request, response) => {
  response.setHeader('Cache-Control', 'no-store'); response.setHeader('X-Content-Type-Options', 'nosniff');
  if (request.url === '/' && request.method === 'GET') {
    response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'");
    response.writeHead(200, { 'Content-Type': 'text/html;charset=utf-8' }); response.end(html); return;
  }
  const match = /^\/proxy\/(seckill|checkout|payment|allocation)(\/(?:summary|[A-Za-z0-9_-]{1,64}\/retry))?(\?minimumAgeSeconds=\d+)?$/.exec(request.url);
  if (!match || !['GET', 'POST'].includes(request.method)) { response.writeHead(404); response.end(); return; }
  const [, kind, suffix = '', query = ''] = match;
  if ((request.method === 'POST') !== suffix.endsWith('/retry') || (kind === 'allocation' && suffix === '/summary')) { response.writeHead(405); response.end(); return; }
  if (request.method === 'POST' && request.headers.origin !== `http://127.0.0.1:${port}` && request.headers.origin !== `http://localhost:${port}`) {
    response.writeHead(403); response.end(); return;
  }
  try {
    let body;
    if (request.method === 'POST') {
      let raw = ''; for await (const chunk of request) { raw += chunk; if (raw.length > 4096) throw new Error('请求过大'); }
      const input = JSON.parse(raw);
      if (typeof input.reason !== 'string' || !input.reason.trim() || input.reason.length > 255) { response.writeHead(400); response.end(); return; }
      body = JSON.stringify({ reason: input.reason });
    }
    const upstream = await fetch((hosts[kind === 'allocation' ? 'seckill' : kind]).replace(/\/$/, '') + prefixes[kind] + suffix + query,
      { method: request.method, headers: { Authorization: request.headers.authorization || '', 'Content-Type': 'application/json' }, body, signal: AbortSignal.timeout(10000) });
    response.writeHead(upstream.status, { 'Content-Type': 'application/json;charset=utf-8' }); response.end(await upstream.text());
  } catch { response.writeHead(502); response.end('{"message":"交易运维接口暂不可用"}'); }
});
server.listen(port, '127.0.0.1', () => console.log(`交易任务工作台：http://127.0.0.1:${port}`));
