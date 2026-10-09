const assert = require("node:assert/strict");
const {featureState, operationView} = require("../demo/feature-state.js");
for (const [operation, initial, next] of [
  ["solve", {status: "INFEASIBLE", solution: null}, {status: "OPTIMAL", solution: {}, verification: {valid: true}}],
  ["verify", {status: "INVALID_PLAN", verification: {valid: false}}, {status: "VALID", verification: {valid: true}}],
  ["assemble", {status: "INVALID_INPUT", request: null}, {status: "VALID", request: {}}],
  ["record", {current_verification: null}, {current_verification: {verification: {valid: true}}}],
]) {
  const state = featureState({value: 1}, operation);
  assert(state.receive(initial, 0));
  assert(!operationView(operation, state.current.response).validPlan);
  state.edit({value: 2});
  assert.equal(state.current, null);
  assert(!state.receive(initial, 0));
  assert(state.receive(next, 1));
  assert.equal(operationView(operation, next).canSolve, operation === "solve" || operation === "assemble");
  assert.equal(operationView(operation, next).validPlan, operation !== "assemble");
  state.restore();
  assert.deepEqual(state.input, {value: 1});
  assert.deepEqual(state.current.response, initial);
}
console.log("共通状態の制御応答：成功（実API往復・利用者評価とは別）");
