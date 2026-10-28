"""
Anti-hallucination validation (section 6.4).
Every failure is logged with a reason; items that fail are dropped, not "fixed up".
"""
import re
import logging
from typing import List, Dict, Any, Tuple

from tkg.vocab import is_valid_driver, is_valid_actor, is_valid_relation, MAGNITUDE_MAP
from finsight_shared.sectors import ALL_SECTOR_IDS
from tkg.llm.schemas import ArticleExtractionOutput

logger = logging.getLogger("tkg.llm.validation")


def is_valid_sector(s: str) -> bool:
    return s in ALL_SECTOR_IDS


ADVICE_WORDS = ("buy", "sell", "trim", "hedge")
_ADVICE_RE = re.compile(r"\b(" + "|".join(ADVICE_WORDS) + r")\b", re.IGNORECASE)


def contains_advice_word(text_value: str | None) -> bool:
    """Case-insensitive whole-word match for buy / sell / trim / hedge."""
    return bool(text_value and _ADVICE_RE.search(text_value))


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace to single spaces and strip."""
    return re.sub(r'\s+', ' ', text.strip().lower())


def evidence_is_substring(evidence: str, title: str, description: str | None) -> bool:
    """
    Check that evidence is a case-insensitive substring of title + description
    (after whitespace normalization).
    """
    combined = title
    if description:
        combined += " " + description
    return normalize_whitespace(evidence) in normalize_whitespace(combined)


def validate_extraction(
    extraction: ArticleExtractionOutput,
    article: Dict[str, Any],
    linked_security_ids: set[str],
) -> Tuple[ArticleExtractionOutput, List[str]]:
    """
    Validate an extraction result against the closed vocabularies and the article's data.
    Drops invalid items and returns the cleaned extraction plus a list of validation errors.
    
    Args:
        extraction: The raw LLM output parsed into Pydantic
        article: The original article dict
        linked_security_ids: Set of security_ids linked to this article (confidence ≥ 0.70)
    
    Returns:
        (cleaned_extraction, errors)
    """
    errors: List[str] = []
    title = article.get("title", "")
    description = article.get("description", "")

    errors.extend(getattr(extraction, "_pre_drops", []) or [])

    # Summary: advice words null the stored summary (never rewritten)
    summary = extraction.summary
    if contains_advice_word(summary):
        errors.append("summary_advice_word")
        summary = ""

    # Validate actors
    valid_actors = []
    for actor in extraction.actors:
        if is_valid_actor(actor):
            valid_actors.append(actor)
        else:
            errors.append(f"invalid_actor:{actor}")
    
    # Validate driver moves
    valid_driver_moves = []
    for dm in extraction.driver_moves:
        issues = []
        
        # Check driver_id
        if not is_valid_driver(dm.driver_id):
            issues.append(f"invalid_driver:{dm.driver_id}")
        
        # Check relation (DISRUPTS is only valid on direct effects)
        if dm.relation == "DISRUPTS":
            issues.append("disrupts_not_allowed_on_driver")
        elif dm.relation not in ("MOVES_UP", "MOVES_DOWN"):
            issues.append(f"invalid_driver_relation:{dm.relation}")
        
        # Check magnitude
        if dm.magnitude not in MAGNITUDE_MAP:
            issues.append(f"invalid_magnitude:{dm.magnitude}")
        
        # Check evidence
        if not dm.evidence or not dm.evidence.strip():
            issues.append("evidence_empty")
        elif not evidence_is_substring(dm.evidence, title, description):
            issues.append(f"evidence_not_found:{dm.evidence[:50]}")
        
        if issues:
            errors.extend(issues)
        else:
            valid_driver_moves.append(dm)

    # Validate direct effects
    valid_direct_effects = []
    for de in extraction.direct_effects:
        issues = []
        
        # Check relation
        if not is_valid_relation(de.relation):
            issues.append(f"invalid_effect_relation:{de.relation}")
        
        # Check target
        if de.target_type == "security":
            if de.target_id not in linked_security_ids:
                issues.append(f"security_not_linked:{de.target_id}")
        elif de.target_type == "sector":
            if not is_valid_sector(de.target_id):
                issues.append(f"invalid_sector:{de.target_id}")
        else:
            issues.append(f"invalid_target_type:{de.target_type}")
        
        # Check evidence
        if not de.evidence or not de.evidence.strip():
            issues.append("evidence_empty")
        elif not evidence_is_substring(de.evidence, title, description):
            issues.append(f"evidence_not_found:{de.evidence[:50]}")
        
        if issues:
            errors.extend(issues)
        else:
            valid_direct_effects.append(de)

    # Reconstruct cleaned extraction
    cleaned = ArticleExtractionOutput(
        article_id=extraction.article_id,
        is_market_relevant=extraction.is_market_relevant,
        summary=summary,
        actors=valid_actors,
        driver_moves=valid_driver_moves,
        direct_effects=valid_direct_effects,
    )

    if errors:
        logger.warning(
            f"Article {extraction.article_id}: {len(errors)} validation errors: {errors}"
        )

    return cleaned, errors
