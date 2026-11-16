"""Write an offline, read-only HTML view of actual CAD reconstruction results."""
from __future__ import annotations

from html import escape
import json
import math
from pathlib import Path
from typing import Any


def _json_value(value: Any) -> Any:
    """Keep failed numeric results JSON-compatible without inventing a value."""
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def write_report(report: dict, path: Path) -> None:
    """Create a self-contained HTML report; controls only change the view.

    No CAD operations are executed here. Geometry verdicts are supplied by the
    caller, while native CAD verification is explicitly marked UNVERIFIED.
    Non-finite measurements are displayed as unavailable, never as zero.
    """
    payload = json.dumps(_json_value(report), ensure_ascii=False, allow_nan=False)
    # JSON inside a script element must not contain an HTML closing tag. Escape
    # all HTML-sensitive characters as JSON escapes, preserving the data itself.
    for literal, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                             ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        payload = payload.replace(literal, escaped)
    title = escape(str(report.get("title") or "CAD 재구성 실행 보고서"), quote=True)
    before, after = _HTML.split("__REPORT_PAYLOAD__", 1)
    output = before.replace("__REPORT_TITLE__", title) + payload + after
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8")


_HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>__REPORT_TITLE__</title>
<style>
:root{--ink:#173348;--muted:#607886;--teal:#087e83;--line:#d7e5e9;--bg:#f2f7f8;--red:#a43c45;--amber:#89651d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 "Segoe UI","Malgun Gothic",system-ui,sans-serif}
button,a{touch-action:manipulation}button{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible,canvas:focus-visible{outline:3px solid #e7b550;outline-offset:3px}
.shell{max-width:1400px;margin:auto;padding:26px 26px 40px}.eyebrow{font-size:11px;letter-spacing:.13em;color:var(--teal);font-weight:750;margin:0 0 5px}h1{font-size:clamp(24px,3vw,35px);line-height:1.25;letter-spacing:-.035em;margin:0 0 7px}h2{font-size:17px;margin:0 0 12px}h3{font-size:14px;margin:0 0 7px}.intro{color:var(--muted);max-width:820px;margin:0;font-size:13px}.topline{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.native{white-space:nowrap;background:#fff4d9;color:var(--amber);padding:5px 10px;border:1px solid #eddfb7;border-radius:7px;font-size:11px;font-weight:750}
.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:13px 0}.stat{min-width:0;padding:8px 12px;background:white;border:1px solid var(--line);border-radius:8px}.stat .key{color:var(--muted);font-size:11px;line-height:1.4}.stat .value{font-size:14px;font-weight:650;margin-top:2px;line-height:1.45;overflow-wrap:anywhere}
.panel{background:white;border:1px solid var(--line);border-radius:14px;overflow:hidden}.tabbar{display:flex;flex-wrap:wrap;gap:6px;padding:11px 13px;border-bottom:1px solid var(--line)}.tab{background:#f5f9fa;border:1px solid var(--line);border-radius:8px;padding:7px 12px;color:var(--muted);font-size:13px}.tab[aria-selected="true"]{background:var(--ink);border-color:var(--ink);color:#fff;font-weight:700}.tabs-empty{color:var(--muted);padding:5px}
.workspace{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(290px,1fr)}.scene{min-width:0;border-right:1px solid var(--line)}.scene-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:17px 20px 5px}.case-name{font-size:17px;font-weight:750;overflow-wrap:anywhere}.badge{font-size:11px;font-weight:750;border-radius:99px;padding:5px 10px;white-space:nowrap;background:#edf1f3;color:var(--muted)}.badge.pass{background:#e2f4ee;color:#167357}.badge.fail{background:#fff0f1;color:var(--red)}.badge.warn{background:#fff4dc;color:var(--amber)}
.canvas-wrap{position:relative;height:470px;min-height:280px;background:radial-gradient(ellipse at 45% 40%,#fff 0,#f7fafb 62%,#edf4f6 100%)}canvas{display:block;width:100%;height:100%;touch-action:none;cursor:grab}canvas:active{cursor:grabbing}.no-mesh{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);padding:40px;pointer-events:none}.no-mesh[hidden]{display:none}.viewtools{display:flex;gap:6px;flex-wrap:wrap;padding:0 18px 12px}.tool{border:1px solid var(--line);border-radius:7px;background:white;color:var(--ink);padding:5px 10px;font-size:12px}.tool:hover{background:#e9f3f4}.hint{font-size:12px;color:var(--muted);margin:0;padding:0 20px 16px}.mesh-info{font-variant-numeric:tabular-nums;font-size:11px;color:var(--muted);padding:0 20px 8px}
.details{padding:20px;min-width:0}.details-section+.details-section{margin-top:24px}.tablewrap{overflow:auto;max-height:320px;border-top:1px solid var(--line)}table{width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed}th,td{border-bottom:1px solid #e8eff1;text-align:left;vertical-align:top;padding:9px 7px;overflow-wrap:anywhere}th{width:47%;color:var(--muted);font-weight:500}td{font-variant-numeric:tabular-nums;white-space:pre-wrap}.empty{font-size:13px;color:var(--muted);margin:8px 0}.links{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.file-link{font-size:12px;text-decoration:none;padding:7px 11px;border:1px solid #b9d8d9;background:#f2faf9;color:var(--teal);border-radius:7px}.file-link:hover{background:#e1f3ef}
.notice{background:#f8fafb;border-top:1px solid var(--line);padding:13px 20px;color:var(--muted);font-size:12px}.bottom{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:16px}.bottom .panel{padding:20px}.reject{border-left:3px solid #d4a14a;background:#fffbf3;padding:11px 13px;margin-top:10px;border-radius:0 7px 7px 0}.reject p{font-size:12px;margin:2px 0;color:var(--muted);overflow-wrap:anywhere;white-space:pre-wrap}.limitations{margin:0;padding-left:20px;color:var(--muted);font-size:13px}.limitations li+li{margin-top:8px}details{margin-top:18px;border-top:1px solid var(--line);padding-top:12px}summary{cursor:pointer;font-size:13px;color:var(--teal)}.run-record{margin-top:12px;padding:11px 15px;background:#fff;border:1px solid var(--line);border-radius:10px}.run-record summary{font-weight:650}.run-record summary span{font-weight:400;color:var(--muted);font-size:11px;margin-left:8px}.run-record[open] summary{margin-bottom:10px}.run-record .tablewrap{max-height:360px}.footer{font-size:11px;color:var(--muted);margin-top:18px}noscript{display:block;padding:24px;color:var(--red)}
@media(max-width:900px){.shell{padding:17px 16px}.workspace{grid-template-columns:1fr}.scene{border-right:0;border-bottom:1px solid var(--line)}.canvas-wrap{height:380px}.details{display:grid;grid-template-columns:1fr 1fr;gap:20px}.details-section+.details-section{margin-top:0}.links{grid-column:1/-1;margin-top:0}.topline{display:block}.native{display:inline-block;margin-top:8px}.bottom{grid-template-columns:1fr}.scene-head{padding-top:12px}}
@media(max-width:520px){.canvas-wrap{height:320px}.details{display:block}.details-section+.details-section{margin-top:22px}.links{margin-top:16px}.scene-head{align-items:flex-start}.badge{white-space:normal}.summary{grid-template-columns:1fr 1fr;gap:6px;margin:10px 0}.stat{padding:6px 10px}.stat .value{font-size:13px}.shell{padding:14px 12px}.tab{padding:6px 9px}.run-record summary span{display:none}}
</style>
</head>
<body>
<main class="shell">
  <header class="topline"><div><p class="eyebrow">CAD RECONSTRUCTION · EXECUTION REPORT</p><h1 id="title">CAD 재구성 실행 보고서</h1><p class="intro">저장된 실제 형상과 검증 결과를 확인하세요.</p></div><span class="native">Native CAD · UNVERIFIED</span></header>
  <section id="summary" class="summary" aria-label="실행 요약"></section>
  <section class="panel" aria-label="형상 및 사례별 결과">
    <nav class="tabbar" id="tabs" role="tablist" aria-label="실행 결과 선택"></nav>
    <div class="workspace" id="case-panel" role="tabpanel">
      <div class="scene"><div class="scene-head"><span id="case-name" class="case-name">실행 결과 없음</span><span id="case-status" class="badge">기하 검증 · UNVERIFIED</span></div>
        <div class="canvas-wrap"><canvas id="viewer" tabindex="0" aria-label="저장된 형상 미리보기. 끌어서 회전하고 스크롤로 확대합니다."></canvas><div id="no-mesh" class="no-mesh">미리 볼 형상이 없습니다.</div></div>
        <div class="viewtools" aria-label="보기 조작"><button type="button" class="tool" data-view="iso">입체 보기</button><button type="button" class="tool" data-view="top">윗면</button><button type="button" class="tool" data-view="front">정면</button><button type="button" class="tool" data-view="in" aria-label="형상 확대">확대 +</button><button type="button" class="tool" data-view="out" aria-label="형상 축소">축소 −</button><button type="button" class="tool" data-view="reset">시점 초기화</button></div>
        <div class="mesh-info" id="mesh-info"></div><p class="hint">드래그로 회전 · 스크롤로 확대. 이 화면은 저장된 결과를 조회하며, 치수 변경이나 형상 재계산을 수행하지 않습니다.</p>
      </div>
      <aside class="details"><section class="details-section"><h2>모델 파라미터</h2><div id="parameters"></div></section><section class="details-section"><h2>기하 검사 결과</h2><div id="metrics"></div></section><div id="artifacts" class="links"></div></aside>
    </div>
    <div class="notice">기하 판정은 실행 프로그램이 기록한 결과를 표시합니다. 3D 미리보기는 실제 결과의 삼각형 메시이며, CATIA 등 대상 CAD의 native 피처·치수 편집과 재개방은 검증되지 않았습니다.</div>
  </section>
  <details class="run-record" id="run-record-details"><summary>실행 기록<span>입력 파일·해시·시간·검토 정보</span></summary><div id="run-record"></div></details>
  <div class="bottom"><section class="panel"><h2>거절·실패 기록</h2><div id="rejections"></div></section><section class="panel"><h2>확인된 범위와 한계</h2><ul id="limitations" class="limitations"></ul><details><summary>실행 환경·기능 상태</summary><div id="capabilities"></div></details></section></div>
  <p class="footer">외부 라이브러리나 네트워크 연결 없이 열 수 있는 결과 파일입니다. 검증되지 않은 값은 완료된 실적으로 표시하지 않습니다.</p>
</main>
<noscript>미리보기와 결과 표를 표시하려면 브라우저의 JavaScript 실행이 필요합니다. 원본 STEP·계획·검사 기록 파일도 함께 확인하세요.</noscript>
<script type="application/json" id="report-data">__REPORT_PAYLOAD__</script>
<script>
"use strict";
(() => {
  const data = JSON.parse(document.getElementById("report-data").textContent);
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => {const e=document.createElement(tag); if(text!==undefined)e.textContent=String(text); if(cls)e.className=cls; return e;};
  const labels = {plate_length:"판 길이",plate_width:"판 너비",plate_thickness:"판 두께",pocket_length:"포켓 길이",pocket_width:"포켓 너비",pocket_depth:"포켓 깊이",hole_diameter:"홀 지름",hole_pitch_x:"홀 X 간격",hole_pitch_y:"홀 Y 간격",volume_mm3:"체적 (mm³)",expected_volume_mm3:"기대 체적 (mm³)",actual_volume_mm3:"측정 체적 (mm³)",volume_error_mm3:"체적 오차 (mm³)",solid_count:"솔리드 수",length:"길이",width:"너비",thickness:"두께",diameter:"지름",depth:"깊이",units:"단위",case_count:"사례 수",native_verified:"Native 검증 여부",geometry_verified:"기하 검증 여부",input_step:"입력 STEP",status:"상태",reason:"이유",name:"이름",error:"오류",valid:"형상 유효성",input:"입력",input_type:"입력 종류",input_sha256:"입력 파일 SHA-256",source_preserved:"원본 보존",elapsed_seconds:"실행 시간 (초)",planner:"재구성 방법",method:"방법",reviewer:"검토 기록",editing_surface:"편집 인터페이스",changes:"변경 요청"};
  const fmt = v => {if(v===null || v===undefined)return "미제공";if(typeof v==="boolean")return v?"예":"아니요";if(typeof v==="number")return Number.isFinite(v)?new Intl.NumberFormat("ko-KR",{maximumSignificantDigits:9}).format(v):"미제공";if(typeof v==="object")return JSON.stringify(v);return String(v);};
  const label = k => labels[k] || k;
  function rows(value, prefix="", depth=0) {if(!value || typeof value!=="object")return [[prefix || "값",value]];const result=[];for(const [k,v] of Object.entries(value)){const key=prefix?prefix+" · "+label(k):label(k);if(v && typeof v==="object" && !Array.isArray(v) && depth<5)result.push(...rows(v,key,depth+1));else result.push([key,v]);}return result;}
  function table(target, value, emptyMessage) {target.replaceChildren();const entries=value && typeof value==="object"?rows(value):[];if(!entries.length){target.append(node("p",emptyMessage || "기록된 값이 없습니다.","empty"));return;}const wrap=node("div",undefined,"tablewrap"),t=node("table"),body=node("tbody");for(const [k,v] of entries){const tr=node("tr"),th=node("th",k);th.scope="row";tr.append(th,node("td",fmt(v)));body.append(tr);}t.append(body);wrap.append(t);target.append(wrap);}
  function safeLink(value) {if(typeof value!=="string")return null;const s=value.trim().replace(/\\/g,"/");if(!s || s.startsWith("/") || /^[a-z][a-z0-9+.-]*:/i.test(s) || /[\x00-\x1f]/.test(s))return null;const parts=s.split("/");if(parts.some(x=>x===".."))return null;return parts.map(encodeURIComponent).join("/");}
  $("title").textContent=data.title || "CAD 재구성 실행 보고서";
  const summary=data.summary && typeof data.summary==="object"?data.summary:{};
  const rawInput=String(summary.input_type || summary.input || "");
  const inputKind=/synthetic/i.test(rawInput)?"합성 STEP":/step|\.stp$/i.test(rawInput)?"STEP 파일":summary.editing_surface || summary.changes?"파라미터 계획":rawInput?"입력 파일":"미제공";
  const preserved=summary.source_preserved===true?"보존 확인":summary.source_preserved===false?"미보존":"미확인";
  const seconds=summary.elapsed_seconds;
  const elapsed=typeof seconds==="number" && Number.isFinite(seconds)?new Intl.NumberFormat("ko-KR",{maximumFractionDigits:2}).format(seconds)+"초":"미제공";
  const rawMethod=summary.planner && typeof summary.planner==="object"?String(summary.planner.method || ""):String(summary.planner || summary.method || summary.editing_surface || "");
  const method=/deterministic|rule.?based/i.test(rawMethod)?"규칙 기반":/parameter/i.test(rawMethod) || summary.changes?"파라미터 편집":/llm|generative/i.test(rawMethod)?"AI 계획":rawMethod?"기록 참조":"미제공";
  for(const [k,v] of [["입력 종류",inputKind],["원본 보존",preserved],["실행 시간",elapsed],["방법",method]]){const s=node("div",undefined,"stat");s.append(node("div",k,"key"),node("div",v,"value"));$("summary").append(s);}
  const hasSummary=Object.keys(summary).length>0;
  $("summary").hidden=!hasSummary;
  $("run-record-details").hidden=!hasSummary;
  table($("run-record"),summary,"실행 기록이 제공되지 않았습니다.");
  const cases=Array.isArray(data.cases)?data.cases.filter(c=>c && typeof c==="object"):[];
  const reject=Array.isArray(data.rejections)?data.rejections:[];
  if(!reject.length)$("rejections").append(node("p","기록된 거절·실패 항목이 없습니다.","empty"));
  reject.forEach((r,i)=>{const box=node("article",undefined,"reject");box.append(node("h3",r && typeof r==="object"?(r.name || r.id || "기록 "+(i+1)):"기록 "+(i+1)));if(r && typeof r==="object"){for(const [k,v] of Object.entries(r)){if(k!=="name" && k!=="id")box.append(node("p",label(k)+": "+fmt(v)));}}else box.append(node("p",fmt(r)));$("rejections").append(box);});
  const limitations=Array.isArray(data.limitations)?data.limitations:[];
  limitations.forEach(v=>$("limitations").append(node("li",fmt(v))));
  if(!limitations.length)$("limitations").append(node("li","추가 한계 설명이 제공되지 않았습니다. Native CAD 검증은 미완료 상태입니다."));
  table($("capabilities"),data.capabilities,"실행 환경 정보가 제공되지 않았습니다.");

  const canvas=$("viewer"),ctx=canvas.getContext("2d");
  let vertices=[],triangles=[],center=[0,0,0],span=1,yaw=-0.62,pitch=0.58,zoom=1,active=-1,drag=null,queued=false;
  const rotation = p => {const x=p[0]*Math.cos(yaw)-p[1]*Math.sin(yaw),y=p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw);return [x,y*Math.cos(pitch)+p[2]*Math.sin(pitch),-y*Math.sin(pitch)+p[2]*Math.cos(pitch)];};
  function draw() {queued=false;if(!ctx)return;const rect=canvas.getBoundingClientRect(),w=Math.max(1,rect.width),h=Math.max(1,rect.height),dpr=Math.min(window.devicePixelRatio || 1,2);if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);if(!triangles.length)return;
    const scale=Math.min(w,h)*0.76*zoom/span;
    const projected=vertices.map(v=>v?rotation([v[0]-center[0],v[1]-center[1],v[2]-center[2]]):null);
    const faces=triangles.map(t=>{const a=projected[t[0]],b=projected[t[1]],c=projected[t[2]],u=[b[0]-a[0],b[1]-a[1],b[2]-a[2]],v=[c[0]-a[0],c[1]-a[1],c[2]-a[2]],n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],mag=Math.hypot(...n)||1;const light=0.42+0.58*Math.abs((n[0]*0.25-n[1]*0.45+n[2]*0.86)/mag);return {a,b,c,z:(a[2]+b[2]+c[2])/3,light};}).sort((a,b)=>a.z-b.z);
    for(const f of faces){ctx.beginPath();ctx.moveTo(w/2+f.a[0]*scale,h/2-f.a[1]*scale);ctx.lineTo(w/2+f.b[0]*scale,h/2-f.b[1]*scale);ctx.lineTo(w/2+f.c[0]*scale,h/2-f.c[1]*scale);ctx.closePath();const r=Math.round(42+56*f.light),g=Math.round(105+68*f.light),b=Math.round(119+65*f.light);ctx.fillStyle=`rgb(${r},${g},${b})`;ctx.fill();ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=0.42;ctx.stroke();}
    const axes=[[[1,0,0],"X","#bb6370"],[[0,1,0],"Y","#55957b"],[[0,0,1],"Z","#608bb2"]];ctx.font="11px Segoe UI, sans-serif";for(const [axis,label,color] of axes){const p=rotation(axis),x=42+p[0]*25,y=h-40-p[1]*25;ctx.beginPath();ctx.moveTo(42,h-40);ctx.lineTo(x,y);ctx.strokeStyle=color;ctx.lineWidth=1.8;ctx.stroke();ctx.fillStyle=color;ctx.fillText(label,x+4,y+3);}
  }
  const schedule=()=>{if(!queued){queued=true;requestAnimationFrame(draw);}};
  function select(index){active=index;const c=cases[index];document.querySelectorAll(".tab").forEach((tab,i)=>{tab.setAttribute("aria-selected",String(i===index));tab.tabIndex=i===index?0:-1;});if(!c){table($("parameters"),null);table($("metrics"),null);schedule();return;}
    $("case-name").textContent=c.name || "사례 "+(index+1);const status=String(c.status || "UNVERIFIED"),norm=status.toLowerCase(),scope=c.metrics&&c.metrics.verification_scope;$("case-status").textContent=(scope==="plan_roundtrip"?"저장·재생성 · ":"기하 검증 · ")+status+(scope==="plan_roundtrip"?" / 편집 과제 UNVERIFIED":"");$("case-status").className="badge "+(["pass","passed","ok","success"].includes(norm)?"pass":["fail","failed","error"].includes(norm)?"fail":["reject","rejected","unsupported","timeout"].includes(norm)?"warn":"");
    table($("parameters"),c.parameters);table($("metrics"),c.metrics,"기하 검사 수치가 제공되지 않았습니다.");$("artifacts").replaceChildren();for(const [key,text] of [["step","STEP 파일 열기"],["plan","모델 계획 열기"]]){const value=c.artifacts && c.artifacts[key],url=safeLink(value);if(url){const a=node("a",text,"file-link");a.href=url;$("artifacts").append(a);}}
    vertices=(Array.isArray(c.vertices)?c.vertices:[]).map(v=>Array.isArray(v)&&v.length>=3&&v.slice(0,3).every(x=>typeof x==="number"&&Number.isFinite(x))?v.slice(0,3):null);
    triangles=(Array.isArray(c.triangles)?c.triangles:[]).filter(t=>Array.isArray(t)&&t.length===3&&t.every(i=>Number.isInteger(i)&&i>=0&&i<vertices.length&&vertices[i]));
    const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const v of vertices){if(v)for(let d=0;d<3;d++){lo[d]=Math.min(lo[d],v[d]);hi[d]=Math.max(hi[d],v[d]);}}center=lo.map((x,d)=>(x+hi[d])/2);span=Math.max(...lo.map((x,d)=>hi[d]-x),1e-12);if(!Number.isFinite(span))span=1;
    $("no-mesh").hidden=!!triangles.length&&!!ctx;$("no-mesh").textContent=!ctx?"이 브라우저에서는 3D 미리보기를 표시할 수 없습니다.":"이 사례에는 미리 볼 유효한 메시가 없습니다. 오른쪽의 결과와 실패 기록을 확인하세요.";
    $("mesh-info").textContent=triangles.length?"실제 결과 메시 · 꼭짓점 "+vertices.filter(Boolean).length.toLocaleString()+"개 · 삼각형 "+triangles.length.toLocaleString()+"개":"메시 미제공 · 기하 성공으로 간주하지 않습니다.";yaw=-0.62;pitch=0.58;zoom=1;schedule();}
  cases.forEach((c,i)=>{const b=node("button",c.name || "사례 "+(i+1),"tab");b.type="button";b.setAttribute("role","tab");b.setAttribute("aria-controls","case-panel");b.addEventListener("click",()=>select(i));b.addEventListener("keydown",e=>{if(e.key==="ArrowRight"||e.key==="ArrowLeft"){e.preventDefault();const j=(i+(e.key==="ArrowRight"?1:-1)+cases.length)%cases.length;select(j);$("tabs").children[j].focus();}});$("tabs").append(b);});
  if(!cases.length)$("tabs").append(node("span","표시할 실행 사례가 없습니다.","tabs-empty"));
  canvas.addEventListener("pointerdown",e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,id:e.pointerId};canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener("pointermove",e=>{if(!drag||e.pointerId!==drag.id)return;yaw+=(e.clientX-drag.x)*0.008;pitch=Math.max(-Math.PI/2,Math.min(Math.PI/2,pitch+(e.clientY-drag.y)*0.008));drag.x=e.clientX;drag.y=e.clientY;schedule();});
  for(const event of ["pointerup","pointercancel","lostpointercapture"])canvas.addEventListener(event,()=>{drag=null;});
  canvas.addEventListener("wheel",e=>{e.preventDefault();zoom=Math.max(0.25,Math.min(5,zoom*Math.exp(-e.deltaY*0.001)));schedule();},{passive:false});
  canvas.addEventListener("keydown",e=>{if(["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","+","=","-"].includes(e.key)){e.preventDefault();if(e.key==="ArrowLeft")yaw-=0.12;if(e.key==="ArrowRight")yaw+=0.12;if(e.key==="ArrowUp")pitch=Math.min(Math.PI/2,pitch+0.12);if(e.key==="ArrowDown")pitch=Math.max(-Math.PI/2,pitch-0.12);if(e.key==="+"||e.key==="=")zoom=Math.min(5,zoom*1.2);if(e.key==="-")zoom=Math.max(0.25,zoom/1.2);schedule();}});
  document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>{const view=b.dataset.view;if(view==="in")zoom=Math.min(5,zoom*1.25);else if(view==="out")zoom=Math.max(0.25,zoom/1.25);else{zoom=1;if(view==="top"){yaw=0;pitch=0;}else if(view==="front"){yaw=0;pitch=Math.PI/2;}else{yaw=-0.62;pitch=0.58;}}schedule();}));
  if(typeof ResizeObserver!=="undefined")new ResizeObserver(schedule).observe(canvas.parentElement);else window.addEventListener("resize",schedule);
  select(cases.length?0:-1);
})();
</script>
</body>
</html>
'''
