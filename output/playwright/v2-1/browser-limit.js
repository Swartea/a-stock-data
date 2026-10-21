async(page)=>{
 await page.route('**/api/daily-k?*',async route=>{const id=new URL(route.request().url()).searchParams.get('index_id');await route.fulfill({contentType:'application/json',body:JSON.stringify({index_id:id,name:id,status:'ok',source:'offline.limit.fixture（验收数据）',bars:[{date:'2026-10-15',close:100},{date:'2026-10-16',close:104}]})});});
 await page.reload();await page.getByRole('button',{name:'市场比较',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.compare-series').length===3);
 await page.getByRole('checkbox',{name:'上证指数 · A股',exact:true}).check();
 await page.waitForFunction(()=>document.querySelectorAll('.compare-series').length===4);
 if(await page.locator('#compare-choices input:disabled').count()!==5)throw new Error('four-index limit not enforced');
 await page.getByRole('button',{name:'移除上证指数',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.compare-series').length===3);
 if(await page.locator('#compare-choices input:disabled').count()!==0)throw new Error('selection not reenabled');
 await page.unroute('**/api/daily-k?*');
 return {status:'PASS',fourSeries:true,fifthSelectionDisabled:true,removeReenables:true};
}
