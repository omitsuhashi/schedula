"use strict";

const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
const time = timestamp => timestamp.slice(11, 16);
const range = interval => `${time(interval.start)}〜${time(interval.end)}`;
const stateText = {
  OPTIMAL: "条件を満たす配置です。",
  FEASIBLE: "条件を満たします。最適性は未証明です。",
  PARTIAL: "必要人数に不足があります。未完成の担当配置を出力しました。",
  INFEASIBLE: "この条件を満たす配置はありません。条件を見直してください。",
  UNKNOWN: "探索予算内に結果が確定しませんでした。再計算できます。",
  INVALID_INPUT: "入力不備があります。診断の欄を修正してください。",
  BACKEND_UNAVAILABLE: "計算に必要な依存がありません。実行環境を確認してください。",
  INTERNAL_ERROR: "計算の実行に失敗しました。解を採用せず、診断を確認してください。",
};
let sample, scenarios, slots, boundaries;
let baseline = null, current = null, previous = null;
let generation = 0, sequence = 0, busy = false, active = null;
let scenarioIndex = 0, stepIndex = 1, guided = true, pendingStep = false, changed = false;

function node(tag, text = "", attributes = {}, children = []) {
  const result = document.createElement(tag);
  result.textContent = text;
  for (const [key, value] of Object.entries(attributes)) result.setAttribute(key, value);
  for (const child of children) result.append(child);
  return result;
}

function table(caption, headings, rows) {
  return node("table", "", {}, [
    node("caption", caption),
    node("thead", "", {}, [node("tr", "", {}, headings.map(text => node("th", text, {scope: "col"})))]),
    node("tbody", "", {}, rows),
  ]);
}

function scroll(label, content) {
  return node("div", "", {class: "scroll", tabindex: "0", role: "region", "aria-label": label}, [content]);
}

function field(tag, label, pointer, attributes = {}) {
  return node(tag, "", {"aria-label": label, "data-pointer": pointer, ...attributes});
}

function fields() { return [...$("editor").querySelectorAll("[data-pointer]")]; }
function at(pointer) { return fields().find(item => item.dataset.pointer === pointer); }

function renderForm(request, preserveTimes = false) {
  const rows = request.employees.map((employee, index) => {
    const prefix = `/employees/${index}`;
    const name = field("input", `${employee.id}の名前`, `${prefix}/label`, {type: "text", required: ""});
    name.value = employee.label;
    const cells = request.skills.map(skill => {
      const input = field("input", `${employee.id}の${skill.label}`, `${prefix}/skills/${skill.id}`, {type: "checkbox"});
      input.checked = employee.skills.some(item => item.skill_id === skill.id);
      return node("td", "", {}, [input]);
    });
    const times = ["start", "end"].map(key => {
      const input = field("select", `${employee.id}の勤務可能時間${key === "start" ? "開始" : "終了"}`, `${prefix}/availability/0/${key}`);
      input.append(...boundaries.map(value => node("option", time(value), {value})));
      // 勤務不可の送信値には含まれない選択時刻を、ガイドでの再描画後も保持する。
      input.value = employee.availability[0]?.[key] ||
        (preserveTimes && at(`${prefix}/availability/0/${key}`)?.value) ||
        sample.employees[index].availability[0]?.[key] || sample.planning_window[key];
      input.disabled = employee.availability.length === 0;
      return input;
    });
    const unavailable = field("input", `${employee.id}を勤務不可にする`, `${prefix}/availability`, {type: "checkbox"});
    unavailable.checked = employee.availability.length === 0;
    unavailable.addEventListener("change", () => times.forEach(input => { input.disabled = unavailable.checked; }));
    return node("tr", "", {}, [node("th", "", {scope: "row"}, [name]), ...cells,
      node("td", "", {}, [times[0], document.createTextNode(" 〜 "), times[1]]), node("td", "", {}, [unavailable])]);
  });
  $("employees").replaceChildren(table("6人固定。技能は保有の有無を指定します。", ["名前", "調理", "接客", "洗浄", "勤務可能時間", "勤務不可"], rows));
  const demandRows = request.roles.map(role => node("tr", "", {}, [
    node("th", role.label, {scope: "row"}), ...slots.map(slot => {
      const index = request.demand.findIndex(item => item.role_id === role.id && item.interval.start === slot.start);
      const input = field("input", `${range(slot)}の${role.label}の必要人数`, `/demand/${index}/required_people`, {type: "number", min: "0", max: "6", step: "1", required: ""});
      input.value = request.demand[index].required_people;
      return node("td", "", {}, [input]);
    }),
  ]));
  $("demand").replaceChildren(table("元の必要人数を保ち、配置できない人数を不足として表示します。", ["役割", ...slots.map(range)], demandRows));
}

