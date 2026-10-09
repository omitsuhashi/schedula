"use strict";

function renderCountFields() {
  const area = $("feature-fields"), targets = feature.input.shift_count_balance[0].employee_targets;
  for (const employee of feature.input.employees) {
    const id = `feature-target-${employee.id}`;
    const select = node("select", "", {id}, [node("option", "目標未指定（対象外）", {value: ""}),
      ...[0, 1, 2, 3].map(value => node("option", `${value}回`, {value}))]);
    select.value = targets.find(item => item.employee_id === employee.id)?.target_count ?? "";
    select.addEventListener("change", () => {
      const input = clone(feature.input);
      input.shift_count_balance[0].employee_targets = input.employees.flatMap(employee => {
        const value = $(`feature-target-${employee.id}`).value;
        return value === "" ? [] : [{employee_id: employee.id, target_count: Number(value)}];
      });
      featureEdited(input);
      select.setCustomValidity(input.shift_count_balance[0].employee_targets.length ? "" : "少なくとも一人の目標を指定してください。");
      // 両者未指定から一人を戻した場合も、前の入力エラーを解除する。
      for (const e of input.employees) $(`feature-target-${e.id}`).setCustomValidity(select.validationMessage);
    });
    area.append(node("label", `${employee.label}の目標勤務回数`, {for: id}), select);
  }
  const category = feature.input.shift_categories[0];
  const start = node("select", "", {id: "feature-category-start"}, [20, 22].map(hour => node("option", `${hour}:00〜翌00:00（10月5・6日）`, {value: hour})));
  start.value = Number(category.intervals[0].start.slice(11, 13));
  start.addEventListener("change", () => {
    const input = clone(feature.input);
    for (const interval of input.shift_categories[0].intervals) interval.start = `${interval.start.slice(0, 11)}${start.value}:00:00+09:00`;
    featureEdited(input);
  });
  const threshold = node("input", "", {id: "feature-number", type: "number", required: "", min: 1, max: 480, step: 1});
  threshold.value = category.min_overlap_minutes;
  threshold.addEventListener("input", () => {
    const input = clone(feature.input); input.shift_categories[0].min_overlap_minutes = Number(threshold.value); featureEdited(input);
  });
  area.append(node("label", "夜勤の分類区間（Asia/Tokyo）", {for: start.id}), start,
    node("label", "分類に必要な重なり（分）", {for: threshold.id}), threshold);
}

function countIndicators(pair) {
  const summary = pair.response.shift_count_balance_summary[0];
  return [`目標偏差合計 ${summary.total_deviation_count}回`, ...pair.input.employees.map(employee => {
    const row = summary.employees.find(row => row.employee_id === employee.id);
    return row ? `${employee.label}：目標${row.target_count}回 / 実績・選択勤務を含む実回数${row.actual_count}回 / 絶対偏差${row.deviation_count}回` : `${employee.label}：目標未指定・対象外（公開集計なし）`;
  })];
}

function countPremises(input) {
  const category = input.shift_categories[0], balance = input.shift_count_balance[0];
  return node("div", "", {}, [node("p", `評価期間：${datedRange(balance.evaluation_period)}`),
    node("p", `勤務分類：${category.intervals.map(datedRange).join(" / ")}・休憩を除く原勤務全体との重なり${category.min_overlap_minutes}分以上`),
    node("p", "原勤務の最初の開始日時で1件ずつ数えます。Aliceの確認済み実績1件、未来の確定勤務なし。目標未達は必須条件違反ではありません。")]);
}
