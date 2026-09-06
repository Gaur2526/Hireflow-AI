"""Turn hiring criteria into a configured Hunar voice-screening agent.

This is the bridge between "here is a job description" and "here is an AI voice
agent that can screen for it". It produces:

* the screening questions the agent must get answered,
* the ``result_schema`` those answers land in (which becomes the dashboard's
  answer columns), and
* the prompt / introduction / objective text posted to ``POST /agents/``.

Hunar templates variables with single braces - ``{callee_name}`` is built in and
any other ``{placeholder}`` becomes a declared custom variable that every call
must supply via ``custom_data``.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.schemas.job import JobCriteria, ScreeningPlan, ScreeningQuestion
from app.services.llm import LLMClient, LLMUnavailable, get_llm

log = get_logger(__name__)

# Variables interpolated into the agent prompt. Every one of these must be
# present in each call's custom_data, or Hunar will render the literal brace.
CUSTOM_VARIABLES = ["job_title", "company", "jd_summary", "key_requirements"]

#: Hunar substitutes these itself and excludes them from ``custom_variables``.
#: Any *other* {token} in the prompt or introduction becomes a required custom
#: variable - so a stray brace used for emphasis silently breaks every call.
SYSTEM_VARIABLES = {
    "callee_name",
    "persona_name",
    "mobile_number",
    "greeting",
    "current_time",
}

# Answers we always collect, on top of the role-specific questions. These drive
# the funnel columns in the dashboard and the compliance signals.
BASELINE_QUESTIONS: list[ScreeningQuestion] = [
    ScreeningQuestion(
        key="consent_to_continue",
        question="After the AI disclosure, did the candidate agree to continue?",
        answer_type="boolean",
        rationale="Consent gate - nothing else is asked without it.",
    ),
    ScreeningQuestion(
        key="open_to_opportunity",
        question="Are you open to hearing about this role right now?",
        answer_type="boolean",
        rationale="Qualifies interest before spending recruiter time.",
    ),
    ScreeningQuestion(
        key="current_role",
        question="What is your current role and company?",
        answer_type="string",
        rationale="Confirms the sourced profile is current.",
    ),
    ScreeningQuestion(
        key="notice_period",
        question="If things move forward, what notice period would you need to serve?",
        answer_type="string",
        rationale="Determines start-date feasibility.",
    ),
    ScreeningQuestion(
        key="best_time_to_talk",
        question="When would be a good time for a human recruiter to call you back?",
        answer_type="string",
        rationale="Hand-off logistics.",
    ),
    ScreeningQuestion(
        key="do_not_contact_requested",
        question="Did the candidate ask not to be contacted again?",
        answer_type="boolean",
        rationale="Compliance signal - suppresses future outreach.",
    ),
]

_BASELINE_KEYS = {q.key for q in BASELINE_QUESTIONS}


class _LLMQuestions(BaseModel):
    """What we ask Claude for - deliberately narrow."""

    questions: list[ScreeningQuestion] = Field(default_factory=list)
    objective: str = ""


QUESTION_SYSTEM = """You design phone-screening questions for an AI voice \
recruiter. The call lasts under three minutes, so every question must earn its \
place.

Produce 3-5 role-specific questions that a candidate can answer out loud in one \
or two sentences and that a recruiter would genuinely use to decide whether to \
book a human interview. Verify the requirements that actually differentiate \
candidates - depth in the core stack, scale/ownership, and any hard constraint \
in the JD.

