// 共通Adapterだけを呼ぶ最小入口。業務検証・集計はエンジンの結果を使う。
let adapterRecord = null, adapterToken = 0, adapterController = null;
const adapterStatus = text => { $("adapter-status").textContent = text; };
const adapterButtons = ["adapter-confirm", "adapter-check", "adapter-run", "adapter-load", "adapter-import", "adapter-split", "adapter-file", "adapter-reverify"];

function adapterBusy(value) {
  adapterButtons.forEach(id => { $(id).disabled = value || (id === "adapter-reverify" && !adapterRecord); });
}

function adapterEdited() {
  adapterToken++;
  adapterController?.abort();
  adapterController = null;
  adapterRecord = null;
  adapterBusy(false);
  $("adapter-save-record").disabled = true;
  $("adapter-output").replaceChildren();
  adapterStatus("入力を変更しました。影響する確認を検査してから再計算してください。");
  adapterSources();
}

function adapterSources() {
  const select = $("adapter-source"), previous = select.value;
  try {
    const draft = JSON.parse($("adapter-input").value);
    select.replaceChildren(...draft.sources.map(source => node("option", `${source.id} (${source.section})`, {value: source.id})));
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
  } catch { select.replaceChildren(); }
}

async function adapterPost(path, body, controller) {
  if (new TextEncoder().encode(body).length > jsonBodyLimit) throw new Error("本文は2 MiB以下にしてください。");
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body, signal: controller.signal});
  const value = await response.json();
  if (!response.ok) throw new Error(`${value.error?.code || "HTTP_ERROR"}：${value.error?.message || "読み込みに失敗しました。"}`);
  return value;
}

async function adapterOperation(action) {
  const token = ++adapterToken, controller = new AbortController();
  adapterController?.abort();
  adapterController = controller;
  adapterBusy(true);
  adapterStatus("確認・計算中です。");
  const timer = setTimeout(() => controller.abort(), 660000);
  try {
    const value = await action(controller);
    if (token !== adapterToken) return;
    if (value === null) {
      adapterStatus("Draftを保存しました。入力と実行記録は保持しています。");
      return;
    }
    if (value.adapter_version) {
      $("adapter-input").value = JSON.stringify(value, null, 2);
      adapterRecord = null;
      $("adapter-save-record").disabled = true;
      $("adapter-output").replaceChildren();
      adapterSources();
      adapterStatus("入力候補を読み込み・更新しました。必要な入力元の確認を検査してください。");
    } else if (value.record) {
      adapterRecord = value.record;
      if (value.draft) {
        $("adapter-input").value = JSON.stringify(value.draft, null, 2);
        adapterSources();
      }
      $("adapter-save-record").disabled = false;
      adapterRender(value.view);
    } else {
      adapterRecord = null;
      $("adapter-save-record").disabled = true;
      const area = $("adapter-output");
      area.replaceChildren(details("確認対象・値と改訂・期間・依存情報のdigest", value.confirmations || []),
        ...((value.diagnostics || []).map(item => node("p", `${item.code}：${item.message} (${item.json_pointer || ""}) 入力元：${(item.sources || []).map(s => `${s.file || s.source_id} ${s.json_pointer}`).join(" / ")}`))),
        details("確定Request・入力元対応・診断", value));
      adapterStatus(value.status === "VALID" ? "入力はVALIDです。実行可能性は計算で確認します。" : `${value.status}：必要情報・確認・入力箇所を修正してください。`);
    }
  } catch (error) {
    if (token === adapterToken) adapterStatus(`処理できませんでした。${error.message} 編集中の入力は保持しています。`);
  } finally {
    clearTimeout(timer);
    if (token === adapterToken) { adapterController = null; adapterBusy(false); }
  }
}

