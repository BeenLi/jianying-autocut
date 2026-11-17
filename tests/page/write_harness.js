// 临时验证脚本：用假 DOM / 假 db 跑页面脚本，检查失败重试的合并与永久错误不重试
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.split("<script>")[1].split("</script>")[0];
const listeners = {};
const app = { innerHTML: "", addEventListener: (t, f) => (listeners[t] = f) };
const calls = [];
let failNext = 0, permanent = false;
const docs = { S01: { chapter: "ch1", order: 1, desc: "x", done: false, note: "" } };
function ref(path) {
  const op = (kind) => async (data) => {
    calls.push({ path, kind, data });
    if (permanent) { const e = new Error("gone"); e.code = "invalid_argument"; throw e; }
    if (failNext > 0) { failNext--; const e = new Error("net"); e.code = "unavailable"; throw e; }
    calls[calls.length - 1].ok = true;
  };
  return { update: op("update"), set: op("set"), delete: op("delete") };
}
const snapCbs = {};
const db = { doc: ref, collection: (c) => ({ onSnapshot: (cb) => (snapCbs[c] = cb), add: async () => {} }) };
global.document = { getElementById: (id) => (id === "app" ? app : null), activeElement: null };
global.window = { claude: { use: async (n) => (n === "db" ? db : null) } };
global.setTimeout = (f) => 0; global.clearTimeout = () => {};
eval(src);
const tick = () => new Promise((r) => setImmediate(r));
(async () => {
  await tick(); await tick();
  const fire = (c, data) => snapCbs[c]({ docs: Object.entries(data).map(([id, d]) => ({ id, exists: true, data: () => d })), metadata: { fromCache: false } });
  fire("plan", { meta: { title: "t" } }); fire("chapters", { ch1: { order: 1, title: "c", function: "hook" } });
  fire("shots", docs); for (const c of ["clips", "matches", "extras", "requests"]) fire(c, {});
  failNext = 2;
  listeners.change({ target: { dataset: { act: "done", id: "S01" }, checked: true } });
  await tick(); await tick();
  listeners.input && listeners.input({ target: { id: "note-S01", value: "风大", dataset: { act: "note", id: "S01" } } });
  listeners.change({ target: { id: "note-S01", value: "风大", dataset: { act: "note", id: "S01" } } });
  await tick(); await tick();
  listeners.click({ target: { closest: () => ({ dataset: { act: "edit", id: "S01" } }) } });   // 任一操作触发重试
  await tick(); await tick();
  const ok = calls.filter((c) => c.path === "shots/S01" && c.ok);
  const merged = ok.some((c) => c.data.done === true) && ok.some((c) => c.data.note === "风大");
  // 永久错误：之后的操作不应再重试这个写入
  permanent = true; calls.length = 0;
  listeners.change({ target: { dataset: { act: "done", id: "S01" }, checked: false } });
  await tick(); await tick();
  permanent = false; const before = calls.length;
  listeners.click({ target: { closest: () => ({ dataset: { act: "edit", id: "S01" } }) } });
  await tick(); await tick();
  const noRetry = calls.length === before;
  console.log(JSON.stringify({ merged, noRetry }));
  process.exit(merged && noRetry ? 0 : 1);
})();
