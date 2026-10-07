"""Export the closest-to-raw layers for one decoded battle capture.

The exporter deliberately keeps three different representations separate:
1. exact visible Lua strings, including markup and placeholders;
2. decoded event records, including raw integer arguments and unresolved IDs;
3. a manifest pointing at the original binary blobs used by the decoder.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path)
    parser.add_argument("--stream", required=True)
    parser.add_argument("--ui-seconds", type=float, default=7.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    session = args.session
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    raw_events = [
        row
        for row in read_jsonl(session / "decoded" / "raw_events.jsonl")
        if row.get("stream_id") == args.stream
    ]
    if not raw_events:
        raise SystemExit(f"No raw events found for stream {args.stream}")

    # Keep the exact decoded records. No text cleanup or field normalization.
    write_jsonl(output / "战报001_原始事件参数.jsonl", raw_events)

    timeline_by_index = {
        row["event_index"]: row
        for row in read_jsonl(session / "decoded" / "timeline.jsonl")
        if row.get("stream_id") == args.stream
    }
    with (output / "战报001_原始事件_对照.txt").open("w", encoding="utf-8") as handle:
        for row in raw_events:
            index = row["event_index"]
            timeline = timeline_by_index.get(index, {})
            handle.write(
                f"[事件 {index}][回合 {row.get('round')}] "
                f"event_id={row['event_id']} {row.get('event_name', '')}\n"
            )
            if timeline.get("text"):
                handle.write(f"显示解释: {timeline['text']}\n")
            handle.write(
                "原始参数: "
                + json.dumps(row.get("args", {}), ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            handle.write("原始整数: " + json.dumps(row.get("raw_ints", []), ensure_ascii=False) + "\n")
            if row.get("names"):
                handle.write(
                    "已映射名称: "
                    + json.dumps(row["names"], ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
            if row.get("unresolved_ids"):
                handle.write(
                    "未映射ID: "
                    + json.dumps(row["unresolved_ids"], ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
            handle.write("\n")

    summary = json.loads((session / "decoded" / "decode_summary.json").read_text(encoding="utf-8"))
    stream_info = next(item for item in summary["streams"] if item["stream_id"] == args.stream)
    source_paths = [session / source["path"] for source in stream_info["sources"]]
    source_rows = list(read_jsonl(session / "blobs" / "index.jsonl"))
    source_by_path = {row["path"]: row for row in source_rows}
    source_meta = [source_by_path[source["path"]] for source in stream_info["sources"]]
    source_times = [datetime.fromisoformat(row["captured_at"]) for row in source_meta]
    ui_start = min(source_times)
    ui_end = ui_start + timedelta(seconds=args.ui_seconds)

    visible = []
    for row in read_jsonl(session / "raw" / "visible_text.jsonl"):
        captured = datetime.fromisoformat(row["captured_at"])
        if ui_start <= captured <= ui_end:
            visible.append(row)

    write_jsonl(output / "战报001_原始UI字符串.jsonl", visible)
    with (output / "战报001_原始UI字符串.txt").open("w", encoding="utf-8") as handle:
        for row in visible:
            handle.write(f"[{row['captured_at']}] count={row['count']} func={row['func']}\n")
            handle.write(row["text"])
            handle.write("\n\n")

    manifest = {
        "session": str(session),
        "stream_id": args.stream,
        "event_count": len(raw_events),
        "ui_window": {
            "start": ui_start.isoformat(),
            "end": ui_end.isoformat(),
            "record_count": len(visible),
        },
        "binary_sources": [
            {
                "path": str(path),
                "relative_path": meta["path"],
                "sha256": meta["sha256"],
                "size": meta["size"],
                "captured_at": meta["captured_at"],
                "decode_mode": next(
                    source["mode"]
                    for source in stream_info["sources"]
                    if source["path"] == meta["path"]
                ),
            }
            for path, meta in zip(source_paths, source_meta)
        ],
    }
    (output / "战报001_原始层说明.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
