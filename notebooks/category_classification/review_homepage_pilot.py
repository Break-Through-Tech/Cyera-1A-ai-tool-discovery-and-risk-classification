"""Reproduce Codex's evidence review of the immutable 30-attempt pilot."""
import hashlib
import importlib.metadata
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from finetuning.data import ROOT, MODEL, REVISION, load_data, reviewed_labels, sha256, write_json, normalized
from finetuning.homepages import training_homepages

OUT = ROOT / 'data/category_classification/homepage_training_v2/reviewed-2026-11-07-v1'
PILOT = OUT.parent / 'pilot-30'
BASE_LABELS = ROOT / 'notebooks/category_classification/reports/bge-reviewed-labels-2026-11-06/approved-training-labels.json'
RULE = 'primary-function-English-visible128-v1'
# Explicit decisions after reading title, metadata, headings, body and final URL.
# Approved excerpts are checked against the actual tokenizer offsets below.
DECISIONS = {
 'Fortellar | Cybersecurity Compliance Assessment': ('insufficient_evidence', None, "Assess your organization's compliance readiness", 'Compliance assessment is clear, but this capture does not establish AI functionality.'),
 'Gentrace': ('insufficient_evidence', None, 'Gentrace has shut down', 'Shutdown notice supplies no usable primary-function evidence.'),
 'Abridge': ('approved', None, 'Generative AI for Clinical Conversations', 'Clinical documentation is a healthcare-specific function.'),
 'TaroTap': ('insufficient_evidence', None, 'AI塔羅牌線上占卜', 'Predominantly Chinese capture is unsuitable for this English encoder supplement; no translation.'),
 'Gamma AI': ('approved', None, 'AI Powered Cloud DLP for SaaS', 'Data loss prevention and security awareness are primary functions.'),
 'bundleIQ': ('ambiguous_category', None, 'AI knowledge agent from bundleIQ', 'Cross-industry knowledge agent does not support Industry Specific; data analysis versus general assistance remains unresolved.'),
 'aijobs.com': ('insufficient_evidence', None, 'AI Job Board Built for AI Talent', 'AI is the subject of job listings; own AI functionality is not established.'),
 'Bexi.ai': ('approved', 'Media And Content Creation', 'Humanize AI Text', 'Primary function edits written content; evading detection does not make it a security detector.'),
 'Geleza': ('approved', None, 'AI Tools for Students', 'Purpose-built study toolkit, despite ancillary content and resume tools.'),
 'Mpilo': ('approved', None, 'Patient Notes with AI for Healthcare Professionals', 'Clinical documentation for healthcare professionals.'),
 'InJob.AI': ('approved', None, 'builds personalized cover letters', 'Individual job search and career assistance.'),
 'LearnGPT': ('wrong_product', None, 'Connect your apps. Then just ask.', 'Redirected iwantmy.ai assistant contains no LearnGPT continuity evidence.'),
 'Brella': ('ambiguous_category', None, 'Event platform', 'Business event management and lead generation conflict with Personal And Lifestyle; operations versus marketing boundary unresolved.'),
 'Dechecker AI': ('approved', None, 'AI Checker detects AI-generated text', 'Primary advertised function is AI-content authenticity detection.'),
 'Socratic Lab': ('wrong_product', None, 'PureSoft Labs', 'Company portfolio names other products, without evidence describing Socratic Lab.'),
 'Huntr': ('approved', None, 'organize your job search', 'Personal career workflow and resume assistance.'),
 'LearnQ': ('approved', None, 'data-driven learning methods', 'Personalized learning and study tools; primary educational function visible in metadata.'),
 'NSFW JS': ('approved', None, 'detects NSFW and nude images', 'Content moderation is the specific primary function, rather than generic developer tooling.'),
 'FloorDesign.ai': ('approved', 'Industry Specific', 'AI Floor Plan & Interior Design', 'Specific space planning and interior design function supports a vertical category rather than general image creation.'),
 'Databricks': ('approved', None, 'unified platform for data, analytics and AI', 'Data warehousing, ETL and analytics are explicit primary functions.'),
 'Atricent': ('approved', 'Personal And Lifestyle', 'Your Personal AI Stylist', 'Personal fashion styling and wardrobe assistance; not a profession-specific enterprise tool.'),
 'AI Pickup Lines Generator': ('approved', None, 'Generate Clever Pick Up Lines with AI', 'Relationship assistance is the specific primary function.'),
 'GPTZero': ('approved', None, 'AI detector', 'AI-content authenticity detection.'),
 'Learnrithm': ('approved', None, 'AI Homework Help, Study Tools & Test Prep', 'Tutoring, homework and test preparation.'),
 'Txt2SQL.com': ('wrong_product', None, 'Corgi SQL', 'Changed title and model-ranking metadata do not establish continuity with the catalog SQL generator.'),
}


