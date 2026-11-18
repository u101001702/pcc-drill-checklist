#!/usr/bin/env python3
"""Build an offline PCC exercise checklist from checklist_data JSON files."""
import argparse
import json
import sys
from datetime import date
from html import escape
from pathlib import Path

LAYERS = {
    "主要問題處置", "預期發生問題", "接續發生問題",
    "置放與日常維護", "可能發生問題", "團隊流程",
}
CAPS = {
    "MON": "傷患監測", "RES": "急救復甦", "VENT": "通氣給氧",
    "AIR": "呼吸道管理", "PAIN": "鎮靜止痛", "EXAM": "理學檢查與診斷",
    "NURS": "護理與衛生", "SURG": "手術介入", "TELE": "遠距醫療指導",
    "EVAC": "包裹與後送準備",
}


def load_data(folder):
    files = sorted(p for p in folder.glob("*.json") if not p.name.startswith("_"))
    sections, errors, warnings = [], [], []
    for path in files:
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: 無法讀取 JSON：{exc}")
            continue
        if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
            errors.append(f"{path}: 頂層必須包含 sections 陣列")
            continue
        for si, sec in enumerate(data["sections"]):
            where = f"{path}: sections[{si}]"
            if not isinstance(sec, dict):
                errors.append(f"{where}: 必須是物件")
                continue
            for key in ("id", "group", "title", "problems"):
                if not sec.get(key): errors.append(f"{where}: 缺少 {key}")
            if not isinstance(sec.get("id"), str): errors.append(f"{where}: id 必須是文字")
            if not isinstance(sec.get("title"), str): errors.append(f"{where}: title 必須是文字")
            if sec.get("group") not in ("main", "proc", "general"):
                errors.append(f"{where}: group 必須是 main、proc 或 general")
            if not isinstance(sec.get("problems"), list):
                errors.append(f"{where}: problems 必須是陣列")
                continue
            if sec.get("group") == "general" and (sec.get("id") != "PCC"):
                errors.append(f"{where}: general 節 id 必須是 PCC")
            if sec.get("group") != "general" and sec.get("id") == "PCC":
                errors.append(f"{where}: PCC 節必須使用 group general")
            for pi, prob in enumerate(sec["problems"]):
                pw = f"{where}.problems[{pi}]"
                if not isinstance(prob, dict):
                    errors.append(f"{pw}: 必須是物件")
                    continue
                for key in ("id", "layer", "name"):
                    if not prob.get(key): errors.append(f"{pw}: 缺少 {key}")
                if not isinstance(prob.get("id"), str): errors.append(f"{pw}: id 必須是文字")
                if not isinstance(prob.get("name"), str): errors.append(f"{pw}: name 必須是文字")
                if not isinstance(prob.get("layer"), str) or prob.get("layer") not in LAYERS:
                    errors.append(f"{pw}: 不合法的 layer：{prob.get('layer')!r}")
                if sec.get("group") == "general":
                    if prob.get("layer") != "團隊流程": errors.append(f"{pw}: general 節 layer 必須是團隊流程")
                    if "monitor" in prob or "treat" in prob:
                        errors.append(f"{pw}: general 節使用 items，不可有 monitor/treat")
                    if not isinstance(prob.get("items"), list): errors.append(f"{pw}: items 必須是陣列")
                    item_fields = ("items",)
                else:
                    if "items" in prob: errors.append(f"{pw}: main/proc 節不可使用 items")
                    item_fields = ("monitor", "treat")
                for field in item_fields:
                    vals = prob.get(field)
                    if not isinstance(vals, list):
                        errors.append(f"{pw}: {field} 必須是陣列")
                        continue
                    for ii, item in enumerate(vals):
                        iw = f"{pw}.{field}[{ii}]"
                        if not isinstance(item, dict) or not isinstance(item.get("t"), str) or not item["t"].strip():
                            errors.append(f"{iw}: 必須是含非空 t 的物件")
                            continue
                        cap = item.get("cap", [])
                        if not isinstance(cap, list):
                            errors.append(f"{iw}: cap 必須是代碼陣列")
                        else:
                            if len(cap) > 2: errors.append(f"{iw}: cap 最多 2 個代碼")
                            for code in cap:
                                if not isinstance(code, str) or code not in CAPS: errors.append(f"{iw}: 未知 cap 代碼 {code!r}")
            rel = sec.get("related_procs", [])
            if sec.get("group") == "main" and not isinstance(rel, list):
                errors.append(f"{where}: related_procs 必須是陣列")
            elif sec.get("group") == "proc" and "related_procs" in sec:
                errors.append(f"{where}: proc 節不需要 related_procs")
        sections.extend(data["sections"])

    ids, pids = set(), set()
    for sec in sections:
        if not isinstance(sec, dict): continue
        sid = sec.get("id")
        if sid in ids: errors.append(f"section id 重複：{sid}")
        ids.add(sid)
        for p in sec.get("problems", []) if isinstance(sec.get("problems"), list) else []:
            if not isinstance(p, dict): continue
            pid = p.get("id")
            if pid in pids: errors.append(f"problem id 重複：{pid}")
            pids.add(pid)
    proc_ids = {s.get("id") for s in sections if isinstance(s, dict) and s.get("group") == "proc"}
    main_sections = [s for s in sections if isinstance(s, dict) and s.get("group") == "main"]
    if main_sections and not proc_ids:
        warnings.append("資料中沒有 proc 節，無法檢查 related_procs 指向；已跳過參照檢查。")
    elif proc_ids:
        for sec in main_sections:
            for target in sec.get("related_procs", []):
                if target not in proc_ids:
                    errors.append(f"section {sec.get('id')} related_procs 指向不存在的 T 節：{target}")
    return sections, errors, warnings


