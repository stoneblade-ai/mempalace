"""Routing layer: decides local/team/both, RRF merge, dedupe."""


def rrf_merge(local_hits: list, team_hits: list, k: int = 60) -> list:
    """Reciprocal Rank Fusion merge.
    Scores each hit by 1/(k+rank) per layer, sums across layers.
    Hits appearing in both layers get boosted naturally."""
    scores = {}
    hit_data = {}

    for rank, hit in enumerate(local_hits):
        hid = hit["id"]
        scores[hid] = scores.get(hid, 0) + 1 / (k + rank)
        if hid not in hit_data:
            hit_data[hid] = {**hit, "layer": "local"}

    for rank, hit in enumerate(team_hits):
        hid = hit["id"]
        scores[hid] = scores.get(hid, 0) + 1 / (k + rank)
        if hid in hit_data:
            hit_data[hid]["_matched_team"] = True
        else:
            hit_data[hid] = {**hit, "layer": "team"}

    result = []
    for hid in sorted(scores, key=scores.get, reverse=True):
        entry = hit_data[hid]
        entry["rrf_score"] = scores[hid]
        entry["layer"] = determine_layer(entry)
        result.append(entry)

    return result


def dedupe(local_hits: list, team_hits: list) -> tuple:
    """Deduplicate across layers.
    First: match by origin link (team's origin_local_id == local id).
    Second: match by content_hash.
    Returns (deduped_local, deduped_team)."""
    local_by_id = {h["id"]: h for h in local_hits}
    local_by_hash = {}
    for h in local_hits:
        ch = h.get("content_hash", "")
        if ch:
            local_by_hash[ch] = h

    deduped_team = []

    for th in team_hits:
        origin_id = th.get("origin_local_id", "")
        content_hash = th.get("content_hash", "")

        matched_local = None
        if origin_id and origin_id in local_by_id:
            matched_local = local_by_id[origin_id]
        elif content_hash and content_hash in local_by_hash:
            matched_local = local_by_hash[content_hash]

        if matched_local:
            matched_local["_matched_team"] = True
            team_entry = {**th, "id": matched_local["id"]}
            deduped_team.append(team_entry)
        else:
            deduped_team.append(th)

    return local_hits, deduped_team


def determine_layer(hit: dict) -> str:
    """Determine which layer(s) a hit belongs to."""
    if hit.get("_matched_team"):
        return "both"
    hid = hit.get("id", "")
    if hid.startswith("team_"):
        return "team"
    return "local"
