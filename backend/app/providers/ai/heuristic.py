"""Deterministic, credential-free AI provider.

This is **not** a stub that fabricates plausible output. Every method here does real
work with real algorithms - section-aware resume parsing, vocabulary-driven skill
extraction, TF-IDF cosine for semantic similarity, template-driven summarisation and a
rule-based intent router for the assistant. It is the default so the whole product runs
and can be evaluated without an API key.

What it is not is a language model, and it never claims to be: ``is_real_model`` is
False, ``name`` is ``heuristic-v1``, and every response is tagged with that engine so
the UI can label it accurately (s69).
"""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

# Shared with the ATS engine so the parser and the scorer never disagree about what a
# degree line means. Matching there is word-bounded: plain substring matching finds "mba"
# inside "Bombay" and silently promotes the candidate's education level.
from app.modules.ats.engine import _LEVEL_PATTERNS
from app.modules.ats.engine import infer_education_level as _infer_education_level
from app.providers.ai.base import (
    AIProvider,
    AIResult,
    AIUsage,
    AssistantContext,
    AssistantTool,
)
from app.providers.ai.schemas import (
    AssistantAnswer,
    AssistantToolCall,
    CandidateSummary,
    ExtractedSkill,
    FeedbackSummary,
    JobDescriptionAnalysis,
    ParsedEducation,
    ParsedExperience,
    ParsedResume,
    SemanticAssessment,
)
from app.utils.skills import (
    categorise_skill,
    display_skill,
    extract_skills,
    normalise_skill,
)
from app.utils.text import (
    PRESENT_RE,
    cosine,
    extract_emails,
    extract_github,
    extract_linkedin,
    extract_phones,
    extract_urls,
    months_between,
    normalise,
    parse_loose_date,
    split_bullets,
    split_lines,
    tokenize,
    truncate,
)

ENGINE_NAME = "heuristic-v1"

# ------------------------------------------------------------------ patterns
_EXPERIENCE_YEARS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:\+|plus)?\s*(?:-|to|–)?\s*(\d+(?:\.\d+)?)?\s*\+?\s*"
    r"(?:years?|yrs?)\s*(?:of\s+)?(?:relevant\s+|professional\s+|hands[- ]on\s+)?(?:experience)?",
    re.IGNORECASE,
)

_SENIORITY_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("LEAD", ("lead", "principal", "staff", "head of", "director", "vp ", "chief")),
    ("SENIOR", ("senior", "sr.", "sr ", "iii", "specialist", "architect")),
    ("MID", ("mid-level", "mid level", "ii", "associate")),
    ("JUNIOR", ("junior", "jr.", "jr ", "entry level", "entry-level", "graduate", "fresher")),
    ("INTERN", ("intern", "internship", "trainee", "apprentice")),
]

#: Resume section headings, mapped to the canonical section they open.
_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("summary", re.compile(r"^\s*(professional\s+)?(summary|profile|objective|about(\s+me)?)\b", re.I)),
    ("experience", re.compile(r"^\s*(work\s+|professional\s+|employment\s+)?(experience|history|employment)\b", re.I)),
    ("education", re.compile(r"^\s*(education|academic|qualification)", re.I)),
    ("skills", re.compile(r"^\s*(technical\s+)?(skills|competenc|technolog|expertise|tech\s+stack)", re.I)),
    ("projects", re.compile(r"^\s*(projects?|portfolio)\b", re.I)),
    ("certifications", re.compile(r"^\s*(certification|certificate|licen[sc]e|credential)", re.I)),
    ("achievements", re.compile(r"^\s*(achievement|award|honou?r|accomplishment)", re.I)),
    ("languages", re.compile(r"^\s*languages?\b", re.I)),
]

_RESPONSIBILITY_VERBS = (
    "build", "design", "develop", "lead", "manage", "own", "deliver", "implement",
    "maintain", "collaborate", "drive", "create", "optimise", "optimize", "architect",
    "mentor", "review", "test", "deploy", "analyse", "analyze", "support", "coordinate",
    "write", "ship", "scale", "integrate", "migrate", "automate", "monitor", "improve",
)

_EMPLOYMENT_SEPARATORS = re.compile(r"\s+(?:at|@|[-–|,])\s+")

