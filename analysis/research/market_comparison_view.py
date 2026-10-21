"""Canvas comparison UI; prices come exclusively from shared research payloads."""

COMPARISON_STYLE = """
.compare-mount{border:0;padding:0;min-width:0}
.compare-controls{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:16px 0}
.compare-controls label{display:grid;gap:4px;font-size:12px;color:var(--muted);min-width:0}
.compare-controls input{max-width:100%;min-width:0}
.compare-choices{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.compare-choice{display:flex;gap:6px;align-items:center;padding:6px 10px;border:1px solid var(--line);border-radius:6px}
.compare-choice input{min-height:20px;margin:0}
.compare-chart{width:100%;height:340px;touch-action:pan-y}
.compare-legend{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}
.compare-series{flex:1 1 220px;min-width:0;border:1px solid var(--line);padding:10px;border-radius:8px;overflow-wrap:anywhere}
.compare-series button{float:right;min-height:28px}
.compare-series strong{display:block;margin-bottom:6px}
.compare-series small{display:block;color:var(--muted)}
.compare-probe{white-space:pre-line;min-height:24px;font-size:12px;margin:8px 0}
@media(max-width:768px){.grid3{grid-template-columns:minmax(0,1fr)}.compare-chart{height:260px}.brand{flex-wrap:wrap}.legend{flex-wrap:wrap}}
"""