function readRequest(report = false) {
  const request = clone(sample);
  for (const input of fields()) input.setCustomValidity("");
  request.employees.forEach((employee, index) => {
    const prefix = `/employees/${index}`;
    const name = at(`${prefix}/label`);
    employee.label = name.value.trim();
    if (Array.from(employee.label).length < 1 || Array.from(employee.label).length > 20) name.setCustomValidity("名前は空白を除き1〜20文字で入力してください。");
    employee.skills = sample.skills.filter(skill => at(`${prefix}/skills/${skill.id}`).checked).map(skill => ({skill_id: skill.id, level: 1}));
    const start = at(`${prefix}/availability/0/start`), end = at(`${prefix}/availability/0/end`);
    employee.availability = at(`${prefix}/availability`).checked ? [] : [{start: start.value, end: end.value}];
    if (employee.availability.length && start.value >= end.value) end.setCustomValidity("終了は開始より後にしてください。");
  });
  request.demand.forEach((item, index) => {
    const input = at(`/demand/${index}/required_people`);
    item.required_people = input.valueAsNumber;
    if (!Number.isInteger(item.required_people) || item.required_people < 0 || item.required_people > 6) input.setCustomValidity("0〜6の整数を入力してください。");
  });
  const invalid = fields().find(input => !input.disabled && !input.validity.valid);
  if (invalid) {
    if (report) { invalid.focus(); invalid.reportValidity(); }
    return null;
  }
  return request;
}

function validPair(pair) {
  return !!pair && ["OPTIMAL", "FEASIBLE", "PARTIAL"].includes(pair.response.status) &&
    pair.response.verification?.performed === true && pair.response.verification?.valid === true &&
    !!pair.response.solution;
}

function assignmentGrid(pair) {
  const grid = new Map();
  for (const assignment of pair.response.solution.assignments) {
    slots.forEach((slot, index) => {
      if (Date.parse(assignment.interval.start) <= Date.parse(slot.start) && Date.parse(assignment.interval.end) >= Date.parse(slot.end)) grid.set(`${assignment.employee_id}/${index}`, assignment.role_id);
    });
  }
  return grid;
}

function roleName(id, input = sample) { return input.roles.find(role => role.id === id)?.label || "担当なし"; }

function renderAssignments(pair) {
  const grid = assignmentGrid(pair);
  const rows = pair.input.employees.map(employee => node("tr", "", {}, [
    node("th", employee.label, {scope: "row"}), ...slots.map((slot, index) => {
      const role = grid.get(`${employee.id}/${index}`);
      const available = employee.availability.some(interval => interval.start <= slot.start && interval.end >= slot.end);
      return node("td", role ? roleName(role, pair.input) : available ? "担当なし" : "勤務可能時間外", {class: role || ""});
    }),
  ]));
  return scroll("担当配置の結果表", table(`${pair.input.request_id} · ${verificationText(pair.response)}`, ["従業員", ...slots.map(range)], rows));
}

function renderCoverage(pair) {
  const grid = assignmentGrid(pair);
  const rows = pair.input.roles.map(role => node("tr", "", {}, [node("th", role.label, {scope: "row"}), ...slots.map((slot, index) => {
    const count = pair.input.employees.filter(employee => grid.get(`${employee.id}/${index}`) === role.id).length;
    const demand = pair.input.demand.find(item => item.role_id === role.id && item.interval.start === slot.start);
    return coverageCell(count, demand.required_people);
  })]));
  return scroll("需要充足の結果表", table("配置人数 / 実行時の必要人数", ["役割", ...slots.map(range)], rows));
}

function coverageCell(assigned, required) {
  const missing = required - assigned;
  return node("td", `${assigned} / ${required}${missing > 0 ? ` · 不足${missing}人` : ""}`, {class: missing > 0 ? "shortage" : ""});
}

function verificationText(result) {
  if (result.status !== "PARTIAL") return "独立検証：成功";
  return (result.schema_version === "0.15") ? "独立検証：不足集計・最低人数を含む必須条件を確認済み" : "独立検証：不足集計・需要以外の必須条件を確認済み";
}

function renderShortages(pair) {
  const summary = pair.response.shortage_summary;
  if (!summary) return node("span");
  const roles = new Map(pair.input.roles.map(role => [role.id, role.label || role.id]));
  const hasMinimum = (pair.input.schema_version === "0.15");
  const zone = pair.input.planning_window.timezone;
  const dateTime = new Intl.DateTimeFormat("ja-JP", {timeZone: zone, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "shortOffset"});
  const result = node("div", "", {}, [
    node("p", `不足合計：${summary.total_person_minutes}人分 · ${summary.proven_minimal ? "不足最小性：証明済み（追加従業員数を示す値ではありません）" : "不足最小性：未証明。埋められないことが確定したわけではありません。"}`),
  ]);
  if (pair.response.priority_summary) result.append(...pair.response.priority_summary.groups.map(group =>
    node("p", `priority ${group.priority}：不足${group.total_person_minutes}人分 · 上位段階を固定した最小性：${group.proven_minimal ? "証明済み" : "未証明"}`)));
  if (!summary.shortages.length) return result;
  const pageSize = 100;
  const select = node("select", "", {"aria-label": "不足一覧のページ"},
    Array.from({length: Math.ceil(summary.shortages.length / pageSize)}, (_, index) =>
      node("option", `${index + 1}ページ`, {value: index})));
  const list = node("div");
  const render = () => {
    const first = Number(select.value) * pageSize;
    const last = Math.min(first + pageSize, summary.shortages.length);
    list.replaceChildren(scroll("不足の一覧", table(`元の必要人数と配置人数・不足人数 · 全${summary.shortages.length}件中${first + 1}〜${last}件`, ["需要ID", "役割", "時間帯", "必要人数", ...(hasMinimum ? ["最低人数"] : []), "配置人数", "不足人数"], summary.shortages.slice(first, last).map(item => node("tr", "", {}, [
      node("th", item.demand_id, {scope: "row"}), node("td", roles.get(item.role_id)),
      node("td", `${dateTime.format(Date.parse(item.interval.start))}〜${dateTime.format(Date.parse(item.interval.end))}`),
      node("td", `${item.required_people}人`), ...(hasMinimum ? [node("td", `${item.minimum_people}人`)] : []), node("td", `${item.assigned_people}人`), node("td", `不足${item.missing_people}人`, {class: "shortage"}),
    ])))));
  };
  select.addEventListener("change", render);
  if (summary.shortages.length > pageSize) result.append(node("label", "不足一覧のページ ", {class: "toolbar"}, [select]));
  result.append(list);
  render();
  return result;
}