#: Separator between the two halves of a date range. ``to`` is word-bounded so it cannot
#: match inside a company or job title (e.g. "Practo", "QA Automation Engineer").
_DATE_SEPARATOR_RE = re.compile(r"\s*(?:[-–—]|\bto\b)\s*", re.IGNORECASE)


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


class HeuristicAIProvider(AIProvider):
    name = ENGINE_NAME
    is_real_model = False

    # ------------------------------------------------------ job description
    async def analyze_job_description(
        self, *, title: str, description: str, extra_context: str | None = None
    ) -> AIResult:
        started = _now_ms()
        blob = "\n".join(filter(None, [title, description, extra_context or ""]))

        required_names, preferred_names = self._split_requirements(description, blob)

        required = [
            ExtractedSkill(
                name=display_skill(s), importance="REQUIRED", category=categorise_skill(s)
            )
            for s in required_names
        ]
        preferred = [
            ExtractedSkill(
                name=display_skill(s), importance="PREFERRED", category=categorise_skill(s)
            )
            for s in preferred_names
        ]

        min_years, max_years = self._extract_experience_range(blob)
        analysis = JobDescriptionAnalysis(
            required_skills=required,
            preferred_skills=preferred,
            min_experience_years=min_years,
            max_experience_years=max_years,
            education_requirements=self._extract_education_requirements(blob),
            certifications=self._extract_certifications(blob),
            responsibilities=self._extract_responsibilities(description),
            keywords=self._top_keywords(blob),
            technical_skills=[s.name for s in required + preferred if s.category == "TECHNICAL"],
            soft_skills=[s.name for s in required + preferred if s.category == "SOFT"],
            seniority=self._detect_seniority(f"{title} {description}"),
            # Confidence reflects how much structure was actually found, so a thin
            # description honestly reports that the extraction is shaky.
            confidence=self._analysis_confidence(required, preferred, description),
        )
        return AIResult(
            value=analysis,
            usage=AIUsage(engine=self.name, latency_ms=_now_ms() - started),
        )

    def _split_requirements(self, description: str, blob: str) -> tuple[list[str], list[str]]:
        """Separate must-haves from nice-to-haves using section headings.

        Falls back to "everything is required" when the description has no such split,
        which is the safe default: over-reporting preferred skills would understate the
        real bar for the role.
        """
        preferred_zone = self._section_text(
            description,
            re.compile(
                r"^\s*(preferred|nice[\s-]to[\s-]have|good[\s-]to[\s-]have|bonus|plus|desirable|"
                r"optional|advantage)",
                re.I,
            ),
        )
        preferred = extract_skills(preferred_zone) if preferred_zone else []
        preferred_keys = {normalise_skill(s) for s in preferred}

        all_skills = extract_skills(blob)
        required = [s for s in all_skills if normalise_skill(s) not in preferred_keys]
        return required, preferred

    @staticmethod
    def _section_text(text: str, heading: re.Pattern[str]) -> str:
        """Return the lines under the first heading matching ``heading``."""
        lines = text.splitlines()
        collected: list[str] = []
        capturing = False
        for line in lines:
            if heading.search(line):
                capturing = True
                continue
            if capturing:
                # A new short, title-like line ends the section.
                stripped = line.strip()
                if stripped and len(stripped) < 60 and stripped.endswith(":"):
                    break
                if re.match(r"^\s*(requirement|responsibilit|about|benefit|what we offer)", line, re.I):
                    break
                collected.append(line)
        return "\n".join(collected)

    @staticmethod
    def _extract_experience_range(text: str) -> tuple[float, float | None]:
        matches = _EXPERIENCE_YEARS_RE.findall(text)
        if not matches:
            return 0.0, None
        lows: list[float] = []
        highs: list[float] = []
        for low, high in matches:
            try:
                low_val = float(low)
            except ValueError:
                continue
            if low_val > 40:  # a stray number, not a span of years
                continue
            lows.append(low_val)
            if high:
                try:
                    high_val = float(high)
                    if high_val <= 45:
                        highs.append(high_val)
                except ValueError:
                    pass
        if not lows:
            return 0.0, None
        return min(lows), (max(highs) if highs else None)

    @staticmethod
    def _extract_education_requirements(text: str) -> list[str]:
        found: list[str] = []
        lowered = normalise(text)
        for level, pattern in _LEVEL_PATTERNS:
            if pattern.search(lowered):
                label = {
                    "DOCTORATE": "Doctorate",
                    "MASTERS": "Master's degree",
                    "BACHELORS": "Bachelor's degree",
                    "DIPLOMA": "Diploma",
                    "HIGH_SCHOOL": "High school",
                }[level]
                found.append(label)
        return found[:3]

    @staticmethod
    def _extract_certifications(text: str) -> list[str]:
        pattern = re.compile(
            r"\b((?:aws|azure|gcp|google|microsoft|oracle|cisco|comptia|pmp|scrum|safe|"
            r"kubernetes|cka|ckad|itil|six sigma)[\w\s\-]{0,40}?"
            r"(?:certified|certification|certificate|professional|associate|practitioner))\b",
            re.IGNORECASE,
        )
        seen: dict[str, None] = {}
        for match in pattern.finditer(text):
            value = " ".join(match.group(1).split()).title()
            seen.setdefault(value, None)
        return list(seen)[:8]

    @staticmethod
    def _extract_responsibilities(description: str) -> list[str]:
        candidates = split_bullets(description)
        results = [
            line
            for line in candidates
            if 15 <= len(line) <= 300
            and any(line.lower().startswith(v) or f" {v}" in line.lower()[:40] for v in _RESPONSIBILITY_VERBS)
        ]
        if not results:
            results = [line for line in candidates if 25 <= len(line) <= 300][:8]
        return results[:12]

    @staticmethod
    def _top_keywords(text: str, limit: int = 20) -> list[str]:
        counts = Counter(tokenize(text))
        return [word for word, _ in counts.most_common(limit) if len(word) > 2]

    @staticmethod
    def _detect_seniority(text: str) -> str | None:
        lowered = normalise(text)
        for level, hints in _SENIORITY_HINTS:
            if any(h in lowered for h in hints):
                return level
        return None

    @staticmethod
    def _analysis_confidence(
        required: list[ExtractedSkill], preferred: list[ExtractedSkill], description: str
    ) -> float:
        score = 0.3
        if required:
            score += min(0.35, 0.05 * len(required))
        if preferred:
            score += 0.1
        if len(description) > 600:
            score += 0.15
        if split_bullets(description):
            score += 0.1
        return round(min(score, 0.9), 2)

    # ------------------------------------------------------------- resumes
    async def parse_resume(self, *, text: str, hint_name: str | None = None) -> AIResult:
        started = _now_ms()
        sections = self._split_sections(text)

        emails = extract_emails(text)
        phones = extract_phones(text)
        experience = self._parse_experience(sections.get("experience", ""))
        education = self._parse_education(sections.get("education", ""))

        skills_text = sections.get("skills") or text
        skills = extract_skills(skills_text)
        if len(skills) < 5:
            # Skills sections are often absent; fall back to the whole document.
            skills = list(dict.fromkeys(skills + extract_skills(text)))

        total_years = self._total_experience_years(experience)
        current = next((e for e in experience if e.is_current), None)
        if current is None and experience:
            current = experience[0]

        parsed = ParsedResume(
            name=hint_name or self._parse_name(text, emails),
            email=emails[0] if emails else None,
            phone=phones[0] if phones else None,
            location=self._parse_location(text),
            linkedin_url=extract_linkedin(text),
            github_url=extract_github(text),
            portfolio_url=self._parse_portfolio(text),
            summary=truncate(sections.get("summary", "").strip(), 800) or None,
            current_designation=current.position if current else None,
            current_company=current.company if current else None,
            total_experience_years=total_years,
            skills=skills,
            experience=experience,
            education=education,
            certifications=split_bullets(sections.get("certifications", ""))[:15],
            projects=split_bullets(sections.get("projects", ""))[:15],
            achievements=split_bullets(sections.get("achievements", ""))[:15],
            languages=self._parse_languages(sections.get("languages", "")),
        )

        parsed.missing_fields = [
            field
            for field, value in (
                ("email", parsed.email),
                ("phone", parsed.phone),
                ("name", parsed.name),
                ("skills", parsed.skills),
                ("experience", parsed.experience),
                ("education", parsed.education),
            )
            if not value
        ]
        parsed.confidence = self._parse_confidence(parsed, text)
        if len(text.strip()) < 200:
            parsed.warnings.append(
                "Very little text was extracted - the file may be a scanned image "
                "rather than a text document."
            )
        if not experience and "experience" not in sections:
            parsed.warnings.append("No work-experience section was detected.")

        return AIResult(
            value=parsed, usage=AIUsage(engine=self.name, latency_ms=_now_ms() - started)
        )

    @staticmethod
    def _split_sections(text: str) -> dict[str, str]:
        """Bucket resume lines by heading. Unheaded leading text becomes ``summary``."""
        sections: dict[str, list[str]] = {}
        current = "header"
        for line in text.splitlines():
            matched = None
            stripped = line.strip()
            # Headings are short lines; a long sentence containing "Experience" is prose.
            if stripped and len(stripped) <= 60:
                for name, pattern in _SECTION_PATTERNS:
                    if pattern.search(stripped):
                        matched = name
                        break
            if matched:
                current = matched
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)
        result = {k: "\n".join(v).strip() for k, v in sections.items()}
        if "summary" not in result and result.get("header"):
            header_lines = split_lines(result["header"])
            prose = [ln for ln in header_lines if len(ln) > 80]
            if prose:
                result["summary"] = " ".join(prose[:3])
        return result

    @staticmethod
    def _parse_name(text: str, emails: list[str]) -> str | None:
        """The name is almost always the first substantial non-contact line."""
        for line in split_lines(text)[:8]:
            if len(line) > 60 or "@" in line or any(c.isdigit() for c in line):
                continue
            if re.search(r"(resume|curriculum vitae|cv)\b", line, re.I):
                continue
            words = line.replace(",", " ").split()
            if 1 < len(words) <= 5 and all(w[:1].isalpha() for w in words):
                # Reject all-caps section headings that slipped through.
                if line.isupper() and len(words) > 3:
                    continue
                return " ".join(w.capitalize() if w.isupper() else w for w in words)
        if emails:
            local = emails[0].split("@")[0]
            parts = re.split(r"[._\-0-9]+", local)
            parts = [p for p in parts if len(p) > 1]
            if len(parts) >= 2:
                return " ".join(p.capitalize() for p in parts[:3])
        return None

    @staticmethod
    def _parse_location(text: str) -> str | None:
        pattern = re.compile(
            r"^\s*(?:address|location|based in|city)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE
        )
        if match := pattern.search(text):
            return truncate(match.group(1).strip(), 120)
        # "Bengaluru, Karnataka, India" style lines near the top of the document.
        for line in split_lines(text)[:12]:
            if 5 < len(line) < 70 and line.count(",") in (1, 2) and "@" not in line:
                if not any(ch.isdigit() for ch in line) and not line.endswith(":"):
                    words = line.split()
                    if 2 <= len(words) <= 6 and words[0][:1].isupper():
                        return line.strip()
        return None

    @staticmethod
    def _parse_portfolio(text: str) -> str | None:
        for url in extract_urls(text):
            lowered = url.lower()
            if any(host in lowered for host in ("linkedin.com", "github.com", "mailto:")):
                continue
            return url
        return None

    def _parse_experience(self, block: str) -> list[ParsedExperience]:
        if not block.strip():
            return []
        entries: list[ParsedExperience] = []
        current: ParsedExperience | None = None

        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            date_range = self._find_date_range(line)
            is_bullet = bool(re.match(r"^[\-•●▪*–—·]|\s{2,}[\-•]", raw_line)) or raw_line.startswith(
                ("    ", "\t")
            )

            if date_range and not is_bullet:
                start, end, is_current = date_range
                company, position = self._split_company_position(
                    _EXPERIENCE_YEARS_RE.sub("", self._strip_dates(line)).strip(" -–|,")
                )
                current = ParsedExperience(
                    company=company,
                    position=position,
                    start_date=start.isoformat() if start else None,
                    end_date=end.isoformat() if end else None,
                    is_current=is_current,
                )
                entries.append(current)
                continue

            if current is None:
                # A dateless line only opens a role if it actually looks like a role
                # header. Without this guard, prose under the heading ("No professional
                # experience yet - recent graduate.") is split on its hyphen and becomes
                # a phantom job.
                if not is_bullet and self._looks_like_role_header(line):
                    company, position = self._split_company_position(line)
                    if company or position:
                        current = ParsedExperience(company=company, position=position)
                        entries.append(current)
                continue

            cleaned = re.sub(r"^[\-•●▪*–—·]\s*", "", line).strip()
            if cleaned and len(cleaned) > 10:
                current.responsibilities.append(truncate(cleaned, 300))
                current.technologies = list(
                    dict.fromkeys(current.technologies + extract_skills(cleaned, limit=10))
                )

        return [e for e in entries if e.company or e.position][:15]

    @staticmethod
    def _looks_like_role_header(line: str) -> bool:
        """Whether a dateless line plausibly names a job rather than being prose.

        Resume experience sections mix role headers with narrative text. Treating every
        short line as a job produces phantom entries that then distort experience totals
        and the responsibilities match, so the bar here is deliberately conservative.
        """
        stripped = line.strip()
        if not 3 < len(stripped) < 120:
            return False
        # Sentences end in punctuation; role headers almost never do.
        if stripped.endswith((".", "!", "?", ":", ";")):
            return False
        lowered = stripped.lower()
        if any(
            lowered.startswith(prefix)
            for prefix in (
                "no ", "none", "not ", "n/a", "seeking", "looking for", "available",
                "i ", "my ", "recent graduate", "fresher",
            )
        ):
            return False
        words = stripped.split()
        if len(words) > 14:
            return False
        # Prose is mostly lowercase; a role header carries proper nouns.
        capitalised = sum(1 for w in words if w[:1].isupper())
        return capitalised >= max(1, len(words) // 3)

    @staticmethod
    def _strip_dates(line: str) -> str:
        return re.sub(
            r"\(?\b(\d{4}|\w{3,9}\.?\s+\d{4}|\d{1,2}[/-]\d{4})\b\)?"
            r"(\s*(?:-|–|to)\s*\(?\b(\d{4}|\w{3,9}\.?\s+\d{4}|\d{1,2}[/-]\d{4}|present|current)\b\)?)?",
            "",
            line,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _find_date_range(line: str) -> tuple[date | None, date | None, bool] | None:
        """Detect ``Mar 2021 - Present`` / ``2019 – 2022`` style ranges."""
        # ``to`` must be word-bounded: without \b it matches inside ordinary words
        # ("QA Automation Engineer", "Practo"), splitting the line at the wrong place
        # and losing the role entirely.
        separator = re.search(_DATE_SEPARATOR_RE, line)
        if not separator:
            single = parse_loose_date(line)
            return None if single is None else (single, None, False)

        left, right = line[: separator.start()], line[separator.end() :]
        start = parse_loose_date(left)
        if start is None:
            return None
        if PRESENT_RE.search(right[:30]):
            return start, None, True
        end = parse_loose_date(right, prefer_end=True)
        if end is None:
            return None
        return start, end, False

    @staticmethod
    def _split_company_position(text: str) -> tuple[str, str]:
        text = text.strip(" .,;|-–")
        if not text:
            return "", ""
        parts = [p.strip() for p in _EMPLOYMENT_SEPARATORS.split(text) if p.strip()]
        if len(parts) >= 2:
            # Convention across resumes is "Position at Company" far more often than
            # the reverse, so treat the first fragment as the role.
            return parts[1], parts[0]
        return "", parts[0] if parts else ""

    @staticmethod
    def _total_experience_years(experience: list[ParsedExperience]) -> float:
        """Sum experience by merging overlapping ranges, so concurrent roles are not
        double-counted into an inflated total."""
        spans: list[tuple[date, date]] = []
        today = date.today()
        for entry in experience:
            if not entry.start_date:
                continue
            try:
                start = date.fromisoformat(entry.start_date)
            except ValueError:
                continue
            end = today
            if entry.end_date:
                try:
                    end = date.fromisoformat(entry.end_date)
                except ValueError:
                    end = today
            if end < start:
                continue
            spans.append((start, min(end, today)))

        if not spans:
            return 0.0
        spans.sort()
        merged: list[list[date]] = [list(spans[0])]
        for start, end in spans[1:]:
            if start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        total_months = sum(months_between(s, e) for s, e in merged)
        return round(total_months / 12, 1)

    def _parse_education(self, block: str) -> list[ParsedEducation]:
        if not block.strip():
            return []
        entries: list[ParsedEducation] = []
        for line in split_lines(block):
            level = self._degree_level(line)
            years = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", line)]
            if not level and not years:
                continue
            grade_match = re.search(
                r"(?:cgpa|gpa|percentage|marks)\s*[:\-]?\s*([\d.]+\s*%?)", line, re.IGNORECASE
            )
            institution = re.search(
                r"(?:from|at)\s+([A-Z][\w.&,\- ]{3,60})", line
            )
            entries.append(
                ParsedEducation(
                    degree=truncate(re.sub(r"\s{2,}", " ", line).strip(" .,;|-"), 200),
                    degree_level=level,
                    institution=institution.group(1).strip() if institution else None,
                    start_year=min(years) if len(years) > 1 else None,
                    end_year=max(years) if years else None,
                    grade=grade_match.group(1).strip() if grade_match else None,
                )
            )
        return entries[:10]

    @staticmethod
    def _degree_level(text: str) -> str | None:
        """Degree level for one education line, using the shared word-bounded matcher."""
        return _infer_education_level([text])

    @staticmethod
    def _parse_languages(block: str) -> list[str]:
        if not block.strip():
            return []
        raw = re.split(r"[,;|\n•●▪]", block)
        out: list[str] = []
        for item in raw:
            cleaned = re.sub(r"\((.*?)\)", "", item).strip(" .-:")
            if 2 <= len(cleaned) <= 30 and cleaned.replace(" ", "").isalpha():
                out.append(cleaned.title())
        return list(dict.fromkeys(out))[:10]

    @staticmethod
    def _parse_confidence(parsed: ParsedResume, text: str) -> float:
        score = 0.0
        if parsed.email:
            score += 0.2
        if parsed.phone:
            score += 0.12
        if parsed.name:
            score += 0.15
        if parsed.skills:
            score += min(0.2, 0.02 * len(parsed.skills))
        if parsed.experience:
            score += min(0.2, 0.05 * len(parsed.experience))
        if parsed.education:
            score += 0.1
        if len(text) < 300:
            score *= 0.5
        return round(min(score, 0.92), 2)

    # ----------------------------------------------------------- summaries
    async def summarize_candidate(
        self, *, candidate_profile: dict, job_context: dict | None = None
    ) -> AIResult:
        started = _now_ms()
        name = candidate_profile.get("full_name") or "This candidate"
        years = candidate_profile.get("total_experience_years") or 0
        designation = candidate_profile.get("current_designation")
        company = candidate_profile.get("current_company")
        skills: list[str] = candidate_profile.get("skills") or []

        parts: list[str] = []
        if designation and company:
            parts.append(f"{name} is currently a {designation} at {company}")
        elif designation:
            parts.append(f"{name} is currently a {designation}")
        else:
            parts.append(f"{name} is an applicant")
        if years:
            parts.append(f"with {years} year{'s' if float(years) != 1 else ''} of experience")
        if skills:
            parts.append(f"working mainly with {', '.join(skills[:5])}")

        summary = ", ".join(parts) + "."
        education = candidate_profile.get("education") or []
        if education:
            summary += f" Highest qualification on file: {education[0]}."

        strengths = [display_skill(s) for s in skills[:5]]
        considerations: list[str] = []
        if job_context:
            missing = job_context.get("missing_skills") or []
            considerations = [
                f"No evidence of {display_skill(s)} in the profile" for s in missing[:4]
            ]
            required_years = job_context.get("min_experience_years")
            if required_years and float(years or 0) < float(required_years):
                considerations.append(
                    f"{years} years of experience against {required_years} required"
                )
        if not candidate_profile.get("email_verified"):
            considerations.append("Email address is not yet verified")

        return AIResult(
            value=CandidateSummary(
                summary=summary, strengths=strengths, considerations=considerations
            ),
            usage=AIUsage(engine=self.name, latency_ms=_now_ms() - started),
        )

    async def summarize_interview_feedback(
        self, *, feedback_items: list[dict], candidate_name: str, job_title: str
    ) -> AIResult:
        started = _now_ms()
        if not feedback_items:
            return AIResult(
                value=FeedbackSummary(summary="No feedback has been submitted yet."),
                usage=AIUsage(engine=self.name, latency_ms=_now_ms() - started),
            )

        ratings = [float(f["overall_rating"]) for f in feedback_items if f.get("overall_rating")]
        average = round(sum(ratings) / len(ratings), 2) if ratings else None
        recommendations = [f.get("recommendation") for f in feedback_items if f.get("recommendation")]
        counts = Counter(recommendations)
        consensus = counts.most_common(1)[0][0] if counts else None
        if consensus and len(set(recommendations)) > 1:
            positives = sum(counts[r] for r in ("STRONG_HIRE", "HIRE") if r in counts)
            negatives = counts.get("NO_HIRE", 0)
            if positives and negatives:
                consensus = "MIXED"

        strengths: list[str] = []
        weaknesses: list[str] = []
        for item in feedback_items:
            strengths.extend(split_bullets(item.get("strengths") or ""))
            weaknesses.extend(split_bullets(item.get("weaknesses") or ""))

        rounds = len(feedback_items)
        summary = (
            f"{rounds} interviewer{'s have' if rounds != 1 else ' has'} submitted feedback for "
            f"{candidate_name} ({job_title})."
        )
        if average is not None:
            summary += f" Average overall rating {average}/5."
        if consensus:
            summary += f" Recommendation trend: {consensus.replace('_', ' ').title()}."
        summary += " Final hiring decision rests with the recruiting team."

        return AIResult(
            value=FeedbackSummary(
                summary=summary,
                strengths=list(dict.fromkeys(strengths))[:8],
                weaknesses=list(dict.fromkeys(weaknesses))[:8],
                consensus=consensus,
            ),
            usage=AIUsage(engine=self.name, latency_ms=_now_ms() - started),
        )

    # ------------------------------------------------------------ semantic
    async def assess_semantic_fit(self, *, job_text: str, resume_text: str) -> AIResult:
        started = _now_ms()
        similarity_score = tfidf_cosine(job_text, resume_text)
        return AIResult(
            value=SemanticAssessment(
                similarity=similarity_score,
                rationale=(
                    "Lexical TF-IDF cosine similarity between the job description and the "
                    "resume text. Computed locally without a language model."
                ),
            ),
            usage=AIUsage(engine=self.name, latency_ms=_now_ms() - started),
        )

    # ----------------------------------------------------------- assistant
    async def answer_recruiter_question(
        self,
        *,
        question: str,
        tools: list[AssistantTool],
        context: AssistantContext,
        history: list[dict] | None = None,
    ) -> AIResult:
        """Rule-based intent routing over the same tools the LLM provider gets.

        This is genuinely useful for the common questions in s41, and it is explicitly
        labelled ``heuristic-v1`` so nobody mistakes it for a conversational model.
        """
        started = _now_ms()
        tool_map = {t.name: t for t in tools}
        lowered = question.lower()

        intent, arguments = self._route_intent(lowered, tool_map)
        calls: list[AssistantToolCall] = []
        data: dict[str, Any] | None = None
        answer: str

        if intent and intent in tool_map:
            try:
                result = await tool_map[intent].handler(**arguments)
                data = result if isinstance(result, dict) else {"result": result}
                calls.append(
                    AssistantToolCall(
                        name=intent,
                        arguments=arguments,
                        result_summary=truncate(str(data), 300),
                    )
                )
                answer = self._render_answer(intent, data, question)
            except Exception as exc:  # surfaced, not swallowed
                answer = f"I could not complete that lookup: {exc}"
        else:
            answer = (
                "I can answer questions about your jobs, applications, candidates, "
                "interviews and pipeline. This server is running the built-in rule-based "
                "assistant, which understands a fixed set of questions. Configure an AI "
                "provider (AI_PROVIDER=anthropic) for free-form conversation."
            )

        return AIResult(
            value=AssistantAnswer(
                answer=answer,
                engine=self.name,
                tool_calls=calls,
                data=data,
                suggestions=[
                    "Show me the top candidates for <job title>",
                    "Which candidates are waiting for interview feedback?",
                    "How many applications did we receive this week?",
                    "Show candidates with ATS score above 85",
                    "What are today's interviews?",
                ],
            ),
            usage=AIUsage(engine=self.name, latency_ms=_now_ms() - started),
        )

    @staticmethod
    def _route_intent(
        lowered: str, tool_map: dict[str, AssistantTool]
    ) -> tuple[str | None, dict[str, Any]]:
        def has(*words: str) -> bool:
            return all(w in lowered for w in words)

        threshold = None
        if match := re.search(r"(?:above|over|greater than|>=?|at least)\s*(\d{1,3})", lowered):
            threshold = float(match.group(1))

        job_title = None
        if match := re.search(
            r"(?:for|on)\s+(?:the\s+)?(?:role\s+of\s+|position\s+of\s+)?([\w\s/+.#-]{3,60}?)"
            r"\s*(?:role|position|job|opening)?\s*[?.]?$",
            lowered,
        ):
            job_title = match.group(1).strip()

        if has("pending") and "feedback" in lowered or has("waiting", "feedback"):
            return "list_pending_feedback", {}
        if "interview" in lowered and any(w in lowered for w in ("today", "todays", "today's")):
            return "list_todays_interviews", {}
        if "interview" in lowered and any(w in lowered for w in ("upcoming", "week", "scheduled")):
            return "list_upcoming_interviews", {}
        if threshold is not None and ("score" in lowered or "ats" in lowered):
            return "search_candidates", {"min_ats_score": threshold}
        if any(w in lowered for w in ("top", "best", "strongest")) and (
            "candidate" in lowered or "applicant" in lowered
        ):
            return "list_top_candidates", ({"job_title": job_title} if job_title else {})
        if has("how many") or "count" in lowered or "total" in lowered:
            if "application" in lowered:
                period = "week" if "week" in lowered else ("month" if "month" in lowered else "all")
                return "count_applications", {"period": period}
            if "job" in lowered:
                return "pipeline_overview", {}
        if "conversion" in lowered or "funnel" in lowered:
            return "pipeline_overview", {}
        if "summar" in lowered and "candidate_summary" in tool_map:
            if match := re.search(r"summari[sz]e\s+([\w\s.'-]{3,50})", lowered):
                return "candidate_summary", {"candidate_name": match.group(1).strip(" .?")}
        if any(w in lowered for w in ("pipeline", "overview", "dashboard", "status")):
            return "pipeline_overview", {}
        if "candidate" in lowered or "applicant" in lowered:
            return "search_candidates", ({"job_title": job_title} if job_title else {})
        if "job" in lowered or "opening" in lowered or "role" in lowered:
            return "list_jobs", {}
        return None, {}

    @staticmethod
    def _render_answer(intent: str, data: dict, question: str) -> str:
        items = data.get("items")
        total = data.get("total")

        if intent == "count_applications":
            return (
                f"You received {data.get('count', 0)} application"
                f"{'s' if data.get('count', 0) != 1 else ''} in the selected period."
            )
        if intent == "pipeline_overview":
            stages = data.get("stages") or {}
            if not stages:
                return "There is no pipeline activity yet."
            rendered = ", ".join(f"{k.replace('_', ' ').title()}: {v}" for k, v in stages.items() if v)
            return f"Current pipeline - {rendered}."
        if isinstance(items, list):
            if not items:
                return "Nothing matched that query."
            count = total if total is not None else len(items)
            label = {
                "list_top_candidates": "top candidate",
                "search_candidates": "candidate",
                "list_pending_feedback": "interview awaiting feedback",
                "list_todays_interviews": "interview scheduled today",
                "list_upcoming_interviews": "upcoming interview",
                "list_jobs": "job",
            }.get(intent, "result")
            plural = "" if count == 1 else "s"
            preview = "; ".join(
                str(i.get("label") or i.get("name") or i.get("title") or "") for i in items[:5]
            )
            return f"Found {count} {label}{plural}. {preview}".strip()
        return f"Here is what I found for: {truncate(question, 120)}"


def tfidf_cosine(text_a: str, text_b: str) -> float:
    """Cosine similarity of TF-IDF vectors built from just these two documents.

    With a two-document corpus, IDF reduces to down-weighting terms present in both.
    That is exactly the wrong thing for similarity, so this uses sublinear term
    frequency (1 + log tf) with no IDF - a well-behaved choice for short-document
    comparison that avoids penalising the shared vocabulary we actually care about.
    """
    tokens_a, tokens_b = tokenize(text_a), tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0

    import math as _math

    def weight(tokens: list[str]) -> Counter[str]:
        counts = Counter(tokens)
        return Counter({t: 1 + _math.log(c) for t, c in counts.items()})

    # Blend unigram and bigram similarity: bigrams capture phrases like "rest api"
    # that unigram overlap alone would miss.
    unigram = cosine(weight(tokens_a), weight(tokens_b))
    bigrams_a = [" ".join(tokens_a[i : i + 2]) for i in range(len(tokens_a) - 1)]
    bigrams_b = [" ".join(tokens_b[i : i + 2]) for i in range(len(tokens_b) - 1)]
    bigram = cosine(weight(bigrams_a), weight(bigrams_b)) if bigrams_a and bigrams_b else 0.0
    return round(min(1.0, 0.7 * unigram + 0.3 * bigram), 4)


def utcnow_iso() -> str:
    return datetime.now(UTC).date().isoformat()
