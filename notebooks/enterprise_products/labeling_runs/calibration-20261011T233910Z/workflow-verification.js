// Continue completed first-stage judgments; no labeler or blind launches.
const root = args.runDirectory;
const model = "openai-codex/gpt-6-luna:high";
const stageResults = {};
const artifactPaths = {};
for (let i = 0; i < 2; i++) {
  const batch = String(i + 1).padStart(2, "0");
  for (const stage of ["labeler", "blind"]) artifactPaths[stage + "-" + batch] = root + "/handoffs/" + stage + "-" + batch + ".audited.json";
}
const nullableString = { type: ["string", "null"] };
const sourceSchema = {
  type: "object", additionalProperties: false,
  required: ["url", "source_type", "excerpt", "applicability", "supports", "captured_at", "capture_reference", "publication_or_version"],
  properties: {
    url: { type: "string", minLength: 1 },
    source_type: { type: "string", enum: ["official", "archived_official", "secondary", "source_dataset"] },
    excerpt: { type: "string", minLength: 1, maxLength: 1800 },
    applicability: { type: "string", minLength: 1 },
    supports: { type: "array", minItems: 1, uniqueItems: true, items: { type: "string", enum: ["binary", "subtype", "identity"] } },
    captured_at: nullableString, capture_reference: nullableString, publication_or_version: nullableString
  }
};
function schema(stage, ids) {
  const properties = {
    product_group_id: { type: "string", enum: ids },
    ai_status: { type: "string", enum: ["ai", "non_ai"] },
    ai_type: { type: ["string", "null"], enum: ["ai_native", "ai_enabled", null] },
    evidence_strength: { type: "string", enum: ["supported", "weak"] },
    forced_decision: { type: "boolean" },
    ai_type_evidence_strength: { type: ["string", "null"], enum: ["supported", "weak", null] },
    ai_type_forced_decision: { type: ["boolean", "null"] },
    rationale: { type: "string", minLength: 1 }, ai_type_rationale: nullableString,
    version_scope: { type: "string", minLength: 1 },
    grouping_conflict: { type: "boolean" }, structural_blocker: { type: "boolean" },
    needs_adjudication: { type: "boolean" },
    issues: { type: "array", items: { type: "string" } },
    sources: { type: "array", items: sourceSchema },
    research_counts: {
      type: "object", additionalProperties: false,
      required: ["search_rounds", "full_page_reads"],
      properties: { search_rounds: { type: "integer", minimum: 0 }, full_page_reads: { type: "integer", minimum: 0 } }
    }
  };
  return {
    type: "object", additionalProperties: false,
    required: ["stage", "records"],
    properties: {
      stage: { type: "string", enum: [stage] },
      records: { type: "array", minItems: ids.length, maxItems: ids.length, items: { type: "object", additionalProperties: false, required: Object.keys(properties), properties } }
    }
  };
}

