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


  // ---------- Task 8：效果卡片 ----------
  const TRX = { type: "叠化", dur: 0.6, reason: "第二天一早", vip: false, confirmed: false, by: "claude" };
  fire("nmatch", base([{ clip_id: "c001", filter: { type: "夏日风吟", intensity: 60, confirmed: false, by: "claude", vip: true } }],
                      { transition: TRX, effect: { type: "冲击波", vip: null, confirmed: false, by: "claude" } }));
  click({ act: "sel", id: "L01" });
  const H = () => app.innerHTML;
  R.cardsRender = H().includes("叠化") && H().includes("0.6s") && H().includes("第二天一早") && H().includes("待确认")
    && H().includes("会员") && H().includes("会员？") && H().includes("夏日风吟") && H().includes("强度 60");
  R.listMarker = H().includes("✦") && H().includes("fx-todo");

  calls.length = 0;
  click({ act: "fx-confirm", kind: "transition", id: "L01" }); await tick();
  const cw = calls.find((c) => c.path === "nmatch/L01" && c.data.transition);
  R.confirmWrites = !!cw && cw.data.transition.confirmed === true && cw.data.transition.by === "user"
    && cw.data.transition.type === "叠化" && Object.keys(cw.data).length === 1;

  calls.length = 0;
  click({ act: "fx-edit", kind: "transition", id: "L01" });
  R.editFormShown = H().includes('id="fx-type-L01-transition"') && H().includes('id="fx-dur-L01-transition"');
  els["fx-type-L01-transition"] = { value: "闪白" }; els["fx-dur-L01-transition"] = { value: "0.8" };
  click({ act: "fx-save", kind: "transition", id: "L01" }); await tick();
  const ew = calls.find((c) => c.path === "nmatch/L01" && c.data.transition);
  R.editWrites = !!ew && ew.data.transition.type === "闪白" && ew.data.transition.dur === 0.8
    && ew.data.transition.confirmed === true && ew.data.transition.vip === null && ew.data.transition.reason === "第二天一早";

  // 全部确认后，清单上的标记不再是黄色
  fire("nmatch", base([{ clip_id: "c001", filter: { type: "夏日风吟", intensity: 60, confirmed: true, by: "user" } }],
                      { transition: { ...TRX, confirmed: true, by: "user" }, effect: { type: "冲击波", confirmed: true, by: "user" } }));
  // 左侧图例里本来就有「待确认 N」，所以看卡片本身的样式
  R.confirmedAfterSnapshot = (H().match(/class="fx"/g) || []).length === 3 && !H().includes('class="fx todo"')
    && H().includes("✦") && !H().includes("fx-todo");

  calls.length = 0;
  click({ act: "fx-remove", kind: "transition", id: "L01" }); await tick();
  R.removeWritesNull = calls.some((c) => c.path === "nmatch/L01" && "transition" in c.data && c.data.transition === null);

  // 去掉滤镜：写出的画面对象里 filter 是 null；失败后马上勾「消音」再重试，滤镜不会复活
  const withFilt = base([{ clip_id: "c001", filter: FILT }]);
  fire("nmatch", withFilt);
  failOnce.add("nmatch/L01");
  click({ act: "fx-remove", kind: "filter", id: "L01", i: "0" }); await tick();   // 失败
  fire("nmatch", withFilt);                                                     // 旧快照
  calls.length = 0;
  change("L01", "mute", 0, true); await tick();
  const vs = calls.filter((c) => c.path === "nmatch/L01" && c.data.visuals);
  R.removeFilterNoResurrection = vs.length > 0 && vs.every((c) => c.data.visuals[0].filter === null) && vs[vs.length - 1].data.visuals[0].mute === true;

  // 片头 / 片尾：在剪辑视图顶部，分别写进 plan/meta，互不覆盖
  fire("plan", { meta: { title: "t", kind: "narration", stage: "editing", intro: { type: "渐显", confirmed: false, by: "claude" },
                         outro: { type: "渐隐", confirmed: false, by: "claude" } } });
  R.introOutroRender = H().includes("片头") && H().includes("渐显") && H().includes("片尾") && H().includes("渐隐");
  calls.length = 0;
  click({ act: "fx-confirm", kind: "intro", meta: "1" }); await tick();
  const mw = calls.find((c) => c.path === "plan/meta");
  R.introOutroSeparate = !!mw && mw.data.intro.confirmed === true && !("outro" in mw.data) && Object.keys(mw.data).length === 1;

  // 旧数据：没有任何效果字段，照常渲染，不出现标记和卡片
  fire("plan", { meta: { title: "t", kind: "narration", stage: "editing" } });
  fire("nmatch", base([{ clip_id: "c001", at: 12 }]));
  R.oldDataRenders = H().includes("凌晨四点出发") && !H().includes("✦") && !H().includes('class="fx ');
  console.log(JSON.stringify(R));
  process.exit(Object.values(R).every(Boolean) ? 0 : 1);
})();
