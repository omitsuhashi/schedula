"use strict";

const groups = {basic: "担当配置と勤務の基本", conditions: "守る勤務条件", objectives: "希望と最適化の目標",
  shortage: "人手が足りない場合", replanning: "履歴と再計画", input: "診断と入力の扱い"};
let catalog, lessons, lesson, feature = null, featureController = null, routeRevision = 0;
const featureMeasurements = [];

function dated(value) { return `${value.slice(0, 10)} ${value.slice(11, 16)} Asia/Tokyo`; }
function datedRange(interval) { return `${dated(interval.start)}〜${dated(interval.end)}`; }
function displayField(field, value) {
  if (field === "employee_targets") return ["alice", "bob"].map(id => { const target = value.find(item => item.employee_id === id); return `${id} ${target ? `${target.target_count}回` : "未指定（対象外）"}`; }).join(" / ");
  if (field === "intervals") return value.map(datedRange).join(" / ");
  if (field === "availability") return value.map(datedRange).join(" / ") || "勤務不可";
  if (field === "history") return `${value.last_shift_end ? dated(value.last_shift_end) : "最終勤務なし"}・開始日${value.last_work_day || "なし"}・直前${value.consecutive_work_days_before_window}日`;
  if (field === "skills") return value.map(item => `${item.skill_id} レベル${item.level}`).join(" / ") || "なし";
  if (field === "objectives") return value.map(item => item.metric).join(" → ");
  return String(value);
}

function featureChanges(definitions, before, after) {
  const changes = [];
  for (const definition of definitions) {
    const {collection, ids, field, label, unit} = definition;
    for (const id of ids || [null]) {
      const item = id === null ? before : before[collection].find(item => item.id === id);
      const next = id === null ? after : after[collection].find(item => item.id === id);
      if (JSON.stringify(item[field]) === JSON.stringify(next[field])) continue;
      changes.push(`${label}${id ? ` (${id})` : ""}：${displayField(field, item[field])} → ${displayField(field, next[field])} · ${unit}`);
    }
  }
  return changes;
}

function consecutiveRuns(pair) {
  const dates = [...new Set(jsonSlots(pair.input).map(slot => slot.date))];
  return pair.input.employees.map(employee => {
    const days = new Set(pair.response.solution.shifts.filter(shift => shift.employee_id === employee.id).map(shift => shift.work_day));
    let run = employee.history.consecutive_work_days_before_window, maximum = run;
    for (const day of dates) { run = days.has(day) ? run + 1 : 0; maximum = Math.max(maximum, run); }
    return {employee, days, maximum};
  });
}

function featureIndicators(pair) {
  const values = [`不足合計 ${pair.response.shortage_summary.total_person_minutes}人分`];
  if (lesson.id === "consecutive_days") values.push(`最大連勤（履歴込み） ${Math.max(...consecutiveRuns(pair).map(item => item.maximum))}日`);
  if (lesson.id === "shift_count_balance") values.push(...countIndicators(pair));
  return values;
}

function featurePlan(pair) {
  if (lesson.id === "consecutive_days") {
    const dates = [...new Set(jsonSlots(pair.input).map(slot => slot.date))];
    return scroll("日別の勤務表", table("勤務の開始日で数える勤務日・明示履歴を含む最大連勤", ["従業員", "直前の連勤", ...dates, "最大連勤"],
      consecutiveRuns(pair).map(({employee, days, maximum}) => node("tr", "", {}, [
        node("th", employee.label, {scope: "row"}), node("td", `${employee.history.consecutive_work_days_before_window}日`),
        ...dates.map(day => node("td", days.has(day) ? "勤務 09:00〜10:00" : "勤務なし")), node("td", `${maximum}日`),
      ]))));
  }
  const area = node("div"), grid = jsonSlots(pair.input);
  renderJSONDay(pair, grid, area);
  return area;
}

function featurePlanChanges(before, after) {
  const states = pair => {
    const values = new Map();
    const grid = jsonSlots(pair.input);
    if (pair.input.problem_type === "roster") for (const shift of pair.response.solution.shifts)
      values.set(`${shift.employee_id} ${shift.work_day}`, shift.segments.map(segment => datedRange(segment.interval)).join(" / "));
    for (const assignment of pair.response.solution.assignments) for (const slot of grid)
      if (Date.parse(assignment.interval.start) <= slot.start && Date.parse(assignment.interval.end) >= slot.end)
        values.set(`${assignment.employee_id} ${slot.date} ${slot.label}`, assignment.role_id);
    return values;
  };
  const first = states(before), last = states(after);
  return [...new Set([...first.keys(), ...last.keys()])].filter(key => first.get(key) !== last.get(key))
    .map(key => `${key}：${first.get(key) || "勤務・担当なし"} → ${last.get(key) || "勤務・担当なし"}`);
}

