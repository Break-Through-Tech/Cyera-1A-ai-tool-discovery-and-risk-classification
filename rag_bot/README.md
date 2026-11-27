# Local Cyera retriever

Ask a question about approved Cyera project documents. Keyword and semantic
modes display excerpts directly. RAG mode retrieves the same semantic evidence
and asks Gemini to compose a cited answer.

## Run it

From the repository root, use the existing `.venv-rag` environment. Press Enter
on an empty line to exit an interactive session.

```sh
.venv-rag/bin/python -B -m rag_bot.chat --mode keyword
.venv-rag/bin/python -B -m rag_bot.chat --mode semantic
.venv-rag/bin/python -B -m rag_bot.chat --mode semantic "What is a Tool Candidate?"
.venv-rag/bin/python -B -m rag_bot.chat --mode rag
.venv-rag/bin/python -B -m rag_bot.chat --mode rag "What is a Tool Candidate?"
```

Keyword is the default and also works with a standard-library Python
installation. Semantic and RAG modes use a provisional minimum cosine score of
`0.25`. Use `--min-score` to try a different threshold from `-1` through `1`.
Use `--min-score=-1` to see the top five even when all similarities are weak.
Semantic queries above the model's input limit prompt you to shorten them.

## Configure Gemini for RAG mode

Set `GEMINI_API_KEY` and `GEMINI_MODEL` in the process environment or in the
repository-root `.env.rag` file. Process values take precedence, even when
empty. The loader leaves the process environment and the team's `.env` alone.
Keep `.env.rag` local and ignored by Git. Replace the placeholder privately.

```dotenv
GEMINI_API_KEY=<your Gemini Developer API key>
GEMINI_MODEL=gemini-3.5-flash-lite
```

[Gemini 3.5 Flash-Lite](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite)
is a supported structured-output example. Account access and live response
quality still need verification. Keyword and semantic modes work without
Gemini credentials. Additional dependencies for RAG mode are in
`requirements-rag.txt`. The existing `.venv-rag` already has them.

When retrieval finds matches, RAG mode sends the current question, up to
five exact excerpts from the approved Markdown, their citation metadata,
the system instructions, and the response schema to Google's Gemini Developer
API. The API key is used for authentication. Embeddings and the rest of the
corpus stay local. Questions are sent as entered, so keep private employee or
organization details out of the prompt. Each turn is independent and carries
no chat history. When no excerpt meets the cutoff, the app returns
`insufficient` locally without sending a request.

## How it works

1. `corpus.py` reads `CONTEXT.md`, four selected sections of `PROJECT_PLAN.md`,
   and the decision section of ADR 0001. Each passage is the text under a
   Markdown heading. Its ID comes from its path, heading, and heading
   occurrence. Its content version is a SHA-256 fingerprint of the retained
   heading and text. The source role is `project_policy`.
2. `retrieval.py` is the keyword baseline. It ranks whole passages by shared
   words, giving rarer matches more weight. Different words with the same
   meaning can be missed.
3. `chunking.py` makes exact overlapping excerpts from longer passages. It
   prefers paragraph, line, and sentence endings, and checks the token count
   for the full heading and excerpt including special tokens. Overlap is up to
   24 body tokens at word boundaries when practical. Each chunk retains its
   original passage metadata and character span. Its ID depends on the
   passage ID, content version, and character span.
4. `semantic.py` loads the model on CPU once per CLI session. It embeds the
   excerpts in batches and keeps the vectors in memory. An embedding is a list
   of numbers representing the text. Each question gets its own vector, and
   cosine similarity compares its direction with each excerpt's vector.
   Semantic matches are sorted by score, with chunk ID breaking exact ties.
5. `chat.py` shows up to five matches with scores and citations. Semantic
   results include both the chunk ID and the original passage ID. Scores rank
   results within a method. Keyword and cosine scores use different scales,
   and cosine similarity is neither a probability nor a confidence percentage.

6. `prompts.py` builds fixed system instructions and a separate JSON user
   message. It labels each excerpt with a number and keeps a local map from
   that number to the original chunk.
7. `generator.py` configures the Google Gen AI SDK. It requests structured JSON
   containing an answer, status, citation labels, and limitations. Requests
   use a 30-second SDK timeout and one attempt. Provider errors and malformed
   responses produce local diagnostics.
8. `rag.py` retrieves evidence, calls the adapter when evidence is available,
   and resolves every returned citation label against the current turn. A
   substantive answer needs at least one valid label. Partial answers must
   state what's missing. The CLI displays references from the local mapping.

A valid citation shows that the model received the cited excerpt. You still
need to read the excerpt to judge whether it supports each claim. The prompt
treats documents as untrusted, and the code checks the response shape and
citation labels. A model may still follow injected text or cite a real chunk
while giving an unsupported answer. The corpus covers project terminology
and rules, with no employee records or enterprise activity lookup. Similarity
can retrieve general risk guidance for a case-specific question, and that
guidance cannot establish an individual's risk tier.

## Model and reproducibility

- Model `sentence-transformers/all-MiniLM-L6-v2`, pinned to cached revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
- The model loads from the local Hugging Face cache. A fresh environment needs
  that snapshot in its cache to use semantic mode.
- Verified with Python 3.15.2, NumPy 2.5.5, Sentence Transformers 6.3.0,
  Transformers 5.24.1, PyTorch 2.15.0, and Hugging Face Hub 2.5.0.
  Direct dependencies are listed in `requirements-semantic.txt`.
- The model accepts 256 input tokens and returns 384 numbers per embedding.

| Original passage heading | Tokens with heading and special tokens | Chunks |
| --- | ---: | ---: |
| AI Tool Governance | 30 | 1 |
| Language | **1,253** | 7 |
| Assessment unit | 63 | 1 |
| Initial contextual-risk contract | **550** | 3 |
| Evidence and citation-ready provenance | **450** | 2 |
| Assistant retrieval and response interaction contract | **1,043** | 6 |
| An AI Tool must show its own AI functionality | 154 | 1 |

The 21 chunks cover the full seven passages. The longest embedding input is
255 tokens.

## Tests and comparison

