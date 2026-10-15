"""Render the local global-index daily-K research page.

This module is **additive and separate** from
:mod:`analysis.research.market_snapshot_view`: the existing A-share static
snapshot page and its record contract are untouched and stay in their own file.

The page shell embeds only *selector metadata* derived from the canonical
registry (``list_global_indices``) plus one endpoint URL. Every price number is
fetched at runtime through the single research service endpoint, so the browser
never calls a provider and no market data is hardcoded here.

Rendered states: ``ok`` / ``empty`` / ``unavailable`` / ``error``, each showing
data date, source, availability, freshness and the trading-day status (which
stays ``unknown`` when no exchange-calendar evidence is attached).
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_API_PATH = "/api/daily-k"

STATUS_LABELS: Mapping[str, str] = {
    "ok": "可用 / available",
    "empty": "无数据 / empty",
    "unavailable": "不可用 / unavailable",
    "error": "错误 / error",
}


def _text(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return html.escape(fallback, quote=True)
    return html.escape(str(value), quote=True)


_STYLE = """
:root{color-scheme:dark;--bg:#0f1115;--fg:#e6e8ee;--muted:#9aa4b2;--card:#181c24;
--line:#2a303c;--accent:#4c9ffe;--warn:#f2b04c;--bad:#f2777a;--ok:#5fd08a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line)}
h1{font-size:16px;margin:0 0 10px}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
label{display:flex;flex-direction:column;font-size:12px;color:var(--muted);gap:4px}
select,input,button{background:var(--card);color:var(--fg);border:1px solid var(--line);
border-radius:6px;padding:6px 8px;font:inherit;min-height:34px}
button{cursor:pointer}
main{padding:16px;display:grid;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.meta{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted)}
.meta b{color:var(--fg);font-weight:600}
.state{font-weight:600}
.state.ok{color:var(--ok)}.state.empty{color:var(--warn)}
.state.unavailable,.state.error{color:var(--bad)}
.chartwrap{overflow-x:auto;overflow-y:hidden}
canvas{display:block;height:280px;min-width:100%;cursor:crosshair;touch-action:pan-x}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:4px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
.scroll{max-height:260px;overflow:auto}
.note{color:var(--muted);font-size:12px}
@media (max-width:640px){canvas{height:220px}main{padding:10px}.meta{gap:10px}}
"""

_JS = """
const OPTS=window.__OPTS||[];const API=window.__API||'/api/daily-k';
const state={payload:null,hover:null,zoom:1,from:0};
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const fmt=(v,d=2)=>(v===null||v===undefined)?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
function statusText(p){return p.status==='ok'?'available':p.status==='empty'?'empty':p.status==='unavailable'?'unavailable':'error';}
function renderMeta(p){
  $('#head').innerHTML='<div><b>'+esc(p.name)+'</b> '+esc(p.index_id)+' · '+esc(String(p.market||'').toUpperCase())+' · '+esc(p.currency)+' · '+esc(p.timezone)+'</div><div class="note">provider symbol '+esc(p.provider_symbol)+' ('+esc(p.publisher)+' '+esc(p.local_code)+')</div>';
  $('#meta').innerHTML=[['数据日期',p.data_date||'—'],['来源',p.source||'—'],['可用性',p.availability],['新鲜度',p.freshness],['交易日状态',p.trading_day_status],['provider status',p.provider_status||'—'],['条数',p.bar_count],['时区',p.timezone],['窗口',String(p.start_date||'')+' – '+String(p.end_date||'')],['降级',p.degraded?'是':'否']].map(kv=>'<span>'+esc(kv[0])+' <b>'+esc(kv[1])+'</b></span>').join('');
  const st=$('#state');st.className='state '+(p.status||'error');st.textContent=statusText(p)+' / '+(p.status||'error');
  $('#note').textContent=p.unavailable_reason||p.failure_reason||'价格单位 index points；成交量仅在数据源提供时显示。';
}
function renderTable(p){
  const bars=p.bars||[],showVol=bars.some(b=>b.volume!=null);
  $('#table').innerHTML='<table><thead><tr><th>日期</th><th>开</th><th>高</th><th>低</th><th>收</th>'+(showVol?'<th>量</th>':'')+'</tr></thead><tbody>'+bars.slice().reverse().map(b=>'<tr><td>'+esc(b.date)+'</td><td>'+fmt(b.open)+'</td><td>'+fmt(b.high)+'</td><td>'+fmt(b.low)+'</td><td>'+fmt(b.close)+'</td>'+(showVol?'<td>'+(b.volume==null?'—':fmt(b.volume,0))+'</td>':'')+'</tr>').join('')+'</tbody></table>';
  $('#empty').hidden=p.status!=='empty';
}
function visible(){const bars=state.payload?.bars||[],span=Math.max(1,Math.ceil(bars.length/state.zoom));state.from=Math.max(0,Math.min(bars.length-span,state.from));return bars.slice(state.from,state.from+span);}
function layout(){
  const c=$('#chart'),viewport=c.parentNode,bars=state.payload?.bars||[],span=Math.max(1,Math.ceil(bars.length/state.zoom));
  const viewportWidth=viewport.clientWidth||600,bw=bars.length?Math.max(5,Math.min(18,viewportWidth/span)):8,width=Math.max(viewportWidth,Math.ceil(span*bw));
  c.style.width=width+'px';const pan=$('#pan');pan.max=String(Math.max(0,bars.length-span));state.from=Math.min(state.from,Number(pan.max));pan.value=String(state.from);
  const H=c.clientHeight||280,dpr=window.devicePixelRatio||1;c.width=width*dpr;c.height=H*dpr;const g=c.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,width,H);
  return {c,g,bw,width,H};
}
function draw(){
  const {c,g,bw,width:W,H}=layout(),rows=visible();if(!rows.length)return;
  const plotH=H-22,hi=Math.max(...rows.map(b=>b.high)),lo=Math.min(...rows.map(b=>b.low)),pad=(hi-lo)*.08||1,y=v=>plotH-pad-(v-(lo-pad))/((hi-lo)+2*pad)*(plotH-2*pad);
  g.strokeStyle='#2a303c';g.beginPath();g.moveTo(0,y(rows[0].open));g.lineTo(W,y(rows[0].open));g.stroke();
  rows.forEach((b,i)=>{const x=i*bw+bw/2,color=b.close>=b.open?'#5fd08a':'#f2777a';g.strokeStyle=color;g.fillStyle=color;g.beginPath();g.moveTo(x,y(b.high));g.lineTo(x,y(b.low));g.stroke();g.fillRect(x-bw*.3,Math.min(y(b.open),y(b.close)),bw*.6,Math.max(1.5,Math.abs(y(b.open)-y(b.close))));});
  g.fillStyle='#9aa4b2';g.font='10px system-ui';g.textBaseline='bottom';
  const ticks=[0,Math.floor((rows.length-1)/2),rows.length-1];
  ticks.forEach(i=>{const x=Math.max(2,Math.min(W-72,i*bw+2));g.fillText(rows[i].date,x,H-2);});
  if(state.hover!==null){const i=state.hover-state.from,b=rows[i];if(b){const x=i*bw+bw/2;g.strokeStyle='#4c9ffe';g.beginPath();g.moveTo(x,0);g.lineTo(x,H);g.stroke();$('#probe').textContent=b.date+'  开 '+fmt(b.open)+'  高 '+fmt(b.high)+'  低 '+fmt(b.low)+'  收 '+fmt(b.close)+(b.volume!=null?'  量 '+fmt(b.volume,0):'');}}
}
function pick(ev){const bars=state.payload?.bars||[];if(!bars.length)return;const c=$('#chart'),r=c.getBoundingClientRect(),src=ev.touches?.[0]||ev,{bw}=layout();const local=Math.max(0,Math.floor((src.clientX-r.left)/bw));state.hover=Math.min(bars.length-1,state.from+local);draw();}
async function load(){
  const q=new URLSearchParams({index_id:$('#index').value,market:$('#market').value,start_date:$('#start').value,end_date:$('#end').value});$('#empty').hidden=true;$('#probe').textContent='';
  try{const res=await fetch(API+'?'+q.toString());const p=await res.json();state.payload=p;state.hover=null;state.zoom=Number($('#zoom').value)||1;state.from=0;$('#pan').value='0';renderMeta(p);renderTable(p);draw();}
  catch(e){$('#state').className='state error';$('#state').textContent='error';$('#note').textContent='研究服务不可用 / research service unavailable: '+String(e);}
}
function fillMarkets(){const markets=Array.from(new Set(OPTS.map(o=>o.market)));$('#market').innerHTML=markets.map(m=>'<option value="'+esc(m)+'">'+esc(String(m).toUpperCase())+'</option>').join('');fillIndices();}
function fillIndices(){const m=$('#market').value;$('#index').innerHTML=OPTS.filter(o=>o.market===m).map(o=>'<option value="'+esc(o.index_id)+'">'+esc(o.name)+(o.proven==='no'?'（未验证 unavailable）':'')+'</option>').join('');}
document.addEventListener('DOMContentLoaded',()=>{fillMarkets();$('#market').addEventListener('change',()=>{fillIndices();load();});$('#index').addEventListener('change',load);$('#go').addEventListener('click',load);$('#zoom').addEventListener('input',e=>{state.zoom=Number(e.target.value)||1;state.from=0;$('#pan').value='0';draw();});$('#pan').addEventListener('input',e=>{state.from=Number(e.target.value)||0;state.hover=null;draw();});$('#chart').parentNode.addEventListener('scroll',draw);window.addEventListener('resize',draw);$('#chart').addEventListener('mousemove',pick);$('#chart').addEventListener('touchstart',pick,{passive:true});$('#chart').addEventListener('touchmove',pick,{passive:true});load();});
"""


def selector_options() -> list[dict[str, str]]:
    """Return selector options derived from the canonical global-index registry."""

    from analysis.research.global_market_research import list_index_choices

    return [dict(choice) for choice in list_index_choices()]


def render_global_market_research_page(
    options: Sequence[Mapping[str, Any]] | None = None,
    *,
    start_date: str = "",
    end_date: str = "",
    api_path: str = DEFAULT_API_PATH,
) -> str:
    """Render the local daily-K research page shell.

    The HTML embeds only selector metadata plus a single endpoint URL; every
    price number is fetched at runtime through the research service, so the
    browser never calls a provider.
    """

    choices = [dict(item) for item in options] if options is not None else selector_options()
    payload = json.dumps(choices, ensure_ascii=False).replace("</", "<\\/")
    api_payload = json.dumps(api_path).replace("</", "<\\/")
    return (
        '<!doctype html>\n'
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Global Index Daily-K Research</title>"
        f"<style>{_STYLE}</style></head><body>\n"
        "<header><h1>Global Index Daily-K Research · 全球指数日线研究</h1>\n"
        '<div class="bar">'
        '<label>市场 market<select id="market"></select></label>'
        '<label>指数 index<select id="index"></select></label>'
        f'<label>起始 start<input id="start" type="date" value="{_text(start_date, "")}"></label>'
        f'<label>结束 end<input id="end" type="date" value="{_text(end_date, "")}"></label>'
        '<label>缩放 zoom<input id="zoom" type="range" min="1" max="6" value="1"></label>'
        '<label>横向浏览 pan<input id="pan" type="range" min="0" max="0" value="0"></label>'
        '<button id="go" type="button">查询</button>'
        "</div></header>\n"
        "<main>"
        '<div class="card"><div id="head"></div><div class="meta" id="meta"></div>'
        '<div style="margin-top:8px">状态 status：<span id="state" class="state">loading</span></div>'
        '<div class="note" id="note"></div></div>'
        '<div class="card"><div id="probe" class="note">'
        "把指针移到图上可查看当日 OHLC · pointer over chart to inspect OHLC</div>"
        '<div class="chartwrap"><canvas id="chart"></canvas></div></div>'
        '<div class="card scroll" id="table"></div>'
        '<div class="card" id="empty" hidden>该窗口内没有可用的日线数据 (empty)。</div>'
        "</main>\n"
        f'<script>window.__OPTS={payload};window.__API={api_payload};</script>\n'
        f"<script>{_JS}</script>\n"
        "</body></html>"
    )


def render_research_state(payload: Mapping[str, Any]) -> str:
    """Render the status/summary block server-side for tests and CLI output."""

    status = str(payload.get("status") or "error")
    label = STATUS_LABELS.get(status, STATUS_LABELS["error"])
    return (
        f'<div class="state {_text(status, "error")}">{_text(payload.get("name"))} · '
        f'{_text(payload.get("index_id"))} · {_text(label)}</div>'
        '<div class="meta">'
        f'<span>数据日期 <b>{_text(payload.get("data_date"))}</b></span>'
        f'<span>来源 <b>{_text(payload.get("source"))}</b></span>'
        f'<span>条数 <b>{_text(payload.get("bar_count"), "0")}</b></span>'
        "</div>"
    )