function renderFeature(message) {
  if (lesson.operation === "verify") return renderVerify(message);
  const area = $("feature-output"), pair = feature.current, base = feature.baseline;
  $("feature-status").textContent = message || (pair ? `${pair.response.status} · ${pair.response.status === "PARTIAL" ? "必要人数に不足のある計画です。" : pair.response.status === "OPTIMAL" ? "必須条件と需要を満たす計画です。" : stateText[pair.response.status]}` : "未計算：編集した条件で再計算してください。");
  area.replaceChildren(node("h3", "入力差分"));
  const changes = featureChanges(lesson.editable_fields, feature.initial, feature.input);
  area.append(node("ul", "", {}, (changes.length ? changes : ["初期条件からの変更なし"]).map(text => node("li", text))));
  if (lesson.id === "shift_count_balance") area.append(countPremises(feature.input));
  if (base) area.append(node("p", `初期比較元：${base.response.status} / 現在：${pair?.response.status || "未計算"}`));
  if (pair) {
    if (operationView(lesson.operation, pair.response).validPlan) {
      area.append(node("h3", "この機能の指標"), ...featureIndicators(pair).map(text => node("p", text)), renderShortages(pair));
      area.append(node("p", `有効性：独立検証済み / 最適性：${pair.response.status === "OPTIMAL" ? "目的順序すべて証明済み" : "全目的の最適性は未証明"}`));
      if (base && operationView(lesson.operation, base.response).validPlan) {
        const initial = featureIndicators(base), actual = featureIndicators(pair);
        area.append(...actual.map((value, i) => node("p", `${initial[i]} → ${value}${initial[i] === value ? "（この指標は変わらない）" : ""}`)));
        const differences = featurePlanChanges(base, pair);
        area.append(node("h3", `勤務・担当の差分：${differences.length}件`),
          node("p", "同率解の差も含み得ます。表示比較であり、変更最小化ではありません。"),
          node("ul", "", {}, differences.map(text => node("li", text))));
      } else area.append(node("p", "初期結果に有効な計画がないため勤務表の差分は比較できません。"));
      area.append(node("h3", "現在の勤務・担当表"), featurePlan(pair));
    } else area.append(node("p", "解がないため勤務表の差分は比較できません。入力と状態を比較してください。"));
    if (!operationView(lesson.operation, pair.response).validPlan) area.append(...pair.response.diagnostics.map(item => node("p", `${item.code}：${item.message} (${item.json_pointer ?? ""})`)));
    area.append(details("全診断", pair.response.diagnostics),
      details("確定入力・全Response・目的と証明範囲", pair));
  }
  if (base) area.append(details("初期入力と実結果", base));
  if (feature.previous) area.append(details("変更前の結果（現在の条件には無効）", feature.previous));
}

function featureEdited(input) {
  featureController?.abort();
  featureController = null;
  feature.edit(input);
  $("feature-result").setAttribute("aria-busy", "false");
  $("feature-controls").disabled = false;
  renderFeature();
}

function renderFeatureFields() {
  const area = $("feature-fields");
  area.replaceChildren();
  if (lesson.id === "shift_count_balance") return renderCountFields();
  if (lesson.operation === "verify") return renderVerifyFields();
  const definition = lesson.editable_fields[0];
  const number = node("input", "", {id: "feature-number", type: "number", required: "", min: definition.min, max: definition.max, step: "1"});
  number.value = feature.input[definition.collection].find(item => item.id === definition.ids[0])[definition.field];
  number.addEventListener("input", () => {
    const request = clone(feature.input);
    for (const id of definition.ids) request[definition.collection].find(item => item.id === id)[definition.field] = number.valueAsNumber;
    featureEdited(request);
  });
  area.append(node("label", `${definition.label}（${definition.unit}） `, {for: "feature-number"}, [number]));
  if (lesson.id === "consecutive_days") {
    const backup = node("input", "", {id: "feature-backups", type: "checkbox"});
    backup.checked = feature.input.employees.find(item => item.id === "b").availability[0].start.startsWith("2026-10-10");
    backup.addEventListener("change", () => {
      const request = clone(feature.input);
      for (const id of ["b", "c"]) request.employees.find(item => item.id === id).availability = backup.checked ?
        [{start: "2026-10-10T00:00:00+09:00", end: "2026-10-12T00:00:00+09:00"}] : clone(feature.initial.employees.find(item => item.id === id).availability);
      featureEdited(request);
    });
    const history = node("input", "", {id: "feature-history", type: "checkbox"});
    history.checked = feature.input.employees[0].history.consecutive_work_days_before_window === 3;
    history.addEventListener("change", () => {
      const request = clone(feature.input);
      request.employees[0].history = history.checked ? clone(lesson.steps.find(step => step.id === "history").changes.employees.a.history) : clone(feature.initial.employees[0].history);
      featureEdited(request);
    });
    area.append(node("label", "", {}, [backup, document.createTextNode(" B・Cを10月10・11日だけ勤務可能にする")]),
      node("label", "", {}, [history, document.createTextNode(" Aに前週からの3連勤を追加する（10月4日10:00終了）")]));
  }
}