function details(label, value) {
  return node("details", "", {}, [node("summary", label), node("pre", JSON.stringify(value, null, 2))]);
}

function renderDiagnostics(items) {
  $("diagnostics").replaceChildren(...items.map(item => {
    const pointer = item.json_pointer;
    const input = pointer == null ? null : at(pointer) || fields().find(field => field.dataset.pointer.startsWith(pointer + "/"));
    const parts = [node("p", `${item.code}：${item.message}`)];
    if (input) {
      const button = node("button", `入力欄へ：${input.getAttribute("aria-label")}`, {type: "button"});
      button.addEventListener("click", () => input.focus());
      parts.push(button);
    }
    parts.push(details("診断の参照先と根拠", item));
    return node("div", "", {}, parts);
  }));
}

function inputChanges(before, after) {
  const result = [];
  for (const employee of before.employees) {
    const next = after.employees.find(item => item.id === employee.id);
    for (const [key, label, display] of [
      ["label", "名前", value => value],
      ["skills", "技能", value => value.map(item => item.skill_id).sort().join("・") || "なし"],
      ["availability", "勤務可能時間", value => value.map(range).join("・") || "勤務不可"],
    ]) {
      if (display(employee[key]) !== display(next[key])) result.push(`${employee.label} (${employee.id}) の${label}：${display(employee[key])} → ${display(next[key])}`);
    }
  }
  for (const demand of before.demand) {
    const next = after.demand.find(item => item.id === demand.id);
    if (demand.required_people !== next.required_people) result.push(`${range(demand.interval)}の${roleName(demand.role_id)}：${demand.required_people}人 → ${next.required_people}人`);
  }
  return result;
}

function renderComparison() {
  const area = $("comparison");
  if (!baseline) { area.replaceChildren(node("p", "比較元の検証済み配置はまだありません。元の条件で再計算するか、サンプルへ復元してください。")); return; }
  const input = current?.input || readRequest();
  area.replaceChildren(node("p", `元の条件：${baseline.response.status} · ${baseline.input.request_id}`),
    details("元の条件の確定入力と実結果", baseline));
  if (validPair(baseline)) area.append(node("details", "", {}, [node("summary", "元の担当配置を見る"), renderAssignments(baseline)]));
  if (!input) { area.append(node("p", "入力途中です。入力不備を修正して再計算してください。")); return; }
  const changes = inputChanges(baseline.input, input);
  area.append(node("p", `現在の条件：${current ? current.response.status : "再計算が必要"}`),
    node("ul", "", {}, (changes.length ? changes : ["入力条件の変更はありません。"]).map(text => node("li", text))));
  if (!validPair(baseline) || !validPair(current)) {
    area.append(node("p", "両方に検証済みの配置があるときだけ担当差分を表示します。"));
    return;
  }
  area.append(node("p", `不足合計：元の条件${baseline.response.shortage_summary?.total_person_minutes || 0}人分 → 現在${current.response.shortage_summary?.total_person_minutes || 0}人分`));
  const before = assignmentGrid(baseline), after = assignmentGrid(current);
  const differences = [];
  for (const employee of baseline.input.employees) slots.forEach((slot, index) => {
    const key = `${employee.id}/${index}`;
    if (before.get(key) !== after.get(key)) differences.push(`${employee.label} (${employee.id}) · ${range(slot)}：${roleName(before.get(key))} → ${roleName(after.get(key))}`);
  });
  area.append(node("p", `担当差分：${differences.length}人枠`), node("ul", "", {}, differences.map(text => node("li", text))));
}

function renderResult(message) {
  $("status").textContent = message || (current ? `${stateText[current.response.status]} · ${current.response.status}` : "まだ計算していません。");
  $("output").replaceChildren();
  if (current) {
    if (validPair(current)) $("output").append(renderShortages(current), renderAssignments(current), node("h2", "必要人数の充足"), renderCoverage(current));
    $("output").append(details("計算の詳細・確定入力と実結果", current));
    renderDiagnostics(current.response.diagnostics);
  } else renderDiagnostics([]);
  $("previous").replaceChildren();
  if (previous) $("previous").append(node("details", "", {}, [node("summary", `変更前の結果：${previous.response.status}（現在の条件には無効）`),
    ...(validPair(previous) ? [renderShortages(previous), renderAssignments(previous)] : []), details("変更前の確定入力と実結果", previous)]));
  renderComparison();
}

