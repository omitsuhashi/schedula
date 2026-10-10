"use strict";

function isWorkLesson() { return ["basic", "conditions", "days"].includes(lesson?.module); }
function basicSelect(id, label, value, choices, update) {
  const select = node("select", "", {id}, choices.map(([value, label]) => node("option", label, {value})));
  select.value = String(value);
  select.addEventListener("change", () => { const input = clone(feature.input); update(input, select.value); featureEdited(input); });
  return node("label", `${label} `, {for: id}, [select]);
}
function basicAbsent(employee) {
  const checkbox = node("input", "", {id: "basic-absent", type: "checkbox"});
  checkbox.checked = !feature.input.employees.find(item => item.id === employee).availability.length;
  checkbox.addEventListener("change", () => {
    const input = clone(feature.input);
    input.employees.find(item => item.id === employee).availability = checkbox.checked ? [] : clone(feature.initial.employees.find(item => item.id === employee).availability);
    featureEdited(input);
  });
  return node("label", "", {}, [checkbox, document.createTextNode(` ${employee.toUpperCase()}を勤務不可にする`)]);
}
function basicNumber(id, label, value, min, max, update) {
  const input = node("input", "", {id, type: "number", min, max, step: 30, required: ""}); input.value = value;
  input.addEventListener("input", () => { const request = clone(feature.input); update(request, input.valueAsNumber); featureEdited(request); });
  return node("label", `${label}（分） `, {for: id}, [input]);
}
function renderBasicFields() {
  const area = $("feature-fields"), input = feature.input;
  if (lesson.module === "days") {
    const rule=input.constraints[0];
    for (const [field,label] of [["min_days","日数下限"],["max_days","日数上限"]]) area.append(basicSelect(`day-${field}`, `${label}（日）`, rule[field],
      Array.from({length:6},(_,n)=>[n,n]), (v,n)=>{v.constraints[0][field]=Number(n);}));
    area.append(basicSelect("day-period", "評価期間（Asia/Tokyo・終端を含まない）", rule.interval.start,
      [["2026-10-05T00:00:00+09:00","10月5日〜10日：計画期間"],["2026-10-04T00:00:00+09:00","10月4日〜10日：確認済み実績込み"],["2026-10-09T00:00:00+09:00","10月9日〜10日：0時終了の翌日"]],
      (v,n)=>{v.constraints[0].interval={start:n,end:"2026-10-10T00:00:00+09:00"};}));
  }
  if (["assigned_limit", "scheduled_limit", "rest"].includes(lesson.id)) area.append(
    basicNumber("condition-limit", lesson.editable_fields[0].label, input.constraints[0].limit_minutes, 0, 1440, (v,n) => { v.constraints[0].limit_minutes=n; }));
  if (lesson.id === "scheduled_bounds") {
    const rule=input.constraints[0];
    area.append(basicNumber("condition-min", "Aの期間別勤務量の下限", rule.min_minutes, 0, 1440, (v,n) => { v.constraints[0].min_minutes=n; }),
      basicNumber("condition-max", "Aの期間別勤務量の上限", rule.max_minutes, 0, 1440, (v,n) => { v.constraints[0].max_minutes=n; }),
      basicSelect("condition-period", "評価期間（Asia/Tokyo）", rule.interval.start, [["2026-10-05T00:00:00+09:00","週：10月5日〜12日"],["2026-10-01T00:00:00+09:00","月：10月1日〜11月1日"]],
        (v,n) => { v.constraints[0].interval={start:n,end:n.includes("10-05") ? "2026-10-12T00:00:00+09:00" : "2026-11-01T00:00:00+09:00"}; }));
  }
  if (lesson.id === "skills") area.append(
    basicSelect("basic-skill", "Aの接客技能レベル", input.employees[0].skills[0].level, [0,1,2].map(n => [n, n]), (v,n) => { v.employees[0].skills[0].level = Number(n); }),
    basicSelect("basic-required", "担当に必要な接客技能レベル", input.roles[0].required_skills[0].min_level, [0,1,2].map(n => [n,n]), (v,n) => { v.roles[0].required_skills[0].min_level = Number(n); }));
  if (lesson.id === "availability") area.append(basicSelect("basic-availability", "Aの勤務可能時間（Asia/Tokyo）", input.employees[0].availability[0]?.start || "none",
    [[feature.initial.employees[0].availability[0].start, "2026-10-05 09:00〜12:00"], ["2026-10-05T10:00:00+09:00", "2026-10-05 10:00〜12:00"], ["none", "勤務不可"]],
    (v,n) => { v.employees[0].availability = n === "none" ? [] : [{start:n,end:feature.initial.employees[0].availability[0].end}]; }));
  if (lesson.id === "shift_candidates") area.append(
    basicSelect("basic-start", "テンプレートの開始（2026-10-05 Asia/Tokyo）", input.shift_templates[0].start_times[0], [["10:00","10:00"],["11:00","11:00"]], (v,n) => { v.shift_templates[0].start_times = [n]; }),
    basicSelect("basic-duration", "テンプレートの勤務長（分）", input.shift_templates[0].segment_options[0][0].duration_minutes, [[60,60],[120,120]], (v,n) => { v.shift_templates[0].segment_options[0][0].duration_minutes = Number(n); }),
    basicSelect("basic-direct", "直接候補（2026-10-05 Asia/Tokyo）", input.shift_candidates[0].segments[0].interval.start, [["2026-10-05T09:00:00+09:00","09:00〜12:00"],["2026-10-05T11:00:00+09:00","11:00〜13:00"]],
      (v,n) => { v.shift_candidates[0].segments[0].interval = {start:n,end:n.includes("T09:") ? "2026-10-05T12:00:00+09:00" : "2026-10-05T13:00:00+09:00"}; }));
  if (lesson.id === "breaks") area.append(
    basicSelect("basic-break", "Aの休憩（2026-10-05 Asia/Tokyo）", input.shift_candidates[0].segments[0].breaks[0].start, [["2026-10-05T10:00:00+09:00","10:00〜11:00"],["2026-10-05T11:00:00+09:00","11:00〜12:00"]],
      (v,n) => { v.shift_candidates[0].segments[0].breaks = [{start:n,end:n.includes("T10:") ? "2026-10-05T11:00:00+09:00" : "2026-10-05T12:00:00+09:00"}]; }), basicAbsent("b"));
  if (lesson.id === "overnight") area.append(
    basicSelect("basic-night-start", "夜勤開始（Asia/Tokyo）", input.shift_candidates[0].segments[0].interval.start, [["2026-10-05T22:00:00+09:00","10月5日22:00"],["2026-10-05T23:00:00+09:00","10月5日23:00"]], (v,n) => { v.shift_candidates[0].segments[0].interval.start=n; }),
    basicSelect("basic-night-end", "夜勤終了（Asia/Tokyo）", input.shift_candidates[0].segments[0].interval.end, [["2026-10-06T06:00:00+09:00","10月6日06:00"],["2026-10-06T07:00:00+09:00","10月6日07:00"]], (v,n) => { v.shift_candidates[0].segments[0].interval.end=n; }));
  if (lesson.id === "split_shift") area.append(
    basicNumber("basic-gap", "分割間の最小間隔", input.constraints[0].limit_minutes, 0, 600, (v,n) => { v.constraints[0].limit_minutes=n; }),
    basicSelect("basic-evening", "夕方の勤務開始（2026-10-05 Asia/Tokyo）", input.shift_candidates[0].segments[1].interval.start, [["2026-10-05T17:00:00+09:00","17:00"],["2026-10-05T18:00:00+09:00","18:00"]], (v,n) => { v.shift_candidates[0].segments[1].interval.start=n; }));
  if (lesson.id.startsWith("coverage_")) {
    area.append(basicSelect("basic-need", "18〜24時の必要人数（各日）", input.demand.find(item => item.id.startsWith("night")).required_people, [[1,1],[2,2]],
      (v,n) => { for (const d of v.demand.filter(item => item.id.startsWith("night"))) d.required_people=Number(n); }), basicAbsent("d"));
    if (lesson.id === "coverage_48h") area.append(basicNumber("basic-rest", "勤務間に必要な休息", input.constraints[0].limit_minutes, 0, 1440, (v,n) => { v.constraints[0].limit_minutes=n; }));
  }
}

