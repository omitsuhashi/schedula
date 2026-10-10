"use strict";

const groups = {basic: "担当配置と勤務の基本", conditions: "守る勤務条件", objectives: "希望と最適化の目標",
  shortage: "人手が足りない場合", replanning: "履歴と再計画", input: "診断と入力の扱い"};
let catalog, lessons, lesson, feature = null, featureController = null, routeRevision = 0;
const featureMeasurements = [];

function dated(value) { return `${value.slice(0, 10)} ${value.slice(11, 16)} Asia/Tokyo`; }
function datedRange(interval) { return `${dated(interval.start)}〜${dated(interval.end)}`; }
function displayField(field, value) {
  if (field === "interval") return datedRange(value);
  if (field === "employee_targets") return ["alice", "bob"].map(id => { const target = value.find(item => item.employee_id === id); return `${id} ${target ? `${target.target_count}回` : "未指定（対象外）"}`; }).join(" / ");
  if (field === "intervals") return value.map(datedRange).join(" / ");
  if (field === "availability") return value.map(datedRange).join(" / ") || "勤務不可";
  if (field === "history") return `${value.last_shift_end ? dated(value.last_shift_end) : "最終勤務なし"}・開始日${value.last_work_day || "なし"}・直前${value.consecutive_work_days_before_window}日`;
  if (field === "skills") return value.map(item => `${item.skill_id} レベル${item.level}`).join(" / ") || "なし";
  if (field === "required_skills") return value.map(item => `${item.skill_id} 最低レベル${item.min_level}`).join(" / ") || "なし";
  if (field === "segments") return value.map(item => `${datedRange(item.interval)} · 休憩 ${item.breaks.map(datedRange).join(" / ") || "なし"}`).join(" / ");
  if (field === "start_times") return value.join(" / ");
  if (field === "segment_options") return value.map(option => option.map(item => `開始から${item.offset_minutes}分後 · 勤務長${item.duration_minutes}分`).join(" / ")).join(" または ");
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

function featureMetric(label, before, after, unit, warning = false) {
  return node("div", "", {class: `feature-metric${warning ? " shortage" : ""}`}, [
    node("p", label, {class: "note"}),
    node("div", "", {class: "feature-values"}, [
      node("span", "", {}, [node("small", "初期"), node("strong", before == null ? "—" : `${before}${unit}`)]),
      node("span", "→", {"aria-hidden": "true"}),
      node("span", "", {}, [node("small", "現在"), node("strong", `${after}${unit}`)]),
    ]),
    node("small", before == null ? "初期結果は比較できません" : before === after ? "変化なし" : "初期から変化"),
  ]);
}

function featureSummary(pair, base) {
  const comparable = base && operationView(lesson.operation, base.response).validPlan;
  const cards = [];
  if (isWorkLesson()) cards.push(...basicCards(pair, base));
  if (lesson.id === "demand") {
    const count = input => input.demand.find(item => item.id === "hall_2").required_people;
    const assigned = value => {
      const demand = value.input.demand.filter(item => ["hall_2", "hall_3"].includes(item.id));
      const counts = jsonSlots(value.input).filter(slot => demand.some(item => Date.parse(item.interval.start) <= slot.start && Date.parse(item.interval.end) >= slot.end))
        .map(slot => value.response.solution.assignments.filter(item => item.role_id === "hall" && Date.parse(item.interval.start) <= slot.start && Date.parse(item.interval.end) >= slot.end).length);
      const minimum = Math.min(...counts), maximum = Math.max(...counts);
      return minimum === maximum ? String(minimum) : `${minimum}〜${maximum}`;
    };
    cards.push(featureMetric("変更した条件 · 12:00〜13:00のホール", count(feature.initial), count(pair.input), "人"),
      featureMetric("12:00〜13:00に配置できた人数", comparable ? assigned(base) : null, assigned(pair), "人"));
  }
  if (lesson.id === "consecutive_days") {
    const limit = input => input.constraints.find(item => item.id === "consecutive").limit_days;
    for (const {collection, ids, field, label, unit} of lesson.editable_fields) for (const id of ids) {
      const before = feature.initial[collection].find(item => item.id === id);
      const after = pair.input[collection].find(item => item.id === id);
      if (JSON.stringify(before[field]) === JSON.stringify(after[field])) continue;
      const card = featureMetric(`変更した条件 · ${label}${collection === "employees" ? ` (${after.label})` : ""}`,
        displayField(field, before[field]), displayField(field, after[field]), field === "limit_days" ? unit : "");
      if (field !== "limit_days") card.classList.add("feature-condition");
      cards.push(card);
    }
    if (!cards.length) cards.push(featureMetric("条件 · 連勤上限", limit(feature.initial), limit(pair.input), "日"));
    cards.push(featureMetric("実際の最大連勤（履歴込み）", comparable ? Math.max(...consecutiveRuns(base).map(item => item.maximum)) : null,
      Math.max(...consecutiveRuns(pair).map(item => item.maximum)), "日"));
  }
  if (lesson.id === "shift_count_balance") cards.push(featureMetric("勤務回数の目標偏差", comparable ? base.response.shift_count_balance_summary[0].total_deviation_count : null,
    pair.response.shift_count_balance_summary[0].total_deviation_count, "回"));
  const shortage = pair.response.shortage_summary.total_person_minutes;
  cards.push(featureMetric("不足合計", comparable ? base.response.shortage_summary.total_person_minutes : null, shortage, "人分", shortage > 0));
  const summary = node("div", "", {class: "feature-summary"}, cards);
  const title = shortage ? "必要人数を満たせない時間帯があります" : "必要人数をすべて満たしています";
  return node("section", "", {class: "feature-overview", "aria-label": "変更と結果の要点"}, [
    node("h3", title), node("p", "必須条件は守れています。", {class: "feature-validity"}), summary,
    ...(shortage ? [node("ul", "", {class: "feature-shortage-locations"}, pair.response.shortage_summary.shortages.map(item =>
      node("li", `${pair.input.roles.find(role => role.id === item.role_id).label} · ${datedRange(item.interval)} · 不足${item.missing_people}人`)))] : []),
    ...(shortage ? [node("p", "不足1人が60分続くと60人分です。追加する従業員の人数とは異なります。", {class: "note"})] : []),
  ]);
}

function featurePlan(pair, base = null) {
  if (isWorkLesson()) return basicPlan(pair, base);
  const comparable = base && operationView(lesson.operation, base.response).validPlan;
  if (lesson.id === "consecutive_days") {
    const dates = [...new Set(jsonSlots(pair.input).map(slot => slot.date))];
    const initialRuns = comparable ? consecutiveRuns(base) : [];
    return scroll("日別の勤務表", table(`${dates[0]}〜${dates.at(-1)} Asia/Tokyo · 勤務の開始日で数える・休みはこの例の完全休日`, ["従業員", "直前の連勤", ...dates.map(day => day.slice(5).replace("-", "/")), "最大連勤"],
      consecutiveRuns(pair).map(({employee, days, maximum}) => node("tr", "", {}, [
        node("th", employee.label, {scope: "row"}), node("td", `${employee.history.consecutive_work_days_before_window}日`),
        ...dates.map(day => {
          const previous = initialRuns.find(item => item.employee.id === employee.id);
          const changed = previous && previous.days.has(day) !== days.has(day);
          return node("td", "", {class: `${days.has(day) ? "feature-work" : "feature-off"}${changed ? " feature-changed" : ""}`}, [
            node("strong", days.has(day) ? "勤務" : "休み"),
            node("small", days.has(day) ? "09:00〜10:00" : "完全休日"),
            ...(changed ? [node("small", "変更"), node("small", `${previous.days.has(day) ? "勤務" : "休み"}→${days.has(day) ? "勤務" : "休み"}`)] : []),
          ]);
        }), node("td", `${maximum}日`),
      ]))));
  }
  if (lesson.id === "demand") {
    const covers = (interval, slot) => Date.parse(interval.start) <= slot.start && Date.parse(interval.end) >= slot.end;
    const counts = (value, role, slot) => ({
      required: value.input.demand.find(item => item.role_id === role && covers(item.interval, slot))?.required_people || 0,
      assigned: value.response.solution.assignments.filter(item => item.role_id === role && covers(item.interval, slot)).length,
    });
    const peak = pair.input.demand.filter(item => ["hall_2", "hall_3"].includes(item.id));
    const grid = jsonSlots(pair.input).filter(slot => peak.some(item => covers(item.interval, slot)) || pair.input.roles.some(role => {
      const now = counts(pair, role.id, slot), before = comparable ? counts(base, role.id, slot) : null;
      return now.assigned < now.required || (before && (now.assigned !== before.assigned || now.required !== before.required));
    }));
    return scroll("必要人数と配置人数", table("12:00〜13:00と、人数変化・不足のある時間帯 · ● 配置 / □ 不足", ["役割", ...grid.map(slot => slot.label)],
      pair.input.roles.map(role => node("tr", "", {}, [node("th", role.label, {scope: "row"}), ...grid.map(slot => {
        const now = counts(pair, role.id, slot), before = comparable ? counts(base, role.id, slot) : null;
        const missing = Math.max(0, now.required - now.assigned);
        const changed = before && (now.required !== before.required || now.assigned !== before.assigned);
        return node("td", "", {class: `${missing ? "shortage" : ""}${changed ? " feature-changed" : ""}`}, [
          node("span", "●".repeat(now.assigned) + "□".repeat(missing), {class: "feature-people", "aria-hidden": "true"}),
          node("strong", `配置${now.assigned} / 必要${now.required}人`),
          node("small", missing ? `不足${missing}人` : "不足なし"),
          ...(changed ? [node("small", `変更 · 初期は配置${before.assigned} / 必要${before.required}人`)] : []),
        ]);
      })]))));
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
  area.replaceChildren();
  const changes = featureChanges(lesson.editable_fields, feature.initial, feature.input);
  const inputs = node("details", "", {class: "feature-input-changes"}, [node("summary", changes.length ? `変更した条件 · ${changes.length}項目` : "初期条件からの変更なし"),
    node("ul", "", {}, changes.map(text => node("li", text)))]);
  if (!pair) {
    inputs.open = true;
    area.append(inputs);
  }
  if (lesson.id === "shift_count_balance") area.append(countPremises(feature.input));
  if (pair) {
    if (operationView(lesson.operation, pair.response).validPlan) {
      area.append(featureSummary(pair, base));
      if (lesson.id === "shift_count_balance") area.append(...countIndicators(pair).map(text => node("p", text)));
      const highlighted = ["demand", "consecutive_days"].includes(lesson.id);
      area.append(node("h3", lesson.id === "demand" ? "どの時間帯が変わったか" : highlighted ? "誰の勤務が変わったか" : "現在の勤務・担当表"),
        node("p", `${highlighted ? "枠線と「変更」は初期からの変化です。" : ""}同率解の差も含み得ます。`, {class: "note"}), featurePlan(pair, base), inputs);
      const proven = pair.response.shortage_summary.proven_minimal && pair.response.priority_summary.groups.every(item => item.proven_minimal) &&
        pair.response.objectives.every(item => item.proven_optimal);
      const proof = node("details", "", {class: "feature-proof"}, [node("summary", "条件の検証・不足・最適性の詳しい情報"),
        node("p", `有効性：独立検証済み / 最適性：${proven ? "目的順序すべて証明済み" : "全目的の最適性は未証明"}`), renderShortages(pair)]);
      if (lesson.id === "demand") {
        const assignments = node("details", "", {}, [node("summary", "誰を配置したか · 担当表")]);
        const plan = node("div"); renderJSONDay(pair, jsonSlots(pair.input), plan);
        assignments.append(plan); area.append(assignments);
      }
      if (base && operationView(lesson.operation, base.response).validPlan) {
        const differences = featurePlanChanges(base, pair);
        area.append(node("details", "", {}, [node("summary", `勤務・担当の差分：${differences.length}件`),
          node("p", "同率解の差も含み得ます。表示比較であり、変更最小化ではありません。"),
          node("ul", "", {}, differences.map(text => node("li", text)))]));
      } else area.append(node("p", "初期結果に有効な計画がないため勤務表の差分は比較できません。"));
      area.append(proof);
    } else {
      if (lesson.module === "conditions") inputs.open = true;
      area.append(inputs, node("p", "解がないため勤務表の差分は比較できません。入力と状態を比較してください。"));
    }
    if (!operationView(lesson.operation, pair.response).validPlan) area.append(...pair.response.diagnostics.map(item => node("p", `${item.code}：${item.message} (${item.json_pointer ?? ""})`)));
    const technical = node("details", "", {}, [node("summary", "入力・診断・保存した結果（詳細）"),
      details("全診断", pair.response.diagnostics), details("確定入力・全Response・目的と証明範囲", pair)]);
    if (base) technical.append(details("初期入力と実結果", base));
    if (feature.previous) technical.append(details("変更前の結果（現在の条件には無効）", feature.previous));
    area.append(technical);
  }
  if (!pair && feature.previous) area.append(details("変更前の結果（現在の条件には無効）", feature.previous));
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
  if (isWorkLesson()) return renderBasicFields();
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
  const topic = [...catalog.topics, ...catalog.templates].find(item => item.id === id);
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
      ...(lesson.premises || []).map(text => node("p", text)),
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
    area.replaceChildren(node("h2", "できること"), node("p", "担当配置・勤務計画の実装済みの主題を選び、条件を編集して比較できます。"), node("p", "", {role: "status", "aria-live": "polite"}));
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
    ]), ...catalog.templates.map(item => node("p", "", {}, lessons.some(lesson => lesson.id === item.id) ? [node("a", item.title, {href: `#${item.id}`})] : [document.createTextNode(`${item.title}：準備中（#${item.issue}）`)])));
    window.addEventListener("hashchange", routeFeature);
    await routeFeature();
  } catch (error) {
    $("feature-list").hidden = false;
    $("feature-list").textContent = `一覧を取得できませんでした。${error.message} 再読み込みしてください。`;
  }
}
startFeatures();
