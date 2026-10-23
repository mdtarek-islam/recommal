"""Generate the results table and the results bar chart from artefacts/metrics.json.

Run from any folder:  python scripts/make_diagrams.py

Outputs:
  docs/assets/results-table.md             Markdown tables.
  docs/assets/diagrams/results-bar.svg     Grouped bar chart of MAP@10 for both directions.
  README.md                                Text between the results markers is replaced.

The script reads no other file. It writes no number that metrics.json does not hold.
The SVG uses a light panel, so it stays legible on light and dark pages.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
METRICS = ROOT / "artefacts" / "metrics.json"
TABLE_OUT = ROOT / "docs" / "assets" / "results-table.md"
SVG_OUT = ROOT / "docs" / "assets" / "diagrams" / "results-bar.svg"
README = ROOT / "README.md"

MARK_START = "<!-- results:start -->"
MARK_END = "<!-- results:end -->"

MODEL_LABELS = {
    "random": "Random vectors",
    "tfidf_svd": "TF-IDF + SVD",
    "sbert_cosine": "Raw SBERT cosine",
    "siamese": "Siamese",
    "siamese_popularity": "Siamese + popularity prior",
}
A2G, G2A = "anime->game", "game->anime"


def fmt(value: Any, places: int = 4) -> str:
    return f"{value:.{places}f}" if isinstance(value, (int, float)) else "n/a"


def load() -> dict[str, Any]:
    with METRICS.open(encoding="utf-8") as handle:
        return json.load(handle)


def get(node: dict[str, Any], *path: str) -> Any:
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def main_rows(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    results = data.get("results", {})
    return [(MODEL_LABELS.get(key, key), block) for key, block in results.items()]


def build_tables(data: dict[str, Any]) -> str:
    proto = data.get("protocol", {})
    lines = [
        f"Test split. Relevance: {proto.get('relevance', 'n/a')}. K = {proto.get('k', 'n/a')}. "
        f"Model version: `{proto.get('model_version', 'n/a')}`. Seed: {proto.get('seed', 'n/a')}.",
        "",
        "| Model | MAP@10 anime->game | MAP@10 game->anime | Mean MAP@10 | Mean P@10 | Mean Recall@10 |",
        "|---|---|---|---|---|---|",
    ]
    for label, block in main_rows(data):
        lines.append(
            f"| {label} | {fmt(get(block, A2G, 'map@10'))} | {fmt(get(block, G2A, 'map@10'))} "
            f"| {fmt(get(block, 'mean', 'map@10'))} | {fmt(get(block, 'mean', 'p@10'))} "
            f"| {fmt(get(block, 'mean', 'recall@10'))} |"
        )
    base_a = get(data, "results", "siamese", A2G, "base_rate")
    base_g = get(data, "results", "siamese", G2A, "base_rate")
    lines += [
        "",
        f"Base rate of a relevant candidate: {fmt(base_a)} (anime->game), {fmt(base_g)} (game->anime). "
        f"Test contrastive loss: {fmt(data.get('test_contrastive_loss'))} on {data.get('test_pairs', 'n/a')} pairs.",
        "",
        "| Ablation | Mean MAP@10 | Note |",
        "|---|---|---|",
    ]
    ab = data.get("ablations", {})
    drop = get(ab, "keyword_masked_test", "map_drop") or {}
    for key, label in (
        ("sbert_cosine", "Keyword-masked test games, raw SBERT"),
        ("siamese", "Keyword-masked test games, Siamese"),
    ):
        note = f"Drop of {fmt(drop.get(key))}" if key in drop else ""
        lines.append(f"| {label} | {fmt(get(ab, 'keyword_masked_test', key, 'mean', 'map@10'))} | {note} |")
    if "no_hard_negatives" in ab:
        lines.append(
            f"| No hard negatives, Siamese | {fmt(get(ab, 'no_hard_negatives', 'mean', 'map@10'))} "
            "| Test score. Selection used validation |"
        )
    rs = get(ab, "random_seeds", "map@10")
    if rs:
        lines.append(
            f"| Random vectors, {get(ab, 'random_seeds', 'n')} seeds | {fmt(rs.get('mean'))} "
            f"| Standard deviation {fmt(rs.get('std'))} |"
        )
    ts = get(ab, "training_seeds", "map@10")
    if ts:
        lines.append(
            f"| Siamese, {get(ab, 'training_seeds', 'n')} training seeds | {fmt(ts.get('mean'))} "
            f"| Standard deviation {fmt(ts.get('std'))} |"
        )
    return "\n".join(lines) + "\n"


def build_svg(data: dict[str, Any]) -> str:
    rows = [
        (label, get(b, A2G, "map@10"), get(b, G2A, "map@10"), get(b, "mean", "map@10")) for label, b in main_rows(data)
    ]
    values = [v for r in rows for v in r[1:3] if isinstance(v, (int, float))]
    top = max(values) if values else 0.1
    step = 0.02
    axis_max = (int(top / step) + 1) * step
    width, left, right = 760, 200, 40
    plot_w = width - left - right
    row_h, bar_h, gap = 56, 15, 4
    head = 78
    height = head + row_h * len(rows) + 48

    def x_of(value: float) -> float:
        return left + plot_w * value / axis_max

    out: list[str] = []
    add = out.append
    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-labelledby="t d">'
    )
    add('<title id="t">MAP@10 by model and direction</title>')
    desc = "; ".join(f"{escape(label)}: anime to game {fmt(a)}, game to anime {fmt(g)}" for label, a, g, _ in rows)
    add(f'<desc id="d">Grouped horizontal bars of test MAP@10. {desc}.</desc>')
    add(
        "<style>text{font-family:'Segoe UI',Helvetica,Arial,sans-serif;fill:#1f2328}"
        ".sub{fill:#57606a;font-size:12px}.lab{font-size:13px}.val{font-size:12px}"
        ".ttl{font-size:16px;font-weight:600}.grid{stroke:#d0d7de;stroke-width:1}</style>"
    )
    add(f'<rect width="{width}" height="{height}" rx="10" fill="#ffffff" stroke="#d0d7de"/>')
    add('<text class="ttl" x="20" y="28">Test MAP@10 by model and query direction</text>')
    add(
        '<rect x="20" y="42" width="12" height="12" fill="#1d4ed8"/>'
        '<text class="sub" x="38" y="53">anime query, game candidates</text>'
    )
    add(
        '<rect x="250" y="42" width="12" height="12" fill="#b45309"/>'
        '<text class="sub" x="268" y="53">game query, anime candidates</text>'
    )
    ticks = round(axis_max / step)
    base_y = head + row_h * len(rows)
    for i in range(ticks + 1):
        tv = i * step
        x = x_of(tv)
        add(f'<line class="grid" x1="{x:.1f}" y1="{head - 6}" x2="{x:.1f}" y2="{base_y}"/>')
        add(f'<text class="sub" x="{x:.1f}" y="{base_y + 16}" text-anchor="middle">{tv:.2f}</text>')
    for idx, (label, a, g, _mean) in enumerate(rows):
        y0 = head + idx * row_h + 6
        bold = ' font-weight="600"' if label == "Siamese" else ""
        add(f'<text class="lab" x="{left - 10}" y="{y0 + bar_h + 3}" text-anchor="end"{bold}>{escape(label)}</text>')
        for off, val, colour in ((0, a, "#1d4ed8"), (bar_h + gap, g, "#b45309")):
            if not isinstance(val, (int, float)):
                continue
            w = max(x_of(val) - left, 1)
            y = y0 + off
            add(f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{colour}"/>')
            add(f'<text class="val" x="{left + w + 6:.1f}" y="{y + bar_h - 3}">{fmt(val)}</text>')
    add(
        f'<text class="sub" x="{left}" y="{height - 8}">MAP@10, higher is better. '
        f"Axis ends at {axis_max:.2f}. Source: artefacts/metrics.json.</text>"
    )
    add("</svg>")
    return "\n".join(out) + "\n"


def update_readme(table_md: str) -> bool:
    if not README.exists():
        return False
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(MARK_START) + r".*?" + re.escape(MARK_END), re.S)
    if not pattern.search(text):
        return False
    block = f"{MARK_START}\n{table_md}{MARK_END}"
    README.write_text(pattern.sub(lambda _m: block, text), encoding="utf-8", newline="\n")
    return True


def main() -> None:
    if not METRICS.exists():
        raise SystemExit(f"Missing {METRICS.relative_to(ROOT)}. Run python -m src.evaluation.evaluate first.")
    data = load()
    table_md = build_tables(data)
    TABLE_OUT.parent.mkdir(parents=True, exist_ok=True)
    SVG_OUT.parent.mkdir(parents=True, exist_ok=True)
    TABLE_OUT.write_text(table_md, encoding="utf-8", newline="\n")
    SVG_OUT.write_text(build_svg(data), encoding="utf-8", newline="\n")
    updated = update_readme(table_md)
    print(f"wrote {TABLE_OUT.relative_to(ROOT)}")
    print(f"wrote {SVG_OUT.relative_to(ROOT)}")
    print("README results block updated" if updated else "README results markers not found")


if __name__ == "__main__":
    main()
