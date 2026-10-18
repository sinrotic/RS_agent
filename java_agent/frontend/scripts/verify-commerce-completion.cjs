// 浏览器夹具验收：历史分页、退款未知响应重试、账号隔离、管理页面库存幂等操作。
const { chromium }=require('playwright');
const assert=require('node:assert/strict');
const {createServer}=require('node:http');
const {spawn}=require('node:child_process');
const fs=require('node:fs/promises');
const path=require('node:path');
async function main(){
 const browser=await chromium.launch({headless:true,...(process.env.RS_CHROMIUM_PATH?{executablePath:process.env.RS_CHROMIUM_PATH}:{})});
 const output=path.resolve(__dirname,'../../../outputs/commerce-completion-browser');await fs.mkdir(output,{recursive:true});
 let consoleProcess,upstream;
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  let account='account-a',refundRequests=[],stockRequests=[];
  const order={orderId:1001,status:'PAID',phase:'DONE',itemId:'item',skuId:'sku',itemTitle:'退款验证商品',quantity:1,originalAmount:3000,discountAmount:500,totalAmount:2500,couponId:'coupon',expiresAt:'2026-12-30T00:00:00',failureReason:null};
  let refunded=false;
  await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
   const request=route.request(),url=new URL(request.url()),endpoint=url.pathname;let body={},status=200;
   if(endpoint==='/api/auth/me')body={accountId:account,username:'交易测试账号',profileUserId:'profile'};
   else if(endpoint==='/api/checkout/capabilities')body={mockPaymentEnabled:true};
   else if(endpoint==='/api/checkout/orders/page')body=account==='account-b'?{items:[],nextCursor:null}:url.searchParams.has('beforeId')?{items:[{...order,orderId:1000,itemTitle:'较早订单',status:'CANCELED'}],nextCursor:null}:{items:[{...order,status:refunded?'REFUNDED':'PAID'}],nextCursor:'1001'};
   else if(endpoint==='/api/promotions/coupons/page')body={items:account==='account-b'?[]:[{couponId:'coupon',campaignId:'campaign',status:refunded?'AVAILABLE':'USED',title:'测试满减券',itemId:'item',minimumAmount:2000,discountAmount:500,expiresAt:'2026-12-30T00:00:00'}],nextCursor:null};
   else if(endpoint==='/api/checkout/orders/1001/refunds'){
    const input=request.postDataJSON();assert.equal(input.amount,undefined);assert.equal(input.accountId,undefined);refundRequests.push(input);
    if(refundRequests.length===1){status=504;body={message:'响应未知'};}else{assert.deepEqual(input,refundRequests[0]);refunded=true;body={refundId:'refund',orderId:1001,amount:2500,status:'REFUNDED',phase:'DONE',reason:input.reason};}
   }else if(endpoint==='/api/checkout/orders/1001/refund'){
    if(!refunded){status=404;body={message:'不存在'};}else body={refundId:'refund',orderId:1001,amount:2500,status:'REFUNDED',phase:'DONE',reason:'未发货，申请整单退款'};
   }else if(endpoint==='/api/checkout/orders/1001')body={...order,status:refunded?'REFUNDED':'PAID'};
   else throw new Error('未配置夹具 '+endpoint);
   await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto((process.env.RS_E2E_BASE_URL||'http://127.0.0.1:5174')+'/commerce');
  await page.getByRole('heading',{name:'我的订单与券包'}).waitFor();
  await page.getByRole('button',{name:'加载更早订单'}).click();await page.getByText('较早订单 · 订单 1000',{exact:false}).waitFor();
  await page.getByRole('button',{name:'申请整单退款'}).click();await page.getByRole('button',{name:'重试原退款请求'}).waitFor();
  await page.getByRole('button',{name:'重试原退款请求'}).click();await page.getByText('退款验证商品 · 订单 1001 · 已退款',{exact:true}).waitFor();
  await page.getByText('测试满减券 · 可使用',{exact:true}).waitFor();assert.equal(refundRequests.length,2);
  await page.screenshot({path:path.join(output,'history-refund.png'),fullPage:true});
  account='account-b';await page.evaluate(async()=>{const shared=await import('/src/api/shared.ts');shared.saveAccountId('account-b');});
  await page.getByText('暂无订单。',{exact:true}).waitFor();assert.equal(await page.getByText('退款验证商品',{exact:false}).count(),0);
  assert.equal(await page.evaluate(()=>Object.keys(sessionStorage).filter(key=>key.startsWith('refund-pending:')).length),0);
  // 使用真正的本地工作台 HTTP 代理；仅库存服务由夹具替代。
  upstream=createServer(async(req,res)=>{
   assert.ok(['Bearer '+ 'r'.repeat(32),'Bearer '+ 'w'.repeat(32)].includes(req.headers.authorization));
   let raw='';for await(const chunk of req)raw+=chunk;
   if(req.method==='POST'){
    const input=JSON.parse(raw);stockRequests.push(input);assert.equal(input.operatorId,undefined);
    if(stockRequests.length===1){res.writeHead(504,{'Content-Type':'application/json'});res.end('{}');return;}
    assert.deepEqual(input,stockRequests[0]);
   }
   res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(req.method==='POST'?{}:{items:[{sku_id:'sku',item_id:'item',available_stock:12,locked_stock:2,sold_stock:0,version:3}],nextCursor:null}));
  });
  await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve));
  const reservation=createServer();await new Promise(resolve=>reservation.listen(0,'127.0.0.1',resolve));const port=reservation.address().port;await new Promise(resolve=>reservation.close(resolve));
  consoleProcess=spawn(process.execPath,[path.resolve(__dirname,'../../deploy/remote/app/commerce_ops_console.mjs')],{env:{...process.env,RS_COMMERCE_CONSOLE_PORT:String(port),RS_INVENTORY_INTERNAL_URL:`http://127.0.0.1:${upstream.address().port}`}});
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('工作台启动超时')),5000);consoleProcess.once('error',reject);consoleProcess.stdout.once('data',()=>{clearTimeout(timer);resolve();});});
  const management=await browser.newPage();management.on('pageerror',e=>errors.push(e.message));await management.goto(`http://127.0.0.1:${port}/manage`);
  await management.locator('#reader').fill('r'.repeat(32));await management.locator('#writer').fill('w'.repeat(32));
  await management.getByRole('button',{name:'查询',exact:true}).click();await management.getByRole('button',{name:'载入盘点'}).click();
  const form=management.locator('#stock-form');assert.equal(await form.locator('[name=version]').inputValue(),'3');assert.equal(await form.locator('[name=quantity]').inputValue(),'14');
  await form.locator('[name=reason]').fill('浏览器盘点验收');await form.getByRole('button',{name:'提交盘点'}).click();
  await form.getByRole('button',{name:'重试原库存变更'}).waitFor();await form.getByRole('button',{name:'重试原库存变更'}).click();
  await management.getByText('操作已确认，请查询最新记录',{exact:true}).waitFor();assert.equal(stockRequests.length,2);assert.equal(stockRequests[0].expectedVersion,3);
  assert.equal(await management.evaluate(()=>Object.values(sessionStorage).some(value=>value.includes('rrrrrrrr')||value.includes('wwwwwwww'))),false);
  await management.screenshot({path:path.join(output,'management-stocktake.png'),fullPage:true});
  assert.deepEqual(errors,[]);await fs.writeFile(path.join(output,'report.json'),JSON.stringify({passed:true,fixture:true,checks:['历史分页','退款未知响应原键重试','退券刷新','账号切换隔离','库存盘点版本','工作台未知响应原键重试','运维凭证不入存储'],browserErrors:errors},null,2));
  console.log('交易补全浏览器夹具验证通过');
 }finally{await browser.close();if(consoleProcess)consoleProcess.kill();if(upstream)await new Promise(resolve=>upstream.close(resolve));}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
