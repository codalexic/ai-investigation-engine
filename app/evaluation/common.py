import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.core.errors import ConfigurationError
from app.evaluation.metrics import bootstrap_ci, percentile


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def questions(paths: str, limit: int | None = None) -> list[dict]:
    if limit is not None and limit < 0:
        raise ConfigurationError("Limit must be nonnegative")
    rows = []
    seen = set()
    for name in paths.split(","):
        for item in read_jsonl(Path(name)):
            item = dict(item)
            item.setdefault("reference_answer", item.get("answer", ""))
            item.setdefault("source", "hotpotqa")
            item.setdefault("category", item.get("type", "unknown"))
            item.setdefault("expected_behavior", "answer")
            item.setdefault("notes", "")
            if item["id"] not in seen:
                rows.append(item)
                seen.add(item["id"])
    return rows if limit is None else rows[:limit]


def safe_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ConfigurationError("Unsafe result or collection identifier")
    return name


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def aggregate(rows: list[dict]) -> dict:
    names = sorted(
        {
            key
            for row in rows
            for key, value in row["metrics"].items()
            if isinstance(value, (int, float))
        }
    )
    metrics = {}
    for name in names:
        values = [r["metrics"][name] for r in rows if r["metrics"].get(name) is not None]
        metrics[name] = {
            "mean": sum(values) / len(values),
            "ci95": bootstrap_ci(values),
            "n": len(values),
        }
    latencies = [r["latency_ms"] for r in rows]
    return {
        "count": len(rows),
        "metrics": metrics,
        "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95)},
    }


def breakdown(rows: list[dict], field: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row[field]].append(row)
    return {key: aggregate(value) for key, value in sorted(groups.items())}


def table(summary: dict) -> str:
    lines = ["| Metric | Mean | 95% CI | N |", "|---|---:|---|---:|"]
    for name, value in summary.get("metrics", {}).items():
        lo, hi = value["ci95"]
        ci = f"{lo:.4f}-{hi:.4f}" if lo is not None else "n/a"
        lines.append(f"| {name} | {value['mean']:.4f} | {ci} | {value['n']} |")
    lines.append("\nLatency (ms): " + json.dumps(summary.get("latency_ms", {})))
    return "\n".join(lines)


def write_result(path: Path, result: dict) -> None:
    write_json(path, result)
    lines = []
    if "configs" in result:
        for name, config in result["configs"].items():
            lines.extend([f"## {name}", table(config["summary"])])
            for key in ("statistics", "index_seconds", "paragraphs", "subset_questions"):
                if key in config:
                    lines.append(key + ": " + json.dumps(config[key]))
            for field in ("source", "category"):
                for group, summary in config.get("by_" + field, {}).items():
                    lines.extend([f"### {field}: {group}", table(summary)])
    elif "summary" in result:
        lines.append(table(result["summary"]))
        for category, summary in result.get("by_category", {}).items():
            lines.extend([f"### {category}", table(summary)])
    else:
        lines.extend(["```json", json.dumps(result, indent=2), "```"])
    path.with_suffix(".md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
