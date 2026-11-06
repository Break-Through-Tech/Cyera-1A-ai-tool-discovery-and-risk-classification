import pytest
from pydantic import TypeAdapter, ValidationError

from app.assistant.contracts import (
    AggregateEvidence,
    EventTimeRange,
    ExecutionStep,
    FactualClaim,
    Finding,
    GroundedAnswer,
    PassageEvidence,
    PinnedScope,
    RecordEvidence,
    RunReference,
    ScopeFilters,
    ToolFailure,
    ToolLimitation,
    ToolOutcome,
    ToolSuccess,
    validate_answer_references,
)


def scope(**changes):
    return PinnedScope(
        **{
            "runs": (RunReference(batch_id="batch_1", run_id="run_1"),),
            "event_time": EventTimeRange(
                start="2026-10-01T00:00:00Z", end="2026-11-01T00:00:00Z"
            ),
            **changes,
        }
    )


def record(**changes):
    return RecordEvidence(
        **{
            "evidence_id": "ev_1",
            "run": RunReference(batch_id="batch_1", run_id="run_1"),
            "record_type": "activity_event",
            "record_id": "event_1",
            **changes,
        }
    )


def answer(**changes):
    return GroundedAnswer(
        **{
            "scope": scope(),
            "findings": (
                Finding(
                    facts=(FactualClaim(text="One observed event.", evidence_ids=("ev_1",)),),
                    interpretation="Review whether approval is needed.",
                    limitations=("Activity does not establish sensitive-data submission.",),
                    advisory_next_steps=("Check the recorded approval context.",),
                ),
            ),
            "stop_reason": "sufficient_evidence",
            **changes,
        }
    )


def step(outcome):
    return ExecutionStep(
        step_id="step_1",
        sequence=1,
        tool="summarize_usage",
        scope=scope(),
        arguments={},
        started_at="2026-11-05T10:00:00Z",
        completed_at="2026-11-05T10:00:01Z",
        outcome=outcome,
    )


def test_answer_and_receipt_round_trip_without_losing_provenance():
    receipt = step(
        ToolSuccess(
            outcome="data", summary="One event.", data={"event_count": 1},
            evidence=(record(),),
        )
    )
    restored = ExecutionStep.model_validate_json(receipt.model_dump_json())
    restored_answer = GroundedAnswer.model_validate_json(answer().model_dump_json())

    assert restored == receipt
    assert restored_answer == answer()
    assert restored.outcome.evidence[0].run == restored.scope.runs[0]
    validate_answer_references(restored_answer, restored.outcome.evidence)


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-10-01T00:00:00", "2026-11-01T00:00:00Z"),
        ("2026-10-01T00:00:00+02:00", "2026-11-01T00:00:00Z"),
        ("2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"),
        ("2026-12-01T00:00:00Z", "2026-11-01T00:00:00Z"),
    ],
)
def test_event_scope_rejects_ambiguous_or_invalid_intervals(start, end):
    with pytest.raises(ValidationError):
        EventTimeRange(start=start, end=end)


def test_scope_rejects_multiple_runs_for_one_batch():
    with pytest.raises(ValidationError, match="one Run"):
        scope(runs=(
            RunReference(batch_id="batch_1", run_id="run_1"),
            RunReference(batch_id="batch_1", run_id="run_2"),
        ))


def test_scope_rejects_a_run_assigned_to_two_batches():
    with pytest.raises(ValidationError, match="repeat a Run"):
        scope(runs=(
            RunReference(batch_id="batch_1", run_id="run_1"),
            RunReference(batch_id="batch_2", run_id="run_1"),
        ))


def test_unknown_fields_and_unsupported_filters_are_not_silently_dropped():
    with pytest.raises(ValidationError):
        ScopeFilters(departmnt="Finance")
    with pytest.raises(ValidationError):
        ScopeFilters(risk_tiers=("Critical",))
    with pytest.raises(ValidationError):
        scope(runs=())


@pytest.mark.parametrize(
    "outcome",
    [
        ToolSuccess(outcome="data", summary="Found records.", data={"event_count": 1}),
        ToolSuccess(outcome="no_matches", summary="No records in scope.", data={}),
        ToolLimitation(reason="unavailable", message="Retrieval is not connected."),
        ToolLimitation(reason="unsupported", message="This grouping is unsupported."),
        ToolLimitation(reason="clarification_required", message="Which department?"),
        ToolFailure(code="retrieval_failed", message="Retrieval failed; retry."),
    ],
)
def test_outcomes_remain_distinguishable_after_serialization(outcome):
    adapter = TypeAdapter(ToolOutcome)
    assert adapter.validate_json(adapter.dump_json(outcome)) == outcome
    assert ExecutionStep.model_validate_json(step(outcome).model_dump_json()).outcome == outcome