function task(stage, batch, ids) {
  const cwd = root + "/" + stage + "-batch-" + batch;
  const output = cwd + "/result.verified.json";
  const inputs = "Independent proposals: " + artifactPaths["labeler-" + batch] + " and " + artifactPaths["blind-" + batch];
  let instruction;
  if (stage === "evidence") instruction = "Audit both independent judgments against actual retained source pages and cited originals. Adopt provisional judgments; needs_adjudication=true for every disagreement, weak/forced judgment, failed evidence check or uncertain applicability. Preserve material limitations. " + inputs;
  if (stage === "adjudicator") instruction = "Make reasoned binary/subtype decisions only for assigned groups using bounded additional evidence if needed. Do not vote or default non-AI. Preserve uncertainty as weak/forced, separately for binary/subtype. " + inputs + "; evidence audit: " + artifactPaths["evidence-" + batch];
  if (stage === "finalcheck") instruction = "Perform the ONE final evidence check of adjudicated decisions. Never certify based on prior agreement. Unsupported binary/subtype calls stay weak/forced. needs_adjudication=false; structural blockers stay visible. " + inputs + "; evidence audit: " + artifactPaths["evidence-" + batch] + "; adjudication: " + artifactPaths["adjudicator-" + batch];
  return {
    key: stage + "-" + batch,
    label: (stage === "evidence" ? "Verify cited evidence for" : stage === "adjudicator" ? "Adjudicate flagged" : "Check final evidence for") + " batch " + batch,
    agent: "researcher", model, context: "fresh", cwd, worktree: false,
    task: "Perform ONLY the " + stage + " stage for assigned IDs: " + ids.join(", ") + ". Read completely " + root + "/STAGE_CONTRACT.md, " + root + "/VERIFICATION_CONTRACT.md and " + root + "/inputs/LABELING_WORKFLOW.md; read the group packet " + root + "/inputs/batch-" + batch + ".json and frozen SOURCE.md/README.md. " + instruction + "\nReuse retained pages indexed at " + root + "/handoffs/retained_recovery_pages.json and initial lanes' retained_pages. No repeated initial research. Write group checkpoints ONLY under " + cwd + "/checkpoints/. DO NOT WRITE aggregate " + output + "; submit the complete object with native structured_output, letting runtime persist it. No subagents, source/config edits, commits, pushes, training, partitions or model/execution fallback. Stop and report infrastructure failures. On retry reuse completed checkpoints and truthful cumulative counts.",
    output, outputMode: "inline", outputSchema: schema(stage, ids),
    gate: "python3 -B " + JSON.stringify(root + "/check_stage.py") + " " + JSON.stringify(output) + " " + stage + " " + ids.join(" ")
  };
}
function valid(result, stage, ids) {
  const data = result.structuredOutput;
  if (!result.ok || !data || data.stage !== stage || !Array.isArray(data.records)) return false;
  const actual = data.records.map(row => row.product_group_id);
  return actual.length === ids.length && new Set(actual).size === ids.length && ids.every(id => actual.includes(id));
}
for (const stage of ["evidence", "adjudicator", "finalcheck"]) {
  const tasks = [];
  for (let i = 0; i < 2; i++) {
    const batch = String(i + 1).padStart(2, "0");
    let ids = args.groupsByBatch[i];
    if (stage !== "evidence") ids = stageResults["evidence-" + batch].structuredOutput.records.filter(row => row.needs_adjudication && !row.structural_blocker && !row.grouping_conflict).map(row => row.product_group_id);
    if (ids.length) tasks.push(task(stage, batch, ids));
  }
  if (tasks.length > 4) throw new Error("Shared four-worker cap exceeded");
  if (!tasks.length) { await state.set("verification-" + stage, {skipped:true}); continue; }
  const results = await runs.all(tasks);
  for (let i = 0; i < tasks.length; i++) {
    const original = tasks[i];
    const ids = original.outputSchema.properties.records.items.properties.product_group_id.enum;
    let result = results[i], path = original.output;
    if (!valid(result, stage, ids)) {
      const diagnostic = JSON.stringify({error:result.error,state:result.state,runId:result.runId});
      await state.set("verification-failure-" + original.key, {diagnostic, checkpoints:original.cwd + "/checkpoints"});
      if (/unknown model|model not found|model.*unavailable|authentication|unauthorized|quota|permission denied|unknown agent|configuration/i.test(diagnostic)) throw new Error("Infrastructure/configuration blocker; no substitution: " + diagnostic);
      console.log("One same-protocol checkpoint/output retry: " + original.key + " " + diagnostic);
      path = original.output.replace(/\.json$/, ".retry.json");
      const retry = {...original, key:original.key + "-retry", label:"Recover " + original.label,
        output:path, gate:original.gate.replace(JSON.stringify(original.output),JSON.stringify(path)),
        task:original.task + "\nONE authorized retry: " + diagnostic + ". Reuse complete checkpoints, finish only unfinished work, preserve counters; submit through structured_output, DO NOT WRITE aggregate " + path + "."};
      result = await runs.run(retry.key,retry);
      if (!valid(result,stage,ids)) throw new Error("Persistent stage failure; preserve checkpoints and pause: " + JSON.stringify({error:result.error,runId:result.runId}));
    }
    stageResults[original.key] = result;
    artifactPaths[original.key] = path;
    await state.set("verification-" + original.key, {runId:result.runId,outputPath:path,groupIds:ids});
  }
}
const finalRecords = [];
for (let i = 0; i < 2; i++) {
  const batch = String(i + 1).padStart(2,"0");
  const evidence = stageResults["evidence-" + batch].structuredOutput.records;
  const checked = stageResults["finalcheck-" + batch]?.structuredOutput.records || [];
  for (const row of evidence) finalRecords.push(checked.find(candidate => candidate.product_group_id === row.product_group_id) || row);
}
const result = {
  scope:"20-group calibration only; stop before remainder",
  artifactPaths,
  completedGroups:finalRecords.filter(row => !row.structural_blocker && !row.grouping_conflict).length,
  forcedBinaryGroups:finalRecords.filter(row => row.forced_decision).length,
  forcedSubtypeGroups:finalRecords.filter(row => row.ai_type_forced_decision).length,
  blockedGroupIds:finalRecords.filter(row => row.structural_blocker || row.grouping_conflict).map(row => row.product_group_id),
  childRunIds:Object.fromEntries(Object.entries(stageResults).map(([key,value]) => [key,value.runId]))
};
await state.set("calibration-verification-result",result);
await state.set("nextReadyAction","Parent validates saved verification artifacts and reports calibration; do not launch remainder without user approval.");
return result;
