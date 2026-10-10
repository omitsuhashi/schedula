const assert = require("node:assert/strict");
const {readFileSync, writeFileSync} = require("node:fs");
const lessons = JSON.parse(readFileSync("examples/playground/lessons.json", "utf8")).filter(x => x.module === "basic");
module.exports = async (browser, url, report) => {
  const page = await browser.newPage({viewport:{width:1440,height:1000},timezoneId:"UTC"});
  const errors=[];page.on("pageerror",error=>errors.push(error.message));
  const ready=()=>page.waitForFunction(()=>feature?.current&&!document.getElementById("feature-controls").disabled);
  const controls={skills:["#basic-skill","1"],availability:["#basic-availability","none"],shift_candidates:["#basic-start","11:00"],breaks:["#basic-break","2026-10-05T11:00:00+09:00"],overnight:["#basic-night-end","2026-10-06T07:00:00+09:00"],split_shift:["#basic-gap","360"],coverage_24h:["#basic-need","2"],coverage_48h:["#basic-rest","1020"]};
  for (const lesson of lessons) {
    await page.goto(url);await page.locator(`#feature-list a[href="#${lesson.id}"]`).click();await ready();
    assert.equal(await page.evaluate(()=>location.hash),`#${lesson.id}`);
    const baseline=await page.evaluate(()=>structuredClone(feature.current));
    for (const step of lesson.steps) {
      if (step.id!=="initial") {
        if(step.id==="restored")await page.locator("#feature-restore").click();
        else {
          await page.locator(`[data-step="${step.id}"]`).click();
          assert.equal(await page.locator(".feature-overview").count(),0);
          assert.match(await page.locator("#feature-status").innerText(),/未計算/);
          assert.equal(await page.locator(".feature-input-changes").evaluate(x=>x.open),true);
          await page.locator("#feature-run").click();
        }
        await ready();
      }
      const pair=await page.evaluate(()=>structuredClone(feature.current));
      assert.equal(pair.response.status,step.expected.status);
      assert.equal(pair.response.verification.valid,true);
      assert.equal(pair.response.shortage_summary.total_person_minutes,step.expected.total_person_minutes);
      const totals=await page.evaluate(()=>basicTotals(feature.current));
      assert.equal(totals.original,step.expected.original_work_minutes);
      assert.equal(totals.assigned,step.expected.assigned_minutes);
      const summary=page.getByRole("region",{name:"変更と結果の要点"});
      assert.match(await summary.innerText(),new RegExp(`現在\\s*${step.expected.total_person_minutes}人分`));
      if (step.id!=="initial"&&step.id!=="restored")assert.match(await summary.innerText(),/変更した条件/);
      if(lesson.id==="skills"&&step.id==="lower")assert.match(await summary.innerText(),/service レベル2.*service レベル1/s);
      if(lesson.id==="skills"&&step.id==="requirement")assert.match(await summary.innerText(),/最低レベル2.*最低レベル1/s);
      if(lesson.id==="shift_candidates"&&["initial","later","shorter"].includes(step.id))assert.match(await page.getByRole("region",{name:"選ばれた候補"}).innerText(),step.id==="initial"?/テンプレートから展開した候補/:/直接指定した候補/);
      if(lesson.id==="overnight")assert.match(await page.getByRole("region",{name:"日付付き勤務表"}).innerText(),/2026-10-05.*2026-10-06.*Asia\/Tokyo/s);
      if(lesson.id==="split_shift"&&step.id!=="long_gap")assert.match(await page.getByRole("region",{name:"日付付き勤務表"}).innerText(),/分割間の非勤務/);
      if(lesson.id.startsWith("coverage_"))assert.equal(await page.locator(".basic-day").count(),lesson.id==="coverage_24h"?1:2);
      assert.match(await page.locator(".basic-day > summary").first().innerText(),/2026-10-05 Asia\/Tokyo/);
      if(lesson.id==="coverage_48h"&&step.id==="rest")assert.match(await page.getByRole("region",{name:"候補間の休息"}).innerText(),/960分.*1020分.*休息条件を満たさない/s);
      if(step.id==="restored")assert.deepEqual(pair,baseline);
      report.interactions.push({lesson:lesson.id,step:step.id,status:pair.response.status,verification:pair.response.verification});
    }
    const [selector,value]=controls[lesson.id],control=page.locator(selector);
    if(await control.evaluate(x=>x.tagName)==="SELECT")await control.selectOption(value);else await control.fill(value);
    assert.equal(await page.evaluate(()=>feature.current),null);
    await page.locator("#feature-run").click();await ready();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const region=page.getByRole("region",{name:lesson.id==="skills"?"担当資格の比較":lesson.id==="availability"?"JSON の担当配置表":"日付付き勤務表",exact:true}).first();
    await region.focus();await page.keyboard.press("ArrowRight");
    assert.equal(await region.evaluate(x=>x===document.activeElement),true);
    await page.screenshot({path:`test-results/basic-${lesson.id}-mobile.png`,fullPage:true});
    await page.emulateMedia({forcedColors:"active"});assert.match(await summaryText(page),/必須条件は守れています/);await page.emulateMedia({forcedColors:"none"});
    await page.setViewportSize({width:1440,height:1000});await page.locator("#feature-restore").click();await ready();
    assert.deepEqual(await page.evaluate(()=>structuredClone(feature.current)),baseline);
    report.feature_measurements ||= []; report.feature_measurements.push(...await page.evaluate(()=>featureMeasurements.splice(0)));
  }
  assert.deepEqual(errors,[]);writeFileSync("test-results/basic-browser.json",JSON.stringify(report,null,2)+"\n");await page.close();
};
async function summaryText(page){return page.getByRole("region",{name:"変更と結果の要点"}).innerText();}
