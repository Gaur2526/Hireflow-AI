"""Turn a free-text job description into structured hiring criteria.

Two paths, same output shape:

* ``llm``       - Claude with a constrained JSON schema (used when a key exists).
* ``heuristic`` - deterministic section/keyword extraction over a curated
  taxonomy. Always available, and used as the fallback whenever the LLM path
  is unavailable or returns something unusable.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.schemas.job import JobCriteria
from app.services import taxonomy as tx
from app.services.llm import LLMClient, LLMUnavailable, get_llm

log = get_logger(__name__)

_MAX_JD_CHARS = 20_000


SYSTEM_PROMPT = """You are a technical sourcing analyst. You read a job \
description and extract precise, machine-usable search criteria for querying a \
people-search API (People Data Labs / Apollo / Proxycurl / Coresignal).

Rules:
- `titles`: 3-6 realistic job titles a matching candidate would ACTUALLY have on \
their profile today. Include the JD's own title plus close synonyms. Do not \
invent grandiose titles.
- `must_have_skills`: 4-10 hard, checkable skills stated as requirements. Use \
canonical names ("PostgreSQL" not "postgres db", "Kubernetes" not "k8s").
- `nice_to_have_skills`: skills framed as bonus/preferred/plus.
- `min_years` / `max_years`: numeric years of professional experience. If the JD \
says "5+ years", min is 5 and max is null.
- `locations`: city or region strings as they'd appear on a profile \
("Bengaluru, Karnataka, India"). Include "Remote" only if the role is remote.
- `countries`: ISO-3166 alpha-2 codes for those locations.
- `seniority`: any of entry, mid, senior, manager, director, vp, cxo.
- `summary`: two sentences an experienced recruiter would write.
Leave a field empty rather than guessing."""


async def parse_job_description(
    description: str,
    *,
    title_hint: str | None = None,
    location_hint: str | None = None,
    llm: LLMClient | None = None,
) -> tuple[JobCriteria, str, list[str]]:
    """Return ``(criteria, parsed_by, warnings)``."""
    warnings: list[str] = []
    text = (description or "").strip()[:_MAX_JD_CHARS]
    if not text:
        return JobCriteria(), "heuristic", ["Empty job description."]

    heuristic = extract_criteria_heuristically(
        text, title_hint=title_hint, location_hint=location_hint
    )

    client = llm or get_llm()
    if not client.configured:
        warnings.append(
            "ANTHROPIC_API_KEY not set - criteria extracted with the built-in "
            "deterministic parser. Set the key for sharper results."
        )
        return heuristic, "heuristic", warnings

    prompt = _build_prompt(text, title_hint, location_hint)
    try:
        criteria = await client.structured(
            system=SYSTEM_PROMPT,
            prompt=prompt,
            output_model=JobCriteria,
            effort="medium",
        )
    except LLMUnavailable as exc:
        log.warning("jd_parser.llm_failed", reason=str(exc))
        warnings.append(
            f"LLM extraction unavailable ({exc}); used the deterministic parser."
        )
        return heuristic, "heuristic", warnings

    merged = _merge(
        criteria, heuristic, title_hint=title_hint, location_hint=location_hint
    )
    return merged, "llm", warnings


def _build_prompt(text: str, title_hint: str | None, location_hint: str | None) -> str:
    header = []
    if title_hint:
        header.append(f"Known role title: {title_hint}")
    if location_hint:
        header.append(f"Known location: {location_hint}")
    prefix = ("\n".join(header) + "\n\n") if header else ""
    return f"{prefix}JOB DESCRIPTION\n---\n{text}\n---"


def _merge(
    primary: JobCriteria,
    fallback: JobCriteria,
    *,
    title_hint: str | None,
    location_hint: str | None,
) -> JobCriteria:
    """Fill gaps in the LLM output from the deterministic pass."""
    data = primary.model_dump()
    backup = fallback.model_dump()
    for key, value in data.items():
        if value in (None, "", [], {}) and backup.get(key):
            data[key] = backup[key]

    if title_hint and not data.get("role_title"):
        data["role_title"] = title_hint
    if title_hint and title_hint not in data.get("titles", []):
        data["titles"] = [title_hint, *data.get("titles", [])][:6]
    if location_hint and location_hint not in data.get("locations", []):
        data["locations"] = [location_hint, *data.get("locations", [])][:5]
    if not data.get("countries"):
        data["countries"] = _countries_for(data.get("locations", []))
    return JobCriteria(**data)


# ---------------------------------------------------------------------------
# Deterministic parser
# ---------------------------------------------------------------------------
def extract_criteria_heuristically(
    text: str,
    *,
    title_hint: str | None = None,
    location_hint: str | None = None,
) -> JobCriteria:
    lowered = text.lower()
    lines = [line.strip() for line in text.splitlines()]

    role_title = title_hint or _extract_title(lines)
    titles = _title_variants(role_title)
    must, nice = _extract_skills(lines)
    min_years, max_years = _extract_years(lowered)
    locations = _extract_locations(lowered, location_hint)

    return JobCriteria(
        role_title=role_title,
        titles=titles,
        # The title is the reliable signal; a stray "mentor two mid-level
        # engineers" in the responsibilities must not add a seniority band.
        seniority=_extract_seniority(role_title) or _extract_seniority(lowered),
        must_have_skills=must,
        nice_to_have_skills=[s for s in nice if s not in must],
        min_years=min_years,
        max_years=max_years,
        locations=locations,
        countries=_countries_for(locations),
        industries=[],
        target_companies=[],
        education=_extract_education(lowered),
        employment_type=_first_match(lowered, tx.EMPLOYMENT_TYPES),
        work_mode=_first_match(lowered, tx.WORK_MODES),
        compensation=_extract_compensation(text),
        summary=_summarise(text, role_title, must, min_years),
    )


_TITLE_LABEL = re.compile(
    r"^(?:job\s*title|role|position|designation)\s*[:\-–]\s*(.+)$", re.I
)


def _extract_title(lines: list[str]) -> str:
    for line in lines[:25]:
        m = _TITLE_LABEL.match(line)
        if m:
            return _clean_title(m.group(1))
    for line in lines:
        if not line:
            continue
        # Judge the heading shape *before* truncating: clipping at 80 chars
        # would strip the full stop that gives a prose sentence away.
        cleaned = _clean_title_text(line)
        # A heading-ish first line: short, no sentence punctuation.
        if 3 <= len(cleaned) <= 80 and not cleaned.endswith((".", ":", "!")):
            return cleaned
        break
    return "Open Role"


#: " - ", " – ", " — ", " | " and " @ " all introduce a qualifier after the
#: title ("Senior Backend Engineer — Payments"), never part of the title itself.
_TITLE_QUALIFIER = re.compile(r"\s+[-–—|@]\s+")


def _clean_title_text(value: str) -> str:
    cleaned = re.sub(r"^[#*\-\s]+", "", value).strip()
    cleaned = re.sub(r"\s*[\(\[].*?[\)\]]\s*$", "", cleaned).strip()
    cleaned = _TITLE_QUALIFIER.split(cleaned)[0]
    return cleaned.strip(" -–—:*#").strip()


def _clean_title(value: str) -> str:
    return _clean_title_text(value)[:80] or "Open Role"


def _title_variants(role_title: str) -> list[str]:
    low = role_title.lower()
    variants: list[str] = [role_title]
    for key, syns in tx.TITLE_SYNONYMS.items():
        if key in low:
            variants.extend(syns)
            break
    else:
        # Strip the seniority prefix so vendors match the base title too.
        base = re.sub(
            r"^(senior|sr\.?|junior|jr\.?|lead|staff|principal|associate)\s+", "", low
        ).strip()
        if base and base != low:
            variants.append(base.title())
    seen: dict[str, str] = {}
    for v in variants:
        k = v.strip().lower()
        if k and k not in seen:
            seen[k] = v.strip()
    return list(seen.values())[:6]


_BULLET = re.compile(r"^\s*(?:[-*•▪·+]|\d+[.)])\s")


def _looks_like_heading(line: str) -> bool:
    """Short, unbulleted, not a sentence."""
    text = line.strip().lstrip("#").strip()
    if not text or _BULLET.match(line):
        return False
    if text.endswith(":"):
        return True
    return len(text) <= 48 and not text.endswith(".") and len(text.split()) <= 7


def _section_of(line: str, current: str) -> str:
    # Only a heading may switch sections. Run on every line, a bullet like
    # "excellent communication skills" would flip a Nice-to-have block back to
    # must-have and promote every bonus skill under it.
    if not _looks_like_heading(line):
        return current
    low = line.lower()
    if any(h in low for h in tx.NICE_TO_HAVE_HEADINGS):
        return "nice"
    if any(h in low for h in tx.MUST_HAVE_HEADINGS):
        return "must"
    if any(h in low for h in tx.RESPONSIBILITY_HEADINGS):
        return "responsibilities"
    return current


#: Requirement bullets outrank responsibility prose when deciding which skill
#: the screening call should probe first.
_SECTION_RANK = {"must": 0, "responsibilities": 1, "intro": 2}


def _extract_skills(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split skills into must-have / nice-to-have, ordered by importance.

    Importance = which section the skill appeared in first (a requirement beats
    a responsibility beats stray prose), then where in the document. That
    ordering matters downstream: the top must-have becomes the skill the voice
    agent digs into.
    """
    must: dict[str, tuple[int, int]] = {}
    nice: dict[str, tuple[int, int]] = {}
    section = "intro"
    for index, line in enumerate(lines):
        if not line:
            continue
        section = _section_of(line, section)
        rank = _SECTION_RANK.get(section, 2)
        for skill in match_skills(line):
            target = nice if section == "nice" else must
            if skill not in target:
                target[skill] = (rank, index)

    ordered_must = [s for s, _ in sorted(must.items(), key=lambda kv: kv[1])][:12]
    ordered_nice = [
        s
        for s, _ in sorted(nice.items(), key=lambda kv: kv[1])
        if s not in ordered_must
    ][:10]
    return ordered_must, ordered_nice


