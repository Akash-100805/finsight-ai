"""
Unit tests for TKG components (section 12.1).
No network or external API calls.
"""
import pytest
import math
from datetime import datetime, timedelta

from tkg.vocab import (
    is_valid_driver, is_valid_actor, is_valid_relation,
    DRIVERS, ACTORS, RELATIONS, MAGNITUDE_MAP
)
from finsight_shared.sectors import ALL_SECTOR_IDS
from tkg.input.eligibility import is_eligible, get_skip_reason
from tkg.llm.validation import (
    evidence_is_substring, normalize_whitespace, validate_extraction
)
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from tkg.graph.scoring import (
    compute_recency_weight, compute_driver_contribution,
    compute_direct_contribution, aggregate_score, aggregate_confidence,
    generate_explanation
)


def test_vocab_validations():
    """Verify closed vocabularies."""
    # Drivers
    assert is_valid_driver("drv:crude_oil_price") is True
    assert is_valid_driver("drv:in_repo_rate") is True
    assert is_valid_driver("drv:fake_driver") is False
    assert is_valid_driver("crude_oil_price") is False

    # Actors
    assert is_valid_actor("act:rbi") is True
    assert is_valid_actor("act:sebi") is True
    assert is_valid_actor("act:unknown") is False

    # Relations
    assert is_valid_relation("MOVES_UP") is True
    assert is_valid_relation("MOVES_DOWN") is True
    assert is_valid_relation("BENEFITS") is True
    assert is_valid_relation("HURTS") is True
    assert is_valid_relation("MIXED") is True
    assert is_valid_relation("DISRUPTS") is True
    assert is_valid_relation("PROMOTES") is False

    # Sectors
    assert ("oil_gas_and_consumable_fuels" in ALL_SECTOR_IDS) is True
    assert ("information_technology" in ALL_SECTOR_IDS) is True
    assert ("financial_services" in ALL_SECTOR_IDS) is True
    assert ("non_existent_sector" in ALL_SECTOR_IDS) is False
    assert ("oil_gas" in ALL_SECTOR_IDS) is False


def test_evidence_substring_normalization():
    """Verify evidence substring check handles whitespace and case-insensitivity."""
    title = "RBI Hikes   Repo Rate By  25 Bps"
    desc = "The central   bank decided to tighten monetary policy."

    assert evidence_is_substring("repo rate by 25 bps", title, desc) is True
    assert evidence_is_substring("RBI HIKES", title, desc) is True
    assert evidence_is_substring("tighten monetary policy", title, desc) is True
    assert evidence_is_substring("rate cut of 50 bps", title, desc) is False


def test_anti_hallucination_validation_drops_unlinked_security():
    """Ensure that the LLM cannot introduce a company not linked in the news component."""
    article = {
        "title": "Automobile sales report for October",
        "description": "Passenger vehicle sales grew by 15% year on year.",
    }
    # Only Maruti is linked
    linked_securities = {"NSE:MARUTI"}

    extraction = ArticleExtractionOutput(
        article_id="11111111-1111-1111-1111-111111111111",
        is_market_relevant=True,
        summary="Car sales surge in festive month",
        actors=[],
        driver_moves=[],
        direct_effects=[
            DirectEffectOutput(
                target_type="security",
                target_id="NSE:MARUTI",
                relation="BENEFITS",
                strength=0.7,
                confidence=0.8,
                evidence="Passenger vehicle sales grew by 15%"
            ),
            # Hallucinated company not in linked_securities
            DirectEffectOutput(
                target_type="security",
                target_id="NSE:TATAMOTORS",
                relation="BENEFITS",
                strength=0.7,
                confidence=0.8,
                evidence="Passenger vehicle sales grew"
            )
        ]
    )

    cleaned, errors = validate_extraction(extraction, article, linked_securities)
    assert len(cleaned.direct_effects) == 1
    assert cleaned.direct_effects[0].target_id == "NSE:MARUTI"
    assert any("security_not_linked:NSE:TATAMOTORS" in e for e in errors)


