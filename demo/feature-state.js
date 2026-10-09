"use strict";

// 操作結果と有効な計画を分け、解なし・無効案も初期比較元として保持する。
function operationView(operation, response) {
  if (operation === "solve") return {
    validPlan: ["OPTIMAL", "FEASIBLE", "PARTIAL"].includes(response.status) &&
      response.verification?.valid === true && !!response.solution,
    canSolve: true,
  };
  if (operation === "verify") return {
    validPlan: ["VALID", "PARTIAL"].includes(response.status) && response.verification?.valid === true,
    canSolve: false,
  };
  if (operation === "assemble") return {
    validPlan: false,
    canSolve: response.status === "VALID" && !!response.request,
  };
  if (operation === "record") return {
    validPlan: response.current_verification?.verification?.valid === true,
    canSolve: false,
  };
  throw new Error("未対応の操作です。");
}

function featureState(input, operation) {
  const state = {initial: structuredClone(input), input: structuredClone(input), operation,
    baseline: null, current: null, previous: null, revision: 0};
  state.edit = input => {
    state.revision++;
    state.input = structuredClone(input);
    if (state.current) state.previous = state.current;
    state.current = null;
  };
  state.receive = (response, revision) => {
    if (revision !== state.revision) return false;
    state.current = {input: structuredClone(state.input), response: structuredClone(response)};
    if (!state.baseline && JSON.stringify(state.input) === JSON.stringify(state.initial))
      state.baseline = structuredClone(state.current);
    return true;
  };
  state.restore = () => {
    state.edit(state.initial);
    state.current = structuredClone(state.baseline);
    state.previous = null;
  };
  return state;
}

if (typeof module !== "undefined") module.exports = {featureState, operationView};
