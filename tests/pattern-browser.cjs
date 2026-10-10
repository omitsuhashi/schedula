const assert=require("node:assert/strict");
const {readFileSync,writeFileSync}=require("node:fs");
const lessons=JSON.parse(readFileSync("examples/playground/lessons.json","utf8")).filter(x=>x.module==="patterns");
module.exports=async(browser,url,report)=>{
  const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:"UTC"}), errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const ready=()=>page.waitForFunction(()=>feature?.current&&!document.getElementById("feature-controls").disabled);
  const run=async()=>{await page.locator("#feature-run").click();await ready();};
  const select=async(id,value)=>{await page.locator(id).selectOption(value);assert.equal(await page.evaluate(()=>feature.current),null);assert.match(await page.locator("#feature-status").innerText(),/未計算/);};
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
        else{await page.locator(`[data-step="${step.id}"]`).click();assert.equal(await page.evaluate(()=>feature.current),null);await run();}
        await ready();
      }
      const pair=await page.evaluate(()=>structuredClone(feature.current));
      assert.equal(pair.response.status,step.expected.status);
      if(["INVALID_INPUT","INFEASIBLE"].includes(step.expected.status)){
        assert.equal(await page.locator(".feature-overview").count(),0);assert.equal(await page.locator(".feature-input-changes").evaluate(x=>x.open),true);
        assert.match(await page.locator("#feature-output").innerText(),/変更した条件.*解がないため/s);
        if(step.id==="margin")assert.match(await page.locator("#feature-output").innerText(),/INCOMPLETE_HISTORY/);
      }else{
        assert.equal(pair.response.verification.valid,true);assert.equal(pair.response.shortage_summary.total_person_minutes,step.expected.total_person_minutes);
        const summary=await page.getByRole("region",{name:"変更と結果の要点"}).innerText();assert.match(summary,/必須条件は守れています/);
        if(!["initial","restored"].includes(step.id))assert.match(summary,/変更した条件/);
        const info=await page.evaluate(()=>patternInfo(feature.current));
        if(lesson.id==="consecutive_days_off"){
          assert.equal(info.off,step.expected.off_days);assert.equal(info.shortest,step.expected.shortest_run);
          assert.match(await page.locator("#feature-output").innerText(),/別条件.*休日がない場合/s);
          if(step.id==="no_holiday")assert.match(summary,/休日なし/);
          if(step.id==="three")assert.match(await page.getByRole("region",{name:"連続休日の区間",exact:true}).innerText(),/2026-10-08.*2026-10-11.*4日.*3日/s);
        }else if(lesson.id==="rest_after_shift"){
          assert.equal(info.rest.length,step.expected.classified_candidates);assert.equal(info.rest[0]?.until || null,step.expected.earliest_next);
          if(step.id==="initial")assert.match(await page.getByRole("region",{name:"勤務後の休みの境界",exact:true}).innerText(),/2026-10-06 06:00.*2026-10-06.*2日.*2026-10-09 00:00/s);
          if(step.id==="classification")assert.match(summary,/対象勤務なし/);
        }else if(lesson.id==="forbidden_successions"){
          assert.equal(info.pairs.length,step.expected.candidate_pairs);assert.equal(info.pairs.filter(p=>p.a.selected&&p.b.selected).length,0);
          if(step.id==="period")assert.match(await page.getByRole("region",{name:"禁止する開始日の組",exact:true}).innerText(),/2026-10-05.*2026-10-07/s);
        }else{
          assert.equal(info.groups.filter(g=>g.touched.length).length,step.expected.worked_groups);assert.equal(info.groups.reduce((n,g)=>n+g.touched.length,0),step.expected.group_days);
          assert.match(summary,/群数とは別/);assert.match(await page.getByRole("region",{name:"明示した日付群",exact:true}).innerText(),/同じ群の複数日も一群/);
        }
        await page.getByText("原勤務と分類の重なり · 採用／不採用の詳細",{exact:true}).click();
        const detail=await page.getByRole("region",{name:"候補の原勤務と分類",exact:true}).innerText();
        if(lesson.id==="rest_after_shift"&&step.id!=="midnight")assert.match(detail,/夜勤 450分／(?:60|480)分/);
        if(lesson.id==="forbidden_successions")assert.match(detail,/早番 60分／(?:30|90)分/);
        await page.getByText("原勤務と分類の重なり · 採用／不採用の詳細",{exact:true}).click();
      }
      if(step.id==="restored")assert.deepEqual(pair,baseline);
      report.interactions.push({lesson:lesson.id,step:step.id,status:pair.response.status});
    }
    if(lesson.id==="consecutive_days_off"){await select("#pattern-days","2");await run();await select("#pattern-off","0");await run();assert.equal(await page.evaluate(()=>patternInfo(feature.current).off),0);}
    if(lesson.id==="rest_after_shift"){
      await select("#pattern-days","1");await run();await select("#pattern-overlap","480");await run();await select("#pattern-minimum","1");await run();
      await page.locator("#feature-restore").click();await ready();await select("#pattern-end","2026-10-06T00:00:00+09:00");await run();assert.equal(await page.evaluate(()=>patternInfo(feature.current).rest[0].until),"2026-10-08T00:00:00+09:00");
    }
    if(lesson.id==="forbidden_successions"){
      await select("#pattern-offset","1");await run();await select("#pattern-overlap","90");await run();
      await page.locator("#feature-restore").click();await ready();await select("#pattern-period","2026-10-06T00:00:00+09:00/2026-10-08T00:00:00+09:00");await run();assert.equal(await page.evaluate(()=>patternInfo(feature.current).pairs.length),1);
    }
    if(lesson.id==="worked_date_groups"){
      await select("#pattern-groups","1");await run();const combined=JSON.stringify([{id:"combined",dates:["2026-10-10","2026-10-11","2026-10-17","2026-10-18"]}]);await select("#pattern-grouping",combined);await run();assert.equal(await page.evaluate(()=>feature.current.response.shortage_summary.total_person_minutes),0);
      await page.locator("#feature-restore").click();await ready();await select("#pattern-end","2026-10-10T00:00:00+09:00");await run();assert.equal(await page.evaluate(()=>patternInfo(feature.current).groups.reduce((n,g)=>n+g.touched.length,0)),2);
    }
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const region=page.getByRole("region",{name:"日別の勤務と完全休日",exact:true});await region.focus();await page.keyboard.press("ArrowRight");assert.equal(await region.evaluate(x=>x===document.activeElement),true);
    await page.screenshot({path:`test-results/pattern-${lesson.id}-mobile.png`,fullPage:true});
    await page.emulateMedia({forcedColors:"active"});assert.match(await region.innerText(),/占有日.*完全休日/s);await page.emulateMedia({forcedColors:"none"});
    await page.setViewportSize({width:1440,height:1000});await page.locator("#feature-restore").click();await ready();assert.deepEqual(await page.evaluate(()=>structuredClone(feature.current)),baseline);
    report.feature_measurements.push(...await page.evaluate(()=>featureMeasurements.splice(0)));
    await page.goto(`${url}#${lesson.id}`);await ready();assert.equal(await page.locator("#feature-fields select").count(),lesson.editable_fields.length);
    report.feature_measurements.push(...await page.evaluate(()=>featureMeasurements.splice(0)));
  }
  assert.deepEqual(errors,[]);writeFileSync("test-results/pattern-browser.json",JSON.stringify(report,null,2)+"\n");await page.close();
};
