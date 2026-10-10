"use strict";

function renderPatternFields() {
  const input=feature.input, rule=input.constraints[0], area=$("feature-fields");
  if (["consecutive_days_off","rest_after_shift"].includes(lesson.id)) area.append(basicSelect("pattern-days","完全休日の連続日数（下限・日）",rule.min_days,
    (lesson.id==="consecutive_days_off" ? [1,2,3,4] : [1,2,3]).map(n=>[n,n]),(v,n)=>{v.constraints[0].min_days=Number(n);}));
  if (lesson.id==="consecutive_days_off") area.append(basicSelect("pattern-off","完全休日数下限（別条件・日）",input.constraints[1].min_days,[[0,0],[1,1]],(v,n)=>{v.constraints[1].min_days=Number(n);}));
  if (["rest_after_shift","worked_date_groups"].includes(lesson.id)) {
    const date=lesson.id==="rest_after_shift" ? "2026-10-06" : "2026-10-10", hour=lesson.id==="rest_after_shift" ? "06:00" : "02:00";
    area.append(basicSelect("pattern-end","原勤務の終端（Asia/Tokyo）",input.shift_candidates[0].segments[0].interval.end,
      [[`${date}T${hour}:00+09:00`,`${date} ${hour}`],[`${date}T00:00:00+09:00`,`${date} 00:00`]],(v,n)=>{v.shift_candidates[0].segments[0].interval.end=n;}));
  }
  if (["rest_after_shift","forbidden_successions"].includes(lesson.id)) {
    const category=input.shift_categories.at(-1);
    area.append(basicSelect("pattern-overlap",`${category.label}分類の最低重なり（分）`,category.min_overlap_minutes,
      (lesson.id==="rest_after_shift" ? [60,480] : [30,90]).map(n=>[n,n]),(v,n)=>{v.shift_categories.at(-1).min_overlap_minutes=Number(n);}));
  }
  if (lesson.id==="rest_after_shift") area.append(basicSelect("pattern-minimum","深夜需要の必須最低人数（人）",input.demand[1].minimum_people,[[0,0],[1,1]],(v,n)=>{v.demand[1].minimum_people=Number(n);}));
  if (lesson.id==="forbidden_successions") area.append(
    basicSelect("pattern-offset","禁止する原開始日差（日）",rule.day_offset,[1,2,3,5].map(n=>[n,n]),(v,n)=>{v.constraints[0].day_offset=Number(n);}),
    basicSelect("pattern-period","評価期間（Asia/Tokyo・終端を含まない）",`${rule.evaluation_period.start}/${rule.evaluation_period.end}`,
      [5,6].map(n=>[`2026-10-0${n}T00:00:00+09:00/2026-10-08T00:00:00+09:00`,`10月${n}日〜8日`]),(v,n)=>{const [start,end]=n.split("/");v.constraints[0].evaluation_period={start,end};}));
  if (lesson.id==="worked_date_groups") {
    const groups=feature.initial.constraints[0].date_groups, combined=[{id:"combined",dates:groups.flatMap(g=>g.dates)}];
    area.append(basicSelect("pattern-groups","勤務する日付群の上限（群）",rule.max_groups,[0,1,2].map(n=>[n,n]),(v,n)=>{v.constraints[0].max_groups=Number(n);}),
      basicSelect("pattern-grouping","明示した日付群の分け方",JSON.stringify(rule.date_groups),[[JSON.stringify(groups),"2群：10・11日／17・18日"],[JSON.stringify(combined),"1群：10・11・17・18日"]],
        (v,n)=>{v.constraints[0].date_groups=JSON.parse(n);}));
  }
}
function patternOverlap(shift,category) {
  const ranges=[];
  for (const [a,b] of category.intervals.map(i=>[Date.parse(i.start),Date.parse(i.end)]).sort((a,b)=>a[0]-b[0])) {
    if (ranges.length && a<=ranges.at(-1)[1]) ranges.at(-1)[1]=Math.max(b,ranges.at(-1)[1]); else ranges.push([a,b]);
  }
  return ranges.reduce((n,[a,b])=>n+basicMinutes(shift.segments,{start:new Date(a).toISOString(),end:new Date(b).toISOString()}),0);
}
function patternDate(day,offset) { return new Date(Date.parse(`${day}T00:00:00Z`)+offset*86400000).toISOString().slice(0,10); }
function patternInfo(pair) {
  const input=pair.input, rule=input.constraints[0], days=dayRows(pair,input.planning_window), first=rule.evaluation_period.start.slice(0,10), last=rule.evaluation_period.end.slice(0,10);
  const inPeriod=day=>first<=day && day<last, off=days.filter(d=>inPeriod(d.day)&&!d.occupied).length;
  const runs=[];
  for (const d of days) {
    if (d.occupied) continue;
    if (runs.length && patternDate(runs.at(-1).end,1)===d.day) { runs.at(-1).end=d.day; runs.at(-1).length++; }
    else runs.push({start:d.day,end:d.day,length:1});
  }
  const intersecting=runs.filter(r=>r.start<last && first<=r.end);
  const candidates=input.shift_candidates.map(s=>({...s,selected:pair.response.solution.shifts.some(t=>t.candidate_id===s.id)}));
  const matches=(s,id)=>{const c=input.shift_categories.find(c=>c.id===id);return patternOverlap(s,c)>=c.min_overlap_minutes;};
  const rest=rule.type==="days_off_after_shift" ? candidates.filter(s=>matches(s,rule.category_id)).map(s=>{
    const end=s.segments.at(-1).interval.end, date=new Intl.DateTimeFormat("en-CA",{timeZone:input.planning_window.timezone,year:"numeric",month:"2-digit",day:"2-digit"}).format(Date.parse(end)-1);
    // shortcut: 教材はAsia/Tokyo固定。別タイムゾーンの教材追加時に00:00の生成を見直す。
    return {shift:s,end,lastDay:date,until:`${patternDate(date,rule.min_days+1)}T00:00:00+09:00`};
  }) : [];
  const pairs=[];
  if (rule.type==="forbidden_shift_successions") for (const a of candidates.filter(s=>matches(s,rule.from_category_id))) {
    const day=a.segments[0].interval.start.slice(0,10), target=patternDate(day,rule.day_offset);
    if (day>=last || (day<first && !inPeriod(target))) continue;
    for (const b of candidates.filter(s=>matches(s,rule.to_category_id)&&s.segments[0].interval.start.slice(0,10)===target)) pairs.push({a,b,target});
  }
  const occupied=new Set(days.filter(d=>d.occupied).map(d=>d.day));
  const groups=(rule.date_groups || []).map(g=>({...g,touched:g.dates.filter(d=>occupied.has(d))}));
  return {days,off,runs:intersecting,shortest:intersecting.length ? Math.min(...intersecting.map(r=>r.length)) : null,candidates,rest,pairs,groups};
}
function patternIndicators(pair,base) {
  const current=patternInfo(pair), before=base && operationView(lesson.operation,base.response).validPlan ? patternInfo(base) : null;
  if (lesson.id==="consecutive_days_off") return [featureMetric("評価期間内の完全休日",before?.off ?? null,current.off,"日"),
    featureMetric("評価と交差する休日区間 · 確認範囲の最短",before ? before.shortest==null ? "休日なし" : `${before.shortest}日` : null,current.shortest==null ? "休日なし" : `${current.shortest}日`,"")];
  if (lesson.id==="rest_after_shift") {
    const boundary=featureMetric("最も早い次勤務（Asia/Tokyo）",before ? before.rest.length ? dated(before.rest[0].until) : "対象勤務なし" : null,current.rest.length ? dated(current.rest[0].until) : "対象勤務なし","");
    boundary.classList.add("feature-condition");
    return [featureMetric("夜勤分類に該当する候補",before?.rest.length ?? null,current.rest.length,"件"),boundary];
  }
  if (lesson.id==="forbidden_successions") return [featureMetric("禁止対象となる候補の組",before?.pairs.length ?? null,current.pairs.length,"組")];
  return [featureMetric("勤務した日付群",before ? before.groups.filter(g=>g.touched.length).length : null,current.groups.filter(g=>g.touched.length).length,"群"),
    featureMetric("勤務が触れた群内日付（群数とは別）",before ? before.groups.reduce((n,g)=>n+g.touched.length,0) : null,current.groups.reduce((n,g)=>n+g.touched.length,0),"日")];
}
function patternPlan(pair,base) {
  const input=pair.input, rule=input.constraints[0], info=patternInfo(pair), previous=base && operationView(lesson.operation,base.response).validPlan ? patternInfo(base) : null, area=node("div");
  area.append(node("p",`評価期間：${datedRange(rule.evaluation_period)}（終端を含まない）。計画内の前後余白も表示します。`,{class:"note"}));
  if (lesson.id==="consecutive_days_off") {
    area.append(node("p",`連続休日下限${rule.min_days}日／完全休日数下限${input.constraints[1].min_days}日（別条件）。休日がない場合、連続休日の条件だけでは違反になりません。`));
    area.append(scroll("連続休日の区間",table("評価期間と交差する各区間。期間端で切らず、確認範囲内で数えます。計画外の続きは推定しません。",["開始日","最終日","確認範囲の連続日数","下限","充足"],info.runs.map(r=>node("tr","",{},[
      node("th",r.start,{scope:"row"}),node("td",r.end),node("td",`${r.length}日`),node("td",`${rule.min_days}日`),node("td","条件内")])))));
    if (!info.runs.length) area.append(node("p","評価期間に完全休日なし。休日を確保するには別の休日数条件が必要です。"));
  }
  if (lesson.id==="rest_after_shift") {
    area.append(scroll("勤務後の休みの境界",table("最終終了後の残り時間と、最後の占有日の翌日から指定数の完全休日を休みます。",["対象勤務","原勤務最終終了","最後の占有日","完全休日下限","最も早い次勤務"],info.rest.map(r=>node("tr","",{},[
      node("th",r.shift.id,{scope:"row"}),node("td",dated(r.end)),node("td",r.lastDay),node("td",`${rule.min_days}日`),node("td",dated(r.until))])))));
    if (!info.rest.length) area.append(node("p","夜勤分類に該当する候補なし。この条件の勤務後の休み義務の対象はありません。"));
  }
  if (lesson.id==="forbidden_successions") {
    area.append(scroll("禁止する開始日の組",table(`原開始日差${rule.day_offset}日。間に別の勤務があっても禁止します。`,["遅番の開始日","禁止する早番の開始日","今回の採用"],info.pairs.map(p=>node("tr","",{},[
      node("th",p.a.segments[0].interval.start.slice(0,10),{scope:"row"}),node("td",p.target),node("td",`遅番${p.a.selected ? "採用" : "不採用"}／早番${p.b.selected ? "採用" : "不採用"}`)])))));
    if (!info.pairs.length) area.append(node("p","分類と原開始日差に該当する禁止対象の候補の組なし。"));
  }
  if (lesson.id==="worked_date_groups") area.append(scroll("明示した日付群",table(`上限${rule.max_groups}群。同じ群の複数日も一群。夜勤明けの占有も含み、週末は推定しません。`,["群ID","明示日付","勤務が触れた日付","群としての件数"],info.groups.map(g=>node("tr","",{},[
    node("th",g.id,{scope:"row"}),node("td",g.dates.join("・")),node("td",g.touched.join("・") || "なし"),node("td",g.touched.length ? "1群" : "0群")])))));
  area.append(scroll("日別の勤務と完全休日",table("Asia/Tokyo · 原勤務が触れる日は占有日。評価期間と前後余白を分けます。",["日付","範囲","初期","現在","変化"],info.days.map(d=>{
    const p=previous?.days.find(p=>p.day===d.day), text=r=>r ? r.occupied ? "占有日" : "完全休日" : "比較不可", changed=!!p && text(p)!==text(d);
    return node("tr","",{class:changed ? "feature-changed" : ""},[node("th",d.day,{scope:"row"}),node("td",rule.evaluation_period.start.slice(0,10)<=d.day && d.day<rule.evaluation_period.end.slice(0,10) ? "評価期間" : "前後の余白"),node("td",text(p)),node("td",text(d)),node("td",changed ? "変更" : "変化なし")]);
  }))));
  const detail=node("details","",{},[node("summary","原勤務と分類の重なり · 採用／不採用の詳細")]);
  detail.append(scroll("候補の原勤務と分類",table("分類区間の和集合と、休憩を除く原勤務全体の重なり分数。待機を含み、分割間を除きます。",["候補ID","原勤務区間","内部休憩","分類の重なり／閾値","今回"],info.candidates.map(s=>node("tr","",{},[
    node("th",s.id,{scope:"row"}),node("td",s.segments.map(t=>datedRange(t.interval)).join(" / ")),node("td",s.segments.flatMap(t=>t.breaks).map(datedRange).join(" / ") || "なし"),node("td",(input.shift_categories || []).map(c=>{const n=patternOverlap(s,c);return `${c.label} ${n}分／${c.min_overlap_minutes}分：${n>=c.min_overlap_minutes ? "該当" : "非該当"}`;}).join(" / ") || "分類を使わない"),node("td",s.selected ? "採用" : "不採用")])))));
  area.append(detail);return area;
}
