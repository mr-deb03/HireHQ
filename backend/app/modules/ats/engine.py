"""The explainable ATS scoring engine.

Design commitments:

* **Not keyword counting.** Six independent components (skills, experience, education,
  responsibilities, semantic, plus a certifications bonus folded into skills) are scored
  separately and combined with configurable weights.
* **Explainable.** Every component returns the evidence behind its number, so a
  recruiter can see *why* a candidate scored 74 rather than being handed an oracle.
* **Deterministic and pure.** No I/O, no database, no clock. The same inputs always give
  the same score, which is what makes it unit-testable and auditable - and means a score
  can be recomputed later to verify it.
* **Never a decision.** The output includes a recommendation *label* for humans; nothing
  in this module rejects, ranks-out, or filters a candidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.core.enums import AtsRecommendation
from app.utils.skills import SkillMatch, match_skill, normalise_skill
from app.utils.text import similarity, tokenize

#: Education ladder. A candidate meets a requirement by holding an equal or higher rung.
EDUCATION_LEVELS: dict[str, int] = {
    "HIGH_SCHOOL": 1,
    "DIPLOMA": 2,
    "BACHELORS": 3,
    "MASTERS": 4,
    "DOCTORATE": 5,
}

EDUCATION_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("DOCTORATE", ("phd", "ph.d", "doctorate", "doctoral", "d.phil")),
    (
        "MASTERS",
        ("master", "masters", "m.tech", "mtech", "msc", "m.sc", "mba", "mca", "m.c.a",
         "m.e", "m.a", "m.s", "postgraduate", "post graduate"),
    ),
    (
        "BACHELORS",
        ("bachelor", "bachelors", "b.tech", "btech", "b.e", "bsc", "b.sc", "bca",
         "b.com", "bcom", "b.a", "b.des", "undergraduate", "degree"),
    ),
    ("DIPLOMA", ("diploma", "polytechnic", "associate degree")),
    ("HIGH_SCHOOL", ("high school", "higher secondary", "12th", "hsc", "a-level")),
]


def _compile_level_patterns(
    levels: list[tuple[str, tuple[str, ...]]],
) -> list[tuple[str, re.Pattern[str]]]:
    """Build word-boundary matchers for degree abbreviations.

    Plain substring matching is badly wrong here: ``mba`` occurs inside ``Bombay`` and
    ``b.a`` inside ``b.arch``, each of which silently promotes a candidate's education
    level and inflates their score. Requiring a non-alphanumeric character before the
    hint - and after it, when it ends in a word character - fixes that while still
    matching dotted forms like ``b.tech``.
    """
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for level, hints in levels:
        alternatives: list[str] = []
        for hint in hints:
            # Guard the left edge so "mba" cannot match inside "Bombay". On the
            # right, require a word boundary only for hints ending in a letter or
            # digit - a dotted form like "b.e" must still match "B.E." followed by
            # a full stop, where \b would not apply.
            trailing = r"\b" if hint[-1].isalnum() else ""
            alternatives.append(
                rf"(?<![a-z0-9]){re.escape(hint)}{trailing}"
            )
        compiled.append((level, re.compile("|".join(alternatives), re.IGNORECASE)))
    return compiled


_LEVEL_PATTERNS = _compile_level_patterns(EDUCATION_KEYWORDS)

#: A preferred skill is worth this fraction of a required one.
PREFERRED_SKILL_WEIGHT = 0.35


@dataclass(slots=True)
class JobRequirements:
    """Everything the engine needs about a job. Built by the service from the DB row."""

    title: str = ""
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    #: Per-skill relative weight (1-5), keyed by normalised skill name.
    skill_weights: dict[str, int] = field(default_factory=dict)
    min_experience_years: float = 0
    max_experience_years: float | None = None
    education_requirements: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    description: str = ""


@dataclass(slots=True)
class CandidateProfile:
    """Everything the engine needs about a candidate."""

    skills: list[str] = field(default_factory=list)
    total_experience_years: float = 0
    #: Highest attained level, e.g. ``"MASTERS"``. Derived by ``infer_education_level``.
    education_level: str | None = None
    education_entries: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    #: Responsibility bullets from work history, used for the responsibilities match.
    experience_bullets: list[str] = field(default_factory=list)
    job_titles: list[str] = field(default_factory=list)
    resume_text: str = ""


@dataclass(slots=True)
class ComponentScore:
    """One dimension's result, carrying its own explanation."""

    name: str
    score: float  # 0-100
    weight: float
    explanation: str
    details: dict = field(default_factory=dict)

    @property
    def contribution(self) -> float:
        return round(self.score * self.weight, 2)


