"""Screening-plan design: questions -> result_schema -> agent script.

The most important assertion in this file is
:func:`test_prompt_placeholders_match_custom_variables_exactly`. Hunar derives
an agent's ``custom_variables`` from the ``{tokens}`` in ``agent_prompt`` plus
``introduction``, and then 422s every single call whose ``custom_data`` does not
carry all of them. A stray brace in the copy is therefore a production outage,
and this test is what stops one landing.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.schemas.job import JobCriteria, ScreeningQuestion
from app.services import screening
from app.services.screening import (
    BASELINE_QUESTIONS,
    CUSTOM_VARIABLES,
    SYSTEM_VARIABLES,
    _LLMQuestions,
    _sanitise,
    build_custom_data,
    build_plan,
    build_result_schema,
    design_screening_plan,
    extract_placeholders,
)

CRITERIA = JobCriteria(
    role_title="Senior Backend Engineer",
    titles=["Senior Backend Engineer"],
    seniority=["senior"],
    must_have_skills=["Python", "PostgreSQL", "Kubernetes"],
    nice_to_have_skills=["Kafka"],
    min_years=5.0,
    max_years=9.0,
    locations=["Bengaluru"],
    countries=["IN"],
    work_mode="hybrid",
    summary="Senior Backend Engineer. Targets 5+ years of experience.",
)

ROLE_QUESTIONS = [
    ScreeningQuestion(
        key="years_of_experience",
        question="How many years of hands-on backend experience do you have?",
        answer_type="number",
    ),
    ScreeningQuestion(
        key="python_depth",
        question="Tell me about your most recent Python project.",
        answer_type="string",
    ),
    ScreeningQuestion(
        key="on_call",
        question="Have you carried a production on-call pager?",
        answer_type="boolean",
    ),
    ScreeningQuestion(
        key="notice_band",
        question="How soon could you start?",
        answer_type="enum",
        options=["immediate", "30 days", "60 days", "90 days"],
    ),
]


# ---------------------------------------------------------------------------
# result_schema
# ---------------------------------------------------------------------------
def test_result_schema_has_one_key_per_question_plus_the_two_standard_keys() -> None:
    schema = build_result_schema(ROLE_QUESTIONS)

    assert list(schema) == [
        "years_of_experience",
        "python_depth",
        "on_call",
        "notice_band",
        "screening_summary",
        "recommended_next_step",
    ]
    assert len(schema) == len(ROLE_QUESTIONS) + 2


@pytest.mark.parametrize(
    ("key", "prefix"),
    [
        ("on_call", "boolean — "),
        ("years_of_experience", "number — "),
        ("python_depth", "string — "),
        ("notice_band", "string — one of: "),
    ],
)
def test_result_schema_prefix_matches_answer_type(key: str, prefix: str) -> None:
    assert build_result_schema(ROLE_QUESTIONS)[key].startswith(prefix)


def test_enum_schema_lists_the_options_and_the_question() -> None:
    spec = build_result_schema(ROLE_QUESTIONS)["notice_band"]
    assert spec.startswith("string — one of: immediate, 30 days, 60 days, 90 days.")
    assert "How soon could you start?" in spec


def test_enum_without_options_degrades_to_a_plain_string() -> None:
    q = ScreeningQuestion(key="mode", question="Onsite or remote?", answer_type="enum")
    assert build_result_schema([q])["mode"].startswith("string — Onsite or remote?")


def test_standard_keys_describe_the_summary_and_the_next_step() -> None:
    schema = build_result_schema(ROLE_QUESTIONS)
    assert schema["screening_summary"].startswith("string — ")
    assert schema["recommended_next_step"].startswith("string — one of: ")
    for step in (
        "schedule_interview",
        "recruiter_callback",
        "not_a_fit",
        "do_not_contact",
    ):
        assert step in schema["recommended_next_step"]


def test_every_question_key_survives_into_the_schema() -> None:
    plan = build_plan(CRITERIA, [*BASELINE_QUESTIONS, *ROLE_QUESTIONS])
    for question in plan.questions:
        assert question.key in plan.result_schema


# ---------------------------------------------------------------------------
# The Hunar 422 invariant
# ---------------------------------------------------------------------------
def test_prompt_placeholders_match_custom_variables_exactly() -> None:
    """{tokens} in the script == CUSTOM_VARIABLES == custom_data keys."""
    plan = build_plan(CRITERIA, [*BASELINE_QUESTIONS, *ROLE_QUESTIONS], company="Acme")
    custom_data = build_custom_data(
        job_title="Senior Backend Engineer", company="Acme", criteria=CRITERIA
    )

    placeholders = extract_placeholders(plan.agent_prompt, plan.introduction)

    assert placeholders == set(CUSTOM_VARIABLES) == set(custom_data)


def test_extract_placeholders_excludes_hunar_system_variables() -> None:
    text = "Hi {callee_name}, this is {persona_name} at {current_time}: {job_title}."
    assert extract_placeholders(text) == {"job_title"}
    # Every system variable is filtered, and none of them leaks into custom_data.
    assert not SYSTEM_VARIABLES & set(CUSTOM_VARIABLES)


def test_introduction_only_uses_callee_name_and_declared_variables() -> None:
    plan = build_plan(CRITERIA, list(BASELINE_QUESTIONS))
    raw = set(extract_placeholders(plan.introduction)) | SYSTEM_VARIABLES
    assert "callee_name" in plan.introduction
    assert extract_placeholders(plan.introduction) <= set(CUSTOM_VARIABLES)
    assert raw >= {"callee_name"}


def test_custom_data_values_are_non_empty_strings() -> None:
    data = build_custom_data(job_title="", company=None, criteria=JobCriteria())
    assert set(data) == set(CUSTOM_VARIABLES)
    assert data["job_title"] == "the open role"
    assert data["company"] == "our client"
    assert all(isinstance(v, str) for v in data.values())


def test_custom_data_is_truncated_for_hunar() -> None:
    fat = JobCriteria(
        summary="x" * 2000,
        must_have_skills=[f"Skill{i}" for i in range(50)],
        min_years=5.0,
    )
    data = build_custom_data(job_title="y" * 500, company="z" * 500, criteria=fat)
    assert len(data["job_title"]) <= 120
    assert len(data["company"]) <= 120
    assert len(data["jd_summary"]) <= 600
    assert len(data["key_requirements"]) <= 600
    assert data["key_requirements"].startswith("5+ years experience;")


def test_role_specific_questions_never_introduce_new_placeholders() -> None:
    """An operator-authored question with a stray brace must be caught."""
    risky = ScreeningQuestion(
        key="stray", question="Do you know {some_framework}?", answer_type="string"
    )
    plan = build_plan(CRITERIA, [*BASELINE_QUESTIONS, risky])
    unknown = extract_placeholders(plan.agent_prompt, plan.introduction) - set(
        CUSTOM_VARIABLES
    )
    assert unknown == {"some_framework"}, (
        "this is exactly the case create_campaign must reject before launch"
    )


# ---------------------------------------------------------------------------
# Baseline questions
# ---------------------------------------------------------------------------
BASELINE_ORDER = [
    "consent_to_continue",
    "open_to_opportunity",
    "current_role",
    "notice_period",
    "best_time_to_talk",
    "do_not_contact_requested",
]


async def test_baseline_questions_are_always_present_and_in_order() -> None:
    plan, designed_by = await design_screening_plan(
        CRITERIA, llm=_StubLLM(configured=False)
    )
    keys = [q.key for q in plan.questions]

    assert designed_by == "heuristic"
    assert [k for k in keys if k in BASELINE_ORDER] == BASELINE_ORDER
    # Consent is asked first; the compliance flag is captured last.
    assert keys[0] == "consent_to_continue"
    assert keys[-1] == "do_not_contact_requested"
    # Role-specific questions sit between current_role and notice_period.
    assert keys.index("current_role") < keys.index("years_of_experience")
    assert keys.index("years_of_experience") < keys.index("notice_period")


async def test_heuristic_questions_probe_the_top_must_have_skill() -> None:
    plan, _ = await design_screening_plan(CRITERIA, llm=_StubLLM(configured=False))
    keys = [q.key for q in plan.questions]
    assert "python_depth" in keys, "the first must-have becomes the depth question"
    assert "location_fit" in keys
    assert "secondary_skills_confirmed" in keys


async def test_plan_objective_names_the_role() -> None:
    plan, _ = await design_screening_plan(CRITERIA, llm=_StubLLM(configured=False))
    assert "Senior Backend Engineer" in plan.objective
    assert len(plan.objective) <= 500


# ---------------------------------------------------------------------------
# LLM path sanitisation
# ---------------------------------------------------------------------------
class _StubLLM:
    """Stands in for :class:`app.services.llm.LLMClient` - never hits the API."""

    def __init__(self, *, configured: bool = True, questions: list[Any] | None = None):
        self.configured = configured
        self._questions = questions or []
        self.calls = 0

    async def structured(self, **_: Any) -> _LLMQuestions:
        self.calls += 1
        return _LLMQuestions(questions=list(self._questions), objective="stub")


DISCRIMINATORY = [
    ScreeningQuestion(key="age_check", question="How old are you?"),
    ScreeningQuestion(key="family", question="Are you married or planning children?"),
    ScreeningQuestion(key="faith", question="What religion do you practise?"),
    ScreeningQuestion(key="caste_q", question="Which caste do you belong to?"),
    ScreeningQuestion(key="gender_q", question="What gender do you identify as?"),
    ScreeningQuestion(key="health_q", question="Do you have any health conditions?"),
    ScreeningQuestion(key="origin", question="What is your nationality?"),
]


@pytest.mark.parametrize("question", DISCRIMINATORY, ids=lambda q: q.key)
def test_sanitise_drops_discriminatory_questions(question: ScreeningQuestion) -> None:
    keep = ScreeningQuestion(key="scale", question="What throughput did you handle?")
    assert [q.key for q in _sanitise([question, keep])] == ["scale"]


def test_sanitise_drops_baseline_overlaps_duplicates_and_blanks() -> None:
    questions = [
        ScreeningQuestion(key="consent_to_continue", question="Do you consent?"),
        ScreeningQuestion(key="scale", question="What throughput did you handle?"),
        ScreeningQuestion(key="scale", question="Duplicate key, different wording?"),
        ScreeningQuestion(key="blank", question="   "),
    ]
    assert [q.key for q in _sanitise(questions)] == ["scale"]


def test_sanitise_caps_the_call_at_five_role_questions() -> None:
    many = [
        ScreeningQuestion(key=f"q_{i}", question=f"Question number {i}?")
        for i in range(12)
    ]
    assert len(_sanitise(many)) == 5


async def test_llm_questions_are_sanitised_before_they_reach_the_plan() -> None:
    stub = _StubLLM(
        questions=[
            ScreeningQuestion(key="age_check", question="How old are you?"),
            ScreeningQuestion(
                key="scale",
                question="What is the largest throughput you have handled?",
                answer_type="string",
            ),
        ]
    )
    plan, designed_by = await design_screening_plan(CRITERIA, llm=stub)
    keys = [q.key for q in plan.questions]

    assert stub.calls == 1
    assert designed_by == "llm"
    assert "age_check" not in keys
    assert "scale" in keys
    # Baseline scaffolding survives the LLM path untouched.
    assert [k for k in keys if k in BASELINE_ORDER] == BASELINE_ORDER
    assert "age_check" not in plan.result_schema
    assert "scale" in plan.result_schema


async def test_all_llm_questions_dropped_falls_back_to_the_heuristic() -> None:
    stub = _StubLLM(questions=list(DISCRIMINATORY))
    plan, designed_by = await design_screening_plan(CRITERIA, llm=stub)

    assert designed_by == "heuristic", "nothing usable came back, so do not claim llm"
    assert "python_depth" in [q.key for q in plan.questions]
    assert not any(q.key in {d.key for d in DISCRIMINATORY} for q in plan.questions)


async def test_llm_failure_degrades_to_the_heuristic_plan() -> None:
    class _Broken(_StubLLM):
        async def structured(self, **_: Any) -> _LLMQuestions:
            from app.services.llm import LLMUnavailable

            raise LLMUnavailable("Anthropic rejected the API key")

    plan, designed_by = await design_screening_plan(CRITERIA, llm=_Broken())
    assert designed_by == "heuristic"
    assert [q.key for q in plan.questions if q.key in BASELINE_ORDER] == BASELINE_ORDER


# ---------------------------------------------------------------------------
def test_agent_prompt_carries_the_compliance_rules() -> None:
    plan = build_plan(CRITERIA, [*BASELINE_QUESTIONS, *ROLE_QUESTIONS])
    prompt = plan.agent_prompt
    assert "CONSENT COMES FIRST" in prompt
    # Role questions are numbered after the two spoken baseline openers.
    assert "3. How many years of hands-on backend experience do you have?" in prompt
    assert "Never ask about age, marital status, religion" in prompt
    # Baseline questions are not duplicated in the numbered list.
    assert prompt.count("What is your current role and company?") == 1


def test_screening_module_declares_no_secrets() -> None:
    assert screening.CUSTOM_VARIABLES == [
        "job_title",
        "company",
        "jd_summary",
        "key_requirements",
    ]


@pytest.mark.parametrize(
    "question",
    [
        "Which programming languages do you use day to day?",
        "How large a team have you managed?",
        "What was the average package size you shipped?",
        "Have you worked on a staged rollout before?",
        "How do you manage on-call coverage?",
    ],
)
def test_sanitise_does_not_over_block_legitimate_questions(question: str) -> None:
    """ "language", "managed", "package" all contain the substring "age"."""
    q = ScreeningQuestion(key="legit", question=question)
    assert [x.key for x in _sanitise([q])] == ["legit"]


def test_location_question_reads_naturally_without_a_work_mode() -> None:
    """The agent speaks this aloud - it must not read out a placeholder."""
    from app.schemas.job import JobCriteria
    from app.services.screening import _heuristic_questions

    with_mode = _heuristic_questions(
        JobCriteria(
            role_title="Backend Engineer", locations=["Bengaluru"], work_mode="hybrid"
        )
    )
    without_mode = _heuristic_questions(
        JobCriteria(role_title="Backend Engineer", locations=["Bengaluru"])
    )

    spoken = {q.key: q.question for q in with_mode + without_mode}
    assert (
        spoken["location_fit"]
        == "This role is based in Bengaluru. Does that work for you?"
    )

    hybrid = next(q for q in with_mode if q.key == "location_fit")
    assert hybrid.question == (
        "This role is based in Bengaluru and is hybrid. Does that work for you?"
    )
    assert "the role's" not in hybrid.question
