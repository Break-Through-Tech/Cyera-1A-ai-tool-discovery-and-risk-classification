# Is runtime website metadata viable classifier input?

## Conclusion

Yes: published models have classified website topics and company industries using website descriptions, HTML metadata, and homepage text. This is credible precedent for an on-demand functionality-text classifier. It is not proof of Cyera's AI/non-AI accuracy, nor proof that any existing model predicts AIToolBuzz's categories.

Treat metadata as one evidence channel, not a universally sufficient input. The most defensible initial representation is title + meta description + relevant headings/product text, with explicit missing-evidence handling and retained source provenance.

## Research method

Three read-only Pi agents ran in Herdr panes on GPT-6 Luna with high thinking. Independent scopes: metadata-specific studies; modern website/company classifiers; transfer and extraction risks. A second pass independently verified the strongest claims against primary papers. The coordinator additionally fetched the primary Homepage2Vec and Jagrič/Herman texts and checked input/evaluation passages. A generic source_check call returned 'unclear', so its verdict was not used as proof; the exact primary passages were inspected instead. No classifier was trained or evaluated by this research.

## 1. Meta-description input has direct classification precedent

**Timotej Jagrič and Aljaž Herman (2024), AI Model for Industry Classification Based on Website Data.**

- Primary full text: https://www.mdpi.com/2078-2489/15/2/89
- DOI: https://doi.org/10.3390/info15020089
- Task: classify business descriptions into 13 industry classes.
- Input: the existing dataset's `Meta Description` column. `Category` is the target, not an input feature.
- Model/data: fine-tuned BERT; 66,886 cleaned records, split 80/20 into training and validation.
- Authors report 88.23% accuracy and F1 0.88. The cited passage does not specify the F1 averaging convention. These are validation results, not an independently reproduced external test.

Exact input passage, §3:

> we only kept 2 of them—“Meta Description”, which contains short business description of the work, and “Category”, in which the corresponding industry class is attributed.

Metric passage, §5:

> our developed model demonstrated an accuracy of 88.23% and an F1 score of 0.88.

**Important qualification:** this establishes predictive value of supplied short business descriptions. It does not establish automated live-crawl coverage or catalog-to-homepage transfer. Although the article discusses live integration, its measured experiment uses a pre-existing dataset; §5 explicitly calls reliance on manually sourced business descriptions a limitation and proposes automated scraping as future work.

## 2. URL → fetched homepage → classification has reproducible precedent

**Sylvain Lugeon, Tiziano Piccardi, Robert West (2022), Homepage2Vec: Language-Agnostic Website Embedding and Classification.**

- Primary paper: https://arxiv.org/html/2201.03677v3
- Official code/model: https://github.com/epfl-dlab/homepage2vec
- Task: 14 top-level Curlie website topics, NOT AIToolBuzz's 14 business-function labels.
- Data: 886K processed accessible homepage URLs; original directory collection 2.28M URLs.
- Input: title, description, keywords, homepage text, domain/TLD, link paths, metatag presence, and screenshot features. The released library also supports operation without visual features.
- Model: XLM-R text embeddings and a feed-forward classifier, with additional feature families.
- Reported macro-F1: 0.902 for class-balanced testing; 0.634 for the original unbalanced testing distribution after calibration. These are different evaluation regimes, not interchangeable performance claims.

Exact scope passage, “Features”:

> All features are extracted from the homepage of a website only. This is important in practice, as it means websites need not be crawled in full; only the homepage URL needs to be known and downloaded.

Exact metadata passage, “Title, description, keywords”:

> we extract them from the HTML of the Web page and represent them as three feature vectors via XLM-R.

**Implication:** a small homepage fetch can provide classification input without a full crawler. But the headline scores belong to a mixed-input model, not meta descriptions alone. Curlie's labels are incomplete; the paper discusses this explicitly. Exact complete train/dev/test proportions and product-level leakage controls were not established in the inspected text. Its pretrained label set is not a drop-in Cyera classifier.

## 3. Older field-level research favors combining evidence

**Koraljka Golub and Anders Ardö (2005), Importance of HTML Structural Elements and Metadata in Automated Subject Classification.**

- DOI: https://doi.org/10.1007/11551362_33
- Author-hosted paper: https://koraljka.net/publ/2005ECDL.pdf
- Task: engineering subject classification using title, headings, metadata, and main text.
- Sample: abstract says 1,000 pages; methods and evaluation tables say 1,003.

