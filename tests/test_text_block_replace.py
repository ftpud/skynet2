from pathlib import Path

from commands.text_block_replace import execute


def test_text_block_replace_rejects_duplicate_ranges(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_text("a\nb\nc\n", encoding="utf-8")

    result = execute(
        {
            "path": str(path),
            "blocks": [
                {
                    "line_range": "1-2",
                    "first_block_line": "a",
                    "last_block_line": "b",
                    "replace_with": "x\ny\n",
                },
                {
                    "line_range": "1-2",
                    "first_block_line": "a",
                    "last_block_line": "b",
                    "replace_with": "z\n",
                },
            ],
        }
    )

    assert result == "ERROR: duplicate block range; aborting for safety"


def test_text_block_replace_accepts_single_line_file_without_trailing_newline(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_text("only line", encoding="utf-8")

    result = execute(
        {
            "path": str(path),
            "blocks": [
                {
                    "line_range": "1-1",
                    "first_block_line": "only line",
                    "last_block_line": "only line",
                    "replace_with": "updated",
                }
            ],
        }
    )

    assert result.startswith("OK: replaced 1 block(s)")
    assert path.read_text(encoding="utf-8") == "updated"
