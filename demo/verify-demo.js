"use strict";

function kitchenEmployee(input) { return input.solution.assignments.find(item => item.role_id === "kitchen")?.employee_id || ""; }
function editKitchen(input, employee) {
  const next = clone(input);
  next.solution.assignments = next.solution.assignments.filter(item => item.role_id !== "kitchen");
  if (employee) next.solution.assignments.unshift({...clone(feature.initial.solution.assignments.find(item => item.role_id === "kitchen")), employee_id: employee});
  return next;
}
function verifyChanges(before, after) {
  const name = value => value ? after.request.employees.find(item => item.id === value)?.label || value : "担当なし";
  return kitchenEmployee(before) === kitchenEmployee(after) ? [] : [`10月5日10:00〜11:00のキッチン担当：${name(kitchenEmployee(before))} → ${name(kitchenEmployee(after))} · 従業員`];
}
function renderVerifyFields() {
  const select = node("select", "", {id: "feature-kitchen"}, [node("option", "担当なし", {value: ""}),
    ...feature.input.request.employees.map(item => node("option", item.label, {value: item.id}))]);
  select.value = kitchenEmployee(feature.input);
  select.addEventListener("change", () => featureEdited(editKitchen(feature.input, select.value)));
  $("feature-fields").append(node("label", "10月5日10:00〜11:00のキッチン担当（Asia/Tokyo）", {for: select.id}), select);
}

function acceptVerification(response, input) {
  const request = input.request, success = ["VALID", "PARTIAL"].includes(response?.status);
  const fields = ["schema_version", "request_id", "status", "verification", "demand_satisfied", "objectives", "diagnostics", "stats",
    "shortage_summary", "priority_summary", "fairness_summary", "change_summary", "continuity_summary", "cost_summary", "duty_balance_summary", "day_count_summary", "shift_count_balance_summary"];
  const diagnostic = item => item && typeof item.code === "string" && typeof item.message === "string" &&
    typeof item.json_pointer === "string" && Array.isArray(item.related_ids) && item.related_ids.every(id => typeof id === "string") &&
    Array.isArray(item.facts) && item.facts.every(fact => fact && typeof fact.name === "string" && Object.hasOwn(fact, "value"));
  if (!response || response.schema_version !== "0.15" || response.request_id !== request.request_id ||
    Object.keys(response).length !== fields.length || fields.some(field => !Object.hasOwn(response, field)) ||
    !["VALID", "PARTIAL", "INVALID_INPUT", "INVALID_PLAN", "INTERNAL_ERROR"].includes(response.status) ||
    Object.hasOwn(response, "solution") || Object.hasOwn(response, "solver") ||
    !Array.isArray(response.diagnostics) || !response.diagnostics.every(diagnostic) || !Array.isArray(response.objectives) ||
    !response.stats || !Number.isFinite(response.stats.elapsed_seconds) || response.stats.elapsed_seconds < 0 ||
    !response.verification || !Array.isArray(response.verification.violations) || !response.verification.violations.every(diagnostic))
    throw new Error("公開verifyの応答形式または実行識別子が一致しません。");
  const {performed, valid, violations} = response.verification;
  if (success ? performed !== true || valid !== true || violations.length !== 0 : response.status === "INVALID_PLAN" ?
    performed !== true || valid !== false || !violations.length : performed !== false || valid !== null || violations.length)
    throw new Error("公開verifyの状態と検証結果が一致しません。");
  if (success) {
    if (request.schema_version !== "0.15" || response.demand_satisfied !== (response.status === "VALID") ||
      response.objectives.length !== request.objectives.length || response.objectives.some((item, i) =>
        item.id !== request.objectives[i].id || item.metric !== request.objectives[i].metric || item.proven_optimal !== false || !Number.isFinite(item.value)) ||
      !response.shortage_summary || response.shortage_summary.proven_minimal !== false ||
      !Number.isSafeInteger(response.shortage_summary.total_person_minutes) || response.shortage_summary.total_person_minutes < 0 ||
      (response.status === "VALID") !== (response.shortage_summary.total_person_minutes === 0) ||
      !Array.isArray(response.shortage_summary.shortages) || !response.priority_summary ||
      !Array.isArray(response.priority_summary.groups) || response.priority_summary.groups.some(item => item.proven_minimal !== false))
      throw new Error("公開verifyに不正な集計または探索の証明があります。");
    let total = 0;
    for (const item of response.shortage_summary.shortages) {
      const demand = request.demand.find(demand => demand.id === item.demand_id);
      const minutes = (Date.parse(item.interval?.end) - Date.parse(item.interval?.start)) / 60000;
      if (!demand || item.role_id !== demand.role_id || !Number.isSafeInteger(minutes) || minutes <= 0 ||
        Date.parse(item.interval.start) < Date.parse(demand.interval.start) || Date.parse(item.interval.end) > Date.parse(demand.interval.end) ||
        item.required_people !== demand.required_people || item.minimum_people !== (demand.minimum_people ?? 0) ||
        !Number.isSafeInteger(item.assigned_people) || item.assigned_people < item.minimum_people ||
        !Number.isSafeInteger(item.missing_people) || item.missing_people <= 0 || item.missing_people !== item.required_people - item.assigned_people)
        throw new Error("公開verifyの不足一覧が不正です。");
      total += minutes * item.missing_people;
    }
    if (total !== response.shortage_summary.total_person_minutes) throw new Error("公開verifyの不足合計が一覧と一致しません。");
  } else if (response.demand_satisfied !== null || response.objectives.length ||
    Object.entries(response).some(([key, value]) => key.endsWith("_summary") && value !== null))
    throw new Error("無効な検証結果に計画の評価があります。");
}