The unit tests use fixed vectors in place of the model. The smoke test loads
the real cached model, checks coverage and token lengths, confirms the vector
shape, and verifies a known search result. Add `--compare` for both rankings
and scores on all six questions.

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_semantic
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_semantic --compare
```

| Question | Top keyword result | Top semantic result | What the results show |
| --- | --- | --- | --- |
| What is a Tool Candidate? | CONTEXT, Language (3.520) | CONTEXT, Language (0.510) | Both found the definition. Semantic search returned the excerpt containing it. |
| What is the difference between an AI Tool and an AI Mention? | ADR 0001, AI functionality (4.584) | CONTEXT, Language (0.682) | Both returned the distinction. The keyword result tied with CONTEXT. |
| How do we identify potentially unknown software applications? | CONTEXT, Language (3.451) | CONTEXT, Language (0.452) | Both found relevant terminology. The semantic excerpt focuses on grouping identity clues and resolving candidates. The corpus gives only a partial procedural answer. |
| Does visiting an application prove confidential information was submitted? | PROJECT_PLAN, Assistant retrieval and response interaction contract (4.367) | Same section (0.332) | Both top hits were indirect. The contextual-risk contract, ranked second in both modes (2.386 and 0.285), explicitly distinguishes observed activity from proof of submission. |
| How is contextual risk evaluated? | CONTEXT, AI Tool Governance (2.604) | PROJECT_PLAN, Assessment unit (0.628) | The semantic top hit identifies what is assessed. Both modes rank the actual risk rubric lower, and the semantic hits split the rule details across excerpts. |
| How do I bake a chocolate cake? | No results | No results at 0.25 | The highest unfiltered cosine score was 0.048, which the provisional cutoff removed. |

This small comparison measures two different search setups: whole passages for
keyword search and chunks for semantic search. It shows examples of more focused
excerpts and weak top hits. It cannot establish a general quality advantage
or validate the cutoff. Several chunks from the same passage can occupy the top
five. The source allowlist limits what either mode can retrieve.

Other queries to try:

- “How do contextual risk tiers use admin controls?” should surface the initial
  contextual-risk contract in `PROJECT_PLAN.md`.
- “Does an AI-powered platform tagline or a course headline establish AI
  functionality?” should surface the decision in ADR 0001.

## Optional live Gemini smoke test

The ordinary test command above includes `test_rag.py`. It uses mocked
answers and an SDK mock HTTP transport. It needs no credentials and makes
no Gemini requests. `smoke_semantic.py` uses only the cached embedding model.

The separate live smoke test sends questions and retrieved project evidence
to Gemini and may incur API usage. Run it only after authorizing that
transmission and configuring your key and model.

```sh
.venv-rag/bin/python -B -m rag_bot.smoke_gemini --live
```

`smoke_gemini.py` covers the Tool Candidate definition, AI Tool versus
AI Mention, evidence of confidential submission, contextual risk, a specific
employee's ChatGPT risk tier, and baking a chocolate cake. Inspect the citations
on the four project questions. The last two should abstain or clearly state
their limits, with no employee risk tier or recipe. The script checks answer
statuses and citation presence. Claim support still requires manual review.

## Local Streamlit interface

Use the existing `.venv-rag` environment. The UI was tested with Streamlit
1.67.0. If recreating the environment, install the pinned UI and RAG
dependencies. Semantic retrieval also requires the cached embedding model
revision documented above.

```sh
.venv-rag/bin/python -m pip install -r rag_bot/requirements-ui.txt
.venv-rag/bin/python -B -m streamlit run rag_bot/app.py --server.address 127.0.0.1
```

Open `http://127.0.0.1:8501` locally. The launch command binds to loopback.

| Mode | What it shows |
| --- | --- |
| **Keyword Search** | Ranked original passages with weighted keyword scores. |
| **Semantic Search** (default) | Ranked excerpts with cosine similarity scores. Adjust the provisional cutoff in the sidebar. |
| **RAG — Gemini** | A generated answer, status, validated citation references, and limitations. Requires Gemini configuration and a checked opt-in before submitting. |
| **Demo — Mock Generation** | A labeled simulation using the real local semantic retriever, prompt builder, and citation validator. It deterministically cites the first matching excerpt and reports a simulated partial status. It performs no reasoning or API requests. |

A prior live Gemini request returned HTTP 402 `RESOURCE_EXHAUSTED` because
prepaid credits were depleted. Connectivity remains unverified. The app
reports configuration separately from connectivity and displays billing,
quota, and other provider failures without switching generators. Use the
default Semantic Search or Demo while the billing issue is pending.

The app stores turns in the current Streamlit session. Each turn keeps its
original mode, evidence, and cutoff. Questions are independent, so a
follow-up must include the context it needs. Clear conversation removes the
displayed turns. The cached CPU model and index are shared across reruns.
The index cache key includes the corpus, model revision, and chunking code.
Questions, answers, and credentials stay out of those caches.

The source panel distinguishes all retrieved evidence from the subset cited
by an answer. The diagnostics panel gives scores as ranking values. Demo
citation selection only exercises the workflow, and model-generated answers
still require manual review for claim support. The app uses the existing
project Markdown allowlist and cannot look up employee activity, assign
a case-specific risk tier, or retrieve from an enterprise database.