function renderFeatureGuide() {
  $("feature-guide").replaceChildren(node("strong", "試す変更（入力後に実行してください）"));
  for (const step of lesson.steps.slice(1).filter(step => !step.restore || Object.keys(step.changes).length)) {
    const button = node("button", step.instruction, {type: "button", "data-step": step.id});
    button.addEventListener("click", () => {
      const request = clone(step.restore ? feature.initial : feature.input);
      if (lesson.operation === "verify") {
        featureEdited(editKitchen(request, step.changes.kitchen_employee)); renderFeatureFields(); $("feature-run").focus(); return;
      }
      for (const [collection, changes] of Object.entries(step.changes))
        for (const [id, values] of Object.entries(changes)) Object.assign(request[collection].find(item => item.id === id), clone(values));
      featureEdited(request);
      renderFeatureFields();
      $("feature-run").focus();
    });
    $("feature-guide").append(button);
  }
}

async function runFeature() {
  if (!feature || featureController || !$("feature-form").reportValidity()) return;
  const state = feature, revision = state.revision, input = clone(state.input);
  featureController?.abort();
  const controller = new AbortController();
  featureController = controller;
  $("feature-controls").disabled = true;
  $("feature-result").setAttribute("aria-busy", "true");
  renderFeature(lesson.operation === "verify" ? "検証中です。入力時の編集案を公開verifyで検査しています。" : "計算中です。入力時の条件で計算しています。");
  const started = performance.now();
  const timer = setTimeout(() => controller.abort(), 660000);
  try {
    const response = await fetch(lesson.operation === "verify" ? "/verify-json" : "/solve-json", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(input), signal: controller.signal});
    const result = await response.json();
    if (feature !== state || revision !== state.revision) return;
    if (!response.ok) throw new Error(`${result.error?.code || "HTTP_ERROR"}：${result.error?.message || "結果を取得できません。"}`);
    if (lesson.operation === "verify") acceptVerification(result, input);
    else {
      const grid = jsonSlots(input);
      acceptResponse(result, input, [input.planning_window.start, ...grid.map(slot => new Date(slot.end).toISOString())]);
    }
    state.receive(result, revision);
    renderFeature();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (feature === state && revision === state.revision) featureMeasurements.push({id: lesson.id, initial: !(lesson.operation === "verify" ? verifyChanges(state.initial, input) : featureChanges(lesson.editable_fields, state.initial, input)).length,
      elapsed_ms: performance.now() - started, status: result.status, solver: result.solver, stats: result.stats});
  } catch (error) {
    if (feature !== state || revision !== state.revision) return;
    renderFeature(`結果を取得できませんでした。${error.name === "AbortError" ? "待機を終了しました。サーバーの計算停止は保証しません。" : error.message} 再実行できます。`);
  } finally {
    clearTimeout(timer);
    if (featureController === controller) {
      featureController = null;
      $("feature-controls").disabled = false;
      $("feature-result").setAttribute("aria-busy", "false");
    }
  }
}

