"""評価結果の記録の契約テスト（FR-041 / FR-042 / FR-043 / FR-071〜073 / SC-016 / SC-027）。

`tests/eval/records.py` を固定入力で検証する（LLM もネットワークも使わない）。

固定する契約:

- ファイル名は `{dataset}__{config_name}__{commit}__{model_slug}.jsonl`（FR-072）
- データセットの名前と指紋を実行の文脈に記録する（FR-073）
- 書き込みは既定で追記。既存を置き換えるのは `overwrite=True` のときだけ（SC-027）
- JSONL 1 行 1 レコード。レコードの行は `id` / `prompt` / `article` の 3 項目（FR-071）
- UTF-8・`ensure_ascii=False`（FR-043）
- 既定の保存先は `artifacts/eval/`（追跡外）。`TR_EVAL_OUT_DIR` で変更（FR-043）
- 2 つの結果は**名前で指定**して比較でき、生成も判定も繰り返さない（FR-041 / SC-016）
"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

#: リポジトリ直下（`tests/` は配布物に含めないため、テストから読み込むために足す）。
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.eval import datasets, records

#: 記録のテストで使う実行の識別子。
COMMIT = "abc1234"

#: 記録のテストで使う判定モデル名。
JUDGE_MODEL = "openai:mimo-v2.5"

#: 既定のデータセット名。
DATASET = datasets.DEFAULT_DATASET


def _run(
    *,
    config_name: str = "baseline",
    model: str = JUDGE_MODEL,
    axes: Sequence[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    scores: Mapping[str, Any] | None = None,
) -> records.RunContext:
    """1 回の評価実行の文脈（保存済みの結果を組み立てる）。"""
    dataset = datasets.load_dataset(DATASET)
    return records.RunContext(
        dataset=dataset.name,
        dataset_fingerprint=dataset.fingerprint,
        config_name=config_name,
        commit=COMMIT,
        platform="x",
        model=model,
        judge_model=JUDGE_MODEL,
        judge_model_is_generator=model == JUDGE_MODEL,
        config={"include_self_review": config_name != "baseline"},
        axes=axes
        or [
            {"axis": "relevance", "normalized": 0.8 if config_name == "baseline" else 0.5},
            {"axis": "structure", "normalized": 0.4},
        ],
        axis_order=["structure", "relevance"],
        excluded_axes=["correctness"],
        overall_quality=0.8 if config_name == "baseline" else 0.5,
        usage=usage
        or {"calls": 8, "prompt_tokens": 1200, "completion_tokens": 800, "total_tokens": 2000},
        scores=scores or {},
    )


def _records(prefix: str, count: int = 2) -> list[dict[str, str]]:
    """結果のレコード（レポートが空の 1 件を含める）。"""
    made = [
        {
            "id": f"{prefix}-{index}",
            "prompt": f"{prefix} の指示 {index}",
            "article": f"# 見出し {index}",
        }
        for index in range(count)
    ]
    if made:
        made[-1]["article"] = ""
    return made


# --- ファイル名と保存先（FR-043 / FR-072） ---------------------------------


def test_result_filename_follows_the_contract() -> None:
    """ファイル名は `{dataset}__{config_name}__{commit}__{model_slug}.jsonl`（FR-072）。"""
    name = records.result_filename(
        dataset="tr-basic", config_name="candidate", commit=COMMIT, model=JUDGE_MODEL
    )

    assert name == f"tr-basic__candidate__{COMMIT}__openai-mimo-v2.5.jsonl"
    # 4 つの識別子がすべて名前に現れる（同名の結果が別の構成を指さない）。
    for part in ("tr-basic", "candidate", COMMIT, "openai-mimo-v2.5"):
        assert part in name


def test_model_name_is_slugified_for_the_filename() -> None:
    """モデル名の区切り文字はファイル名に使える形へ置き換える（FR-072）。"""
    assert records.model_slug("openai:mimo-v2.5") == "openai-mimo-v2.5"
    assert records.model_slug("openai/gpt-4.1") == "openai-gpt-4.1"
    assert "/" not in records.model_slug("a/b:c")


def test_default_out_dir_is_artifacts_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """保存先の既定は `artifacts/eval/`。`TR_EVAL_OUT_DIR` と引数で変更できる（FR-043）。"""
    assert records.DEFAULT_OUT_DIR == Path("artifacts/eval")

    monkeypatch.delenv("TR_EVAL_OUT_DIR", raising=False)
    assert records.resolve_out_dir() == Path("artifacts/eval")
    assert records.resolve_out_dir(tmp_path) == tmp_path

    monkeypatch.setenv("TR_EVAL_OUT_DIR", str(tmp_path / "eval"))
    assert records.resolve_out_dir() == tmp_path / "eval"
    # 引数は環境変数より優先する。
    assert records.resolve_out_dir(tmp_path) == tmp_path


def test_write_result_creates_the_directory_and_reports_the_count(tmp_path: Path) -> None:
    """保存先が無ければ作成し、保存先と件数を返す（FR-043）。"""
    out_dir = tmp_path / "not" / "created" / "yet"
    path, count = records.write_result(_run(), _records("baseline"), out_dir=out_dir)

    assert path.parent == out_dir
    assert path.is_file()
    assert count == 2


# --- 記録する文脈（FR-042 / FR-043 / FR-061 / FR-073） ----------------------


def test_the_dataset_name_and_fingerprint_are_recorded(tmp_path: Path) -> None:
    """データセットの名前と内容の指紋を記録する（FR-073）。"""
    dataset = datasets.load_dataset(DATASET)
    path, _ = records.write_result(_run(), _records("baseline"), out_dir=tmp_path)

    result = records.load_result(path)
    assert result["dataset"] == DATASET
    assert result["dataset_fingerprint"] == dataset.fingerprint
    assert len(result["dataset_fingerprint"]) == 16

    # 中身が変われば指紋も変わる（過去の結果と同一視できる／できないが判定できる。SC-032）。
    changed = [
        datasets.DatasetEntry(id=entry.id, prompt=entry.prompt + "（変更）")
        for entry in dataset.entries
    ]
    assert datasets.fingerprint(changed) != dataset.fingerprint


def test_the_run_context_records_the_settings_and_the_judge_model(tmp_path: Path) -> None:
    """設定の中身・識別子・判定モデル名・生成と同一かどうかを記録する（FR-043 / FR-069）。"""
    path, _ = records.write_result(
        _run(config_name="candidate", model=JUDGE_MODEL), _records("candidate"), out_dir=tmp_path
    )

    result = records.load_result(path)
    assert result["config_name"] == "candidate"
    assert result["commit"] == COMMIT
    assert result["platform"] == "x"
    assert result["model"] == JUDGE_MODEL
    assert result["judge_model"] == JUDGE_MODEL
    assert result["judge_model_is_generator"] is True
    assert result["config"] == {"include_self_review": True}
    assert result["records"] == 2
    assert result["articles_empty"] == 1
    assert [row["axis"] for row in result["axes"]] == ["relevance", "structure"]
    assert result["axis_order"] == ["structure", "relevance"]
    assert result["excluded_axes"] == ["correctness"]


# --- レコードごとの採点（FR-039 / FR-071） ---------------------------------


def test_per_record_scores_are_linked_by_record_id(tmp_path: Path) -> None:
    """レコードごとの採点を識別子で結び付けて記録する（FR-039 / FR-071）。"""
    written = _records("baseline", count=2)
    scores = {
        record["id"]: {
            "axes": [{"axis": "relevance", "normalized": 0.8, "reason": "トピックに合う"}],
            "overall_quality": 0.8,
            "axis_order": ["relevance"],
            "excluded_axes": ["correctness"],
        }
        for record in written
    }
    path, _ = records.write_result(_run(scores=scores), written, out_dir=tmp_path)

    result = records.load_result(path)
    assert set(result["scores"]) == {record["id"] for record in written}
    assert result["scores"]["baseline-0"]["axes"][0]["normalized"] == pytest.approx(0.8)
    # レコードの行と採点は識別子で結び付けられる（行の形は 3 項目のまま）。
    assert {record.id for record in records.load_records(path)} == set(result["scores"])


def test_usage_is_recorded_and_missing_usage_is_unknown(tmp_path: Path) -> None:
    """トークン数と呼び出し回数を併記する。得られなければ「不明」として記録する（FR-042 / FR-061）。"""
    path, _ = records.write_result(_run(), _records("baseline"), out_dir=tmp_path)
    usage = records.load_result(path)["usage"]
    assert usage["calls"] == 8
    assert usage["total_tokens"] == 2000

    assert records.usage_summary(None)["status"] == records.UNKNOWN
    assert records.usage_summary({})["total_tokens"] is None
    assert records.usage_summary({"calls": 3})["calls"] == 3
    assert records.usage_summary({"calls": 3})["total_tokens"] is None


# --- JSONL の形（FR-043 / FR-071） -----------------------------------------


def test_records_are_written_one_line_per_record(tmp_path: Path) -> None:
    """1 行 1 レコード。レコードの行は 3 項目だけ（FR-071）。"""
    written = _records("baseline", count=3)
    path, _ = records.write_result(_run(), written, out_dir=tmp_path)

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1 + len(written)

    assert json.loads(lines[0])["kind"] == records.RUN_KIND
    for line, expected in zip(lines[1:], written, strict=True):
        assert json.loads(line) == expected
        assert set(json.loads(line)) == {"id", "prompt", "article"}

    assert [record.model_dump() for record in records.load_records(path)] == written


def test_japanese_text_is_written_without_escaping(tmp_path: Path) -> None:
    """UTF-8 で書き、`ensure_ascii=False` にする（FR-043）。"""
    path, _ = records.write_result(_run(), _records("baseline"), out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "baseline の指示 0" in text
    assert "\\u" not in text


def test_a_malformed_record_is_rejected() -> None:
    """レコードの形（`id` / `prompt` / `article`）を満たさない入力は拒否する（FR-071）。"""
    with pytest.raises(records.ResultError, match="レコードの形"):
        records.record_line({"id": "only-id"})

    with pytest.raises(records.ResultError, match="レコードの形"):
        records.record_line({"id": "a", "prompt": "b", "article": "c", "extra": "d"})


# --- 追記と上書き（SC-027） ------------------------------------------------


def test_existing_results_are_appended_by_default(tmp_path: Path) -> None:
    """既定は追記で、既存の結果を消さない（SC-027）。"""
    first, _ = records.write_result(_run(), _records("first"), out_dir=tmp_path)
    second, _ = records.write_result(_run(), _records("second", count=1), out_dir=tmp_path)

    assert first == second
    runs = records.load_runs(second)
    assert len(runs) == 2  # 1 回目の実行の文脈も残っている
    assert {record.id for record in records.load_records(second)} == {
        "first-0",
        "first-1",
        "second-0",
    }
    assert runs[0]["dataset_fingerprint"] == runs[1]["dataset_fingerprint"]


def test_only_overwrite_replaces_the_existing_result(tmp_path: Path) -> None:
    """`overwrite=True` を明示したときだけ既存を置き換える（SC-027）。"""
    path, _ = records.write_result(_run(), _records("first"), out_dir=tmp_path)
    _, count = records.write_result(
        _run(config_name="baseline"),
        _records("replacement", count=1),
        out_dir=tmp_path,
        overwrite=True,
    )

    assert count == 1
    assert len(records.load_runs(path)) == 1
    assert [record.id for record in records.load_records(path)] == ["replacement-0"]


# --- 保存済みの結果の比較（FR-041 / SC-016） ------------------------------


def test_results_are_compared_by_name(tmp_path: Path) -> None:
    """保存済みの 2 つの結果を名前で指定して比較する（SC-016）。"""
    baseline, _ = records.write_result(
        _run(config_name="baseline"), _records("baseline"), out_dir=tmp_path
    )
    records.write_result(_run(config_name="candidate"), _records("candidate"), out_dir=tmp_path)

    result = records.compare_saved(
        baseline.stem, "tr-basic__candidate__abc1234__openai-mimo-v2.5", out_dir=tmp_path
    )

    assert result["comparable"] is True
    assert result["winner"] == "left"
    assert result["configs"] == {"left": "baseline", "right": "candidate"}
    assert result["files"]["left"] == str(baseline)
    rows = {row["axis"]: row for row in result["axes"]}
    assert rows["relevance"]["left"] == pytest.approx(0.8)
    assert rows["relevance"]["right"] == pytest.approx(0.5)
    assert rows["relevance"]["preference"] == "left"
    assert rows["structure"]["preference"] == "tie"


def test_comparison_does_not_regenerate_or_judge(tmp_path: Path) -> None:
    """比較は保存済みの結果を読むだけ（生成も判定もしない。FR-041 / SC-016）。"""
    baseline, _ = records.write_result(
        _run(config_name="baseline"), _records("baseline"), out_dir=tmp_path
    )
    candidate, _ = records.write_result(
        _run(config_name="candidate"), _records("candidate"), out_dir=tmp_path
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    # 生成の入口（判定モデル）を注入できる余地が無い = 2 つを順に走らせる経路を持たない。
    assert set(inspect.signature(records.compare_saved).parameters) == {
        "left",
        "right",
        "out_dir",
        "rng",
    }

    records.compare_saved(baseline.stem, candidate.stem, out_dir=tmp_path)

    after = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert after == before  # 結果ファイルを書き換えない・増やさない


def test_a_missing_result_is_named_and_comparison_does_not_start(tmp_path: Path) -> None:
    """指定した結果が無い場合は比較を開始せず、不足している対象を名指しする（FR-041）。"""
    baseline, _ = records.write_result(
        _run(config_name="baseline"), _records("baseline"), out_dir=tmp_path
    )

    with pytest.raises(records.MissingResultError) as excinfo:
        records.compare_saved(
            baseline.stem, "tr-basic__candidate__abc1234__missing", out_dir=tmp_path
        )

    assert "missing" in str(excinfo.value)
    assert len(records.load_runs(baseline)) == 1  # 比較を始めていないので結果は増えない


# --- データセットの解決（FR-070） ------------------------------------------


def test_the_default_dataset_is_a_repository_file() -> None:
    """既定のデータセットはリポジトリ内の固定ファイル（外部サービスを必須にしない。FR-070）。"""
    dataset = datasets.load_dataset()

    assert dataset.name == datasets.DEFAULT_DATASET
    assert datasets.fixture_path().is_file()
    assert datasets.fixture_path().parent == datasets.FIXTURE_DIR
    assert dataset.entries
    assert all(entry.id and entry.prompt for entry in dataset.entries)
    assert dataset.fingerprint == datasets.fingerprint(dataset.entries)


def test_an_unreachable_dataset_is_reported_without_falling_back() -> None:
    """到達できない名前は失敗を明示する（既定へ黙って切り替えない。FR-070）。"""
    with pytest.raises(datasets.DatasetError) as excinfo:
        datasets.load_dataset("tr-unknown")

    assert "tr-unknown" in str(excinfo.value)
    assert datasets.DEFAULT_DATASET in str(excinfo.value)  # 切り替えないことを明示する


def test_a_broken_dataset_is_rejected(tmp_path: Path) -> None:
    """名前の不一致と識別子の重複を拒否する（比較の単位を崩さない。FR-070 / FR-073）。"""
    entries = [{"id": "a", "prompt": "1"}, {"id": "a", "prompt": "2"}]
    duplicated = tmp_path / "tr-dup.json"
    duplicated.write_text(
        json.dumps({"name": "tr-dup", "entries": entries}, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(datasets.DatasetError, match="重複"):
        datasets.load_dataset("tr-dup", fixtures_dir=tmp_path)

    mismatched = tmp_path / "tr-dup.json"
    mismatched.write_text(
        json.dumps({"name": "other", "entries": entries[:1]}, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(datasets.DatasetError, match="名前が一致しません"):
        datasets.load_dataset("tr-dup", fixtures_dir=tmp_path)

    empty = tmp_path / "tr-empty.json"
    empty.write_text(json.dumps({"name": "tr-empty", "entries": []}), encoding="utf-8")
    with pytest.raises(datasets.DatasetError, match="指示がありません"):
        datasets.load_dataset("tr-empty", fixtures_dir=tmp_path)
