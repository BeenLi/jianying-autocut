// 旁白片的状态显示：画面留空 = 延续上一镜头；录音稿标出待录、顶部显示录音进度
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.split("<script>")[1].split("</script>")[0];
const listeners = {};
const app = { innerHTML: "", addEventListener: (t, f) => (listeners[t] = f) };
const els = {};
function ref() {
  const op = () => async () => {};
  return { update: op(), set: op(), delete: op() };
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
const dotOf = (id) => ((app.innerHTML.match(new RegExp(`data-id="${id}"[^>]*><span class="dot (\\w+)"`)) || [])[1]);
const results = {};
(async () => {
  await tick(); await tick();
  fire("plan", { meta: { title: "t", kind: "narration", stage: "editing" } });
  fire("chapters", { ch1: { order: 1, title: "出发", function: "hook" } });
  fire("shots", { S01: { chapter: "ch1", order: 1, desc: "山脚", duration: 6, done: true, note: "" } });
  fire("clips", { c001: { desc: "山脚的灯", duration: 30 }, c005: { desc: "被跳过的画面", duration: 30 } });
  for (const c of ["matches", "extras", "requests"]) fire(c, {});
  fire("lines", {
    L01: { chapter: "ch1", order: 1, kind: "narr", text: "凌晨四点出发", shots: [] },
    V01: { chapter: "ch1", order: 2, kind: "live", text: "原声：到了", shots: [] },
    L02: { chapter: "ch1", order: 4, kind: "narr", text: "一路往上爬", shots: [] },
    L03: { chapter: "ch1", order: 5, kind: "narr", text: "还没想好画面", shots: [] },
    L04: { chapter: "ch1", order: 6, kind: "narr", text: "这句还没录", shots: [] },
  });
  fire("nmatch", {
    L01: { file: "n1", start: 1, end: 4, visuals: [{ clip_id: "c001", at: 12 }], confirmed: true, by: "claude" },
    V01: { file: "n1", start: 5, end: 8, visuals: [], confirmed: true, by: "claude" },
    X01: { chapter: "ch1", order: 3, text: "口误", file: "n1", start: 9, end: 10, skip: true, visuals: [{ clip_id: "c005" }] },
    L02: { file: "n1", start: 11, end: 14, visuals: [], confirmed: true, by: "claude" },
    L03: { file: "n1", start: 15, end: 18, visuals: [], confirmed: false, by: "claude" },
  });

  // 1. 确认过的空画面 = 延续上一镜头（绿点），往前跳过原声和被跳过的句子，找到 c001
  click({ act: "view", v: "edit" });
  results.carriedIsOk = dotOf("L02") === "ok";
  click({ act: "sel", id: "L02" });
  results.carriedLabel = app.innerHTML.includes("延续上一镜头");
  results.carriedClip = app.innerHTML.includes("延续 c001") && !app.innerHTML.includes("延续 c005");
  // 没确认的空画面仍然是红点
  results.unconfirmedEmptyIsBad = dotOf("L03") === "bad";

  // 2. 录音稿：待录的句子标出来，原声行不算
  click({ act: "view", v: "script" });
  const h = app.innerHTML;
  results.todoTagged = /class="say todo"><span class="todo-tag">待录<\/span>这句还没录/.test(h);
  results.recordedNotTagged = !/todo-tag">待录<\/span>凌晨四点出发/.test(h);
  results.summary = h.includes("还有 <b class=\"mono\">1</b> 句待录") && h.includes("1 出发（1 句）");
  // 顶部：已录 3/4（原声 V01 不计），进度条按录音算，不是拍摄的 100%
  results.headerCount = h.includes("已录 <b class=\"mono\">3/4</b>");
  results.progressByRecording = h.includes('style="width:75.0%"');

  // 录音之前（nmatch 为空）整份稿子都没录，不标黄也不出汇总
  fire("nmatch", {});
  results.noMarksBeforeRecording = !app.innerHTML.includes("todo-tag") && !app.innerHTML.includes("句待录");

  // 3. 全部录完
  fire("nmatch", {
    L01: { file: "n1", start: 1, end: 4, visuals: [{ clip_id: "c001" }], confirmed: true },
    L02: { file: "n1", start: 11, end: 14, visuals: [], confirmed: true },
    L03: { file: "n1", start: 15, end: 18, visuals: [], confirmed: true },
    L04: { file: "n1", start: 19, end: 22, visuals: [], confirmed: true },
  });
  results.allRecorded = app.innerHTML.includes("所有旁白都录好了") && !app.innerHTML.includes("todo-tag");

  console.log(JSON.stringify(results));
  process.exit(Object.values(results).every(Boolean) ? 0 : 1);
})();
