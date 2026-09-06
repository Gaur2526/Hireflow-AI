"""The deterministic job-description parser.

These are pure-function tests: no key, no network, no database. The heuristic
path is the one that has to work when ``ANTHROPIC_API_KEY`` is absent, so it is
the one worth pinning down.
"""

from __future__ import annotations

import pytest

from app.services.jd_parser import (
    _extract_years,
    extract_criteria_heuristically,
    match_skills,
    parse_job_description,
)
from app.services.llm import LLMClient

RICH_JD = """\
Role: Senior Backend Engineer — Payments (Bengaluru)

About the role
We process a few million transactions a day. We rebuilt the ledger 2 years ago
and now need someone to own it.

Responsibilities
- Own the Observability stack: dashboards, alerting and on-call rotation
- Partner with product on the roadmap

Requirements
- 5-9 years building production backend services
- Deep Python experience and strong PostgreSQL fundamentals
- Kubernetes in production

Nice to have
- Kafka or other event streaming
- Go for tooling

This is a hybrid, full-time role based in Bengaluru.
Compensation: ₹45,00,000 per annum.
"""


@pytest.fixture(scope="module")
def rich() -> object:
    return extract_criteria_heuristically(RICH_JD)


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
def test_title_from_labelled_line(rich) -> None:
    # "Role: X — Y (Z)" keeps the role, drops the parenthetical and the dash tail.
    assert rich.role_title == "Senior Backend Engineer"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Job Title: Staff Data Engineer", "Staff Data Engineer"),
        ("Position - Product Manager", "Product Manager"),
        ("Designation: QA Engineer", "QA Engineer"),
    ],
)
def test_title_from_other_labels(line: str, expected: str) -> None:
    criteria = extract_criteria_heuristically(f"{line}\n\nWe are hiring.\n")
    assert criteria.role_title == expected


def test_title_from_bare_first_line() -> None:
    """No label: a short, heading-shaped first line is the title."""
    criteria = extract_criteria_heuristically(
        "# Machine Learning Engineer\n\nRequirements\n- PyTorch\n"
    )
    assert criteria.role_title == "Machine Learning Engineer"


def test_title_falls_back_when_first_line_is_prose() -> None:
    jd = (
        "We are a fast-growing fintech looking for great people to join our "
        "platform team in Pune.\n"
    )
    assert extract_criteria_heuristically(jd).role_title == "Open Role"


def test_title_hint_wins_over_the_document() -> None:
    criteria = extract_criteria_heuristically(RICH_JD, title_hint="Backend Engineer II")
    assert criteria.role_title == "Backend Engineer II"
    assert criteria.titles[0] == "Backend Engineer II"


# ---------------------------------------------------------------------------
# Years
# ---------------------------------------------------------------------------
def test_years_range(rich) -> None:
    assert (rich.min_years, rich.max_years) == (5.0, 9.0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("we need 5-9 years of experience", (5.0, 9.0)),
        ("5 to 9 years in backend", (5.0, 9.0)),
        ("9-5 years (typo, normalised)", (5.0, 9.0)),
        ("5+ years of python", (5.0, None)),
        ("minimum 3 years of experience", (3.0, None)),
        ("min. 3 years of experience", (3.0, None)),
        ("at least 4 yrs of relevant work", (4.0, None)),
        ("no experience requirement stated", (None, None)),
    ],
)
def test_years_variants(text: str, expected: tuple[float | None, float | None]) -> None:
    assert _extract_years(text) == expected


def test_years_ago_is_not_an_experience_requirement() -> None:
    """ "2 years ago" is a date, not a requirement - it must not win."""
    assert _extract_years("we launched the product 2 years ago") == (None, None)

    text = "we launched 2 years ago. minimum 4 years of experience required."
    assert _extract_years(text) == (4.0, None)


def test_rich_jd_ignores_the_2_years_ago_sentence(rich) -> None:
    assert rich.min_years == 5.0


def test_a_stated_minimum_beats_a_stray_year_count_in_the_company_blurb() -> None:
    """ "8+ years" is the requirement; "in the last 2 years" is marketing."""
    text = (
        "requirements: 8+ years of professional backend experience. "
        "about us: we have grown 10x in the last 2 years and shipped our "
        "platform in 3 years flat."
    )
    assert _extract_years(text) == (8.0, None)


# ---------------------------------------------------------------------------
# Skills: must vs nice, and ordering
# ---------------------------------------------------------------------------
def test_must_have_and_nice_to_have_split_by_heading(rich) -> None:
    assert {"Python", "PostgreSQL", "Kubernetes"} <= set(rich.must_have_skills)
    assert {"Kafka", "Go"} <= set(rich.nice_to_have_skills)
    # A nice-to-have never doubles as a must-have.
    assert not set(rich.must_have_skills) & set(rich.nice_to_have_skills)


def test_requirements_outrank_responsibilities(rich) -> None:
    """Observability appears *earlier* in the document, under Responsibilities.

    Python appears later, under Requirements. Section rank has to beat document
    order, because the top must-have becomes the skill the voice agent probes.
    """
    must = rich.must_have_skills
    assert "Observability" in must, "responsibilities still contribute skills"
    assert must.index("Python") < must.index("Observability")
    assert must[0] == "Python"


