"""Explainable candidate <-> job fit scoring.

Deliberately deterministic: recruiters need to know *why* someone ranked where
they did, and the ranking must not change between page loads. Every dimension
contributes a bounded number of points and a human-readable reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.job import JobCriteria
from app.services.people_search.base import SourcedProfile

WEIGHTS = {
    "must_have_skills": 40.0,
    "experience": 25.0,
    "title": 20.0,
    "location": 10.0,
    "nice_to_have_skills": 5.0,
}


@dataclass
class FitScore:
    score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    matched_must: list[str] = field(default_factory=list)
    missing_must: list[str] = field(default_factory=list)
    matched_nice: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 1),
            "breakdown": {k: round(v, 1) for k, v in self.breakdown.items()},
            "matched_must_have": self.matched_must,
            "missing_must_have": self.missing_must,
            "matched_nice_to_have": self.matched_nice,
        }


def score_profile(profile: SourcedProfile, criteria: JobCriteria) -> FitScore:
    result = FitScore()
    profile_skills = {s.strip().lower() for s in profile.skills if s and s.strip()}
    # Titles and headlines often carry skills the vendor did not tag.
    haystack = " ".join(
        filter(
            None,
            [
                profile.title,
                profile.headline,
                *(str(e.get("title", "")) for e in profile.experience),
            ],
        )
    ).lower()

    _score_skills(result, criteria, profile_skills, haystack)
    _score_experience(result, criteria, profile)
    _score_title(result, criteria, profile)
    _score_location(result, criteria, profile)

    result.score = max(0.0, min(100.0, sum(result.breakdown.values())))
    return result


def _has_skill(skill: str, skills: set[str], haystack: str) -> bool:
    low = skill.strip().lower()
    if not low:
        return False
    if low in skills:
        return True
    # Word boundaries, not substrings: plain containment credits "Go" to anyone
    # listing Django, and the recruiter dials on a fabricated match.
    pattern = re.compile(rf"(?<![\w+#.]){re.escape(low)}(?![\w+#.])")
    return any(pattern.search(s) for s in skills) or bool(pattern.search(haystack))


def _score_skills(
    result: FitScore, criteria: JobCriteria, skills: set[str], haystack: str
) -> None:
    must = [s for s in criteria.must_have_skills if s.strip()]
    if must:
        matched = [s for s in must if _has_skill(s, skills, haystack)]
        result.matched_must = matched
        result.missing_must = [s for s in must if s not in matched]
        ratio = len(matched) / len(must)
        result.breakdown["must_have_skills"] = WEIGHTS["must_have_skills"] * ratio
        if matched:
            result.reasons.append(
                f"Matches {len(matched)}/{len(must)} must-have skills: "
                + ", ".join(matched[:5])
            )
        if result.missing_must:
            result.reasons.append("Missing: " + ", ".join(result.missing_must[:4]))
    else:
        # No stated requirements - don't punish anyone for it.
        result.breakdown["must_have_skills"] = WEIGHTS["must_have_skills"] * 0.6
        result.reasons.append("No must-have skills specified in the job description.")

    nice = [s for s in criteria.nice_to_have_skills if s.strip()]
    if nice:
        matched_nice = [s for s in nice if _has_skill(s, skills, haystack)]
        result.matched_nice = matched_nice
        result.breakdown["nice_to_have_skills"] = WEIGHTS["nice_to_have_skills"] * (
            len(matched_nice) / len(nice)
        )
        if matched_nice:
            result.reasons.append("Bonus skills: " + ", ".join(matched_nice[:4]))
    else:
        result.breakdown["nice_to_have_skills"] = 0.0


def _score_experience(
    result: FitScore, criteria: JobCriteria, profile: SourcedProfile
) -> None:
    weight = WEIGHTS["experience"]
    years = profile.years_experience
    lo, hi = criteria.min_years, criteria.max_years

    if years is None:
        result.breakdown["experience"] = weight * 0.5
        result.reasons.append("Years of experience unknown - verify on the call.")
        return
    if lo is None and hi is None:
        result.breakdown["experience"] = weight * 0.7
        return

    if lo is not None and years < lo:
        shortfall = lo - years
        # 1 year short keeps most of the credit; 3+ years short keeps very little.
        result.breakdown["experience"] = weight * max(0.0, 1 - (shortfall / 3.0)) * 0.8
        result.reasons.append(f"{years:g} yrs experience vs {lo:g}+ required.")
        return
    if hi is not None and years > hi:
        overshoot = years - hi
        result.breakdown["experience"] = weight * max(0.55, 1 - (overshoot / 10.0))
        result.reasons.append(f"{years:g} yrs experience, above the {hi:g} yr band.")
        return

    result.breakdown["experience"] = weight
    band = f"{lo:g}-{hi:g}" if lo is not None and hi is not None else f"{lo:g}+"
    result.reasons.append(f"{years:g} yrs experience fits the {band} yr band.")


def _score_title(
    result: FitScore, criteria: JobCriteria, profile: SourcedProfile
) -> None:
    weight = WEIGHTS["title"]
    title = (profile.title or profile.headline or "").lower()
    if not title:
        result.breakdown["title"] = weight * 0.4
        return

    targets = [t.lower() for t in criteria.titles if t.strip()]
    best = 0.0
    matched_on = ""
    for target in targets:
        if target and target in title:
            best, matched_on = 1.0, target
            break
        overlap = _token_overlap(target, title)
        if overlap > best:
            best, matched_on = overlap, target

    seniority_bonus = 0.0
    if criteria.seniority and profile.seniority:
        if profile.seniority.lower() in {s.lower() for s in criteria.seniority}:
            seniority_bonus = 0.15
        else:
            seniority_bonus = -0.1

    result.breakdown["title"] = max(
        0.0, weight * min(1.0, best * 0.85 + seniority_bonus)
    )
    if best >= 0.9:
        result.reasons.append(f"Title matches the target role ({profile.title}).")
    elif best >= 0.4:
        result.reasons.append(f"Title is adjacent to '{matched_on}' ({profile.title}).")
    else:
        result.reasons.append(f"Title '{profile.title}' is off-target.")


def _token_overlap(a: str, b: str) -> float:
    stop = {"of", "the", "and", "a", "an", "in", "for", "senior", "sr", "lead", "staff"}
    ta = {t for t in a.replace("/", " ").split() if t and t not in stop}
    tb = {t for t in b.replace("/", " ").split() if t and t not in stop}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)


def _score_location(
    result: FitScore, criteria: JobCriteria, profile: SourcedProfile
) -> None:
    weight = WEIGHTS["location"]
    wanted = [loc.lower() for loc in criteria.locations if loc.strip()]
    if not wanted:
        result.breakdown["location"] = weight * 0.7
        return
    if any("remote" in loc for loc in wanted):
        result.breakdown["location"] = weight
        result.reasons.append("Role is remote - location is not a constraint.")
        return

    location = (profile.location or "").lower()
    if location and any(_city(w) in location for w in wanted):
        result.breakdown["location"] = weight
        result.reasons.append(f"Based in {profile.location}.")
        return
    if profile.country_code and profile.country_code.upper() in {
        c.upper() for c in criteria.countries
    }:
        result.breakdown["location"] = weight * 0.6
        result.reasons.append(
            f"In-country ({profile.country_code}) but a different city."
        )
        return

    result.breakdown["location"] = 0.0
    if profile.location:
        result.reasons.append(
            f"Located in {profile.location} - outside the target area."
        )


def _city(location: str) -> str:
    return location.split(",")[0].strip()