The UI files are `app.py` for the interface and session state, `test_app.py`
for offline Streamlit interaction tests, and `requirements-ui.txt` for
installation. The terminal application still uses `chat.py`.

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
```

For a manual local check, ask the suggested Tool Candidate question, expand
a source, and enable diagnostics. Switch to Keyword Search and ask again.
Check that the earlier turn keeps its Semantic Search label. Switch to Demo,
verify the simulated response and its citation, then clear the conversation.
In RAG — Gemini, verify that submitting is disabled before opt-in. Leave
opt-in unchecked while live testing is on hold.

## Versioned corpus profiles

The CLI accepts `--profile` and Streamlit has a **Corpus profile** selector.
The corpus profile determines the evidence pool. The operating mode
determines how the app searches or answers.

| Profile | Availability and purpose |
| --- | --- |
| `docs_only` | Default. Uses the existing Markdown allowlist and keeps the seven passage IDs and content versions. The current snapshot yields 21 semantic chunks. |
| `catalog_dev` | Blocked pending confirmed reuse permission. Designed for local exploration of the approved Markdown plus screened AIToolBuzz listings. The fixture tests exercise this profile using fictional records. |
| `catalog_unseen_eval` | Disabled. The fixture pins binary v4 manifest SHA-256 prefix `46b05a1c`, while the audited working-tree manifest starts with `797a7aa0`. Alias and identity review is also pending. The previously measured 5,566 provisional candidates are uncertified. |

Both interfaces report the profile, corpus version, actual passage counts,
and source roles. Semantic or RAG mode in the terminal reports the actual
chunk count. Terminal keyword mode builds no semantic index. Streamlit uses
the selected profile's cached index and retains the original profile and
version on each turn.

### Catalog schema and evidence rules

The loader accepts the cleaned AIToolBuzz columns in this order:
`tool_id`, `Name`, `Website`, `Category`, `Primary Task`,
`Short Description`, `Keywords`, `industry`, `text_quality_flag`,
`duplicate_description_flag`, and `description_label_conflict_flag`.
It validates required fields, unique 64-character hexadecimal IDs, HTTP(S)
website URLs, and known flag values. Blank optional fields stay absent.
The original description is preserved as citable text and the website
hostname is derived locally.

Markdown rules carry `project_policy`. Listings carry `tool_evidence` and
can support claims about advertised functionality or catalog membership.
A listing alone cannot establish verified AI Tool status, organizational
approval, employee activity, sensitive data submission, contextual risk,
or Previously Unseen Tool status. Gemini generation is restricted to
`docs_only`; the adapter also rejects catalog evidence before calling the SDK.

A listing has record ID `aitoolbuzz:<tool_id>` and a deterministic passage
ID derived from it. Its content version hashes the title, original text,
and citable metadata. Chunk IDs use the existing passage, version, and
character-span scheme. The corpus version hashes the profile, input
fingerprints, selection and eligibility policy, and passage IDs and
versions. The semantic cache also keys on the model and revision and
a fingerprint of the chunking code.

Development eligibility excludes the verified IDs for MeetOscar and Magic
Inspector and rows flagged for an identical-description Category conflict.
Additional reviewed IDs and reasons can be configured in
`REVIEWED_IDENTITY_EXCLUSIONS` in `profiles.py`. All applicable reasons are
recorded. Short and duplicate descriptions retain their review flags.
Distinct listings stay separate while their identities are uncertain.
The audit's 13,689 candidate count is provisional and is never used as a
runtime expectation. Development profiles are unsuitable for unseen-Tool
evaluation.

### Eventual activation and checks

Once confirmed for local use, record the reviewed permission reference in
`CATALOG_REUSE_REFERENCE` in `rag_bot/profiles.py`. The checked-in default
is unset. After activation, choose `catalog_dev` in Streamlit or pass
`--profile catalog_dev --mode semantic` in the CLI. Keep hosted transmission
and the unseen-evaluation profile blocked pending their separate reviews.

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_semantic
.venv-rag/bin/python -B -m rag_bot.chat --profile docs_only --mode keyword "What is a Tool Candidate?"
.venv-rag/bin/python -B -m rag_bot.chat --profile catalog_dev --mode keyword
.venv-rag/bin/python -B -m rag_bot.chat --profile catalog_unseen_eval --mode keyword
```

The last two commands should exit with a profile explanation under the
current configuration. `catalog.py` owns schema validation, `profiles.py`
owns selection and versioning, and `test_catalog.py` exercises both with
fictional CSV rows.

## Persistent local vector index

Semantic and RAG modes use an ignored repository-local cache at
`rag_bot/.index_cache/`. Keyword Search does not load the model or build an
index. The app checks profile permissions and reconstructs current chunks
before looking up vectors. The cache contains only a JSON manifest and
normalized float32 NumPy arrays. All evidence text and citation metadata come
from the authorized corpus loaded for the current run.

An index identity hashes the profile, corpus version, ordered chunk IDs,
pinned model and revision, embedding settings, chunking settings and code
fingerprint, and format and normalization versions. Questions, result limits,
and similarity cutoffs are outside that identity. On load, the manifest must
match the expected metadata exactly. The vector file must match its SHA-256,
shape, dtype, and finite unit-length or zero rows. A missing or invalid cache
triggers a rebuild. NumPy loads with pickle disabled.

Writers publish a complete checksum-named vector file using a temporary file
and an atomic rename. They publish the manifest last, the same way. Readers
can keep using the vector file named by the manifest they read. Two processes
can both embed on a cache miss, and the last valid manifest wins. There is no
cross-process build lock or automatic eviction. Old identities, superseded
vectors, and temporary files left by a hard interruption can accumulate.
A rebuild publishes only the current index and leaves other files in place.
A cache write failure leaves search available in memory and reports the
storage issue. Query embeddings and exact NumPy search still run in memory.

### Build, load, inspect, and debug

From the repository root:

```sh
# Build on a cache miss, or load the current index.
.venv-rag/bin/python -B -m rag_bot.chat --profile docs_only --mode semantic "What is a Tool Candidate?"
# Run the same command again to verify disk reuse in a new process.
.venv-rag/bin/python -B -m rag_bot.chat --profile docs_only --mode semantic "What is a Tool Candidate?"
# Inspect the local manifests.
find rag_bot/.index_cache -name manifest.json -exec cat {} \;
# Force a rebuild of the current index.
.venv-rag/bin/python -B -m rag_bot.chat --mode semantic --rebuild-index "What is a Tool Candidate?"
# Bypass both persistent reads and writes.
.venv-rag/bin/python -B -m rag_bot.chat --mode semantic --no-index-cache "What is a Tool Candidate?"
```

