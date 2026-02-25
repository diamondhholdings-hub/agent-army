"""Prompt builder output validation tests for CSM agent prompt_builders module.

Proves each prompt builder returns a string containing its expected output
schema fields. All tests are synchronous since prompt builders are pure
functions with no I/O.
"""

from __future__ import annotations

from src.app.agents.customer_success.prompt_builders import (
    CSM_SYSTEM_PROMPT,
    build_churn_narrative_prompt,
    build_expansion_prompt,
    build_feature_adoption_prompt,
    build_health_score_prompt,
    build_qbr_prompt,
)


class TestCSMPromptBuilders:
    """Tests for CSM prompt builder functions."""

    def test_csm_system_prompt_is_string(self):
        """CSM_SYSTEM_PROMPT is a non-empty string."""
        assert isinstance(CSM_SYSTEM_PROMPT, str)
        assert len(CSM_SYSTEM_PROMPT) > 0

    def test_build_health_score_prompt_returns_string(self):
        """build_health_score_prompt returns a non-empty string."""
        result = build_health_score_prompt(
            signals={"feature_adoption_rate": 0.8},
            account_data={"account_id": "acct-001"},
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_health_score_prompt_contains_schema(self):
        """build_health_score_prompt embeds health score schema fields."""
        result = build_health_score_prompt(
            signals={"feature_adoption_rate": 0.8},
            account_data={"account_id": "acct-001"},
        )
        # Schema should contain key fields from CSMHealthScore
        assert "score" in result
        assert "rag" in result
        assert "churn_risk_level" in result
        assert "signal_breakdown" in result

    def test_build_churn_narrative_prompt_returns_string(self):
        """build_churn_narrative_prompt returns a non-empty string."""
        result = build_churn_narrative_prompt(
            health_score={"score": 35, "rag": "RED"},
            account_data={"account_id": "acct-002"},
        )
        assert isinstance(result, str)
        assert len(result) > 0
        # Should reference the churn narrative schema fields
        assert "churn_risk_level" in result
        assert "churn_narrative" in result

    def test_build_qbr_prompt_includes_section_names(self):
        """build_qbr_prompt includes all 4 QBR section-related field names."""
        result = build_qbr_prompt(
            account_data={"name": "Acme Corp"},
            health_history={"scores": [70, 75, 80]},
            period="Q1 2026",
        )
        assert isinstance(result, str)
        # Check for the 4 main QBR content fields
        assert "health_summary" in result
        assert "roi_metrics" in result
        assert "feature_adoption_scorecard" in result
        assert "expansion_next_steps" in result

    def test_build_expansion_prompt_returns_string(self):
        """build_expansion_prompt returns a non-empty string with schema fields."""
        result = build_expansion_prompt(
            account_data={"name": "Acme Corp"},
            usage_signals={"seats_used": 95},
        )
        assert isinstance(result, str)
        assert len(result) > 0
        # Schema should contain key fields from ExpansionOpportunity
        assert "opportunity_type" in result
        assert "evidence" in result
        assert "estimated_arr_impact" in result
        assert "recommended_talk_track" in result

    def test_build_feature_adoption_prompt_returns_string(self):
        """build_feature_adoption_prompt returns a non-empty string with schema fields."""
        result = build_feature_adoption_prompt(
            account_data={"name": "Acme Corp"},
            feature_usage={"dashboard": {"active": True}},
        )
        assert isinstance(result, str)
        assert len(result) > 0
        # Schema should contain key fields from FeatureAdoptionReport
        assert "features_used" in result
        assert "adoption_rate" in result
        assert "underutilized_features" in result
        assert "recommendations" in result
