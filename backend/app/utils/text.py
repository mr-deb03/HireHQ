"""Text normalisation, tokenisation and lexical similarity.

These primitives back the deterministic resume parser, the skill matcher and the
semantic component of the ATS engine. They are pure functions with no I/O, which is what
lets the ATS engine be unit-tested exhaustively without a database or a network.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from datetime import date

# ---------------------------------------------------------------- constants
STOPWORDS = frozenset(
    """
    a an the and or but if then else of in on at to for with without from by as is are was
    were be been being have has had do does did will would shall should can could may might
    must this that these those it its we you your our their they he she his her them us i me
    my mine ours yours not no nor so such than too very just also more most other some any
    each few own same s t don now o re ve ll d m y
    """.split()
)

#: Words that appear in nearly every resume and job ad, and so carry no signal.
DOMAIN_STOPWORDS = frozenset(
    """
    experience experienced work working works worked job role position responsibility
    responsibilities requirement requirements skill skills knowledge ability abilities
    candidate candidates applicant company team teams year years month months strong good
    excellent proven track record etc using use used help helping ensure ensuring
    """.split()
)

ALL_STOPWORDS = STOPWORDS | DOMAIN_STOPWORDS

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-_]*", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RUN_RE = re.compile(r"[^\w\s+#.\-/@]")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
#: Deliberately permissive: resumes write phone numbers a dozen ways.
PHONE_RE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s.\-]?)?(?:\(\d{1,4}\)[\s.\-]?)?\d{3,5}[\s.\-]?\d{3,5}(?:[\s.\-]?\d{2,5})?"
)
URL_RE = re.compile(r"https?://[^\s<>\"')]+|www\.[^\s<>\"')]+", re.IGNORECASE)
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[A-Za-z0-9\-_%]+/?", re.IGNORECASE
)
GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9\-_.]+/?", re.IGNORECASE
)


def normalise_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalise(text: str) -> str:
    """Casefold, strip accents and collapse punctuation - the canonical comparison form."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return normalise_whitespace(text.casefold())


def slugify(text: str, *, max_length: int = 80) -> str:
    base = normalise(text)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:max_length].rstrip("-") or "item"


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Split into comparison tokens, preserving technical forms like ``c++`` and ``node.js``."""
    if not text:
        return []
    tokens = [t.casefold() for t in _WORD_RE.findall(text)]
    tokens = [t.strip(".-_") for t in tokens]
    tokens = [t for t in tokens if len(t) > 1 or t in {"c", "r"}]
    if not keep_stopwords:
        tokens = [t for t in tokens if t not in ALL_STOPWORDS]
    return tokens


def ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def char_ngrams(text: str, n: int = 3) -> list[str]:
    padded = f"  {normalise(text)} "
    return [padded[i : i + n] for i in range(len(padded) - n + 1)]


# ------------------------------------------------------------- similarity
def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cosine(vec_a: Counter[str], vec_b: Counter[str]) -> float:
    """Cosine similarity of two sparse term vectors."""
    if not vec_a or not vec_b:
        return 0.0
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0
    dot = sum(vec_a[t] * vec_b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def levenshtein_ratio(a: str, b: str) -> float:
    """Normalised edit-distance similarity in [0, 1].

    Iterative two-row implementation - O(len(b)) memory - because it is called once per
    (job skill x candidate skill) pair and must stay cheap.
    """
    a, b = normalise(a), normalise(b)
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if abs(len(a) - len(b)) / max(len(a), len(b)) > 0.5:
        return 0.0  # too different in length to be a plausible variant

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    distance = previous[-1]
    return 1.0 - distance / max(len(a), len(b))


def token_set_ratio(a: str, b: str) -> float:
    """Order-insensitive token overlap - "React Developer" vs "Developer, React"."""
    ta, tb = set(tokenize(a)), set(tokenize(b))
    return jaccard(ta, tb)


def similarity(a: str, b: str) -> float:
    """Best of exact / edit-distance / token-overlap. Used for fuzzy skill matching."""
    if not a or not b:
        return 0.0
    na, nb = normalise(a), normalise(b)
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        # "aws" inside "aws lambda" is a real but partial match.
        return 0.85 + 0.1 * (min(len(na), len(nb)) / max(len(na), len(nb)))
    return max(levenshtein_ratio(na, nb), token_set_ratio(a, b))


# ------------------------------------------------------------- extraction
def extract_emails(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).lower() for m in EMAIL_RE.finditer(text)))


def extract_phones(text: str) -> list[str]:
    """Pull plausible phone numbers, rejecting things that are really years or IDs."""
    results: list[str] = []
    for match in PHONE_RE.finditer(text):
        raw = match.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if not 7 <= len(digits) <= 15:
            continue
        # A bare 4-digit run is a year; a long run with no separators inside prose is
        # usually an ID number, not a phone.
        if len(digits) < 10 and not raw.startswith("+"):
            continue
        results.append(normalise_whitespace(raw))
    return list(dict.fromkeys(results))


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).rstrip(".,;)") for m in URL_RE.finditer(text)))


def extract_linkedin(text: str) -> str | None:
    match = LINKEDIN_RE.search(text)
    if not match:
        return None
    url = match.group(0).rstrip("/")
    return url if url.startswith("http") else f"https://{url}"


def extract_github(text: str) -> str | None:
    match = GITHUB_RE.search(text)
    if not match:
        return None
    url = match.group(0).rstrip("/")
    if url.lower().rstrip("/").endswith("github.com"):
        return None
    return url if url.startswith("http") else f"https://{url}"


def split_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def split_bullets(text: str) -> list[str]:
    """Break a block into bullet-like items, whether it uses -, *, • or numbering."""
    items: list[str] = []
    for line in split_lines(text):
        cleaned = re.sub(r"^[\-•●▪*–—·]\s*", "", line)
        cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned)
        cleaned = cleaned.strip(" .;")
        if len(cleaned) > 3:
            items.append(cleaned)
    return items


def truncate(text: str, limit: int, suffix: str = "...") -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


# ------------------------------------------------------------------ dates
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        ],
        start=1,
    )
}

_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{4})[-/](\d{1,2})\b"), "ym"),
    (re.compile(r"\b(\d{1,2})[/-](\d{4})\b"), "my"),
    (
        re.compile(
            r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*,?\s*(\d{4})\b",
            re.IGNORECASE,
        ),
        "monthname",
    ),
    (re.compile(r"\b(\d{4})\b"), "year"),
]

PRESENT_RE = re.compile(
    r"\b(present|current|currently|till date|to date|now|ongoing)\b", re.IGNORECASE
)


def parse_loose_date(text: str, *, prefer_end: bool = False) -> date | None:
    """Parse the many date formats resumes use. Returns None rather than guessing wildly."""
    if not text:
        return None
    text = text.strip()
    for pattern, kind in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            if kind == "ymd":
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if kind == "ym":
                return date(int(match.group(1)), _clamp_month(int(match.group(2))), 1)
            if kind == "my":
                return date(int(match.group(2)), _clamp_month(int(match.group(1))), 1)
            if kind == "monthname":
                month = _MONTHS[match.group(1)[:3].lower()]
                return date(int(match.group(2)), month, 1)
            if kind == "year":
                year = int(match.group(1))
                if not 1950 <= year <= date.today().year + 8:
                    return None
                return date(year, 12 if prefer_end else 1, 31 if prefer_end else 1)
        except ValueError:
            return None
    return None


def _clamp_month(month: int) -> int:
    return min(12, max(1, month))


def months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))
