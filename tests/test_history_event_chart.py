import csv

from dev.history_event.chart import MODEL_ORDER, MODEL_SETS, build_chart
from dev.history_event.io import read_json, write_json
from dev.history_event.models import MODEL_SPECS


def test_chart_exports_png_svg_csv_json_and_manifest(tmp_path):
    results = tmp_path / "results"
    for index, model_id in enumerate(MODEL_ORDER):
        summary = {
            "complete": True,
            "unresolved_errors": 0,
            "model": {"revision": MODEL_SPECS[model_id]["revision"]},
            "metrics": {"by_decade": {
                "1900": {
                    "event_count": 2,
                    "macro_mean_bpb": 1.0 + index,
                    "micro_bpb": 1.1 + index,
                    "standard_deviation": 0.2,
                    "standard_error": 0.1,
                    "total_nll_nats": 2.0,
                    "target_bytes": 2,
                },
                "1910": {
                    "event_count": 1,
                    "macro_mean_bpb": 1.5 + index,
                    "micro_bpb": 1.5 + index,
                    "standard_deviation": 0.0,
                    "standard_error": 0.0,
                    "total_nll_nats": 1.0,
                    "target_bytes": 1,
                },
            }},
        }
        write_json(results / model_id / "summary.json", summary)
    output = tmp_path / "chart"
    manifest = build_chart(results, output)
    for name in (
        "history-event-surprisingness.png", "history-event-surprisingness.svg",
        "history-event-surprisingness.csv", "history-event-surprisingness.json",
        "run-manifest.json",
    ):
        assert (output / name).is_file()
        assert (output / name).stat().st_size > 0
    with (output / "history-event-surprisingness.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 14
    assert rows[0]["macro_mean_bpb"] == "1.0"
    assert set(manifest["models"]) == set(MODEL_ORDER)
    assert read_json(output / "run-manifest.json")["files"] == manifest["files"]


def test_smollm_proxy_chart_has_no_fabricated_cutoff(tmp_path):
    results = tmp_path / "results"
    for model_id in MODEL_SETS["all-smollm3"]:
        write_json(results / model_id / "summary.json", {
            "complete": True,
            "unresolved_errors": 0,
            "model": {"revision": MODEL_SPECS[model_id]["revision"]},
            "metrics": {"by_decade": {"2020": {
                "event_count": 1,
                "macro_mean_bpb": 1.0,
                "micro_bpb": 1.0,
                "standard_deviation": 0.0,
                "standard_error": 0.0,
                "total_nll_nats": 1.0,
                "target_bytes": 1,
            }}},
        })
    output = tmp_path / "chart-smollm3"
    manifest = build_chart(results, output, model_set="all-smollm3")
    assert manifest["model_set"] == "all-smollm3"
    assert manifest["models"]["smollm3-3b"]["cutoff_year"] is None
    with (output / "history-event-surprisingness.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    smol = next(row for row in rows if row["model_id"] == "smollm3-3b")
    assert smol["cutoff_year"] == ""
