"""Generate the reproducible synthetic enterprise activity fixture."""

import argparse
import csv
import hashlib
import io
import json
import math
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ACTIVITY_PATH = ROOT / "activity.csv"
EXPECTED_PATH = ROOT / "evaluation_only" / "expected_scenarios.csv"
CONTRACT_PATH = ROOT / "evaluation_only" / "partition_contract.json"
SEED = 20261014
EMPLOYEE_COUNT = 72
START_DATE = date(2026, 9, 15)
END_DATE = date(2026, 10, 14)

DEPARTMENTS = (
    ("Engineering", 0.24),
    ("Sales", 0.15),
    ("Finance", 0.12),
    ("Marketing", 0.12),
    ("Support", 0.10),
    ("IT", 0.09),
    ("Research", 0.07),
    ("Operations", 0.06),
    ("Product", 0.05),
)

ROLES = {
    "Engineering": (("Software Engineer", 0.65), ("Data Engineer", 0.20), ("Engineering Manager", 0.15)),
    "Sales": (("Account Executive", 0.65), ("Sales Operations Analyst", 0.20), ("Sales Manager", 0.15)),
    "Finance": (("Financial Analyst", 0.55), ("Accountant", 0.30), ("Finance Manager", 0.15)),
    "Marketing": (("Marketing Specialist", 0.60), ("Campaign Analyst", 0.25), ("Marketing Manager", 0.15)),
    "Support": (("Support Specialist", 0.65), ("Customer Success Representative", 0.20), ("Support Manager", 0.15)),
    "IT": (("IT Administrator", 0.50), ("Systems Engineer", 0.30), ("Security Analyst", 0.20)),
    "Research": (("Research Analyst", 0.45), ("Data Scientist", 0.40), ("Research Manager", 0.15)),
    "Operations": (("Operations Analyst", 0.60), ("Program Manager", 0.25), ("Operations Manager", 0.15)),
    "Product": (("Product Manager", 0.50), ("Product Designer", 0.25), ("UX Researcher", 0.25)),
}

