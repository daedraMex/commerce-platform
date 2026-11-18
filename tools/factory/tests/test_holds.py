import stat

from factory.holds import LABEL_HOLDS_FILE, LabelHolds


def test_holds_start_empty(tmp_path):
    assert LabelHolds(tmp_path / "state").numbers() == frozenset()


def test_add_and_remove_survive_a_new_instance(tmp_path):
    state = tmp_path / "state"
    LabelHolds(state).add(7)
    LabelHolds(state).add(9)
    LabelHolds(state).add(7)
    LabelHolds(state).remove(9)

    assert LabelHolds(state).numbers() == {7}


def test_the_file_is_private_to_the_factory(tmp_path):
    state = tmp_path / "state"
    LabelHolds(state).add(7)

    mode = stat.S_IMODE((state / LABEL_HOLDS_FILE).stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(state.stat().st_mode) == 0o700


def test_unreadable_lines_are_ignored(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / LABEL_HOLDS_FILE).write_text("#7\ngarbage\n\n#12\n")

    assert LabelHolds(state).numbers() == {7, 12}