Rules:
- Do NOT include: consent, interest, current role, notice period, callback time, \
or do-not-contact. Those are asked separately.
- Do NOT ask about salary unless the job description explicitly names a budget.
- `key` is snake_case and becomes a column in a results table.
- `question` is the exact wording the voice agent will speak - conversational, \
one sentence, no compound questions.
- `answer_type`: "number" for years/counts, "boolean" for strict yes/no, \
"enum" with `options` for a small fixed set, otherwise "string".
- `rationale` names the JD requirement being verified.
- Never ask anything that would be discriminatory (age, marital status, \
religion, caste, gender, health, pregnancy, national origin)."""


async def design_screening_plan(
    criteria: JobCriteria,
    *,
    description: str = "",
    company: str | None = None,
    llm: LLMClient | None = None,
) -> tuple[ScreeningPlan, str]:
    """Return ``(plan, designed_by)`` where designed_by is 'llm' or 'heuristic'."""
    client = llm or get_llm()
    designed_by = "heuristic"
    role_questions = _heuristic_questions(criteria)

    if client.configured:
        try:
            result = await client.structured(
                system=QUESTION_SYSTEM,
                prompt=_question_prompt(criteria, description),
                output_model=_LLMQuestions,
                effort="medium",
            )
            cleaned = _sanitise(result.questions)
            if cleaned:
                role_questions = cleaned
                designed_by = "llm"
        except LLMUnavailable as exc:
            log.warning("screening.llm_failed", reason=str(exc))

    questions = _merge_questions(role_questions)
    plan = build_plan(criteria, questions, company=company)
    return plan, designed_by


def build_plan(
    criteria: JobCriteria,
    questions: list[ScreeningQuestion],
    *,
    company: str | None = None,
) -> ScreeningPlan:
    """Assemble the full Hunar agent configuration from a question list."""
    role_title = criteria.role_title or "the open role"
    objective = (
        f"Confirm interest and screen {role_title} candidates against the must-have "
        "requirements, then capture a callback time for a human recruiter."
    )[:500]

    return ScreeningPlan(
        questions=questions,
        objective=objective,
        introduction=_introduction(),
        agent_prompt=_agent_prompt(questions),
        result_prompt=_result_prompt(questions),
        result_schema=build_result_schema(questions),
    )


def build_result_schema(questions: list[ScreeningQuestion]) -> dict[str, str]:
    """Hunar's ``result_schema``: ``{key: "<type> - <description>"}``.

    Those keys come back on every completed call as ``result``, which is exactly
    what the dashboard renders.
    """
    schema: dict[str, str] = {}
    for q in questions:
        if q.answer_type == "enum" and q.options:
            options = ", ".join(o.strip() for o in q.options if o.strip())
            schema[q.key] = f"string — one of: {options}. {q.question}"
        elif q.answer_type == "boolean":
            schema[q.key] = f"boolean — {q.question}"
        elif q.answer_type == "number":
            schema[q.key] = f"number — {q.question} Use null if not stated."
        else:
            schema[q.key] = f"string — {q.question} Use 'unknown' if not stated."
    schema["screening_summary"] = (
        "string — two sentences summarising what the candidate actually said, "
        "quoting their own words where possible"
    )
    schema["recommended_next_step"] = (
        "string — one of: schedule_interview, recruiter_callback, "
        "not_a_fit, do_not_contact"
    )
    return schema


def _introduction() -> str:
    return (
        "Hi {callee_name}, this is an AI voice assistant calling on behalf of the "
        "{company} talent team about a {job_title} opening. Your profile came up in "
        "a professional-data search. Is it alright if I take two minutes of your time?"
    )


def _agent_prompt(questions: list[ScreeningQuestion]) -> str:
    role_questions = [q for q in questions if q.key not in _BASELINE_KEYS]
    numbered = "\n".join(f"{i}. {q.question}" for i, q in enumerate(role_questions, 1))
    return f"""You are an AI voice assistant screening candidates for the \
{{job_title}} role at {{company}}.

ROLE CONTEXT
{{jd_summary}}

MUST-HAVE REQUIREMENTS
{{key_requirements}}

CONSENT COMES FIRST. Your opening must disclose three things: that you are an AI \
assistant, which company you represent, and that their details came from a \
professional-data search. Then ask permission to continue.
- If they decline, hesitate, or say it is a bad time: thank them warmly, tell \
them they will not be contacted again, and END THE CALL. Do not pitch. Do not \
ask a single follow-up question.
- If they ask to be removed or not called again, confirm you have noted it and \
end the call.

ONLY with clear permission, work through these questions in order, one at a \
time. Keep the whole call under three minutes.
1. Are you open to hearing about this role right now?
2. What is your current role and company?
{_indent_numbered(numbered, start=3)}
{len(role_questions) + 3}. If things move forward, what notice period would you need to serve?
{len(role_questions) + 4}. When would be a good time for a human recruiter to call you back?

