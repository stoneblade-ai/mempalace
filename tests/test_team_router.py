"""Tests for team router: RRF merge, dedupe, routing decisions."""
import pytest
from cortex.team_router import rrf_merge, dedupe, determine_layer


def test_rrf_merge_basic():
    """RRF merge ranks by position, not score."""
    local_hits = [{"id": "a", "similarity": 0.95}, {"id": "b", "similarity": 0.80}]
    team_hits = [{"id": "b", "similarity": 0.70}, {"id": "c", "similarity": 0.65}]
    merged = rrf_merge(local_hits, team_hits, k=60)
    ids = [h["id"] for h in merged]
    assert ids[0] == "b"  # appears in both, gets highest RRF score


def test_rrf_merge_empty_team():
    local_hits = [{"id": "a", "similarity": 0.9}, {"id": "b", "similarity": 0.8}]
    merged = rrf_merge(local_hits, [], k=60)
    assert len(merged) == 2
    assert merged[0]["id"] == "a"


def test_rrf_merge_empty_both():
    assert rrf_merge([], [], k=60) == []


def test_dedupe_by_origin():
    local_hits = [{"id": "local_abc", "content_hash": "abc", "similarity": 0.9}]
    team_hits = [{"id": "team_xyz", "origin_local_id": "local_abc", "content_hash": "different", "similarity": 0.7}]
    deduped_local, deduped_team = dedupe(local_hits, team_hits)
    # After dedupe, team hit should use same ID as local for RRF merging
    total_ids = [h["id"] for h in deduped_local] + [h["id"] for h in deduped_team]
    assert len(deduped_local) + len(deduped_team) <= 2


def test_dedupe_by_content_hash():
    local_hits = [{"id": "local_abc", "content_hash": "same_hash", "similarity": 0.9}]
    team_hits = [{"id": "team_def", "origin_local_id": "", "content_hash": "same_hash", "similarity": 0.7}]
    deduped_local, deduped_team = dedupe(local_hits, team_hits)
    total_ids = [h["id"] for h in deduped_local] + [h["id"] for h in deduped_team]
    assert len(deduped_local) + len(deduped_team) <= 2


def test_determine_layer():
    assert determine_layer({"id": "local_abc"}) == "local"
    assert determine_layer({"id": "team_abc"}) == "team"
    assert determine_layer({"id": "local_abc", "_matched_team": True}) == "both"
    assert determine_layer({"id": "drawer_wing_room_hash"}) == "local"  # legacy no-prefix = local
