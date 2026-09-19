import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile, chmod, rm, access } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { runSimulatorGoal } from "../examples/brigade-call.mjs";

const validResult = { type: "result", schema: "jev-ios/run/v1", status: "verified", reason: "exact_labels_visible" };

async function fixture(t, source = `process.stdout.write(JSON.stringify({...${JSON.stringify(validResult)}, args:process.argv.slice(2)})+'\\n');`) {
  const root = await mkdtemp(path.join(os.tmpdir(), "jev-brigade-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const python = path.join(root, "fake python");
  await writeFile(python, `#!${process.execPath}\n${source}\n`);
  await chmod(python, 0o700);
  return { root, python, udid: "00000000-0000-0000-0000-000000000000", bundleId: "example.fixture", goal: "Open settings", expectLabels: ["Settings"], timeoutMs: 3000 };
}

test("direct goal invocation preserves labels, literal values, and optional bounds", async (t) => {
  const options = await fixture(t);
  const literal = "--open $(touch SHELL_SENTINEL); `echo nope`";
  const result = await runSimulatorGoal({ ...options, goal: literal, allowLabels: ["Continue"], maxSteps: 6 });
  assert.deepEqual(result.args.slice(0, 3), ["-m", "jev_ios", "run"]);
  assert.ok(result.args.includes(`--goal=${literal}`));
  assert.ok(result.args.includes("--expect-label=Settings"));
  assert.ok(result.args.includes("--allow-label=Continue"));
  assert.ok(result.args.includes("--max-steps=6"));
  await assert.rejects(access(path.join(options.root, "SHELL_SENTINEL")));
});

test("scenario preserves scenario defaults and forwards every artifact path", async (t) => {
  const { goal, expectLabels, ...options } = await fixture(t);
  const result = await runSimulatorGoal({
    ...options, scenarioPath: "scenarios/showcase.json", tracePath: "runs/daybreak.jsonl",
    reportPath: "runs/daybreak report.html", recordVideoPath: "runs/daybreak.mp4", screenshotPath: "runs/daybreak.png",
    vercelProject: "fixture-project",
  });
  for (const argument of ["--scenario=scenarios/showcase.json", "--trace=runs/daybreak.jsonl", "--report=runs/daybreak report.html", "--record-video=runs/daybreak.mp4", "--screenshot=runs/daybreak.png", "--vercel-project=fixture-project"]) {
    assert.ok(result.args.includes(argument));
  }
  assert.ok(!result.args.some((value) => value.startsWith("--max-steps") || value.startsWith("--goal") || value.startsWith("--expect-label")));
});

test("old direct invocation leaves the CLI's default step count intact", async (t) => {
  const result = await runSimulatorGoal(await fixture(t));
  assert.ok(!result.args.some((value) => value.startsWith("--max-steps")));
});

test("scenario and direct goal inputs are mutually exclusive", async (t) => {
  const options = await fixture(t);
  await assert.rejects(runSimulatorGoal({ ...options, scenarioPath: "flow.json" }), /cannot be combined/);
  await assert.rejects(runSimulatorGoal({ ...options, goal: undefined, scenarioPath: "flow.json" }), /cannot be combined/);
  await assert.rejects(runSimulatorGoal({ ...options, expectLabels: undefined, scenarioPath: "flow.json" }), /cannot be combined/);
});

test("invalid options reject before the executable starts", async (t) => {
  const options = await fixture(t, "require('node:fs').writeFileSync('STARTED', 'started');");
  for (const invalid of [
    { maxSteps: 0 }, { maxSteps: 31 }, { maxSteps: 1.5 }, { maxSteps: null },
    { timeoutMs: 0 }, { timeoutMs: Infinity }, { timeoutMs: 600001 }, { timeoutMs: true }, { killGraceMs: 0 }, { killGraceMs: 20001 },
    { expectLabels: [] }, { expectLabels: [" "] }, { expectLabels: ["a".repeat(301)] },
    { allowLabels: "Settings" }, { allowLabels: Array(31).fill("x") }, { goal: "a".repeat(4001) },
    { tracePath: "" }, { reportPath: "\0" }, { screenshotPath: 42 }, { recordVideoPath: "run.mov" },
    { tracePath: "runs/same", reportPath: "runs/../runs/same" },
  ]) {
    await assert.rejects(runSimulatorGoal({ ...options, ...invalid }));
  }
  await assert.rejects(access(path.join(options.root, "STARTED")));
});

test("split NDJSON and a final line without a newline are supported", async (t) => {
  const raw = JSON.stringify(validResult);
  const options = await fixture(t);
  await writeFile(options.python, `#!${process.execPath}\nprocess.stdout.write('{"type":"observation"}\\n'); process.stdout.write(${JSON.stringify(raw.slice(0, 12))}); setTimeout(()=>process.stdout.write(${JSON.stringify(raw.slice(12))}), 10);\n`);
  assert.equal((await runSimulatorGoal(options)).status, "verified");
});

test("malformed NDJSON rejects and stops a running child", async (t) => {
  const options = await fixture(t, "process.stdout.write('not-json\\n'); setInterval(()=>{},1000);");
  await assert.rejects(runSimulatorGoal(options), /invalid NDJSON/);
});

test("missing, malformed, duplicate, and unverified results reject", async (t) => {
  for (const events of [
    [{ type: "observation" }],
    [{ type: "result", status: "verified" }],
    [validResult, validResult],
    [{ ...validResult, status: "blocked" }],
    [null],
  ]) {
    const source = `process.stdout.write(${JSON.stringify(events.map((event) => JSON.stringify(event)).join("\n") + "\n")});`;
    await assert.rejects(runSimulatorGoal(await fixture(t, source)));
  }
});

test("nonzero exits and error events never echo private subprocess text", async (t) => {
  for (const source of [
    "process.stderr.write('SECRET_FIXTURE_TOKEN'); process.exitCode=2;",
    "process.stdout.write(JSON.stringify({type:'error',error:'SECRET_FIXTURE_TOKEN'})+'\\n');",
  ]) {
    await assert.rejects(runSimulatorGoal(await fixture(t, source)), (error) => {
      assert.ok(!error.message.includes("SECRET_FIXTURE_TOKEN"));
      return true;
    });
  }
});

test("oversized NDJSON lines fail with a bounded error", async (t) => {
  const options = await fixture(t, "process.stdout.write('x'.repeat(1024*1024+1)); setInterval(()=>{},1000);");
  await assert.rejects(runSimulatorGoal(options), /exceeded 1 MiB/);
});

test("timeout terminates the child even when it ignores SIGTERM", async (t) => {
  const options = await fixture(t, "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000);");
  await assert.rejects(runSimulatorGoal({ ...options, timeoutMs: 200, killGraceMs: 50 }), /exceeded 200 ms; effects may be incomplete/);
});

test("spawn failure returns a sanitized process error", async (t) => {
  const options = await fixture(t);
  await assert.rejects(runSimulatorGoal({ ...options, python: path.join(options.root, "absent") }), /Unable to start simulator runner \(ENOENT\)/);
});

test('baseline options are forwarded without inventing a confidence value', async (t) => {
  const options = await fixture(t);
  const result = await runSimulatorGoal({...options, engine:'baseline', baselineModel:'openai/gpt-5.4-nano', minProbability:0, budgetUsd:0.1});
  for (const argument of ['--engine=baseline','--baseline-model=openai/gpt-5.4-nano','--min-probability=0','--budget-usd=0.1']) assert.ok(result.args.includes(argument));
  for (const extra of [{engine:'unknown'},{minProbability:NaN},{minProbability:-1},{budgetUsd:0},{baselineModel:''}]) await assert.rejects(runSimulatorGoal({...options,...extra}));
});
