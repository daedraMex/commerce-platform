from factory.pause import PauseState


def test_enter_is_true_only_on_the_transition_into_paused(tmp_path):
    state = PauseState(tmp_path / "state")

    assert state.enter("2 PRs waiting for review") is True
    assert state.enter("daily limit reached") is False
    assert state.path.exists()

    state.clear()
    assert not state.path.exists()
    assert state.enter("daily limit reached") is True


def test_clear_is_safe_when_not_paused(tmp_path):
    state = PauseState(tmp_path / "state")

    state.clear()

    assert not state.path.exists()
