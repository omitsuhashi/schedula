const assert = require("node:assert/strict");
const {readFileSync, writeFileSync} = require("node:fs");
require("./feature-state.cjs");
const lessons = JSON.parse(readFileSync("examples/playground/lessons.json", "utf8"));
const ready = page => page.waitForFunction(() => feature?.current && !document.getElementById("feature-controls").disabled);
module.exports = async (browser, url, report) => {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, timezoneId: "UTC"});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let requests = 0;
  page.on("request", request => { if (request.url().endsWith("/solve-json")) requests++; });
  await page.goto(url);
  await page.locator("#feature-list .feature-cards").first().waitFor();
  assert.equal(await page.locator("#feature-list .feature-cards li").count(), 44);
  assert.equal(requests, 0);
  assert.equal(await page.locator("#editor").isVisible(), false);
  for (const lesson of lessons.filter(item => item.operation === "solve" && !["basic","conditions"].includes(item.module))) {
    await page.goto(`${url}#${lesson.id}`);
    await ready(page);
    const initial = await page.evaluate(() => structuredClone(feature.current));
    for (const step of lesson.steps) {
      if (step.id !== "initial") {
        if (step.restore && !Object.keys(step.changes).length) await page.locator("#feature-restore").click();
        else {
          await page.locator(`[data-step="${step.id}"]`).click();
          assert.equal(await page.evaluate(() => feature.current), null);
          assert.match(await page.locator("#feature-status").innerText(), /未計算/);
          assert.equal(await page.locator(".feature-overview").count(), 0);
          assert.equal(await page.locator(".feature-input-changes").evaluate(element => element.open), true);
          await page.locator("#feature-run").click();
        }
      }
      await ready(page);
      const pair = await page.evaluate(() => structuredClone(feature.current));
      assert.equal(pair.response.status, step.expected.status);
      assert.equal(pair.response.shortage_summary.total_person_minutes, step.expected.total_person_minutes);
      assert.equal(pair.response.verification.valid, true);
      if (step.expected.total_deviation_count !== undefined) {
        const summary = pair.response.shift_count_balance_summary[0];
        assert.equal(summary.total_deviation_count, step.expected.total_deviation_count);
        if (step.expected.actual_counts) assert.deepEqual(Object.fromEntries(summary.employees.map(item => [item.employee_id, item.actual_count])), step.expected.actual_counts);
        if (step.id === "unspecified") assert.match(await page.locator("#feature-output").innerText(), /目標未指定・対象外/);
        if (step.id === "zero") assert.match(await page.locator("#feature-output").innerText(), /目標0回/);
        if (step.id === "classification") assert.match(await page.locator("#feature-output").innerText(), /22:00.*重なり300分/);
      }
      if (step.expected.max_consecutive_days) {
        assert.equal(await page.evaluate(() => Math.max(...consecutiveRuns(feature.current).map(item => item.maximum))), step.expected.max_consecutive_days);
      }
      const summary = page.getByRole("region", {name: "変更と結果の要点"});
      assert.match(await summary.innerText(), new RegExp(`現在\\s*${step.expected.total_person_minutes}人分`));
      const proof = page.locator(".feature-proof");
      assert.equal(await proof.evaluate(element => element.open), false);
      await proof.locator("summary").click();
      assert.match(await proof.innerText(), /有効性：独立検証済み/);
      assert.match(await proof.innerText(), /不足最小性：証明済み/);
      await proof.locator("summary").click();
      if (step.id === "shorter") {
        assert.match(await summary.innerText(), /初期\s*5日\s*→\s*現在\s*3日/);
        assert.ok(await page.locator(".feature-changed").count() > 0);
      }
      if (lesson.id === "consecutive_days" && ["history", "fewer_backups"].includes(step.id)) {
        const conditions = summary.locator(".feature-condition");
        assert.equal(await conditions.count(), step.id === "history" ? 1 : 2);
        if (step.id === "history") {
          assert.match(await conditions.innerText(), /計画前の最終勤務と連勤 \(A\).*初期\s*最終勤務なし.*直前0日.*現在\s*2026-10-04 10:00 Asia\/Tokyo.*開始日2026-10-04.*直前3日/s);
          assert.doesNotMatch(await summary.innerText(), /変更した条件 · 連勤上限/);
        } else for (const name of ["B", "C"]) {
          const card = conditions.filter({hasText: `交代要員の勤務可能時間 (${name})`});
          assert.match(await card.innerText(), /初期\s*2026-10-05 00:00 Asia\/Tokyo.*現在\s*2026-10-10 00:00 Asia\/Tokyo.*2026-10-12 00:00 Asia\/Tokyo.*初期から変化/s);
        }
        await page.setViewportSize({width: 390, height: 844});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.setViewportSize({width: 1440, height: 1000});
      }
      if (step.id === "covered") {
        assert.match(await summary.innerText(), /初期\s*2人\s*→\s*現在\s*3人/);
        assert.equal(await page.locator(".feature-changed").count(), 2);
      }
      if (lesson.id === "demand" && step.id === "shortage") {
        const counts = ["hall_2", "hall_3"].map(id => {
          const interval = pair.input.demand.find(item => item.id === id).interval;
          return pair.response.solution.assignments.filter(item => item.role_id === "hall" && Date.parse(item.interval.start) <= Date.parse(interval.start) && Date.parse(item.interval.end) >= Date.parse(interval.end)).length;
        });
        const value = counts[0] === counts[1] ? String(counts[0]) : `${Math.min(...counts)}〜${Math.max(...counts)}`;
        assert.match(await summary.innerText(), new RegExp(`配置できた人数\\s*初期\\s*2人\\s*→\\s*現在\\s*${value}人`));
        assert.match(await summary.innerText(), /必要人数を満たせない時間帯/);
        const coverage = await page.getByRole("region", {name: "必要人数と配置人数"}).innerText();
        for (const count of counts) assert.match(coverage, new RegExp(`配置${count} / 必要4人\\s*${count === 4 ? "不足なし" : `不足${4 - count}人`}`));
      }
      if (["covered", "shortage", "shorter", "fewer_backups"].includes(step.id))
        await page.screenshot({path: `test-results/feature-${lesson.id}-${step.id}.png`, fullPage: true});
      if (step.id === "restored") {
        assert.deepEqual(pair, initial);
        assert.equal(await summary.locator(".feature-condition").count(), 0);
      }
      report.interactions.push({lesson: lesson.id, step: step.id, status: pair.response.status, verification: pair.response.verification});
    }
    // 自由編集とキーボード、狭い画面の表スクロール。
    const number = page.locator("#feature-number");
    await number.focus(); await page.keyboard.press("ArrowUp");
    assert.equal(await page.evaluate(() => feature.current), null);
    await page.locator("#feature-run").click(); await ready(page);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.locator(".feature-summary").evaluate(element => getComputedStyle(element).gridTemplateColumns.split(" ").length), 1);
    await page.getByRole("region", {name: lesson.id === "consecutive_days" ? "日別の勤務表" : lesson.id === "demand" ? "必要人数と配置人数" : "JSON の担当配置表", exact: true}).focus();
    await page.keyboard.press("ArrowRight");
    await page.screenshot({path: `test-results/feature-${lesson.id}-mobile.png`, fullPage: true});
    await page.emulateMedia({forcedColors: "active"});
    assert.match(await page.locator("#feature-output").innerText(), /必須条件は守れています/);
    await page.emulateMedia({forcedColors: "none"});
    await page.setViewportSize({width: 1440, height: 1000});
    await page.locator("#feature-restore").click(); await ready(page);
    // HTTP + 描画を3回。最初の画面計算と継続実行を別々に記録。
    for (let repeat = 0; repeat < 3; repeat++) { await number.fill(lesson.id === "demand" ? "3" : "3"); await page.locator("#feature-run").click(); await ready(page); }
    report.feature_measurements ||= [];
    report.feature_measurements.push(...await page.evaluate(() => featureMeasurements.splice(0)));
  }
  await require("./basic-browser.cjs")(browser, url, report);
  await require("./condition-browser.cjs")(browser, url, report);
  await require("./verify-browser.cjs")(page, url, report);
  // 初期解なし→編集→実再試行。制御応答の証拠として記録する。
  let first = true;
  await page.route("**/solve-json", async route => {
    if (!first) return route.continue();
    first = false;
    const response = await route.fetch(), value = await response.json();
    Object.assign(value, {status: "INFEASIBLE", solution: null, objectives: [], verification: {performed: false, valid: null, violations: []}});
    for (const key of Object.keys(value)) if (key.endsWith("_summary")) value[key] = null;
    await route.fulfill({json: value});
  });
  await page.goto(`${url}#demand`); await ready(page);
  assert.equal(await page.evaluate(() => feature.baseline.response.status), "INFEASIBLE");
  await page.locator("#feature-number").fill("3"); await page.locator("#feature-run").click(); await ready(page);
  assert.equal(await page.evaluate(() => feature.current.response.status), "OPTIMAL");
  assert.match(await page.locator("#feature-output").innerText(), /初期結果に有効な計画がない/);
  await page.unroute("**/solve-json");
  report.response_samples.push("機能デモの初期INFEASIBLEから編集・実再試行");
  const proofText = await page.evaluate(() => {
    const actual = feature.current.response;
    feature.current.response = structuredClone(actual);
    feature.current.response.status = "FEASIBLE";
    feature.current.response.shortage_summary.proven_minimal = false;
    for (const item of feature.current.response.priority_summary.groups) item.proven_minimal = false;
    for (const item of feature.current.response.objectives) item.proven_optimal = false;
    renderFeature();
    const text = document.querySelector(".feature-proof").textContent;
    feature.current.response = actual; renderFeature();
    return text;
  });
  assert.match(proofText, /全目的の最適性は未証明/);
  assert.match(proofText, /不足最小性：未証明/);
  report.response_samples.push("最適性・不足最小性が未証明の有効計画の表示（制御データ）");
  // HTTP失敗後の再試行と、遅い応答をデモ切替後に採用しないこと。
  await page.route("**/solve-json", route => route.fulfill({status: 503, json: {error: {code: "BUSY", message: "計算中"}}}));
  await page.locator("#feature-run").click();
  await page.waitForFunction(() => !document.getElementById("feature-controls").disabled);
  assert.match(await page.locator("#feature-status").innerText(), /BUSY/);
  await page.unroute("**/solve-json");
  await page.locator("#feature-run").click(); await ready(page);
  let release, started, captured = false;
  const waiting = new Promise(resolve => { started = resolve; });
  await page.route("**/solve-json", async route => {
    if (captured) return route.continue();
    captured = true;
    const response = await route.fetch(); started();
    await new Promise(resolve => { release = resolve; });
    await route.fulfill({response}).catch(() => {});
  });
  await page.locator("#feature-number").fill("4"); await page.locator("#feature-run").click(); await waiting;
  const beforeRetry = requests;
  await page.evaluate(() => { runFeature(); runFeature(); });
  assert.equal(requests, beforeRetry);
  await page.evaluate(() => { location.hash = "consecutive_days"; });
  await page.waitForFunction(() => lesson?.id === "consecutive_days");
  release(); await page.unrouteAll({behavior: "wait"}); await ready(page);
  assert.equal(await page.evaluate(() => feature.current.input.request_id), "demo_consecutive_days");
  const differences = await page.evaluate(() => {
    const before = {employees: [{id: "a", skills: [{skill_id: "s", level: 1}], availability: [{start: "2026-10-01T09:00:00+09:00", end: "2026-10-01T10:00:00+09:00"}]}], objectives: [{metric: "scheduled_cost"}, {metric: "preference_penalty"}]};
    const after = structuredClone(before); after.employees[0].skills[0].level = 2; after.employees[0].availability[0].start = "2026-10-02T09:00:00+09:00"; after.objectives.reverse();
    return featureChanges([{collection: "employees", ids: ["a"], field: "skills", label: "技能", unit: "レベル"}, {collection: "employees", ids: ["a"], field: "availability", label: "勤務可能日時", unit: "日時"}, {field: "objectives", label: "目的順序", unit: "順序"}], before, after);
  });
  assert.equal(differences.length, 3);
  assert.match(differences[0], /レベル1 → s レベル2/);
  assert.match(differences[1], /2026-10-02/);
  assert.match(differences[2], /scheduled_cost → preference_penalty/);
  await page.goto(`${url}#max_assigned_minutes`);
  await page.waitForFunction(() => document.querySelector("#feature-list [role=status]").textContent.includes("準備中"));
  for (const sample of ["lunch", "scenarios"]) {
    await page.route(`**/samples/${sample}.json`, route => route.fulfill({status: 503, json: {error: "読込失敗の制御応答"}}));
    await page.goto(`${url}#combined`);
    await page.reload();
    await page.waitForFunction(() => document.getElementById("status").textContent.includes("サンプルの取得に失敗"));
    assert.equal(await page.locator("#calculate").isDisabled(), true);
    await page.unroute(`**/samples/${sample}.json`);
  }
  let sampleStarted, sampleRelease;
  const sampleWaiting = new Promise(resolve => { sampleStarted = resolve; });
  await page.route("**/samples/lunch.json", async route => {
    const response = await route.fetch(); sampleStarted();
    await new Promise(resolve => { sampleRelease = resolve; });
    await route.fulfill({response});
  });
  await page.reload(); await sampleWaiting;
  assert.equal(await page.locator("#calculate").isDisabled(), true);
  await page.evaluate(() => { location.hash = "demand"; });
  sampleRelease(); await page.unrouteAll({behavior: "wait"}); await ready(page);
  assert.equal(await page.locator("#editor").isVisible(), false);
  await page.goto(`${url}#combined`);
  await page.waitForFunction(() => current?.response.status === "OPTIMAL" && !document.getElementById("controls").disabled);
  report.response_samples.push("複合フォームはサンプル読込中・読込失敗後に無効、切替後の古い読込を拒否、再読込で復帰");
  assert.deepEqual(errors, []);
  writeFileSync("test-results/feature-measurements.json", JSON.stringify(report.feature_measurements, null, 2) + "\n");
  await page.close();
};
