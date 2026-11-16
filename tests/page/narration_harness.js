// 旁白稿 / 录音稿 / 旁白片剪辑视图的验证：假 DOM + 假 db 跑页面脚本
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.split("<script>")[1].split("</script>")[0];
const listeners = {};
const app = { innerHTML: "", addEventListener: (t, f) => (listeners[t] = f) };
const els = {};
const calls = [];
function ref(path) {
  const op = (kind) => async (data) => { calls.push({ path, kind, data }); };
  return { update: op("update"), set: op("set"), delete: op("delete") };
}
const snapCbs = {};
const db = { doc: ref, collection: (c) => ({ onSnapshot: (cb) => (snapCbs[c] = cb), add: async () => {} }) };
global.document = { getElementById: (id) => (id === "app" ? app : (els[id] = els[id] || { id, value: "" })), activeElement: null };
global.window = { claude: { use: async (n) => (n === "db" ? db : null) } };
global.setTimeout = () => 0; global.clearTimeout = () => {};
eval(src);
const tick = () => new Promise((r) => setImmediate(r));
const click = (dataset) => listeners.click({ target: { closest: () => ({ dataset }) } });
const fire = (c, data) => snapCbs[c] && snapCbs[c]({ docs: Object.entries(data).map(([id, d]) => ({ id, exists: true, data: () => d })), metadata: { fromCache: false } });
const results = {};
(async () => {
  await tick(); await tick();
  // 0. 旧数据（没有 lines / nmatch）照常渲染
  fire("plan", { meta: { title: "t" } });
  fire("chapters", { ch1: { order: 1, title: "出发", function: "hook" } });
  fire("shots", { S01: { chapter: "ch1", order: 1, desc: "山脚的灯", duration: 6, done: false, note: "" } });
  for (const c of ["clips", "matches", "extras", "requests"]) fire(c, {});
  results.oldDataRenders = app.innerHTML.includes("山脚的灯");

  // 1. 加一句旁白
  fire("lines", {}); fire("nmatch", {});
  click({ act: "add-line", ch: "ch1" });
  await tick();
  const add = calls.find((c) => c.path === "lines/L01" && c.kind === "set");
  results.addLine = !!add && add.data.chapter === "ch1" && add.data.kind === "narr" && Array.isArray(add.data.edited_by_user);

  // 2. 编辑中的旁白稿在数据库推送后不丢
  fire("lines", { L01: { chapter: "ch1", order: 1, kind: "narr", text: "凌晨四点出发", shots: ["S01"], est_s: 20 } });
  click({ act: "edit-line", id: "L01" });
  listeners.input({ target: { id: "lt-L01", value: "凌晨四点，我们出发", dataset: {} } });
  (els["lt-L01"] = els["lt-L01"] || { value: "" }).value = "";
  fire("shots", { S01: { chapter: "ch1", order: 1, desc: "山脚的灯", duration: 6, done: true, note: "" } });
  results.draftKept = els["lt-L01"].value === "凌晨四点，我们出发";

  // 3. 保存：只写改了的字段，记进 edited_by_user
  click({ act: "save-line", id: "L01" });
  await tick();
  const save = calls.find((c) => c.path === "lines/L01" && c.kind === "update");
  results.saveLine = !!save && save.data.text === "凌晨四点，我们出发" && save.data.edited_by_user.includes("text");

  // 4. 旁白比画面长很多时提示
  results.imbalanceHint = app.innerHTML.includes("旁白比画面长");

  // 5. 录音稿视图
  click({ act: "view", v: "script" });
  results.teleprompter = app.innerHTML.includes("凌晨四点出发") && app.innerHTML.includes("prompter");

  // 6. 旁白片剪辑视图：确认、跳过、恢复
  fire("plan", { meta: { title: "t", kind: "narration", stage: "editing" } });
  fire("nmatch", { L01: { file: "n1", start: 1, end: 4, visuals: [{ clip_id: "c001", at: 12 }], confirmed: false, by: "claude", reason: "灯" },
                   X01: { chapter: "ch1", order: 2, text: "嗯这个录上了吗", file: "n1", start: 5, end: 6, skip: true, skip_reason: "稿外：口误或闲聊", visuals: [] } });
  click({ act: "view", v: "edit" });
  results.editListsLines = app.innerHTML.includes("凌晨四点出发") && app.innerHTML.includes("嗯这个录上了吗");
  click({ act: "sel", id: "L01" });
  click({ act: "confirm-n", id: "L01" });
  await tick();
  results.confirm = calls.some((c) => c.path === "nmatch/L01" && c.data.confirmed === true && c.data.by === "user");
  click({ act: "skip-n", id: "L01", v: "1" });
  await tick();
  results.skip = calls.some((c) => c.path === "nmatch/L01" && c.data.skip === true);
  click({ act: "sel", id: "X01" });
  click({ act: "skip-n", id: "X01", v: "0" });
  await tick();
  results.restore = calls.some((c) => c.path === "nmatch/X01" && c.data.skip === false);

  console.log(JSON.stringify(results));
  process.exit(Object.values(results).every(Boolean) ? 0 : 1);
})();