SCENARIOS = (
    {
        "scenario_id": "scenario_01", "department": "Engineering", "application_name": "ChatGPT",
        "domain": "chatgpt.com", "event_type": "app_open", "usage_purpose": "code_assistance",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.72, "mean_events": 4.8,
        "expected": ("known_catalog_ai", "aitoolbuzz:2c1fde4c873a82ca00d999e553012213c67abe8463e0f2947bb10598c555a3cd",
                     "known_tool", "ai", "Communication And Support", "Lower", "false",
                     "aitoolbuzz_catalog_snapshot_and_synthetic_risk_facts"),
    },
    {
        "scenario_id": "scenario_02", "department": "Finance", "application_name": "ChatGPT",
        "domain": "chatgpt.com", "event_type": "app_open", "usage_purpose": "draft_summary",
        "data_sensitivity_tier": "confidential", "adoption_probability": 0.42, "mean_events": 3.2,
        "expected": ("known_catalog_ai", "aitoolbuzz:2c1fde4c873a82ca00d999e553012213c67abe8463e0f2947bb10598c555a3cd",
                     "known_tool", "ai", "Communication And Support", "Lower", "false",
                     "aitoolbuzz_catalog_snapshot_and_synthetic_risk_facts"),
    },
    {
        "scenario_id": "scenario_03", "department": "Engineering", "application_name": "Cursor",
        "domain": "cursor.so", "event_type": "app_open", "usage_purpose": "software_development",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.56, "mean_events": 4.2,
        "expected": ("known_catalog_ai", "aitoolbuzz:598c6b12630af5f5f3987ddd91ca8c207b19f8f6be4fd10af4489bc8c79b149c",
                     "known_tool", "ai", "Technology And Development", "Medium", "true",
                     "aitoolbuzz_catalog_snapshot_and_synthetic_risk_facts"),
    },
    {
        "scenario_id": "scenario_04", "department": "Sales", "application_name": "Slack",
        "domain": "slack.com", "event_type": "app_open", "usage_purpose": "team_messaging",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.78, "mean_events": 6.2,
        "expected": ("reviewed_non_ai_control", "enterprise-row:96", "observed_tool", "non_ai",
                     "inapplicable", "not_applicable", "not_applicable", "reviewed_description_label_non_ai"),
    },
    {
        "scenario_id": "scenario_12", "department": "Support", "application_name": "Slack",
        "domain": "slack.com", "event_type": "app_open", "usage_purpose": "team_messaging",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.66, "mean_events": 4.8,
        "expected": ("reviewed_non_ai_control", "enterprise-row:96", "observed_tool", "non_ai",
                     "inapplicable", "not_applicable", "not_applicable", "reviewed_description_label_non_ai"),
    },
    {
        "scenario_id": "scenario_05", "department": "IT", "application_name": "Mattermost",
        "domain": "mattermost.com", "event_type": "app_open", "usage_purpose": "team_messaging",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.58, "mean_events": 4.1,
        "expected": ("reviewed_non_ai_control", "enterprise-row:79", "observed_tool", "non_ai",
                     "inapplicable", "not_applicable", "not_applicable", "reviewed_description_label_non_ai"),
    },
    {
        "scenario_id": "scenario_06", "department": "Marketing", "application_name": "MeetOscar",
        "domain": "meetoscar.com", "event_type": "browser_visit", "usage_purpose": "email_campaigns",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.44, "mean_events": 3.1,
        "expected": ("catalog_held_out_ai", "aitoolbuzz:227949d3a6ca2fc955ca573c724b1f93a59a41832a1778524d85b2a0d4b98cf9",
                     "observed_tool", "ai", "Marketing And Sales", "High", "true",
                     "aitoolbuzz_test_label_and_synthetic_risk_facts"),
    },
    {
        "scenario_id": "scenario_07", "department": "Engineering", "application_name": "Magic Inspector",
        "domain": "magicinspector.com", "event_type": "browser_visit", "usage_purpose": "visual_testing",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.24, "mean_events": 2.5,
        "expected": ("catalog_held_out_ai", "aitoolbuzz:eae7b946239074e028ddaec2c04a8fcab433fabbab5d951046213b91de76b8d8",
                     "observed_tool", "ai", "Technology And Development", "Lower", "false",
                     "aitoolbuzz_test_label_and_synthetic_risk_facts"),
    },
    {
        "scenario_id": "scenario_08", "department": "Research", "application_name": "Amazon Comprehend",
        "domain": "aws.amazon.com", "event_type": "app_open", "usage_purpose": "text_analysis",
        "data_sensitivity_tier": "confidential", "adoption_probability": 0.38, "mean_events": 2.8,
        "expected": ("reviewed_out_of_catalog_ai", "enterprise-row:46", "observed_tool", "ai",
                     "Data And Analytics", "Medium", "false",
                     "reviewed_binary_ai_label_and_fixture_category_mapping"),
    },
    {
        "scenario_id": "scenario_09", "department": "Sales", "application_name": "Playbooks",
        "domain": "insidesales.com", "event_type": "browser_visit", "usage_purpose": "sales_outreach",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.36, "mean_events": 2.8,
        "expected": ("reviewed_out_of_catalog_ai", "enterprise-row:112", "observed_tool", "ai",
                     "Marketing And Sales", "High", "true",
                     "reviewed_binary_ai_label_and_fixture_category_mapping"),
    },
    {
        "scenario_id": "scenario_10", "department": "Operations", "application_name": "Workbench",
        "domain": "workbench.example", "event_type": "browser_visit", "usage_purpose": "unknown",
        "data_sensitivity_tier": "unknown", "adoption_probability": 0.20, "mean_events": 1.8,
        "expected": ("insufficient_evidence", "unresolved", "unresolved_candidate", "unresolved",
                     "inapplicable", "not_assessed_ai_unresolved", "not_applicable",
                     "no_metadata_and_reserved_example_domain"),
    },
    {
        "scenario_id": "scenario_11", "department": "Product", "application_name": "Open Canvas AI",
        "domain": "open-canvas-ai.example", "event_type": "app_open", "usage_purpose": "product_ideation",
        "data_sensitivity_tier": "internal", "adoption_probability": 0.24, "mean_events": 2.0,
        "expected": ("fictional_reviewed_ai", "synthetic-tool:open-canvas-ai", "observed_tool", "ai",
                     "unresolved", "unresolved", "true",
                     "fictional_ai_functionality_with_ambiguous_category_and_unknown_risk_facts"),
    },
)