In Streamlit, use **Rebuild current index** or turn off **Persistent vector
cache**. The sidebar reports chunk count, dimensions, index status,
initialization time, and document embedding time when applicable. Streamlit
can reuse the active in-memory index on later reruns. The CLI reports the
same initialization details.

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_vector_store
```

`vector_store.py` owns local validation and atomic publication.
`test_vector_store.py` exercises persistent storage with fictional vectors.
`smoke_vector_store.py` runs separate cold and warm processes in a temporary
cache using the approved documentation corpus.

| Measurement, local CPU sample | Cold | Warm |
| --- | ---: | ---: |
| End-to-end process startup to index ready | 2.238 s | 2.050 s |
| Model load, including its lazy imports | 1.998 s | 1.946 s |
| Index initialization after model load | 0.185 s | 0.042 s |
| Document embedding | 0.142 s | skipped |
| Mean query time across six questions | 2.62 ms | 3.28 ms |
| Vector file / manifest | 32,384 B / 1,348 B | 32,384 B / 1,348 B |

Both runs returned identical ranked chunk IDs and scores to seven decimal
places on the six smoke questions. The 21-chunk corpus is too small to draw a
general performance conclusion. The model loads in both processes for query
embedding. Catalog permission, unseen-Tool evaluation certification, and
live Gemini verification remain pending.

## Hybrid retrieval

Hybrid Search runs weighted keyword overlap and semantic cosine search on
the same chunks. The original Keyword Search mode still ranks whole
passages. The chunk keyword index precomputes term sets and document
frequencies over headings, excerpts, and exact IDs. Both staged rankings
use the same authorized corpus and require no change to the disk vector
index.

Reciprocal Rank Fusion adds `1 / (k + rank)` for each ranking that contains
a chunk, with rank starting at 1. An absent ranking contributes zero.
The lists contribute equally, and the two raw score scales stay separate.
Duplicate chunk IDs use their first rank in each list. Exact fused ties
break by chunk ID. The provisional settings are `k=60`, 20 candidates per
method, 5 final results, a cosine cutoff of `0.25`, and at most 2 chunks
per original passage.

A semantic candidate must meet the cosine cutoff. A keyword-only
candidate must be in the keyword candidate list and match an exact chunk,
passage, or catalog Tool ID in the query, or match the entire normalized
query to a catalog listing name. For example, a bare catalog name can
qualify but mentioning that name in an unrelated sentence does not qualify
through the keyword-only path. A name match indicates a listing match.
It cannot establish Tool identity or AI functionality. Ordinary overlap
can contribute to the RRF score of an accepted semantic hit. It cannot
admit a hit on its own. Both cosine and RRF are ranking signals. A semantic
false positive can still enter fusion, and a valid paraphrase can fall
below the cutoff.

The per-passage cap is applied after ranking eligible chunks. It limits
redundant excerpts and can omit additional useful evidence in a long
passage. Some queries return fewer than five hits or no hits. Distinct
catalog listings retain their own passage IDs even when their text is
similar. RAG abstains without a generation request when the selected
retriever returns no evidence.

### Run and compare

From the repository root:

```sh
.venv-rag/bin/python -B -m rag_bot.chat --mode hybrid "What is a Tool Candidate?"
.venv-rag/bin/python -B -m rag_bot.chat --mode hybrid --candidate-depth 20 --rrf-k 60 --result-limit 5 --max-per-passage 2 --min-score 0.25 "How is contextual risk evaluated?"
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_hybrid
.venv-rag/bin/python -B -m streamlit run rag_bot/app.py --server.address 127.0.0.1
```

In Streamlit, choose **Hybrid Search** for retrieval alone. Demo and RAG
have a **Retrieval strategy** selector. **Retrieval diagnostics** shows
both component ranks and scores, and **Advanced hybrid settings** exposes
the fusion settings. Each turn keeps its strategy, cutoff, and settings.
Ranking changes reuse the same document embeddings.

Terminal RAG keeps semantic retrieval by default. The optional
`--mode rag --retrieval hybrid` uses the same Gemini adapter and citation
validator. Running RAG with matching evidence can make a live request.
Use local Hybrid Search or Streamlit Demo while live verification is on hold.
The catalog permission and Gemini transmission gates still apply.

`hybrid.py` contains fusion and retrieval configuration.
`test_hybrid.py` covers fusion and integration offline.
`smoke_hybrid.py` prints all four rankings, with source headings, IDs,
raw and fused scores, distinct passage counts, and per-query timings.

### CPU smoke findings

On the 21-chunk documentation corpus, hybrid recovered the two exact
references that semantic search missed. It kept the same leading chunk
for the Tool Candidate, AI Mention, contextual-risk, and AI marketing
queries. For the Tool Candidate definition, it kept the relevant first
chunk while increasing distinct passages from two to four. For the
uncertain-observations paraphrase, it moved a less relevant risk-rule
excerpt ahead of the terminology. For confidential submission, it
demoted the direct warning from second to third. Plain cake and three
unrelated queries with incidental terms returned no hybrid matches.
Both keyword baselines returned matches for all three incidental queries.

This local sample took approximately 0.39–0.75 ms for passage keywords,
0.01–0.03 ms for chunk keywords, 2.61–6.61 ms for semantic, and
2.61–5.86 ms for hybrid per question, excluding setup. These single-run
timings and relevance observations are exploratory. Threshold, candidate
depth, and diversification effects need Milestone 6.4 evaluation.

<details>
<summary>Ranked chunk IDs from the CPU sample</summary>

IDs appear in rank order. The number in parentheses is the distinct original
passage count. The smoke command above prints the headings and all scores.

| Question | Chunk keyword | Semantic | Hybrid |
| --- | --- | --- | --- |
| What is a Tool Candidate? | (1) `39dc057eb25718d30d7f`, `aecfd1e47a0a0f21965e`, `daaa5efada9a909ccb56`, `fe158e0805dd399772a8`, `48d6c79baf79f688c1f3` | (2) `daaa5efada9a909ccb56`, `84de396edf39d7aedc9f`, `bb116705221924b19a61`, `39dc057eb25718d30d7f`, `fe158e0805dd399772a8` | (4) `daaa5efada9a909ccb56`, `39dc057eb25718d30d7f`, `bb116705221924b19a61`, `5c98e73f349d2138d059`, `f68117bd5f34dd4410a7` |
| What is the difference between an AI Tool and an AI Mention? | (3) `84de396edf39d7aedc9f`, `f68117bd5f34dd4410a7`, `39dc057eb25718d30d7f`, `5f8bb8426a1b12d3ed7f`, `aecfd1e47a0a0f21965e` | (3) `84de396edf39d7aedc9f`, `f68117bd5f34dd4410a7`, `bb116705221924b19a61`, `39dc057eb25718d30d7f`, `daaa5efada9a909ccb56` | (4) `84de396edf39d7aedc9f`, `f68117bd5f34dd4410a7`, `39dc057eb25718d30d7f`, `bb116705221924b19a61`, `5f8bb8426a1b12d3ed7f` |
| How do we identify potentially unknown software applications? | (4) `84de396edf39d7aedc9f`, `bb116705221924b19a61`, `458ba390bd07c1e4eb39`, `5f8bb8426a1b12d3ed7f`, `94c8a41d9c16885f1064` | (2) `daaa5efada9a909ccb56`, `84de396edf39d7aedc9f`, `fe158e0805dd399772a8`, `f68117bd5f34dd4410a7`, `39dc057eb25718d30d7f` | (4) `84de396edf39d7aedc9f`, `bb116705221924b19a61`, `daaa5efada9a909ccb56`, `d6bac100c93cae898f51`, `d039e9c4b17d91a10f80` |
| Does visiting an application prove confidential information was submitted? | (3) `324ba4e76269b5ad98a4`, `d039e9c4b17d91a10f80`, `d6bac100c93cae898f51`, `458ba390bd07c1e4eb39`, `c41d55992bdf5ff1c9d4` | (2) `458ba390bd07c1e4eb39`, `d6bac100c93cae898f51`, `324ba4e76269b5ad98a4` | (2) `324ba4e76269b5ad98a4`, `458ba390bd07c1e4eb39`, `d6bac100c93cae898f51` |
| How is contextual risk evaluated? | (4) `48d6c79baf79f688c1f3`, `5c98e73f349d2138d059`, `5f8bb8426a1b12d3ed7f`, `aecfd1e47a0a0f21965e`, `bb116705221924b19a61` | (3) `5c98e73f349d2138d059`, `aecfd1e47a0a0f21965e`, `fdeef0ca9a3cafdc4f87`, `5f8bb8426a1b12d3ed7f`, `94c8a41d9c16885f1064` | (3) `5c98e73f349d2138d059`, `aecfd1e47a0a0f21965e`, `5f8bb8426a1b12d3ed7f`, `48d6c79baf79f688c1f3`, `fdeef0ca9a3cafdc4f87` |
| How do I bake a chocolate cake? | No hits | No hits | No hits |
| How do uncertain observations get grouped before software identity is resolved? | (4) `84de396edf39d7aedc9f`, `5f8bb8426a1b12d3ed7f`, `daaa5efada9a909ccb56`, `c41d55992bdf5ff1c9d4`, `bb116705221924b19a61` | (3) `fe158e0805dd399772a8`, `daaa5efada9a909ccb56`, `5f8bb8426a1b12d3ed7f`, `d039e9c4b17d91a10f80`, `d6bac100c93cae898f51` | (3) `5f8bb8426a1b12d3ed7f`, `daaa5efada9a909ccb56`, `84de396edf39d7aedc9f`, `57d0d3ab49b5b380cfcc`, `d039e9c4b17d91a10f80` |
| Can an AI marketing claim alone establish what software actually does? | (4) `f68117bd5f34dd4410a7`, `84de396edf39d7aedc9f`, `fe158e0805dd399772a8`, `d039e9c4b17d91a10f80`, `bb116705221924b19a61` | (3) `f68117bd5f34dd4410a7`, `84de396edf39d7aedc9f`, `bb116705221924b19a61`, `fe158e0805dd399772a8`, `daaa5efada9a909ccb56` | (4) `f68117bd5f34dd4410a7`, `84de396edf39d7aedc9f`, `fe158e0805dd399772a8`, `bb116705221924b19a61`, `d039e9c4b17d91a10f80` |
| Find passage c44b2b41dea183af. | (2) `57d0d3ab49b5b380cfcc`, `39dc057eb25718d30d7f`, `48d6c79baf79f688c1f3`, `84de396edf39d7aedc9f`, `94c8a41d9c16885f1064` | No hits | (1) `39dc057eb25718d30d7f`, `48d6c79baf79f688c1f3` |
| Show chunk daaa5efada9a909ccb56. | (2) `daaa5efada9a909ccb56`, `f68117bd5f34dd4410a7` | No hits | (1) `daaa5efada9a909ccb56` |
| How do I bake a chocolate cake for the governance committee? | (4) `324ba4e76269b5ad98a4`, `48d6c79baf79f688c1f3`, `57d0d3ab49b5b380cfcc`, `aecfd1e47a0a0f21965e`, `bb116705221924b19a61` | No hits | No hits |
| What bike tire pressure should I use for a risk assessment team outing? | (3) `324ba4e76269b5ad98a4`, `c4cfee566cdb8072be45`, `5f8bb8426a1b12d3ed7f`, `daaa5efada9a909ccb56`, `48d6c79baf79f688c1f3` | No hits | No hits |
| How do I water an orchid using a tool from my kitchen? | (3) `84de396edf39d7aedc9f`, `39dc057eb25718d30d7f`, `48d6c79baf79f688c1f3`, `5c98e73f349d2138d059`, `5f8bb8426a1b12d3ed7f` | No hits | No hits |

</details>

## Documentation retrieval benchmark

This benchmark measures retrieval on the current `docs_only` snapshot.
It does not evaluate generated answers or certify Previously Unseen Tool
performance. The checked-in [60 questions and relevance judgments](evaluation/benchmark-v1.json)
contain 36 calibration and 24 held-out questions, with paraphrase families kept
together. All 13 prior smoke questions are in calibration. Grades and rationales
were drafted from the approved excerpts before tuning and await independent
human review.

From the repository root, reproduce into a separate output directory:

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.evaluate --phase calibrate --output /tmp/cyera-retrieval-v1
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.evaluate --phase evaluate --output /tmp/cyera-retrieval-v1
```

