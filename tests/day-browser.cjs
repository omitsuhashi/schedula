const assert=require("node:assert/strict");
const {readFileSync,writeFileSync}=require("node:fs");
const lessons=JSON.parse(readFileSync("examples/playground/lessons.json","utf8")).filter(x=>x.module==="days");
module.exports=async(browser,url,report)=>{
  const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:"UTC"}), errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const ready=()=>page.waitForFunction(()=>feature?.current&&!document.getElementById("feature-controls").disabled);
  for(const lesson of lessons){
    await page.goto(url);await page.locator(`#feature-list a[href="#${lesson.id}"]`).click();await ready();
    assert.equal(await page.locator("#feature-intro").innerText(),lesson.intro);
    await page.getByText("この例の前提・目的順序",{exact:true}).click();
    for(const premise of lesson.premises)assert.ok((await page.locator("#feature-premises").innerText()).includes(premise));
    await page.getByText("この例の前提・目的順序",{exact:true}).click();
    const baseline=await page.evaluate(()=>structuredClone(feature.current));
    for(const step of lesson.steps){
      if(step.id!=="initial"){
        if(step.id==="restored")await page.locator("#feature-restore").click();
        else{await page.locator(`[data-step="${step.id}"]`).click();assert.equal(await page.evaluate(()=>feature.current),null);assert.match(await page.locator("#feature-status").innerText(),/未計算/);await page.locator("#feature-run").click();}
        await ready();
      }
      const pair=await page.evaluate(()=>structuredClone(feature.current));
      assert.equal(pair.response.status,step.expected.status);
      if(!step.expected.day_counts){
        assert.equal(await page.locator(".feature-overview").count(),0);
        assert.equal(await page.locator(".feature-input-changes").evaluate(x=>x.open),true);
        assert.match(await page.locator("#feature-output").innerText(),/変更した条件.*解がないため/s);
        if(step.id==="future")assert.match(await page.locator("#feature-output").innerText(),/INVALID_DAY_COUNT_INTERVAL/);
      }else{
        assert.deepEqual(pair.response.day_count_summary[0].employees[0],step.expected.day_counts);
        assert.equal(pair.response.shortage_summary.total_person_minutes,step.expected.total_person_minutes);
        const summary=await page.getByRole("region",{name:"変更と結果の要点"}).innerText();
        assert.match(summary,/必須条件は守れています/);assert.match(summary,/勤務日.*占有日.*完全休日/s);
        if(!["initial","restored"].includes(step.id))assert.match(summary,/変更した条件/);
        const rows=await page.evaluate(()=>dayRows(feature.current));
        assert.equal(rows.filter(r=>r.starts).length,step.expected.day_counts.work_days);
        assert.equal(rows.filter(r=>r.occupied).length,step.expected.day_counts.occupied_days);
        assert.equal(rows.filter(r=>!r.occupied).length,step.expected.day_counts.days_off);
        const calendar=page.getByRole("region",{name:"日別の数え方",exact:true});
        if(["initial","restored"].includes(step.id)){
          assert.match(await calendar.locator("tr").filter({hasText:"2026-10-06"}).innerText(),/勤務開始なし \/ 占有日.*0日.*1日.*0日/);
          assert.match(await calendar.locator("tr").filter({hasText:"2026-10-07"}).innerText(),/勤務開始あり \/ 占有日.*1日.*1日.*0日/);
          assert.match(await calendar.locator("tr").filter({hasText:"2026-10-09"}).innerText(),/勤務開始なし \/ 完全休日.*0日.*0日.*1日/);
        }
        if(step.id==="history")assert.match(await calendar.locator("tr").filter({hasText:"2026-10-04"}).innerText(),/評価対象外.*勤務開始あり \/ 占有日.*変更/);
        if(step.id==="last_day")assert.equal(rows.length,1);
        await page.getByText("何を数えたか · 実績・確定勤務・今回の採用",{exact:true}).click();
        assert.match(await page.getByRole("region",{name:"集計元の原勤務",exact:true}).innerText(),/確認済み実績.*確定勤務.*今回の採用/s);
        await page.getByText("何を数えたか · 実績・確定勤務・今回の採用",{exact:true}).click();
      }
      if(step.id==="restored")assert.deepEqual(pair,baseline);
      report.interactions.push({lesson:lesson.id,step:step.id,status:pair.response.status});
    }
    await page.locator("#day-min_days").selectOption("3");await page.locator("#day-max_days").selectOption("2");
    assert.equal(await page.evaluate(()=>feature.current),null);await page.locator("#feature-run").click();await ready();
    assert.equal(await page.evaluate(()=>feature.current.response.status),"INVALID_INPUT");assert.equal(await page.locator(".feature-overview").count(),0);
    await page.locator("#day-min_days").selectOption("0");await page.locator("#day-max_days").selectOption("5");
    await page.locator("#day-period").selectOption("2026-10-04T00:00:00+09:00");await page.locator("#feature-run").click();await ready();
    assert.equal(await page.evaluate(()=>feature.current.response.day_count_summary[0].employees[0].work_days),4);
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const region=page.getByRole("region",{name:"日別の数え方",exact:true});await region.focus();await page.keyboard.press("ArrowRight");assert.equal(await region.evaluate(x=>x===document.activeElement),true);
    await page.screenshot({path:`test-results/day-${lesson.id}-mobile.png`,fullPage:true});
    await page.emulateMedia({forcedColors:"active"});assert.match(await region.innerText(),/評価対象外.*変更/s);await page.emulateMedia({forcedColors:"none"});
    await page.setViewportSize({width:1440,height:1000});await page.locator("#feature-restore").click();await ready();assert.deepEqual(await page.evaluate(()=>structuredClone(feature.current)),baseline);
    report.feature_measurements.push(...await page.evaluate(()=>featureMeasurements.splice(0)));
    await page.goto(`${url}#${lesson.id}`);await ready();assert.equal(await page.locator("#feature-fields select").count(),3);
    report.feature_measurements.push(...await page.evaluate(()=>featureMeasurements.splice(0)));
  }
  assert.deepEqual(errors,[]);writeFileSync("test-results/day-browser.json",JSON.stringify(report,null,2)+"\n");await page.close();
};