function adapterRender(view) {
  const area = $("adapter-output");
  area.replaceChildren(node("p", `実行ID：${view.run_id}`),
    node("p", `元の求解：${view.original_status} · 現在の独立検証：${view.current_status} · 需要充足：${view.demand_satisfied === null ? "未確認" : view.demand_satisfied ? "完全" : "不足あり"}`),
    node("p", `現在の評価には最適性・不足最小性の証明を付与しません。過去の証拠は元Responseの詳細で確認できます。`));
  if (view.solution && view.verification?.valid === true) {
    const request = adapterRecord.request;
    const response = {...view.original_evidence, ...view.metrics, solution: view.solution, verification: view.verification,
      status: view.current_status === "PARTIAL" ? "PARTIAL" : "FEASIBLE"};
    const pair = {input: request, response};
    area.append(renderShortages(pair));
    const slots = jsonSlots(request), dates = [...new Set(slots.map(slot => slot.date))];
    const select = node("select", "", {id: "adapter-day"}, dates.map(date => node("option", date, {value: date})));
    const grid = node("div");
    const render = () => renderJSONDay(pair, slots.filter(slot => slot.date === select.value), grid);
    select.addEventListener("change", render);
    area.append(node("label", "表示する日付", {for: "adapter-day"}), select, grid);
    render();
  }
  area.append(...view.diagnostics.map(item => node("p", `${item.code}：${item.message} (${item.json_pointer}) ${JSON.stringify(item.sources)}`)),
    details("現在の評価・診断・元の探索証拠", view), details("完全な実行記録（原区間を保持）", adapterRecord));
  adapterStatus(`${view.original_status} · 現在の検証 ${view.current_status} · ${view.demand_satisfied === false ? "必要人数に不足があります。" : view.solution ? "有効な計画です。" : "有効な勤務表はありません。"}`);
}

function adapterDownload(name, text) {
  const url = URL.createObjectURL(new Blob([text], {type: "application/json;charset=utf-8"}));
  const link = node("a", "", {href: url, download: name});
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("adapter-input").addEventListener("input", adapterEdited);
$("adapter-load").addEventListener("click", () => adapterOperation(async controller => {
  const response = await fetch(`/samples/${$("adapter-sample").value}.draft.json`, {signal: controller.signal});
  if (!response.ok) throw new Error("サンプルを読み込めませんでした。");
  return response.json();
}));
$("adapter-check").addEventListener("click", () => adapterOperation(controller => adapterPost("/adapter/check", $("adapter-input").value, controller)));
$("adapter-confirm").addEventListener("click", () => adapterOperation(controller => adapterPost("/adapter/confirm",
  `{"draft":${$("adapter-input").value},"source_id":${JSON.stringify($("adapter-source").value)}}`, controller)));
$("adapter-run").addEventListener("click", () => {
  adapterRecord = null;
  $("adapter-save-record").disabled = true;
  $("adapter-output").replaceChildren();
  adapterOperation(controller => adapterPost("/adapter/run", $("adapter-input").value, controller));
});
for (const action of ["import", "split"]) $("adapter-" + action).addEventListener("click", () => adapterOperation(controller => adapterPost("/adapter/" + action, $("json-input").value, controller)));
$("adapter-file").addEventListener("change", () => {
  const file = $("adapter-file").files[0];
  if (file) adapterOperation(async controller => {
    if (file.size > jsonBodyLimit) throw new Error("ファイルは2 MiB以下にしてください。");
    const text = new TextDecoder("utf-8", {fatal: true}).decode(await file.arrayBuffer());
    const value = JSON.parse(text);
    if (value.record_version) return adapterPost("/adapter/verify", text, controller);
    const checked = await adapterPost("/adapter/draft", text, controller);
    return checked;
  });
  $("adapter-file").value = "";
});
$("adapter-save-draft").addEventListener("click", () => adapterOperation(async controller => {
  const value = await adapterPost("/adapter/draft", $("adapter-input").value, controller);
  if (!value.adapter_version) return value;
  adapterDownload("draft.json", JSON.stringify(value, null, 2));
  return null;
}));
$("adapter-save-record").addEventListener("click", () => {
  if (adapterRecord) adapterDownload(`${adapterRecord.run_id}.json`, JSON.stringify(adapterRecord, null, 2));
});
$("adapter-reverify").addEventListener("click", () => {
  if (adapterRecord) adapterOperation(controller => adapterPost("/adapter/verify", JSON.stringify(adapterRecord), controller));
});
