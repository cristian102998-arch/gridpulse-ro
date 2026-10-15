import pytest

from gridpulse.agent.evaluate import QUESTIONS, grade, number_candidates


def test_reads_english_and_romanian_numbers():
    assert 146383.0 in number_candidates("146,383 MWh")
    assert 146383.0 in number_candidates("146.383 MWh")  # Romanian thousands
    assert 146.4 in number_candidates("146,4 GWh")  # Romanian decimal
    assert 146383.0 in number_candidates("146 383 MWh")
    assert 1234567.89 in number_candidates("1,234,567.89")
    assert 1234567.89 in number_candidates("1.234.567,89")
    assert -2.6 in number_candidates("-2.6 °C")


@pytest.mark.parametrize(
    "answer",
    [
        "Romania consumed 146,383 MWh on 13 October 2026.",
        "Consumul a fost de 146.383 MWh.",
        "About 146.4 GWh.",
        "Aproximativ 146,4 GWh.",
    ],
)
def test_units_and_formats_pass(answer):
    assert grade(answer, 146383.0, {})


def test_wrong_number_fails():
    assert not grade("It was 152,000 MWh.", 146383.0, {})


def test_absolute_tolerance_for_percentages_and_counts():
    assert grade("Renewables were 56.7% of generation.", 56.7, {"abs_tolerance": 0.6})
    assert grade("Ponderea a fost 57%.", 56.7, {"abs_tolerance": 0.6})
    assert not grade("It was 58.5%.", 56.7, {"abs_tolerance": 0.6})
    assert grade("37 days.", 37, {"abs_tolerance": 0})
    assert not grade("36 days.", 37, {"abs_tolerance": 0})


def test_twh_questions_accept_mwh():
    q = {"units_extra": [1000000]}
    assert grade("53.6 TWh", 53.56, q)
    assert grade("53,560,002 MWh", 53.56, q)


def test_unavailable_answers():
    q = {"kind": "unavailable"}
    assert grade("Day-ahead prices are not available yet.", 0, q)
    assert grade("Nu există încă date despre preț.", 0, q)
    assert not grade("The average price was 95.50 EUR/MWh.", 0, q)


def test_question_file_is_well_formed():
    import yaml

    qs = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    data_qs = [q for q in qs if q.get("kind") != "document"]
    doc_qs = [q for q in qs if q.get("kind") == "document"]
    assert len(data_qs) == 25 and len(doc_qs) == 3
    assert len({q["id"] for q in qs}) == len(qs)
    assert all(q["question"] and q["reference_sql"] for q in data_qs)
    assert all(q["expected_doc"] for q in doc_qs)


def test_document_grading():
    from gridpulse.agent.evaluate import grade_document

    q = {"expected_doc": "tel-q4-2025-prelim"}
    docs = [{"query": "x", "hits": [("tel-q4-2025-prelim", 32), ("other", 1)]}]
    assert grade_document("Importurile au crescut (Transelectrica, 2026, p. 32).", docs, q)
    assert not grade_document("Importurile au crescut.", docs, q)  # no page cited
    assert not grade_document("(p. 3)", [{"hits": [("other", 3)]}], q)  # wrong document
