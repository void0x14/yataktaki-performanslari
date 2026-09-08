from proxy_pipeline.decision.evaluation import RankingMetrics, evaluate, passes_manual_baseline


def test_evaluation_set_replay_metric_contract():
    predicted = ["asn-1", "asn-2", "asn-3"]
    relevant = {"asn-1", "asn-3"}
    metrics = evaluate(predicted, relevant, k=3)
    baseline = RankingMetrics(0.5, 0.5, 0.5, 1.0, 1.0)
    assert metrics.precision >= 0.5
    assert passes_manual_baseline(metrics, RankingMetrics(0.0, 0.0, 0.0, 0.0, 10.0))
    assert not passes_manual_baseline(RankingMetrics(0.1, 0.1, 0.1, 0.0, 5), baseline)
