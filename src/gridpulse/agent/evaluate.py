"""Run the agent over evals/agent_questions.yaml and grade the answers against live SQL."""

import contextlib
import json
import re
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import yaml

from gridpulse.agent.core import ask

QUESTIONS = Path(__file__).resolve().parents[3] / "evals" / "agent_questions.yaml"
NUMBER = re.compile(r"-?\d(?:[\d.,   ]*\d)?")
UNAVAILABLE = re.compile(
    r"not (?:yet )?available|no (?:price )?data|not connected|nu (?:este|sunt|există|am)"
    r"|indisponibil|lipsesc|nu e(?:ste)? încă",
    re.IGNORECASE,
)


def number_candidates(text: str) -> set[float]:
    """Every plausible reading of each number in an English or Romanian answer.

    "146,383" may be 146383 (English thousands) or 146.383 (Romanian decimal), and
    "146.383" the other way round; both readings are kept and grading picks the match.
    """
    out: set[float] = set()
    for raw in NUMBER.findall(text):
        s = re.sub(r"[   ]", "", raw)
        readings = []
        if "," in s and "." in s:
            dec = "," if s.rfind(",") > s.rfind(".") else "."
            thou = "." if dec == "," else ","
            readings.append(s.replace(thou, "").replace(dec, "."))
        elif "," in s or "." in s:
            sep = "," if "," in s else "."
            readings.append(s.replace(sep, ""))  # thousands separator
            if s.count(sep) == 1:
                readings.append(s.replace(sep, "."))  # decimal separator
        else:
            readings.append(s)
        for r in readings:
            with contextlib.suppress(ValueError):
                out.add(float(r))
    return out


def grade(answer: str, expected: float | None, question: dict) -> bool:
    if question.get("kind") == "unavailable":
        return bool(UNAVAILABLE.search(answer))
    if expected is None:
        return False
    factors = [
        1,
        1000,
        0.001,
        *question.get("units_extra", []),
        *[1 / f for f in question.get("units_extra", [])],
    ]
    abs_tol = question.get("abs_tolerance")
    for value in number_candidates(answer):
        for f in factors:
            v = value * f
            if abs_tol is not None:
                if abs(v - expected) <= abs_tol:
                    return True
            elif abs(v - expected) <= 0.01 * abs(expected):
                return True
    return False


@dataclass
class QuestionResult:
    id: str
    question: str
    expected: float | None
    answer: str
    passed: bool
    model: str
    escalated: bool
    n_sql: int
    sql_errors: int
    cost_usd: float
    seconds: float


def run_eval(
    model: str,
    escalate_to: str | None,
    database_url: str,
    owner_url: str,
    only: list[str] | None = None,
) -> dict:
    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if only:
        questions = [q for q in questions if q["id"] in only]
    results = []
    with psycopg.connect(owner_url) as conn:
        for q in questions:
            row = conn.execute(q["reference_sql"]).fetchone()
            expected = float(row[0]) if row and row[0] is not None else None
            r = ask(q["question"], database_url, model=model, escalate_to=escalate_to)
            results.append(
                QuestionResult(
                    id=q["id"],
                    question=q["question"],
                    expected=expected,
                    answer=r.answer,
                    passed=grade(r.answer, expected, q),
                    model=r.model,
                    escalated=r.escalated,
                    n_sql=len(r.sql),
                    sql_errors=sum(1 for s in r.sql if s.get("error")),
                    cost_usd=r.usage.cost_usd,
                    seconds=r.seconds,
                )
            )
    passed = sum(r.passed for r in results)
    summary = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": model,
        "escalate_to": escalate_to,
        "passed": passed,
        "total": len(results),
        "accuracy": passed / len(results) if results else 0.0,
        "cost_usd": sum(r.cost_usd for r in results),
        "cost_per_question_usd": statistics.mean(r.cost_usd for r in results) if results else 0,
        "median_seconds": statistics.median(r.seconds for r in results) if results else 0,
        "escalations": sum(r.escalated for r in results),
        "results": [asdict(r) for r in results],
    }
    return summary


def write_report(summary: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    slug = summary["model"].replace(":", "-")
    path = folder / f"{summary['run_at'][:10]}_{slug}.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    badge = {
        "schemaVersion": 1,
        "label": f"agent eval ({slug})",
        "message": f"{summary['passed']}/{summary['total']}",
        "color": "brightgreen"
        if summary["accuracy"] >= 0.9
        else "yellow"
        if summary["accuracy"] >= 0.7
        else "red",
    }
    (folder.parent / f"badge_{slug}.json").write_text(json.dumps(badge), encoding="utf-8")
    return path
