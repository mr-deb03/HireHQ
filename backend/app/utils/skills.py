"""Skill vocabulary, normalisation and matching.

The ATS engine must not treat "ReactJS", "React.js" and "React" as three different
skills, nor miss that "Postgres" satisfies a "PostgreSQL" requirement. This module owns
that knowledge in one place so the parser, the matcher and the job analyser agree.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.utils.text import normalise, similarity

#: Canonical form -> the aliases that should collapse onto it.
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "javascript": ("js", "java script", "ecmascript", "es6", "es2015", "vanilla js"),
    "typescript": ("ts",),
    "react": ("reactjs", "react.js", "react js", "react native"),
    "next.js": ("nextjs", "next js"),
    "node.js": ("nodejs", "node", "node js"),
    "vue.js": ("vuejs", "vue", "vue js"),
    "angular": ("angularjs", "angular.js", "angular js"),
    "python": ("python3", "py"),
    "postgresql": ("postgres", "psql", "postgre sql", "postgresql db"),
    "mysql": ("my sql",),
    "mongodb": ("mongo", "mongo db"),
    "amazon web services": ("aws", "amazon aws"),
    "microsoft azure": ("azure",),
    "google cloud platform": ("gcp", "google cloud"),
    "kubernetes": ("k8s", "kube"),
    "docker": ("dockerize", "containerization", "containerisation"),
    "ci/cd": ("cicd", "ci cd", "continuous integration", "continuous delivery"),
    "rest api": ("rest", "restful", "restful api", "rest apis", "restful apis", "api development"),
    "graphql": ("graph ql",),
    "html": ("html5",),
    "css": ("css3", "cascading style sheets"),
    "tailwind css": ("tailwind", "tailwindcss"),
    "c++": ("cpp", "c plus plus"),
    "c#": ("csharp", "c sharp"),
    ".net": ("dotnet", "dot net", "asp.net", "aspnet"),
    "sql": ("structured query language",),
    "machine learning": ("ml",),
    "deep learning": ("dl",),
    "natural language processing": ("nlp",),
    "artificial intelligence": ("ai",),
    "user interface design": ("ui design", "ui"),
    "user experience design": ("ux design", "ux", "ux/ui", "ui/ux"),
    "git": ("github", "gitlab", "version control", "bitbucket"),
    "agile": ("scrum", "kanban", "agile methodology"),
    "spring boot": ("springboot", "spring"),
    "django": ("django rest framework", "drf"),
    "fastapi": ("fast api",),
    "flask": (),
    "redis": (),
    "kafka": ("apache kafka",),
    "elasticsearch": ("elastic search", "elk"),
    "terraform": (),
    "jenkins": (),
    "power bi": ("powerbi",),
    "tableau": (),
    "excel": ("ms excel", "microsoft excel", "advanced excel"),
    "communication": ("communication skills", "verbal communication", "written communication"),
    "leadership": ("team leadership", "people management"),
    "problem solving": ("problem-solving", "analytical thinking", "analytical skills"),
    "teamwork": ("collaboration", "team player", "team work"),
}

#: Reverse map, built once at import.
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in SKILL_ALIASES.items():
    _ALIAS_TO_CANONICAL[normalise(_canonical)] = _canonical
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[normalise(_alias)] = _canonical

SOFT_SKILLS = frozenset(
    {
        "communication", "leadership", "teamwork", "problem solving", "adaptability",
        "time management", "critical thinking", "creativity", "collaboration",
        "mentoring", "stakeholder management", "presentation", "negotiation",
        "ownership", "attention to detail",
    }
)

#: Vocabulary used by the deterministic parser to find skills in free text. Extending it
#: improves the fallback parser; the LLM provider does not depend on it.
KNOWN_SKILLS: frozenset[str] = frozenset(SKILL_ALIASES) | frozenset(
    {
        "java", "go", "golang", "rust", "ruby", "php", "swift", "kotlin", "scala", "r",
        "matlab", "perl", "bash", "shell scripting", "powershell",
        "spring", "hibernate", "express.js", "nestjs", "svelte", "remix", "astro",
        "redux", "zustand", "react query", "webpack", "vite", "babel",
        "sass", "less", "bootstrap", "material ui", "chakra ui", "figma", "adobe xd",
        "sqlite", "oracle", "sql server", "dynamodb", "cassandra", "neo4j", "snowflake",
        "airflow", "spark", "hadoop", "databricks", "dbt", "etl", "data warehousing",
        "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras", "opencv",
        "langchain", "llm", "rag", "vector database", "prompt engineering",
        "rabbitmq", "grpc", "websockets", "microservices", "system design",
        "linux", "nginx", "apache", "ansible", "prometheus", "grafana", "datadog",
        "jira", "confluence", "selenium", "cypress", "playwright", "jest", "pytest",
        "junit", "tdd", "unit testing", "integration testing", "qa automation",
        "seo", "google analytics", "salesforce", "hubspot", "sap", "erp",
        "financial modelling", "accounting", "taxation", "auditing", "payroll",
        "recruitment", "talent acquisition", "onboarding", "employee engagement",
        "content writing", "copywriting", "social media marketing", "email marketing",
        "product management", "roadmapping", "user research", "wireframing",
        "prototyping", "design systems", "accessibility", "wcag",
    }
)

#: Longest-first so "machine learning" is found before "learning".
_SEARCH_VOCABULARY: list[tuple[str, str]] = sorted(
    (
        [(normalise(s), s) for s in KNOWN_SKILLS]
        + list(_ALIAS_TO_CANONICAL.items())
    ),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

TECHNICAL_HINTS = frozenset(
    {"api", "sdk", "framework", "database", "cloud", "language", "library", "protocol"}
)


def normalise_skill(name: str) -> str:
    """Canonical comparison key for a skill. ``ReactJS`` and ``React.js`` -> ``react``."""
    if not name:
        return ""
    key = normalise(name).strip(" .,;:/")
    return _ALIAS_TO_CANONICAL.get(key, key)


#: Correct presentation for skills whose casing is not simple title case. Anything not
#: listed falls back to title case, which is right for ordinary words ("leadership").
DISPLAY_OVERRIDES: dict[str, str] = {
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "rest api": "REST API",
    "graphql": "GraphQL",
    "html": "HTML",
    "css": "CSS",
    "sql": "SQL",
    "nosql": "NoSQL",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "dynamodb": "DynamoDB",
    "sqlite": "SQLite",
    "node.js": "Node.js",
    "next.js": "Next.js",
    "vue.js": "Vue.js",
    "express.js": "Express.js",
    "nestjs": "NestJS",
    "c++": "C++",
    "c#": "C#",
    ".net": ".NET",
    "php": "PHP",
    "ci/cd": "CI/CD",
    "aws": "AWS",
    "gcp": "GCP",
    "amazon web services": "Amazon Web Services",
    "google cloud platform": "Google Cloud Platform",
    "ios": "iOS",
    "macos": "macOS",
    "ui design": "UI Design",
    "ux design": "UX Design",
    "user interface design": "User Interface Design",
    "user experience design": "User Experience Design",
    "qa automation": "QA Automation",
    "etl": "ETL",
    "llm": "LLM",
    "rag": "RAG",
    "nlp": "NLP",
    "natural language processing": "Natural Language Processing",
    "artificial intelligence": "Artificial Intelligence",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "scikit-learn": "scikit-learn",
    "numpy": "NumPy",
    "pandas": "pandas",
    "pytest": "pytest",
    "junit": "JUnit",
    "tdd": "TDD",
    "seo": "SEO",
    "sap": "SAP",
    "erp": "ERP",
    "wcag": "WCAG",
    "dbt": "dbt",
    "jira": "Jira",
    "github": "GitHub",
    "gitlab": "GitLab",
    "nginx": "Nginx",
    "grpc": "gRPC",
    "websockets": "WebSockets",
    "power bi": "Power BI",
    "ms excel": "MS Excel",
    "figma": "Figma",
    "adobe xd": "Adobe XD",
    "material ui": "Material UI",
    "chakra ui": "Chakra UI",
    "tailwind css": "Tailwind CSS",
    "bigquery": "BigQuery",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "spring boot": "Spring Boot",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "golang": "Go",
    "r": "R",
    "go": "Go",
}


def display_skill(name: str) -> str:
    """Presentation form of a skill, preserving acronyms and vendor casing.

    Normalises first, so ``reactjs``, ``React.JS`` and ``react`` all render as ``React``.
    """
    canonical = normalise_skill(name)
    if not canonical:
        return name.strip()
    if canonical in DISPLAY_OVERRIDES:
        return DISPLAY_OVERRIDES[canonical]
    # Preserve any casing the vocabulary itself defines.
    for known in KNOWN_SKILLS:
        if normalise(known) == canonical:
            return DISPLAY_OVERRIDES.get(known, known.title() if known.islower() else known)
    return canonical.title()


def categorise_skill(name: str) -> str:
    canonical = normalise_skill(name)
    if canonical in SOFT_SKILLS:
        return "SOFT"
    if canonical in {normalise(s) for s in KNOWN_SKILLS}:
        return "TECHNICAL"
    return "DOMAIN"


def extract_skills(text: str, *, limit: int = 60) -> list[str]:
    """Find known skills in free text, returned in canonical display form.

    Matching is done on a normalised copy with word boundaries so "R" does not match
    every word containing the letter and "go" does not match "going".
    """
    if not text:
        return []
    haystack = f" {normalise(text)} "
    found: dict[str, None] = {}
    for needle, canonical in _SEARCH_VOCABULARY:
        if len(found) >= limit:
            break
        if not needle:
            continue
        if f" {needle} " in haystack or f" {needle}," in haystack or f" {needle}." in haystack:
            found.setdefault(display_skill(canonical), None)
    return list(found)


@dataclass(slots=True)
class SkillMatch:
    requirement: str
    matched: bool
    strength: float
    evidence: str | None = None


#: Below this, two skill strings are treated as unrelated.
FUZZY_THRESHOLD = 0.86


def match_skill(requirement: str, candidate_skills: list[str]) -> SkillMatch:
    """Decide whether a candidate satisfies one required skill.

    Exact canonical equality scores 1.0; a close variant scores its similarity. Anything
    below ``FUZZY_THRESHOLD`` counts as missing - being generous here would inflate
    scores and mislead recruiters, which is worse than a visible gap.
    """
    req_key = normalise_skill(requirement)
    if not req_key:
        return SkillMatch(requirement, False, 0.0)

    best_strength = 0.0
    best_evidence: str | None = None

    for skill in candidate_skills:
        skill_key = normalise_skill(skill)
        if not skill_key:
            continue
        if skill_key == req_key:
            return SkillMatch(requirement, True, 1.0, skill)
        score = similarity(req_key, skill_key)
        if score > best_strength:
            best_strength, best_evidence = score, skill

    if best_strength >= FUZZY_THRESHOLD:
        return SkillMatch(requirement, True, round(best_strength, 2), best_evidence)
    return SkillMatch(requirement, False, round(best_strength, 2), None)


def match_skills(
    requirements: list[str], candidate_skills: list[str]
) -> list[SkillMatch]:
    return [match_skill(req, candidate_skills) for req in requirements]
