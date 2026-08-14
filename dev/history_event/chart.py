"""Combine complete model summaries into paper-style chart artifacts."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .io import read_json, sha256_bytes, write_json
from .models import MODEL_SPECS


MODEL_ORDER = [
    "think-unbounded-d32-step9600",
    "gpt1900-d34",
    "gpt1900-sft",
    "llama-3.1-8b-instruct",
]
COLORS = {
    "think-unbounded-d32-step9600": "#d95f02",
    "gpt1900-d34": "#1b9e77",
    "gpt1900-sft": "#66a61e",
    "llama-3.1-8b-instruct": "#7570b3",
}


def build_chart(results_root: Path, output_dir: Path) -> dict:
    summaries = {}
    for model_id in MODEL_ORDER:
        path = results_root / model_id / "summary.json"
        if not path.exists():
            raise FileNotFoundError(f"missing model summary: {path}")
        summary = read_json(path)
        spec = MODEL_SPECS[model_id]
        if not summary.get("complete") or summary.get("unresolved_errors"):
            raise RuntimeError(f"{model_id} is not complete: {summary}")
        model = summary.get("model") or {}
        if model.get("revision") != spec["revision"]:
            raise RuntimeError(f"{model_id} revision mismatch")
        summaries[model_id] = summary

    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for model_id in MODEL_ORDER:
        summary = summaries[model_id]
        for decade, metrics in summary["metrics"]["by_decade"].items():
            records.append({
                "model_id": model_id,
                "display_name": MODEL_SPECS[model_id]["display_name"],
                "cutoff_year": MODEL_SPECS[model_id]["cutoff_year"],
                "decade": int(decade),
                **metrics,
            })
    fields = [
        "model_id", "display_name", "cutoff_year", "decade", "event_count",
        "macro_mean_bpb", "micro_bpb", "standard_deviation", "standard_error",
        "total_nll_nats", "target_bytes",
    ]
    csv_path = output_dir / "history-event-surprisingness.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path = output_dir / "history-event-surprisingness.json"
    write_json(json_path, {"models": summaries, "decades": records})

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(11.5, 6.5))
    for model_id in MODEL_ORDER:
        model_rows = [row for row in records if row["model_id"] == model_id]
        x = [row["decade"] for row in model_rows]
        y = [row["macro_mean_bpb"] for row in model_rows]
        se = [row["standard_error"] for row in model_rows]
        color = COLORS[model_id]
        axis.plot(x, y, marker="o", markersize=3, linewidth=2, color=color,
                  label=MODEL_SPECS[model_id]["display_name"])
        axis.fill_between(x, [a - b for a, b in zip(y, se)], [a + b for a, b in zip(y, se)],
                          color=color, alpha=0.12, linewidth=0)
        cutoff = MODEL_SPECS[model_id]["cutoff_year"]
        axis.axvline(cutoff, color=color, linestyle="--", linewidth=1.2, alpha=0.7)
    axis.set_xlabel("Event decade")
    axis.set_ylabel("Bits per byte (BPB)")
    axis.set_title("HISTORY-EVENT surprisingness (independent reconstruction)")
    axis.grid(axis="y", alpha=0.25)
    axis.legend(frameon=False)
    figure.tight_layout()
    png_path = output_dir / "history-event-surprisingness.png"
    svg_path = output_dir / "history-event-surprisingness.svg"
    figure.savefig(png_path, dpi=220)
    figure.savefig(svg_path)
    plt.close(figure)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "history_event_surprisingness_chart",
        "metric": "per-event target NLL / (ln(2) * semantic target UTF-8 bytes), macro mean by decade",
        "models": {
            model_id: {
                "revision": MODEL_SPECS[model_id]["revision"],
                "cutoff_year": MODEL_SPECS[model_id]["cutoff_year"],
                "summary_sha256": sha256_bytes(
                    (results_root / model_id / "summary.json").read_bytes()
                ),
            }
            for model_id in MODEL_ORDER
        },
        "files": {
            path.name: sha256_bytes(path.read_bytes())
            for path in (png_path, svg_path, csv_path, json_path)
        },
    }
    write_json(output_dir / "run-manifest.json", manifest)
    return manifest