def match_skills(text: str) -> list[str]:
    """Return canonical skill names mentioned in ``text``."""
    low = f" {text.lower()} "
    hits: list[str] = []
    for canonical, aliases in tx.SKILLS.items():
        needles = [canonical.lower(), *aliases]
        for needle in needles:
            if len(needle) <= 2:
                # "-" and "&" too: otherwise "go" matches go-to-market and the
                # canonical skill "R" matches R&D.
                pattern = rf"(?<![\w+#.&-]){re.escape(needle)}(?![\w+#.&-])"
            else:
                pattern = rf"(?<![\w]){re.escape(needle)}(?![\w])"
            if re.search(pattern, low):
                hits.append(canonical)
                break
    return hits


_YEARS_RANGE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs|yr)",
    re.I,
)
_YEARS_MIN = re.compile(
    r"(?:\b(minimum|min\.?|at least|over|more than)\s*)?(\d{1,2})\s*(\+?)"
    r"\s*(?:years|yrs|yr)",
    re.I,
)


def _extract_years(lowered: str) -> tuple[float | None, float | None]:
    m = _YEARS_RANGE.search(lowered)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi))
    stated: list[float] = []
    bare: list[float] = []
    for m in _YEARS_MIN.finditer(lowered):
        # Ignore "years of college", "in the last 2 years", etc.
        tail = lowered[m.end() : m.end() + 24]
        if any(w in tail for w in ("ago", "old", "of college", "of school")):
            continue
        value = float(m.group(2))
        if not 0 < value <= 30:
            continue
        (stated if (m.group(1) or m.group(3)) else bare).append(value)
    # An explicit floor ("8+ years", "at least 5 years") is the requirement; a
    # bare "2 years" in the company blurb must never outrank it.
    best = max(stated) if stated else (min(bare) if bare else None)
    return (best, None)


