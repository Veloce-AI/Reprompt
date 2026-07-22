"""Tests for reprompt_core.contract.cluster — semantic entropy clustering.

All tests use a fake entails callable: exact string match. This makes the
clustering deterministic without loading any NLI model.
"""

from __future__ import annotations

import math

from reprompt_core.contract.cluster import Cluster, cluster_by_meaning, semantic_entropy


def exact_match(a: str, b: str) -> bool:
    return a.strip() == b.strip()


def always_entails(a: str, b: str) -> bool:
    return True


def never_entails(a: str, b: str) -> bool:
    return False


def test_identical_outputs_cluster_together() -> None:
    outputs = ["hello world", "hello world", "hello world"]
    clusters = cluster_by_meaning(outputs, entails=exact_match)
    assert len(clusters) == 1
    assert len(clusters[0]) == 3


def test_distinct_outputs_each_get_own_cluster() -> None:
    outputs = ["apple", "banana", "cherry"]
    clusters = cluster_by_meaning(outputs, entails=exact_match)
    assert len(clusters) == 3
    assert all(len(c) == 1 for c in clusters)


def test_partial_duplicates_cluster_correctly() -> None:
    outputs = ["foo", "bar", "foo", "baz", "bar"]
    clusters = cluster_by_meaning(outputs, entails=exact_match)
    assert len(clusters) == 3
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2, 2]


def test_always_entails_gives_one_cluster() -> None:
    outputs = ["a", "b", "c", "d"]
    clusters = cluster_by_meaning(outputs, entails=always_entails)
    assert len(clusters) == 1
    assert len(clusters[0]) == 4


def test_never_entails_gives_one_cluster_per_output() -> None:
    outputs = ["x", "y", "z"]
    # even with never_entails, the first output creates a cluster and the
    # second call entails(rep, output) is False → new cluster each time.
    clusters = cluster_by_meaning(outputs, entails=never_entails)
    assert len(clusters) == 3


def test_empty_outputs_gives_empty_clusters() -> None:
    clusters = cluster_by_meaning([], entails=exact_match)
    assert clusters == []


def test_single_output_gives_single_cluster() -> None:
    clusters = cluster_by_meaning(["only"], entails=exact_match)
    assert len(clusters) == 1
    assert clusters[0].representative == "only"


def test_cluster_representative_is_first_member() -> None:
    clusters = cluster_by_meaning(["alpha", "beta", "alpha"], entails=exact_match)
    alpha_cluster = next(c for c in clusters if c.representative == "alpha")
    assert alpha_cluster.representative == "alpha"


# ---------------------------------------------------------------------------
# semantic_entropy
# ---------------------------------------------------------------------------


def test_entropy_zero_for_single_cluster() -> None:
    clusters = [Cluster(members=["a", "b", "c"])]
    assert semantic_entropy(clusters) == 0.0


def test_entropy_zero_for_empty_list() -> None:
    assert semantic_entropy([]) == 0.0


def test_entropy_log2_for_two_equal_clusters() -> None:
    clusters = [Cluster(members=["a", "b"]), Cluster(members=["c", "d"])]
    # p = 0.5 each → entropy = -2 * (0.5 * ln(0.5)) = ln(2) ≈ 0.693
    entropy = semantic_entropy(clusters)
    assert abs(entropy - math.log(2)) < 1e-9


def test_entropy_higher_for_more_clusters() -> None:
    two_clusters = [Cluster(members=["a", "b"]), Cluster(members=["c", "d"])]
    four_clusters = [Cluster(members=["a"]), Cluster(members=["b"]), Cluster(members=["c"]), Cluster(members=["d"])]
    assert semantic_entropy(four_clusters) > semantic_entropy(two_clusters)


def test_entropy_non_negative() -> None:
    clusters = [Cluster(members=["x"]), Cluster(members=["y", "z"])]
    assert semantic_entropy(clusters) >= 0.0
