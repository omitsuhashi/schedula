// 実ブラウザーと実エンジンの結合確認。再現しにくい状態だけ応答サンプルを使う。
const assert = require("node:assert/strict");
const {spawn} = require("node:child_process");
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
  assert.equal(pair.response.status, expected.status);
  if (expected.status === "OPTIMAL") {
    assert.deepEqual([pair.response.verification.performed, pair.response.verification.valid], [true, true]);
    const count = pair.response.solution.assignments.reduce((sum, item) => sum + (Date.parse(item.interval.end) - Date.parse(item.interval.start)) / 1800000, 0);
    assert.equal(count, expected.assigned_slots);
    assert.equal(await page.locator("#output table").count(), 2);
  } else {
    assert.equal(pair.response.solution, null);
    assert.equal(await page.locator("#output table").count(), 0);
    assert.ok(pair.response.diagnostics.some(item => item.code === expected.diagnostic.code));
    assert.ok(!(await page.locator("#comparison").innerText()).includes("担当差分："));
  }
  return pair;
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
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let acceptDialog = true;
  page.on("dialog", dialog => acceptDialog ? dialog.accept() : dialog.dismiss());
  await page.goto(url);
  let initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  await page.screenshot({path: "test-results/playground-desktop.png", fullPage: true});

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
      if (scenario.id === "absence" && step.id === "repaired") assert.deepEqual(pair.input.employees[0].availability, []);
      report.scenarios.push({scenario: scenario.id, step: step.id, status: pair.response.status, verification: pair.response.verification});
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
  await status(page, "INFEASIBLE");
  assert.equal(await page.locator("#output table").count(), 0);
  await page.locator("#restore").click();
  initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  await page.locator('[data-pointer="/employees/0/availability/0/end"]').selectOption("2026-10-06T11:00:00+09:00");
  await page.locator("#calculate").click();
  await status(page, "入力不備");
  await page.locator("#restore").click();
  initial = await verified(page, {status: "OPTIMAL", assigned_slots: 22});
  report.interactions.push("技能チェックをキーボードで編集して解なしを実計算、勤務可能時間の逆転を拒否");

  // 以下は実エンジンの実測ではなく、表示・応答失効を確認する応答サンプル。
  for (const state of ["FEASIBLE", "INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "BACKEND_UNAVAILABLE", "INTERNAL_ERROR"]) {
    await page.route("**/solve", async route => {
      const result = structuredClone(initial.response);
      result.request_id = route.request().postDataJSON().request_id;
      result.status = state;
      if (state !== "FEASIBLE") { result.solution = null; result.objectives = []; result.verification = {performed: false, valid: null, violations: []}; }
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
  for (const kind of ["http-error", "communication", "request-id", "verification", "malformed"]) {
    await page.route("**/solve", async route => {
      if (kind === "communication") { await route.abort(); return; }
      if (kind === "http-error") { await route.fulfill({status: 503, json: {error: {code: "BUSY", message: "計算中", json_pointer: null}}}); return; }
      const result = structuredClone(initial.response);
      result.request_id = kind === "request-id" ? "old_request" : route.request().postDataJSON().request_id;
      if (kind === "verification") result.verification.valid = false;
      if (kind === "malformed") result.solution.assignments = [{}];
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
  assert.deepEqual(errors, []);
  report.page_errors = errors;
  writeFileSync("test-results/playground-browser.json", JSON.stringify(report, null, 2) + "\n");
  console.log("3シナリオ・入力不備・比較・復元・キーボード・狭い画面・応答失効：成功");
}

main().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server) server.kill("SIGINT");
});
