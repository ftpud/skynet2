from pathlib import Path

from commands.apply_patch import execute


def test_apply_patch_update_file(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("one\ntwo\n", encoding="utf-8")

    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {path}\n"
        "@@\n"
        " one\n"
        "-two\n"
        "+three\n"
        "*** End Patch\n"
    )

    result = execute({"patch": patch})
    assert result == "OK: applied 1 operation(s)"
    assert path.read_text(encoding="utf-8") == "one\nthree\n"


def test_apply_patch_add_and_delete_file(tmp_path: Path):
    add_path = tmp_path / "new.txt"
    del_path = tmp_path / "old.txt"
    del_path.write_text("x\n", encoding="utf-8")

    patch = (
        "*** Begin Patch\n"
        f"*** Add File: {add_path}\n"
        "+hello\n"
        "+world\n"
        f"*** Delete File: {del_path}\n"
        "*** End Patch\n"
    )

    result = execute({"patch": patch})
    assert result == "OK: applied 2 operation(s)"
    assert add_path.read_text(encoding="utf-8") == "hello\nworld\n"
    assert not del_path.exists()