def test_eligibility_rules():
    """Test article eligibility filtering (section 6.1)."""
    # 1. Macro / Commodity categories are always eligible
    assert is_eligible({"category": "economy_macro", "event_type": "macro_data_release"}) is True
    assert is_eligible({"category": "commodities_energy", "event_type": "commodity_price_move"}) is True
    assert is_eligible({"category": "central_bank_monetary_policy", "event_type": "policy_rate_decision"}) is True

    # 2. Company categories: only specific event types
    assert is_eligible({"category": "company", "event_type": "earnings"}) is True
    assert is_eligible({"category": "company", "event_type": "mna"}) is True
    assert is_eligible({"category": "company", "event_type": "order_contract_win"}) is True
    assert is_eligible({"category": "company", "event_type": "corporate_admin"}) is False
    assert is_eligible({"category": "company", "event_type": "insider_trade"}) is False
    assert is_eligible({"category": "company", "event_type": "dividend_buyback_split"}) is False

    # 3. Source type regulator / government is always eligible (unless skipped event type)
    assert is_eligible({"source_type": "regulator", "category": "company", "event_type": "regulatory_action"}) is True
    assert is_eligible({"source_type": "government", "category": "company", "event_type": "other", "sectors": ["banking"]}) is True



def test_scoring_math_driver_path():
    """Driver path: contrib = s_i × m_i × sensitivity × w_e × confidence_i."""
    sign = 1.0  # MOVES_UP
    magnitude = "high"  # 1.0
    sensitivity = -0.70  # crude -> paints
    event_weight = 0.90
    confidence = 0.80

    contrib = compute_driver_contribution(sign, magnitude, sensitivity, event_weight, confidence)
    expected = 1.0 * 1.0 * (-0.70) * 0.90 * 0.80  # = -0.504
    assert math.isclose(contrib, expected, rel_tol=1e-4)


def test_scoring_math_direct_path():
    """Direct path: contrib = sign(relation) × strength × w_e × confidence_i."""
    relation = "HURTS"  # sign = -1.0
    strength = 0.60
    event_weight = 0.85
    confidence = 0.90

    contrib = compute_direct_contribution(relation, strength, event_weight, confidence)
    expected = -1.0 * 0.60 * 0.85 * 0.90  # = -0.459
    assert math.isclose(contrib, expected, rel_tol=1e-4)


def test_scoring_tanh_aggregation_bounds():
    """Tanh aggregation must keep score bounded in -1..1."""
    large_positive = [0.8, 0.9, 0.7, 1.2, 0.9]
    score_pos = aggregate_score(large_positive, k=1.0)
    assert 0.0 < score_pos < 1.0

    large_negative = [-1.0, -0.8, -0.9, -1.5]
    score_neg = aggregate_score(large_negative, k=1.0)
    assert -1.0 < score_neg < 0.0

    # Empty contributions yield 0
    assert aggregate_score([], k=1.0) == 0.0


def test_confidence_aggregation_bounds():
    """Confidence = min(1, Σ |w_e × confidence_i| / c)."""
    weighted_confs = [0.8, 0.9, 0.7]
    conf = aggregate_confidence(weighted_confs, c=2.0)
    assert 0.0 <= conf <= 1.0
    assert conf == 1.0  # (0.8+0.9+0.7)/2.0 = 1.2 -> capped at 1.0

    small_confs = [0.2]
    conf_small = aggregate_confidence(small_confs, c=2.0)
    assert conf_small == 0.1


def test_advice_word_ban():
    """
    CRITICAL QUALITY GATE: No advice words ('buy', 'sell', 'trim', 'hedge')
    may ever appear in generated explanations or summaries.
    """
    forbidden_words = ["buy", "sell", "trim", "hedge"]

    sample_paths = [
        {
            "type": "driver",
            "driver_id": "drv:crude_oil_price",
            "relation": "MOVES_UP",
            "magnitude": "high",
            "sensitivity": -0.70,
            "contrib": -0.42,
            "summary": "OPEC+ agreed to deepen crude production cuts",
        },
        {
            "type": "direct",
            "relation": "BENEFITS",
            "contrib": 0.35,
            "summary": "Company secured order contract for electrical transformers",
        },
        {
            "type": "second_hop",
            "from_sector": "metals_and_mining",
            "link": "supplier_of",
            "to_sector": "capital_goods",
            "contrib": -0.15,
        }
    ]

    for p in sample_paths:
        explanation = generate_explanation(p).lower()
        for word in forbidden_words:
            assert f" {word} " not in f" {explanation} ", f"Forbidden advice word '{word}' found in explanation: {explanation}"