ACTIVITY_FIELDS = (
    "event_id", "timestamp", "employee_id", "department", "job_role", "application_name",
    "domain", "event_type", "usage_purpose", "data_sensitivity_tier",
)
EXPECTED_FIELDS = (
    "scenario_id", "event_ids", "cohort", "expected_tool_identity", "expected_identity_outcome",
    "expected_ai_status", "expected_category", "expected_risk_behavior",
    "expected_investigation_flag", "label_basis",
)


def weighted_choice(rng, choices):
    values, weights = zip(*choices)
    return rng.choices(values, weights=weights, k=1)[0]


def poisson(rng, rate):
    threshold = math.exp(-rate)
    count = 0
    product = 1.0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def negative_binomial_count(rng, mean, shape=2.0):
    rate = rng.gammavariate(shape, mean / shape)
    return min(20, max(1, poisson(rng, rate)))


def make_employees(rng):
    departments = [department for department, _ in DEPARTMENTS]
    employees = []
    for index in range(EMPLOYEE_COUNT):
        if index < len(departments) * 2:
            department = departments[index // 2]
        else:
            department = weighted_choice(rng, DEPARTMENTS)
        role = weighted_choice(rng, ROLES[department])
        employees.append({
            "employee_id": f"emp_{index + 1:03d}",
            "department": department,
            "job_role": role,
        })
    return employees


def make_timestamp(rng):
    dates = []
    current = START_DATE
    while current <= END_DATE:
        weekday_weight = 0.18 if current.weekday() < 5 else 0.05
        dates.append((current, weekday_weight))
        current += timedelta(days=1)
    event_date = weighted_choice(rng, dates)
    period = weighted_choice(rng, (("business", 0.72), ("shoulder", 0.20), ("after_hours", 0.08)))
    if period == "business":
        hour = rng.randint(8, 17)
    elif period == "shoulder":
        hour = weighted_choice(rng, ((7, 0.2), (18, 0.4), (19, 0.3), (20, 0.1)))
    else:
        hour = rng.randint(20, 23)
    return datetime.combine(event_date, time(hour, rng.randrange(60)), tzinfo=timezone.utc)


def generate_rows():
    rng = random.Random(SEED)
    employees = make_employees(rng)
    employees_by_department = {}
    for employee in employees:
        employees_by_department.setdefault(employee["department"], []).append(employee)

    events = []
    for scenario in SCENARIOS:
        eligible = employees_by_department[scenario["department"]]
        active = [
            employee for employee in eligible
            if rng.random() < scenario["adoption_probability"]
        ]
        while len(active) < 2:
            remaining = [employee for employee in eligible if employee not in active]
            active.append(rng.choice(remaining))

        for employee in active:
            event_count = negative_binomial_count(rng, scenario["mean_events"])
            for _ in range(event_count):
                event_type = weighted_choice(
                    rng, ((scenario["event_type"], 0.72),
                          ("browser_visit" if scenario["event_type"] == "app_open" else "app_open", 0.28))
                )
                events.append({
                    "scenario_id": scenario["scenario_id"],
                    "timestamp": make_timestamp(rng),
                    "employee_id": employee["employee_id"],
                    "department": employee["department"],
                    "job_role": employee["job_role"],
                    "application_name": scenario["application_name"],
                    "domain": scenario["domain"],
                    "event_type": event_type,
                    "usage_purpose": scenario["usage_purpose"],
                    "data_sensitivity_tier": scenario["data_sensitivity_tier"],
                })

    events.sort(key=lambda event: (
        event["timestamp"], event["employee_id"], event["application_name"], event["event_type"]
    ))
    rows = []
    event_ids_by_scenario = {scenario["scenario_id"]: [] for scenario in SCENARIOS}
    for index, event in enumerate(events, 1):
        event_id = f"evt_{index:06d}"
        event_ids_by_scenario[event["scenario_id"]].append(event_id)
        rows.append({
            "event_id": event_id,
            "timestamp": event["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            **{field: event[field] for field in ACTIVITY_FIELDS if field not in {"event_id", "timestamp"}},
        })

    if any(not event_ids_by_scenario[scenario["scenario_id"]] for scenario in SCENARIOS):
        raise ValueError("generated activity failed required scenario coverage")
    return rows, event_ids_by_scenario


def make_expected_rows(event_ids_by_scenario):
    rows = []
    for scenario in SCENARIOS:
        (cohort, identity, identity_outcome, ai_status, category, risk_behavior,
         investigation_flag, label_basis) = scenario["expected"]
        rows.append({
            "scenario_id": scenario["scenario_id"],
            "event_ids": "|".join(event_ids_by_scenario[scenario["scenario_id"]]),
            "cohort": cohort,
            "expected_tool_identity": identity,
            "expected_identity_outcome": identity_outcome,
            "expected_ai_status": ai_status,
            "expected_category": category,
            "expected_risk_behavior": risk_behavior,
            "expected_investigation_flag": investigation_flag,
            "label_basis": label_basis,
        })
    return rows


def validate_fixture(rows, event_ids_by_scenario):
    event_ids = [row["event_id"] for row in rows]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("generated event IDs are not unique")
    expected_ids = {scenario["scenario_id"] for scenario in SCENARIOS}
    if set(event_ids_by_scenario) != expected_ids:
        raise ValueError("generated scenario set differs from the required fixture scenarios")

    events_by_id = {row["event_id"]: row for row in rows}
    for scenario in SCENARIOS:
        scenario_events = [
            events_by_id[event_id] for event_id in event_ids_by_scenario[scenario["scenario_id"]]
        ]
        if len({row["employee_id"] for row in scenario_events}) < 2:
            raise ValueError(f"{scenario['scenario_id']} has fewer than two active employees")
        if any(
            row["application_name"] != scenario["application_name"]
            or row["department"] != scenario["department"]
            for row in scenario_events
        ):
            raise ValueError(f"{scenario['scenario_id']} contains an unexpected activity context")

    cohorts = {scenario["expected"][0] for scenario in SCENARIOS}
    required_cohorts = {
        "known_catalog_ai", "catalog_held_out_ai", "reviewed_out_of_catalog_ai",
        "reviewed_non_ai_control", "insufficient_evidence", "fictional_reviewed_ai",
    }
    if not required_cohorts.issubset(cohorts):
        raise ValueError("generated fixture is missing a required evaluation cohort")
    risk_outcomes = {scenario["expected"][5] for scenario in SCENARIOS}
    if not {"High", "Medium", "Lower", "unresolved"}.issubset(risk_outcomes):
        raise ValueError("generated fixture is missing a required risk outcome")


def render_csv(rows, fields):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def output_bytes():
    activity_rows, event_ids_by_scenario = generate_rows()
    validate_fixture(activity_rows, event_ids_by_scenario)
    expected_rows = make_expected_rows(event_ids_by_scenario)
    activity_bytes = render_csv(activity_rows, ACTIVITY_FIELDS)
    expected_bytes = render_csv(expected_rows, EXPECTED_FIELDS)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["input_files"]["activity.csv"] = hashlib.sha256(activity_bytes).hexdigest()
    contract["hidden_expected_answers_sha256"] = hashlib.sha256(expected_bytes).hexdigest()
    contract_bytes = (json.dumps(contract, indent=2) + "\n").encode("utf-8")
    return activity_bytes, expected_bytes, contract_bytes, len(activity_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the fixture files")
    mode.add_argument("--check", action="store_true", help="verify checked-in files match the seeded output")
    args = parser.parse_args()

    outputs = output_bytes()
    files = (
        (ACTIVITY_PATH, outputs[0]),
        (EXPECTED_PATH, outputs[1]),
        (CONTRACT_PATH, outputs[2]),
    )
    if args.check:
        mismatches = [str(path) for path, content in files if not path.exists() or path.read_bytes() != content]
        if mismatches:
            raise SystemExit("Generated fixture differs from checked-in files: " + ", ".join(mismatches))
        print(f"PASS: seeded fixture is reproducible ({outputs[3]} activity events).")
        return

    for path, content in files:
        path.write_bytes(content)
    print(f"Wrote seeded fixture with {outputs[3]} activity events.")


if __name__ == "__main__":
    main()
