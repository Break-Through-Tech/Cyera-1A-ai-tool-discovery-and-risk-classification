#!/usr/bin/env python3
"""Render the finalized batch-02 data as a static, read-only review page."""
import html
import json
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent
DATA_PATH = RUN / "REVIEW_DATA.json"
OUTPUT_PATH = RUN / "review.html"
EXPECTED = {
    "descriptions": 20, "source_rows": 31, "ai": 8, "non_ai": 12,
    "trusted_negative_descriptions": 9, "trusted_negative_rows": 18,
    "binary_weak": 3, "subtype_weak": 3, "final_uncertain_cases": 6,
    "reconciled_cases": 7, "binary_agreement": 20,
}


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def text_list(values):
    return "".join(f'<li class="quote">{esc(value)}</li>' for value in (values or []))


def field(label, value):
    return f'<div><h4>{esc(label)}</h4><p>{esc(value) if value is not None else "Not applicable"}</p></div>'


def judgment(title, judgment):
    return (f'<section class="judgment"><h4>{esc(title)}</h4>'
            f'{field("Binary decision", judgment["ai_status"])}'
            f'{field("Binary evidence", judgment["evidence_strength"])}'
            f'{field("Binary forced", str(judgment["forced_decision"]).lower())}'
            f'{field("Binary rationale", judgment["rationale"])}'
            f'<h4>Exact binary evidence quotes</h4><ul>{text_list(judgment["evidence_spans"])}</ul>'
            f'{field("Subtype", judgment["ai_type"])}'
            f'{field("Subtype evidence", judgment["ai_type_evidence_strength"])}'
            f'{field("Subtype forced", str(judgment["ai_type_forced_decision"]).lower() if judgment["ai_type_forced_decision"] is not None else None)}'
            f'{field("Subtype rationale", judgment["ai_type_rationale"])}'
            f'<h4>Exact subtype evidence quotes</h4><ul>{text_list(judgment["ai_type_evidence_spans"])}</ul></section>')


def render_case(case):
    final = case["final"]
    weak_binary = final["evidence_strength"] == "weak"
    weak_subtype = final["ai_type"] is not None and final["ai_type_evidence_strength"] == "weak"
    uncertain = weak_binary or weak_subtype
    negative = final["ai_status"] == "non_ai" and not weak_binary
    ai = final["ai_status"] == "ai"
    if weak_binary:
        eligibility = "Excluded from trusted binary and negative pools (weak binary evidence)."
    elif negative:
        eligibility = "Eligible for the supported-negative pool."
    elif ai and weak_subtype:
        eligibility = "Not a negative candidate. Binary AI is supported; subtype excluded from trusted subtype pool."
    else:
        eligibility = "Not a negative candidate."
    rows = "".join(
        f'<li><span>Record {esc(row["source_record_number"])}</span>'
        f'<span class="provenance">{esc(row["product_name"])} · {esc(row["vendor_name"])}</span></li>'
        for row in case["source_rows"])
    final_panel = (f'<div class="final-grid"><div><span class="badge {"ai" if ai else "neutral"}">{"AI" if ai else "Non-AI"}</span>'
                   f'<span class="badge {"amber" if weak_binary else "teal" if negative else "neutral"}">{"Weak binary" if weak_binary else "Supported negative" if negative else "Supported binary"}</span>'
                   f'{field("Binary rationale", final["rationale"])}<h4>Exact binary evidence quotes</h4><ul>{text_list(final["evidence_spans"])}</ul></div>'
                   f'<div>{field("Subtype", final["ai_type"])}'
                   f'{field("Subtype strength", final["ai_type_evidence_strength"])}'
                   f'{field("Subtype forced", str(final["ai_type_forced_decision"]).lower() if final["ai_type_forced_decision"] is not None else None)}'
                   f'{field("Subtype rationale", final["ai_type_rationale"])}'
                   f'<h4>Exact subtype evidence quotes</h4><ul>{text_list(final["ai_type_evidence_spans"])}</ul></div></div>'
                   f'<p class="eligibility">{esc(eligibility)}</p>')
    compare = judgment("Labeler", case["labeler"]) + judgment("Blind", case["blind"])
    concern = ""
    if case["parent_concern"] or final.get("conflict_response"):
        concern = ('<details><summary>Why reconciled</summary>'
                   f'{field("Parent concern", case["parent_concern"])}'
                   f'{field("Final conflict response", final.get("conflict_response"))}</details>')
    repairs = ""
    if case["quote_repairs"]:
        items = "".join(f'<li>{field("Stage", repair["stage"])}{field("Raw quote", repair["raw_quote"])}'
                        f'{field("Original-text repaired span", repair["exact_source_span"])}</li>'
                        for repair in case["quote_repairs"])
        repairs = f'<details class="quote-audit"><summary>Quote repair audit · raw artifacts preserved</summary><ul>{items}</ul></details>'
    flags = "".join(f'<span class="badge amber">{label}</span>' for label, active in
                    (("Weak binary", weak_binary), ("Weak subtype", weak_subtype)) if active)
    return (f'<article class="case" id="{esc(case["annotation_id"])}" data-annotation-id="{esc(case["annotation_id"])}" '
            f'data-rows="{len(case["source_rows"])}" data-uncertain="{str(uncertain).lower()}" '
            f'data-reconciled="{str(case["reconciled"]).lower()}" data-negative="{str(negative).lower()}">'
            f'<header class="case-head"><div><h2>Record {esc(case["source_rows"][0]["source_record_number"])} · {esc(case["source_rows"][0]["product_name"])}</h2><code>{esc(case["annotation_id"])}</code></div>{flags}</header>'
            f'<div class="description">{esc(case["description"])}</div>'
            f'<details><summary>Source provenance · {len(case["source_rows"])} record reference(s)</summary><ul class="rows">{rows}</ul></details>'
            f'<section><h3>Final judgment</h3>{final_panel}</section>'
            f'<details><summary>Compare independent judgments</summary><div class="compare">{compare}</div></details>'
            f'{concern}{repairs}</article>')