function renderVerify(message) {
  const area = $("feature-output"), pair = feature.current, input = feature.input;
  const changes = verifyChanges(feature.initial, input);
  const texts = {VALID: "必須条件と需要を満たす編集案です。", PARTIAL: "必須条件を満たしますが需要に不足があります。",
    INVALID_PLAN: "必須条件違反のある編集案です。担当を直して再検証できます。", INVALID_INPUT: "元入力が不正です。検証は未実施です。", INTERNAL_ERROR: "検証を完了できませんでした。再実行できます。"};
  $("feature-status").textContent = message || (pair ? `${pair.response.status} · ${texts[pair.response.status]}` : "未検証：担当を編集したため前の検証は現在の案には無効です。再検証してください。");
  area.replaceChildren(node("h3", "入力差分"), node("ul", "", {}, (changes.length ? changes : ["初期の編集案から変更なし"]).map(text => node("li", text))));
  if (feature.baseline) area.append(node("p", `初期比較元：${feature.baseline.response.status} / 現在：${pair?.response.status || "未検証"}`));
  area.append(node("h3", "この機能の指標"), node("p", "最適性：認定しない / 不足最小性：認定しない（公開verifyは探索しません）"));
  if (pair) {
    area.append(node("p", `有効性：${pair.response.verification.valid === true ? "公開検証成功" : pair.response.verification.performed ? "必須条件違反" : "未検証"}`));
    if (pair.response.shortage_summary) area.append(renderShortages({input: input.request, response: pair.response}));
    if (feature.baseline?.response.shortage_summary && pair.response.shortage_summary)
      area.append(node("p", `初期不足${feature.baseline.response.shortage_summary.total_person_minutes}人分 → 現在不足${pair.response.shortage_summary.total_person_minutes}人分`));
    area.append(...pair.response.diagnostics.map(item => node("p", `${item.code}：${item.message} · ${item.json_pointer}`)));
  }
  const violations = pair?.response.verification.violations || [];
  const rows = input.request.roles.map(role => {
    const index = input.solution.assignments.findIndex(item => item.role_id === role.id), assignment = input.solution.assignments[index];
    const pointer = index < 0 ? "担当なし" : `/assignments/${index}`;
    return node("tr", "", {}, [node("th", role.label, {scope: "row"}), node("td", datedRange(input.request.demand.find(item => item.role_id === role.id).interval)),
      node("td", assignment ? input.request.employees.find(item => item.id === assignment.employee_id)?.label || assignment.employee_id : "担当なし"),
      node("td", pointer), node("td", violations.filter(item => item.json_pointer === pointer).map(item => `${item.code}：${item.message}`).join(" / "))]);
  });
  area.append(node("h3", "検査対象の編集案"), node("p", "無効案・未検証の案もここに表示します。有効な勤務表として採用する操作はありません。"),
    scroll("検査対象の表", table("固定の勤務2件に対する担当編集案（最適化結果ではありません）", ["役割", "時間帯", "担当者", "JSON位置", "この位置の違反"], rows)));
  if (pair) area.append(details("元Request・編集案・公開verify結果", pair));
  if (feature.baseline) area.append(details("初期入力と公開検証", feature.baseline));
  if (feature.previous) area.append(details("変更前の検証（現在の案には無効）", feature.previous));
}