def test_failure_cannot_masquerade_as_a_success_with_partial_data():
    with pytest.raises(ValidationError):
        TypeAdapter(ToolOutcome).validate_python({
            "status": "failed", "code": "database_failed", "message": "Retry.",
            "data": {"partial_count": 3},
        })


def test_truncation_requires_disclosure():
    with pytest.raises(ValidationError, match="limitations"):
        ToolSuccess(outcome="data", summary="Preview.", data={}, truncated=True)
    result = ToolSuccess(
        outcome="data", summary="Preview.", data={}, truncated=True,
        qualifications=("Only the first 10 groups are shown.",), continuation="page_2",
    )
    assert result.truncated and result.continuation == "page_2"


def test_receipts_reject_reversed_execution_times_and_unknown_tools():
    payload = step(ToolFailure(code="failed", message="Retry.")).model_dump()
    with pytest.raises(ValidationError, match="Completion"):
        ExecutionStep.model_validate({**payload, "completed_at": "2026-11-04T00:00:00Z"})
    with pytest.raises(ValidationError):
        ExecutionStep.model_validate({**payload, "tool": "execute_sql"})


def test_budget_stop_requires_unfinished_work_disclosure():
    with pytest.raises(ValidationError, match="unfinished"):
        answer(stop_reason="budget_reached")
    result = answer(stop_reason="budget_reached", unfinished_work=("Period comparison.",))
    assert result.unfinished_work == ("Period comparison.",)


def test_facts_require_citations_and_nonempty_text():
    with pytest.raises(ValidationError):
        FactualClaim(text="Unsupported claim.", evidence_ids=())
    with pytest.raises(ValidationError):
        FactualClaim(text="  ", evidence_ids=("ev_1",))


def test_unknown_or_duplicate_citations_are_rejected():
    with pytest.raises(ValueError, match="Unknown evidence"):
        validate_answer_references(answer(), ())
    with pytest.raises(ValueError, match="unique"):
        validate_answer_references(answer(), (record(), record()))


def test_same_event_id_from_another_batch_cannot_support_this_scope():
    with pytest.raises(ValueError, match="outside"):
        validate_answer_references(answer(), (record(
            run=RunReference(batch_id="batch_2", run_id="run_2")
        ),))


def test_a_newer_run_cannot_silently_replace_a_historical_reference():
    with pytest.raises(ValueError, match="outside"):
        validate_answer_references(answer(), (record(
            run=RunReference(batch_id="batch_1", run_id="run_2")
        ),))


def test_aggregate_citations_preserve_query_metrics_and_drilldown():
    aggregate = AggregateEvidence(
        evidence_id="ev_1", scope=scope(), operation="summarize_usage",
        query={"metric": "event_count", "group_by": []},
        metric_definitions=("Count supplied Activity Events without deduplication.",),
        drilldown_reference="query_1",
    )
    validate_answer_references(answer(), (aggregate,))
    narrower = scope(filters=ScopeFilters(departments=("Finance",)))
    with pytest.raises(ValueError, match="match the answer scope"):
        validate_answer_references(answer(scope=narrower), (aggregate,))


def test_passage_evidence_keeps_source_role_and_version_without_implying_org_policy():
    passage = PassageEvidence(
        evidence_id="ev_1", corpus_version="corpus-v1", document_id="guidance_1",
        document_version="2026-10", passage_id="p1", source_role="general_guidance",
        excerpt="Review organizational approval requirements.",
    )
    validate_answer_references(answer(), (passage,))
    assert passage.source_role == "general_guidance"


def test_schema_checks_do_not_claim_to_verify_semantic_support():
    unsupported = answer(findings=(Finding(
        facts=(FactualClaim(text="Sensitive content was submitted.", evidence_ids=("ev_1",)),),
        interpretation="This assertion needs separate support evaluation.",
    ),))
    # Reference membership can pass even when the cited event does not support the claim.
    validate_answer_references(unsupported, (record(),))
