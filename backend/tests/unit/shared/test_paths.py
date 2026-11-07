import os

import pytest

from apps.shared.domain.paths import safe_child_path


def test_a_path_inside_the_root_resolves(tmp_path):
    nested = tmp_path / "photos" / "one.jpg"
    nested.parent.mkdir()
    nested.write_bytes(b"image")

    assert safe_child_path(tmp_path, "photos/one.jpg") == nested.resolve()


@pytest.mark.parametrize("name", ["/etc/passwd", "../outside.jpg", "photos/../../outside.jpg"])
def test_absolute_and_parent_paths_are_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        safe_child_path(tmp_path, name)


def test_a_symlinked_file_outside_the_root_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"outside")
    root = tmp_path / "images"
    root.mkdir()
    link = root / "link.jpg"
    os.symlink(outside, link)

    with pytest.raises(ValueError):
        safe_child_path(root, "link.jpg")


def test_a_symlinked_directory_outside_the_root_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "photo.jpg").write_bytes(b"outside")
    root = tmp_path / "images"
    root.mkdir()
    os.symlink(outside, root / "linked")

    with pytest.raises(ValueError):
        safe_child_path(root, "linked/photo.jpg")


def test_a_symlinked_file_inside_the_root_is_allowed(tmp_path):
    target = tmp_path / "images" / "target.jpg"
    target.parent.mkdir()
    target.write_bytes(b"image")
    link = target.parent / "link.jpg"
    os.symlink(target, link)

    assert safe_child_path(target.parent, "link.jpg") == target.resolve()
