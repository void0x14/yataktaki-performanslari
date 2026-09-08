from services.echo.app import EchoObservation, EchoVerifier, sign


def test_echo_verifier_accepts_matching_nonce_and_signature():
    secret = b"test-secret"
    verifier = EchoVerifier(secret)
    timestamp = 1_700_000_000
    observation = EchoObservation(
        request_id="req-1",
        nonce="nonce-1",
        exit_ip="203.0.113.9",
        observed_at=timestamp,
        region="a",
        signature=sign(secret, "req-1", "nonce-1", "203.0.113.9", timestamp),
    )
    assert verifier.verify(observation, max_age_seconds=10**9) is True


def test_echo_verifier_rejects_tampered_signature():
    secret = b"test-secret"
    verifier = EchoVerifier(secret)
    timestamp = 1_700_000_000
    observation = EchoObservation(
        request_id="req-1",
        nonce="nonce-1",
        exit_ip="203.0.113.9",
        observed_at=timestamp,
        region="a",
        signature="00" * 32,
    )
    assert verifier.verify(observation, max_age_seconds=10**9) is False
