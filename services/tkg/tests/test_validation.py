"""Unit tests for extraction validation (guide 6.4 / F2.1). Normal suite: no network, no database."""
import pytest
from pydantic import ValidationError

from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from tkg.llm.validation import validate_extraction, contains_advice_word

ARTICLE = {
    "title": "RBI hikes repo rate by 25 bps",
    "description": "The Reserve Bank raised the policy repo rate; Infosys shares fell.",
}


def extraction(driver_moves=(), direct_effects=(), summary="RBI raises the repo rate"):
    return ArticleExtractionOutput(
        article_id="a1", is_market_relevant=True, summary=summary,
        driver_moves=list(driver_moves), direct_effects=list(direct_effects),
    )


def dm(**kw):
    base = dict(driver_id="drv:in_repo_rate", relation="MOVES_UP", magnitude="medium", confidence=0.9,
                evidence="hikes repo rate by 25 bps")
    base.update(kw)
    return DriverMoveOutput(**base)


def de(**kw):
    base = dict(target_type="sector", target_id="realty", relation="HURTS", strength=0.7, confidence=0.8,
                evidence="raised the policy repo rate")
    base.update(kw)
    return DirectEffectOutput(**base)


def test_valid_items_are_kept():
    cleaned, errors = validate_extraction(extraction([dm()], [de()]), ARTICLE, set())
    assert errors == [] and len(cleaned.driver_moves) == 1 and len(cleaned.direct_effects) == 1


def test_schema_requires_non_empty_evidence():
    with pytest.raises(ValidationError):
        DriverMoveOutput(driver_id="drv:in_repo_rate", relation="MOVES_UP", magnitude="low",
                         confidence=0.5, evidence="")


@pytest.mark.parametrize("evidence", ["", "   ", "\n\t"])
def test_empty_or_whitespace_evidence_is_dropped_with_reason(evidence):
    # model_construct bypasses the schema so the validator itself is exercised (TRAP-10)
    bad_effect = DirectEffectOutput.model_construct(
        target_type="sector", target_id="realty", relation="HURTS", strength=0.7, confidence=0.8, evidence=evidence)
    bad_move = DriverMoveOutput.model_construct(
        driver_id="drv:in_repo_rate", relation="MOVES_UP", magnitude="low", confidence=0.5, evidence=evidence)
    cleaned, errors = validate_extraction(extraction([bad_move], [bad_effect]), ARTICLE, set())
    assert cleaned.driver_moves == [] and cleaned.direct_effects == []
    assert errors.count("evidence_empty") == 2


def test_disrupts_not_allowed_on_driver_but_allowed_on_direct_effect():
    cleaned, errors = validate_extraction(
        extraction([dm(relation="DISRUPTS")], [de(relation="DISRUPTS")]), ARTICLE, set())
    assert cleaned.driver_moves == []
    assert "disrupts_not_allowed_on_driver" in errors
    assert len(cleaned.direct_effects) == 1


def test_evidence_must_be_in_text_and_security_must_be_linked():
    cleaned, errors = validate_extraction(
        extraction([dm(evidence="made up sentence")],
                   [de(target_type="security", target_id="NSE:INFY", evidence="Infosys shares fell")]),
        ARTICLE, linked_security_ids=set())
    assert cleaned.driver_moves == [] and cleaned.direct_effects == []
    assert any(e.startswith("evidence_not_found") for e in errors)
    assert "security_not_linked:NSE:INFY" in errors


@pytest.mark.parametrize("summary,expected", [
    ("Investors BUY gold ahead of Dhanteras", True),
    ("Analysts advise to sell the rally", True),
    ("Funds trim exposure", True),
    ("Importers hedge currency risk", True),
    ("Buyback announced by company", False),     # whole words only
    ("Rebuying is not advice", False),
    ("RBI raises the repo rate by 25 bps", False),
    (None, False),
])
def test_advice_word_detection(summary, expected):
    assert contains_advice_word(summary) is expected


def test_advice_word_summary_is_nulled_not_rewritten():
    cleaned, errors = validate_extraction(
        extraction([dm()], summary="Investors should buy gold now"), ARTICLE, set())
    assert "summary_advice_word" in errors
    assert cleaned.summary == ""            # the runner stores this as NULL
    assert len(cleaned.driver_moves) == 1   # the rest of the extraction is untouched


def test_pre_parse_drops_are_reported():
    ext = extraction([dm()])
    ext._pre_drops = ["evidence_empty"]
    _, errors = validate_extraction(ext, ARTICLE, set())
    assert errors == ["evidence_empty"]