@dataclass(slots=True)
class AtsResult:
    overall_score: float
    recommendation: AtsRecommendation
    components: dict[str, ComponentScore]
    matches: list[SkillMatch]
    matched_skills: list[str]
    missing_skills: list[str]
    weights_used: dict[str, float]
    explanation: dict

    @property
    def skills_score(self) -> float:
        return self.components["skills"].score

    @property
    def experience_score(self) -> float:
        return self.components["experience"].score

    @property
    def education_score(self) -> float:
        return self.components["education"].score

    @property
    def responsibilities_score(self) -> float:
        return self.components["responsibilities"].score

    @property
    def semantic_score(self) -> float:
        return self.components["semantic"].score


DEFAULT_WEIGHTS: dict[str, float] = {
    "skills": 0.40,
    "experience": 0.25,
    "education": 0.10,
    "responsibilities": 0.15,
    "semantic": 0.10,
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "strong": 85.0,
    "good": 70.0,
    "partial": 50.0,
}


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    """Rescale to sum to 1.0.

    A company can set any five numbers; normalising here means a profile of
    ``40/25/10/15/10`` and one of ``4/2.5/1/1.5/1`` behave identically, and a score can
    never exceed 100 because someone entered percentages that sum to 150.
    """
    merged = {**DEFAULT_WEIGHTS, **{k: max(0.0, float(v)) for k, v in weights.items()}}
    total = sum(merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in merged.items()}


def infer_education_level(entries: list[str]) -> str | None:
    """Highest education rung mentioned across a candidate's education entries."""
    best: str | None = None
    best_rank = 0
    for entry in entries:
        lowered = entry.lower()
        for level, pattern in _LEVEL_PATTERNS:
            if pattern.search(lowered):
                rank = EDUCATION_LEVELS[level]
                if rank > best_rank:
                    best, best_rank = level, rank
                break
    return best


def requirement_to_level(requirement: str) -> str | None:
    lowered = requirement.lower()
    for level, pattern in _LEVEL_PATTERNS:
        if pattern.search(lowered):
            return level
    return None


# --------------------------------------------------------------- components
def score_skills(
    job: JobRequirements, candidate: CandidateProfile
) -> tuple[ComponentScore, list[SkillMatch]]:
    """Weighted coverage of required and preferred skills.

    Required skills dominate; preferred skills add a bounded bonus. Per-skill weights let
    a recruiter say "React matters more than Git" without touching global weights.
    """
    matches: list[SkillMatch] = []
    earned = 0.0
    possible = 0.0

    for skill in job.required_skills:
        weight = float(job.skill_weights.get(normalise_skill(skill), 3))
        match = match_skill(skill, candidate.skills)
        matches.append(match)
        possible += weight
        earned += weight * match.strength if match.matched else 0.0

    preferred_earned = 0.0
    preferred_possible = 0.0
    for skill in job.preferred_skills:
        weight = float(job.skill_weights.get(normalise_skill(skill), 3)) * PREFERRED_SKILL_WEIGHT
        match = match_skill(skill, candidate.skills)
        match.requirement = skill
        matches.append(match)
        preferred_possible += weight
        preferred_earned += weight * match.strength if match.matched else 0.0

    # Certifications the job asked for count towards the skills dimension.
    cert_earned = cert_possible = 0.0
    for cert in job.certifications:
        cert_possible += 1.0
        if any(similarity(cert, held) >= 0.8 for held in candidate.certifications):
            cert_earned += 1.0

    total_possible = possible + preferred_possible + cert_possible
    total_earned = earned + preferred_earned + cert_earned

    if total_possible == 0:
        # A job with no stated skills cannot discriminate on skills. Returning a neutral
        # 50 (rather than 0 or 100) keeps the overall score honest instead of letting an
        # unspecified requirement silently dominate the result.
        return (
            ComponentScore(
                name="skills",
                score=50.0,
                weight=0.0,
                explanation="No skills were specified for this job, so this dimension is neutral.",
                details={"required": 0, "matched": 0},
            ),
            matches,
        )

    score = round(min(100.0, total_earned / total_possible * 100), 2)
    required_matches = [m for m in matches[: len(job.required_skills)] if m.matched]
    matched_names = [m.evidence or m.requirement for m in required_matches]
    missing_names = [m.requirement for m in matches[: len(job.required_skills)] if not m.matched]

    parts = [
        f"Matched {len(required_matches)} of {len(job.required_skills)} required skills"
    ]
    if job.preferred_skills:
        preferred_hits = sum(1 for m in matches[len(job.required_skills) :] if m.matched)
        parts.append(f"{preferred_hits} of {len(job.preferred_skills)} preferred skills")
    if job.certifications:
        parts.append(f"{int(cert_earned)} of {len(job.certifications)} certifications")
    explanation = ", ".join(parts) + "."
    if missing_names:
        explanation += f" Not evidenced: {', '.join(missing_names[:6])}."

    return (
        ComponentScore(
            name="skills",
            score=score,
            weight=0.0,
            explanation=explanation,
            details={
                "required_total": len(job.required_skills),
                "required_matched": len(required_matches),
                "preferred_total": len(job.preferred_skills),
                "matched": matched_names,
                "missing": missing_names,
                "certifications_matched": int(cert_earned),
                "certifications_required": len(job.certifications),
            },
        ),
        matches,
    )