def render_html(sections):
    payload = json.dumps(sections, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    import hashlib
    dhash = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    html = r'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PCC 演習檢核表（TCH-015）</title>
<style>
:root{font-family:system-ui,-apple-system,"Noto Sans TC",sans-serif;color:#18212b;background:#f3f6f8;font-size:16px}*{box-sizing:border-box}body{margin:0}.wrap{max-width:1500px;margin:auto;padding:16px}.top{background:#fff;border:1px solid #d5dee6;border-radius:12px;padding:16px;margin-bottom:12px}.title-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}h1{font-size:1.5rem;margin:0 0 6px}.version,footer{color:#596875;font-size:.9rem}.fields{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin:14px 0}.fields label{display:flex;flex-direction:column;gap:4px;font-weight:600}.fields input{font:inherit;padding:8px;border:1px solid #aab7c3;border-radius:6px;min-height:40px}.toolbar,.chips,.toggles{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.toolbar{margin:8px 0}.btn,.chip{font:inherit;min-height:38px;padding:6px 12px;border:1px solid #8193a3;border-radius:8px;background:#fff;color:#16222d;cursor:pointer}.btn:hover,.chip:hover{background:#eef5fa}.chip.active{color:#fff;background:#176b87;border-color:#176b87}.toggle{display:flex;align-items:center;gap:7px;min-height:38px;padding:4px 8px}.toggle input,.checks input{width:22px;height:22px;accent-color:#147493}.chips{margin:8px 0}.chip-title{font-weight:700;margin-right:4px}.scorebar{position:sticky;top:0;z-index:5;background:#142e40;color:white;border-radius:10px;padding:10px 14px;box-shadow:0 2px 10px #172b3b35}.scoregrid{display:flex;gap:18px;flex-wrap:wrap}.scoregrid strong{white-space:nowrap}.cap-summary{background:#fff;border:1px solid #d5dee6;border-radius:10px;margin:12px 0;padding:10px 14px}.cap-summary summary{cursor:pointer;font-weight:700;min-height:30px}.caprow{display:grid;grid-template-columns:minmax(160px,230px) 1fr 110px;align-items:center;gap:10px;margin:8px 0}.bar{height:12px;background:#e1e8ed;border-radius:8px;overflow:hidden}.bar>i{height:100%;display:block;background:#2786a3}.section{background:#fff;border:1px solid #cbd6df;border-radius:10px;margin:12px 0;overflow:hidden}.section>summary{font-size:1.14rem;font-weight:700;cursor:pointer;padding:12px 14px;background:#eaf1f5}.section-body{padding:8px}.layer-title{font-size:1rem;margin:12px 4px 8px;padding-bottom:4px;border-bottom:1px solid #d8e1e7;color:#294d61}.problem{border:1px solid #d6dfe5;border-radius:9px;margin:8px 0;padding:10px;background:white;break-inside:avoid}.problem.na{background:#edf0f2;color:#66717a}.problem-head{display:flex;align-items:center;gap:10px}.problem-name{font-weight:700;font-size:1.03rem;flex:1}.checks{display:flex;align-items:center;gap:8px;min-height:36px}.status{font:inherit;min-height:38px;border:1px solid #a7b4bf;border-radius:7px;padding:4px 8px;background:#fff}.problem-score{white-space:nowrap;font-size:.92rem;color:#405565}.columns{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px}.columns.one{grid-template-columns:1fr}@media (min-width:1000px){details.section.general .columns.one .col{column-count:2;column-gap:28px}details.section.general .columns.one .col>h4{column-span:all}details.section.general .columns.one .item{break-inside:avoid}details.section.general .columns.one .item-h{break-after:avoid;break-inside:avoid}}.col h4{margin:4px 0 6px;color:#31556a}.item{display:flex;align-items:flex-start;gap:8px;margin:5px 0;line-height:1.45}.item input{flex:0 0 22px;margin:1px 0 0;width:22px;height:22px}.item-text{flex:1}.src{color:#71808c;font-size:.82rem;margin-left:5px}.cap{display:inline-block;margin-left:5px;padding:1px 6px;border-radius:10px;background:#e0eff4;color:#245d70;font-size:.75rem;white-space:nowrap}.note{width:100%;font:inherit;min-height:38px;margin-top:8px;padding:7px;border:1px solid #b9c5ce;border-radius:6px}.item-note{display:block;color:#5b6b78;font-size:.84rem;margin-top:1px;line-height:1.4}.item-h{font-weight:700;color:#294d61;margin:12px 0 2px;padding-top:6px;border-top:1px dashed #d8e1e7}.item-h:first-child{border-top:0;margin-top:2px}.hidden{display:none!important}footer{padding:16px 4px}.plan{background:#fff;border:2px solid #176b87;border-radius:12px;margin:18px 0;padding:14px 16px}.plan h2{margin:0 0 4px;font-size:1.3rem;color:#142e40}.plan-meta{color:#596875;font-size:.9rem;margin-bottom:8px}.plan-cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}.plan h3{margin:6px 0;color:#176b87}.plan ol{margin:0;padding-left:1.6em}.plan li{margin:4px 0;line-height:1.45}.plan .lvb{font-size:.72rem;padding:1px 5px;border-radius:4px;margin-right:5px;vertical-align:1px}.lvb.l1{background:#c62828;color:#fff}.lvb.l3{background:#e3e8ec;color:#596875}.pgh{margin:12px 0 4px;color:#176b87;font-size:.95rem;border-bottom:1px solid #d5dee6}.pids{color:#71808c;font-size:.8rem;margin-left:6px;white-space:nowrap}.plan .pnote{display:block;color:#5b6b78;font-size:.84rem}.plan .pnote+.pnote{margin-top:0}@media(max-width:800px){.plan-cols{grid-template-columns:1fr}}
@media(max-width:800px){.wrap{padding:8px}.fields{grid-template-columns:repeat(2,minmax(130px,1fr))}.columns{grid-template-columns:1fr}.caprow{grid-template-columns:130px 1fr 82px;gap:6px}.problem-head{flex-wrap:wrap}.problem-name{min-width:55%}}
.status-print{display:none}@media print{.status-print{display:inline;font-weight:600;margin-left:8px}body{background:#fff;font-size:12pt}.wrap{max-width:none;padding:0}.top,.section,.cap-summary,.problem{box-shadow:none;border-color:#9aa3aa}.toolbar,.chips,.toggles,.btn,.status{display:none!important}.scorebar{position:static;background:white;color:#111;border:1px solid #888}.section:not(.hidden){display:block!important;break-inside:auto}.section>summary{list-style:none}.section>summary::-webkit-details-marker{display:none}.problem{break-inside:avoid}.item input{appearance:none;width:18px;height:18px;border:1px solid #111;border-radius:2px;position:relative}.item input:checked:after{content:"☑";position:absolute;inset:-3px 0 0 -1px;background:#fff;font-size:17px}.item input:not(:checked):after{content:"☐";position:absolute;inset:-3px 0 0 -1px;background:#fff;font-size:17px}.checks input{appearance:none;width:18px;height:18px;border:1px solid #111;position:relative}.checks input:checked:after{content:"☑";position:absolute;inset:-3px 0 0 -1px;background:#fff;font-size:17px}.checks input:not(:checked):after{content:"☐";position:absolute;inset:-3px 0 0 -1px;background:#fff;font-size:17px}.cap-summary{break-inside:avoid}.plan{break-before:page;border-color:#888}footer{font-size:10pt}}
</style></head><body><main class="wrap"><header class="top"><div class="title-row"><div><h1>PCC 演習檢核表（TCH-015）</h1><div class="version">資料版本：content.md v2、content_procedures.md v2｜產生日期：2026-11-17</div></div></div>
<div class="fields"><label>組別／隊伍名稱<input id="team" autocomplete="off"></label><label>日期<input id="date" type="date"></label><label>評分員<input id="rater" autocomplete="off"></label></div>
<div class="toggles"><label class="toggle"><input id="showSrc" type="checkbox">顯示出處</label><label class="toggle"><input id="showCaps" type="checkbox" checked>顯示核心能力標籤</label><label class="toggle"><input id="showGeneral" type="checkbox" checked>顯示 PCC 團隊流程</label><label class="toggle">顯示層級：<select id="lvSel" class="btn"><option value="1">只看 L1 必看</option><option value="2">L1＋L2 延伸</option><option value="3">全部（含 L3 教官參考）</option></select></label><label class="toggle"><input id="planNoAuto" type="checkbox">自動帶出的處置節不計分（計分、總表、CSV 一致）</label></div>
<div class="toolbar"><button class="btn" id="showAll">顯示全部</button><button class="btn" id="clearMain">清除勾選</button><button class="btn" id="expandAll">全部展開</button><button class="btn" id="collapseAll">全部收合</button><button class="btn" id="csv">匯出 CSV</button><button class="btn" id="print">列印</button><button class="btn" id="reset">重設</button></div>
<div class="chips" id="mainChips"><span class="chip-title">主要傷情：</span></div><div class="chips" id="procChips"><span class="chip-title">處置節：</span></div></header>
<div class="scorebar" id="scorebar"></div><details class="cap-summary" id="capSummary" open><summary>核心能力涵蓋</summary><div id="capRows"></div></details><div id="sections"></div><section class="plan" id="plan"><h2>監測與治療計畫總表</h2><div class="plan-meta" id="planMeta"></div><div class="toolbar"><label class="toggle">排序：<select id="planOrder" class="btn"><option value="mp">依 MARCH-PAWS</option><option value="cap">依 PCC 十大能力</option></select></label><button class="btn" id="copyPlan">複製總表</button></div><div class="plan-cols"><div><h3>監測計畫（<span id="planMonN">0</span> 項）</h3><div id="planMon"></div></div><div><h3>治療計畫（<span id="planTreatN">0</span> 項）</h3><div id="planTreat"></div></div></div></section><footer>參考來源：content.md v2、content_procedures.md v2、TCH-014 PCC 十大核心能力（CPG91 依 PFC WG 2014 重整）。</footer></main>
<script type="application/json" id="checklist-data">__DATA__</script><script>
(()=>{'use strict';
const data=JSON.parse(document.getElementById('checklist-data').textContent), KEY='tch015_checklist_'+'__DHASH__';
const CAPN={MON:'傷患監測',RES:'急救復甦',VENT:'通氣給氧',AIR:'呼吸道管理',PAIN:'鎮靜止痛',EXAM:'理學檢查與診斷',NURS:'護理與衛生',SURG:'手術介入',TELE:'遠距醫療指導',EVAC:'包裹與後送準備'};
const CAPC=['MON','RES','VENT','AIR','PAIN','EXAM','NURS','SURG','TELE','EVAC'];
let state={fields:{},main:[],proc:{},general:true,showSrc:false,showCaps:true,problems:{},items:{},notes:{},sections:{},capOpen:true};
try{state={...state,...JSON.parse(localStorage.getItem(KEY)||'{}')}}catch(_){ }
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sections=data.slice().sort((a,b)=>(a.group==='general'?-1:b.group==='general'?1:0));
function save(){localStorage.setItem(KEY,JSON.stringify(state))}
function sid(s){return String(s.id)} function pid(p){return String(p.id)}
function mainSelected(s){return state.main.includes(sid(s))}
function relatedVisible(s){return sections.some(m=>m.group==='main'&&state.main.includes(sid(m))&&(m.related_procs||[]).includes(sid(s)))}
function secVisible(s){if(s.group==='general')return state.general;if(s.group==='main')return mainSelected(s);if(state.main.length){let auto=relatedVisible(s);let choice=state.proc[sid(s)];return choice===undefined?auto:choice}return state.proc[sid(s)]===true}
function status(p,s){return state.problems[pid(p)]||'all'}
function itemEntries(p,s){if(s.group==='general')return p.items.map((x,i)=>({x,i,col:'flow'})).filter(o=>lvOK(o.x));let st=status(p,s),out=[];if(st==='all'||st==='未發生'||st==='已發生')p.monitor.forEach((x,i)=>out.push({x,i,col:'monitor'}));if(st==='all'||st==='已發生')p.treat.forEach((x,i)=>out.push({x,i,col:'treat'}));return out.filter(o=>lvOK(o.x))}
function lvOK(x){return (x.lv||2)<=Number(state.lv||1)}
function itemKey(p,col,i){return pid(p)+'|'+col+'|'+i}
function autoOut(s){return state.planNoAuto!==false&&s.group==='proc'&&state.proc[sid(s)]!==true}
function counted(p,s){return status(p,s)!=='不適用'&&!autoOut(s)}
function groupName(s){return s.group==='main'?'主要傷情':s.group==='proc'?'處置':'團隊流程'}
function renderChips(){const ms=$('mainChips'),ps=$('procChips');ms.innerHTML='<span class="chip-title">主要傷情：</span>';ps.innerHTML='<span class="chip-title">處置節：</span>';sections.filter(s=>s.group==='main').forEach(s=>{let b=document.createElement('button');b.className='chip '+(state.main.includes(sid(s))?'active':'');b.textContent=s.id+' '+s.title;b.onclick=()=>{if(!state.main.length)state.main=[sid(s)];else state.main=state.main.includes(sid(s))?state.main.filter(x=>x!==sid(s)):[...state.main,sid(s)];render()};ms.append(b)});sections.filter(s=>s.group==='proc').forEach(s=>{let b=document.createElement('button');let visible=state.main.length?(state.proc[sid(s)]===undefined?relatedVisible(s):state.proc[sid(s)]):(state.proc[sid(s)]===true);b.className='chip '+(visible?'active':'');b.textContent=s.id+' '+s.title;b.onclick=()=>{state.proc[sid(s)]=!visible;render()};ps.append(b)});ps.classList.toggle('hidden',!state.main.length&&!sections.some(s=>s.group==='proc'))}
function itemHtml(p,s,col,x,i){let k=itemKey(p,col,i),caps=Array.isArray(x.cap)?x.cap:[],src=x.src||'',disabled=status(p,s)==='不適用'?'disabled':'';return '<label class="item"><input type="checkbox" data-item="'+esc(k)+'" '+(state.items[k]?'checked':'')+' '+disabled+'><span class="item-text" title="'+esc(src)+'">'+(x.lv===1?'<b class="lvb l1">L1</b>':x.lv===3?'<b class="lvb l3">教官參考</b>':'')+esc(x.t)+(x.note?'<small class="item-note">備註：'+esc(x.note)+'</small>':'')+(src?'<small class="src '+(state.showSrc?'':'hidden')+'">'+esc(src)+'</small>':'')+caps.map(c=>'<small class="cap '+(state.showCaps?'':'hidden')+'">'+esc(CAPN[c]||c)+'</small>').join('')+'</span></label>'}
function renderProblem(p,s){let general=s.group==='general',key=pid(p),na=status(p,s)==='不適用',entries=itemEntries(p,s),cols=general?[['flow','團隊流程',p.items]]:[['monitor','未發生：監測',p.monitor],['treat','已發生：治療',p.treat]];let statButtons=general?['all','不適用'] : ['all','未發生','已發生','不適用'];let label={all:'全計','未發生':'未發生','已發生':'已發生','不適用':'不適用'};let html='<article class="problem '+(na?'na':'')+'" data-problem="'+esc(key)+'"><div class="problem-head">'+(!general?'<label class="checks"><input type="checkbox" data-problem-check="'+esc(key)+'" '+(state.problems[key+'|listed']?'checked':'')+' '+(na?'disabled':'')+'><span>已列入問題列表</span></label>':'')+'<span class="problem-name">'+esc(p.name)+'</span><select class="status" data-status="'+esc(key)+'">'+statButtons.map(v=>'<option value="'+v+'" '+(status(p,s)===v?'selected':'')+'>'+label[v]+'</option>').join('')+'</select><span class="status-print">狀態：'+label[status(p,s)]+'</span><span class="problem-score" data-p-score="'+esc(key)+'"></span></div><div class="columns '+(general?'one':'')+'">';
for(const [col,title,arr] of cols){html+='<div class="col"><h4>'+title+'</h4>'+(arr||[]).map((x,i)=>!lvOK(x)?'':((x.h&&(i===0||(arr[i-1]||{}).h!==x.h))?'<div class="item-h">'+esc(x.h)+'</div>':'')+itemHtml(p,s,col,x,i)).join('')+'</div>'}html+='</div>'+(general?'':'<input class="note" data-note="'+esc(key)+'" placeholder="備註" value="'+esc(state.notes[key]||'')+'">')+'</article>';return html}
function render(){renderChips();$('lvSel').value=state.lv||'1';$('showSrc').checked=!!state.showSrc;$('showCaps').checked=state.showCaps!==false;$('showGeneral').checked=state.general!==false;$('capSummary').open=state.capOpen!==false;
for(const k of ['team','date','rater'])$(k).value=state.fields[k]|| (k==='date'?new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10):'');
const host=$('sections');host.innerHTML=sections.some(s=>s.group!=='general'&&secVisible(s))?'':'<p class="empty-hint" style="padding:16px;color:#596875">還沒選傷情或處置節。請在上方點選，問題列表才會顯示在這裡。</p>';sections.filter(secVisible).forEach(s=>{let d=document.createElement('details');d.className='section'+(s.group==='general'?' general':'');d.open=state.sections[sid(s)]!==false;d.dataset.sid=sid(s);let groups={};s.problems.forEach(p=>(groups[p.layer]??=[]).push(p));d.innerHTML='<summary>'+esc(s.id+'｜'+s.title)+' <small>（'+groupName(s)+(autoOut(s)?'・自動帶出，不計分':'')+'）</small></summary><div class="section-body">'+Object.entries(groups).map(([layer,probs])=>'<section><h3 class="layer-title">'+esc(layer)+'</h3>'+probs.map(p=>renderProblem(p,s)).join('')+'</section>').join('')+'<div class="problem-score section-score"></div></div>';d.addEventListener('toggle',()=>{state.sections[sid(s)]=d.open;save();updateScores()});host.append(d)});
host.querySelectorAll('[data-item]').forEach(e=>e.onchange=()=>{state.items[e.dataset.item]=e.checked;save();updateScores()});host.querySelectorAll('[data-problem-check]').forEach(e=>e.onchange=()=>{state.problems[e.dataset.problemCheck+'|listed']=e.checked;save();updateScores()});host.querySelectorAll('[data-status]').forEach(e=>e.onchange=()=>{state.problems[e.dataset.status]=e.value;save();render()});host.querySelectorAll('[data-note]').forEach(e=>e.oninput=()=>{state.notes[e.dataset.note]=e.value;save()});host.querySelectorAll('.section').forEach(d=>{let s=sections.find(x=>sid(x)===d.dataset.sid);d.addEventListener('toggle',()=>updateScores())});updateScores();renderPlan()}
function planData(){let mon=new Map(),treat=new Map(),probs=[];let noAuto=state.planNoAuto!==false;sections.filter(secVisible).forEach(s=>{if(s.group==='general')return;s.problems.forEach(p=>{if(!counted(p,s))return;probs.push(pid(p));for(const {x,col}of itemEntries(p,s)){let m=col==='monitor'?mon:treat,k=x.t;if(!m.has(k))m.set(k,{t:x.t,notes:[],pids:[],mp:x.mp||'',cap:(x.cap||[])[0]||''});let e=m.get(k);if(x.note&&!e.notes.includes(x.note))e.notes.push(x.note);if(!e.pids.includes(pid(p)))e.pids.push(pid(p))}})});return {mon:[...mon.values()],treat:[...treat.values()],probs}}
const MPO=[['M','M 大出血'],['A','A 呼吸道'],['R','R 呼吸'],['C','C 循環'],['H','H 低體溫／頭部'],['P','P 止痛與鎮靜'],['AB','A 抗生素與感染'],['W','W 傷口'],['S','S 夾板固定'],['X','PCC 照護（護理、遠距、後送）']];
function planGroups(list){let mode=state.planOrder||'mp',order=mode==='mp'?MPO:CAPC.map(c=>[c,CAPN[c]]),key=e=>mode==='mp'?e.mp:e.cap,out=order.map(([k,n])=>({n,items:list.filter(e=>key(e)===k)}));out.push({n:mode==='mp'?'未分類':'未標記',items:list.filter(e=>!order.some(([k])=>k===key(e)))});out.forEach(g=>g.items=[...g.items.filter(e=>!e.t.includes('後送')),...g.items.filter(e=>e.t.includes('後送'))]);return out.filter(g=>g.items.length)}
function renderPlan(){let d=planData();const li=e=>'<li>'+esc(e.t)+'<span class="pids">［'+esc(e.pids.join('、'))+'］</span>'+e.notes.map(n=>'<small class="pnote">備註：'+esc(n)+'</small>').join('')+'</li>';const gh=list=>{let n=0;return planGroups(list).map(g=>'<h4 class="pgh">'+esc(g.n)+'（'+g.items.length+'）</h4><ol start="'+(n+1)+'">'+g.items.map(e=>(n++,li(e))).join('')+'</ol>').join('')||'<p>（無）</p>'};$('planMon').innerHTML=gh(d.mon);$('planTreat').innerHTML=gh(d.treat);$('planOrder').value=state.planOrder||'mp';$('planMonN').textContent=d.mon.length;$('planTreatN').textContent=d.treat.length;$('planNoAuto').checked=state.planNoAuto!==false;$('planMeta').textContent=(state.main.length?'依目前選擇的傷情：'+state.main.join('、'):'目前沒有選傷情')+(state.planNoAuto!==false?'；已排除自動帶出的處置節':'；含自動帶出的處置節')+'；依各題狀態（未發生＝只列監測；已發生或全計＝監測＋治療；不適用＝不列）；顯示層級 '+({'1':'L1','2':'L1＋L2','3':'全部'}[state.lv||'1'])+'；共 '+d.probs.length+' 題，相同項目合併並標示來自哪幾題'}
function planText(){let d=planData(),f=e=>'- '+e.t+'［'+e.pids.join('、')+'］'+(e.notes.length?'（'+e.notes.join('；')+'）':'');const g=list=>planGroups(list).flatMap(x=>['### '+x.n,...x.items.map(f)]);return ['監測與治療計畫總表',$('planMeta').textContent,'','## 監測計畫',...g(d.mon),'','## 治療計畫',...g(d.treat)].join('\n')}
function updateScores(){let total={listC:0,listN:0,monC:0,monN:0,treatC:0,treatN:0,flowC:0,flowN:0,allC:0,allN:0},caps=Object.fromEntries(CAPC.map(c=>[c,{c:0,n:0}])),un={c:0,n:0};
document.querySelectorAll('.section').forEach(el=>{let s=sections.find(x=>sid(x)===el.dataset.sid),local={c:0,n:0};s.problems.forEach(p=>{if(!counted(p,s))return;let entries=itemEntries(p,s),pc=0,pn=0;for(const {x,i,col} of entries){let k=itemKey(p,col,i),checked=!!state.items[k];pc+=checked?1:0;pn++;let cc=x.cap||[];if(cc.length)cc.forEach(c=>{caps[c].n++;if(checked)caps[c].c++});else{un.n++;if(checked)un.c++}if(col==='monitor'){total.monN++;if(checked)total.monC++}else if(col==='treat'){total.treatN++;if(checked)total.treatC++}else{total.flowN++;if(checked)total.flowC++}}
if(s.group!=='general'){total.listN++;if(state.problems[pid(p)+'|listed'])total.listC++;pc+=state.problems[pid(p)+'|listed']?1:0;pn++}total.allC+=pc;total.allN+=pn;local.c+=pc;local.n+=pn});let score=el.querySelector('.section-score');if(score)score.textContent='本節小計：'+local.c+'／'+local.n+'（'+pct(local.c,local.n)+'）';el.querySelectorAll('[data-p-score]').forEach(x=>{let p=s.problems.find(y=>pid(y)===x.dataset.pScore);if(!p)return;let active=counted(p,s),es=active?itemEntries(p,s):[],c=es.filter(o=>state.items[itemKey(p,o.col,o.i)]).length+(active&&s.group!=='general'&&state.problems[pid(p)+'|listed']?1:0),n=es.length+(active&&s.group!=='general'?1:0);x.textContent='得分 '+c+'／'+n+'（'+pct(c,n)+'）'})});
$('scorebar').innerHTML='<div class="scoregrid"><strong>問題列表完整度：'+total.listC+'／'+total.listN+'（'+pct(total.listC,total.listN)+'）</strong><strong>監測：'+total.monC+'／'+total.monN+'（'+pct(total.monC,total.monN)+'）</strong><strong>治療：'+total.treatC+'／'+total.treatN+'（'+pct(total.treatC,total.treatN)+'）</strong><strong>團隊流程：'+total.flowC+'／'+total.flowN+'（'+pct(total.flowC,total.flowN)+'）</strong><strong>總計：'+total.allC+'／'+total.allN+'（'+pct(total.allC,total.allN)+'）</strong></div>';
let rows=CAPC.map(c=>[CAPN[c],caps[c]]).concat([['未標記',un]]);$('capRows').innerHTML=rows.map(([name,v])=>'<div class="caprow"><span>'+esc(name)+'</span><div class="bar"><i style="width:'+pct(v.c,v.n)+'"></i></div><span>'+v.c+'／'+v.n+'（'+pct(v.c,v.n)+'）</span></div>').join('')}
function pct(c,n){return n?Math.round(c*100/n)+'%':'0%'}
function csv(){let rows=[['組別','日期','評分員','section','layer','problem id','問題','狀態','已列入問題列表','欄別','項目','是否勾選','備註','核心能力','層級','項目備註']];let date=$('date').value,team=$('team').value,rater=$('rater').value,totalCheck=0,totalCount=0;sections.filter(secVisible).forEach(s=>s.problems.forEach(p=>{if(!counted(p,s))return;let listed=s.group==='general'?'':(state.problems[pid(p)+'|listed']?'是':'否'),st=status(p,s),note=state.notes[pid(p)]||'',base=[team,date,rater,s.id,p.layer,p.id,p.name,st==='all'?'全計':st,listed];if(s.group!=='general'){let yes=listed==='是';totalCheck+=yes?1:0;totalCount++;rows.push([...base,'問題名稱',p.name,yes?'是':'否',note,''])}for(const {x,i,col}of itemEntries(p,s)){let yes=!!state.items[itemKey(p,col,i)];totalCheck+=yes?1:0;totalCount++;rows.push([...base,col==='flow'?'流程':col==='monitor'?'監測':'治療',x.t,yes?'是':'否',note,(x.cap||[]).map(c=>CAPN[c]||c).join('、'),'L'+(x.lv||2),x.note||''])}}));
// Build capability summary rows from the displayed and scoreable items.
let stat=Object.fromEntries(CAPC.map(c=>[c,{c:0,n:0}]));let un={c:0,n:0};sections.filter(secVisible).forEach(s=>s.problems.filter(p=>counted(p,s)).forEach(p=>itemEntries(p,s).forEach(({x,i,col})=>{let yes=!!state.items[itemKey(p,col,i)];if((x.cap||[]).length)(x.cap||[]).forEach(c=>{stat[c].n++;if(yes)stat[c].c++});else{un.n++;if(yes)un.c++}})));for(const c of CAPC)rows.push([team,date,rater,'能力小計','',c,CAPN[c],'','','','','',stat[c].c+'／'+stat[c].n,'']);rows.push([team,date,rater,'能力小計','','未標記','未標記','','','','','',un.c+'／'+un.n,'']);rows.push([team,date,rater,'總分','','','總計','','','','',totalCheck+'／'+totalCount,'','']);
let csvText='\uFEFF'+rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');let blob=new Blob([csvText],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='PCC_checklist_'+($('team').value||'未命名').replace(/[\\/:*?"<>|]/g,'_')+'_'+($('date').value||'').replace(/-/g,'')+'.csv';a.click();URL.revokeObjectURL(a.href)}
['team','date','rater'].forEach(k=>$(k).oninput=()=>{state.fields[k]=$(k).value;save()});$('showSrc').onchange=()=>{state.showSrc=$('showSrc').checked;save();render()};$('showCaps').onchange=()=>{state.showCaps=$('showCaps').checked;save();render()};$('showGeneral').onchange=()=>{state.general=$('showGeneral').checked;save();render()};$('capSummary').ontoggle=()=>{state.capOpen=$('capSummary').open;save()};$('showAll').onclick=()=>{state.main=[];state.proc={};render()};$('clearMain').onclick=()=>{if(confirm('清除所有勾選、題目狀態與備註？（保留組別、日期、評分員與傷情選擇）')){state.items={};state.problems={};state.notes={};save();render()}};$('expandAll').onclick=()=>document.querySelectorAll('.section').forEach(d=>d.open=true);$('collapseAll').onclick=()=>document.querySelectorAll('.section').forEach(d=>d.open=false);$('csv').onclick=csv;$('lvSel').onchange=()=>{state.lv=$('lvSel').value;save();render()};$('planOrder').onchange=()=>{state.planOrder=$('planOrder').value;save();renderPlan()};$('planNoAuto').onchange=()=>{state.planNoAuto=$('planNoAuto').checked;save();render()};$('copyPlan').onclick=()=>{navigator.clipboard.writeText(planText()).then(()=>{$('copyPlan').textContent='已複製';setTimeout(()=>$('copyPlan').textContent='複製總表',1500)})};$('print').onclick=()=>window.print();$('reset').onclick=()=>{if(confirm('確定清除所有檢核表狀態？')){localStorage.removeItem(KEY);location.reload()}};window.addEventListener('beforeprint',()=>document.querySelectorAll('.section').forEach(d=>d.open=true));render();
})();</script></body></html>'''
    return html.replace("__DATA__", payload).replace("__DHASH__", dhash).replace("2026-11-17", date.today().isoformat())


def main():
    parser = argparse.ArgumentParser(description="產生離線 PCC 演習檢核表")
    parser.add_argument("--data", default="checklist_data", help="JSON 資料資料夾（預設 checklist_data）")
    parser.add_argument("--out", default="checklist.html", help="輸出 HTML（預設 checklist.html）")
    args = parser.parse_args()
    sections, errors, warnings = load_data(Path(args.data))
    for warning in warnings: print(f"警告：{warning}", file=sys.stderr)
    if errors:
        for error in errors: print(f"錯誤：{error}", file=sys.stderr)
        return 1
    try:
        Path(args.out).write_text(render_html(sections), encoding="utf-8")
    except OSError as exc:
        print(f"錯誤：無法寫入 {args.out}：{exc}", file=sys.stderr)
        return 1
    problems = sum(len(s["problems"]) for s in sections)
    mon = sum(len(p.get("monitor", [])) for s in sections for p in s["problems"])
    treat = sum(len(p.get("treat", [])) for s in sections for p in s["problems"])
    flow = sum(len(p.get("items", [])) for s in sections for p in s["problems"])
    print(f"section 數：{len(sections)}")
    print(f"problem 數：{problems}")
    print(f"item 數：{mon + treat + flow}（monitor {mon}、treat {treat}、流程 {flow}）")
    print(f"已輸出：{args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
