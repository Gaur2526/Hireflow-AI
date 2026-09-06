"""Offline people-search provider.

The commercial vendors (PDL, Apollo, Proxycurl, Coresignal) all require a paid
key before they return dialable mobile numbers. This provider makes the whole
pipeline demonstrable with zero credentials: it synthesises a realistic,
*deterministic* candidate pool that genuinely reflects the parsed job criteria,
so search -> scoring -> shortlist -> voice screening -> dashboard all behave the
way they would against a live vendor.

Phone numbers come from the +1-555-01XX range reserved for fiction, so nothing
here can dial a real person. Set ``DEMO_CALL_REDIRECT_NUMBER`` to route demo
calls to your own handset.
"""

from __future__ import annotations

import hashlib
import random
import time
from typing import Any

from app.services.people_search.base import (
    PeopleSearchProvider,
    SearchQuery,
    SearchResult,
    SourcedProfile,
)

FIRST_NAMES = [
    "Aarav",
    "Ananya",
    "Rohan",
    "Priya",
    "Vikram",
    "Meera",
    "Karthik",
    "Divya",
    "Siddharth",
    "Neha",
    "Arjun",
    "Kavya",
    "Rahul",
    "Ishita",
    "Nikhil",
    "Sneha",
    "Aditya",
    "Pooja",
    "Varun",
    "Shreya",
    "Manish",
    "Tanvi",
    "Rajat",
    "Anjali",
    "Daniel",
    "Sofia",
    "Marcus",
    "Elena",
    "Omar",
    "Leila",
    "Chen",
    "Yuki",
    "Emeka",
    "Fatima",
    "Lucas",
    "Amara",
    "Noah",
    "Zara",
    "Ethan",
    "Maya",
]

LAST_NAMES = [
    "Sharma",
    "Iyer",
    "Reddy",
    "Nair",
    "Kulkarni",
    "Bose",
    "Menon",
    "Gupta",
    "Verma",
    "Rao",
    "Chatterjee",
    "Desai",
    "Pillai",
    "Joshi",
    "Malhotra",
    "Krishnan",
    "Banerjee",
    "Sinha",
    "Mehta",
    "Ahuja",
    "Okafor",
    "Nakamura",
    "Rossi",
    "Fernandez",
    "Novak",
    "Haddad",
    "Silva",
    "Andersson",
    "Kowalski",
    "Dubois",
]

COMPANIES = [
    ("Razorpay", "Financial Services", 3000),
    ("Swiggy", "Internet", 6000),
    ("Zerodha", "Financial Services", 1200),
    ("Freshworks", "Software", 5000),
    ("Postman", "Software", 800),
    ("CRED", "Financial Services", 900),
    ("PhonePe", "Financial Services", 5500),
    ("Meesho", "Internet", 1800),
    ("Zoho", "Software", 15000),
    ("Flipkart", "Internet", 22000),
    ("Atlassian", "Software", 12000),
    ("Stripe", "Financial Services", 8000),
    ("Datadog", "Software", 5000),
    ("Shopify", "Internet", 11000),
    ("Twilio", "Software", 6000),
    ("Cloudflare", "Software", 3800),
    ("Snowflake", "Software", 7000),
    ("HashiCorp", "Software", 2200),
    ("Grafana Labs", "Software", 1100),
    ("Vercel", "Software", 600),
]

DEFAULT_LOCATIONS = [
    ("Bengaluru, Karnataka, India", "IN"),
    ("Hyderabad, Telangana, India", "IN"),
    ("Pune, Maharashtra, India", "IN"),
    ("Gurugram, Haryana, India", "IN"),
    ("Chennai, Tamil Nadu, India", "IN"),
    ("Mumbai, Maharashtra, India", "IN"),
]

ADJACENT_SKILLS = [
    "Git",
    "Docker",
    "Linux",
    "REST APIs",
    "CI/CD",
    "Agile",
    "System Design",
    "Unit Testing",
    "Code Review",
    "Microservices",
    "SQL",
    "Observability",
]

# Real NANP area codes; combined with the 555-01XX block these are guaranteed
# non-routable, so a misconfigured demo can never dial a real person.
FICTION_AREA_CODES = ["202", "212", "312", "415", "617", "718"]

DEGREES = [
    ("B.Tech", "Computer Science"),
    ("B.E.", "Information Technology"),
    ("M.Tech", "Computer Science"),
    ("B.Sc", "Mathematics"),
    ("MCA", "Computer Applications"),
]

UNIVERSITIES = [
    "Indian Institute of Technology, Bombay",
    "Indian Institute of Technology, Madras",
    "BITS Pilani",
    "National Institute of Technology, Trichy",
    "Delhi Technological University",
    "VIT Vellore",
    "Manipal Institute of Technology",
    "PES University",
]

SENIORITY_PREFIX = {
    "entry": ["Associate", "Junior"],
    "mid": ["", ""],
    "senior": ["Senior", "Sr."],
    "manager": ["Lead", "Staff", "Principal"],
    "director": ["Director of", "Head of"],
    "vp": ["VP,", "Vice President,"],
    "cxo": ["Chief", "Head of"],
}