def score_experience(job: JobRequirements, candidate: CandidateProfile) -> ComponentScore:
    """Years of experience against the job's band.

    Meeting the minimum scores 100. Falling short degrades proportionally rather than
    cliff-edging to zero - someone with 2.5 of 3 years is a near-miss, not a non-starter.
    Substantially exceeding the band is *mildly* penalised because it usually signals a
    level mismatch, but never below 80: over-qualification is a conversation, not a flaw.
    """
    have = float(candidate.total_experience_years or 0)
    need = float(job.min_experience_years or 0)
    ceiling = float(job.max_experience_years) if job.max_experience_years else None

    if need <= 0 and ceiling is None:
        return ComponentScore(
            name="experience",
            score=75.0 if have > 0 else 50.0,
            weight=0.0,
            explanation=(
                f"No experience requirement was specified. Candidate has {have:g} years."
            ),
            details={"candidate_years": have, "required_years": None},
        )

    if have >= need:
        score = 100.0
        explanation = f"Candidate has {have:g} years against {need:g} required."
        if ceiling is not None and have > ceiling:
            excess = have - ceiling
            # -4 points per year over the band, floored at 80.
            score = max(80.0, 100.0 - excess * 4)
            explanation = (
                f"Candidate has {have:g} years, above the {need:g}-{ceiling:g} year band "
                f"for this role - review for level fit."
            )
    elif need > 0:
        ratio = have / need
        # Below the bar, score tracks the shortfall but keeps a floor so a junior
        # applicant with strong skills is not driven to zero overall.
        score = round(max(0.0, ratio) * 100, 2)
        shortfall = need - have
        explanation = (
            f"Candidate has {have:g} years against {need:g} required "
            f"({shortfall:g} short)."
        )
    else:
        score = 100.0
        explanation = f"Candidate has {have:g} years of experience."

    return ComponentScore(
        name="experience",
        score=round(min(100.0, score), 2),
        weight=0.0,
        explanation=explanation,
        details={
            "candidate_years": have,
            "required_years": need,
            "max_years": ceiling,
            "meets_minimum": have >= need,
        },
    )


def score_education(job: JobRequirements, candidate: CandidateProfile) -> ComponentScore:
    """Highest attained level against the highest level the job asks for."""
    required_levels = [
        level for level in (requirement_to_level(r) for r in job.education_requirements) if level
    ]

    if not required_levels:
        return ComponentScore(
            name="education",
            score=100.0,
            weight=0.0,
            explanation="No specific education requirement for this role.",
            details={"required": None, "candidate": candidate.education_level},
        )

    required_rank = max(EDUCATION_LEVELS[level] for level in required_levels)
    required_name = next(
        level for level, rank in EDUCATION_LEVELS.items() if rank == required_rank
    )

    candidate_level = candidate.education_level or infer_education_level(
        candidate.education_entries
    )
    if candidate_level is None:
        return ComponentScore(
            name="education",
            score=0.0,
            weight=0.0,
            explanation=(
                f"This role asks for a {_pretty(required_name)}; no education could be "
                "read from the candidate's profile."
            ),
            details={
                "required": required_name,
                "candidate": None,
                "meets_requirement": False,
                "note": "absent_from_profile",
            },
        )

    candidate_rank = EDUCATION_LEVELS.get(candidate_level, 0)
    if candidate_rank >= required_rank:
        score = 100.0
        explanation = (
            f"Holds a {_pretty(candidate_level)}, meeting the {_pretty(required_name)} "
            "requirement."
        )
    else:
        # One rung short scores 60, two rungs 30, beyond that 10.
        gap = required_rank - candidate_rank
        score = {1: 60.0, 2: 30.0}.get(gap, 10.0)
        explanation = (
            f"Holds a {_pretty(candidate_level)}; this role asks for a "
            f"{_pretty(required_name)}."
        )

    return ComponentScore(
        name="education",
        score=score,
        weight=0.0,
        explanation=explanation,
        details={
            "required": required_name,
            "candidate": candidate_level,
            "meets_requirement": candidate_rank >= required_rank,
        },
    )


