from __future__ import annotations

from dataclasses import dataclass
from math import log2


@dataclass(frozen=True)
class RankingMetrics:
    precision: float
    recall: float
    ndcg: float
    top_k_hit_rate: float
    regret: float


def evaluate(predicted: list[str], relevant: set[str], k: int | None = None) -> RankingMetrics:
    ranked = predicted[:k] if k else predicted
    hits = [x for x in ranked if x in relevant]
    precision = len(hits) / len(ranked) if ranked else 0.0
    recall = len(hits) / len(relevant) if relevant else 1.0
    dcg = sum(1 / log2(i + 2) for i, x in enumerate(ranked) if x in relevant)
    ideal = sum(1 / log2(i + 2) for i in range(min(len(relevant), len(ranked))))
    missed = relevant - set(hits)
    return RankingMetrics(precision, recall, dcg / ideal if ideal else 0.0, 1.0 if hits else 0.0, float(len(missed)))


def passes_manual_baseline(current: RankingMetrics, baseline: RankingMetrics) -> bool:
    return (
        current.precision >= baseline.precision
        and current.recall >= baseline.recall
        and current.ndcg >= baseline.ndcg
        and current.top_k_hit_rate >= baseline.top_k_hit_rate
    )
