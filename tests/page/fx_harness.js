// 旁白片的效果：visuals 的本地待定副本、效果卡片（假 DOM + 假 db 跑页面脚本；db 写入可以按路径让它失败一次）
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.split("<script>")[1].split("</script>")[0];
const listeners = {};
const app = { innerHTML: "", addEventListener: (t, f) => (listeners[t] = f) };
const els = {};
const calls = [];
const failOnce = new Set();
function ref(path) {
  const op = (kind) => async (data) => {
    if (failOnce.has(path)) { failOnce.delete(path); throw { code: "unavailable" }; }
    calls.push({ path, kind, data: JSON.parse(JSON.stringify(data)) });
  };
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
const change = (id, f, i, checked) => listeners.change({ target: { id: `v${f[0]}-${id}-${i}`, type: "checkbox", checked, dataset: { act: "vflag-n", id, i: String(i), f } } });
const fire = (c, data) => snapCbs[c] && snapCbs[c]({ docs: Object.entries(data).map(([id, d]) => ({ id, exists: true, data: () => d })), metadata: { fromCache: false } });
const lastVis = (id) => { const w = [...calls].reverse().find((c) => c.path === "nmatch/" + id && c.data && c.data.visuals); return w && w.data.visuals; };
const FILT = { type: "夏日风吟", intensity: 60, reason: "回忆", confirmed: true, by: "user" };
const base = (visuals, extra = {}) => ({ L01: { file: "n1", start: 1, end: 4, visuals, confirmed: true, by: "user", ...extra } });
const R = {};
(async () => {
  await tick(); await tick();
  fire("plan", { meta: { title: "t", kind: "narration", stage: "editing" } });
  fire("chapters", { ch1: { order: 1, title: "出发", function: "hook" } });
  for (const c of ["shots", "clips", "matches", "extras", "requests"]) fire(c, {});
  fire("lines", { L01: { chapter: "ch1", order: 1, kind: "narr", text: "凌晨四点出发" } });
  fire("nmatch", base([{ clip_id: "c001", at: 12, filter: FILT }]));
  click({ act: "view", v: "edit" });
  click({ act: "sel", id: "L01" });

  const reassign = async (clip, at) => {
    els["n-clip-L01"] = { id: "n-clip-L01", value: clip }; els["n-at-L01"] = { id: "n-at-L01", value: at };
    click({ act: "reassign-n", id: "L01" });
    await tick();
    return (lastVis("L01") || [])[0];
  };

  // 1. 换画面：同一素材只改秒数保留滤镜；换素材清掉滤镜、重复用、消音
  let v = await reassign("c001", "15");
  R.reassignSameClipKeepsFilter = !!v && v.at === 15 && v.filter && v.filter.type === "夏日风吟";
  fire("nmatch", base([{ clip_id: "c001", at: 12, filter: FILT, mute: true, reuse: true }]));
  v = await reassign("c002", "");
  R.reassignOtherClipClears = !!v && v.clip_id === "c002" && !("filter" in v) && !("mute" in v) && !("reuse" in v);

  // 2. 勾「消音」不丢滤镜
  fire("nmatch", base([{ clip_id: "c001", at: 12, filter: FILT }]));
  change("L01", "mute", 0, true); await tick();
  v = (lastVis("L01") || [])[0];
  R.muteKeepsFilter = !!v && v.mute === true && v.filter && v.filter.intensity === 60;

  // 3. 写入失败、快照还是旧的：下一次操作从待定副本出发，去掉的东西不会复活
  fire("nmatch", base([{ clip_id: "c001", at: 12, filter: FILT, mute: true }]));
  failOnce.add("nmatch/L01");
  change("L01", "mute", 0, false); await tick();       // 取消消音：写入失败
  fire("nmatch", base([{ clip_id: "c001", at: 12, filter: FILT, mute: true }]));   // 旧快照又推了一次
  calls.length = 0;
  change("L01", "reuse", 0, true); await tick();       // 马上勾「允许重复用」，失败的那次一起重试
  R.noResurrection = calls.filter((c) => c.path === "nmatch/L01" && c.data.visuals).length > 0
    && calls.every((c) => c.path !== "nmatch/L01" || !c.data.visuals || !c.data.visuals[0].mute)
    && lastVis("L01")[0].reuse === true;

  // 4. 快照迟迟不来：连续两次操作，后一次基于前一次的结果
  fire("nmatch", base([{ clip_id: "c003" }]));
  failOnce.add("nmatch/L01");                            // 第一次写入失败 → 待定副本不会因为「已落地」被清掉
  change("L01", "reuse", 0, true); await tick();
  change("L01", "mute", 0, true); await tick();
  v = (lastVis("L01") || [])[0];
  R.chainedOpsWithStaleSnapshot = !!v && v.reuse === true && v.mute === true;

  // 5. 快照和待定副本内容一样、只是键的顺序不同：认作一致，清掉待定副本
  fire("nmatch", base([{ clip_id: "c004", at: 3 }]));
  failOnce.add("nmatch/L01");
  change("L01", "mute", 0, true); await tick();          // 失败：待定副本 = [{clip_id, at, mute}]
  fire("nmatch", base([{ mute: true, at: 3, clip_id: "c004" }]));   // 服务器其实已经有了，键顺序不同
  fire("nmatch", base([{ clip_id: "c004", at: 20, mute: true }]));  // 之后 Claude 改了秒数
  calls.length = 0;
  change("L01", "reuse", 0, true); await tick();
  v = (lastVis("L01") || [])[0];
  R.pendingClearedOnReorderedSnapshot = !!v && v.at === 20 && v.reuse === true;

  console.log(JSON.stringify(R));
  process.exit(Object.values(R).every(Boolean) ? 0 : 1);
})();
