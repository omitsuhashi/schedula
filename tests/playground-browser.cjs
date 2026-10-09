// 実ブラウザーと実エンジンの結合確認。再現しにくい状態だけ応答サンプルを使う。
const assert = require("node:assert/strict");
const {spawn, spawnSync} = require("node:child_process");
const {readFileSync, mkdirSync, writeFileSync} = require("node:fs");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
const scenarios = JSON.parse(readFileSync("examples/playground/scenarios.json", "utf8"));
const report = {scenarios: [], response_samples: [], interactions: []};
let server, browser;

async function status(page, value) {
  await page.waitForFunction(text => document.getElementById("status").textContent.includes(text) && !document.getElementById("controls").disabled, value);
}

async function verified(page, expected) {
  await status(page, expected.status);
  const pair = await page.evaluate(() => structuredClone(current));
  assert.equal(pair.input.schema_version, "0.15");
  assert.equal(pair.response.schema_version, "0.15");
  assert.equal(pair.response.status, expected.status);
  if (["OPTIMAL", "PARTIAL"].includes(expected.status)) {
    assert.deepEqual([pair.response.verification.performed, pair.response.verification.valid], [true, true]);
    const count = pair.response.solution.assignments.reduce((sum, item) => sum + (Date.parse(item.interval.end) - Date.parse(item.interval.start)) / 1800000, 0);
    assert.equal(count, expected.assigned_slots);
    assert.equal(await page.locator("#output table").count(), expected.status === "PARTIAL" ? 3 : 2);
    if (expected.status === "PARTIAL") {
      assert.equal(pair.response.shortage_summary.total_person_minutes, expected.total_person_minutes);
      assert.ok((await page.locator("#output").innerText()).includes("不足1人"));
      assert.ok((await page.locator("#output").innerText()).includes("最低人数を含む必須条件"));
      assert.ok((await page.locator("#comparison").innerText()).includes("担当差分："));
    }
  } else {
    assert.equal(pair.response.solution, null);
    assert.equal(await page.locator("#output table").count(), 0);
    assert.ok(pair.response.diagnostics.some(item => item.code === expected.diagnostic.code));
    assert.ok(!(await page.locator("#comparison").innerText()).includes("担当差分："));
  }
  return pair;
}

async function reviewRegressions(page, url) {
  const yuiStart = page.locator('[data-pointer="/employees/4/availability/0/start"]');
  const yuiEnd = page.locator('[data-pointer="/employees/4/availability/0/end"]');
  const yuiUnavailable = page.locator('[data-pointer="/employees/4/availability"]');
  for (const [start, end] of [["11:00", "13:00"], ["11:30", "12:30"]]) {
    await page.locator("#restore").click();
    await verified(page, {status: "OPTIMAL", assigned_slots: 22});
    const interval = {start: `2026-10-06T${start}:00+09:00`, end: `2026-10-06T${end}:00+09:00`};
    await yuiStart.selectOption(interval.start);
    await yuiEnd.selectOption(interval.end);
    await yuiUnavailable.check();
    assert.deepEqual(await page.evaluate(() => readRequest().employees[4].availability), []);
    await page.getByRole("button", {name: "この変更を入力", exact: true}).click();
    await yuiUnavailable.uncheck();
    assert.equal(await yuiStart.inputValue(), interval.start);
    assert.equal(await yuiEnd.inputValue(), interval.end);
    assert.deepEqual(await page.evaluate(() => readRequest().employees[4].availability), [interval]);
    await page.locator("#restore").click();
    await verified(page, {status: "OPTIMAL", assigned_slots: 22});
    assert.equal(await yuiEnd.inputValue(), "2026-10-06T13:00:00+09:00");
  }
  report.interactions.push("勤務不可→需要ガイド→解除でサンプル時刻・編集済み時刻を保持、復元でサンプル時刻へ戻る");

  for (const kind of ["initial-http-validation", "initial-unknown-baseline", "initial-http-guide"]) {
    let requests = 0;
    await page.route("**/solve", async route => {
      requests++;
      if (requests !== 1) { await route.continue(); return; }
      if (kind === "initial-unknown-baseline") {
        const result = await (await route.fetch()).json();
        Object.assign(result, {status: "UNKNOWN", solution: null, objectives: [], shortage_summary: null, priority_summary: null, verification: {performed: false, valid: null, violations: []}});
        await route.fulfill({json: result});
      } else await route.fulfill({status: 500, json: {error: {code: "SERVER_ERROR", message: "初回失敗の応答サンプル", json_pointer: null}}});
    });
    await page.goto(url);
    await status(page, kind === "initial-unknown-baseline" ? "UNKNOWN" : "結果を取得できませんでした");
    assert.equal(await page.evaluate(() => baseline), null);
    assert.ok(!(await page.locator("#comparison").innerText()).includes("計算結果を待っています"));
    const apply = page.getByRole("button", {name: "この変更を入力", exact: true});
    assert.equal(await apply.isDisabled(), true);
    if (kind === "initial-http-validation") {
      const name = page.locator('[data-pointer="/employees/0/label"]');
      await name.fill("あ".repeat(21));
      await page.locator("#calculate").click();
      await status(page, "入力不備");
      assert.equal(requests, 1);
      await name.fill("あおい");
      assert.equal(await name.evaluate(input => input.validationMessage), "");
      const start = page.locator('[data-pointer="/employees/0/availability/0/start"]');
      const end = page.locator('[data-pointer="/employees/0/availability/0/end"]');
      await start.selectOption("2026-10-06T14:00:00+09:00");
      await page.locator("#calculate").click();
      await status(page, "入力不備");
      await start.selectOption("2026-10-06T11:00:00+09:00");
      assert.equal(await end.evaluate(input => input.validationMessage), "");
      assert.equal(requests, 1);
    }
    if (kind === "initial-http-guide") {
      const before = await page.evaluate(() => readRequest());
      await apply.evaluate(button => button.dispatchEvent(new MouseEvent("click", {bubbles: true})));
      assert.deepEqual(await page.evaluate(() => readRequest()), before);
      assert.equal(requests, 1);
    }
    await page.locator("#calculate").click();
    const initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
    assert.equal(requests, 2);
    assert.deepEqual(await page.evaluate(() => baseline), initial);
    assert.equal(await apply.isDisabled(), false);
    await apply.click();
    await page.locator("#calculate").click();
    await verified(page, {status: "OPTIMAL", assigned_slots: 23});
    assert.equal(requests, 3);
    assert.deepEqual(await page.evaluate(() => baseline), initial);
    assert.ok((await page.locator("#comparison").innerText()).includes("担当差分："));
    report.response_samples.push(kind);
    await page.unroute("**/solve");
  }
  await page.goto(url);
}

