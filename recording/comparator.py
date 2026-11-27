
def compare_runs(original, replay):
    """
    Compare application request outcomes between
    an original experiment and its replay.
    """

    original_by_id = {
        request["request_id"]: request
        for request in original
    }

    replay_by_id = {
        request["request_id"]: request
        for request in replay
    }

    common_ids = original_by_id.keys() & replay_by_id.keys()

    matching_outcomes = 0

    for request_id in common_ids:
        original_success = original_by_id[request_id]["success"]
        replay_success = replay_by_id[request_id]["success"]

        if original_success == replay_success:
            matching_outcomes += 1

    total = len(common_ids)

    return {
        "original_requests": len(original),
        "replay_requests": len(replay),
        "compared_requests": total,
        "original_failures": sum(
            not request["success"] for request in original
        ),
        "replay_failures": sum(
            not request["success"] for request in replay
        ),
        "matching_outcomes": matching_outcomes,
        "outcome_match_rate": (
            round(matching_outcomes / total * 100, 2)
            if total else None
        ),
        "unmatched_original_requests": sorted(
            original_by_id.keys() - replay_by_id.keys()
        ),
        "unmatched_replay_requests": sorted(
            replay_by_id.keys() - original_by_id.keys()
        )
    }
