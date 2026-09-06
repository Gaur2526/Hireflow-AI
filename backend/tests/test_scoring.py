"""Explainable fit scoring.

The contract recruiters rely on: the same profile always scores the same, the
score is bounded 0..100, and every deduction has a sentence attached to it.
"""

from __future__ import annotations

import pytest

from app.schemas.job import JobCriteria
from app.services.people_search.base import SourcedProfile
from app.services.scoring import WEIGHTS, score_profile

CRITERIA = JobCriteria(
    role_title="Senior Backend Engineer",
    titles=["Senior Backend Engineer", "Backend Engineer"],
    seniority=["senior"],
    must_have_skills=["Python", "PostgreSQL", "Kubernetes", "Kafka"],
    nice_to_have_skills=["Go", "Terraform"],
    min_years=5.0,
    max_years=9.0,
    locations=["Bengaluru"],
    countries=["IN"],
)


def profile(**kw) -> SourcedProfile:
    base = dict(
        full_name="Priya Iyer",
        title="Senior Backend Engineer",
        headline="Senior Backend Engineer at Razorpay",
        company="Razorpay",
        location="Bengaluru, Karnataka, India",
        country_code="IN",
        years_experience=7.0,
        seniority="senior",
        skills=["Python", "PostgreSQL", "Kubernetes", "Kafka", "Go", "Terraform"],
    )
    base.update(kw)
    return SourcedProfile(**base)


PERFECT = profile()


# ---------------------------------------------------------------------------
def test_perfect_candidate_scores_near_100() -> None:
    fit = score_profile(PERFECT, CRITERIA)
    assert fit.score >= 98.0
    assert fit.missing_must == []
    assert set(fit.matched_must) == set(CRITERIA.must_have_skills)
    assert set(fit.matched_nice) == set(CRITERIA.nice_to_have_skills)


def test_score_is_bounded_and_the_breakdown_adds_up() -> None:
    fit = score_profile(PERFECT, CRITERIA)
    assert 0.0 <= fit.score <= 100.0
    assert fit.score == pytest.approx(sum(fit.breakdown.values()), abs=1e-6)
    assert set(fit.breakdown) == set(WEIGHTS)
    for key, value in fit.breakdown.items():
        assert 0.0 <= value <= WEIGHTS[key] + 1e-9


def test_missing_every_must_have_scores_far_lower() -> None:
    weak = profile(
        skills=["Excel", "Salesforce"],
        title="Account Executive",
        headline="Account Executive at Zoho",
    )
    strong_fit = score_profile(PERFECT, CRITERIA)
    weak_fit = score_profile(weak, CRITERIA)

    assert weak_fit.missing_must == CRITERIA.must_have_skills
    assert weak_fit.breakdown["must_have_skills"] == 0.0
    # Losing all four must-haves costs the entire 40-point skills weight.
    assert strong_fit.score - weak_fit.score >= WEIGHTS["must_have_skills"]
    assert weak_fit.score < 50.0


def test_reasons_are_non_empty_and_name_the_missing_skills() -> None:
    partial = profile(skills=["Python", "PostgreSQL"])
    fit = score_profile(partial, CRITERIA)

    assert fit.reasons, "every score must be explainable"
    assert all(isinstance(r, str) and r.strip() for r in fit.reasons)

    missing_line = next(r for r in fit.reasons if r.startswith("Missing:"))
    assert "Kafka" in missing_line
    assert set(fit.missing_must) == {"Kubernetes", "Kafka"}
    assert fit.breakdown["must_have_skills"] == pytest.approx(
        WEIGHTS["must_have_skills"] * 0.5
    )


def test_a_substring_of_another_skill_is_not_a_match() -> None:
    """ "go" is inside "django": a fabricated match gets someone dialled."""
    criteria = JobCriteria(must_have_skills=["Go", "Kubernetes", "PostgreSQL"])
    candidate = profile(
        skills=["Django", "Python", "Kubernetes Operators", "PostgreSQL"],
        title="Backend Engineer",
        headline="Backend Engineer at Zerodha",
    )

    fit = score_profile(candidate, criteria)

    assert fit.missing_must == ["Go"]
    assert set(fit.matched_must) == {"Kubernetes", "PostgreSQL"}


