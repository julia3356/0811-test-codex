import sys
from pathlib import Path


# Ensure repo root is on sys.path so `import src.excel_transformer` works
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.excel_transformer.config import load_config  # noqa: E402
from src.excel_transformer.transform import transform_rows  # noqa: E402


def _write_config(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_readme_scenario_1(tmp_path: Path):
    # Use provided sample workbook
    excel_path = REPO_ROOT / "tests" / "data" / "sample.xlsx"

    # Scenario 1 config from README
    cfg_text = (
        """
        [map]
        {
          "原始记录":"record",
          "计分":"score",
          "原始记录-问题":"ask",
          "问题的积分":"ask_score"
        }

        [out]
        {
          "原始记录":"record",
          "计分":"score"
        }
        {
          "原始记录-问题":"ask",
          "问题的积分":"ask_score"
        }
        """
    )
    cfg_path = tmp_path / "config1.conf"
    _write_config(cfg_path, cfg_text)

    cfg = load_config(str(cfg_path))
    rows = transform_rows(
        excel_path=str(excel_path),
        display_to_internal=cfg.display_to_internal,
        out_groups=cfg.out_groups,
        header_row=1,
        row_numbers=[2],
    )

    # Expect two records for row 2
    assert rows == [
        {"原始记录": "记录B", "计分": 2},
        {"原始记录-问题": "问题B", "问题的积分": 8},
    ]


def test_readme_scenario_2(tmp_path: Path):
    excel_path = REPO_ROOT / "tests" / "data" / "sample.xlsx"

    # Scenario 2 config from README
    cfg_text = (
        """
        [map]
        {
          "原始记录":"record",
          "计分":"score",
          "标准回答":"answer-1",
          "猜测回答":"answer-2"
        }

        [out]
        {
          "原始记录":"record",
          "回答":{
            "name":"answer",
            "value":"answer-1",
            "ex": { "if":"score==2", "answer":"answer-2" }
          }
        }
        """
    )
    cfg_path = tmp_path / "config2.conf"
    _write_config(cfg_path, cfg_text)

    cfg = load_config(str(cfg_path))
    rows = transform_rows(
        excel_path=str(excel_path),
        display_to_internal=cfg.display_to_internal,
        out_groups=cfg.out_groups,
        header_row=1,
        row_numbers=[2],
    )

    # For row 2, score == 2, so "回答" uses "猜测答B"
    assert rows == [
        {"原始记录": "记录B", "回答": "猜测答B"},
    ]