def jsonl(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def main():
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, use_fast=True)
    splits, split_hashes = load_data()
    OUT.mkdir(parents=True, exist_ok=False)
    captures = [json.loads(line) for line in (PILOT / 'captures.jsonl').read_text(encoding='utf-8').strip().split('\n')]
    labels = json.loads(BASE_LABELS.read_text(encoding='utf-8'))
    labels.update(version='homepage-reviewed-2026-11-07-v1', provenance='Codex review of immutable pilot captures; retains prior two reviewed corrections. Rule: ' + RULE)
    reviews, pages = [], []
    now = datetime.now(timezone.utc).isoformat()
    for index, c in enumerate(captures):
        if c['outcome'] != 'extracted':
            status, proposed, excerpt, reason = 'fetch_failed', None, '', 'Acquisition outcome: ' + c['outcome']
        else:
            status, proposed, excerpt, reason = DECISIONS[c['name']]
        category = proposed or c['catalog_category']
        fields = {k: c.get(k) or '' for k in ('title', 'meta_description', 'body')}
        fields['headings'] = ' | '.join(c.get('headings') or [])
        text = ' '.join(fields[k] for k in ('title', 'meta_description', 'headings', 'body') if fields[k])
        # SentenceTransformer's Transformer.tokenize strips each input before encoding.
        prepared = text.strip()
        tokens = tokenizer(prepared, truncation=False)
        truncated = tokenizer(prepared, truncation=True, max_length=128, return_offsets_mapping=True)
        start = prepared.casefold().find(excerpt.casefold()) if excerpt else -1
        end = start + len(excerpt)
        visible_end = max((b for a, b in truncated['offset_mapping']), default=0)
        visible = start >= 0 and end <= visible_end
        if status == 'approved' and not visible:
            status = 'insufficient_evidence'
            reason += ' Supporting functional excerpt is absent from the actual 128-token input; separate preprocessing review required.'
        review = dict(tool_id=c['tool_id'], group_id=c['group_id'], name=c['name'], capture_index=index,
            capture_reference=str((PILOT / 'captures.jsonl').relative_to(ROOT)),
            capture_sha256=hashlib.sha256(json.dumps(c, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            requested_url=c['requested_url'], final_url=c.get('final_url'),
            identity_status='different_or_unverified_product' if status == 'wrong_product' else 'specific_product' if status == 'approved' else 'unresolved_or_unsuitable',
            original_category=c['catalog_category'], proposed_category=category, status=status,
            supporting_excerpt=excerpt, rationale=reason, reviewer='Codex (AI; not human approval)', reviewed_at=now,
            labeling_rule_version=RULE, training_text=text, token_count=len(tokens['input_ids']),
            excerpt_visible_at_128=visible, visible_character_end=visible_end,
            suitability='English encoder unsuitable' if c['name'] == 'TaroTap' else 'English' if status == 'approved' else 'not approved',
            preprocessing_review_required=start >= 0 and not visible)
        reviews.append(review)
        if status == 'approved':
            if category != c['catalog_category']:
                labels['labels'][c['tool_id']] = category
            pages.append(dict(host=c['host'], tool_ids=[c['tool_id']], category=category, catalog_split='train',
                requested_url=c['requested_url'], final_url=c['final_url'], review_tool_id=c['tool_id'],
                capture_sha256=review['capture_sha256'], **fields))
    write_json(OUT / 'reviewed-labels.json', labels)
    jsonl(OUT / 'reviews.jsonl', reviews)
    jsonl(OUT / 'pages.jsonl', pages)
    effective, label_provenance = reviewed_labels(splits['train'], OUT / 'reviewed-labels.json')
    counts = Counter(r['status'] for r in reviews)
    old_pages = [json.loads(line) for line in (ROOT / 'data/category_classification/transfer_v1/pages.jsonl').read_text(encoding='utf-8').strip().split('\n')]
    duplicate_audit = {}
    for key, getter in [('host', lambda p:p['host']), ('group', lambda p:tuple(sorted({r['group_id'] for r in splits['train'] if r['tool_id'] in p['tool_ids']}))), ('text', lambda p:normalized(' '.join(p[k] for k in ('title','meta_description','headings','body') if p[k])))]:
        values = Counter(getter(p) for p in old_pages if p['catalog_split'] == 'train')
        duplicate_audit[key] = {str(k):v for k,v in values.items() if v > 1}
    manifest = dict(version=1, capture_source=(PILOT / 'captures.jsonl').relative_to(ROOT).as_posix(),
        capture_sha256=sha256(PILOT / 'captures.jsonl'), seed=20261014, model=MODEL, revision=REVISION,
        tokenizer_revision=REVISION, max_length=128, text_preparation='title-meta-headings-body-space-join-v1; tokenizer strip',
        labeling_rule_version=RULE, review_counts=dict(counts), effective_labels=label_provenance,
        split_hashes=split_hashes, extractor_hashes=captures[0]['extractor_version'],
        source_hashes={p.name:sha256(p) for p in PILOT.iterdir() if p.is_file()},
        output_hashes={name:sha256(OUT / name) for name in ('pages.jsonl','reviews.jsonl','reviewed-labels.json')},
        packages={p:importlib.metadata.version(p) for p in ('torch','transformers','tokenizers','sentence-transformers')},
        approved_by_category=dict(Counter(p['category'] for p in pages)),
        existing_training_duplicate_audit=duplicate_audit,
        scope='New supplement only; existing pages not combined; AI evidence review, not human approval')
    write_json(OUT / 'manifest.json', manifest)
    training_homepages(effective, OUT / 'pages.jsonl')
    lines = ['# Homepage evidence review', '', 'Reviewer: Codex (AI). No human approval claimed.', '',
             f'{len(captures)} attempts; {len(pages)} approved distinct tools/groups.', '',
             'Outcomes: ' + json.dumps(dict(counts)), '',
             '| Tool | Original category | Reviewed category | Decision | Reason |', '|---|---|---|---|---|']
    lines += [f"| {r['name'].replace('|','/')} | {r['original_category']} | {r['proposed_category']} | {r['status']} | {r['rationale']} |" for r in reviews]
    lines += ['', 'Approved tools/groups per category: ' + json.dumps(manifest['approved_by_category']),
              '', 'Exact excerpts, capture references, texts, token counts and visibility checks: reviews.jsonl. Existing training duplicate audit: manifest.json.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(OUT), outcomes=dict(counts), approved=len(pages)), indent=2))


if __name__ == '__main__':
    main()