Exact conclusion, §5:

> The study showed that using all the structural elements and metadata is necessary since not all of them occur on every page.

**Implication:** missing fields and unequal signal quality justify retaining several text channels. This narrow, older task does not establish modern AI-tool performance or a universal metadata-only advantage.

## 4. A recent website-sector corpus supports the approach, with realistic limitations

**Shahriar Shayesteh et al. (2025), SoAC and SoACer: A Sector-Based Corpus and LLM-Based Framework for Sectoral Website Classification.**

- Primary PDF: https://shomir.net/pdf/publications/soac_doceng_2025.pdf
- DOI: https://doi.org/10.1145/3704268.3742691
- Dataset: https://huggingface.co/datasets/Shahriar/SoAC_Corpus
- Task: company websites classified into 10 broad sectors. Initial PDL industry labels are mapped from 148 fine-grained labels to 10 PrivaSeer sectors.
- Input: landing page plus depth-one same-domain pages, boilerplate removal, extractive summaries, frozen Llama-3-8B embeddings, trained MLP head.
- Table 4 reports 72.6% accuracy and 72.4% weighted F1 for its best listed Llama3-8B model.
- Corpus is reported as 195,495 websites in abstract/§3.2; Figure 1 instead says 195,485 samples. Do not treat either as a verified released-file count without inspecting that file.

**Implication:** fetched website text can support business-sector classification at scale, but broad/overlapping labels and noisy text remain difficult. This is not metadata-only evidence, and its sectors are not Cyera's categories. The paper's summary-vs-full-text improvement is specific to a subsampled smaller-model experiment, not a universal justification for adding an LLM summarizer.

## Evidence limits

No primary source verified in this bounded search demonstrated the exact task: AI-tool versus non-AI-tool detection from runtime-fetched product metadata, followed by AIToolBuzz category classification. That means direct evidence was not found here, not that no such work exists.

These studies do not measure the transfer from AIToolBuzz-written descriptions to current website copy. They also do not establish that a vendor's AI marketing proves an employee used an AI feature. Product functionality, identity resolution, and observed feature use remain distinct.

The local fetch experiment recovered Claude's useful meta description but mostly footer text from Trafilatura, and LibreOffice's metadata was more useful than its extracted main text. These examples agree with the evidence for multiple channels, but they are not accuracy measurements.

## Recommended Cyera experiment

1. Assemble a reviewed tool-level transfer sample: AI-positive, non-AI, mixed-function and ambiguous products, plus blocked/missing-evidence cases. Keep enough support per category to avoid overstating category results from a tiny sample.
2. Freeze tool-held-out partitions with suspected same-product records grouped. Vendor-held-out evaluation is an additional stress test, not a replacement for the project's Previously Unseen Tool definition. Keep evaluation tools out of known lookup and retrieval evidence as required by the plan.
3. On the same held-out tools compare (a) title/meta description, (b) relevant body/headings, (c) combined functionality text. Evaluate the catalog-description-trained baseline on runtime text to measure the actual transfer gap; compare against training augmented with reviewed fetched examples from training tools only.
4. Start with TF-IDF plus logistic regression or a linear SVM. Larger pretrained text models are experiments if they outperform this baseline, not prerequisites supplied by the literature.
5. Report fetch coverage, manually reviewed evidence usability, binary precision/recall/F1, category macro-F1/per-class support, and abstention coverage separately. Choose thresholds on validation data and do not count failed enrichment as non-AI.
6. Preserve the fixed 14-category project target and permit category abstention for ambiguous evidence. Research on multilabel sectors is not authorization to change the taxonomy.

**Decision recommendation:** runtime enrichment is a justified prototype direction; metadata-only sufficiency and catalog-to-website transfer remain experimental. Keep bounded fetching, SSRF/redirect validation for arbitrary inputs, provenance, and unresolved outcomes. This research does not modify the confirmed architecture document.

## Review and resources

Independent primary-source evidence review passed the three central model claims with qualifications: unspecified F1 averaging in Jagrič/Herman; separate balanced/unbalanced Homepage2Vec regimes; SoAC's internal sample-count inconsistency and different taxonomy. No production/source implementation changed, so code-review/complexity skills were not applicable. Scout reports and evidence review are temporary files under `/tmp/cyera-*.md`; this document retains the final synthesis and primary links.
