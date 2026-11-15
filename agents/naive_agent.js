#!/usr/bin/env node
// BASELINE 3 - naive single-shot Node.js agent (subprocess adapter).
// Shows that agents in other languages plug in unchanged via the JSON-lines
// protocol. Deliberately minimal: no retries, no fallbacks. Any tool error ends
// the run with no answer. Reads only the structured `result` field.
const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin });
const waiting = [];
const buffered = [];
rl.on("line", (l) => { if (!l.trim()) return; const m = JSON.parse(l); waiting.length ? waiting.shift()(m) : buffered.push(m); });
const recv = () => new Promise((res) => (buffered.length ? res(buffered.shift()) : waiting.push(res)));
const send = (o) => process.stdout.write(JSON.stringify(o) + "\n");
let id = 0;
async function tool(name, args) {
  send({ type: "tool_call", id: ++id, name, args });
  const r = await recv();
  if (!r.ok) throw new Error(`${name}: ${r.error}`);
  return r.output.result;
}
const fmt = (x) => (Number.isInteger(+x) ? String(+x) : String(Math.round(+x * 1e4) / 1e4));

async function solve(t) {
  let m;
  if ((m = t.match(/Compute (.+?)\. Answer/))) return fmt(await tool("calculator", { expression: m[1] }));
  if ((m = t.match(/total price in USD of (\d+) units of SKU (\S+) and (\d+) units of SKU (\S+?)\?/))) {
    const a = await tool("lookup", { key: `sku:${m[2]}` });
    const b = await tool("lookup", { key: `sku:${m[4]}` });
    return fmt(await tool("calculator", { expression: `${m[1]}*${a.unit_price}+${m[3]}*${b.unit_price}` }));
  }
  if ((m = t.match(/unit price in USD of SKU (\S+?)\?/))) return fmt((await tool("lookup", { key: `sku:${m[1]}` })).unit_price);
  if ((m = t.match(/lines in (\S+) contain the word (\w+)/))) {
    const txt = await tool("read_file", { path: m[1] });
    return String(txt.split("\n").filter((l) => l.includes(m[2])).length);
  }
  if ((m = t.match(/city is (.+?) headquartered/))) {
    const docs = await tool("search", { query: `${m[1]} headquartered` });
    const h = docs[0].text.match(/headquartered in (\w+)/);
    return h ? h[1] : "unknown";
  }
  if ((m = t.match(/Convert ([\d.]+) (\w+) to (\w+), rounded to (\d+) decimal/)))
    return (await tool("convert", { value: +m[1], from_unit: m[2], to_unit: m[3] })).toFixed(+m[4]);
  if ((m = t.match(/Read (\S+) and return the email/))) {
    const o = JSON.parse(await tool("read_file", { path: m[1] }));
    return (await tool("lookup", { key: `customer:${o.customer_id}` })).email;
  }
  if ((m = t.match(/Read (\S+) and return the name of the person with the highest score/))) {
    const rows = (await tool("read_file", { path: m[1] })).trim().split("\n").slice(1).map((l) => l.split(","));
    return rows.reduce((best, r) => (+r[1] > +best[1] ? r : best))[0];
  }
  if ((m = t.match(/from (\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)/))) return String(await tool("date_diff", { start: m[1], end: m[2] }));
  if ((m = t.match(/Read (\S+?)\. Is every item in the order in stock/))) {
    const o = JSON.parse(await tool("read_file", { path: m[1] }));
    for (const it of o.items) if ((await tool("lookup", { key: `sku:${it.sku}` })).stock <= 0) return "no";
    return "yes";
  }
  if (t.includes("refund policy")) {
    const docs = await tool("search", { query: "refund policy" });
    const d = docs[0].text.match(/within (\d+) days/);
    return d ? d[1] : "unknown";
  }
  if ((m = t.match(/Reverse the string '([^']*)'/))) return [...m[1]].reverse().join("");
  return "I don't know";
}

(async () => {
  const task = await recv();
  let answer = null;
  try { answer = await solve(task.instruction); } catch (e) { send({ type: "log", message: `failed: ${e.message}` }); }
  send({ type: "final", answer });
  rl.close();
})();