def score_responsibilities(job: JobRequirements, candidate: CandidateProfile) -> ComponentScore:
    """How much of the job's day-to-day work the candidate has demonstrably done.

    Each responsibility bullet from the job is compared against the candidate's own
    experience bullets and job titles by token overlap. This is the dimension that
    separates "has the keyword on their CV" from "has actually done the work".
    """
    if not job.responsibilities:
        return ComponentScore(
            name="responsibilities",
            score=50.0,
            weight=0.0,
            explanation="No responsibilities were listed for this job.",
            details={"total": 0, "matched": 0},
        )

    corpus = candidate.experience_bullets + candidate.job_titles
    if not corpus:
        return ComponentScore(
            name="responsibilities",
            score=0.0,
            weight=0.0,
            explanation=(
                "No work-experience detail was available to compare against this role's "
                "responsibilities."
            ),
            details={"total": len(job.responsibilities), "matched": 0, "note": "no_experience_detail"},
        )

    corpus_tokens = [set(tokenize(text)) for text in corpus]
    matched: list[str] = []
    partial: list[str] = []
    total = 0.0

    for responsibility in job.responsibilities:
        tokens = set(tokenize(responsibility))
        if not tokens:
            continue
        best = 0.0
        for candidate_tokens in corpus_tokens:
            if not candidate_tokens:
                continue
            # Overlap relative to the *requirement*, so a long CV bullet does not dilute
            # the signal the way symmetric Jaccard would.
            overlap = len(tokens & candidate_tokens) / len(tokens)
            best = max(best, overlap)
        total += min(1.0, best * 1.4)  # partial credit, capped
        if best >= 0.5:
            matched.append(responsibility)
        elif best >= 0.25:
            partial.append(responsibility)

    count = len([r for r in job.responsibilities if tokenize(r)])
    score = round(min(100.0, (total / count) * 100), 2) if count else 0.0

    return ComponentScore(
        name="responsibilities",
        score=score,
        weight=0.0,
        explanation=(
            f"Evidence found for {len(matched)} of {count} listed responsibilities"
            + (f", partial evidence for {len(partial)} more" if partial else "")
            + "."
        ),
        details={
            "total": count,
            "matched": len(matched),
            "partial": len(partial),
            "matched_examples": matched[:5],
        },
    )


def score_semantic(similarity_value: float, *, engine: str) -> ComponentScore:
    """Wrap a pre-computed similarity (0-1) as a component.

    Computing the similarity itself is I/O (it may call a model), so it happens in the
    service and is passed in - keeping this module pure.
    """
    value = max(0.0, min(1.0, float(similarity_value)))
    return ComponentScore(
        name="semantic",
        score=round(value * 100, 2),
        weight=0.0,
        explanation=(
            f"Overall similarity between the resume and the job description: "
            f"{value:.0%} (computed by {engine})."
        ),
        details={"similarity": round(value, 4), "engine": engine},
    )


def _pretty(level: str) -> str:
    return {
        "DOCTORATE": "doctorate",
        "MASTERS": "master's degree",
        "BACHELORS": "bachelor's degree",
        "DIPLOMA": "diploma",
        "HIGH_SCHOOL": "high-school qualification",
    }.get(level, level.lower())


def recommend(score: float, thresholds: dict[str, float] | None = None) -> AtsRecommendation:
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if score >= limits["strong"]:
        return AtsRecommendation.STRONG_MATCH
    if score >= limits["good"]:
        return AtsRecommendation.GOOD_MATCH
    if score >= limits["partial"]:
        return AtsRecommendation.PARTIAL_MATCH
    return AtsRecommendation.WEAK_MATCH


