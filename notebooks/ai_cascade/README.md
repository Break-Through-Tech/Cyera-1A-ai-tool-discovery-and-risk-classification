# AI Determination cascade for website text

A three-stage AI Determination for fetched homepages under [ADR 0001](../../docs/adr/0001-ai-tool-requires-own-ai-functionality.md).

**Status (2026-10-23):** the selected classification step is the gate plus the Jev judge with evidence ([ADR 0002](../../docs/adr/0002-binary-ai-detection-uses-gated-jev-judge.md)). Start at [Production reference](#production-reference). The sections below record the experiments that led there, in order. The first one describes the original Luna cascade (v1).

1. **Keyword gate:** a page with no keyword from the v4 regex is non-AI. If it also has under 200 characters of text, it's unresolved.
2. **Snippets:** for pages with a keyword, `mention_snippets` collects the title, the meta description, two lead sentences, and up to 10 keyword-bearing sentences, each tagged with its page location.
3. **Context judge:** the snippets decide `ai`, `non_ai`, or `unresolved`. The judge is either `gpt-5.6-luna` at low effort through `codex exec` (read-only, empty working directory, JSON-schema output, 25 pages per call, cached by a hash of the full input), or a distilled student model.

## Run it

```sh
python3 notebooks/ai_cascade/evaluate_dev.py                                     # keyword vs Luna cascade on dev
/tmp/cyera-enrichment-venv/bin/python notebooks/ai_cascade/fetch_pool.py          # refetches the train/test pool
python3 -m venv /tmp/cyera-embed-venv
/tmp/cyera-embed-venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch
/tmp/cyera-embed-venv/bin/pip install sentence-transformers scikit-learn
/tmp/cyera-embed-venv/bin/python notebooks/ai_cascade/train_student.py            # teacher labels + students
```

Judge calls need a signed-in Codex CLI. `judge_cache.json` holds every judgment, so reruns only call the model for new evidence or changed instructions.

## Data

- **Dev:** the 250 pages from [website_feasibility](../website_feasibility/README.md). Gold determinations come from two independent Claude-family label passes mapped through the ADR 0001 table. The prompt was revised once against this set, so dev results are optimistic.
- **Pool:** `fetch_pool.py` uses seed `20261023` to sample 450 more AIToolBuzz domains and the remaining 350 CompanyEnrich domains, excluding dev hosts. A URL hash splits them two-thirds train, one-third test. 409 train pages and 190 test pages were usable. **The test pages are untouched**: they're neither labeled nor scored.
- **Teacher labels:** Luna judged the 282 keyword-bearing train pages, giving 224 `ai`, 26 `non_ai`, and 32 `unresolved`. These are model labels, not reviewed ground truth.

## Dev results (2026-10-22)

Macro-F1 is over `ai`/`non_ai` on the 215 dev pages whose gold determination is resolved. Abstaining on those pages counts as an error.

| Stage 3 | Macro-F1 | Accuracy | False alarms | Missed AI | Abstained | Gold-unresolved left unresolved |
|---|---|---|---|---|---|---|
| None (keyword rule) | 0.879 | 0.888 | 19 | 5 | 0 | 0 / 35 |
| **Luna judge** | **0.945** | **0.916** | **1** | 13 | 13 | 20 / 35 |
| TF-IDF + LR (context) | 0.859 | 0.833 | 10 | 19 | 16 | 16 / 35 |
| MiniLM embeddings + LR (context) | 0.805 | 0.726 | 5 | 46 | 40 | 20 / 35 |
| BGE-small embeddings + LR (context) | 0.801 | 0.730 | 4 | 47 | 36 | 18 / 35 |
| MiniLM embeddings + LR (mentions only) | 0.813 | 0.753 | 3 | 45 | 30 | 23 / 35 |

Student settings (C in {0.1, 1, 10}, class weighting) were chosen by 5-fold cross-validation against the teacher labels on train only. Balanced weighting won every time.

- **The Luna cascade beats the keyword rule.** It removes 18 of 19 false alarms and leaves most vague claims unresolved. Most of its remaining misses are abstentions on large SaaS sites (Miro, Shopify, Brevo, Workday), where the concrete AI feature sits deeper in the page than the snippets reach.
- **The students don't beat the keyword rule.** They agree with Luna on only 59–70% of dev keyword pages. With 26 `non_ai` and 32 `unresolved` training pages, they can't learn the distinction Luna makes, and balanced weighting turns that into heavy abstention on real AI pages. Choosing between embeddings and TF-IDF doesn't fix a data shortage.

## Held-out test results (2026-10-23)

`evaluate_test.py` scores the frozen cascade once on the 190 usable test pages. `test_labeling/FREEZE.json` recorded the `cascade.py` hash before the test pages were labeled, and the script refuses to run if the code has changed. Gold labels come from two fresh blind Claude-family passes under the same rubric. The passes agreed exactly on 182 pages and on the same determination on 188; the two that cross determinations count as unresolved. Gold: 113 `ai`, 53 `non_ai`, 24 `unresolved`.

| Method | Macro-F1 (166 resolved) | Accuracy | False alarms | Missed AI | Abstained | Gold-unresolved left unresolved |
|---|---|---|---|---|---|---|
| Keyword rule | 0.894 | 0.910 | 9 | 6 | 0 | 0 / 24 |
| **Luna cascade** | **0.923** | **0.916** | **1** | 13 | 4 | **16 / 24** |

- **By source:** on CompanyEnrich pages the cascade scores 0.969 against 0.925, with 0 false alarms. On AIToolBuzz pages its accuracy is lower (0.876 against 0.897), because the cascade misses more AI tools.
- **Unsupported AI calls,** counting gold-unresolved pages called AI: keyword rule 22 (9 + 13), cascade 5 (1 + 4).
- **The cascade's 13 misses:** 6 are keyword-gate misses shared with the keyword rule (StyleDrop, Muzaic, Frigo, and others describe AI tasks without the listed terms). 4 are abstentions. 3 are a new error mode where the judge reads "AI as the product's subject" too broadly: Meltwater, AppsFlyer, and Faros both use AI and serve AI customers, and the judge called them non-AI.
- `test_results.json` lists every cascade error, plus 70 disputed or low-confidence pages for human spot-checking.

The dev advantage shrank as expected (0.945 → 0.923, while the keyword rule rose 0.879 → 0.894), but the cascade still wins on macro-F1, false alarms, and abstention. Treat this as a single held-out result: future changes to the gate or prompt need a new test sample.

## Cascade v2 (2026-10-23)

`cascade_v2.py` differs from the frozen v1 in three ways:

- **Capability gate.** A `CAPABILITY` pattern also sends pages to the judge when they describe AI work without AI terms: "text-to-image", "plain English", "ask questions", named models, transcription and summarization, and similar.
- **Judge prompt.** It now says the word "AI" is not required, gives examples of what only a learned model can do (and of conventional automation, which doesn't count), and says a product that serves or tracks AI is still AI if its own AI also performs a task.
- **Snippet cap.** `MAX_SNIPPETS` rises from 10 to 25. On development pages, about half the judged errors had evidence past the old cap.

**Development.** v2 was developed on all 440 pages scored before it existed: the dev sample plus the spent v1 test sample. It scored 0.961 there, against 0.936 for v1 and 0.886 for the keyword rule. A longer subject-rule paragraph made results worse, and medium judge effort didn't help. Neither change was kept.

**Second held-out test.** `test2_labeling/FREEZE.json` recorded the hash of `cascade_v2.py` before any label in that folder was read. The sample is the pool's 409 train-split pages: the students trained on them, but the cascade was never tuned on them. Two blind passes agreed exactly on 390 pages and on the same determination on 399. 279 evidence quotes are identical across passes, a reminder that both passes come from the same model family. Gold: 226 `ai`, 115 `non_ai`, 68 `unresolved`. Run `python evaluate_test.py test2` to reproduce.

| Method | Macro-F1 (341 resolved) | Accuracy | False alarms | Missed AI | Abstained | Gold-unresolved left unresolved | Unsupported AI calls |
|---|---|---|---|---|---|---|---|
| Keyword rule | 0.889 | 0.906 | 27 | 5 | 0 | 0 / 68 | 61 |
| Cascade v1 | 0.923 | 0.903 | 7 | 19 | 19 | 39 / 68 | 17 |
| **Cascade v2** | **0.929** | **0.909** | **6** | 17 | 19 | **42 / 68** | **14** |

- **Cascade vs keyword rule:** the advantage is confirmed on a sample twice the size of the first test, and it is largest on CompanyEnrich pages (0.884 against 0.798).
- **v2 vs v1:** most of v2's development gain did not carry over. On the fresh sample it is +0.006 over v1.
  - The capability gate behaved cleanly: it sent 8 pages to the judge, recovered 2 AI tools, and correctly rejected the other 6.
  - The other 15 pages where v1 and v2 differ split roughly evenly between fixes and regressions, so the dev gain was mostly a reshuffle of borderline pages.
- **Remaining errors are mostly rubric boundaries, not missing evidence:**
  - abstentions on short AI claims that the labelers accepted ("built-in AI Assistant", "AI-powered client relationship platform");
  - support chatbots on vendor sites that Luna counts as a product feature (Stripe, SendGrid);
  - parked or sign-in pages that the keyword gate calls `non_ai` instead of unresolved.

  Further prompt tuning is unlikely to pay off until those boundaries are decided. With gold labels from a single model family, the measurable ceiling is also limited.

## Jev judge (2026-10-23)

`jev_cascade.py` keeps the v2 gate but replaces the Luna call with TypeSafe Jev (`jev-latest`, which resolved to `jev-1.14.0`) through `jev_judge.py`. It sends one request per gated page, with the title, meta description, headings, and up to 12,000 characters of page text. The request asks one `choice` question (ai, non_ai, unresolved, with ADR 0001 descriptions) and four audit `noul` questions: whether the product's own AI performs a task, whether AI appears only as subject, whether the AI claim is vague, and whether the page describes a product. Answers are cached in `jev_cache.json` by request hash. The API key comes from `TYPESAFE_API_KEY` or the gitignored `.env`.

**Development** (`explore_jev_dev.py`, 440 pages):

- Full page text beats v2 snippets (0.943 against 0.938 with argmax).
- Escalating from snippets to full text only when Jev is unsure performs about the same as always sending full text.
- Using the audit questions as decision rules fails: the own-AI-task question is far too conservative.
- `P(ai)` is under-confident between 0.1 and 0.5; about 65% of those pages are gold AI.
- A cutoff of `P(ai) ≥ 0.4` matches Luna v2's development error profile (0.950, 3 false alarms, 15 missed AI). Lower cutoffs raise macro-F1 slightly but double unsupported AI calls.

**Test2** (`python evaluate_test.py test2_jev`): the configuration was frozen in `test2_labeling/FREEZE_jev.json` before scoring. This is the second use of the test2 labels.

| Method | Macro-F1 | Accuracy | False alarms | Missed AI | Abstained | Unsupported AI calls |
|---|---|---|---|---|---|---|
| Keyword rule | 0.889 | 0.906 | 27 | 5 | 0 | 61 |
| Luna cascade v2 | 0.929 | 0.909 | 6 | 17 | 19 | 14 |
| **Jev cascade** | **0.931** | **0.918** | 7 | **14** | **15** | 19 |

Jev matches Luna in accuracy, with fewer misses and abstentions but slightly more AI calls on gold-unresolved pages. It answers in about 0.15 s per page, with no CLI dependency. All development and test runs together used 1.4M input tokens, about $0.06. It returns no free-text reason: the four audit probabilities and the evidence are the explanation.

### Evidence trail and review flag

The four audit questions above contradict the final call too often to explain it. On test2, 51 of 231 AI calls have own-AI-task below 0.5. `jev_audit.classify` replaces them as the explanation:

- **Evidence request.** A second Jev request asks one `noul` per candidate sentence: "this sentence shows the product's own AI performing a task". Candidates are the title, meta description, gate-matching sentences, then the other sentences, up to 60. It is kept separate because extra questions in the decision request shift `P(ai)` by up to 0.05, and the frozen decision stays byte-identical.
- **Output.** Every judged page gets its top 3 sentences with probabilities.
- **Review flag.** AI calls whose best sentence scores below `REVIEW_EVIDENCE_CUTOFF` = 0.6 are marked `needs_review`.

**Development** (`explore_jev_evidence.py`, 440 pages):

- The labelers' quote was among Jev's candidates on 225 of 228 correct AI calls. It was Jev's top sentence on 100 and in its top 3 on 154.
- In a sample of 10 top-sentence mismatches, 9 were valid, often more specific, evidence. One was a line from a demo chat transcript.
- The 0.6 cutoff flagged 24 of 243 AI calls, 6 of them wrong.

**Test2 confirmation** (cutoff fixed on development pages): 19 of 231 AI calls flagged (8.2%). 6 of the flagged are wrong (31.6%, against an 8.2% base rate), so the flag catches 6 of the 19 wrong AI calls. Flagging non-AI calls with strong evidence as possible misses was not worth it on development pages (4 pages, 1 real miss).

Evidence probabilities are scored independently by the same model, not a reasoning chain. They show which sentence supports a call, not why the model made it.

## Production reference

The selected classification step is the Jev cascade ([ADR 0002](../../docs/adr/0002-binary-ai-detection-uses-gated-jev-judge.md)). The entry point is `jev_audit.classify(captures)`. Each capture is a dict as produced by `notebooks/website_feasibility/fetch_sample.fetch` (`sample_id`, `title`, `metadata`, `headings`, `main_text`). Every result has `determination` (`ai` / `non_ai` / `unresolved`), `stage`, and `needs_review`. Judged pages also carry `model`, the decision and audit probabilities, and `evidence` (the top 3 sentences with their probabilities).

```text
classify(captures)                       jev_audit.py
  determine(captures)                    jev_cascade.py
    gate(text)                           cascade_v2.py   -> non_ai / unresolved without a model call
    ask(gated, "full")                   jev_judge.py    -> POST /v1/systemone, choice + audit nouls
    decide(p)                            jev_cascade.py  -> ai if P(ai) >= 0.4
  ask_evidence(judged)                   jev_judge.py    -> one noul per sentence, separate request
  needs_review = ai and best evidence < 0.6
```

| File | Port to the backend? |
|---|---|
| `jev_audit.py`, `jev_cascade.py`, `jev_judge.py` | Yes: entry point, decision rule, Jev client |
| `cascade_v2.py` | Only `KEYWORD`, `CAPABILITY`, `gate`, `fields`, `all_text`, `sentences`, `mention_snippets`, `MIN_TEXT_CHARS`, `SNIPPET_CHARS`; the rest is the Luna judge |
| `../website_feasibility/fetch_sample.py` | Yes: `fetch`, `homepage`, `host_key` (curl_cffi, robots.txt, 2 MB limit, Trafilatura) |
| `cascade.py`, `evaluate_*.py`, `explore_*.py`, `make_test2_packets.py`, `train_student.py`, `fetch_pool.py` | No: experiment history and re-validation harness |

Porting checklist:

- Pin `jev_judge.MODEL = "jev-1.14.0"`; `jev-latest` is an alias that moves with TypeSafe releases.
- Replace `jev_cache.json` with a database table keyed by the same request hash. Store the evidence sentences as citation-ready excerpts, with the capture's URL and time, per the plan's provenance rules.
- Supply `TYPESAFE_API_KEY` from the secrets manager; `jev_judge.api_key()` reads the environment before `.env`.
- Record the configuration version (gate patterns, question text, model ID, `AI_CUTOFF`, `REVIEW_EVIDENCE_CUTOFF`) with each Analysis Run.
- Any change to those requires re-validation on newly labeled pages. Both labeled held-out samples here (`test_labeling/` and `test2_labeling/`) have already been used.
- Cost on this project: about $0.00004 per page per request, two requests per judged page. All experiments together used 2.3M input tokens, about $0.10.

Known open edges, all rubric boundaries rather than evidence gaps:

- vendor support chatbots counted as product AI;
- short "built-in AI Assistant" claims left unresolved;
- parked and sign-in pages that pass the length check get `non_ai` instead of `unresolved`.

## What would make a student viable

The minority classes need several hundred examples each, which means many more keyword-bearing pages from ordinary software sites. AIToolBuzz pages are about 90% `ai`, and the CompanyEnrich pool is exhausted. Until such a source exists, the Luna judge is the practical stage 3.
