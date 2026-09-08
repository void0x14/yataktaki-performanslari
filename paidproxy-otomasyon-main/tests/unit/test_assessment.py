from proxy_pipeline.assessment.classifier import AssetClass, classify
from proxy_pipeline.assessment.executor import HighValueExecutor, TestProfile
import pytest


def test_insufficient_evidence():
    result = classify([])
    assert result.classification is AssetClass.INSUFFICIENT_EVIDENCE


def test_rotation_classes():
    possible = classify(["1.1.1.1", "8.8.8.8"])
    confirmed = classify(["1.1.1.1", "8.8.8.8", "9.9.9.9"])
    assert possible.classification is AssetClass.POSSIBLE_ROTATION
    assert confirmed.classification is AssetClass.CONFIRMED_ROTATION


def test_capacity_requires_operator_ack():
    executor = HighValueExecutor(TestProfile("cap", "1", 1, 0, ("a",), capacity_enabled=True), lambda e: "1.1.1.1")
    with pytest.raises(PermissionError):
        executor.run("198.51.100.1:3128")
