// One bounded calibration workflow; children launch only here.
const root = args.runDirectory;
const model = "openai-codex/gpt-6-luna:high";
const phases = ["research", "evidence", "adjudication", "finalcheck"];
const stageResults = {};
const artifactPaths = {};
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
  const lane = `${stage}-batch-${batch}`;
  let instruction = "";
  if (stage === "labeler") instruction = "Propose the binary and applicable AI-type annotations independently, with source-backed rationale. No other judgments are available or authorized inputs.";
  if (stage === "blind") instruction = "You are the BLIND VERIFIER. Independently research and label the assigned groups. Do not inspect labeler/sibling results, checkpoints, workflow state, or any other judgments. Your permitted inputs are only the frozen common contract, rubric and batch/source context.";
  if (stage === "evidence") instruction = `You are the EVIDENCE VERIFIER. Audit both independent proposals: ${artifactPaths[`labeler-${batch}`]} and ${artifactPaths[`blind-${batch}`]}. Inspect the underlying cited material and actual excerpts, not just URLs or agreement. Report a provisional adopted judgment for each group, with needs_adjudication=true whenever judgments differ, support is weak/forced, applicability is uncertain or evidence fails. Preserve material reasons and grouping conflicts. Your task is verification, not unbounded new research.`;
  if (stage === "adjudicator") instruction = `You are the CONDITIONAL ADJUDICATOR, only for these IDs: ${ids.join(", ")}. Read the independent proposals ${artifactPaths[`labeler-${batch}`]} and ${artifactPaths[`blind-${batch}`]}, and evidence audit ${artifactPaths[`evidence-${batch}`]}. Seek bounded additional evidence and make a reasoned binary/type decision. Do not vote or silently default to non-AI. Retain weak/forced flags when support remains insufficient.`;
  if (stage === "finalcheck") instruction = `You are the FINAL EVIDENCE CHECKER, only for these adjudicated IDs: ${ids.join(", ")}. Audit ${artifactPaths[`adjudicator-${batch}`]} against the original proposals/audit and actual cited sources. This is the one authorized final check, not another adjudication loop. Retain unsupported/forced binary or subtype judgments as weak and flagged, never certify them merely because the adjudicator says so. needs_adjudication=false because no additional loop is authorized. Missing provenance, grouping conflicts or malformed data remain structural blockers.`;
  return {
    key: `${stage}-${batch}`, label: `${stage === "blind" ? "Independently verify" : stage === "evidence" ? "Audit evidence for" : stage === "adjudicator" ? "Adjudicate" : stage === "finalcheck" ? "Recheck adjudicated" : "Label"} batch ${batch}`,
    agent: "researcher", model, context: "fresh", cwd: `${root}/${lane}`, worktree: false,
    task: `Perform the ${stage} stage of the approved 20-group calibration. Read ${root}/STAGE_CONTRACT.md and the complete frozen ${root}/inputs/LABELING_WORKFLOW.md, then ${root}/inputs/batch-${batch}.json and frozen source context as directed. Assigned IDs: ${ids.join(", ")}. Ignore unassigned groups in the packet.\n${instruction}\nYour sole write boundary is your cwd's checkpoints and the bound result artifact. Checkpoint each completed group separately. On retry reuse your own completed checkpoints without repeating its research or reading sibling judgments. Return a complete JSON object matching the bound schema, not a Markdown research brief. No subagents, code/source edits, commits, pushes, merges, training, or partitions. Stop and report exact infrastructure failures; no execution-mode/model fallback.`,
    output: `${root}/${lane}/result.json`, outputMode: "file-only", outputSchema: schema(stage, ids)
  };
}
function valid(result, stage, ids) {
  if (!result.ok || !result.structuredOutput) return false;
  const data = result.structuredOutput;
  if (data.stage !== stage || !Array.isArray(data.records)) return false;
  const actual = data.records.map(r => r.product_group_id);
  if (actual.length !== ids.length || new Set(actual).size !== ids.length || ids.some(id => !actual.includes(id))) return false;
  return data.records.every(r => {
    if (r.forced_decision && r.evidence_strength !== "weak") return false;
    if (r.ai_status === "non_ai") return r.ai_type === null && r.ai_type_evidence_strength === null && r.ai_type_forced_decision === null && r.ai_type_rationale === null;
    return ["ai_native", "ai_enabled"].includes(r.ai_type) && ["supported", "weak"].includes(r.ai_type_evidence_strength) && typeof r.ai_type_forced_decision === "boolean" && Boolean(r.ai_type_rationale) && (!r.ai_type_forced_decision || r.ai_type_evidence_strength === "weak");
  });
}
for (const phase of phases) {
  let tasks = [];
  for (let index = 0; index < 2; index++) {
    const batch = String(index + 1).padStart(2, "0");
    const allIds = args.groupsByBatch[index];
    if (phase === "research") {
      tasks.push(task("labeler", batch, allIds), task("blind", batch, allIds));
    } else if (phase === "evidence") {
      tasks.push(task("evidence", batch, allIds));
    } else {
      const previous = stageResults[`evidence-${batch}`].structuredOutput.records;
      const ids = previous.filter(r => r.needs_adjudication && !r.structural_blocker && !r.grouping_conflict).map(r => r.product_group_id);
      if (ids.length) tasks.push(task(phase === "adjudication" ? "adjudicator" : "finalcheck", batch, ids));
    }
  }
  if (!tasks.length) {
    await state.set(`phase-${phase}`, { skipped: true });
    continue;
  }
  if (tasks.length > 4) throw new Error("Concurrency contract violated");
  let results = await runs.all(tasks);
  for (let index = 0; index < tasks.length; index++) {
    const original = tasks[index];
    const stage = original.outputSchema.properties.stage.enum[0];
    const ids = original.outputSchema.properties.records.items.properties.product_group_id.enum;
    let result = results[index];
    let path = original.output;
    if (!valid(result, stage, ids)) {
      const diagnostic = JSON.stringify({ error: result.error, output: result.output, state: result.state });
      console.log(`Stage failure ${original.key}: ${diagnostic}`);
      await state.set(`failure-${original.key}`, { runId: result.runId || null, diagnostic, checkpointDirectory: `${original.cwd}/checkpoints` });
      if (/unknown model|model not found|model.*unavailable|authentication|unauthorized|quota|permission denied|unknown agent/i.test(diagnostic)) throw new Error(`Configuration/provider blocker in ${original.key}; no retry or substitution: ${diagnostic}`);
      path = original.output.replace(/\.json$/, ".retry.json");
      const retry = { ...original, key: `${original.key}-retry`, label: `Retry unfinished ${original.label}`, output: path, task: `${original.task}\nThis is the ONE authorized infrastructure/output correction retry. Prior failure: ${diagnostic}. Read your own completed checkpoints and finish only unfinished work; do not repeat completed groups or reset per-group research allowances.` };
      result = await runs.run(retry.key, retry);
      if (!valid(result, stage, ids)) throw new Error(`Persistent stage failure in ${original.key}; pause run. Checkpoints preserved. ${JSON.stringify({ error: result.error, output: result.output, state: result.state })}`);
    }
    stageResults[original.key] = result;
    artifactPaths[original.key] = path;
    await state.set(original.key, { runId: result.runId, outputPath: path, outputReference: result.outputReference || null, completedGroupIds: result.structuredOutput.records.map(r => r.product_group_id) });
  }
  await state.set(`phase-${phase}`, { complete: true, keys: tasks.map(t => t.key) });
}
const finalRecords = [];
for (let index = 0; index < 2; index++) {
  const batch = String(index + 1).padStart(2, "0");
  const evidence = stageResults[`evidence-${batch}`].structuredOutput.records;
  const checked = stageResults[`finalcheck-${batch}`]?.structuredOutput.records || [];
  for (const row of evidence) finalRecords.push(checked.find(r => r.product_group_id === row.product_group_id) || row);
}
const result = {
  scope: "20-group calibration only; user approval required before remainder",
  artifactPaths,
  completedGroups: finalRecords.filter(r => !r.structural_blocker && !r.grouping_conflict).length,
  forcedBinaryGroups: finalRecords.filter(r => r.forced_decision).length,
  forcedSubtypeGroups: finalRecords.filter(r => r.ai_type_forced_decision).length,
  blockedGroupIds: finalRecords.filter(r => r.structural_blocker || r.grouping_conflict).map(r => r.product_group_id),
  childRunIds: Object.fromEntries(Object.entries(stageResults).map(([key, value]) => [key, value.runId]))
};
await state.set("calibration-result", result);
return result;
