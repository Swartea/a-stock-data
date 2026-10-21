async (page) => {
 const check=(ok,message)=>{if(!ok)throw new Error(message);};
 const key='swartea.market-research.watchlist.v1';
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 let scenario='partial';
 await page.route('**/api/daily-k?*',async route=>{
   const url=new URL(route.request().url()),id=url.searchParams.get('index_id');
   let bars=[{date:'2026-10-14',open:100,high:102,low:99,close:100},
     {date:'2026-10-15',open:100,high:105,low:99,close:104},
     {date:'2026-10-16',open:104,high:106,low:102,close:105}];
   let status='ok';
   if(scenario==='partial' && id==='us.index.nasdaq.composite'){bars=[];status='unavailable';}
   if(scenario==='disjoint' && id==='us.index.nasdaq.composite')bars=bars.map(b=>({...b,date:b.date.replace('-10-','-09-')}));
   if(scenario==='empty'){bars=[];status='empty';}
   if(scenario==='single')bars=bars.slice(0,1);
   if(scenario==='missing' && id==='hk.index.hang_seng.hstech')bars=bars.filter((_,i)=>i!==1);
   if(scenario==='network'){await route.abort('failed');return;}
   await route.fulfill({contentType:'application/json',body:JSON.stringify({index_id:id,name:id,market:id.slice(0,2),bars,status,
      bar_count:bars.length,availability:status==='ok'?'available':'unavailable',freshness:'unknown',trading_day_status:'unknown',
      source:'offline.browser.fixture（验收数据）',data_date:bars.length?bars.at(-1).date:null,
      failure_reason:status==='ok'?null:'BROWSER_TEST_PROVIDER_FAILURE'})});
 });
 async function compareScenario(next){
   scenario=next;await page.reload();await page.getByRole('button',{name:'市场比较',exact:true}).click();
   await page.waitForFunction(()=>!document.querySelector('#compare-message').textContent.includes('加载'));
 }
 await compareScenario('partial');
 check(await page.locator('.compare-series').count()===2,'partial failure keeps two usable');
 check((await page.locator('#compare-excluded').textContent()).includes('数据不可用'),'partial reason');
 await compareScenario('disjoint');
 check(await page.locator('.compare-series').count()===0,'disjoint must not silently drop selected series');
 check((await page.locator('#compare-message').textContent()).includes('没有所有'),'no common baseline reason');
 await compareScenario('empty');check(await page.locator('.compare-series').count()===0,'empty safe');
 await compareScenario('single');check((await page.locator('#compare-excluded').textContent()).includes('不足两日'),'single safe');
 await compareScenario('missing');check(await page.locator('.compare-series').count()===3,'gaps keep valid series');
 await page.locator('#compare-start').fill('2026-10-21');await page.locator('#compare-end').fill('2026-09-01');
 await page.getByRole('button',{name:'比较走势',exact:true}).click();
 check((await page.locator('#compare-message').textContent()).includes('起始日期不能晚'),'invalid range');
 await compareScenario('network');
 check(await page.locator('.compare-series').count()===0,'network safe');
 await page.getByRole('button',{name:'指数研究',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#state').classList.contains('error'));
 check((await page.locator('#reason').textContent()).includes('不可用'),'network detail error');
 scenario='missing';
 for(const stored of ['broken','["retired.index","sse.composite","cn.index.sh_comp",42]']){
   await page.evaluate(({key,stored})=>localStorage.setItem(key,stored),{key,stored});await page.reload();
   await page.getByRole('button',{name:'自选关注',exact:true}).click();
   const count=await page.locator('#watch-list .watch-card').count();
   check(count===(stored==='broken'?0:1),'corrupt and alias storage');
 }
 await page.unroute('**/api/daily-k?*');
 const denied=await page.context().newPage();
 await denied.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new Error('storage denied for test');}}));
 await denied.goto('http://127.0.0.1:8766/');
 await denied.getByRole('button',{name:'加入自选',exact:true}).first().click();
 await denied.getByRole('button',{name:'自选关注',exact:true}).click();
 check(await denied.locator('#watch-list .watch-card').count()===1,'denied storage memory add');
 check((await denied.locator('#watch-notice').textContent()).includes('内存'),'denied storage disclosure');
 await denied.close();
 const mobileContext=await page.context().browser().newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const mobile=await mobileContext.newPage();
 await mobile.route('**/api/daily-k?*',async route=>{const id=new URL(route.request().url()).searchParams.get('index_id');await route.fulfill({contentType:'application/json',body:JSON.stringify({index_id:id,name:id,status:'ok',source:'offline.browser.fixture（验收数据）',freshness:'unknown',bars:[{date:'2026-10-15',open:100,high:102,low:99,close:101},{date:'2026-10-16',open:101,high:105,low:100,close:104}]})});});
 await mobile.goto('http://127.0.0.1:8766/');
 await mobile.getByRole('button',{name:'市场比较',exact:true}).click();
 await mobile.waitForFunction(()=>document.querySelector('#compare-message').textContent.includes('共同基准日'));
 await mobile.locator('#compare-chart').scrollIntoViewIfNeeded();
 const box=await mobile.locator('#compare-chart').boundingBox();await mobile.touchscreen.tap(box.x+box.width/2,box.y+box.height/2);
 check((await mobile.locator('#compare-probe').textContent()).includes('累计'),'actual mobile touch');
 await mobile.screenshot({path:'output/playwright/v2-1/mobile-touch-fixture-390.png',fullPage:true});
 await mobileContext.close();
 check(errors.length===0,'page errors '+errors.join(','));
 return {status:'PASS',scenarios:['partial','no_common_base','empty','single','gaps','touch','invalid_dates','network','corrupt_storage','aliases','denied_storage'],errors};
}