# ---------------------------------------------------------------------------
# Experience band
# ---------------------------------------------------------------------------
def test_below_the_years_band_loses_experience_points_but_not_everything() -> None:
    junior = profile(years_experience=3.0)  # two years short of the 5-year floor
    fit = score_profile(junior, CRITERIA)
    reference = score_profile(PERFECT, CRITERIA)

    assert fit.breakdown["experience"] < reference.breakdown["experience"]
    assert fit.breakdown["experience"] > 0.0, "a near-miss keeps partial credit"
    # Everything else is untouched.
    for key in ("must_have_skills", "nice_to_have_skills", "title", "location"):
        assert fit.breakdown[key] == reference.breakdown[key]
    assert any("3 yrs experience vs 5+ required" in r for r in fit.reasons)


def test_far_below_the_band_keeps_almost_no_experience_credit() -> None:
    fit = score_profile(profile(years_experience=1.0), CRITERIA)
    assert fit.breakdown["experience"] == 0.0


def test_unknown_years_is_not_treated_as_a_failure() -> None:
    fit = score_profile(profile(years_experience=None), CRITERIA)
    assert fit.breakdown["experience"] == pytest.approx(WEIGHTS["experience"] * 0.5)
    assert any("verify on the call" in r for r in fit.reasons)


def test_overshooting_the_band_keeps_most_of_the_credit() -> None:
    fit = score_profile(profile(years_experience=14.0), CRITERIA)
    assert fit.breakdown["experience"] >= WEIGHTS["experience"] * 0.55
    assert fit.breakdown["experience"] < WEIGHTS["experience"]
    assert any("above the 9 yr band" in r for r in fit.reasons)


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def test_out_of_area_candidate_loses_the_location_points() -> None:
    away = profile(location="Berlin, Germany", country_code="DE")
    fit = score_profile(away, CRITERIA)
    reference = score_profile(PERFECT, CRITERIA)

    assert fit.breakdown["location"] == 0.0
    assert reference.breakdown["location"] == WEIGHTS["location"]
    assert fit.score == pytest.approx(reference.score - WEIGHTS["location"])
    assert any("outside the target area" in r for r in fit.reasons)


def test_in_country_different_city_keeps_partial_location_credit() -> None:
    fit = score_profile(
        profile(location="Hyderabad, Telangana, India", country_code="IN"), CRITERIA
    )
    assert 0.0 < fit.breakdown["location"] < WEIGHTS["location"]
    assert any("In-country (IN)" in r for r in fit.reasons)


def test_remote_role_never_penalises_location() -> None:
    remote = CRITERIA.model_copy(update={"locations": ["Remote"], "countries": []})
    fit = score_profile(profile(location="Berlin, Germany", country_code="DE"), remote)
    assert fit.breakdown["location"] == WEIGHTS["location"]


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
def test_off_target_title_costs_title_points() -> None:
    fit = score_profile(
        profile(title="Graphic Designer", headline="Graphic Designer at Zoho"),
        CRITERIA,
    )
    assert fit.breakdown["title"] < WEIGHTS["title"] * 0.5
    assert any("off-target" in r for r in fit.reasons)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "candidate",
    [
        PERFECT,
        profile(years_experience=2.0, skills=["Python"]),
        profile(location="London, UK", country_code="GB", skills=[]),
        profile(title=None, headline=None),
    ],
)
def test_scores_are_deterministic_across_runs(candidate: SourcedProfile) -> None:
    runs = [score_profile(candidate, CRITERIA) for _ in range(5)]
    first = runs[0].as_dict()
    for run in runs[1:]:
        assert run.as_dict() == first
        assert run.reasons == runs[0].reasons


@pytest.mark.parametrize(
    "candidate",
    [
        PERFECT,
        profile(years_experience=0.0, skills=[], title="", headline="", location=""),
        profile(years_experience=40.0, skills=["python"] * 20),
        profile(country_code=None, location=None),
    ],
)
def test_score_always_stays_within_0_100(candidate: SourcedProfile) -> None:
    fit = score_profile(candidate, CRITERIA)
    assert 0.0 <= fit.score <= 100.0
    assert 0.0 <= fit.as_dict()["score"] <= 100.0


def test_no_stated_requirements_does_not_punish_anyone() -> None:
    empty = JobCriteria(titles=["Backend Engineer"])
    fit = score_profile(profile(skills=[]), empty)
    assert fit.breakdown["must_have_skills"] > 0.0
    assert any("No must-have skills specified" in r for r in fit.reasons)