def render(data):
    cases = "".join(render_case(case) for case in data["cases"])
    options = "".join(f'<option value="{key}">{label} ({count})</option>' for key, label, count in (
        ("all", "All cases", 20), ("uncertain", "Weak evidence", 6),
        ("reconciled", "Reconciled", 7), ("negative", "Supported negative", 9)))
    notes = "".join(f'<li>{esc(note)}</li>' for note in data["operational_notes"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Batch 2 · description review</title><style>
:root{{color-scheme:light;--ink:#172b40;--muted:#5d6d7e;--line:#dce4ec;--blue:#1769aa;--amber:#8a5700;--teal:#087e78}}
*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f8;color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1100px;margin:auto;padding:32px 24px 64px}}h1{{font-size:2rem;line-height:1.2;margin:.1em 0}}h2{{font-size:1.25rem;margin:0}}h3{{font-size:1.05rem;margin:20px 0 10px}}h4{{font-size:.88rem;margin:14px 0 4px;color:#354b60}}p{{margin:4px 0 10px;overflow-wrap:anywhere}}
.hero,.case{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:24px;box-shadow:0 2px 10px #17324a0a}}.hero{{margin-bottom:20px}}.status{{font-weight:700;color:#174f79;margin:10px 0 4px}}.scope,.note{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}}.metric{{padding:12px;background:#f5f8fb;border-radius:8px}}.metric strong{{display:block;font-size:1.2rem}}.filterbar{{display:flex;align-items:center;gap:12px;margin:20px 0}}select{{font:inherit;padding:8px 34px 8px 10px;border:1px solid #8798a9;border-radius:6px;background:white;color:var(--ink)}}:focus-visible{{outline:3px solid #1681d0;outline-offset:3px}}
.case{{margin:16px 0;padding:22px}}.case-head,.final-grid,.compare{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.case-head{{display:flex;align-items:center;justify-content:space-between}}.case-head>div{{min-width:0}}.case-head h2{{overflow-wrap:anywhere}}.quote-audit p{{white-space:pre-wrap}}code{{font-size:.8rem;color:var(--muted);overflow-wrap:anywhere}}.description{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fb;border-left:3px solid #aab9c8;padding:14px;margin:18px 0;unicode-bidi:plaintext}}.badge{{display:inline-block;border-radius:999px;padding:3px 10px;margin:0 6px 8px 0;font-weight:700;font-size:.82rem}}.badge.ai{{background:#e4f1fb;color:#145d92}}.badge.neutral{{background:#edf0f3;color:#455361}}.badge.amber{{background:#fff1d4;color:var(--amber)}}.badge.teal{{background:#dff4f1;color:#07655f}}.eligibility{{padding:10px 12px;border-radius:6px;background:#f5f8fb;font-weight:600}}
details{{border-top:1px solid var(--line);padding:12px 0;margin-top:10px}}summary{{cursor:pointer;font-weight:650}}summary:focus-visible{{border-radius:3px}}ul{{padding-left:22px}}.rows li{{margin:6px 0}}.provenance{{display:block;color:var(--muted);font-size:.92rem}}.quote{{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0;padding-left:3px}}.judgment{{padding:12px;background:#f8fafc;border-radius:8px;min-width:0}}.judgment p{{white-space:pre-wrap}}[hidden]{{display:none!important}}
@media(max-width:700px){{main{{padding:18px 12px 40px}}.hero,.case{{padding:17px}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.final-grid,.compare{{grid-template-columns:1fr;gap:8px}}.case-head{{align-items:flex-start;gap:10px;flex-wrap:wrap}}.filterbar{{align-items:flex-start;flex-direction:column}}select{{max-width:100%}}}}
@media print{{body{{background:white;font-size:11pt}}main{{max-width:none;padding:0}}.hero,.case{{box-shadow:none;break-inside:avoid;border-color:#aaa}}.filterbar{{display:none}}details>summary{{list-style:none}}details:not([open])>*:not(summary){{display:block}}a{{color:inherit}}}}
</style></head><body><main><section class="hero"><h1>Batch 2 · description review</h1>
<p class="status">Waiting for your review; no further batch will run</p><p class="scope">Description-based historical snapshot, not current product truth. Source names and vendors are provenance only, not labeling evidence. Agreement (20/20 binary) is not accuracy. Generic acceptance of weak cases cannot upgrade evidence.</p>
<div class="metrics"><div class="metric"><strong>20 descriptions / 31 source rows</strong>Batch scope</div><div class="metric"><strong>8 AI / 12 non-AI</strong>Final binary</div><div class="metric"><strong>9 descriptions / 18 row references</strong>Supported negatives</div><div class="metric"><strong>6 flagged</strong>3 weak binary + 3 weak subtype</div><div class="metric"><strong>7</strong>Reconciled cases</div><div class="metric"><strong>40 / 51</strong>Cumulative descriptions / rows</div><div class="metric"><strong>1,351</strong>Remainder still unapproved</div></div>
<details><summary>Operational notes</summary><ul>{notes}</ul></details></section>
<div class="filterbar"><label for="case-filter">Show cases</label><select id="case-filter">{options}</select><span id="filter-count" aria-live="polite">Showing 20 of 20 descriptions</span></div>
<section aria-label="Description cases">{cases}</section></main><script>
const filter=document.getElementById('case-filter'),cards=[...document.querySelectorAll('article.case')],count=document.getElementById('filter-count');
function update(){{const mode=filter.value;let shown=0,rows=0;for(const card of cards){{const match=mode==='all'||card.dataset[mode]==='true';card.hidden=!match;if(match){{shown++;rows+=Number(card.dataset.rows)}}}}count.textContent=`Showing ${{shown}} of ${{cards.length}} descriptions · ${{rows}} source rows`}}
filter.addEventListener('change',update);update();
</script></body></html>'''


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if (data["counts"] != EXPECTED or len(data["cases"]) != 20
            or sum(len(c["source_rows"]) for c in data["cases"]) != 31):
        raise ValueError("REVIEW_DATA counts do not match the approved batch-02 snapshot")
    OUTPUT_PATH.write_text(render(data), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