def test_match_skills_uses_canonical_names() -> None:
    """Aliases map to one canonical spelling so the vendor query is stable."""
    assert set(match_skills("we use k8s and postgres with golang")) == {
        "Go",
        "PostgreSQL",
        "Kubernetes",
    }


def test_match_skills_respects_word_boundaries() -> None:
    # "js" inside "jsonb" must not register as JavaScript.
    assert "JavaScript" not in match_skills("we store jsonb documents")
    assert "Go" not in match_skills("a good golfer joins the going concern")


def test_short_aliases_do_not_leak_across_hyphens_and_ampersands() -> None:
    """A PM job description is not a Go/R job description."""
    assert "Go" not in match_skills("own the go-to-market plan for new features")
    assert "R" not in match_skills("work closely with R&D teams")


def test_a_bullet_mentioning_skills_does_not_reopen_the_must_have_section() -> None:
    """Only a heading may switch sections - see _looks_like_heading."""
    jd = """\
Role: Backend Engineer

Requirements
- 6+ years of Python and PostgreSQL

Nice to have
- Excellent written communication skills
- Exposure to Kafka and Terraform
- Familiarity with Kubernetes
"""
    criteria = extract_criteria_heuristically(jd)

    assert {"Kafka", "Terraform", "Kubernetes"} <= set(criteria.nice_to_have_skills)
    assert not {"Kafka", "Terraform", "Kubernetes"} & set(criteria.must_have_skills)


# ---------------------------------------------------------------------------
# Seniority
# ---------------------------------------------------------------------------
def test_seniority_comes_from_the_title_not_the_body() -> None:
    jd = """\
Role: Senior Backend Engineer

Responsibilities
- Mentor two junior engineers and run the intern programme
"""
    criteria = extract_criteria_heuristically(jd)
    assert criteria.seniority == ["senior"]
    assert "entry" not in criteria.seniority


def test_seniority_falls_back_to_the_body_when_the_title_is_neutral() -> None:
    criteria = extract_criteria_heuristically(
        "Role: Backend Engineer\n\nThis is an entry level position for a fresher.\n"
    )
    assert "entry" in criteria.seniority


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Staff Data Engineer", "manager"),
        ("Director of Engineering", "director"),
        ("VP of Product", "vp"),
        ("Chief Technology Officer", "cxo"),
    ],
)
def test_seniority_bands_from_title(title: str, expected: str) -> None:
    criteria = extract_criteria_heuristically(f"Role: {title}\n\nWe are hiring.\n")
    assert expected in criteria.seniority


# ---------------------------------------------------------------------------
# Location / countries / comp / work mode
# ---------------------------------------------------------------------------
def test_location_and_country_codes(rich) -> None:
    assert rich.locations == ["Bengaluru"]
    assert rich.countries == ["IN"]


@pytest.mark.parametrize(
    ("city", "code"),
    [("London", "GB"), ("San Francisco", "US"), ("Riyadh", "SA"), ("Dubai", "AE")],
)
def test_country_code_per_city(city: str, code: str) -> None:
    criteria = extract_criteria_heuristically(
        f"Role: Backend Engineer\n\nBased in {city}.\n"
    )
    assert criteria.locations == [city]
    assert criteria.countries == [code]


def test_remote_role_with_no_city() -> None:
    criteria = extract_criteria_heuristically(
        "Role: Backend Engineer\n\nThis is a fully remote position.\n"
    )
    assert criteria.locations == ["Remote"]
    assert criteria.work_mode == "remote"


def test_compensation_and_work_mode(rich) -> None:
    assert rich.compensation == "₹45,00,000 per annum"
    assert rich.work_mode == "hybrid"
    assert rich.employment_type == "Full-time"


def test_dollar_band_compensation() -> None:
    criteria = extract_criteria_heuristically(
        "Role: Backend Engineer\n\nComp: $180,000 - $220,000 per year.\n"
    )
    assert criteria.compensation is not None
    assert "180,000" in criteria.compensation


def test_summary_mentions_the_role_and_the_stack(rich) -> None:
    assert rich.summary.startswith("Senior Backend Engineer.")
    assert "Python" in rich.summary
    assert len(rich.summary) <= 400


# ---------------------------------------------------------------------------
# The async entry point with no LLM key
# ---------------------------------------------------------------------------
async def test_parse_job_description_without_a_key_uses_the_heuristic() -> None:
    criteria, parsed_by, warnings = await parse_job_description(
        RICH_JD, llm=LLMClient(api_key="")
    )
    assert parsed_by == "heuristic"
    assert any("ANTHROPIC_API_KEY" in w for w in warnings)
    assert criteria.role_title == "Senior Backend Engineer"
    assert criteria.min_years == 5.0


async def test_parse_empty_description() -> None:
    criteria, parsed_by, warnings = await parse_job_description(
        "   ", llm=LLMClient(api_key="")
    )
    assert parsed_by == "heuristic"
    assert warnings == ["Empty job description."]
    assert criteria.role_title == ""


def test_parser_is_deterministic() -> None:
    a = extract_criteria_heuristically(RICH_JD).model_dump()
    b = extract_criteria_heuristically(RICH_JD).model_dump()
    assert a == b