function renderGuide() {
  const area = $("guide");
  if (!guided) { area.replaceChildren(node("strong", "自由編集"), node("p", "条件を編集し、再計算できます。元の条件と結果は比較欄に残ります。")); return; }
  const step = scenarios[scenarioIndex].steps[stepIndex];
  const apply = node("button", step.restore ? "サンプルへ復元" : "この変更を入力", {type: "button"});
  apply.disabled = pendingStep || !validPair(baseline);
  apply.addEventListener("click", () => {
    if (!validPair(baseline)) return;
    if (step.restore) { resetScenario(scenarioIndex); return; }
    const request = readRequest(true);
    if (!request) { renderResult("入力不備があります。欄を修正してください。"); return; }
    for (const [collection, changes] of Object.entries(step.changes)) {
      for (const [id, values] of Object.entries(changes)) Object.assign(request[collection].find(item => item.id === id), clone(values));
    }
    renderForm(request, true);
    edited();
    pendingStep = true;
    renderGuide();
    $("calculate").focus();
  });
  const free = node("button", "自由に編集する", {type: "button"});
  free.addEventListener("click", () => { guided = false; pendingStep = false; renderGuide(); $("calculate").focus(); });
  area.replaceChildren(node("strong", `試してみる：${scenarios[scenarioIndex].label}`), node("p", step.instruction),
    ...(!baseline ? [node("p", "変更ガイドは元の条件の検証済み配置を確認してから進めます。失敗・未確定の場合は「再計算」で再試行してください。")] : []),
    ...(pendingStep ? [node("p", "変更を入力しました。「再計算」で結果と比較を確認してください。")] : []),
    node("div", "", {class: "actions"}, [apply, free]));
}

function setBusy(value) {
  busy = value;
  $("controls").disabled = value;
  $("json-controls").disabled = value;
  $("result").setAttribute("aria-busy", String(value));
  $("json-result").setAttribute("aria-busy", String(value));
}

function edited() {
  generation++;
  active?.abort();
  active = null;
  setBusy(false);
  changed = true;
  if (current) previous = current;
  current = null;
  readRequest();
  renderResult("条件を変更しました。再計算が必要です。");
}

