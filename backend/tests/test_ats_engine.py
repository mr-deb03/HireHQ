"""Unit tests for the ATS scoring engine.

The engine is pure, so these run without a database and cover the behaviour that
matters: that scores are explainable, bounded, weight-configurable, and that they degrade
sensibly rather than cliff-edging.
"""

from __future__ import annotations

import pytest

from app.core.enums import AtsRecommendation
from app.modules.ats.engine import (
    CandidateProfile,
    JobRequirements,
    compute_ranks,
    infer_education_level,
    normalise_weights,
    recommend,
    score_application,
    score_education,
    score_experience,
    score_responsibilities,
    score_skills,
)


def make_job(**overrides) -> JobRequirements:
    base = {
        "title": "Senior React Developer",
        "required_skills": ["React", "TypeScript", "REST API", "Git"],
        "preferred_skills": ["AWS", "Docker"],
        "skill_weights": {"react": 5, "typescript": 4},
        "min_experience_years": 3,
        "max_experience_years": 8,
        "education_requirements": ["Bachelor's degree"],
        "responsibilities": [
            "Build reusable React components",
            "Develop REST APIs",
            "Mentor junior developers",
        ],
        "description": "Senior React developer with TypeScript and REST API experience.",
    }
    base.update(overrides)
    return JobRequirements(**base)


def make_candidate(**overrides) -> CandidateProfile:
    base = {
        "skills": ["React", "TypeScript", "REST API", "Git"],
        "total_experience_years": 5,
        "education_level": "BACHELORS",
        "experience_bullets": [
            "Built reusable React components for the design system",
            "Developed REST APIs in Node.js",
            "Mentored two junior developers",
        ],
        "job_titles": ["Senior Frontend Engineer"],
        "resume_text": "Senior frontend engineer with React and TypeScript.",
    }
    base.update(overrides)
    return CandidateProfile(**base)


# ----------------------------------------------------------------- weights
class TestWeights:
    def test_normalises_to_one(self):
        weights = normalise_weights(
            {"skills": 40, "experience": 25, "education": 10,
             "responsibilities": 15, "semantic": 10}
        )
        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["skills"] == pytest.approx(0.40)

    def test_percentages_and_fractions_are_equivalent(self):
        as_percent = normalise_weights(
            {"skills": 40, "experience": 25, "education": 10,
             "responsibilities": 15, "semantic": 10}
        )
        as_fraction = normalise_weights(
            {"skills": 0.4, "experience": 0.25, "education": 0.1,
             "responsibilities": 0.15, "semantic": 0.1}
        )
        assert as_percent == pytest.approx(as_fraction)

    def test_weights_summing_over_one_cannot_inflate_the_score(self):
        # A misconfigured profile must not produce a score above 100.
        job, candidate = make_job(), make_candidate()
        result = score_application(
            job,
            candidate,
            weights={"skills": 100, "experience": 100, "education": 100,
                     "responsibilities": 100, "semantic": 100},
            semantic_similarity=1.0,
        )
        assert 0 <= result.overall_score <= 100

    def test_all_zero_weights_falls_back_to_defaults(self):
        weights = normalise_weights(
            {"skills": 0, "experience": 0, "education": 0,
             "responsibilities": 0, "semantic": 0}
        )
        assert sum(weights.values()) == pytest.approx(1.0)


