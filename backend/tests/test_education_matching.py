"""Regression tests for degree-level detection.

Both bugs covered here were found by inspecting real seeded output, not by a failing
assertion, so they are pinned explicitly: substring matching silently inflated education
scores, which directly changes how candidates rank.
"""

from __future__ import annotations

import pytest

from app.modules.ats.engine import (
    CandidateProfile,
    JobRequirements,
    infer_education_level,
    requirement_to_level,
    score_education,
)
from app.providers.ai.heuristic import HeuristicAIProvider


class TestDegreeInference:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ("B.Tech in Computer Science from IIT Bombay", "BACHELORS"),
            ("B.E. in Information Technology, COEP Pune", "BACHELORS"),
            ("B.Sc in Computer Science, Madras University", "BACHELORS"),
            ("B.Com, Delhi University", "BACHELORS"),
            ("B.Des in Interaction Design from NID Ahmedabad", "BACHELORS"),
            ("Bachelor of Engineering", "BACHELORS"),
            ("MBA in Analytics from NMIMS Mumbai", "MASTERS"),
            ("M.Tech in Computer Science, IIIT Hyderabad", "MASTERS"),
            ("M.Sc in Statistics, University of Pune", "MASTERS"),
            ("Master of Science", "MASTERS"),
            ("PhD in Machine Learning", "DOCTORATE"),
            ("Ph.D, Indian Institute of Science", "DOCTORATE"),
            ("Diploma in Mechanical Engineering", "DIPLOMA"),
            ("Higher Secondary, Mumbai", "HIGH_SCHOOL"),
        ],
    )
    def test_recognises_common_degrees(self, entry, expected):
        assert infer_education_level([entry]) == expected

    @pytest.mark.parametrize(
        ("entry", "wrong_level"),
        [
            # "mba" is a substring of "Bombay" - the original bug.
            ("B.Tech in Computer Science from IIT Bombay", "MASTERS"),
            ("B.Sc from Mumbai University", "MASTERS"),
            ("Diploma from Coimbatore", "MASTERS"),
        ],
    )
    def test_place_names_do_not_promote_the_level(self, entry, wrong_level):
        """A city name must never be read as a qualification."""
        assert infer_education_level([entry]) != wrong_level

    def test_takes_the_highest_level_held(self):
        assert infer_education_level(["B.Tech, NIT", "M.Tech, IIT"]) == "MASTERS"
        assert infer_education_level(["B.Sc", "PhD in Physics"]) == "DOCTORATE"

    def test_unrecognised_text_returns_none(self):
        assert infer_education_level(["Attended some courses"]) is None
        assert infer_education_level([]) is None

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Bachelor's degree", "BACHELORS"),
            ("Master's degree", "MASTERS"),
            ("Doctorate", "DOCTORATE"),
            ("Diploma", "DIPLOMA"),
            ("High school", "HIGH_SCHOOL"),
        ],
    )
    def test_job_requirements_map_to_levels(self, requirement, expected):
        assert requirement_to_level(requirement) == expected


class TestEducationScoringIsNotInflated:
    def test_bombay_graduate_does_not_satisfy_a_masters_requirement(self):
        """The end-to-end consequence of the substring bug: a wrongly full score."""
        component = score_education(
            JobRequirements(education_requirements=["Master's degree"]),
            CandidateProfile(
                education_level=None,
                education_entries=["B.Tech in Computer Science from IIT Bombay"],
            ),
        )
        assert component.score < 100
        assert component.details["candidate"] == "BACHELORS"

    def test_genuine_masters_still_scores_full(self):
        component = score_education(
            JobRequirements(education_requirements=["Master's degree"]),
            CandidateProfile(
                education_level=None,
                education_entries=["MBA in Analytics from NMIMS Mumbai"],
            ),
        )
        assert component.score == 100


class TestParserSharesTheSameLogic:
    """The parser and the scorer must never disagree about what a degree line means."""

    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ("B.Tech in Computer Science from IIT Bombay", "BACHELORS"),
            ("MBA in Analytics from NMIMS Mumbai", "MASTERS"),
            ("PhD in Machine Learning", "DOCTORATE"),
        ],
    )
    def test_parser_agrees_with_engine(self, entry, expected):
        provider = HeuristicAIProvider()
        assert provider._degree_level(entry) == expected
        assert infer_education_level([entry]) == expected


class TestDateSeparatorWordBoundary:
    """The other substring bug: 'to' matching inside ordinary words."""

    @pytest.mark.parametrize(
        "line",
        [
            "QA Automation Engineer at Practo    Jan 2021 - Present",
            "Automation Lead at Toronto Labs    Mar 2019 - Mar 2021",
            "Data Scientist at Octopus    Feb 2020 - Present",
        ],
    )
    async def test_roles_containing_to_are_still_parsed(self, line):
        provider = HeuristicAIProvider()
        text = f"Test Person\ntest@example.test\n\nEXPERIENCE\n{line}\n- Did the work\n"
        parsed = (await provider.parse_resume(text=text)).value
        assert len(parsed.experience) == 1, f"failed to parse: {line}"
        assert parsed.experience[0].start_date is not None

    async def test_explicit_to_separator_still_works(self):
        provider = HeuristicAIProvider()
        text = (
            "Test Person\ntest@example.test\n\nEXPERIENCE\n"
            "Engineer at Acme    Jan 2020 to Jan 2023\n- Did the work\n"
        )
        parsed = (await provider.parse_resume(text=text)).value
        assert len(parsed.experience) == 1
        assert parsed.experience[0].end_date is not None