function acceptResponse(response, request, requestBoundaries = boundaries) {
  if (!response || response.schema_version !== "0.15" || response.request_id !== request.request_id || !stateText[response.status] ||
      !Array.isArray(response.diagnostics) || !Array.isArray(response.objectives) || !response.verification || !response.solver || !response.stats) throw new Error("応答の形式または実行識別子が一致しません。");
  const success = ["OPTIMAL", "FEASIBLE", "PARTIAL"].includes(response.status);
  if (success && request.schema_version !== "0.15") throw new Error("入力の契約版が不正です。");
  if (success ? !validPair({input: request, response}) || !Array.isArray(response.solution.assignments) : response.solution !== null || response.objectives.length !== 0 || response.verification.valid === true) throw new Error("応答の状態と解・独立検証が一致しません。");
  if (!response.diagnostics.every(item => item && typeof item.code === "string" && typeof item.message === "string") ||
      !response.objectives.every(item => item && typeof item.proven_optimal === "boolean" && Number.isFinite(item.value))) throw new Error("応答の診断または評価値が不正です。");
  if (!success) {
    const notPerformed = response.verification.performed === false && response.verification.valid === null &&
      Array.isArray(response.verification.violations) && response.verification.violations.length === 0;
    const failedVerification = response.status === "INTERNAL_ERROR" && response.verification.performed === true && response.verification.valid === false &&
      Array.isArray(response.verification.violations) && response.verification.violations.length > 0 &&
      response.verification.violations.every(item => item && typeof item.code === "string" && typeof item.message === "string" &&
        typeof item.json_pointer === "string" && Array.isArray(item.related_ids) && item.related_ids.every(id => typeof id === "string") &&
        Array.isArray(item.facts) && item.facts.every(fact => fact && typeof fact.name === "string" && Object.hasOwn(fact, "value")));
    if (!notPerformed && !failedVerification) throw new Error("解なし応答の検証状態が不正です。");
    if (response.cost_summary !== null || response.duty_balance_summary !== null) throw new Error("計画がない応答に費用・指定区間の集計があります。");
    if (response.priority_summary !== null) throw new Error("計画がない応答にpriority集計があります。");
    if (response.shortage_summary !== null) throw new Error("計画がない応答に不足集計があります。");
    if (response.day_count_summary !== null) throw new Error("計画がない応答に日数集計があります。");
    if (["fairness_summary", "change_summary", "continuity_summary", "shift_count_balance_summary"].some(name => response[name] !== null)) throw new Error("計画がない応答に集計があります。");
    return;
  }
  if (success && (response.objectives.length !== request.objectives.length || response.objectives.some((item, i) => item.id !== request.objectives[i].id || item.metric !== request.objectives[i].metric || item.duty_id !== request.objectives[i].duty_id || item.balance_id !== request.objectives[i].balance_id))) throw new Error("応答の目的が入力と一致しません。");
  if (request.schema_version === "0.15") {
    const definitions = request.shift_count_balance || [], summaries = response.shift_count_balance_summary;
    if (!success || !definitions.length) {
      if (summaries !== null) throw new Error("対象外の応答に勤務回数集計があります。");
    } else if (!Array.isArray(summaries) || summaries.length !== definitions.length || summaries.some((s, i) =>
      s.id !== definitions[i].id || s.category_id !== definitions[i].category_id || s.unit !== "shifts" || s.scale !== "absolute_deviation" || s.normalized !== false ||
      !Array.isArray(s.employees) || s.employees.length !== definitions[i].employee_targets.length || s.employees.some((e, j) =>
        e.employee_id !== definitions[i].employee_targets[j].employee_id || e.target_count !== definitions[i].employee_targets[j].target_count ||
        !Number.isSafeInteger(e.actual_count) || e.actual_count < 0 || e.deviation_count !== Math.abs(e.actual_count - e.target_count)) ||
      s.total_deviation_count !== s.employees.reduce((total, e) => total + e.deviation_count, 0) ||
      response.objectives.find(o => o.balance_id === s.id)?.value !== s.total_deviation_count)) throw new Error("勤務回数集計が入力・目的と一致しません。");
  }
  if (success && !response.solution.assignments.every(item => item && request.employees.some(employee => employee.id === item.employee_id) &&
      request.roles.some(role => role.id === item.role_id) && requestBoundaries.some(value => Date.parse(value) === Date.parse(item.interval?.start)) &&
      requestBoundaries.some(value => Date.parse(value) === Date.parse(item.interval?.end)) && Date.parse(item.interval.start) < Date.parse(item.interval.end))) throw new Error("担当配置の参照または日時が不正です。");
  if (!success && (request.schema_version === "0.15") && response.day_count_summary !== null) throw new Error("計画がない応答に日数集計があります。");
  const hasPriority = (request.schema_version === "0.15");
  if ((request.schema_version === "0.15")) {
    if (!success && (request.schema_version === "0.15") && (response.cost_summary !== null || response.duty_balance_summary !== null)) throw new Error("計画がない応答に費用・指定区間の集計があります。");
    if (!success) { if (hasPriority && response.priority_summary !== null) throw new Error("計画がない応答にpriority集計があります。"); if (response.shortage_summary !== null) throw new Error("計画がない応答に不足集計があります。"); return; }
    const summary = response.shortage_summary;
    if (!summary || typeof summary.proven_minimal !== "boolean" || !Number.isSafeInteger(summary.total_person_minutes) || !Array.isArray(summary.shortages)) throw new Error("不足集計が不正です。");
    const grid = requestBoundaries.map(Date.parse), positions = new Map(grid.map((value, i) => [value, i]));
    const counts = new Map(), occupied = new Set();
    for (const item of response.solution.assignments) {
      for (let i = positions.get(Date.parse(item.interval.start)); i < positions.get(Date.parse(item.interval.end)); i++) {
        const key = `${item.role_id}/${i}`;
        const employeeSlot = `${item.employee_id}/${i}`;
        if (occupied.has(employeeSlot)) throw new Error("応答に二重配置があります。");
        occupied.add(employeeSlot);
        counts.set(key, (counts.get(key) || 0) + 1);
      }
    }
    const expected = [];
    let total = 0;
    for (const demand of request.demand) {
      let run = null;
      for (let i = positions.get(Date.parse(demand.interval.start)); i < positions.get(Date.parse(demand.interval.end)); i++) {
        const assigned = counts.get(`${demand.role_id}/${i}`) || 0, missing = demand.required_people - assigned;
        const minimum = (request.schema_version === "0.15") ? demand.minimum_people ?? 0 : 0;
        if (assigned < minimum) throw new Error("応答が必須の最低人数を満たしていません。");
        if (missing < 0) throw new Error("応答に過剰配置があります。");
        counts.delete(`${demand.role_id}/${i}`);
        if (missing <= 0) { run = null; continue; }
        total += missing * (grid[i + 1] - grid[i]) / 60000;
        if (run && run.end === grid[i] && run.assigned_people === assigned) run.end = grid[i + 1];
        else {
          run = {demand_id: demand.id, role_id: demand.role_id, start: grid[i], end: grid[i + 1], required_people: demand.required_people, assigned_people: assigned, missing_people: missing};
          if ((request.schema_version === "0.15")) run.minimum_people = minimum;
          expected.push(run);
        }
      }
    }
    const actual = summary.shortages.map(item => ({demand_id: item.demand_id, role_id: item.role_id, start: Date.parse(item.interval?.start), end: Date.parse(item.interval?.end), required_people: item.required_people, assigned_people: item.assigned_people, missing_people: item.missing_people, ...((request.schema_version === "0.15") ? {minimum_people: item.minimum_people} : {})}));
    const proofs = response.objectives.map(item => item.proven_optimal);
    if (hasPriority) {
      const groups = response.priority_summary?.groups;
      const grouped = new Map(request.demand.map(d => [d.priority ?? 0, 0]));
      const priorities = new Map(request.demand.map(d => [d.id, d.priority ?? 0]));
      for (const item of expected) {
        const priority = priorities.get(item.demand_id);
        grouped.set(priority, grouped.get(priority) + (item.end - item.start) / 60000 * item.missing_people);
      }
      const ordered = [...grouped].sort(([a], [b]) => b - a);
      if (!Array.isArray(groups) || groups.length !== ordered.length || groups.some((g, i) =>
        g.priority !== ordered[i][0] || g.total_person_minutes !== ordered[i][1] || typeof g.proven_minimal !== "boolean")) throw new Error("priority別不足が元需要に一致しません。");
      proofs.unshift(summary.proven_minimal, ...groups.map(g => g.proven_minimal));
    }
    if (counts.size || total !== summary.total_person_minutes || JSON.stringify(expected) !== JSON.stringify(actual) ||
        (total > 0) !== (response.status === "PARTIAL") || (!total && !summary.proven_minimal) ||
        (!summary.proven_minimal && proofs.some(Boolean)) || proofs.some((proof, i) => proof && proofs.slice(0, i).includes(false)) ||
        (response.status === "OPTIMAL" && !proofs.every(Boolean)) || (response.status === "FEASIBLE" && proofs.every(Boolean))) throw new Error("不足・状態・最適性の証明が入力と一致しません。");
  } else if (response.status === "PARTIAL") throw new Error("旧契約は不足付き計画に対応していません。");
}

