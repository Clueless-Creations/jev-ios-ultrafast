import { spawn } from "node:child_process";
import path from "node:path";
import { pathToFileURL } from "node:url";

/** Invoke the standalone prototype. This is not a registered Brigade operation. */
export async function runSimulatorGoal({
  root = process.env.JEV_IOS_ROOT,
  python = process.env.JEV_IOS_PYTHON || "python3",
  udid,
  bundleId,
  goal,
  expectLabels,
  scenarioPath,
  engine = "jev",
  baselineModel,
  minProbability,
  budgetUsd,
  allowLabels = [],
  vercelProject,
  maxSteps,
  tracePath,
  reportPath,
  recordVideoPath,
  screenshotPath,
  timeoutMs = 120_000,
  killGraceMs = 20_000,
}) {
  const validString = (value, limit = 4096) => typeof value === "string" && value.trim() && !value.includes("\0") && value.length <= limit;
  for (const [name, value] of Object.entries({ root, python, udid, bundleId })) {
    if (!validString(value)) throw new Error(`${name} is required and must be a nonempty string`);
  }
  const validLabels = (labels, required) => Array.isArray(labels) && labels.length <= 30 && (!required || labels.length > 0) && labels.every((label) => validString(label, 300));
  if (scenarioPath !== undefined) {
    if (!validString(scenarioPath)) throw new Error("scenarioPath must be a nonempty path");
    if (goal !== undefined || expectLabels !== undefined) throw new Error("scenarioPath cannot be combined with goal or expectLabels");
  } else {
    if (!validString(goal, 4000)) throw new Error("goal is required without scenarioPath and must be at most 4000 characters");
    if (!validLabels(expectLabels, true)) throw new Error("expectLabels must contain 1 to 30 exact visible UI labels, at most 300 characters each");
  }
  if (!validLabels(allowLabels, false)) throw new Error("allowLabels must contain at most 30 exact labels, at most 300 characters each");
  if (!["jev", "baseline"].includes(engine)) throw new Error("engine must be jev or baseline");
  if (baselineModel !== undefined && !validString(baselineModel, 200)) throw new Error("baselineModel must be nonempty");
  if (minProbability !== undefined && (!Number.isFinite(minProbability) || minProbability < 0 || minProbability > 1)) throw new Error("minProbability must be between 0 and 1");
  if (budgetUsd !== undefined && (!Number.isFinite(budgetUsd) || budgetUsd <= 0)) throw new Error("budgetUsd must be positive");
  if (vercelProject !== undefined && !validString(vercelProject, 300)) throw new Error("vercelProject must be nonempty");
  if (maxSteps !== undefined && (!Number.isInteger(maxSteps) || maxSteps < 1 || maxSteps > 30)) throw new Error("maxSteps must be between 1 and 30");
  if (!Number.isInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > 600_000) throw new Error("timeoutMs must be an integer between 1 and 600000");
  if (!Number.isInteger(killGraceMs) || killGraceMs < 1 || killGraceMs > 20_000) throw new Error("killGraceMs must be an integer between 1 and 20000");
  const artifactOptions = { tracePath, reportPath, recordVideoPath, screenshotPath };
  for (const [name, value] of Object.entries(artifactOptions)) {
    if (value !== undefined && !validString(value)) throw new Error(`${name} must be a nonempty path`);
  }
  const artifactPaths = Object.values(artifactOptions).filter((value) => value !== undefined).map((value) => path.resolve(root, value));
  if (new Set(artifactPaths).size !== artifactPaths.length) throw new Error("Artifact paths must be distinct");
  if (recordVideoPath !== undefined && path.extname(recordVideoPath).toLowerCase() !== ".mp4") throw new Error("recordVideoPath must end in .mp4");

  const args = ["-m", "jev_ios", "run"];
  // The equals form preserves values beginning with a dash as data to argparse.
  const option = (name, value) => args.push(`${name}=${value}`);
  option("--udid", udid);
  option("--bundle-id", bundleId);
  option("--engine", engine);
  if (baselineModel !== undefined) option("--baseline-model", baselineModel);
  if (minProbability !== undefined) option("--min-probability", minProbability);
  if (budgetUsd !== undefined) option("--budget-usd", budgetUsd);
  if (scenarioPath !== undefined) option("--scenario", scenarioPath);
  else {
    option("--goal", goal);
    for (const label of expectLabels) option("--expect-label", label);
  }
  for (const label of allowLabels) option("--allow-label", label);
  if (vercelProject !== undefined) option("--vercel-project", vercelProject);
  if (maxSteps !== undefined) option("--max-steps", maxSteps);
  for (const [flag, value] of [["--trace", tracePath], ["--report", reportPath], ["--record-video", recordVideoPath], ["--screenshot", screenshotPath]]) {
    if (value !== undefined) option(flag, value);
  }

  return new Promise((resolve, reject) => {
    const child = spawn(python, args, {
      cwd: path.resolve(root),
      env: process.env,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let pending = "";
    let result;
    let failure;
    let forceKill;
    let closed = false;
    const stop = (error) => {
      if (failure) return;
      failure = error;
      if (closed) return;
      child.kill("SIGTERM");
      forceKill = setTimeout(() => child.kill("SIGKILL"), killGraceMs);
      forceKill.unref();
    };
    const timer = setTimeout(() => stop(new Error(`Simulator run exceeded ${timeoutMs} ms; effects may be incomplete`)), timeoutMs);
    const consume = (line) => {
      if (!line.trim()) return;
      try {
        const event = JSON.parse(line);
        if (!event || typeof event !== "object" || Array.isArray(event) || typeof event.type !== "string") {
          return stop(new Error("Simulator runner emitted an invalid event"));
        }
        if (event.type === "error") return stop(new Error("Simulator runner reported an error; inspect its local trace"));
        if (event.type === "result") {
          if (result) return stop(new Error("Simulator runner emitted multiple result events"));
          if (event.schema !== "jev-ios/run/v1" || typeof event.status !== "string") return stop(new Error("Simulator runner emitted an invalid result"));
          result = event;
        }
      } catch {
        stop(new Error("Simulator runner emitted invalid NDJSON"));
      }
    };
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      pending += chunk;
      if (pending.length > 1024 * 1024) return stop(new Error("Simulator runner output line exceeded 1 MiB"));
      let end;
      while ((end = pending.indexOf("\n")) >= 0) {
        consume(pending.slice(0, end));
        pending = pending.slice(end + 1);
      }
    });
    // Drain stderr without echoing arbitrary subprocess output into host errors.
    child.stderr.resume();
    child.on("error", (error) => {
      failure = failure || new Error(`Unable to start simulator runner (${error.code || "process error"})`);
    });
    child.on("close", (code, signal) => {
      closed = true;
      clearTimeout(timer);
      clearTimeout(forceKill);
      if (!failure) consume(pending);
      if (failure) return reject(failure);
      if (code !== 0) return reject(new Error(`Simulator runner exited ${code ?? signal ?? "unknown"}; effects may be incomplete`));
      if (!result) return reject(new Error("Simulator runner exited without a result event"));
      if (result.status !== "verified") return reject(new Error("Simulator run did not verify its expected labels"));
      resolve(result);
    });
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const [udid, bundleId, goal, ...expectLabels] = process.argv.slice(2);
  runSimulatorGoal({ udid, bundleId, goal, expectLabels })
    .then((result) => process.stdout.write(`${JSON.stringify(result)}\n`))
    .catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