def _extract_locations(lowered: str, location_hint: str | None) -> list[str]:
    found: list[str] = []
    if location_hint:
        found.append(location_hint)
    for city in sorted(tx.LOCATIONS, key=len, reverse=True):
        if re.search(rf"(?<![\w]){re.escape(city)}(?![\w])", lowered):
            pretty = city.title() if city not in {"nyc", "usa"} else city.upper()
            if not any(pretty.lower() in f.lower() for f in found):
                found.append(pretty)
        if len(found) >= 4:
            break
    if not found and any(w in lowered for w in ("remote", "work from home")):
        found.append("Remote")
    return found[:4]


def _countries_for(locations: list[str]) -> list[str]:
    codes: list[str] = []
    for loc in locations:
        low = loc.lower()
        for city, code in tx.LOCATIONS.items():
            if city in low and code not in codes:
                codes.append(code)
                break
    return codes


def _extract_seniority(text: str) -> list[str]:
    low = text.lower()
    hits = [
        level
        for level, markers in tx.SENIORITY_MARKERS.items()
        if any(m in low for m in markers)
    ]
    return hits[:2]


def _extract_education(lowered: str) -> list[str]:
    return [d.upper() for d in tx.DEGREE_MARKERS if d in lowered][:4]


def _first_match(lowered: str, mapping: dict[str, list[str]]) -> str | None:
    for label, needles in mapping.items():
        if any(n in lowered for n in needles):
            return label
    return None


_COMP = re.compile(
    r"(?:₹|rs\.?|inr|\$|usd|£|gbp)\s?[\d,.]+\s*(?:-|–|to)?\s*(?:₹|rs\.?|inr|\$|usd|£)?\s?"
    r"[\d,.]*\s*(?:lpa|lakhs?|lacs?|cr|crore|k|m|per annum|pa|annually|/year|per year)?",
    re.I,
)


def _extract_compensation(text: str) -> str | None:
    for m in _COMP.finditer(text):
        value = m.group(0).strip()
        if any(ch.isdigit() for ch in value) and len(value) > 3:
            return value[:80]
    return None


def _summarise(
    text: str, role_title: str, skills: list[str], min_years: float | None
) -> str:
    bits = [f"{role_title}."]
    if min_years:
        bits.append(f"Targets {min_years:g}+ years of experience.")
    if skills:
        bits.append("Core stack: " + ", ".join(skills[:5]) + ".")
    if len(" ".join(bits)) < 40:
        first = next(
            (ln.strip() for ln in text.splitlines() if len(ln.strip()) > 40), ""
        )
        if first:
            bits.append(first[:180])
    return " ".join(bits)[:400]