async function calculate() {
  if (busy) return;
  const input = readRequest(true);
  if (!input) { if (current) previous = current; current = null; renderResult("入力不備があります。欄を修正してください。"); return; }
  input.request_id = `playground_${++sequence}`;
  const token = ++generation;
  const controller = new AbortController();
  active = controller;
  if (current) previous = current;
  current = null;
  renderResult("計算中です。入力時の条件で計算しています。");
  setBusy(true);
  let timer;
  try {
    const result = await Promise.race([
      (async () => {
        const response = await fetch("/solve", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(input), signal: controller.signal});
        const value = await response.json();
        if (!response.ok) {
          const error = new Error(value.error?.message || "実行入口から結果を取得できませんでした。");
          error.detail = value.error;
          throw error;
        }
        return value;
      })(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("15秒の待機期限を超えました。サーバーの計算停止を保証するものではありません。")), 15000); }),
    ]);
    if (token !== generation) return;
    acceptResponse(result, input);
    current = {input: clone(input), response: clone(result)};
    if (!baseline && validPair(current) && inputChanges(sample, input).length === 0) baseline = clone(current);
    if (pendingStep) { stepIndex++; pendingStep = false; }
    renderGuide();
    renderResult();
  } catch (error) {
    if (token !== generation) return;
    generation++;
    controller.abort();
    current = null;
    renderResult(`結果を取得できませんでした。${error.message} 再計算で再試行できます。`);
    if (error.detail) {
      renderDiagnostics([error.detail]);
      if (error.detail.code === "DEMO_INPUT_OUT_OF_RANGE") $("status").textContent = "入力不備があります。診断の欄を修正してください。";
    }
  } finally {
    clearTimeout(timer);
    if (active === controller) { active = null; setBusy(false); }
  }
}

async function resetScenario(index) {
  generation++;
  active?.abort();
  active = null;
  scenarioIndex = index;
  stepIndex = 1;
  guided = true;
  pendingStep = changed = false;
  baseline = current = previous = null;
  setBusy(false);
  $("scenario").value = scenarios[index].id;
  renderForm(clone(sample));
  renderGuide();
  renderResult();
  await calculate();
}

$("editor").addEventListener("input", event => { if (event.target.dataset.pointer) edited(); });
$("editor").addEventListener("change", event => { if (event.target.dataset.pointer && event.target.tagName === "SELECT") edited(); });
$("editor").addEventListener("submit", event => { event.preventDefault(); calculate(); });
$("editor").addEventListener("invalid", () => { if (current) previous = current; current = null; renderResult("入力不備があります。欄を修正してください。"); }, true);
$("restore").addEventListener("click", () => resetScenario(scenarioIndex));
$("scenario").addEventListener("change", () => {
  const index = scenarios.findIndex(item => item.id === $("scenario").value);
  if (changed && !window.confirm("変更した条件と比較結果を置き換えます。シナリオを切り替えますか？")) { $("scenario").value = scenarios[scenarioIndex].id; return; }
  resetScenario(index);
});

let jsonPair = null;
const jsonBodyLimit = 2 * 1024 * 1024;

function jsonEdited(message = "JSON を変更しました。再計算が必要です。") {
  generation++;
  active?.abort();
  active = null;
  setBusy(false);
  jsonPair = null;
  $("json-output").replaceChildren();
  $("json-status").textContent = message;
}

