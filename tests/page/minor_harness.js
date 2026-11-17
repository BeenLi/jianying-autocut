// A3 时间解析 / A6 改素材清掉旧理由
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.split("<script>")[1].split("</script>")[0];
const listeners = {};
const app = { innerHTML: "", addEventListener: (t, f) => (listeners[t] = f) };
const els = {};
const calls = [];
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
  fire("plan", { meta: { title: "t", stage: "editing" } });
  fire("chapters", { ch1: { order: 1, title: "c", function: "hook" } });
  fire("shots", { S01: { chapter: "ch1", order: 1, desc: "x" } });
  fire("clips", { c001: { duration: 7200, thumbs: [] } });
  fire("matches", { S01: { clip_id: "c001", at: 5, confirmed: false, reason: "Claude 的理由", confidence: "high", by: "claude" } });
  for (const c of ["extras", "requests", "lines", "nmatch"]) fire(c, {});
  // 1:05:00 → 3900
  els["m-clip-S01"] = { value: "c001" }; els["m-at-S01"] = { value: "1:05:00", setCustomValidity() {}, reportValidity() {} };
  click({ act: "reassign", id: "S01" }); await tick();
  const w = calls.find((c) => c.path === "matches/S01");
  R.hms = !!w && w.data.at === 3900;
  R.clearsReason = !!w && w.data.reason === "" && w.data.confidence === null;
  // 空白不是 0
  calls.length = 0;
  els["m-at-S01"].value = "   ";
  click({ act: "reassign", id: "S01" }); await tick();
  R.blankRejected = calls.length === 0;
  els["m-at-S01"].value = "1:";
  click({ act: "reassign", id: "S01" }); await tick();
  R.halfRejected = calls.length === 0;
  // 旁白片换画面也清掉旧理由；空白 at = 不指定
  fire("plan", { meta: { title: "t", stage: "editing", kind: "narration" } });
  fire("lines", { L01: { chapter: "ch1", order: 1, kind: "narr", text: "出发" } });
  fire("nmatch", { L01: { file: "n1", start: 1, end: 3, visuals: [{ clip_id: "c001", at: 4 }], reason: "旧理由", confidence: "mid" } });
  els["n-clip-L01"] = { value: "c001" }; els["n-at-L01"] = { value: "  ", setCustomValidity() {}, reportValidity() {} };
  click({ act: "reassign-n", id: "L01" }); await tick();
  const n = calls.find((c) => c.path === "nmatch/L01");
  R.narrBlankMeansNoAt = !!n && n.data.visuals.length === 1 && !("at" in n.data.visuals[0]);
  R.narrClearsReason = !!n && n.data.reason === "" && n.data.confidence === null;
  console.log(JSON.stringify(R));
  process.exit(Object.values(R).every(Boolean) ? 0 : 1);
})();