`evaluate.py` validates benchmark IDs, source versions, and family splits.
Calibration caches candidate scores across sweeps and writes a frozen
selection before the held-out command. The held-out command checks the
benchmark, corpus, model revision, selection rule, and calibration IDs.
Both phases time real query calls separately from the sweep. The
[protocol](evaluation/PROTOCOL.md) spells out the formulas and weights.

The comparison uses five-result metrics. Hit Rate, Precision, Recall,
and MRR count direct Grade 2 evidence. Precision always divides by five.
Recall divides by the number of judged direct units. MRR averages the
reciprocal of the first direct rank, with zero for misses. nDCG discounts
Grade 2 and Grade 1 gains of three and one by `log2(rank + 1)`, then
normalizes to the ideal judged order. Unjudged results get zero gain.
Passage metrics deduplicate by original passage ID in rank order within
the returned results. Chunk metrics keep distinct excerpts. Answerable
ranking metrics, out-of-domain empty rates, and unsupported background
hits use separate denominators. A nonempty irrelevant list is a ranking
miss. It is not false abstention.

### Calibration and frozen selection

Stages sweep the semantic and hybrid cutoffs from 0.15 through 0.40.
Hybrid then sweeps k, depth, passage cap, and final limit one factor at a
time. The fixed utility weights direct hits, graded rank, multi-evidence
coverage, and out-of-domain abstention. The chosen semantic cutoff was
**0.25**. Frozen hybrid settings were **cutoff 0.25, k=10, depth 20 per
method, no passage cap, and 5 final results**. The application still
uses its existing defaults.

