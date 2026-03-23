from pathlib import Path

from commands.text_block_replace import execute


def test_text_block_replace_on_fortest_add_function(tmp_path: Path):
    path = tmp_path / "fortest.py"
    path.write_text(
        "def greet(name):\n"
        "    return f\"Hello, {name}!\"\n\n\n"
        "def add(a, b):\n"
        "    return a + b + 1\n",
        encoding="utf-8",
    )

    result = execute(
        {
            "path": str(path),
            "first_block_lines": ["def add(a, b):"],
            "last_block_lines": ["    return a + b + 1"],
            "replace_with": "def add(a, b):\n    return a + b",
        }
    )

    assert result == "OK: patched 1 block"
    assert "return a + b\n" in path.read_text(encoding="utf-8")


def test_text_block_replace_multiple_blocks_on_fortest(tmp_path: Path):
    path = tmp_path / "fortest.py"
    path.write_text(
        "def greet(name):\n"
        "    return f\"Hello, {name}!\"\n\n\n"
        "def add(a, b):\n"
        "    return a + b + 1\n",
        encoding="utf-8",
    )

    result = execute(
        {
            "path": str(path),
            "first_block_lines": ["def greet(name):"],
            "last_block_lines": ["    return f\"Hello, {name}!\""],
            "replace_with": "def greet(name):\n    return f\"Hi, {name}!\"",
        }
    )

    content = path.read_text(encoding="utf-8")
    assert result == "OK: patched 1 block"
    assert "return f\"Hi, {name}!\"\n" in content
    assert "return a + b + 1\n" in content


def test_text_block_replace_missing_anchor_returns_error(tmp_path: Path):
    path = tmp_path / "fortest.py"
    path.write_text(
        "def greet(name):\n"
        "    return f\"Hello, {name}!\"\n\n\n"
        "def add(a, b):\n"
        "    return a + b + 1\n",
        encoding="utf-8",
    )

    result = execute(
        {
            "path": str(path),
            "first_block_lines": ["def subtract(a, b):"],
            "last_block_lines": ["    return a - b"],
            "replace_with": "def subtract(a, b):\n    return a - b",
        }
    )

    assert result == "ERROR: block[0] not found"


def test_text_block_replace_empty_replace_removes_block(tmp_path: Path):
    path = tmp_path / "fortest.py"
    path.write_text(
        "def greet(name):\n"
        "    return f\"Hello, {name}!\"\n\n\n"
        "def add(a, b):\n"
        "    return a + b + 1\n",
        encoding="utf-8",
    )

    result = execute(
        {
            "path": str(path),
            "first_block_lines": ["def add(a, b):"],
            "last_block_lines": ["    return a + b + 1"],
            "replace_with": "",
        }
    )

    content = path.read_text(encoding="utf-8")
    assert result == "OK: patched 1 block"
    assert "def add(a, b):" not in content
