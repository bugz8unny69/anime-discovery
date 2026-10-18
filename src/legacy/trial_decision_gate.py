from dataclasses import dataclass


class DecisionError(ValueError):
    pass


@dataclass(frozen=True)
class TrialState:
    series_id: int
    status: str
    identity_bound: bool
    mapping_approved: bool
    mapping_revision: int
    published_prefix: int
    episode_one_verified: bool
    pending_attempts: tuple = ()


@dataclass(frozen=True)
class DecisionPlan:
    series_id: int
    action: str
    expected_status: str
    expected_mapping_revision: int
    cancel_attempts: tuple
    target_status: str
    dry_run: bool = True


def plan_trial_decision(state, action):
    if type(state.series_id) is not int or state.series_id <= 0:
        raise DecisionError("Invalid series ID")

    if action not in ("KEEP", "REJECT"):
        raise DecisionError("Unsupported decision")

    if state.status != "TRIAL":
        raise DecisionError("Series is not in an active trial")

    if state.identity_bound is not True or state.mapping_approved is not True:
        raise DecisionError("Verified identity and approved mapping required")

    if type(state.mapping_revision) is not int or state.mapping_revision <= 0:
        raise DecisionError("Invalid mapping revision")

    if (
        type(state.published_prefix) is not int
        or not 0 <= state.published_prefix <= 6
    ):
        raise DecisionError("Invalid published prefix")

    if not state.episode_one_verified or state.published_prefix < 1:
        raise DecisionError("Episode 1 must be verified and published")

    attempts = state.pending_attempts

    if (
        not isinstance(attempts, tuple)
        or any(type(x) is not int or x <= 0 for x in attempts)
        or len(set(attempts)) != len(attempts)
    ):
        raise DecisionError("Invalid pending attempts")

    return DecisionPlan(
        series_id=state.series_id,
        action=action,
        expected_status="TRIAL",
        expected_mapping_revision=state.mapping_revision,
        cancel_attempts=tuple(sorted(attempts)),
        target_status="KEPT" if action == "KEEP" else "REJECTED",
    )


def validate_commit_preconditions(plan, current):
    if current.series_id != plan.series_id:
        raise DecisionError("Series identity changed")

    if current.status != plan.expected_status:
        raise DecisionError("Trial status changed")

    if current.mapping_revision != plan.expected_mapping_revision:
        raise DecisionError("Mapping revision changed")

    if not current.identity_bound or not current.mapping_approved:
        raise DecisionError("Identity or mapping approval revoked")

    if not current.episode_one_verified or current.published_prefix < 1:
        raise DecisionError("Episode 1 no longer available")

    if tuple(sorted(current.pending_attempts)) != plan.cancel_attempts:
        raise DecisionError("Pending download attempts changed")
