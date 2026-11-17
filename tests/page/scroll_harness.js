// 问题 1：点确认后左侧列表不跳回顶部；选中项不在可视范围时把它滚进来（只滚列表）
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.split("<script>")[1].split("</script>")[0];
const listeners = {};
let list = null, renders = 0;
const newList = () => {
  // 列表 400px 高，里面每项 40px；选中项的位置由 curIndex 决定（模拟真实布局）
  const l = { scrollTop: 0, clientHeight: 400, curIndex: 0,
    getBoundingClientRect: () => ({ top: 100 }),
    querySelector: (sel) => sel.includes("aria-current") ? { offsetHeight: 40,
      getBoundingClientRect: () => ({ top: 100 + l.curIndex * 40 - l.scrollTop }) } : null };
  return l;
};
const app = { _h: "", get innerHTML() { return this._h; }, set innerHTML(v) { this._h = v; renders++; list = v.includes('class="list"') ? newList() : null; if (list) list.curIndex = curIndex; },
  addEventListener: (t, f) => (listeners[t] = f), querySelector: (sel) => (sel === ".list" ? list : null) };
let curIndex = 0;
const els = {}, calls = [];
const ref = (path) => { const op = (kind) => async (data) => { calls.push({ path, kind, data }); }; return { update: op("update"), set: op("set"), delete: op("delete") }; };
const snapCbs = {};
const db = { doc: ref, collection: (c) => ({ onSnapshot: (cb) => (snapCbs[c] = cb), add: async () => {} }) };
global.document = { getElementById: (id) => (id === "app" ? app : (els[id] = els[id] || { id, value: "" })), activeElement: null };
global.window = { claude: { use: async (n) => (n === "db" ? db : null) } };
global.setTimeout = () => 0; global.clearTimeout = () => {};
eval(src);
const tick = () => new Promise((r) => setImmediate(r));
const click = (dataset) => listeners.click({ target: { closest: () => ({ dataset }) } });
const fire = (c, data) => snapCbs[c] && snapCbs[c]({ docs: Object.entries(data).map(([id, d]) => ({ id, exists: true, data: () => d })), metadata: { fromCache: false } });
const R = {};
(async () => {
  await tick(); await tick();
  const shots = {}, matches = {};
  for (let i = 1; i <= 30; i++) { const id = "S" + String(i).padStart(2, "0"); shots[id] = { chapter: "ch1", order: i, desc: "镜头" + i }; matches[id] = { clip_id: "c001", at: 5, confirmed: false, by: "claude" }; }
  fire("plan", { meta: { title: "t", stage: "editing" } });
  fire("chapters", { ch1: { order: 1, title: "c", function: "setup" } });
  fire("shots", shots); fire("clips", { c001: { duration: 60, thumbs: [] } }); fire("matches", matches);
  for (const c of ["extras", "requests", "lines", "nmatch"]) fire(c, {});
  // 用户把列表滚到 500px，选中第 15 个镜头（在可视范围 500–900 里），点确认，数据库推回新快照
  curIndex = 14; click({ act: "sel", id: "S15" }); await tick();
  list.scrollTop = 500;
  click({ act: "confirm", id: "S15" }); await tick();
  fire("matches", Object.assign({}, matches, { S15: Object.assign({}, matches.S15, { confirmed: true }) })); await tick();
  R.keepsScroll = list && list.scrollTop === 500;
  // 选中项在可视范围外（第 28 个，在 1080px）：只滚列表把它带进来
  curIndex = 27; click({ act: "sel", id: "S28" }); await tick();
  const top = 27 * 40;
  R.bringsSelectedIntoView = list && top >= list.scrollTop && top + 40 <= list.scrollTop + list.clientHeight;
  // 用户自己把清单滚开（选中项 S28 不在视野里），数据库推新快照触发重绘：不要把清单拽回选中项
  list.scrollTop = 0;
  fire("matches", Object.assign({}, matches, { S02: Object.assign({}, matches.S02, { confirmed: true }) })); await tick();
  R.noYankBack = list && list.scrollTop === 0;
  console.log(JSON.stringify(R));
  process.exit(Object.values(R).every(Boolean) ? 0 : 1);
})();
