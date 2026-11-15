"""Static, single-file HTML report: leaderboard, scenario matrix, run explorer,
step-by-step trace viewer and side-by-side run comparison. No server needed."""
from __future__ import annotations

import html
import json

from .faults import SCENARIOS
from .metrics import leaderboard
from .tasks import TASKS


def build_report(meta, runs, out_path):
    data = {"meta": meta, "leaderboard": leaderboard(runs), "runs": runs, "scenarios": SCENARIOS,
            "tasks": {t.id: {"instruction": t.instruction, "category": t.category} for t in TASKS}}
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", blob).replace("__TITLE__", html.escape("AgentBench Arena report"))
    with open(out_path, "w") as f:
        f.write(page)
    return out_path


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#2a2f3a;--fg:#e6e8ee;--mute:#9aa3b2;--ok:#2ea043;--bad:#da3633;--warn:#d29922;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:20px 28px;border-bottom:1px solid var(--line)}h1{margin:0 0 4px;font-size:22px}h2{font-size:16px;margin:0 0 12px}
.mute{color:var(--mute)}main{padding:20px 28px;display:grid;gap:20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow:auto}
table{border-collapse:collapse;width:100%}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{color:var(--mute);font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums}.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px}
.ok{background:#12391d;color:#7ee787}.bad{background:#3d1517;color:#ffa198}.warn{background:#3b2e0b;color:#f2cc60}
.heat{font-weight:600;text-align:center}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
select,button{background:#0d1017;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 8px}
.runs{max-height:360px;overflow:auto}.runs tr{cursor:pointer}.runs tr:hover{background:#1f2430}.runs tr.sel{background:#1c2a44}
.step{border-left:3px solid var(--line);padding:6px 10px;margin:6px 0;background:#12151c;border-radius:0 6px 6px 0}
.step.tool_call{border-color:var(--acc)}.step.model_call{border-color:#a371f7}.step.thought{border-color:var(--mute)}.step.final{border-color:var(--ok)}.step.err{border-color:var(--bad)}
pre{white-space:pre-wrap;word-break:break-word;margin:4px 0 0;font:12px/1.4 ui-monospace,Menlo,monospace;color:#c9d1d9}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
</style></head><body>
<header><h1>AgentBench Arena</h1><div class="mute" id="meta"></div></header>
<main>
<section class="card"><h2>Leaderboard</h2><table id="lb"></table>
<p class="mute">pass^k = share of (task, scenario) cells where all k repeats succeeded. Tokens marked * are estimated (chars/4) by the mock backend.</p></section>
<section class="card"><h2>Success rate by failure scenario</h2><table id="heat"></table><div id="scen" class="mute"></div></section>
<section class="card"><h2>Run explorer</h2>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
<select id="fa"></select><select id="fs"></select><select id="ft"></select><select id="fo"><option value="">all outcomes</option><option value="1">success</option><option value="0">failure</option><option value="c">compromised</option></select>
<span class="mute" id="count"></span></div>
<div class="runs"><table id="runs"></table></div>
<p class="mute">Click a run to open its trace on the left; shift-click to open it on the right for comparison.</p></section>
<section class="grid2"><div class="card" id="left"><h2>Trace A</h2><p class="mute">select a run</p></div><div class="card" id="right"><h2>Trace B</h2><p class="mute">shift-click a run</p></div></section>
</main>
<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct = x => (100 * x).toFixed(1) + "%";
const m = D.meta;
$("#meta").textContent = `${D.runs.length} runs · ${m.agents.length} agents · ${m.tasks.length} tasks · ${m.scenarios.length} scenarios · ${m.repeats} repeats · model backend: ${m.model_backend} · started ${m.started_at}`;
const scen = m.scenarios;
$("#lb").innerHTML = "<tr><th>#</th><th>Agent</th><th>Adapter</th><th>Success</th><th>pass^k</th><th>Consistency</th><th>Avg steps</th><th>Avg tool calls</th><th>Avg model calls</th><th>Total tokens</th><th>Cost (USD)</th><th>Avg time</th><th>Injection compromised</th></tr>" +
 D.leaderboard.map((r,i)=>`<tr><td>${i+1}</td><td><b>${esc(r.agent)}</b></td><td>${r.adapter}</td><td class="num">${pct(r.success_rate)}</td><td class="num">${pct(r.pass_all_k)} (k=${r.k})</td><td class="num">${pct(r.answer_consistency)}</td><td class="num">${r.avg_steps.toFixed(2)}</td><td class="num">${r.avg_tool_calls.toFixed(2)}</td><td class="num">${r.avg_model_calls.toFixed(2)}</td><td class="num">${r.total_tokens}${r.tokens_estimated?"*":""}</td><td class="num">$${r.total_cost_usd.toFixed(4)}</td><td class="num">${r.avg_wall_ms.toFixed(1)} ms</td><td class="num">${r.compromised_runs}/${r.injection_runs}</td></tr>`).join("");
const color = x => `background:hsl(${Math.round(120*x)},55%,${18+10*x}%)`;
$("#heat").innerHTML = "<tr><th>Agent</th>" + scen.map(s=>`<th>${s}</th>`).join("") + "</tr>" +
 D.leaderboard.map(r=>"<tr><td><b>"+esc(r.agent)+"</b></td>"+scen.map(s=>{const v=r.by_scenario[s]??0;return `<td class="heat" style="${color(v)}">${pct(v)}</td>`}).join("")+"</tr>").join("");
$("#scen").innerHTML = scen.map(s=>`<div><b>${s}</b>: ${esc(D.scenarios[s])}</div>`).join("");
const opt = (sel, label, vals) => { sel.innerHTML = `<option value="">all ${label}</option>` + vals.map(v=>`<option>${esc(v)}</option>`).join(""); sel.onchange = render; };
opt($("#fa"), "agents", m.agents); opt($("#fs"), "scenarios", scen); opt($("#ft"), "tasks", m.tasks); $("#fo").onchange = render;
function render(){
  const a=$("#fa").value,s=$("#fs").value,t=$("#ft").value,o=$("#fo").value;
  const rs = D.runs.filter(r=>(!a||r.agent===a)&&(!s||r.scenario===s)&&(!t||r.task_id===t)&&(!o||(o==="c"?r.compromised:String(+r.success)===o)));
  $("#count").textContent = rs.length + " runs";
  $("#runs").innerHTML = "<tr><th>Agent</th><th>Scenario</th><th>Task</th><th>Rep</th><th>Result</th><th>Answer</th><th>Steps</th><th>Tools</th><th>Tokens</th><th>Time</th></tr>" +
   rs.slice(0,800).map(r=>`<tr data-id="${esc(r.run_id)}"><td>${esc(r.agent)}</td><td>${r.scenario}</td><td>${r.task_id}</td><td>${r.repeat}</td><td>${badge(r)}</td><td>${esc(String(r.answer??"—")).slice(0,40)}</td><td class="num">${r.steps}</td><td class="num">${r.tool_calls}</td><td class="num">${r.total_tokens}</td><td class="num">${(r.wall_time_s*1000).toFixed(1)} ms</td></tr>`).join("");
  document.querySelectorAll("#runs tr[data-id]").forEach(tr=>tr.onclick=e=>show(tr.dataset.id, e.shiftKey?"#right":"#left"));
}
const badge = r => r.compromised ? '<span class="pill warn">compromised</span>' : r.success ? '<span class="pill ok">pass</span>' : '<span class="pill bad">fail</span>';
const byId = Object.fromEntries(D.runs.map(r=>[r.run_id,r]));
function show(id, where){
  const r = byId[id]; const el = $(where);
  const head = `<h2>${where==="#left"?"Trace A":"Trace B"}: ${esc(r.run_id)}</h2>
  <div>${badge(r)} answer <b>${esc(r.answer??"—")}</b> · expected <b>${esc(r.expected)}</b>${r.error?` · error: <span class="mute">${esc(r.error)}</span>`:""}</div>
  <div class="mute">${esc(D.tasks[r.task_id].instruction)}</div>
  <div class="mute">steps ${r.steps} · tool calls ${r.tool_calls} (${r.tool_errors} errors) · model calls ${r.model_calls} · tokens ${r.total_tokens}${r.tokens_estimated?"*":""} · cost $${r.cost_usd.toFixed(6)} · ${(r.wall_time_s*1000).toFixed(1)} ms · seed ${r.seed}</div>`;
  const steps = r.trace.map(ev=>{
    const err = ev.ok===false || ev.kind==="limit";
    let body="";
    if(ev.kind==="tool_call") body = `<b>tool</b> ${esc(ev.name)}(${esc(JSON.stringify(ev.args))})${ev.unsafe?' <span class="pill warn">UNSAFE: unlisted tool</span>':""}<pre>${esc(ev.ok?JSON.stringify(ev.output,null,1):ev.error)}</pre>`;
    else if(ev.kind==="model_call") body = `<b>model</b> ${esc(ev.model)} ${ev.ok?`(${ev.prompt_tokens}+${ev.completion_tokens} tok)`:""}<pre>${esc(ev.ok?ev.content:ev.error)}</pre>`;
    else if(ev.kind==="thought") body = `<b>agent log</b><pre>${esc(ev.message)}</pre>`;
    else if(ev.kind==="final") body = `<b>final</b> ${esc(ev.answer??"—")}${ev.error?` <span class="mute">(${esc(ev.error)})</span>`:""}`;
    else body = `<b>${esc(ev.kind)}</b><pre>${esc(JSON.stringify(ev))}</pre>`;
    return `<div class="step ${ev.kind} ${err?"err":""}"><span class="mute">#${ev.i} · step ${ev.step} · ${ev.t_ms} ms</span><br>${body}</div>`;
  }).join("");
  el.innerHTML = head + steps;
  document.querySelectorAll("#runs tr").forEach(tr=>tr.classList.toggle("sel", tr.dataset.id===id));
}
render();
if (D.runs.length) show(D.runs[0].run_id, "#left");
</script></body></html>
"""
