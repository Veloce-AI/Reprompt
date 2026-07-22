"""Semantic-entropy clustering over LLM outputs (PDF §4.1, §4.4).

Pure functions — no LLM calls, no DB imports. The ``entails`` callable is
injected by the caller so tests can pass a deterministic fake without loading
any NLI model.

Bidirectional-entailment clustering (Kuhn / Farquhar semantic entropy):
two outputs A and B belong to the same cluster iff A entails B AND B entails
A, i.e. they are semantically equivalent under the entailment model. The
cluster representative is the first member added, used for pairwise
comparisons against new candidates.

Semantic entropy = Shannon entropy over cluster-size probabilities. A value
near zero means the model always says the same thing (one big cluster). A
high value means the model produces many semantically distinct outputs — a
signal of either genuine multi-modal behaviour or noise.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = ["Cluster", "cluster_by_meaning", "semantic_entropy"]


@dataclass
class Cluster:
    members: list[str] = field(default_factory=list)

    @property
    def representative(self) -> str:
        return self.members[0]

    def __len__(self) -> int:
        return len(self.members)


def cluster_by_meaning(
    outputs: list[str],
    *,
    entails: Callable[[str, str], bool],
) -> list[Cluster]:
    """Partition *outputs* into semantic-equivalence clusters.

    Two outputs end up in the same cluster iff each entails the other
    (bidirectional test against the cluster's representative). Greedy,
    O(n × k) where k is the number of clusters found so far. For typical
    stage-level sample sizes (5–50 outputs) this is fast enough.
    """
    clusters: list[Cluster] = []
    for output in outputs:
        placed = False
        for cluster in clusters:
            rep = cluster.representative
            if entails(rep, output) and entails(output, rep):
                cluster.members.append(output)
                placed = True
                break
        if not placed:
            clusters.append(Cluster(members=[output]))
    return clusters


def semantic_entropy(clusters: list[Cluster]) -> float:
    """Shannon entropy (nats) over cluster-size probabilities.

    Returns 0.0 for an empty cluster list or a single cluster (no uncertainty).
    """
    total = sum(len(c) for c in clusters)
    if total == 0 or len(clusters) <= 1:
        return 0.0
    entropy = 0.0
    for cluster in clusters:
        p = len(cluster) / total
        if p > 0:
            entropy -= p * math.log(p)
    return entropy