| Calibration method | Passage Hit / nDCG@5 | Chunk Hit / nDCG@5 | Empty out of domain |
| --- | ---: | ---: | ---: |
| Passage keyword | .889 / .795 | — | 2/5 |
| Chunk keyword | 1.000 / .867 | .926 / .672 | 2/5 |
| Semantic baseline and selected | .815 / .743 | .778 / .608 | 5/5 |
| Hybrid baseline | .926 / .867 | .889 / .698 | 5/5 |
| Hybrid selected | .926 / .858 | .926 / .754 | 5/5 |

At the hybrid cutoff stage, 0.15 raised direct chunk hit rate from .889
to .926 and dropped correct empty responses from 5/5 to 3/5.
A 0.30 cutoff still abstained on 5/5 and reduced chunk hit rate to .704.
Changing k from 60 to 10 improved the utility only marginally. Removing
the cap helped chunk ranking and recall in calibration and reduced
diversity relative to capped hybrid.

### Held-out results

| Method | Passage Hit / nDCG@5 | Chunk Hit / nDCG@5 | Empty out of domain | False abstention, answerable |
| --- | ---: | ---: | ---: | ---: |
| Passage keyword | .889 / .804 | — | 0/3 | 1/18 |
| Chunk keyword | 1.000 / .913 | 1.000 / .726 | 0/3 | 0/18 |
| Semantic baseline and selected | .833 / .706 | .667 / .507 | 2/3 | 3/18 |
| Hybrid baseline | .944 / .855 | .778 / .675 | 2/3 | 1/18 |
| Hybrid selected | .944 / .847 | .778 / .663 | 2/3 | 1/18 |

Calibrated hybrid recovered both held-out exact references, which semantic
missed. Excluding those two questions, both found direct chunk evidence
on 12 of 16. Both covered 50% of required excerpt groups on the two
multi-evidence questions, while chunk keyword covered all groups. At
passage level, both appeared to cover all groups because the broader
passage can contain multiple required excerpts. All four methods retrieved
background on all three unsupported held-out questions. The corpus
still lacks their case-specific facts.

Selected hybrid returned a mean of 2.12 distinct passages and selected
semantic 2.21. Held-out query latency for selected hybrid was 2.451 ms
mean, 2.440 ms median, and 2.740 ms p95. Selected semantic measured
2.383 / 2.378 / 2.507 ms. These timings come from one sequential CPU
run over a small corpus and do not establish a general speed advantage.

### What failed and why

- **Exact references, DOC-044 and DOC-045.** Semantic returned empty.
  The exact lexical rule surfaced the provenance excerpt
  `d039e9c4b17d91a10f80` and the ADR 0001 excerpt
  `f68117bd5f34dd4410a7`. On DOC-045, chunk keyword initially ranked a
  provenance excerpt for its incidental word “passage.” Hybrid
  admitted the explicit ID match.
- **Semantic paraphrase, DOC-013.** Semantic ranked the excerpt
  defining the grouping of unresolved identity clues first
  (`daaa5efada9a909ccb56`, cosine .452). Chunk keyword's top five missed
  both direct excerpts. Hybrid retained the candidate definition at
  rank three, behind broad Tool terminology and governance background.
- **Hybrid rank regression, DOC-027.** The contextual-risk excerpt
  explicitly says the activity condition is “not proof that data was
  submitted.” Hybrid moved it from semantic rank two to fused rank
  three. The appeal of the top fused result came from keyword rank one,
  though that excerpt discusses evidence assembly and citation format.
- **False abstention, DOC-011.** The glossary distinguishes a successful
  unresolved outcome from execution failure, but neither semantic nor
  hybrid returned a chunk. The literal match appeared in chunk keyword.
  Hybrid's fallback admits exact references and catalog names, so an
  ordinary glossary term could not override the cutoff.
- **Incidental terms and a semantic false positive, DOC-051.** All
  methods returned evidence for a question about which train to take.
  The risk grouping excerpt scored .371 cosine even though it contains
  no travel information. Incidental risk/policy phrasing is a plausible
  explanation. The measured result is the score and the irrelevant hit.
- **Passage cap, DOC-004.** In a calibration diagnostic holding the other
  selected settings fixed, cap two omitted the glossary chunk
  `fe158e0805dd399772a8`, which defines Category as one of 14 business
  function labels. Earlier chunks of the same passage filled its slots.
  Removing the cap restored that excerpt.
- **Multi-evidence gap, DOC-040.** Both semantic and hybrid found the
  provenance instructions to cite contributing Runs, event-time range,
  and count definition. They missed `c41d55992bdf5ff1c9d4`, where the
  assistant contract directs FastAPI to execute bounded deterministic
  queries. Broad passage-level scoring hid the missing excerpt.
- **Unsupported question, DOC-059.** Retrieved risk rules describe
  which facts matter for admin controls. They contain no evidence about
  the organization's particular subscription. A background hit cannot
  answer the question.

### Recommendation and artifacts

Advance hybrid as the **candidate default for Milestone 6.5 review**.
It improved direct-evidence retrieval over semantic while matching the
measured out-of-domain empty rate. The held-out hit gain came from two
exact-reference questions. The uncapped calibrated configuration also
scored slightly below the capped hybrid baseline on held-out nDCG.
Keep the current semantic default until review and use a new independent
question set to assess diversification and semantic false positives.
The small corpus, three held-out out-of-domain prompts, two held-out
multi-evidence prompts, and unreviewed labels limit generalization.

- [Benchmark and partitions](evaluation/benchmark-v1.json)
- [Frozen configuration and 24 staged sweep trials](evaluation/results/selection.json)
- [Calibration aggregate, per-category, per-question, and latency results](evaluation/results/calibration.json)
- [Held-out aggregate, per-category, per-question, and latency results](evaluation/results/held_out.json)
- `test_evaluate.py` tests metric calculations, labels, partitions,
  cutoff-independent deduplication, and calibration isolation.