STYLE
- One question at a time. Wait for the answer. Acknowledge briefly, then move on.
- Conversational and warm, never salesy. Never pressure, never repeat the pitch \
after a no.
- If they give a partial answer, ask at most one short follow-up, then move on.
- If they ask something you do not know (exact salary, team details, interview \
process), say a human recruiter will cover it on the callback.
- Never promise compensation, an interview, or an offer.
- Never ask about age, marital status, religion, caste, gender, health, \
pregnancy or national origin. If the candidate volunteers any of it, do not \
record it and do not follow up on it.

Close by thanking them by name and confirming the callback time."""


def _indent_numbered(block: str, start: int) -> str:
    lines = [ln for ln in block.splitlines() if ln.strip()]
    out = []
    for offset, line in enumerate(lines):
        out.append(re.sub(r"^\d+\.", f"{start + offset}.", line))
    return "\n".join(out)


def _result_prompt(questions: list[ScreeningQuestion]) -> str:
    return (
        "Extract only what the candidate actually said. Use null for anything they "
        "did not clearly state - never infer, guess, or fill in a plausible value. "
        "Set `consent_to_continue` to false if they did not clearly agree to "
        "continue after the AI disclosure. Set `do_not_contact_requested` to true "
        "if they asked in any form not to be contacted again - this is a compliance "
        "signal, so err toward true when it is ambiguous. Set "
        "`recommended_next_step` to do_not_contact whenever that flag is true. "
        "Quote the candidate's own words in `screening_summary`."
    )


# ---------------------------------------------------------------------------
def _question_prompt(criteria: JobCriteria, description: str) -> str:
    parts = [
        f"Role: {criteria.role_title or 'unspecified'}",
        f"Seniority: {', '.join(criteria.seniority) or 'unspecified'}",
        f"Experience band: {_years_label(criteria)}",
        f"Must-have skills: {', '.join(criteria.must_have_skills) or 'unspecified'}",
        f"Nice-to-have skills: {', '.join(criteria.nice_to_have_skills) or 'none'}",
        f"Locations: {', '.join(criteria.locations) or 'unspecified'}",
        f"Work mode: {criteria.work_mode or 'unspecified'}",
    ]
    body = "\n".join(parts)
    jd = (description or "").strip()[:8000]
    return f"PARSED CRITERIA\n{body}\n\nORIGINAL JOB DESCRIPTION\n---\n{jd}\n---"


def _years_label(criteria: JobCriteria) -> str:
    if criteria.min_years and criteria.max_years:
        return f"{criteria.min_years:g}-{criteria.max_years:g} years"
    if criteria.min_years:
        return f"{criteria.min_years:g}+ years"
    return "unspecified"


#: Protected characteristics an AI screener must never ask about. Matched on
#: word boundaries, not raw substrings: bare ``"age" in question`` both misses
#: "How old are you?" and wrongly drops "Which languages do you use?".
_BANNED_TOPICS = re.compile(
    r"\b(?:"
    r"age|aged|ages|how old|date of birth|dob|birth\s?year"
    r"|marital|married|spouse|husband|wife|children|kids|pregnan\w*"
    r"|religion|religious|caste"
    r"|gender|sexual orientation"
    r"|disab\w*|health|medical|illness"
    r"|nationality|national origin|race|ethnic\w*|visa status|citizenship"
    r")\b",
    re.I,
)


def _sanitise(questions: list[ScreeningQuestion]) -> list[ScreeningQuestion]:
    """Drop duplicates, baseline overlaps, and anything off-limits."""
    out: list[ScreeningQuestion] = []
    seen: set[str] = set()
    for q in questions:
        if q.key in _BASELINE_KEYS or q.key in seen:
            continue
        if _BANNED_TOPICS.search(q.question):
            log.warning("screening.dropped_question", key=q.key)
            continue
        if not q.question.strip():
            continue
        seen.add(q.key)
        out.append(q)
    return out[:5]


def _merge_questions(
    role_questions: list[ScreeningQuestion],
) -> list[ScreeningQuestion]:
    """Baseline questions first, role-specific ones in the middle."""
    by_key = {q.key: q for q in BASELINE_QUESTIONS}
    ordered = [
        by_key["consent_to_continue"],
        by_key["open_to_opportunity"],
        by_key["current_role"],
        *role_questions,
        by_key["notice_period"],
        by_key["best_time_to_talk"],
        by_key["do_not_contact_requested"],
    ]
    return ordered


def _heuristic_questions(criteria: JobCriteria) -> list[ScreeningQuestion]:
    """Deterministic fallback: probe the top must-have skills and the years band."""
    questions: list[ScreeningQuestion] = []
    skills = criteria.must_have_skills[:3]

    if criteria.min_years:
        questions.append(
            ScreeningQuestion(
                key="years_of_experience",
                question=(
                    "How many years of hands-on professional experience do you have "
                    f"as {_article(criteria.role_title)}?"
                ),
                answer_type="number",
                rationale=f"JD requires {_years_label(criteria)}.",
            )
        )
    if skills:
        primary = skills[0]
        questions.append(
            ScreeningQuestion(
                key=_skill_key(primary, "depth"),
                question=(
                    f"Could you tell me about the most recent project where you used "
                    f"{primary}, and what your specific role was?"
                ),
                answer_type="string",
                rationale=f"Verifies depth in must-have skill: {primary}.",
            )
        )
    if len(skills) > 1:
        rest = ", ".join(skills[1:])
        questions.append(
            ScreeningQuestion(
                key="secondary_skills_confirmed",
                question=f"Which of these have you worked with in production: {rest}?",
                answer_type="string",
                rationale=f"Confirms remaining must-have skills: {rest}.",
            )
        )
    if criteria.locations:
        loc = criteria.locations[0]
        # The agent speaks this sentence aloud, so drop the clause entirely
        # rather than reading out a placeholder when the JD omits work mode.
        mode = f" and is {criteria.work_mode}" if criteria.work_mode else ""
        questions.append(
            ScreeningQuestion(
                key="location_fit",
                question=f"This role is based in {loc}{mode}. Does that work for you?",
                answer_type="boolean",
                rationale=(
                    f"JD location constraint: {loc}"
                    + (f" ({criteria.work_mode})." if criteria.work_mode else ".")
                ),
            )
        )
    if not questions:
        questions.append(
            ScreeningQuestion(
                key="relevant_experience",
                question=(
                    "Could you walk me through your most relevant experience for this role?"
                ),
                answer_type="string",
                rationale="No specific requirements were extractable from the JD.",
            )
        )
    return questions[:5]


def _article(role_title: str) -> str:
    """ "a Senior Backend Engineer" / "an Android Developer" / "an engineer"."""
    role = (role_title or "").strip()
    if not role:
        return "an engineer in this kind of role"
    return f"{'an' if role[0].lower() in 'aeiou' else 'a'} {role}"


def _skill_key(skill: str, suffix: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in skill.lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"{slug.strip('_')}_{suffix}"[:48]


def build_custom_data(
    *,
    job_title: str,
    company: str | None,
    criteria: JobCriteria,
) -> dict[str, str]:
    """The ``custom_data`` payload every call in this campaign must carry.

    Keys map 1:1 to :data:`CUSTOM_VARIABLES`; a missing one would leave a literal
    ``{placeholder}`` in what the agent says.
    """
    requirements = criteria.must_have_skills[:8]
    req_text = "; ".join(requirements) if requirements else "See role context."
    if criteria.min_years:
        req_text = f"{_years_label(criteria)} experience; {req_text}"

    return {
        "job_title": (job_title or criteria.role_title or "the open role")[:120],
        "company": (company or "our client")[:120],
        "jd_summary": (criteria.summary or job_title or "")[:600],
        "key_requirements": req_text[:600],
    }


def extract_placeholders(*texts: str) -> set[str]:
    """Placeholders Hunar will treat as custom variables."""
    found: set[str] = set()
    for text in texts:
        found.update(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text or ""))
    # Hunar injects these itself; everything else must come from custom_data.
    return found - SYSTEM_VARIABLES