COMPARISON_JS = r"""
document.addEventListener('DOMContentLoaded', () => {
  const work = window.__WORKBENCH__;
  const root = document.getElementById('compare-root');
  const oldStatus = document.getElementById('compare-status');
  if (!root || !work) return;
  oldStatus.hidden = true;
  const colors = ['#4c9ffe', '#f2b04c', '#d990f4', '#5fd0d0'];
  const chosen = new Set(['cn.index.csi300', 'hk.index.hang_seng.hstech', 'us.index.nasdaq.composite']
    .filter(id => work.options.some(o => o.index_id === id)));
  let revision = 0, result = null, hover = null;
  const q = selector => root.querySelector(selector);
  const safe = v => String(v == null ? '—' : v).replace(/[&<>"']/g,
    ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const markets = {cn:'A股', hk:'港股', us:'美股'};
  const number = n => typeof n === 'number' && Number.isFinite(n);
  const f = n => number(n) ? n.toFixed(2) : '缺失';
  root.innerHTML = '<div class="compare-controls">'
    + '<label>起始日期<input type="date" id="compare-start"></label>'
    + '<label>结束日期<input type="date" id="compare-end"></label>'
    + '<button id="compare-go" type="button">比较走势</button>'
    + '<span class="muted">选择 2～4 个指数</span></div>'
    + '<div class="compare-choices" id="compare-choices"></div>'
    + '<p id="compare-message" role="status" aria-live="polite"></p>'
    + '<div class="compare-legend" id="compare-legend"></div>'
    + '<div class="chartwrap"><canvas class="compare-chart" id="compare-chart" aria-label="跨市场累计价格收益率走势"></canvas></div>'
    + '<div class="compare-probe" id="compare-probe">移动指针或触摸图表查看各指数日线。</div>'
    + '<div class="reason" id="compare-excluded"></div>'
    + '<p class="muted">共同有效基准日归一化为 100；曲线显示相对基准的累计价格收益率。'
    + '各市场按本地交易日期对齐，不表示同步实时行情；不含分红、不作汇率调整，缺失日期不插值。'
    + '交易日历状态未知。</p>';
  q('#compare-start').value = document.getElementById('start').value;
  q('#compare-end').value = document.getElementById('end').value;
  function choices() {
    q('#compare-choices').innerHTML = work.options.map(o => '<label class="compare-choice">'
      + '<input type="checkbox" value="' + safe(o.index_id) + '" '
      + (chosen.has(o.index_id) ? 'checked ' : '')
      + (!chosen.has(o.index_id) && chosen.size >= 4 ? 'disabled ' : '')
      + '><span>' + safe(o.name) + ' · ' + safe(markets[o.market]) + '</span></label>').join('');
  }
  function reset(message) {
    result = null; hover = null;
    q('#compare-message').textContent = message;
    q('#compare-legend').innerHTML = '';
    q('#compare-excluded').textContent = '';
    q('#compare-probe').textContent = '移动指针或触摸图表查看各指数日线。';
    draw();
  }
  async function compare() {
    const token = ++revision;
    const start = q('#compare-start').value, end = q('#compare-end').value;
    reset('加载历史日线…');
    if (chosen.size < 2 || chosen.size > 4) { reset('请选择 2～4 个指数。'); return; }
    if (!start || !end || start > end) { reset('请选择有效日期范围，起始日期不能晚于结束日期。'); return; }
    const ids = [...chosen];
    const payloads = await Promise.all(ids.map(id => work.requestDailyK(id, start, end)
      .catch(() => ({index_id:id, status:'error', bars:[], failure_reason:'研究服务请求失败'}))));
    if (token !== revision) return;
    try {
      const response = await fetch('/api/compare', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({payloads:payloads, start_date:start, end_date:end})});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (token !== revision) return;
      const reasons = {index_unavailable:'数据不可用', no_bars:'无日线', no_valid_rows:'无有效收盘',
        insufficient_dates:'有效历史不足两日', no_common_base:'没有共同有效基准日', duplicate_index:'重复身份'};
      q('#compare-excluded').textContent = (data.excluded || []).map(e =>
        (e.name || e.index_id || '指数') + '：' + (reasons[e.reason] || '数据无效') + ' · ' + (e.detail || '')).join('\n');
      if (data.status !== 'ok') {
        q('#compare-message').textContent = data.error && data.error.code === 'no_common_base'
          ? '区间内没有所有可用指数共同的有效基准日，请调整日期或移除指数。'
          : '无法比较：至少需要两个各含两日有效收盘的指数。';
        draw(); return;
      }
      result = data;
      q('#compare-message').textContent = '共同基准日 ' + data.base_date + ' · 基准值 100 · 累计价格收益率（%）';
      q('#compare-legend').innerHTML = data.series.map((s,i) => {
        const payload = payloads.find(p => p.index_id === s.index_id) || {};
        const last = s.cumulative_return_pct.filter(number).slice(-1)[0];
        return '<div class="compare-series" style="border-top:3px solid ' + colors[i] + '">'
          + '<button type="button" data-remove="' + safe(s.index_id) + '" aria-label="移除' + safe(s.name) + '">移除</button>'
          + '<strong>' + safe(s.name) + ' · ' + safe(markets[s.market]) + '</strong>'
          + '<span class="' + (last >= 0 ? 'up' : 'down') + '">' + (last >= 0 ? '+' : '') + f(last) + '%</span>'
          + '<small>有效数据截至 ' + safe(s.last_date) + ' · 基准收盘 ' + f(s.base_close) + '</small>'
          + '<small>来源 ' + safe(s.source) + ' · ' + safe(({fresh:'新鲜',stale:'已过期',unknown:'未知'})[payload.freshness] || '新鲜度未知') + '</small>'
          + '<small>缺失 ' + s.close.filter(v => v === null).length + ' 个日期'
          + (s.issues.length ? ' · ' + safe(s.issues.map(v => v.code + ':' + v.count).join('，')) : '')
          + '</small></div>';
      }).join('');
      draw();
    } catch (error) {
      if (token === revision) reset('比较服务请求失败，请稍后重新比较。');
    }
  }
  function geometry() {
    const canvas = q('#compare-chart'), box = canvas.getBoundingClientRect();
    const width = Math.max(100,box.width), height = Math.max(100,box.height);
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d'); ctx.setTransform(ratio,0,0,ratio,0,0);
    return {canvas, ctx, width, height};
  }
  function draw() {
    const {ctx,width,height} = geometry();
    ctx.clearRect(0,0,width,height);
    if (!result || !result.dates.length) {
      ctx.fillStyle='#8b97a8'; ctx.font='13px system-ui'; ctx.fillText('选择指数和日期后查看累计收益率',18,40); return;
    }
    const left=56, right=18, top=22, bottom=36;
    const values=result.series.flatMap(s => s.cumulative_return_pct).filter(number);
    let low=Math.min(0,...values), high=Math.max(0,...values);
    const pad=Math.max(1,(high-low)*0.12); low-=pad; high+=pad;
    const x=i => left + i / Math.max(1,result.dates.length-1)*(width-left-right);
    const y=v => top + (high-v)/(high-low)*(height-top-bottom);
    ctx.font='11px system-ui';
    for(let i=0;i<=4;i++) {
      const v=low+(high-low)*i/4;
      ctx.strokeStyle='#242c3a';ctx.beginPath();ctx.moveTo(left,y(v));ctx.lineTo(width-right,y(v));ctx.stroke();
      ctx.fillStyle='#8b97a8';ctx.fillText(v.toFixed(1)+'%',2,y(v)+4);
    }
    [0,Math.floor((result.dates.length-1)/2),result.dates.length-1].forEach((i,n) => {
      if(width<450 && n===1) return;
      ctx.fillStyle='#8b97a8';ctx.textAlign=n===2?'right':n===0?'left':'center';
      ctx.fillText(result.dates[i], n===2?width-right:x(i),height-10);
    });ctx.textAlign='left';
    result.series.forEach((s,index) => {
      ctx.strokeStyle=colors[index];ctx.lineWidth=2;ctx.beginPath();let connected=false;
      s.cumulative_return_pct.forEach((v,i) => {
        if(!number(v)){connected=false;return;}
        if(connected)ctx.lineTo(x(i),y(v));else ctx.moveTo(x(i),y(v));connected=true;
      });ctx.stroke();
      // Points keep isolated valid sessions visible without connecting across gaps.
      s.cumulative_return_pct.forEach((v,i)=>{if(number(v)){ctx.beginPath();ctx.arc(x(i),y(v),2,0,Math.PI*2);ctx.fillStyle=colors[index];ctx.fill();}});
    });
    if(hover!==null) {
      ctx.strokeStyle='#8b97a8';ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x(hover),top);ctx.lineTo(x(hover),height-bottom);ctx.stroke();ctx.setLineDash([]);
    }
  }
  function pick(event) {
    if(!result)return;
    const box=q('#compare-chart').getBoundingClientRect();
    const clientX=event.touches && event.touches.length?event.touches[0].clientX:event.clientX;
    hover=Math.max(0,Math.min(result.dates.length-1,Math.round((clientX-box.left-56)/Math.max(1,box.width-74)*(result.dates.length-1))));
    q('#compare-probe').textContent=result.dates[hover]+' · 各市场本地交易日期\n'+result.series.map(s =>
      s.name+' · 收盘 '+f(s.close[hover])+' · 基准 '+f(s.normalized100[hover])+' · 累计 '+f(s.cumulative_return_pct[hover])+(number(s.cumulative_return_pct[hover])?'%':'（当日无有效数据）')).join('\n');
    draw();
  }
  q('#compare-choices').addEventListener('change',event=>{
    const input=event.target;if(input.type!=='checkbox')return;
    if(input.checked && chosen.size<4)chosen.add(input.value);else chosen.delete(input.value);
    choices();compare();
  });
  q('#compare-legend').addEventListener('click',event=>{
    const button=event.target.closest('[data-remove]');if(!button)return;
    chosen.delete(button.dataset.remove);choices();compare();
  });
  q('#compare-go').addEventListener('click',compare);
  ['#compare-start','#compare-end'].forEach(id=>q(id).addEventListener('change',()=>{++revision;reset('日期已更改，点击「比较走势」载入。');}));
  q('#compare-chart').addEventListener('mousemove',pick);
  q('#compare-chart').addEventListener('touchstart',pick,{passive:true});
  q('#compare-chart').addEventListener('touchmove',pick,{passive:true});
  document.addEventListener('swartea:workbench-section',event=>{if(event.detail.section==='compare'){if(!result)compare();else draw();}});
  if(typeof ResizeObserver==='function')new ResizeObserver(draw).observe(q('#compare-chart').parentElement);
  window.addEventListener('resize',draw);
  choices();draw();
});
"""