async function largeShortageRendering(page) {
  // 描画上限の合成データ。実ソルバーの不足集計や応答受理を検証するものではない。
  assert.equal(await page.evaluate(() => node("div", "", {},
    Array.from({length: 150000}, () => document.createTextNode(""))).childNodes.length), 150000);
  const expected = await page.evaluate(() => {
    jsonPair = structuredClone(jsonPair);
    jsonPair.input.planning_window.end = new Date(Date.parse(jsonPair.input.planning_window.end) + 86400000).toISOString();
    const summary = jsonPair.response.shortage_summary;
    const item = summary.shortages[0];
    summary.shortages = Array.from({length: 150000}, (_, index) => ({...item, demand_id: `render_${index}`}));
    summary.total_person_minutes = 150000 * item.missing_people * (Date.parse(item.interval.end) - Date.parse(item.interval.start)) / 60000;
    summary.proven_minimal = false;
    jsonPair.response.objectives.forEach(objective => { objective.proven_optimal = false; });
    renderJSONResult();
    return {total: summary.total_person_minutes, date: jsonSlots(jsonPair.input).at(-1).date,
      solution: jsonPair.response.solution};
  });
  const output = page.locator("#json-output");
  const shortages = output.getByRole("region", {name: "不足の一覧", exact: true});
  const pages = output.getByRole("combobox", {name: "不足一覧のページ", exact: true});
  assert.equal(await shortages.locator("tbody tr").count(), 100);
  assert.ok((await shortages.locator("caption").innerText()).includes("全150000件中1〜100件"));
  assert.ok((await output.locator("p").first().innerText()).includes(`不足合計：${expected.total}人分`));
  await pages.selectOption("1499");
  assert.equal(await shortages.locator("tbody tr").count(), 100);
  assert.equal(await shortages.locator("tbody th").last().innerText(), "render_149999");
  await pages.selectOption("0");
  await pages.focus();
  await page.keyboard.press("2");
  await page.keyboard.press("Enter");
  assert.ok((await shortages.locator("caption").innerText()).includes("101〜200件"));
  await page.locator("#json-day").selectOption(expected.date);
  assert.ok((await output.getByRole("region", {name: "JSON の担当配置表", exact: true}).locator("caption").innerText()).includes(expected.date));
  assert.equal(await output.locator("table").count(), 3);
  const retained = await page.evaluate(() => {
    const detail = JSON.parse(document.querySelector("#json-output > details pre").textContent);
    return {count: jsonPair.response.shortage_summary.shortages.length,
      detailCount: detail.response.shortage_summary.shortages.length,
      last: detail.response.shortage_summary.shortages.at(-1).demand_id,
      solution: jsonPair.response.solution};
  });
  assert.equal(retained.count, 150000);
  assert.equal(retained.detailCount, 150000);
  assert.equal(retained.last, "render_149999");
  assert.deepEqual(retained.solution, expected.solution);
  assert.ok((await page.locator("#json-status").innerText()).includes("PARTIAL"));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  report.response_samples.push({shortage_rendering: "合成データ・実ブラウザー", count: retained.count,
    detail_count: retained.detailCount, visible_rows: 100, selected_date: expected.date});
}

