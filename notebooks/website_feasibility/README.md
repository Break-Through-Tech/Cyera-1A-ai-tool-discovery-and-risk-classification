# Website-text feasibility: can anything beat the keyword rule?

This experiment asks whether an AI/non-AI classifier has room to beat the v4 keyword rule on the text the application will actually classify at runtime: fetched homepages, not catalog taglines. No model is trained.

## Run it

```sh
python3 -m venv /tmp/cyera-enrichment-venv
/tmp/cyera-enrichment-venv/bin/pip install -r notebooks/metadata_enrichment/requirements.txt
/tmp/cyera-enrichment-venv/bin/python notebooks/website_feasibility/fetch_sample.py   # refetches; sites change
python3 notebooks/website_feasibility/analyze.py                                     # rescoring only
```

## Method

1. **Sample.** Seed `20261022` draws 150 distinct domains from AIToolBuzz (`Website Status == Active`) and 150 from [CompanyEnrich SaaS](../../data/companyenrich-saas-companies/SOURCE.md). Domains present in both sources are excluded.
2. **Fetch.** `fetch_sample.py` reuses the [metadata-enrichment](../metadata_enrichment/README.md) rules: robots.txt is honored, the agent is identified explicitly, requests use timeouts and a 2 MB limit, and curl_cffi is the client. It keeps the title, meta/Open Graph descriptions, H1/H2 headings, and up to 6,000 characters of Trafilatura main text. 250 of the 300 homepages were usable (112 AIToolBuzz, 138 CompanyEnrich).
3. **Label.** Two independent model passes label each page from its text only, under [`labeling/RUBRIC.md`](labeling/RUBRIC.md). They don't see the source, catalog metadata, or keyword results. The labels are `ai_core`, `ai_feature`, `ai_mention_only`, `no_ai`, and `insufficient`. Packets are shuffled across sources.
4. **Score.** `analyze.py` scores the unchanged v4 regex on the 231 agreed, sufficient pages under two definitions:
   - **any product AI claim:** core, feature, or mention-only counts as AI.
   - **real AI capability:** only core or feature counts as AI.

## Results (captured 2026-10-22)

The two passes agreed on 245 of 250 pages. All 5 disputes are on the boundary between `ai_feature`, `ai_mention_only`, and `no_ai`. Both passes used the same underlying model, so this agreement is an upper bound on how consistently humans would label.

| Method | Any AI claim: macro-F1 | Real AI capability: macro-F1 | Real capability: false alarms / misses |
|---|---|---|---|
| Keyword rule, full page | 0.884 | 0.811 | 36 / 5 |
| Keyword rule, title/meta/headings only | 0.820 | 0.785 | 25 / 24 |
| Catalog source as label (AIToolBuzz = AI) | 0.718 | 0.784 | 10 / 40 |

- **On websites the keyword rule rarely misses AI.** It caught 124 of 129 real-capability pages. The 5 misses include Todoist, Quizlet, and GeoGebra, whose AI features are described without the listed terms.
- **Its errors are false alarms from context.** 19 of 85 no-AI pages contain a keyword, where AI is the product's subject (analytics tracking AI traffic, SEO for AI search, password managers securing AI agents), its content (blog or course headlines), or a denial ("no AI translations"). All 17 mention-only pages also match. On CompanyEnrich pages, AI precision under the real-capability definition is 0.54.
- **The catalogs are poor labels for websites.** 56 of 132 sufficient CompanyEnrich "SaaS" pages make a product AI claim, and 40 describe a real AI capability. 9 AIToolBuzz pages show no AI, and 11 are unusable.

### Under the adopted definition ([ADR 0001](../../docs/adr/0001-ai-tool-requires-own-ai-functionality.md))

Mapping labels through the rubric's AI Determination table gives 130 AI, 85 non-AI, and 35 unresolved pages. The unresolved pages are 17 vague claims, 14 insufficient, and 4 disputes that span determinations; PamPam's core-versus-feature dispute resolves to AI. On the 215 resolved pages, the full-page keyword rule scores **0.879 macro-F1** (AI precision 0.87, recall 0.96, 19 false alarms, 5 misses). Separately, it calls all 17 vague-claim pages AI, because a keyword cannot abstain.

## Interpretation and limits

The headroom is in precision, not recall. Deciding whether an AI mention refers to the product's own functionality requires reading context, which is exactly what the labelers did and a keyword cannot. A text model, or an LLM judgment restricted to the fetched evidence, has room to raise macro-F1 for real AI capability from about 0.81 toward the labeler-agreement ceiling. That is an opportunity, not a demonstrated result. No model was tested here, and these 231 pages were used to characterize keyword errors, so they shouldn't be used to tune a future rule or model while also claiming held-out performance.

Labels are model-generated, not human-reviewed, and come from a single homepage per tool. 2026 homepages also differ from the dated catalog snapshots. Websites change, so refetching gives different captures.