async function routeFeature() {
  const revision = ++routeRevision;
  featureController?.abort(); featureController = null;
  if (feature) feature.edit(feature.input);
  feature = null;
  generation++; active?.abort(); active = null; setBusy(false);
  adapterToken++; adapterController?.abort(); adapterController = null; adapterBusy(false);
  jsonPair = null; $("json-input").value = ""; $("json-output").replaceChildren();
  $("json-status").textContent = "サンプルまたはファイルを読み込んでください。";
  adapterRecord = null; $("adapter-input").value = ""; $("adapter-output").replaceChildren(); adapterSources();
  $("adapter-request-input").value = "";
  $("adapter-save-record").disabled = $("adapter-reverify").disabled = true;
  adapterStatus("分割サンプルを読み込んでください。");
  const id = location.hash.slice(1);
  for (const area of ["feature-list", "feature-demo", "editor", "json-demo", "adapter-demo"]) $(area).hidden = true;
  if (id === "combined") {
    $("editor").hidden = false; $("controls").disabled = true;
    $("status").textContent = "サンプルを読み込んでいます。";
    await start(() => revision === routeRevision); return;
  }
  if (["json", "large", "records"].includes(id)) {
    const area = $(id === "records" ? "adapter-demo" : "json-demo"); area.hidden = false; area.open = true;
    if (id === "large") $("json-sample").value = "roster-100-30";
    return;
  }
  const topic = catalog.topics.find(item => item.id === id);
  lesson = lessons.find(item => item.id === id);
  if (!lesson) {
    $("feature-list").hidden = false;
    $("feature-list").querySelector("[role=status]").textContent = id ? `${topic?.title || id}：準備中です。実装済みの機能を選んでください。` : "実装済みの機能を選んでください。";
    return;
  }
  $("feature-demo").hidden = false;
  $("feature-title").textContent = lesson.label;
  $("feature-title").focus();
  $("feature-status").textContent = "初期教材を読み込んでいます。";
  $("feature-output").replaceChildren();
  $("feature-controls").disabled = true;
  try {
    const response = await fetch(`/samples/${lesson.request_file}`);
    if (!response.ok) throw new Error("教材を取得できません。");
    const request = await response.json();
    if (revision !== routeRevision) return;
    let input = request;
    if (lesson.operation === "verify") {
      const solution = await fetch(`/samples/${lesson.solution_file}`);
      if (!solution.ok) throw new Error("初期の編集案を取得できません。");
      input = {request, solution: await solution.json()};
    }
    if (revision !== routeRevision) return;
    feature = featureState(input, lesson.operation);
    $("feature-run").textContent = lesson.operation === "verify" ? "再検証" : "再計算";
    $("feature-intro").textContent = lesson.intro || (lesson.id === "demand" ? "12:00〜13:00のホール人数だけを編集します。必須の最低人数は0人で、必要人数を残した不足を表示します。" :
      "連勤上限だけを5日から3日へ変えます。Aの希望を優先する選好、B・Cの交代要員、各日09:00〜10:00の需要1人が前提です。");
    $("feature-premises").replaceChildren(node("p", `${request.employees.length}人 / ${datedRange(request.planning_window)} / ${request.planning_window.slot_minutes}分刻み / ${lesson.operation === "verify" ? "公開verify：探索なし" : `探索予算${request.solver.time_limit_seconds}秒（総応答時間とは別）`}`),
      node("p", `目的順序：${request.objectives.map(item => item.metric).join(" → ") || "なし"}`),
      details("技能・需要・候補・希望・必須条件を含む全入力", input));
    renderFeatureFields(); renderFeatureGuide();
    $("feature-controls").disabled = false;
    await runFeature();
  } catch (error) {
    if (revision === routeRevision) $("feature-status").textContent = `教材を取得できませんでした。${error.message} 一覧から選び直してください。`;
  }
}

$("feature-form").addEventListener("submit", event => { event.preventDefault(); runFeature(); });
$("feature-restore").addEventListener("click", () => {
  featureController?.abort(); featureController = null;
  feature.restore(); renderFeatureFields(); renderFeature();
  if (!feature.current) runFeature();
});

async function startFeatures() {
  try {
    [catalog, lessons] = await Promise.all(["catalog", "lessons"].map(async name => {
      const response = await fetch(`/samples/${name}.json`);
      if (!response.ok) throw new Error("一覧を取得できません。");
      return response.json();
    }));
    const area = $("feature-list");
    area.replaceChildren(node("h2", "できること"), node("p", "必要人数・連続勤務日数・夜勤回数・手修正検証を試せます。"), node("p", "", {role: "status", "aria-live": "polite"}));
    for (const [group, title] of Object.entries(groups)) area.append(node("h3", title), node("ul", "", {class: "feature-cards"},
      catalog.topics.filter(item => item.group === group).map(item => {
        const ready = lessons.some(lesson => lesson.id === item.id);
        return node("li", "", {}, [ready ? node("a", item.title, {href: `#${item.id}`}) : node("strong", `${item.title}（準備中）`),
          node("p", ready ? lessons.find(lesson => lesson.id === item.id).steps[1].instruction : `専用操作は準備中です。担当Issue #${item.issue}`)]);
      })));
    area.append(node("h3", "補助の入口"), node("p", "", {}, [
      node("a", "複数条件を組み合わせる", {href: "#combined"}), document.createTextNode(" · "),
      node("a", "100人・30日で試す", {href: "#large"}), document.createTextNode(" · "),
      node("a", "JSONで自由に試す", {href: "#json"}), document.createTextNode(" · "),
      node("a", "入力確認・実行記録", {href: "#records"}),
    ]), ...catalog.templates.map(item => node("p", `${item.title}：準備中（#${item.issue}）`)));
    window.addEventListener("hashchange", routeFeature);
    await routeFeature();
  } catch (error) {
    $("feature-list").hidden = false;
    $("feature-list").textContent = `一覧を取得できませんでした。${error.message} 再読み込みしてください。`;
  }
}
startFeatures();