# ------------------------------------------------------------------ skills
class TestSkills:
    def test_exact_match_scores_full(self):
        component, matches = score_skills(
            make_job(required_skills=["React"], preferred_skills=[], skill_weights={}),
            make_candidate(skills=["React"]),
        )
        assert component.score == 100
        assert matches[0].matched

    def test_alias_matches(self):
        """ReactJS must satisfy a React requirement - the whole point of normalisation."""
        component, matches = score_skills(
            make_job(required_skills=["React"], preferred_skills=[], skill_weights={}),
            make_candidate(skills=["ReactJS"]),
        )
        assert matches[0].matched
        assert component.score == 100

    def test_unrelated_skill_does_not_match(self):
        _, matches = score_skills(
            make_job(required_skills=["React"], preferred_skills=[], skill_weights={}),
            make_candidate(skills=["PHP", "WordPress"]),
        )
        assert not matches[0].matched

    def test_per_skill_weight_is_respected(self):
        job = make_job(
            required_skills=["React", "Git"],
            preferred_skills=[],
            skill_weights={"react": 5, "git": 1},
        )
        with_react = score_skills(job, make_candidate(skills=["React"]))[0].score
        with_git = score_skills(job, make_candidate(skills=["Git"]))[0].score
        assert with_react > with_git, "the heavier skill must contribute more"

    def test_missing_skills_are_reported(self):
        component, _ = score_skills(
            make_job(required_skills=["React", "Kubernetes"], preferred_skills=[],
                     skill_weights={}),
            make_candidate(skills=["React"]),
        )
        assert "Kubernetes" in component.details["missing"]
        assert "Kubernetes" in component.explanation

    def test_no_required_skills_is_neutral_not_zero(self):
        component, _ = score_skills(
            make_job(required_skills=[], preferred_skills=[], certifications=[],
                     skill_weights={}),
            make_candidate(skills=[]),
        )
        assert component.score == 50

    def test_preferred_skills_add_but_do_not_dominate(self):
        job = make_job(required_skills=["React"], preferred_skills=["AWS"],
                       skill_weights={})
        only_required = score_skills(job, make_candidate(skills=["React"]))[0].score
        both = score_skills(job, make_candidate(skills=["React", "AWS"]))[0].score
        assert both == 100
        assert 50 < only_required < 100


# -------------------------------------------------------------- experience
class TestExperience:
    def test_meeting_the_minimum_scores_full(self):
        component = score_experience(
            make_job(min_experience_years=3, max_experience_years=None),
            make_candidate(total_experience_years=3),
        )
        assert component.score == 100
        assert component.details["meets_minimum"] is True

    def test_shortfall_degrades_proportionally(self):
        """A near miss must not score the same as no experience at all."""
        job = make_job(min_experience_years=4, max_experience_years=None)
        close = score_experience(job, make_candidate(total_experience_years=3)).score
        far = score_experience(job, make_candidate(total_experience_years=1)).score
        none = score_experience(job, make_candidate(total_experience_years=0)).score
        assert close > far > none
        assert close == pytest.approx(75)

    def test_over_qualification_is_capped_not_punished(self):
        component = score_experience(
            make_job(min_experience_years=3, max_experience_years=6),
            make_candidate(total_experience_years=20),
        )
        assert component.score >= 80, "over-qualification is a conversation, not a flaw"
        assert "review for level fit" in component.explanation

    def test_no_requirement_is_neutral(self):
        component = score_experience(
            make_job(min_experience_years=0, max_experience_years=None),
            make_candidate(total_experience_years=0),
        )
        assert 0 < component.score < 100


# --------------------------------------------------------------- education
class TestEducation:
    def test_exact_level_meets_requirement(self):
        component = score_education(
            make_job(education_requirements=["Bachelor's degree"]),
            make_candidate(education_level="BACHELORS"),
        )
        assert component.score == 100

    def test_higher_level_satisfies_lower_requirement(self):
        component = score_education(
            make_job(education_requirements=["Bachelor's degree"]),
            make_candidate(education_level="MASTERS"),
        )
        assert component.score == 100

    def test_one_rung_short_is_partial(self):
        component = score_education(
            make_job(education_requirements=["Master's degree"]),
            make_candidate(education_level="BACHELORS"),
        )
        assert component.score == 60

    def test_no_requirement_scores_full(self):
        component = score_education(
            make_job(education_requirements=[]), make_candidate(education_level=None)
        )
        assert component.score == 100

    def test_absent_education_is_flagged_not_guessed(self):
        component = score_education(
            make_job(education_requirements=["Bachelor's degree"]),
            make_candidate(education_level=None, education_entries=[]),
        )
        assert component.score == 0
        assert component.details["note"] == "absent_from_profile"

    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ("B.Tech in Computer Science", "BACHELORS"),
            ("Master of Science", "MASTERS"),
            ("PhD in Machine Learning", "DOCTORATE"),
            ("Diploma in Mechanical Engineering", "DIPLOMA"),
            ("Higher Secondary", "HIGH_SCHOOL"),
        ],
    )
    def test_infers_level_from_text(self, entry, expected):
        assert infer_education_level([entry]) == expected

    def test_infers_the_highest_level_held(self):
        assert infer_education_level(["B.Tech", "M.Tech"]) == "MASTERS"