async function loadJSON(read) {
  if (busy) return;
  jsonEdited("JSON を読み込んでいます。");
  const token = generation;
  setBusy(true);
  try {
    const text = await read();
    if (token !== generation) return;
    if (new TextEncoder().encode(text).length > jsonBodyLimit) throw new Error("JSON は2 MiB以下にしてください。");
    $("json-input").value = text;
    $("json-status").textContent = "JSON を読み込みました。「JSON で計算」で実行できます。";
  } catch (error) {
    if (token === generation) $("json-status").textContent = `JSON を読み込めませんでした。${error.message}`;
  } finally {
    if (token === generation) setBusy(false);
  }
}

function jsonSlots(request) {
  const window = request.planning_window;
  const step = window.slot_minutes * 60000;
  const first = Date.parse(window.start), end = Date.parse(window.end);
  if (!Number.isFinite(step) || step <= 0 || !(first < end) || (end - first) / step > 3000) throw new Error("応答の計画期間が不正です。");
  const date = new Intl.DateTimeFormat("en-CA", {timeZone: window.timezone, year: "numeric", month: "2-digit", day: "2-digit"});
  const clock = new Intl.DateTimeFormat("ja-JP", {timeZone: window.timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23"});
  return Array.from({length: (end - first) / step}, (_, index) => {
    const start = first + index * step;
    return {start, end: start + step, date: date.format(start), label: `${clock.format(start)}〜${clock.format(start + step)}`};
  });
}

function renderJSONDay(pair, daySlots, area, showAll = false) {
  const roles = new Map(pair.input.roles.map(role => [role.id, role.label || role.id]));
  const assignments = new Map(), work = new Map();
  const covers = (interval, slot) => Date.parse(interval.start) <= slot.start && Date.parse(interval.end) >= slot.end;
  for (const assignment of pair.response.solution.assignments) daySlots.forEach((slot, index) => {
    if (covers(assignment.interval, slot)) assignments.set(`${assignment.employee_id}/${index}`, assignment.role_id);
  });
  for (const shift of pair.response.solution.shifts || []) {
    for (const segment of shift.segments || [{interval: shift.interval, breaks: shift.breaks}]) daySlots.forEach((slot, index) => {
      if (covers(segment.interval, slot)) work.set(`${shift.employee_id}/${index}`, segment.breaks.some(interval => covers(interval, slot)) ? "休憩" : "待機");
    });
  }
  let visible = daySlots.map((slot, index) => ({slot, index}));
  if (!showAll) {
    const active = visible.filter(({slot, index}) => pair.input.demand.some(item => item.required_people > 0 && covers(item.interval, slot)) ||
      pair.input.employees.some(employee => work.has(`${employee.id}/${index}`)));
    if (active.length) visible = active;
  }
  const rows = pair.input.employees.map(employee => node("tr", "", {}, [
    node("th", employee.label || employee.id, {scope: "row"}), ...visible.map(({slot, index}) => {
      const key = `${employee.id}/${index}`, role = assignments.get(key);
      const empty = pair.input.problem_type === "roster" ? work.get(key) || "勤務なし" :
        employee.availability.some(interval => covers(interval, slot)) ? "担当なし" : "勤務可能時間外";
      return node("td", roles.get(role) || empty, {class: ["kitchen", "hall", "washing"].includes(role) ? role : ""});
    }),
  ]));
  const coverage = pair.input.roles.map(role => node("tr", "", {}, [
    node("th", role.label || role.id, {scope: "row"}), ...visible.map(({slot, index}) => {
      const count = pair.input.employees.filter(employee => assignments.get(`${employee.id}/${index}`) === role.id).length;
      const required = pair.input.demand.find(item => item.role_id === role.id && covers(item.interval, slot))?.required_people || 0;
      return coverageCell(count, required);
    }),
  ]));
  area.replaceChildren(scroll("JSON の担当配置表", table(`${daySlots[0].date} · ${verificationText(pair.response)}`, ["従業員", ...visible.map(({slot}) => slot.label)], rows)),
    scroll("JSON の需要充足表", table("配置人数 / 必要人数", ["役割", ...visible.map(({slot}) => slot.label)], coverage)));
}

function renderJSONResult() {
  const pair = jsonPair, result = pair.response;
  const area = $("json-output");
  area.replaceChildren();
  if (validPair(pair)) {
    area.append(renderShortages(pair));
    for (const summary of result.day_count_summary || []) {
      area.append(node("p", `${summary.constraint_id} (${summary.interval.start}〜${summary.interval.end})：${summary.employees.map(e => `${e.employee_id} 勤務${e.work_days}日・占有${e.occupied_days}日・完全休日${e.days_off}日`).join(" / ")}`));
    }
    for (const summary of result.shift_count_balance_summary || []) {
      area.append(node("p", `${summary.label} (${summary.evaluation_period.start}〜${summary.evaluation_period.end})：偏差合計${summary.total_deviation_count}回 / ${summary.employees.map(e => `${e.employee_id} 目標${e.target_count}回・実際${e.actual_count}回・偏差${e.deviation_count}回`).join(" / ")}`));
    }
    const grid = jsonSlots(pair.input);
    area.append(node("p", `${pair.input.employees.length}人 · ${new Set(grid.map(slot => slot.date)).size}日 · ${pair.input.planning_window.slot_minutes}分刻み · ${grid.length}時間枠 · ${verificationText(result)} · 総処理時間 ${result.stats.elapsed_seconds.toFixed(2)}秒`));
    const select = node("select", "", {id: "json-day"});
    select.append(...[...new Set(grid.map(slot => slot.date))].map(date => node("option", date, {value: date})));
    const tables = node("div");
    const all = node("input", "", {id: "json-all-slots", type: "checkbox"});
    const render = () => renderJSONDay(pair, grid.filter(slot => slot.date === select.value), tables, all.checked);
    select.addEventListener("change", render);
    all.addEventListener("change", render);
    area.append(node("div", "", {class: "toolbar"}, [node("label", "表示する日付", {for: "json-day"}), select,
      node("label", "", {}, [all, document.createTextNode(" 全時間枠を表示")])]),
      node("p", "通常は需要・勤務がある時間枠を表示します。", {class: "note"}), tables);
    render();
  }
  area.append(...result.diagnostics.map(item => {
    const facts = new Map((item.facts || []).map(fact => [fact.name, fact.value]));
    const required = facts.has("required_start") && facts.has("required_end") ? ` 判定に必要な期間：${facts.get("required_start")}〜${facts.get("required_end")}` : "";
    return node("p", `${item.code}：${item.message} (${item.json_pointer ?? ""})${required}`);
  }),
    details("診断・目的・確定入力と実結果", pair));
}

async function calculateJSON() {
  if (busy) return;
  const text = $("json-input").value;
  jsonEdited("計算中です。JSON の条件で計算しています。");
  const token = generation, controller = new AbortController();
  active = controller;
  setBusy(true);
  let timer;
  try {
    if (new TextEncoder().encode(text).length > jsonBodyLimit) throw new Error("JSON は2 MiB以下にしてください。");
    const result = await Promise.race([
      (async () => {
        // 原文を送信し、サーバーの厳密な読み取りで重複キーも検出する。
        const response = await fetch("/solve-json", {method: "POST", headers: {"Content-Type": "application/json"}, body: text, signal: controller.signal});
        const value = await response.json();
        if (!response.ok) throw new Error(`${value.error?.code || "HTTP_ERROR"}：${value.error?.message || "結果を取得できませんでした。"} (${value.error?.json_pointer ?? ""})`);
        return value;
      })(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("11分の待機期限を超えました。サーバーの計算停止を保証するものではありません。")), 660000); }),
    ]);
    if (token !== generation) return;
    const input = JSON.parse(text);
    const expected = {...input, request_id: typeof input?.request_id === "string" ? input.request_id : null};
    const requestBoundaries = ["OPTIMAL", "FEASIBLE", "PARTIAL"].includes(result.status) ?
      [input.planning_window.start, ...jsonSlots(input).map(slot => new Date(slot.end).toISOString())] : [];
    acceptResponse(result, expected, requestBoundaries);
    jsonPair = {input, response: result};
    renderJSONResult();
    $("json-status").textContent = `${result.status === "PARTIAL" && input.problem_type === "roster" ? "必要人数に不足があります。未完成の勤務計画を出力しました。" : stateText[result.status]} · ${result.status}`;
  } catch (error) {
    if (token !== generation) return;
    controller.abort();
    jsonPair = null;
    $("json-output").replaceChildren();
    $("json-status").textContent = `計算できませんでした。${error.message}`;
  } finally {
    clearTimeout(timer);
    if (active === controller) { active = null; setBusy(false); }
  }
}

