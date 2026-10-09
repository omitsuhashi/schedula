const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const ready = page => page.waitForFunction(() => feature?.current && !document.getElementById("feature-controls").disabled);
module.exports = async (page, url, report) => {
  let solves = 0, checks = 0;
  const count = request => { if (request.url().endsWith("/solve-json")) solves++; if (request.url().endsWith("/verify-json")) checks++; };
  page.on("request", count);
  // 自由フォームで目標未指定と明示0、両者未指定を区別する。
  await page.goto(`${url}#shift_count_balance`); await ready(page);
  await page.locator("#feature-target-alice").selectOption("");
  await page.locator("#feature-target-bob").selectOption("");
  const before = solves;
  await page.locator("#feature-run").click();
  assert.equal(solves, before);
  assert.equal(await page.evaluate(() => feature.current), null);
  await page.locator("#feature-target-bob").selectOption("0");
  await page.locator("#feature-run").click(); await ready(page);
  assert.match(await page.locator("#feature-output").innerText(), /Alice：目標未指定・対象外/);
  assert.match(await page.locator("#feature-output").innerText(), /Bob：目標0回/);
  await page.locator("#feature-restore").click(); await ready(page);
  const solveCount = solves;
  const lesson = JSON.parse(readFileSync("examples/playground/lessons.json", "utf8")).find(item => item.id === "verify");
  await page.goto(`${url}#verify`); await ready(page);
  const initial = await page.evaluate(() => structuredClone(feature.current));
  for (const step of lesson.steps) {
    if (step.id !== "initial") {
      if (step.restore) await page.locator("#feature-restore").click();
      else {
        await page.locator(`[data-step="${step.id}"]`).click();
        assert.equal(await page.evaluate(() => feature.current), null);
        assert.match(await page.locator("#feature-status").innerText(), /未検証/);
        await page.locator("#feature-run").click();
      }
    }
    await ready(page);
    const pair = await page.evaluate(() => structuredClone(feature.current));
    assert.equal(pair.response.status, step.expected.status);
    assert.equal(pair.response.shortage_summary?.total_person_minutes ?? null, step.expected.total_person_minutes);
    assert.equal(Object.hasOwn(pair.response, "solver"), false);
    assert.equal(Object.hasOwn(pair.response, "solution"), false);
    assert.match(await page.locator("#feature-output").innerText(), /最適性：認定しない.*不足最小性：認定しない/);
    if (step.id === "invalid") {
      assert.match(await page.locator("#feature-output").innerText(), /DOUBLE_ASSIGNMENT.*\/assignments\/1/);
      const row = page.locator("#feature-output tbody tr").filter({has: page.getByRole("rowheader", {name: "hall", exact: true})});
      assert.match(await row.innerText(), /Bob.*\/assignments\/1.*DOUBLE_ASSIGNMENT/);
    }
    if (step.restore) assert.deepEqual(pair, initial);
    report.interactions.push({lesson: "verify", step: step.id, status: pair.response.status, verification: pair.response.verification});
  }
  assert.equal(solves, solveCount);
  const restoredChecks = checks;
  await page.locator("#feature-restore").click(); await ready(page);
  assert.equal(checks, restoredChecks);
  const select = page.locator("#feature-kitchen");
  await select.focus(); await page.keyboard.press("Home"); await page.keyboard.press("Enter");
  await select.selectOption("");
  assert.equal(await page.evaluate(() => feature.current), null);
  await page.locator("#feature-run").click(); await ready(page);
  assert.equal(await page.evaluate(() => feature.current.response.status), "PARTIAL");
  await page.setViewportSize({width: 390, height: 844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.getByRole("region", {name: "検査対象の表", exact: true}).focus(); await page.keyboard.press("ArrowRight");
  await page.screenshot({path: "test-results/feature-verify-mobile.png", fullPage: true});
  await page.setViewportSize({width: 1440, height: 1000});
  // 公開APIへ実際の不正Requestを渡す。受理/表示は求解Responseを強制しない。
  await page.evaluate(() => { const input = structuredClone(feature.input); input.request.demand[0].required_people = -1; featureEdited(input); });
  await page.locator("#feature-run").click(); await ready(page);
  assert.equal(await page.evaluate(() => feature.current.response.status), "INVALID_INPUT");
  assert.match(await page.locator("#feature-status").innerText(), /検証は未実施/);
  await page.locator("#feature-restore").click(); await ready(page);
  const rejected = await page.evaluate(() => {
    const pair = feature.current, variants = [
      response => { response.shortage_summary.proven_minimal = true; },
      response => { response.verification.valid = false; },
      response => { response.request_id = "wrong"; },
      response => { response.status = "OPTIMAL"; },
      response => { delete response.priority_summary; },
      response => { response.shortage_summary.shortages = [{demand_id: "unknown"}]; },
    ];
    return variants.map(change => { const response = structuredClone(pair.response); change(response); try { acceptVerification(response, pair.input); return false; } catch { return true; } });
  });
  assert.deepEqual(rejected, [true, true, true, true, true, true]);
  await page.route("**/verify-json", route => route.fulfill({status: 503, json: {error: {code: "BUSY", message: "検証中"}}}));
  await select.selectOption("bob"); await page.locator("#feature-run").click();
  await page.waitForFunction(() => !document.getElementById("feature-controls").disabled);
  assert.match(await page.locator("#feature-status").innerText(), /BUSY/);
  assert.equal(await page.evaluate(() => feature.current), null);
  await page.unroute("**/verify-json"); await page.locator("#feature-run").click(); await ready(page);
  assert.equal(await page.evaluate(() => feature.current.response.status), "INVALID_PLAN");
  let release, started;
  const waiting = new Promise(resolve => { started = resolve; });
  await page.route("**/verify-json", async route => {
    const response = await route.fetch(); started();
    await new Promise(resolve => { release = resolve; });
    await route.fulfill({response}).catch(() => {});
  });
  await select.selectOption("alice"); await page.locator("#feature-run").click(); await waiting;
  await page.evaluate(() => { location.hash = "demand"; });
  await page.waitForFunction(() => lesson?.id === "demand");
  release(); await page.unrouteAll({behavior: "wait"}); await ready(page);
  assert.equal(await page.evaluate(() => feature.current.input.request_id), "demo_demand");
  report.response_samples.push("公開verifyの実INVALID_INPUT、無効案から再検証、証明・形式不整合拒否、HTTP失敗復帰、切替後の古い応答排除");
  report.feature_measurements ||= [];
  report.feature_measurements.push(...await page.evaluate(() => featureMeasurements.splice(0)));
  page.off("request", count);
  await page.goto(url);
  await page.locator("#feature-list .feature-cards").first().waitFor();
};