class MockPeopleSearchProvider(PeopleSearchProvider):
    name = "mock"
    label = "Built-in demo dataset"
    docs_url = ""
    requires_key = False

    async def search(self, query: SearchQuery) -> SearchResult:
        started = time.perf_counter()
        rng = random.Random(_seed(query))

        title_pool = query.titles or ["Software Engineer"]
        locations = _locations_for(query)
        must = [s for s in query.must_have_skills if s][:10]
        nice = [s for s in query.nice_to_have_skills if s][:10]
        skill_pool = list(dict.fromkeys([*must, *nice, *ADJACENT_SKILLS]))

        lo = query.min_years if query.min_years is not None else 3.0
        hi = query.max_years if query.max_years is not None else max(lo + 6.0, 9.0)

        profiles: list[SourcedProfile] = []
        n = max(1, min(query.limit, 100))
        for i in range(n):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            full_name = f"{first} {last}"
            company, industry, headcount = rng.choice(COMPANIES)
            location, country = rng.choice(locations)

            # Spread experience around the requested band, with a deliberate
            # minority of near-misses so the fit score has something to say.
            if i % 7 == 0:
                years = round(max(0.5, lo - rng.uniform(0.5, 2.5)), 1)
            else:
                years = round(rng.uniform(lo, hi + 2), 1)

            level = _level_for(query, years, rng)
            # Rotate through the title variants so a shortlist looks like real
            # search results rather than 20 copies of the JD's own title.
            title = _title_for(title_pool[i % len(title_pool)], level, rng)

            # Strong candidates cover most must-haves; weaker ones drop some.
            keep_must = must[:] if i % 5 else must[: max(1, len(must) - 2)]
            extra = rng.sample(skill_pool, k=min(len(skill_pool), rng.randint(3, 6)))
            skills = list(dict.fromkeys([*keep_must, *extra]))
            rng.shuffle(skills)

            slug = f"{first}-{last}-{i:03d}".lower()
            # +1 (NPA) 555-01XX is the range reserved for fictional use.
            area_code = FICTION_AREA_CODES[i % len(FICTION_AREA_CODES)]
            line = 100 + (i % 100)
            profiles.append(
                SourcedProfile(
                    external_id=f"mock_{_seed(query)[:8]}_{i:03d}",
                    source=self.name,
                    full_name=full_name,
                    first_name=first,
                    last_name=last,
                    title=title,
                    headline=f"{title} at {company}",
                    company=company,
                    location=location,
                    country_code=country,
                    linkedin_url=f"https://www.linkedin.com/in/{slug}",
                    email=f"{first.lower()}.{last.lower()}@{_domain(company)}",
                    phone=f"+1{area_code}555{line:04d}",
                    years_experience=years,
                    seniority=level,
                    skills=skills[:12],
                    experience=_experience(company, title, years, rng),
                    education=_education(rng),
                    raw={
                        "synthetic": True,
                        "industry": industry,
                        "company_headcount": headcount,
                        "matched_titles": query.titles,
                        "matched_skills": [s for s in must if s in skills],
                    },
                )
            )

        elapsed = int((time.perf_counter() - started) * 1000)
        return SearchResult(
            provider=self.name,
            profiles=profiles,
            total_available=len(profiles) * 24,
            query_sent=query.model_dump(exclude_none=True),
            latency_ms=elapsed,
            warnings=[
                "Synthetic dataset - profiles are generated from the parsed job "
                "criteria, not sourced from a live vendor.",
                "Phone numbers use the +1-555-01XX range reserved for fiction and "
                "cannot reach a real person. Set DEMO_CALL_REDIRECT_NUMBER to place "
                "a real test call.",
            ],
        )


# ---------------------------------------------------------------------------
def _seed(query: SearchQuery) -> str:
    payload = "|".join(
        [
            ",".join(sorted(t.lower() for t in query.titles)),
            ",".join(sorted(s.lower() for s in query.must_have_skills)),
            ",".join(sorted(loc.lower() for loc in query.locations)),
            str(query.min_years),
            str(query.max_years),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _locations_for(query: SearchQuery) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for loc in query.locations:
        country = "IN"
        low = loc.lower()
        if any(
            k in low for k in ("united states", "usa", ", us", "california", "new york")
        ):
            country = "US"
        elif any(k in low for k in ("united kingdom", "london", ", uk")):
            country = "GB"
        elif "saudi" in low or "riyadh" in low:
            country = "SA"
        elif query.countries:
            country = query.countries[0]
        out.append((loc, country))
    return out or DEFAULT_LOCATIONS


def _level_for(query: SearchQuery, years: float, rng: random.Random) -> str:
    if query.seniority:
        return rng.choice(query.seniority).lower()
    if years >= 12:
        return "director"
    if years >= 8:
        return "manager"
    if years >= 4:
        return "senior"
    if years <= 1.5:
        return "entry"
    return "mid"


def _title_for(base_title: str, level: str, rng: random.Random) -> str:
    core = base_title
    for token in ("Senior ", "Sr. ", "Junior ", "Lead ", "Staff ", "Principal "):
        core = core.replace(token, "")
    prefix = rng.choice(SENIORITY_PREFIX.get(level, [""]))
    return f"{prefix} {core}".strip() if prefix else core


def _domain(company: str) -> str:
    return "".join(ch for ch in company.lower() if ch.isalnum()) + ".example.com"


def _experience(
    company: str, title: str, years: float, rng: random.Random
) -> list[dict[str, Any]]:
    current_years = min(years, round(rng.uniform(1.0, max(1.5, years)), 1))
    prev_company, _, _ = rng.choice(COMPANIES)
    entries = [
        {
            "company": company,
            "title": title,
            "is_current": True,
            "years": current_years,
        }
    ]
    if years - current_years >= 1:
        entries.append(
            {
                "company": prev_company,
                "title": title.replace("Senior ", "").replace("Lead ", ""),
                "is_current": False,
                "years": round(years - current_years, 1),
            }
        )
    return entries


def _education(rng: random.Random) -> list[dict[str, Any]]:
    degree, major = rng.choice(DEGREES)
    return [{"school": rng.choice(UNIVERSITIES), "degree": degree, "major": major}]