The evaluation directory is outside the retrieval allowlist. The reports
record the corpus version, pinned model revision, and execution environment.

## Presets and offline demonstration

`presets.py` defines the named settings used by the CLI and Streamlit.
Semantic remains the running default. Keyword Search still uses the
original whole-passage baseline. Presets affect query ranking and reuse
the authorized document index.

| Preset | CLI key | Settings |
| --- | --- | --- |
| Semantic — Stable | `semantic-stable` | Cosine cutoff 0.25, five results |
| Hybrid — Baseline | `hybrid-baseline` | k=60, 20 candidates per method, five results, cutoff 0.25, at most two chunks per passage |
| Hybrid — Calibrated (experimental) | `hybrid-calibrated` | k=10, 20 candidates per method, five results, cutoff 0.25, no passage cap |

From the repository root:

```sh
.venv-rag/bin/python -B -m streamlit run rag_bot/app.py --server.address 127.0.0.1
.venv-rag/bin/python -B -m rag_bot.chat --mode semantic --preset semantic-stable "What is a Tool Candidate?"
.venv-rag/bin/python -B -m rag_bot.chat --mode hybrid --preset hybrid-baseline "How is contextual risk evaluated?"
.venv-rag/bin/python -B -m rag_bot.chat --mode hybrid --preset hybrid-calibrated "Show chunk daaa5efada9a909ccb56."
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
```

In Streamlit, select the operating mode and then the applicable preset.
Demo and RAG also expose a retrieval strategy selector. **Advanced
retrieval settings** permits overrides. Each turn retains the original
mode, preset, settings, and corpus version. Sources cited by an answer
and all retrieved evidence have separate expandable views. Demo is
labeled as simulated and uses only local evidence. Leave Gemini off
during the offline demonstration.

| Example | Mode | What to check |
| --- | --- | --- |
| What is a Tool Candidate? | Semantic — Stable | The glossary excerpt defines how identity clues are grouped. |
| Can an AI marketing claim alone establish what software actually does? | Semantic — Stable | ADR 0001 explains the difference between a mention and demonstrated functionality. |
| Show chunk daaa5efada9a909ccb56. | Hybrid — Baseline | The requested chunk ID appears at rank one. |
| How is contextual risk evaluated? | Hybrid — Baseline | Turn on diagnostics to see keyword rank, semantic rank, and RRF. |
| What is the risk tier of a specific employee's ChatGPT usage? | Demo with Semantic — Stable | Retrieved background and a simulated partial status are shown. An employee-specific assessment requires records outside the corpus. |
| How do I bake a chocolate cake? | Hybrid — Baseline | Shows no relevant evidence. |

These examples were verified with the cached CPU model through Streamlit.
The scope notice describes the corpus rather than classifying questions
or deciding answerability. A service failure is shown separately from
empty retrieval. Generative behavior still requires live verification.

The **Retrieval evaluation** tab reads the frozen benchmark, selection,
and reports through `evaluation_view.py`. It shows calibration and
held-out metrics separately and checks the artifacts against the current
documentation corpus and pinned model. Missing or stale reports produce
a warning while the assistant remains available. The tab never feeds
benchmark material into the retrieval pipeline. `test_presets.py` verifies
settings, CLI selection, and report compatibility.

## Reusable documentation retrieval service

`service.py` exposes a synchronous Python interface without importing
Streamlit or Gemini generation. It uses the same authorized `docs_only`
snapshot, chunker, index cache, MiniLM model, and named retrieval presets.
Initialize one service per process or worker and reuse it across requests.
The service serializes access to the embedder. Pass `cache_dir=None` to
use an in-memory index.

```python
from rag_bot.service import RetrievalRequest, RetrievalService

service = RetrievalService()
result = service.retrieve(RetrievalRequest("What is a Tool Candidate?"))
if result.status == "data":
    evidence = result.matches[0].evidence
    resolution = service.resolve(evidence.reference)
    assert resolution.evidence == evidence
```

The query must contain 1–2,000 characters after stripping. The request
limit is a strict integer from 1 to 10 (default 5) and overrides only
the preset's final result count. Preset IDs match the CLI and default to
`semantic-stable`. The service checks the actual embedding tokenizer
including special tokens. Inputs that exceed its limit receive
`unsupported_input` without truncation or embedding.

Retrieval returns `data`, `no_matches`, `unavailable`, `invalid_input`,
`unsupported_input`, or `execution_failure`. Failures return a safe local
message with no raw exception detail. Resolve returns `resolved`,
`malformed_reference`, `not_found`, `version_mismatch`, or `unavailable`.

`evidence.py` constructs the unprefixed reference
`passage:<corpus_version>:<document_id>:<document_version>:<chunk_id>`.
The document ID is `doc-` plus the SHA-256 of the exact repository-relative
source path. The document version fingerprints the full source bytes.
The existing chunk ID is the proposed backend passage ID. The original
section ID, source path, heading, and `project_policy` role are retained.
The excerpt is the original chunk slice with boundary whitespace stripped;
ranking scores and ranks are returned separately.

