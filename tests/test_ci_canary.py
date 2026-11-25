def test_ci_fails_on_a_failing_test() -> None:
    assert 1 + 1 == 3, "deliberate failure to prove CI goes red"
