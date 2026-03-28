import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from logger_config import setup_logger

logger = setup_logger("ReportMetadataAnalyzer")

ENGLISH_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

HEBREW_MONTHS = {
    "ינואר": 1,
    "פברואר": 2,
    "מרץ": 3,
    "אפריל": 4,
    "מאי": 5,
    "יוני": 6,
    "יולי": 7,
    "אוגוסט": 8,
    "ספטמבר": 9,
    "אוקטובר": 10,
    "נובמבר": 11,
    "דצמבר": 12,
}

DATE_HINTS = [
    "date",
    "dated",
    "published",
    "issued",
    "updated",
    "report",
    "document",
    "תאריך",
    "פורסם",
    "עדכון",
    "נדון",
    "מסמך",
    "דוח",
]


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _excerpt_from_chapters(report_name: str, chapters: List[Dict[str, Any]], limit: int = 12000) -> str:
    parts = [report_name]
    for chapter in chapters[:3]:
        title = chapter.get("title", "")
        content = chapter.get("content", "")
        parts.append(str(title))
        parts.append(str(content)[:3000])
    return _normalize_space("\n".join(part for part in parts if part))[:limit]


def _line_context(text: str, index: int) -> str:
    start = max(0, text.rfind("\n", 0, index))
    end = text.find("\n", index)
    if end == -1:
        end = min(len(text), index + 180)
    return _normalize_space(text[start:end])


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _score_candidate(text: str, start: int, line: str, candidate_date: date, precision: str) -> int:
    current_year = datetime.now().year
    score = 0
    if start < 500:
        score += 60
    elif start < 1500:
        score += 45
    elif start < 3500:
        score += 25
    else:
        score += 10

    line_lower = line.lower()
    if any(hint in line_lower for hint in DATE_HINTS):
        score += 35
    if precision == "full":
        score += 15
    if candidate_date.year > current_year:
        score -= 100
    if candidate_date.year < 1990:
        score -= 20
    return score


def _date_candidates(text: str) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    numeric_pattern = re.compile(r"\b(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>19\d{2}|20\d{2})\b")
    english_patterns = [
        re.compile(r"\b(?P<day>\d{1,2})\s+(?P<month_name>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>19\d{2}|20\d{2})\b", re.IGNORECASE),
        re.compile(r"\b(?P<month_name>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<day>\d{1,2}),?\s+(?P<year>19\d{2}|20\d{2})\b", re.IGNORECASE),
    ]
    hebrew_pattern = re.compile(
        r"(?P<day>\d{1,2})\s+(?P<month_name>ינואר|פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר)\s*(?P<year>19\d{2}|20\d{2})"
    )
    year_only_pattern = re.compile(r"\b(19\d{2}|20\d{2})\b")

    for match in numeric_pattern.finditer(text):
        candidate_date = _safe_date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        if not candidate_date:
            continue
        line = _line_context(text, match.start())
        candidates.append(
            {
                "date": candidate_date,
                "matched_text": match.group(0),
                "line": line,
                "score": _score_candidate(text, match.start(), line, candidate_date, "full"),
            }
        )

    for pattern in english_patterns:
        for match in pattern.finditer(text):
            month = ENGLISH_MONTHS.get(match.group("month_name").lower())
            candidate_date = _safe_date(int(match.group("year")), month, int(match.group("day"))) if month else None
            if not candidate_date:
                continue
            line = _line_context(text, match.start())
            candidates.append(
                {
                    "date": candidate_date,
                    "matched_text": match.group(0),
                    "line": line,
                    "score": _score_candidate(text, match.start(), line, candidate_date, "full"),
                }
            )

    for match in hebrew_pattern.finditer(text):
        month = HEBREW_MONTHS.get(match.group("month_name"))
        candidate_date = _safe_date(int(match.group("year")), month, int(match.group("day"))) if month else None
        if not candidate_date:
            continue
        line = _line_context(text, match.start())
        candidates.append(
            {
                "date": candidate_date,
                "matched_text": match.group(0),
                "line": line,
                "score": _score_candidate(text, match.start(), line, candidate_date, "full"),
            }
        )

    if not candidates:
        for match in year_only_pattern.finditer(text[:1200]):
            candidate_date = _safe_date(int(match.group(1)), 1, 1)
            if not candidate_date:
                continue
            line = _line_context(text, match.start())
            candidates.append(
                {
                    "date": candidate_date,
                    "matched_text": match.group(1),
                    "line": line,
                    "score": _score_candidate(text, match.start(), line, candidate_date, "year"),
                    "precision": "year",
                }
            )

    return candidates


def infer_report_metadata(report_name: str, chapters: List[Dict[str, Any]]) -> Dict[str, str]:
    excerpt = _excerpt_from_chapters(report_name, chapters)
    if not excerpt:
        return {}

    candidates = _date_candidates(excerpt)
    if not candidates:
        logger.info("No report-date candidates found in report text for '%s'.", report_name)
        return {}

    best = max(
        candidates,
        key=lambda item: (item.get("score", 0), item["date"].toordinal() * -1),
    )
    confidence = "high" if best.get("score", 0) >= 75 else "medium" if best.get("score", 0) >= 45 else "low"
    result = {
        "original_report_date": best["date"].isoformat(),
        "source_excerpt": best.get("line", "")[:220],
        "matched_text": best.get("matched_text", ""),
        "confidence": confidence,
    }
    logger.info(
        "Inferred original report date for '%s' as %s (confidence=%s, matched='%s').",
        report_name,
        result["original_report_date"],
        confidence,
        result["matched_text"],
    )
    return result