function basicMinutes(segments, window = null) {
  const minutes = interval => Math.max(0, (Math.min(Date.parse(interval.end), window ? Date.parse(window.end) : Infinity) - Math.max(Date.parse(interval.start), window ? Date.parse(window.start) : -Infinity)) / 60000);
  return segments.reduce((sum, item) => sum + minutes(item.interval) - item.breaks.reduce((sum,b) => sum + minutes(b),0),0);
}
function basicTotals(pair) {
  const shifts = pair.response.solution.shifts;
  const assigned = pair.response.solution.assignments.reduce((n,a) => n + (Date.parse(a.interval.end)-Date.parse(a.interval.start))/60000,0);
  return {assigned, original: shifts.reduce((n,s) => n+basicMinutes(s.segments),0), scheduled: shifts.reduce((n,s) => n+basicMinutes(s.segments,pair.input.planning_window),0)};
}
function basicQualified(input, employee, role) { return role.required_skills.every(required => employee.skills.some(skill => skill.skill_id === required.skill_id && skill.level >= required.min_level)); }
function conditionMinutes(pair) {
  const rule=pair.input.constraints[0], employee=rule.employee_ids[0];
  if (lesson.id === "assigned_limit") return pair.response.solution.assignments.filter(a=>a.employee_id===employee).reduce((n,a)=>n+(Date.parse(a.interval.end)-Date.parse(a.interval.start))/60000,0);
  const selected=pair.response.solution.shifts.filter(s=>s.employee_id===employee);
  const known=lesson.id === "scheduled_bounds" ? pair.input.continuity.employees.find(e=>e.employee_id===employee) : null;
  return [...selected,...(known?.actual_shifts || []),...(known?.committed_shifts || [])].reduce((n,s)=>n+basicMinutes(s.segments,rule.interval || pair.input.planning_window),0);
}
function basicCards(pair, base) {
  const cards = [];
  for (const {collection, ids, field, label, unit} of lesson.editable_fields) for (const id of ids) {
    const first = feature.initial[collection].find(item => item.id === id), current = pair.input[collection].find(item => item.id === id);
    if (JSON.stringify(first[field]) === JSON.stringify(current[field])) continue;
    const card = featureMetric(`変更した条件 · ${label}${ids.length > 1 ? ` (${current.label || current.interval?.start.slice(0,10) || id})` : ""}`,
      displayField(field,first[field]), displayField(field,current[field]), ["required_people","limit_minutes","min_minutes","max_minutes","min_days","max_days"].includes(field) ? unit : "");
    if (!["required_people","limit_minutes","min_minutes","max_minutes","min_days","max_days"].includes(field)) card.classList.add("feature-condition");
    cards.push(card);
  }
  if (!cards.length) cards.push(node("p", "初期条件からの変更なし。", {class:"note"}));
  if (lesson.module === "days") {
    const previous=base?.response.day_count_summary?.[0].employees[0], current=pair.response.day_count_summary[0].employees[0];
    for (const [field,label] of [["work_days","勤務日：原勤務の開始日"],["occupied_days","占有日：夜勤明けも含む"],["days_off","完全休日：占有のない日"]])
      cards.push(featureMetric(label,previous?.[field] ?? null,current[field],"日"));
    return cards;
  }
  const before = base && operationView(lesson.operation,base.response).validPlan ? basicTotals(base) : null, current = basicTotals(pair);
  if (lesson.id === "skills") {
    const qualified = v => v.employees.filter(e => basicQualified(v,e,v.roles[0])).length;
    cards.push(featureMetric("担当資格のある人",qualified(feature.initial),qualified(pair.input),"人"));
  }
  if (["assigned_limit","scheduled_limit","scheduled_bounds"].includes(lesson.id)) cards.push(featureMetric(
    lesson.id === "assigned_limit" ? "Aが担当した時間" : lesson.id === "scheduled_limit" ? "Aの計画内勤務量（待機込み）" : "Aの評価期間の勤務量（実績・確定勤務込み）",
    before ? conditionMinutes(base) : null,conditionMinutes(pair),"分"));
  if (pair.input.problem_type === "roster") cards.push(featureMetric("計画内の勤務量（休憩・分割間を除く）",before?.scheduled ?? null,current.scheduled,"分"),
    featureMetric("計画内の待機（勤務量に含む）",before ? before.scheduled-before.assigned : null,current.scheduled-current.assigned,"分"));
  else cards.push(featureMetric("担当した時間",before?.assigned ?? null,current.assigned,"分"));
  return cards;
}
function dayFacts(pair) {
  const known=pair.input.continuity.employees[0];
  return [...known.actual_shifts.map(s=>({...s,source:"確認済み実績"})), ...known.committed_shifts.map(s=>({...s,source:"確定勤務"})),
    ...pair.response.solution.shifts.filter(s=>!s.committed_shift_id).map(s=>({...s,source:"今回の採用"}))];
}
function dayRows(pair) {
  const rule=pair.input.constraints[0], window={...pair.input.planning_window,...rule.interval}, slots=jsonSlots({planning_window:window});
  const date=new Intl.DateTimeFormat("en-CA",{timeZone:window.timezone,year:"numeric",month:"2-digit",day:"2-digit"}), facts=dayFacts(pair);
  return [...new Set(slots.map(s=>s.date))].map(day=>{
    const range=slots.filter(s=>s.date===day), start=range[0].start, end=range.at(-1).end;
    const starts=facts.some(s=>date.format(Date.parse(s.segments[0].interval.start))===day);
    const occupied=facts.some(s=>s.segments.some(t=>Date.parse(t.interval.start)<end && start<Date.parse(t.interval.end)));
    return {day,starts,occupied};
  });
}
function dayPlan(pair, base) {
  const rule=pair.input.constraints[0], counts=pair.response.day_count_summary[0].employees[0], value=counts[rule.type==="work_days_bounds" ? "work_days" : "days_off"];
  const area=node("div"), previous=base && operationView(lesson.operation,base.response).validPlan ? dayRows(base) : [];
  const state=r=>r ? `${r.starts ? "勤務開始あり" : "勤務開始なし"} / ${r.occupied ? "占有日" : "完全休日"}` : "評価対象外";
  area.append(scroll("日数条件と集計",table("A · Asia/Tokyo · 評価終端を含まない",["評価期間","数える対象","下限","上限","実際","条件の充足"],[node("tr","",{},[
    node("td",datedRange(rule.interval)),node("td",rule.type==="work_days_bounds" ? "勤務日" : "完全休日"),node("td",`${rule.min_days}日`),node("td",`${rule.max_days}日`),node("td",`${value}日`),node("td","条件内")])])));
  area.append(scroll("日別の数え方",table("勤務開始と占有を分離。夜勤明けは占有日、0時終了は翌日を占有しません。分割勤務は1勤務日。",["日付（Asia/Tokyo）","初期","現在","勤務日","占有日","完全休日","初期からの変化"],dayRows(pair).map(r=>{
    const first=previous.find(p=>p.day===r.day), changed=!!base && state(first)!==state(r);
    return node("tr","",{class:changed ? "feature-changed" : ""},[node("th",r.day,{scope:"row"}),node("td",base ? state(first) : "比較不可"),node("td",state(r)),node("td",r.starts ? "1日" : "0日"),node("td",r.occupied ? "1日" : "0日"),node("td",r.occupied ? "0日" : "1日"),node("td",changed ? "変更" : "変化なし")]);
  }))));
  area.append(node("details","",{},[node("summary","何を数えたか · 実績・確定勤務・今回の採用"),scroll("集計元の原勤務",table("確定勤務は今回の解にも含まれますが、一度だけ数えます。評価期間外の実績はその期間の集計に含めません。",["区分","開始日（Asia/Tokyo）","原勤務区間"],dayFacts(pair).map(s=>node("tr","",{},[
    node("th",s.source,{scope:"row"}),node("td",s.segments[0].interval.start.slice(0,10)),node("td",s.segments.map(t=>datedRange(t.interval)).join(" / "))]))))]));
  return area;
}
function basicPlan(pair, base) {
  if (lesson.module === "days") return dayPlan(pair,base);
  const area = node("div"), input = pair.input, shifts = pair.response.solution.shifts;
  if (lesson.module === "conditions") {
    const rule=input.constraints[0];
    if (lesson.id === "rest") {
      const [first,next]=input.shift_candidates, end=first.segments.at(-1).interval.end, start=next.segments[0].interval.start;
      const gap=(Date.parse(start)-Date.parse(end))/60000;
      area.append(scroll("勤務間の休息",table("前勤務の最終終了から次勤務の最初の開始まで。勤務中の休憩とは別です。",["前勤務終了","次勤務開始","候補間の休息","必要な休息","同時採用の可否","今回の採用"],[node("tr","",{},[
        node("td",dated(end)),node("td",dated(start)),node("td",`${gap}分`),node("td",`${rule.limit_minutes}分`),node("td",gap>=rule.limit_minutes ? "休息条件を満たす" : "休息条件を満たさない"),node("td",shifts.map(s=>s.candidate_id===first.id ? "夜勤" : "日勤").join("・") || "なし")])])));
    } else {
      const bounded=lesson.id === "scheduled_bounds", amount=conditionMinutes(pair);
      area.append(scroll("適用条件と実際の分数",table(bounded ? "評価区間に重なる実績・確定勤務・今回の勤務を一度ずつ集計します。" : "担当時間は役割担当だけ。勤務量は待機を含み、休憩・分割間を除きます。",["対象者","評価期間","下限","上限","実際","条件の充足"],[node("tr","",{},[
        node("th",input.employees.find(e=>e.id===rule.employee_ids[0]).label,{scope:"row"}),node("td",datedRange(rule.interval || input.planning_window)),node("td",bounded ? `${rule.min_minutes}分` : "指定なし"),node("td",`${bounded ? rule.max_minutes : rule.limit_minutes}分`),node("td",`${amount}分`),node("td","条件内")])])));
    }
  }
  if (lesson.id === "skills") area.append(scroll("担当資格の比較",table("必要技能を満たす人だけが担当可能",["従業員","保有レベル","必要レベル","担当資格"],input.employees.map(e => node("tr","",{},[
    node("th",e.label,{scope:"row"}),node("td",e.skills[0].level),node("td",input.roles[0].required_skills[0].min_level),node("td",basicQualified(input,e,input.roles[0]) ? "担当可能" : "担当不可")])))));
  if (input.problem_type === "roster") {
    area.append(scroll("日付付き勤務表",table("Asia/Tokyo · 勤務日は原勤務の開始日。勤務量は休憩を除く実経過分数",["従業員","勤務日","選ばれた原勤務区間","内部休憩","分割間の非勤務","原勤務量","計画内勤務量"],shifts.map(s => {
      const employee=input.employees.find(e=>e.id===s.employee_id);
      const gaps=s.segments.slice(1).map((segment,i)=>datedRange({start:s.segments[i].interval.end,end:segment.interval.start}));
      const previous=base?.response.solution?.shifts.filter(t=>t.employee_id===s.employee_id && t.work_day===s.work_day);
      const changed=previous && !previous.some(t=>JSON.stringify(t.segments)===JSON.stringify(s.segments));
      return node("tr","",{class:changed ? "feature-changed" : ""},[node("th",employee.label,{scope:"row"}),node("td",s.work_day),node("td",s.segments.map(t=>datedRange(t.interval)).join(" / ")),node("td",s.segments.flatMap(t=>t.breaks).map(datedRange).join(" / ") || "なし"),node("td",gaps.join(" / ") || "なし"),node("td",`${basicMinutes(s.segments)}分`),node("td",`${basicMinutes(s.segments,input.planning_window)}分`)]);
    }))));
    if (!shifts.length) area.append(node("p","採用された勤務はありません。条件は緩めず、不足を示しています。"));
    area.append(scroll("個人別勤務量",table("原勤務と計画内への投影を区別します",["従業員","原勤務量","計画内勤務量"],input.employees.map(e=> {
      const selected=shifts.filter(s=>s.employee_id===e.id);
      return node("tr","",{},[node("th",e.label,{scope:"row"}),node("td",`${selected.reduce((n,s)=>n+basicMinutes(s.segments),0)}分`),node("td",`${selected.reduce((n,s)=>n+basicMinutes(s.segments,input.planning_window),0)}分`)]);
    }))));
  }
  if (lesson.id === "shift_candidates") area.append(node("p","候補外の時刻は選びません。直接候補とテンプレートは同じ有限候補集合として扱います。"),
    scroll("選ばれた候補",table("採用した有限候補の種類",["従業員","勤務候補"],shifts.map(s=>node("tr","",{},[node("th",s.employee_id,{scope:"row"}),node("td",input.shift_candidates.some(c=>c.id===s.candidate_id) ? "直接指定した候補" : "テンプレートから展開した候補")])))));
  if (lesson.id === "coverage_48h") {
    const rest=input.constraints.find(c=>c.id==="rest").limit_minutes;
    area.append(scroll("候補間の休息",table("同じ開始時刻の2日分の候補 · 休息は前勤務終了から次勤務開始まで",["従業員","前勤務終了","次勤務開始","候補間の休息","必要な休息","2日とも採用可能"],input.shift_templates.map(t=> {
      const hour=Number(t.start_times[0].slice(0,2));
      const time=(date,h)=>new Date(Date.parse(`${date}T00:00:00+09:00`)+h*3600000).toISOString();
      const end=time(t.dates[0],hour+8),start=time(t.dates[1],hour),gap=(Date.parse(start)-Date.parse(end))/60000;
      return node("tr","",{},[node("th",input.employees.find(e=>e.id===t.employee_ids[0]).label,{scope:"row"}),node("td",dated(new Date(Date.parse(end)+9*3600000).toISOString())),node("td",dated(new Date(Date.parse(start)+9*3600000).toISOString())),node("td",`${gap}分`),node("td",`${rest}分`),node("td",gap>=rest ? "休息条件を満たす" : "休息条件を満たさない")]);
    }))));
  }
  if (!lesson.id.startsWith("coverage_")) area.append(node("p","時間帯表は需要・勤務のある枠を表示します。分割間の非勤務は原勤務表で確認できます。",{class:"note"}));
  const grid=jsonSlots(input), dates=[...new Set(grid.map(s=>s.date))];
  for (const date of dates) {
    const detail=node("details","",{class:"basic-day"},[node("summary",`${date} Asia/Tokyo · 配置人数／必要人数と担当表`)]); detail.open=true;
    const tables=node("div"); renderJSONDay(pair,grid.filter(s=>s.date===date),tables,lesson.id.startsWith("coverage_")); detail.append(tables); area.append(detail);
  }
  return area;
}
