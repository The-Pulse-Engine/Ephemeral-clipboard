def test_ci_fails_on_a_failing_test() -> None:
    assert False, "deliberate failure to prove CI goes red"