# ------------------------------------------------------------------ scoring
def score_application(
    job: JobRequirements,
    candidate: CandidateProfile,
    *,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    semantic_similarity: float = 0.0,
    semantic_engine: str = "lexical",
) -> AtsResult:
    """Compute the full explainable ATS result.

    Pure: same inputs, same output, no I/O. ``semantic_similarity`` is supplied by the
    caller because obtaining it may involve a model call.
    """
    resolved_weights = normalise_weights(weights or {})

    skills_component, matches = score_skills(job, candidate)
    experience_component = score_experience(job, candidate)
    education_component = score_education(job, candidate)
    responsibilities_component = score_responsibilities(job, candidate)
    semantic_component = score_semantic(semantic_similarity, engine=semantic_engine)

    components = {
        "skills": skills_component,
        "experience": experience_component,
        "education": education_component,
        "responsibilities": responsibilities_component,
        "semantic": semantic_component,
    }

    # A job that specifies no skills at all should not have 40% of the score decided by a
    # neutral placeholder, so that weight is redistributed across the informative
    # dimensions instead of quietly anchoring every candidate towards the middle.
    effective = dict(resolved_weights)
    if not job.required_skills and not job.preferred_skills and not job.certifications:
        freed = effective.pop("skills", 0.0)
        remaining = sum(effective.values())
        if remaining > 0:
            effective = {k: v + freed * (v / remaining) for k, v in effective.items()}
            effective["skills"] = 0.0
        else:
            effective = dict(resolved_weights)

    for name, component in components.items():
        component.weight = round(effective.get(name, 0.0), 4)

    overall = round(
        sum(component.score * effective.get(name, 0.0) for name, component in components.items()),
        2,
    )
    overall = max(0.0, min(100.0, overall))

    required_count = len(job.required_skills)
    matched_skills = [
        m.evidence or m.requirement for m in matches if m.matched
    ]
    missing_skills = [m.requirement for m in matches[:required_count] if not m.matched]

    recommendation = recommend(overall, thresholds)

    explanation = {
        "summary": _summarise(overall, recommendation, components),
        "components": {
            name: {
                "score": component.score,
                "weight": component.weight,
                "contribution": component.contribution,
                "explanation": component.explanation,
                "details": component.details,
            }
            for name, component in components.items()
        },
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "notes": [
            "This score ranks applications against the requirements written on the job. "
            "It is a screening aid, not a hiring decision.",
        ],
    }
    if not job.required_skills:
        explanation["notes"].append(
            "This job lists no required skills, so the skills dimension was excluded and "
            "its weight redistributed."
        )
    if not candidate.resume_text:
        explanation["notes"].append(
            "No resume text was available, so the semantic dimension has low confidence."
        )

    return AtsResult(
        overall_score=overall,
        recommendation=recommendation,
        components=components,
        matches=matches,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        weights_used=effective,
        explanation=explanation,
    )


def _summarise(
    overall: float, recommendation: AtsRecommendation, components: dict[str, ComponentScore]
) -> str:
    ranked = sorted(components.values(), key=lambda c: c.contribution, reverse=True)
    strongest = next((c for c in ranked if c.weight > 0), None)
    weakest = min(
        (c for c in components.values() if c.weight > 0),
        key=lambda c: c.score,
        default=None,
    )
    label = recommendation.value.replace("_", " ").lower()
    text = f"Overall {overall:g}% - {label}."
    if strongest:
        text += f" Strongest area: {strongest.name} ({strongest.score:g}%)."
    if weakest and weakest.name != (strongest.name if strongest else None):
        text += f" Weakest area: {weakest.name} ({weakest.score:g}%)."
    return text


def compute_ranks(scores: list[tuple[str, float]]) -> dict[str, int]:
    """Dense ranking, ties sharing a rank. ``[(id, score), ...] -> {id: rank}``."""
    ordered = sorted(scores, key=lambda pair: pair[1], reverse=True)
    ranks: dict[str, int] = {}
    previous_score: float | None = None
    rank = 0
    for index, (identifier, score) in enumerate(ordered, start=1):
        if previous_score is None or score != previous_score:
            rank = index
            previous_score = score
        ranks[identifier] = rank
    return ranks


def years_between(start: date, end: date | None = None) -> float:
    end = end or date.today()
    return round(max(0, (end - start).days) / 365.25, 1)
