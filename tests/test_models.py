from fallout76_build_metadata.models import PerkCardMetadata, ValidationError, VerificationStatus


def test_perk_card_rank_validation_passes() -> None:
    card = PerkCardMetadata(
        perk_id="commando",
        canonical_name="Commando",
        display_name="Commando",
        special_category="Perception",
        max_rank=3,
        rank_costs={1: 1, 2: 2, 3: 3},
        effect_by_rank={1: "+10%", 2: "+15%", 3: "+20%"},
        level_required=15,
        card_type="Combat",
        recommended_rank_default=3,
        recommended_rank_min=1,
        recommended_rank_max=3,
        source_records=["src-1"],
        status=VerificationStatus.VERIFIED,
        confidence_score=0.9,
    )
    assert card.effect_by_rank[3] == "+20%"


def test_perk_card_rank_validation_fails() -> None:
    try:
        PerkCardMetadata(
            perk_id="broken",
            canonical_name="Broken",
            display_name="Broken",
            special_category="Luck",
            max_rank=2,
            rank_costs={1: 1},
            effect_by_rank={1: "a", 2: "b"},
            level_required=1,
            card_type="Utility",
            recommended_rank_default=1,
            recommended_rank_min=1,
            recommended_rank_max=2,
            confidence_score=0.5,
        )
    except ValidationError:
        return
    raise AssertionError("expected validation failure")
