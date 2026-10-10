const assert = require("node:assert/strict");
const {readFileSync,writeFileSync} = require("node:fs");
const lessons=JSON.parse(readFileSync("examples/playground/lessons.json","utf8")).filter(x=>x.module==="conditions");
module.exports=async(browser,url,report)=>{
  const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:"UTC"});
  const errors=[];page.on("pageerror",e=>errors.push(e.message));
  const ready=()=>page.waitForFunction(()=>feature?.current&&!document.getElementById("feature-controls").disabled);
  for(const lesson of lessons){
    await page.goto(url);await page.locator(`#feature-list a[href="#${lesson.id}"]`).click();await ready();
    const baseline=await page.evaluate(()=>structuredClone(feature.current));
    for(const step of lesson.steps){
      if(step.id!=="initial"){
        if(step.id==="restored")await page.locator("#feature-restore").click();
        else{
          await page.locator(`[data-step="${step.id}"]`).click();
          assert.equal(await page.evaluate(()=>feature.current),null);
          assert.match(await page.locator("#feature-status").innerText(),/未計算/);
          await page.locator("#feature-run").click();
        }
        await ready();
      }
      const pair=await page.evaluate(()=>structuredClone(feature.current));
      assert.equal(pair.response.status,step.expected.status);
      if(step.expected.status==="INFEASIBLE"){
        assert.equal(await page.locator(".feature-overview").count(),0);
        assert.equal(await page.locator(".feature-input-changes").evaluate(x=>x.open),true);
        assert.match(await page.locator("#feature-output").innerText(),/勤務量下限.*0.*270.*解がないため/s);
      }else{
        assert.equal(pair.response.verification.valid,true);
        assert.equal(pair.response.shortage_summary.total_person_minutes,step.expected.total_person_minutes);
        const text=await page.getByRole("region",{name:"変更と結果の要点"}).innerText();
        assert.match(text,/必須条件は守れています/);
        if(!["initial","restored"].includes(step.id))assert.match(text,/変更した条件/);
        assert.match(text,new RegExp(`現在\\s*${step.expected.total_person_minutes}人分`));
        assert.equal((await page.evaluate(()=>basicTotals(feature.current))).assigned,step.expected.assigned_minutes);
        const region=page.getByRole("region",{name:lesson.id==="rest"?"勤務間の休息":"適用条件と実際の分数",exact:true});
        assert.match(await region.innerText(),/分/);
        if(lesson.id==="scheduled_bounds"&&step.id==="month")assert.match(await region.innerText(),/2026-10-01.*2026-11-01.*360分.*300分/s);
        if(lesson.id==="rest"&&step.id==="longer")assert.match(await region.innerText(),/2026-10-06 06:00.*2026-10-06 12:00.*360分.*420分.*休息条件を満たさない/s);
      }
      if(step.id==="restored")assert.deepEqual(pair,baseline);
      report.interactions.push({lesson:lesson.id,step:step.id,status:pair.response.status});
    }
    const control=page.locator(lesson.id==="scheduled_bounds"?"#condition-min":"#condition-limit");
    await control.fill(lesson.id==="scheduled_bounds"?"270":lesson.id==="rest"?"420":"90");
    assert.equal(await page.evaluate(()=>feature.current),null);
    await page.locator("#feature-run").click();await ready();
    if(lesson.id==="scheduled_bounds"){
      await page.locator("#condition-min").fill("390");await page.locator("#feature-run").click();await ready();
      assert.match(await page.locator("#feature-status").innerText(),/INVALID_INPUT/);
      assert.equal(await page.locator(".feature-overview").count(),0);
      await page.locator("#condition-min").fill("0");await page.locator("#condition-max").fill("360");
      await page.locator("#condition-period").selectOption("2026-10-01T00:00:00+09:00");await page.locator("#feature-run").click();await ready();
      assert.equal(await page.evaluate(()=>conditionMinutes(feature.current)),300);
    }
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const region=page.getByRole("region",{name:lesson.id==="rest"?"勤務間の休息":"適用条件と実際の分数",exact:true});
    await region.focus();await page.keyboard.press("ArrowRight");assert.equal(await region.evaluate(x=>x===document.activeElement),true);
    await page.screenshot({path:`test-results/condition-${lesson.id}-mobile.png`,fullPage:true});
    await page.emulateMedia({forcedColors:"active"});assert.match(await page.locator("#feature-output").innerText(),/必須条件は守れています/);await page.emulateMedia({forcedColors:"none"});
    await page.setViewportSize({width:1440,height:1000});await page.locator("#feature-restore").click();await ready();
    assert.deepEqual(await page.evaluate(()=>structuredClone(feature.current)),baseline);
    report.feature_measurements.push(...await page.evaluate(()=>featureMeasurements.splice(0)));
    await page.goto(`${url}#${lesson.id}`);await ready();assert.equal(await page.locator("#feature-fields input").count(),lesson.id==="scheduled_bounds"?2:1);
    report.feature_measurements.push(...await page.evaluate(()=>featureMeasurements.splice(0)));
  }
  assert.deepEqual(errors,[]);writeFileSync("test-results/condition-browser.json",JSON.stringify(report,null,2)+"\n");await page.close();
};
