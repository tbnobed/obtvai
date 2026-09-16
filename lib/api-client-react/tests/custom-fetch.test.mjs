import { test } from "node:test";
import assert from "node:assert/strict";
import { ApiError } from "../src/custom-fetch.ts";

function error(data) {
  return new ApiError(new Response(null, { status: 422, statusText: "Unprocessable Entity" }),
    data, { method: "POST", url: "/api/campaigns" });
}

test("campaign validation errors name the rejected field without echoing input", () => {
  const result = error({ error: { message: "Request validation failed", details: [
    { loc: ["body", "project_action", "name"], msg: "Must be at most 200 characters", input: "private input" },
  ] } });
  assert.match(result.message, /project action.name: Must be at most 200 characters/);
  assert.doesNotMatch(result.message, /private input/);
});

test("structured domain errors and ordinary FastAPI errors remain readable", () => {
  assert.match(error({ error: { message: "Select an existing project" } }).message, /Select an existing project/);
  assert.match(error({ detail: "Project not found" }).message, /Project not found/);
  assert.match(error({ detail: [{ loc: ["body", "name"], msg: "Required" }] }).message, /name: Required/);
});