Resolution checks every reference component against the service's
loaded snapshot. Recreate the service to load changed documents or retry
failed initialization. References from other snapshots, including historical
versions absent from the loaded snapshot, do not resolve. The local resolver
accepts the unprefixed reference; a future backend adapter handles any
step prefix. The service has no Batch or Run scope and supplies documentary
evidence only. Future backend code owns authentication, authorization,
pinned scope, async dispatch, result-byte budgeting, and any decisions about
sending evidence externally.

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_service
```

## Isolated backend compatibility adapter

`backend_adapter.py` targets upstream revision
`d271c83de9b9bf222546612f9bb66fd108ce247c`. It injects the real
`app.assistant.contracts`, `app.assistant.tools`, and `app.evidence` modules
through `BackendModules`. The independent service still runs without the
backend, Streamlit, or Gemini dependencies.

The adapter implements the async handler shape
`await adapter(scope, arguments)` and maps the actual
`RetrieveContextArgs` into the service's default semantic retrieval request.
It can return `ToolSuccess(data)`, `ToolSuccess(no_matches)`,
`ToolLimitation(unavailable)`, `ToolLimitation(unsupported)`, or a safe
`ToolFailure`. Unsupported input includes a query beyond the tokenizer
limit. Invalid arguments, worker failure, overload, timeout, and an
individually oversized result have distinct failure codes. The scope is
passed to an explicit authorization check. Its fields are never inferred
from the question or attached to documentary evidence.

Synchronous retrieval runs in a worker thread. One active dispatch is
allowed per service across adapters, and another call receives
`retrieval_busy` while the worker owns capacity. The caller can cancel or
time out without stopping the running thread. Capacity is released by
the worker when it exits. Authorization hooks must be fast, local checks.
The backend's own turn deadline remains authoritative.

The default argument and result budgets are 4,096 and 32,768 UTF-8 JSON
bytes. The adapter uses the upstream serializer and reserves a 64-byte
ASCII namespace plus its colon per evidence ID. The current upstream
step namespace is 37 bytes. To fit a tight limit it drops complete
lower-ranked passages and marks the preview truncated with a qualification.
An excerpt that cannot fit even by itself yields an explicit failure.
Chunk IDs serve as backend passage IDs. Canonical excerpts and full
references are retained in typed `PassageEvidence`; rankings and original
section IDs are in the result data.

`adapter.resolve_passage(connection, reference)` implements the synchronous
resolver shape. It maps exact current-snapshot references to
`ResolvedEvidence`, uses the resolver role `governance_guidance`, and
retains `project_policy` in the record. Stale versions return
`source_version_unavailable`. The adapter ships unregistered and denies
retrieval or inspection unless explicitly supplied authorization callbacks.
The future backend owns authentication, scope and historical retention,
async integration, and external transmission approval. Register the
handler and resolver against the same service snapshot only after those
decisions are approved. The audited upstream `get_evidence` currently
omits resolved passages from its typed citation tuple, which still needs
a backend change before end-to-end citation reuse.

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_service
.venv-rag/bin/python -B -m rag_bot.verify_backend_contract --checkout /path/to/existing/audited-checkout
```

The ordinary adapter tests use wire doubles. The separate conformance
runner verifies exact Git blob hashes and executes the real assistant
contract and registry source, plus the exact resolver declarations and
execution-limit model. It also accepts a JSON mapping from repository paths
to exact source text on standard input, so it can run without updating Git
references. This verifies typed mapping and registry serialization with
the available Pydantic runtime. It does not execute the full upstream
backend, LangGraph workflow, database, or public evidence endpoint.

The [integration guide](INTEGRATION.md) records the isolated upstream
passage-path verification, the reproduced typed-citation omission, and the
remaining backend registration and deployment work.

## Contribution and portability checklist

The tested environment is Python **3.15.2** on macOS. The keyword path
uses the standard library and its syntax assumes Python 3.10 or newer.
The semantic dependency set and optional backend verification target
Python 3.12 or newer, based on the NumPy pin and upstream backend minimum.
Other Python versions and operating systems have not been verified here.

| Feature | Dependencies and prerequisites |
| --- | --- |
| Terminal Keyword Search | Python standard library. |
| Semantic, Hybrid, and reusable retrieval service | `requirements-semantic.txt`. SentenceTransformers brings the PyTorch runtime (tested with 2.15.0). Pre-provision the exact MiniLM revision listed above in the local Hugging Face cache. |
| Optional Gemini generation | `requirements-rag.txt`. Explicitly choosing CLI `--mode rag` or checking the Streamlit consent box authorizes a request. Keep those paths off for offline demos. |
| Optional Streamlit interface and full offline unit suite | `requirements-ui.txt`. The interface imports the optional SDK for its Gemini mode, and local modes work without credentials. |
| Isolated upstream verifiers | Semantic dependencies and Pydantic (tested with 2.14.4), plus the exact hash-checked upstream sources. The passage-path verifier also requires the pinned model in cache. See [INTEGRATION.md](INTEGRATION.md). |

The independent service imports neither Streamlit nor the generation
modules. The dependency files pin direct packages and do not lock the
transitive stack for every platform. Persistent index identity includes
the exact model revision, ordered chunks, corpus identity, and chunking
configuration. If those change, build a fresh index. Benchmark reports
correspond to their frozen corpus and model identities.

### Proposed contribution inventory

- **Core source and tests** comprise corpus, chunking, profiles, catalog
  gates, lexical and semantic retrieval, hybrid fusion, presets, vector
  storage, the local service and evidence resolver, the isolated adapter,
  and their tests. The catalog loader's inclusion does not activate a corpus.
- **Optional demonstration and verification** comprise the terminal and
  Streamlit entry points, report view, local Gemini and Demo code, smoke
  scripts, upstream verifiers, and feature-specific requirements files.
- **Documentation and benchmark** comprise this README, the integration
  guide, the evaluation protocol, the benchmark, and the three frozen JSON
  reports. Keep their distinct provenance and keep evaluation files outside
  the retrieval allowlist.
- **Generated and private material** stays out of contributions. The
  prototype ignore rules cover `.index_cache/`, `.model_cache/`,
  `.traces/`, `.scratch/`, and `evaluation/.runs/` inside `rag_bot/`.
  Use those folders or an external temporary directory for new artifacts.
  Repository rules ignore bytecode and backend runtime state. The model cache
  normally lives outside the repository. Avoid adding environment files,
  API keys, real employee data, or private logs.
- **Local Git exclusions** currently protect root `.env.rag` and
  `.venv-rag/` in this checkout. These rules do not travel with a
  contribution. Verify exclusion locally before staging or negotiate a
  shared root ignore change with maintainers. The stabilization scope only
  allows changes inside `rag_bot/`.
- **Third-party material** needs separate review. Keep real catalog
  activation blocked pending reuse permission and keep downloaded model
  weights outside the contribution. Confirm the repository contribution
  license with maintainers. The root README names MIT, and the audited
  revision has no tracked root license file.

For an offline demo, start Streamlit, ask the Tool Candidate definition in
Semantic — Stable, switch to Hybrid Search and find the exact chunk ID,
then select Demo and ask the employee-risk question. The resulting
background and simulated status are separate from a case-specific
assessment. Ask the cake question in Hybrid Search to see empty retrieval,
then open the evaluation tab to compare the two frozen partitions.