# --------------------------------------------------------- responsibilities
class TestResponsibilities:
    def test_evidenced_work_scores_high(self):
        component = score_responsibilities(
            make_job(responsibilities=["Build reusable React components"]),
            make_candidate(
                experience_bullets=["Built reusable React components for the platform"]
            ),
        )
        assert component.score > 60

    def test_unrelated_work_scores_low(self):
        component = score_responsibilities(
            make_job(responsibilities=["Build reusable React components"]),
            make_candidate(experience_bullets=["Managed warehouse inventory records"]),
        )
        assert component.score < 30

    def test_absent_history_is_zero_with_a_reason(self):
        component = score_responsibilities(
            make_job(), make_candidate(experience_bullets=[], job_titles=[])
        )
        assert component.score == 0
        assert component.details["note"] == "no_experience_detail"


# ----------------------------------------------------------------- overall
class TestOverallScoring:
    def test_strong_candidate_scores_well(self):
        result = score_application(make_job(), make_candidate(), semantic_similarity=0.7)
        assert result.overall_score >= 80
        assert result.recommendation in (
            AtsRecommendation.STRONG_MATCH,
            AtsRecommendation.GOOD_MATCH,
        )

    def test_poor_candidate_scores_low(self):
        result = score_application(
            make_job(),
            make_candidate(
                skills=["PHP", "WordPress"],
                total_experience_years=1,
                education_level="HIGH_SCHOOL",
                experience_bullets=["Built WordPress sites"],
                job_titles=["PHP Developer"],
            ),
            semantic_similarity=0.1,
        )
        assert result.overall_score < 45
        assert result.recommendation == AtsRecommendation.WEAK_MATCH

    def test_score_is_always_bounded(self):
        for similarity in (0.0, 0.5, 1.0):
            result = score_application(
                make_job(), make_candidate(), semantic_similarity=similarity
            )
            assert 0 <= result.overall_score <= 100

    def test_is_deterministic(self):
        first = score_application(make_job(), make_candidate(), semantic_similarity=0.6)
        second = score_application(make_job(), make_candidate(), semantic_similarity=0.6)
        assert first.overall_score == second.overall_score

    def test_explanation_covers_every_component(self):
        result = score_application(make_job(), make_candidate(), semantic_similarity=0.6)
        components = result.explanation["components"]
        for name in ("skills", "experience", "education", "responsibilities", "semantic"):
            assert name in components
            assert components[name]["explanation"], f"{name} must explain itself"

    def test_contributions_sum_to_the_overall_score(self):
        result = score_application(make_job(), make_candidate(), semantic_similarity=0.6)
        total = sum(c["contribution"] for c in result.explanation["components"].values())
        assert total == pytest.approx(result.overall_score, abs=0.05)

    def test_skill_weight_is_redistributed_when_no_skills_are_specified(self):
        job = make_job(required_skills=[], preferred_skills=[], certifications=[],
                       skill_weights={})
        result = score_application(job, make_candidate(), semantic_similarity=0.5)
        assert result.weights_used["skills"] == 0
        assert sum(result.weights_used.values()) == pytest.approx(1.0)
        assert any("redistributed" in note for note in result.explanation["notes"])

    def test_output_carries_a_human_decision_disclaimer(self):
        result = score_application(make_job(), make_candidate(), semantic_similarity=0.5)
        assert any("not a hiring decision" in note for note in result.explanation["notes"])


# ---------------------------------------------------------------- ranking
class TestRanking:
    def test_dense_ranking_with_ties(self):
        ranks = compute_ranks([("a", 94.0), ("b", 91.0), ("c", 91.0), ("d", 80.0)])
        assert ranks == {"a": 1, "b": 2, "c": 2, "d": 4}

    def test_empty_input(self):
        assert compute_ranks([]) == {}

    def test_order_of_input_does_not_matter(self):
        forwards = compute_ranks([("a", 90.0), ("b", 80.0)])
        backwards = compute_ranks([("b", 80.0), ("a", 90.0)])
        assert forwards == backwards


class TestRecommendation:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (95, AtsRecommendation.STRONG_MATCH),
            (85, AtsRecommendation.STRONG_MATCH),
            (75, AtsRecommendation.GOOD_MATCH),
            (55, AtsRecommendation.PARTIAL_MATCH),
            (20, AtsRecommendation.WEAK_MATCH),
        ],
    )
    def test_thresholds(self, score, expected):
        assert recommend(score) == expected

    def test_custom_thresholds_are_honoured(self):
        assert recommend(75, {"strong": 70, "good": 60, "partial": 40}) == (
            AtsRecommendation.STRONG_MATCH
        )