$("json-input").addEventListener("input", () => jsonEdited());
$("json-editor").addEventListener("submit", event => { event.preventDefault(); calculateJSON(); });
$("json-load-sample").addEventListener("click", () => {
  const name = $("json-sample").value;
  loadJSON(async () => {
    const response = await fetch(`/samples/${name}.json`);
    if (!response.ok) throw new Error("サンプルを取得できませんでした。");
    return response.text();
  });
});
$("json-file").addEventListener("change", () => {
  const file = $("json-file").files[0];
  if (file) loadJSON(async () => {
    if (file.size > jsonBodyLimit) throw new Error("ファイルは2 MiB以下にしてください。");
    return new TextDecoder("utf-8", {fatal: true}).decode(await file.arrayBuffer());
  });
  $("json-file").value = "";
});

async function start() {
  try {
    [sample, scenarios] = await Promise.all(["lunch", "scenarios"].map(async name => {
      const response = await fetch(`/samples/${name}.json`);
      if (!response.ok) throw new Error("サンプルを読み込めませんでした。");
      return response.json();
    }));
    slots = sample.demand.filter(item => item.role_id === sample.roles[0].id).map(item => item.interval);
    boundaries = [slots[0].start, ...slots.map(slot => slot.end)];
    $("scenario").append(...scenarios.map(item => node("option", item.label, {value: item.id})));
    await resetScenario(0);
  } catch (error) {
    $("status").textContent = `サンプルの取得に失敗しました。${error.message} ページを再読み込みしてください。`;
  }
}
start();