async function jsonInputChecks(page) {
  const waitJSON = text => page.waitForFunction(value =>
    document.getElementById("json-status").textContent.includes(value) && !busy,
  text, {timeout: 120000});
  await page.locator("#json-demo summary").first().click();
  await page.locator("#json-load-sample").click();
  await waitJSON("読み込みました");
  const sample = JSON.parse(await page.locator("#json-input").inputValue());
  assert.equal(sample.employees.length, 100);
  assert.equal(sample.planning_window.slot_minutes, 30);
  const oldBaseline = await page.evaluate(() => baseline);
  await page.locator("#json-calculate").click();
  await page.waitForFunction(() => jsonPair !== null && !busy, null, {timeout: 120000});
  const large = await page.evaluate(() => jsonPair);
  assert.ok(["OPTIMAL", "FEASIBLE"].includes(large.response.status));
  assert.deepEqual(large.input, sample);
  assert.equal(large.response.verification.valid, true);
  assert.ok(large.response.solution.shifts.length >= 1200);
  assert.equal(await page.locator("#json-day option").count(), 30);
  assert.equal(await page.locator("#json-output table").first().locator("tbody tr").count(), 100);
  assert.equal(await page.locator("#json-output table").first().locator("thead th").count(), 17);
  assert.ok((await page.locator("#json-output").innerText()).includes("休憩"));
  assert.ok((await page.locator("#json-output").innerText()).includes("勤務なし"));
  await page.locator("#json-day").selectOption("2026-10-30");
  assert.ok((await page.locator("#json-output caption").first().innerText()).includes("2026-10-30"));
  await page.locator("#json-all-slots").check();
  assert.equal(await page.locator("#json-output table").first().locator("thead th").count(), 49);
  await page.locator("#json-all-slots").uncheck();
  assert.deepEqual(await page.evaluate(() => baseline), oldBaseline);
  await page.setViewportSize({width: 1440, height: 1000});
  await page.locator("#json-result").scrollIntoViewIfNeeded();
  await page.screenshot({path: "test-results/playground-json-100.png"});
  await page.setViewportSize({width: 390, height: 844});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path: "test-results/playground-json-mobile.png"});
  report.interactions.push({json_sample: "100人・30日・30分", status: large.response.status, verification: large.response.verification, stats: large.response.stats});

  for (const name of ["roster", "overnight", "split_roster", "infeasible", "invalid-input", "roster_conditions", "partial_replan_preserve_assigned", "partial_replan_rebuild", "partial_assignment", "partial_roster", "demand_priority"]) {
    const input = readFileSync(`examples/${name}.json`);
    const partial = name === "demand_priority" || name.startsWith("partial_") && name !== "partial_replan_rebuild";
    await page.locator("#json-file").setInputFiles({name: `${name}.json`, mimeType: "application/json", buffer: input});
    await waitJSON("読み込みました");
    assert.equal(await page.locator("#json-output table").count(), 0);
    await page.locator("#json-calculate").click();
    await waitJSON(name === "infeasible" ? "INFEASIBLE" : name === "invalid-input" ? "INVALID_INPUT" : partial ? "PARTIAL" : "OPTIMAL");
    assert.deepEqual(await page.evaluate(() => jsonPair.input), JSON.parse(input));
    if (name === "demand_priority") {
      assert.ok((await page.locator("#json-output").innerText()).includes("priority 10：不足0人分"));
      assert.ok((await page.locator("#json-output").innerText()).includes("priority 0：不足30人分"));
    }
    assert.equal(await page.locator("#json-output table").count(), ["infeasible", "invalid-input"].includes(name) ? 0 : partial ? 3 : 2);
  }
  await largeShortageRendering(page);
  for (const name of ["scheduled_cost", "duty_balance", "continuity_duty_balance"]) {
    const input = JSON.parse(readFileSync(`examples/${name}.json`, "utf8"));
    await page.locator("#json-input").fill(JSON.stringify(input));
    await page.locator("#json-calculate").click();
    await page.waitForFunction(() => !busy);
    const pair = await page.evaluate(() => jsonPair);
    assert.ok(pair, await page.locator("#json-status").innerText());
    assert.deepEqual(pair.input, input);
    assert.equal(pair.response.schema_version, input.schema_version);
    assert.equal(pair.response.status, "OPTIMAL");
    assert.equal(pair.response.verification.valid, true);
    assert.equal(pair.response.cost_summary.total_units, name === "scheduled_cost" ? 108000 : name === "continuity_duty_balance" ? 432000 : 2016000);
    if (name !== "scheduled_cost") {
      assert.equal(pair.response.duty_balance_summary[0].total_deviation_minutes, 0);
      assert.equal(pair.response.objectives[0].duty_id, input.objectives[0].duty_id);
      assert.match(await page.evaluate(() => {
        const {input, response} = structuredClone(jsonPair);
        response.objectives[0].duty_id = "other_duty";
        try { acceptResponse(response, input); return ""; } catch (error) { return error.message; }
      }), /目的が入力と一致しません/);
      for (const status of ["INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "BACKEND_UNAVAILABLE", "INTERNAL_ERROR"]) {
        for (const retained of [null, "cost_summary", "duty_balance_summary"]) {
          const message = await page.evaluate(({status, retained}) => {
            const {input, response} = structuredClone(jsonPair);
            Object.assign(response, {status, solution: null, objectives: [], fairness_summary: null, change_summary: null, continuity_summary: null, shortage_summary: null, priority_summary: null, cost_summary: null, duty_balance_summary: null, day_count_summary: null, shift_count_balance_summary: null, verification: {performed: false, valid: null, violations: []}});
            if (retained) response[retained] = jsonPair.response[retained];
            try { acceptResponse(response, input); return ""; } catch (error) { return error.message; }
          }, {status, retained});
          if (retained) assert.match(message, /計画がない応答に費用・指定区間の集計があります/, `${status}/${retained}`);
          else assert.equal(message, "", status);
        }
      }
      report.response_samples.push(`契約${input.schema_version}の全5失敗状態：費用・指定区間の集計を個別に残すと拒否、両方nullなら受理`);
    }
    if (name === "continuity_duty_balance") {
      assert.deepEqual(pair.response.duty_balance_summary[0].employees.map(e => e.actual_minutes), [240, 240]);
      assert.equal(pair.response.solution.shifts[0].employee_id, "bob");
    }
  }
  const daysInput = JSON.parse(readFileSync("examples/day_counts.json", "utf8"));
  await page.locator("#json-input").fill(JSON.stringify(daysInput));
  await page.locator("#json-calculate").click();
  await page.waitForFunction(() => !busy);
  const daysPair = await page.evaluate(() => jsonPair);
  assert.ok(daysPair, await page.locator("#json-status").innerText());
  assert.equal(daysPair.response.status, "OPTIMAL");
  assert.deepEqual(daysPair.response.day_count_summary[0].employees[0], {employee_id: "alice", work_days: 3, occupied_days: 3, days_off: 4});
  assert.match(await page.locator("#json-output").innerText(), /勤務3日・占有3日・完全休日4日/);
  for (const status of ["INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "BACKEND_UNAVAILABLE", "INTERNAL_ERROR"]) {
    for (const retained of [false, true]) {
      const message = await page.evaluate(({status, retained}) => {
        const {input, response} = structuredClone(jsonPair);
        Object.assign(response, {status, solution: null, objectives: [], fairness_summary: null, change_summary: null, continuity_summary: null, shortage_summary: null, priority_summary: null, cost_summary: null, duty_balance_summary: null, verification: {performed: false, valid: null, violations: []}});
        if (!retained) response.day_count_summary = null;
        try { acceptResponse(response, input); return ""; } catch (error) { return error.message; }
      }, {status, retained});
      if (retained) assert.match(message, /計画がない応答に日数集計があります/);
      else assert.equal(message, "");
    }
  }
  report.interactions.push("契約0.11の勤務日数・占有日数・完全休日数をJSON入力から計算・表示し、全5失敗状態の集計保持を拒否");
  for (const kind of ["assignment", "roster"]) {
    const input = JSON.parse(readFileSync(`examples/minimum_${kind}.json`, "utf8"));
    await page.locator("#json-input").fill(JSON.stringify(input));
    await page.locator("#json-calculate").click();
    await page.waitForFunction(() => !busy);
    const pair = await page.evaluate(() => jsonPair);
    assert.ok(pair, await page.locator("#json-status").innerText());
    assert.equal(pair.response.status, "PARTIAL");
    assert.equal(pair.response.shortage_summary.total_person_minutes, 30);
    assert.equal(pair.response.shortage_summary.shortages[0].minimum_people, 1);
    assert.match(await page.locator("#json-output").innerText(), /最低人数/);
    for (const damage of ["assignment", "minimum", "missing-minimum"]) {
      assert.match(await page.evaluate(damage => {
        const {input, response} = structuredClone(jsonPair);
        if (damage === "assignment") response.solution.assignments = [];
        if (damage === "minimum") response.shortage_summary.shortages[0].minimum_people = 0;
        if (damage === "missing-minimum") delete response.shortage_summary.shortages[0].minimum_people;
        const grid = [input.planning_window.start, ...jsonSlots(input).map(slot => new Date(slot.end).toISOString())];
        try { acceptResponse(response, input, grid); return ""; } catch (error) { return error.message; }
      }, damage), /最低人数|不足/);
    }
    input.employees.forEach(e => { e.availability = []; });
    input.shift_candidates = [];
    await page.locator("#json-input").fill(JSON.stringify(input));
    await page.locator("#json-calculate").click();
    await page.waitForFunction(() => !busy);
    assert.equal(await page.evaluate(() => jsonPair.response.status), "INFEASIBLE");
    assert.equal(await page.locator("#json-output table").count(), 0);
  }
  report.interactions.push("契約0.15の担当配置・勤務計画で必須最低人数とPARTIALの不足を表示し、下限違反・集計改ざんを拒否");
  for (const backend of ["auto", "min_cost_flow"]) {
    const input = JSON.parse(readFileSync("tests/fixtures/contract-015/assignment.json", "utf8"));
    input.solver.backend = backend;
    for (const available of [true, false]) {
      if (!available) input.employees.forEach(e => { e.availability = []; });
      await page.locator("#json-input").fill(JSON.stringify(input));
      await page.locator("#json-calculate").click();
      await page.waitForFunction(() => !busy);
      const pair = await page.evaluate(() => jsonPair);
      assert.ok(pair, await page.locator("#json-status").innerText());
      assert.equal(pair.response.schema_version, "0.15");
      assert.equal(pair.response.solver.backend, "min_cost_flow");
      assert.equal(pair.response.status, available ? "OPTIMAL" : "INFEASIBLE");
      if (available) {
        assert.equal(pair.response.verification.valid, true);
        assert.equal(pair.response.shortage_summary.total_person_minutes, 0);
      } else {
        assert.equal(pair.response.solution, null);
        assert.equal(pair.response.shortage_summary, null);
        assert.equal(await page.locator("#json-output table").count(), 0);
      }
    }
  }
  report.interactions.push("契約0.15の完全充足assignmentをauto・明示flowで計算し、不足時は解なしINFEASIBLEを表示");
  await page.locator("#json-sample").selectOption("shift_patterns");
  await page.locator("#json-load-sample").click();
  await page.waitForFunction(() => document.getElementById("json-input").value.includes("shift_patterns_example"));
  await page.locator("#json-calculate").click();
  await page.waitForFunction(() => !busy);
  const patternsPair = await page.evaluate(() => jsonPair);
  assert.ok(patternsPair, await page.locator("#json-status").innerText());
  assert.equal(patternsPair.response.schema_version, "0.15");
  assert.equal(patternsPair.response.status, "PARTIAL");
  assert.equal(patternsPair.response.shortage_summary.total_person_minutes, 30);
  assert.deepEqual(patternsPair.response.solution.shifts.map(s => s.candidate_id), ["night", "day4", "late", "weekend"]);
  assert.match(await page.locator("#json-output").innerText(), /最低人数/);
  patternsPair.input.constraints[1].evaluation_period.start = patternsPair.input.planning_window.start;
  await page.locator("#json-input").fill(JSON.stringify(patternsPair.input));
  await page.locator("#json-calculate").click();
  await page.waitForFunction(() => !busy);
  assert.equal(await page.evaluate(() => jsonPair.response.status), "INVALID_INPUT");
  assert.match(await page.locator("#json-output").innerText(), /INCOMPLETE_HISTORY/);
  assert.match(await page.locator("#json-output").innerText(), /判定に必要な期間：2026-10-03/);
  report.interactions.push("契約0.15の4パターンをサンプルから実計算し、必須下限とPARTIALの不足・余白不足の必要区間を表示");
  await page.locator("#json-sample").selectOption("coworkers");
  await page.locator("#json-load-sample").click();
  await page.waitForFunction(() => document.getElementById("json-input").value.includes("coworkers_example"));
  await page.locator("#json-calculate").click();
  await page.waitForFunction(() => !busy);
  const coworkersPair = await page.evaluate(() => jsonPair);
  assert.ok(coworkersPair, await page.locator("#json-status").innerText());
  assert.equal(coworkersPair.response.schema_version, "0.15");
  assert.equal(coworkersPair.response.status, "PARTIAL");
  assert.equal(coworkersPair.response.shortage_summary.total_person_minutes, 120);
  assert.match(await page.locator("#json-output").innerText(), /待機/);
  assert.match(await page.locator("#json-output").innerText(), /最低人数/);
  coworkersPair.input.constraints[0].coworker_ids = ["trainee"];
  await page.locator("#json-input").fill(JSON.stringify(coworkersPair.input));
  await page.locator("#json-calculate").click();
  await page.waitForFunction(() => !busy);
  assert.equal(await page.evaluate(() => jsonPair.response.status), "INVALID_INPUT");
  assert.match(await page.locator("#json-output").innerText(), /OVERLAPPING_EMPLOYEE_SETS/);
  report.interactions.push("契約0.15の交代指導者・同時勤務禁止を実計算し、待機勤務・最低人数・PARTIALを表示、集合交差の入力不備を表示");
  for (const name of ["shift_count_balance", "combined_conditions"]) {
    await page.locator("#json-sample").selectOption(name);
    await page.locator("#json-load-sample").click();
    await page.waitForFunction(name => document.getElementById("json-input").value.includes(name), name);
    await page.locator("#json-calculate").click();
    await page.waitForFunction(() => !busy);
    const pair = await page.evaluate(() => jsonPair);
    assert.ok(pair, await page.locator("#json-status").innerText());
    assert.equal(pair.response.schema_version, "0.15");
    assert.equal(pair.response.status, name === "shift_count_balance" ? "OPTIMAL" : "PARTIAL");
    assert.equal(pair.response.shift_count_balance_summary[0].total_deviation_count, 0);
    assert.match(await page.locator("#json-output").innerText(), /目標1回・実際1回・偏差0回/);
    const rejected = await page.evaluate(pair => {
      const boundaries = jsonSlots(pair.input).flatMap(slot => [slot.start, slot.end]).map(t => new Date(t).toISOString());
      const response = structuredClone(pair.response);
      response.shift_count_balance_summary[0].employees[0].actual_count++;
      try { acceptResponse(response, pair.input, boundaries); return false; } catch { return true; }
    }, pair);
    assert.ok(rejected);
    pair.input.shift_count_balance[0].employee_targets[0].target_count = true;
    await page.locator("#json-input").fill(JSON.stringify(pair.input));
    await page.locator("#json-calculate").click();
    await page.waitForFunction(() => !busy);
    assert.equal(await page.evaluate(() => jsonPair.response.status), "INVALID_INPUT");
    assert.equal(await page.locator("#json-output table").count(), 0);
  }
  report.interactions.push("契約0.15の履歴付き勤務回数・全5機能の休憩交代を実計算し、回数を表示、改ざん集計・bool目標を拒否");
  // 現在契約の不足・証明と、全旧版の明示拒否を別々に確認する。
  for (const schema_version of ["0.15"]) {
    const input = {...JSON.parse(readFileSync("examples/partial_assignment.json", "utf8")), schema_version};
    await page.locator("#json-input").fill(JSON.stringify(input));
    await page.locator("#json-calculate").click();
    await page.waitForFunction(() => !busy);
    const pair = await page.evaluate(() => jsonPair);
    assert.ok(pair, await page.locator("#json-status").innerText());
    assert.equal(pair.response.schema_version, schema_version);
    assert.equal(pair.response.status, "PARTIAL");
    assert.equal(pair.response.shortage_summary.total_person_minutes, 60);
    assert.ok((await page.locator("#json-output").innerText()).includes("priority 0：不足60人分"));
    for (const kind of ["shortage", "priority", "proof", "no-plan"]) {
      assert.match(await page.evaluate(kind => {
        const {input, response} = structuredClone(jsonPair);
        if (kind === "shortage") response.shortage_summary.total_person_minutes++;
        if (kind === "priority") response.priority_summary.groups[0].total_person_minutes++;
        if (kind === "proof") response.shortage_summary.proven_minimal = false;
        if (kind === "no-plan") Object.assign(response, {status: "UNKNOWN", solution: null, objectives: [], shortage_summary: null, verification: {performed: false, valid: null, violations: []}});
        const grid = [input.planning_window.start, ...jsonSlots(input).map(slot => new Date(slot.end).toISOString())];
        try { acceptResponse(response, input, grid); return ""; } catch (error) { return error.message; }
      }, kind), /不足|priority/);
    }
  }
  for (const schema_version of [...Array.from({length:14}, (_, i) => `0.${i + 1}`), "0.16", null]) {
    const input = {...JSON.parse(readFileSync("examples/partial_assignment.json", "utf8")), schema_version};
    await page.locator("#json-input").fill(JSON.stringify(input));
    await page.locator("#json-calculate").click();
    await page.waitForFunction(() => !busy);
    const pair = await page.evaluate(() => jsonPair);
    assert.ok(pair, await page.locator("#json-status").innerText());
    assert.deepEqual(pair.input, input);
    assert.equal(pair.response.schema_version, "0.15");
    assert.equal(pair.response.status, "INVALID_INPUT");
    assert.equal(pair.response.solution, null);
    assert.equal(pair.response.verification.performed, false);
    assert.equal(await page.locator("#json-output table").count(), 0);
    const forged = structuredClone(pair.response);
    forged.schema_version = schema_version;
    assert.equal(await page.evaluate(({response, input}) => {
      try { acceptResponse(response, input, []); return false; } catch { return true; }
    }, {response: forged, input}), true);
  }
  report.interactions.push("契約0.15の費用・夜勤評価・不足・priority・証明・解なし応答と、全旧版・未知版・不正型の明示拒否を検証");
  const request = JSON.parse(readFileSync('examples/assignment.json', 'utf8'));
  request.demand.forEach(demand => { demand.minimum_people = 0; });
  // 夏時間終了で同じ壁時計時刻が繰り返されても、実際の不足区間を区別する。
  const clockChange = structuredClone(request);
  Object.assign(clockChange.planning_window, {start: '2026-11-01T00:00:00-04:00', end: '2026-11-01T03:00:00-05:00', timezone: 'America/New_York'});
  clockChange.demand = [{...clockChange.demand[0], interval: {start: '2026-11-01T01:30:00-04:00', end: '2026-11-01T01:30:00-05:00'}}];
  clockChange.employees.forEach(employee => { employee.availability = []; });
  await page.locator('#json-input').fill(JSON.stringify(clockChange));
  await page.locator('#json-calculate').click();
  await waitJSON('PARTIAL');
  const clockResult = await page.evaluate(() => jsonPair.response);
  assert.deepEqual(clockResult.verification, {performed: true, valid: true, violations: []});
  assert.equal(clockResult.shortage_summary.total_person_minutes, 60);
  const displayedInterval = await page.locator('#json-output').getByRole('region', {name: '不足の一覧', exact: true}).locator('tbody td').nth(1).innerText();
  assert.equal(displayedInterval, '11/01 01:30 GMT-4〜11/01 01:30 GMT-5');
  report.interactions.push({clock_change: 'America/New_York の夏時間終了', total_person_minutes: 60, displayed_interval: displayedInterval});
  // 実ソルバーの結果を変更した表示サンプル。探索の最適性の実測ではない。
  for (const state of ['FEASIBLE', 'PARTIAL']) {
    if (state === 'PARTIAL') request.employees[0].availability = [];
    await page.locator('#json-input').fill(JSON.stringify(request));
    await page.route('**/solve-json', async route => {
      const result = await (await route.fetch()).json();
      result.status = state;
      result.objectives.forEach(o => { o.proven_optimal = false; });
      if (state === 'PARTIAL') {
        result.shortage_summary.proven_minimal = false;
        result.priority_summary.groups.forEach(group => { group.proven_minimal = false; });
      }
      await route.fulfill({json: result});
    });
    await page.locator('#json-calculate').click();
    await waitJSON(state);
    if (state === 'PARTIAL') assert.ok((await page.locator('#json-output').innerText()).includes('不足最小性：未証明'));
    report.response_samples.push(`JSON ${state} 未証明の表示`);
    await page.unroute('**/solve-json');
  }
  for (const [text, expected] of [["{", "INVALID_JSON"], ['{"a":1,"a":2}', "DUPLICATE_JSON_KEY"], ["null", "INVALID_INPUT"]]) {
    await page.locator("#json-input").fill(text);
    assert.equal(await page.locator("#json-output table").count(), 0);
    await page.locator("#json-calculate").click();
    await waitJSON(expected);
  }
  await page.locator("#json-file").setInputFiles({name: "bad.json", mimeType: "application/json", buffer: Buffer.from([255])});
  await waitJSON("読み込めませんでした");
  assert.equal(await page.locator("#json-output table").count(), 0);
  report.interactions.push("JSON のファイル入力・夜勤・分割勤務・解なし・入力不備・重複キー・不正UTF-8・日付切替・編集で結果を失効");
}

async function adapterChecks(page) {
  const wait = text => page.waitForFunction(value => document.getElementById("adapter-status").textContent.includes(value) && !document.getElementById("adapter-check").disabled, text, {timeout: 120000});
  await page.locator("#adapter-demo > summary").click();
  const staleWeek = JSON.parse(readFileSync("examples/adapter/week-next-stale.draft.json", "utf8"));
  const nextWeek = JSON.parse(readFileSync("examples/adapter/week-next.draft.json", "utf8"));
  await page.locator("#adapter-file").setInputFiles("examples/adapter/week-next-stale.draft.json");
  await wait("入力候補");
  await page.locator("#adapter-check").click();
  await wait("INVALID_INPUT");
  assert.ok((await page.locator("#adapter-output").innerText()).includes("STALE_APPLICABILITY"));
  const editedWeek = structuredClone(staleWeek);
  for (const id of ["period", "history"]) {
    const source = editedWeek.sources.find(s => s.id === id);
    const updated = nextWeek.sources.find(s => s.id === id);
    source.data = updated.data;
    source.applies_to = updated.applies_to;
    source.revision = updated.revision;
  }
  await page.locator("#adapter-input").fill(JSON.stringify(editedWeek));
  await page.locator("#adapter-check").click();
  await wait("INVALID_INPUT");
  const weekStates = await page.evaluate(() => JSON.parse(document.querySelector("#adapter-output details pre").textContent));
  for (const id of ["basic", "common", "execution"]) assert.equal(weekStates.find(s => s.source_id === id).state, "confirmed");
  for (const id of ["period", "history"]) {
    assert.equal(weekStates.find(s => s.source_id === id).state, "stale");
    await page.locator("#adapter-source").selectOption(id);
    await page.locator("#adapter-confirm").click();
    await wait("入力候補");
  }
  await page.locator("#adapter-check").click();
  await wait("VALIDです");
  await page.locator("#adapter-run").click();
  await wait("現在の検証 VALID");
  const weekRecord = await page.evaluate(() => structuredClone(adapterRecord));
  assert.deepEqual(weekRecord.request, JSON.parse(readFileSync("examples/adapter/week-next.request.json", "utf8")));
  assert.deepEqual(weekRecord.sources.find(s => s.source.id === "history").source.data, staleWeek.sources.find(s => s.id === "history").data);
  const weekDownloadPromise = page.waitForEvent("download");
  await page.locator("#adapter-save-record").click();
  const weekSavedPath = await (await weekDownloadPromise).path();
  await page.locator("#adapter-file").setInputFiles(weekSavedPath);
  await wait("現在の検証 VALID");
  assert.deepEqual(await page.evaluate(() => adapterRecord), weekRecord);
  report.interactions.push("翌週の古い日付を診断→基本情報/共通ルールの確認を保持→期間/履歴の適用範囲を明示更新・個別確認→実計算→保存/再読込、原履歴は不変");
  await page.locator("#adapter-sample").selectOption("unconfirmed");
  await page.locator("#adapter-load").click();
  await wait("入力候補");
  await page.locator("#adapter-check").click();
  await wait("INVALID_INPUT");
  assert.ok((await page.locator("#adapter-output").innerText()).includes("UNCONFIRMED_SOURCE"));
  assert.ok((await page.locator("#adapter-output").innerText()).includes("/employees/0/availability"));
  let draft = JSON.parse(await page.locator("#adapter-input").inputValue());
  draft.unresolved = [];
  await page.locator("#adapter-input").fill(JSON.stringify(draft));
  await page.locator("#adapter-source").selectOption("basic");
  await page.locator("#adapter-confirm").focus();
  await page.keyboard.press("Enter");
  await wait("入力候補");
  await page.locator("#adapter-check").click();
  await wait("VALIDです");
  await page.locator("#adapter-run").click();
  await wait("現在の検証 VALID");
  const original = await page.evaluate(() => structuredClone(adapterRecord));
  assert.equal(original.response.verification.valid, true);
  assert.ok((await page.locator("#adapter-output").innerText()).includes(original.run_id));
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#adapter-save-record").click();
  const download = await downloadPromise;
  const savedPath = await download.path();
  const saved = JSON.parse(readFileSync(savedPath, "utf8"));
  assert.deepEqual(saved, original);
  draft = JSON.parse(await page.locator("#adapter-input").inputValue());
  const period = draft.sources.find(s => s.section === "period");
  period.data.employees[0].availability = [];
  await page.locator("#adapter-input").fill(JSON.stringify(draft));
  assert.equal(await page.evaluate(() => adapterRecord), null);
  await page.locator("#adapter-check").click();
  await wait("INVALID_INPUT");
  const states = await page.evaluate(() => JSON.parse(document.querySelector("#adapter-output details pre").textContent));
  assert.equal(states.find(s => s.source_id === "period").state, "stale");
  assert.equal(states.find(s => s.source_id === "basic").state, "confirmed");
  await page.locator("#adapter-file").setInputFiles(savedPath);
  await wait("現在の検証 VALID");
  assert.deepEqual(await page.evaluate(() => adapterRecord), saved);
  const input = await page.locator("#adapter-input").inputValue();
  await page.locator("#adapter-file").setInputFiles({name:"bad.json",mimeType:"application/json",buffer:Buffer.from([255])});
  await wait("処理できませんでした");
  assert.equal(await page.locator("#adapter-input").inputValue(), input);
  await page.locator("#adapter-reverify").click();
  await wait("現在の検証 VALID");
  assert.deepEqual(await page.evaluate(() => adapterRecord), saved);
  await page.locator("#adapter-sample").selectOption("partial_roster");
  await page.locator("#adapter-load").click();
  await wait("入力候補");
  await page.locator("#adapter-run").click();
  await wait("現在の検証 PARTIAL");
  assert.ok((await page.locator("#adapter-output").innerText()).includes("不足あり"));
  const partial = await page.evaluate(() => structuredClone(adapterRecord));
  assert.equal(partial.response.shortage_summary.proven_minimal, true);
  const detailsText = await page.locator("#adapter-output details").first().locator("pre").textContent();
  assert.equal(JSON.parse(detailsText).metrics.shortage_summary.proven_minimal, false);
  for (const state of ["UNKNOWN", "INFEASIBLE", "INTERNAL_ERROR"]) {
    // 状態表示用サンプル。実求解の証拠として数えない。
    await page.route("**/adapter/run", async route => {
      const record = structuredClone(partial);
      record.response = {...record.response, status:state, solution:null, objectives:[], shortage_summary:null,
        verification:{performed:false,valid:null,violations:[]}};
      const view = {run_id:record.run_id,original_status:state,current_status:"NOT_PERFORMED",demand_satisfied:null,
        solution:null,metrics:{},diagnostics:[],original_evidence:record.response};
      await route.fulfill({json:{record,view}});
    });
    await page.locator("#adapter-run").click();
    await wait(`${state} · 現在の検証 NOT_PERFORMED`);
    assert.equal(await page.locator("#adapter-output table").count(), 0);
    await page.unroute("**/adapter/run");
    report.response_samples.push(`adapter-${state}`);
  }
  await page.locator("#adapter-input").fill(JSON.stringify(draft));
  let release;
  const released = new Promise(resolve => {release = resolve;});
  await page.route("**/adapter/check", async route => {
    await released;
    try { await route.fulfill({json:{status:"VALID",request:original.request,provenance:{},diagnostics:[],confirmations:[]}}); } catch { /* 編集で失効した応答 */ }
  });
  await page.locator("#adapter-check").click();
  await page.locator("#adapter-input").fill(JSON.stringify({...draft,assumptions:["新しい編集"]}));
  release();
  await page.waitForTimeout(100);
  assert.ok((await page.locator("#adapter-status").innerText()).includes("入力を変更"));
  assert.equal(await page.evaluate(() => adapterRecord), null);
  await page.unroute("**/adapter/check");
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path:"test-results/adapter-mobile.png",fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  report.interactions.push("分割入力の未確認修正・個別確認・実計算・記録ダウンロード/再読み込み・失敗時の入力保持・再検証・PARTIALと過去の証明・古い応答の排除・キーボード/狭い画面");
  const currentDraft = JSON.parse(readFileSync("examples/adapter/assignment.draft.json", "utf8"));
  currentDraft.sources.find(s => s.section === "period").revision = "edited";
  await page.locator("#adapter-input").fill(JSON.stringify(currentDraft));
  await page.locator("#adapter-check").click();
  await wait("INVALID_INPUT");
  const updatedStates = await page.evaluate(() => JSON.parse(document.querySelector("#adapter-output details pre").textContent));
  assert.equal(updatedStates.find(s => s.source_id === "period").state, "stale");
  for (const id of ["basic", "common", "execution"]) assert.equal(updatedStates.find(s => s.source_id === id).state, "confirmed");
  await page.locator("#adapter-source").selectOption("period");
  await page.locator("#adapter-confirm").focus();
  await page.keyboard.press("Enter");
  await wait("入力候補");
  await page.locator("#adapter-run").click();
  await wait("現在の検証 VALID");
  const updatedRecord = await page.evaluate(() => structuredClone(adapterRecord));
  assert.equal(updatedRecord.request.schema_version, "0.15");
  assert.ok(updatedRecord.request.demand.every(d => d.minimum_people === d.required_people));
  const updatedDownload = page.waitForEvent("download");
  await page.locator("#adapter-save-record").click();
  await page.locator("#adapter-file").setInputFiles(await (await updatedDownload).path());
  await wait("現在の検証 VALID");
  assert.deepEqual(await page.evaluate(() => adapterRecord), updatedRecord);
  await page.locator("#adapter-reverify").click();
  await wait("現在の検証 VALID");
  const migratedView = JSON.parse(await page.locator("#adapter-output details").first().locator("pre").textContent());
  assert.equal(migratedView.metrics.shortage_summary.proven_minimal, false);
  report.interactions.push("旧manifestを0.15へ明示移行→無変更の確認保持・期間確認の失効→キーボードで再確認→実計算→記録保存/再読込/再検証、現在検証へ証明を転記しない");
}

async function main() {
  mkdirSync("test-results", {recursive: true});
  let url = process.env.PLAYGROUND_URL;
  if (!url) {
    server = spawn(process.env.PYTHON || ".venv/bin/python", ["demo/server.py"], {stdio: ["ignore", "pipe", "pipe"]});
    url = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("サーバーの起動期限を超えました。")), 10000);
      server.stderr.on("data", data => process.stderr.write(data));
      server.once("exit", code => { clearTimeout(timer); reject(new Error(`起動失敗：${code}`)); });
      server.stdout.on("data", data => {
        const match = data.toString().match(/http:\/\/127\.0\.0\.1:\d+/);
        if (match) { clearTimeout(timer); resolve(match[0]); }
      });
    });
  }
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  report.browser = browser.version();
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, timezoneId: "UTC"});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let acceptDialog = true;
  page.on("dialog", dialog => acceptDialog ? dialog.accept() : dialog.dismiss());
  await page.goto(url);
  let initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  await page.screenshot({path: "test-results/playground-desktop.png", fullPage: true});
  await reviewRegressions(page, url);
  initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});

  for (const scenario of scenarios) {
    if (await page.locator("#scenario").inputValue() !== scenario.id) {
      await page.locator("#scenario").selectOption(scenario.id);
      initial = await verified(page, scenario.steps[0].expected);
    }
    report.scenarios.push({scenario: scenario.id, step: "initial", status: initial.response.status, verification: initial.response.verification});
    for (const step of scenario.steps.slice(1)) {
      if (step.restore) await page.locator("#restore").click();
      else {
        await page.getByRole("button", {name: "この変更を入力", exact: true}).click();
        assert.ok((await page.locator("#status").innerText()).includes("再計算が必要"));
        assert.equal(await page.locator("#output table").count(), 0);
        assert.ok((await page.locator("#previous").innerText()).includes("現在の条件には無効"));
        await page.locator("#calculate").click();
      }
      const pair = await verified(page, step.expected);
      if (scenario.id === "absence" && step.id === "changed") {
        await page.setViewportSize({width: 390, height: 844});
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        await page.locator('#result').scrollIntoViewIfNeeded();
        await page.emulateMedia({forcedColors: 'active'});
        assert.ok((await page.locator('#output').innerText()).includes('不足1人'));
        await page.screenshot({path: 'test-results/playground-partial-mobile.png'});
        await page.emulateMedia({forcedColors: 'none'});
        await page.setViewportSize({width: 1440, height: 1000});
      }
      if (scenario.id === "absence" && step.id === "repaired") assert.deepEqual(pair.input.employees[0].availability, []);
      report.scenarios.push({scenario: scenario.id, step: step.id, status: pair.response.status, verification: pair.response.verification, shortage_summary: pair.response.shortage_summary});
      if (!step.restore) assert.equal((await page.evaluate(() => baseline.input.request_id)), initial.input.request_id);
    }
    const before = await page.evaluate(() => ({baseline, current, input: readRequest()}));
    await page.getByRole("button", {name: "自由に編集する", exact: true}).click();
    assert.deepEqual(await page.evaluate(() => ({baseline, current, input: readRequest()})), before);
  }

  // キーボードで編集、再計算、復元。名前の重複でもIDによる担当比較を保つ。
  await page.locator('[data-pointer="/employees/0/label"]').focus();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type("ren");
  await page.locator("#calculate").focus();
  await page.keyboard.press("Enter");
  await status(page, "OPTIMAL");
  assert.ok((await page.locator("#comparison").innerText()).includes("担当差分：0人枠"));
  await page.locator('[data-pointer="/employees/0/label"]').fill("れん");
  await page.locator("#calculate").click();
  await status(page, "OPTIMAL");
  assert.ok((await page.locator("#comparison").innerText()).includes("担当差分：0人枠"));
  acceptDialog = false;
  const selection = await page.locator("#scenario").inputValue();
  await page.locator("#scenario").selectOption("normal");
  assert.equal(await page.locator("#scenario").inputValue(), selection);
  acceptDialog = true;
  await page.locator("#restore").focus();
  await page.keyboard.press("Enter");
  await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  report.interactions.push("キーボード編集・再計算・復元、自由編集の保持、シナリオ切替の取消、重複名のID比較");

  for (const value of ["", "1.5", "7"]) {
    await page.locator('[data-pointer="/demand/0/required_people"]').fill(value);
    await page.locator("#calculate").click();
    await status(page, "入力不備");
    assert.equal(await page.locator("#output table").count(), 0);
  }
  await page.locator("#restore").click();
  initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  await page.locator('[data-pointer="/employees/0/label"]').fill("<img src=x>");
  await page.locator("#calculate").click();
  await status(page, "OPTIMAL");
  assert.equal(await page.locator("#output img").count(), 0);
  assert.ok((await page.locator("#output").innerText()).includes("<img src=x>"));
  report.interactions.push("空欄・小数・範囲外の入力不備、ラベルの文字表示");

  await page.locator("#restore").click();
  initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: 844});
    const geometry = await page.evaluate(() => ({width: innerWidth, document: document.documentElement.scrollWidth, columns: getComputedStyle(document.querySelector(".layout")).gridTemplateColumns.split(" ").length}));
    assert.ok(geometry.document <= geometry.width);
    assert.equal(geometry.columns, width === 1440 ? 2 : 1);
    await page.locator("#demand").focus();
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.dataset.pointer), "/demand/0/required_people");
    assert.equal(await page.evaluate(() => getComputedStyle(document.activeElement).outlineWidth), "3px");
    report.interactions.push({viewport: width, geometry, keyboard_focus: true});
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({path: "test-results/playground-mobile.png"});
  await page.locator("#result").scrollIntoViewIfNeeded();
  await page.screenshot({path: "test-results/playground-mobile-result.png"});
  await page.emulateMedia({forcedColors: "active"});
  assert.ok((await page.locator("#status").innerText()).includes("OPTIMAL"));
  for (const role of ["調理", "ホール", "皿洗い"]) assert.ok((await page.locator("#output").innerText()).includes(role));
  await page.screenshot({path: "test-results/playground-forced-colors.png"});
  await page.emulateMedia({forcedColors: "none"});
  report.interactions.push("強制配色でも状態・役割名を文字で確認");

  await page.locator('[data-pointer="/employees/0/skills/cooking"]').focus();
  await page.keyboard.press("Space");
  await page.locator("#calculate").focus();
  await page.keyboard.press("Enter");
  await status(page, "PARTIAL");
  assert.equal(await page.locator("#output table").count(), 3);
  await page.locator("#restore").click();
  initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  await page.locator('[data-pointer="/employees/0/availability/0/end"]').selectOption("2026-10-06T11:00:00+09:00");
  await page.locator("#calculate").click();
  await status(page, "入力不備");
  await page.locator("#restore").click();
  initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  report.interactions.push("技能チェックをキーボードで編集して不足付き配置を実計算、勤務可能時間の逆転を拒否");

  for (let i = 0; i < 6; i++) await page.locator(`[data-pointer="/employees/${i}/availability"]`).check();
  await page.locator('#calculate').click();
  await status(page, 'PARTIAL');
  const allMissing = await page.evaluate(() => current);
  assert.equal(allMissing.response.solution.assignments.length, 0);
  assert.equal(allMissing.response.shortage_summary.total_person_minutes, 660);
  assert.ok((await page.locator('#output').innerText()).includes('不足'));
  report.interactions.push({all_missing: allMissing.response.shortage_summary, verification: allMissing.response.verification});
  await page.locator('#restore').click();
  initial = await verified(page, {status: 'OPTIMAL', assigned_slots: 22});

  // 以下は実エンジンの実測ではなく、表示・応答失効を確認する応答サンプル。
  for (const state of ["INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "BACKEND_UNAVAILABLE", "INTERNAL_ERROR"]) {
    await page.route("**/solve", async route => {
      const result = structuredClone(initial.response);
      result.request_id = route.request().postDataJSON().request_id;
      result.status = state;
      if (state !== "FEASIBLE") { result.shortage_summary = null; result.priority_summary = null; result.solution = null; result.objectives = []; result.verification = {performed: false, valid: null, violations: []}; }
      result.diagnostics = [{code: "DISPLAY_SAMPLE", message: "表示確認用の応答サンプル", json_pointer: "/demand/0/required_people", related_ids: [], facts: []}];
      await route.fulfill({json: result});
    });
    await page.locator("#calculate").click();
    await status(page, state);
    assert.equal(await page.locator("#output table").count(), state === "FEASIBLE" ? 2 : 0);
    if (state !== "FEASIBLE") assert.ok(!(await page.locator("#comparison").innerText()).includes("担当差分："));
    await page.getByRole("button", {name: /入力欄へ/}).click();
    assert.equal(await page.evaluate(() => document.activeElement.dataset.pointer), "/demand/0/required_people");
    report.response_samples.push(state);
    await page.unroute("**/solve");
  }
  for (const kind of ["http-error", "communication", "request-id", "verification", "malformed", "shortage", "double"]) {
    await page.route("**/solve", async route => {
      if (kind === "communication") { await route.abort(); return; }
      if (kind === "http-error") { await route.fulfill({status: 503, json: {error: {code: "BUSY", message: "計算中", json_pointer: null}}}); return; }
      const result = structuredClone(initial.response);
      result.request_id = kind === "request-id" ? "old_request" : route.request().postDataJSON().request_id;
      if (kind === "verification") result.verification.valid = false;
      if (kind === "malformed") result.solution.assignments = [{}];
      if (kind === "shortage") result.shortage_summary.total_person_minutes = 30;
      if (kind === "double") result.solution.assignments.push(structuredClone(result.solution.assignments[0]));
      await route.fulfill({json: result});
    });
    await page.locator("#calculate").click();
    await status(page, "結果を取得できませんでした");
    assert.equal(await page.locator("#output table").count(), 0);
    report.response_samples.push(kind);
    await page.unroute("**/solve");
  }
  await page.locator("#calculate").click();
  await verified(page, {status: "OPTIMAL", assigned_slots: 22});

  let release, entered;
  const ready = new Promise(resolve => { entered = resolve; });
  const hold = new Promise(resolve => { release = resolve; });
  let requests = 0;
  await page.route("**/solve", async route => {
    requests++;
    const response = await route.fetch();
    entered();
    await hold;
    try { await route.fulfill({response}); } catch { /* 失効済みの通信 */ }
  });
  await page.locator("#calculate").click();
  await ready;
  assert.equal(await page.locator("#calculate").isDisabled(), true);
  await page.evaluate(() => { calculate(); calculate(); });
  assert.equal(requests, 1);
  await page.evaluate(() => {
    const input = document.querySelector('[data-pointer="/demand/0/required_people"]');
    input.value = "2";
    input.dispatchEvent(new Event("input", {bubbles: true}));
  });
  release();
  await page.waitForFunction(() => !busy && current === null);
  await page.unroute("**/solve", {behavior: "wait"});
  assert.ok((await page.locator("#status").innerText()).includes("再計算が必要"));
  assert.equal(await page.locator("#output table").count(), 0);
  await page.locator("#calculate").click();
  await verified(page, {status: "OPTIMAL", assigned_slots: 23});
  report.response_samples.push("計算中・二重送信抑止・編集で失効した遅延応答");

  let timeoutRelease;
  const timeoutHold = new Promise(resolve => { timeoutRelease = resolve; });
  await page.evaluate(() => {
    window.originalSetTimeout = window.setTimeout;
    window.setTimeout = (callback, delay, ...args) => originalSetTimeout(callback, delay === 15000 ? 100 : delay, ...args);
  });
  await page.route("**/solve", async route => {
    const response = await route.fetch();
    await timeoutHold;
    try { await route.fulfill({response}); } catch { /* 期限後の通信 */ }
  });
  await page.locator("#calculate").click();
  await status(page, "15秒の待機期限");
  timeoutRelease();
  await page.unroute("**/solve", {behavior: "wait"});
  assert.equal(await page.evaluate(() => current), null);
  await page.evaluate(() => { window.setTimeout = window.originalSetTimeout; });
  await page.locator("#restore").click();
  await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  report.response_samples.push("待機期限（テスト時のみ100msに短縮）・期限後応答の拒否・復帰");
  await jsonInputChecks(page);
  await adapterChecks(page);
  assert.deepEqual(errors, []);
  report.page_errors = errors;
  writeFileSync("test-results/playground-browser.json", JSON.stringify(report, null, 2) + "\n");
  console.log("3シナリオ・JSON入力・100人30日の勤務計画・キーボード・狭い画面・応答失効：成功");
}

main().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server) server.kill("SIGINT");
});
