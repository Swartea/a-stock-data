async(page)=>{
 const counts=new Map();let compares=0;
 const seen=request=>{const u=new URL(request.url());if(u.pathname==='/api/daily-k'){const k=u.search;counts.set(k,(counts.get(k)||0)+1);}if(u.pathname==='/api/compare')compares++;};
 page.on('request',seen);
 await page.unroute('**/api/daily-k?*');
 await page.route('**/api/daily-k?*',async route=>{const id=new URL(route.request().url()).searchParams.get('index_id');await route.fulfill({contentType:'application/json',body:JSON.stringify({index_id:id,name:id==='cn.index.csi300'?'沪深300':id,status:'ok',source:'offline.cache.fixture（验收数据）',bars:[{date:'2026-10-15',open:100,high:102,low:99,close:101},{date:'2026-10-16',open:101,high:105,low:100,close:104}]})});});
 await page.reload();
 await page.waitForFunction(()=>[...document.querySelectorAll('#strip [data-field="close"]')].every(e=>!e.textContent.includes('读取')));
 if(counts.size!==9||[...counts.values()].some(n=>n!==1))throw new Error('overview duplicate requests '+JSON.stringify([...counts]));
 await page.getByRole('button',{name:'市场比较',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#compare-message').textContent.includes('共同基准日'));
 if([...counts.values()].reduce((a,b)=>a+b,0)!==9)throw new Error('compare did not reuse daily cache');
 await page.getByRole('button',{name:'市场总览',exact:true}).click();
 await page.getByRole('button',{name:'进入 沪深300 研究',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#head').textContent.includes('沪深300'));
 if([...counts.values()].reduce((a,b)=>a+b,0)!==9)throw new Error('detail did not reuse cache');
 page.off('request',seen);
 await page.unroute('**/api/daily-k?*');
 await page.route('**/api/daily-k?*',async route=>{
 const id=new URL(route.request().url()).searchParams.get('index_id');
 await new Promise(r=>setTimeout(r,id==='cn.index.sh_comp'?400:10));
 await route.fulfill({contentType:'application/json',body:JSON.stringify({index_id:id,name:id,status:'ok',availability:'available',freshness:'unknown',trading_day_status:'unknown',source:'offline.race.fixture',data_date:'2026-10-16',bars:[{date:'2026-10-15',open:100,high:102,low:99,close:101},{date:'2026-10-16',open:101,high:103,low:100,close:102}]})});
 });
 await page.reload();
 await page.getByRole('button',{name:'进入 沪深300 研究',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#head').textContent.includes('cn.index.csi300'));
 await page.waitForTimeout(600);
 if(!(await page.locator('#head').textContent()).includes('cn.index.csi300'))throw new Error('stale selection overwrote newer data');
 await page.unroute('**/api/daily-k?*');
 return {status:'PASS',mode:'offline.cache.fixture',overviewDailyRequests:counts.size,compareExtraDailyRequests:0,detailExtraDailyRequests:0,comparisonCalculationRequests:compares,staleSelection:'PASS'};
}
