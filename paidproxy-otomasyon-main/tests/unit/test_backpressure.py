from proxy_pipeline.queue.backpressure import BackpressureController, WatermarkProfile


def test_backpressure_is_technical_only():
    controller = BackpressureController(WatermarkProfile("p", 1000, 100, 50, 10, 20))
    assert controller.observe(spool_bytes=50) == "run"
    assert controller.observe(spool_bytes=150) == "slow"
    assert controller.observe(spool_bytes=2000) == "pause"
    assert controller.paused is True
