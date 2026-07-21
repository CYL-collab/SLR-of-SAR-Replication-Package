"""Plot the number of SAR papers for different system types.

The source CSV stores detailed ``system_type_tag`` values in Chinese and
English.  This script maps those values to the eleven system-type families
used by the review figure.  Every paper is assigned to exactly one family;
unknown tags raise an error so that taxonomy changes cannot silently alter the
figure.
"""

from __future__ import annotations

import argparse
import csv
import html
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

from plot_sar_papers_per_year import BAR, GRID, INK, WHITE, centered_text, font


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "final_list_with_venue.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures"

WIDTH, HEIGHT = 3000, 1600
PLOT_LEFT, PLOT_RIGHT = 790, WIDTH - 105
PLOT_TOP, PLOT_BOTTOM = 65, HEIGHT - 245

CATEGORY_ORDER = [
    "Safety-critical Systems",
    "Database Systems",
    "Emerging Systems",
    "Specialized Systems",
    "Cluster Systems",
    "Mobile Systems",
    "Cloud, fog and edge computing",
    "Desktop Operating Systems",
    "Virtualized Systems",
    "Unspecified",
    "Server Systems",
]

# Mixed tags require an explicit primary family.  Keeping these decisions in
# one table makes the mutually exclusive counting rule easy to review.
MIXED_TAG_OVERRIDES = {
    "Android&web服务器": "Mobile Systems",
    "移动应用&云服务器": "Mobile Systems",
    "高可靠性软件系统&移动软件系统": "Safety-critical Systems",
    "深度学习系统&虚拟化系统": "Virtualized Systems",
    "虚拟化系统&集群": "Virtualized Systems",
    "Linux、MySQL、AXIS、HTTPD": "Server Systems",
    "web服务器（Apache）、工业电信系统": "Server Systems",
    "web服务器、操作系统": "Server Systems",
    "web服务器、操作系统（Linux、Apache）": "Server Systems",
}

SPECIALIZED_TAGS = {
    "Jest",
    "JVM",
    "network management",
    "传感器网络系统",
    "电信应用",
    "电子商务系统",
    "分布式应用程序",
    "基于组件的系统",
    "计算密集型",
    "面向对象的软件",
    "嵌入式系统",
    "软件系统",
    "视频点播系统与真实世界生产系统",
    "数据缓存系统",
    "网络搜索系统",
    "卸载系统",
    "应用程序",
    "专用系统",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot the number of SAR papers for different system types."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def contains_any(value: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment.casefold() in value.casefold() for fragment in fragments)


def system_category(raw_tag: str) -> str:
    """Map one detailed repository tag to one figure category."""
    tag = raw_tag.strip()
    if not tag:
        raise ValueError("Blank system_type_tag")
    if tag in MIXED_TAG_OVERRIDES:
        return MIXED_TAG_OVERRIDES[tag]
    if tag == "非特定的":
        return "Unspecified"
    if contains_any(
        tag,
        (
            "安全关键",
            "任务关键",
            "高可靠性",
            "深空",
            "Space system",
            "Fermilab",
            "CPS",
            "智能电网",
            "双版本容错",
        ),
    ):
        return "Safety-critical Systems"
    if "数据库" in tag:
        return "Database Systems"
    if contains_any(tag, ("Android", "移动")):
        return "Mobile Systems"
    if contains_any(tag, ("云", "雾", "边缘", "Docker", "Kubernetes", "MEC")):
        return "Cloud, fog and edge computing"
    if contains_any(tag, ("虚拟", "VMM", "KVM", "VM（")):
        return "Virtualized Systems"
    if "集群" in tag:
        return "Cluster Systems"
    if contains_any(tag, ("web", "服务器", "server", "Apache", "client-server")):
        return "Server Systems"
    if contains_any(tag, ("Linux", "Windows", "OS", "UNIX", "ext2", "Unikernels")):
        return "Desktop Operating Systems"
    if contains_any(
        tag,
        ("区块链", "深度学习", "LLM", "SDN", "物联网", "微服务", "无人机"),
    ):
        return "Emerging Systems"
    if tag in SPECIALIZED_TAGS:
        return "Specialized Systems"
    raise ValueError(f"Unmapped system_type_tag: {raw_tag!r}")


def load_system_counts(csv_path: Path) -> tuple[list[tuple[str, int]], int]:
    counts: Counter[str] = Counter()
    row_count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "system_type_tag" not in reader.fieldnames:
            raise ValueError(f"Missing system_type_tag column in {csv_path}")
        for row_number, row in enumerate(reader, start=2):
            raw_tag = row.get("system_type_tag") or ""
            try:
                category = system_category(raw_tag)
            except ValueError as exc:
                raise ValueError(f"{exc} at CSV row {row_number}") from exc
            counts[category] += 1
            row_count += 1

    missing = set(CATEGORY_ORDER) - set(counts)
    if missing:
        raise ValueError(f"System categories with no papers: {sorted(missing)}")
    if sum(counts.values()) != row_count:
        raise AssertionError("System-type counts do not sum to the CSV row count")

    rank = {category: index for index, category in enumerate(CATEGORY_ORDER)}
    rows = sorted(counts.items(), key=lambda item: (item[1], rank[item[0]]))
    return rows, row_count


def nice_x_limit(max_count: int) -> tuple[int, int]:
    if max_count <= 100:
        step = 10
    elif max_count <= 200:
        step = 20
    else:
        step = 50
    x_max = ((max_count // step) + 1) * step
    return x_max, step


def chart_geometry(rows: list[tuple[str, int]]) -> tuple[float, float, int, int]:
    row_step = (PLOT_BOTTOM - PLOT_TOP) / len(rows)
    bar_height = row_step * 0.78
    x_max, x_step = nice_x_limit(max(count for _, count in rows))
    return row_step, bar_height, x_max, x_step


def render_png(rows: list[tuple[str, int]], output: Path) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    axis_font = font(54)
    tick_font = font(43)
    value_font = font(43)
    row_step, bar_height, x_max, x_tick_step = chart_geometry(rows)
    plot_width = PLOT_RIGHT - PLOT_LEFT
    dash, gap = 10, 10

    for value in range(0, x_max + 1, x_tick_step):
        x = PLOT_LEFT + value / x_max * plot_width
        for y in range(PLOT_TOP, PLOT_BOTTOM, dash + gap):
            draw.line((x, y, x, min(y + dash, PLOT_BOTTOM)), fill=GRID, width=2)
        label = str(value)
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text(
            (x - (box[2] - box[0]) / 2, PLOT_BOTTOM + 24),
            label,
            font=tick_font,
            fill=INK,
        )

    for index in range(len(rows)):
        y = PLOT_TOP + (index + 0.5) * row_step
        for x in range(PLOT_LEFT, PLOT_RIGHT, dash + gap):
            draw.line((x, y, min(x + dash, PLOT_RIGHT), y), fill=GRID, width=2)

    for index, (category, count) in enumerate(rows):
        center_y = PLOT_TOP + (index + 0.5) * row_step
        x1 = PLOT_LEFT + count / x_max * plot_width
        y0, y1 = center_y - bar_height / 2, center_y + bar_height / 2
        draw.rectangle(
            (PLOT_LEFT, y0, x1, y1), fill=BAR, outline=WHITE, width=3
        )

        label_box = draw.textbbox((0, 0), category, font=tick_font)
        draw.text(
            (
                PLOT_LEFT - 28 - (label_box[2] - label_box[0]),
                center_y - (label_box[3] - label_box[1]) / 2,
            ),
            category,
            font=tick_font,
            fill=INK,
        )
        draw.text(
            (x1 + 12, center_y - 20), str(count), font=value_font, fill=INK
        )

    draw.rectangle(
        (PLOT_LEFT, PLOT_TOP, PLOT_RIGHT, PLOT_BOTTOM), outline=INK, width=4
    )
    plot_center_x = (PLOT_LEFT + PLOT_RIGHT) / 2
    centered_text(draw, (plot_center_x, HEIGHT - 88), "Number of Papers", axis_font)
    image.convert("RGB").save(output, dpi=(300, 300), optimize=True)


def render_pdf(rows: list[tuple[str, int]], output: Path) -> None:
    scale = 72.0 / 300.0
    pdf = canvas.Canvas(str(output), pagesize=(WIDTH * scale, HEIGHT * scale))
    pdf.scale(scale, scale)
    row_step, bar_height, x_max, x_tick_step = chart_geometry(rows)
    plot_width = PLOT_RIGHT - PLOT_LEFT

    def py(y: float) -> float:
        return HEIGHT - y

    pdf.setFillColor(HexColor(WHITE))
    pdf.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
    pdf.setStrokeColor(HexColor(GRID))
    pdf.setLineWidth(2)
    pdf.setDash(10, 10)
    pdf.setFont("Times-Roman", 43)
    pdf.setFillColor(HexColor(INK))
    for value in range(0, x_max + 1, x_tick_step):
        x = PLOT_LEFT + value / x_max * plot_width
        pdf.line(x, py(PLOT_TOP), x, py(PLOT_BOTTOM))
        pdf.drawCentredString(x, py(PLOT_BOTTOM + 58), str(value))
    for index in range(len(rows)):
        y = PLOT_TOP + (index + 0.5) * row_step
        pdf.line(PLOT_LEFT, py(y), PLOT_RIGHT, py(y))

    pdf.setDash()
    for index, (category, count) in enumerate(rows):
        center_y = PLOT_TOP + (index + 0.5) * row_step
        x1 = PLOT_LEFT + count / x_max * plot_width
        y0 = center_y - bar_height / 2
        pdf.setFillColor(HexColor(BAR))
        pdf.setStrokeColor(HexColor(WHITE))
        pdf.setLineWidth(3)
        pdf.rect(
            PLOT_LEFT,
            py(y0 + bar_height),
            x1 - PLOT_LEFT,
            bar_height,
            fill=1,
            stroke=1,
        )
        pdf.setFillColor(HexColor(INK))
        pdf.setFont("Times-Roman", 43)
        pdf.drawRightString(PLOT_LEFT - 28, py(center_y + 12), category)
        pdf.drawString(x1 + 12, py(center_y + 12), str(count))

    pdf.setStrokeColor(HexColor(INK))
    pdf.setLineWidth(4)
    pdf.rect(
        PLOT_LEFT,
        py(PLOT_BOTTOM),
        PLOT_RIGHT - PLOT_LEFT,
        PLOT_BOTTOM - PLOT_TOP,
        fill=0,
        stroke=1,
    )
    pdf.setFillColor(HexColor(INK))
    pdf.setFont("Times-Roman", 54)
    plot_center_x = (PLOT_LEFT + PLOT_RIGHT) / 2
    pdf.drawCentredString(plot_center_x, py(HEIGHT - 72), "Number of Papers")
    pdf.showPage()
    pdf.save()


def render_svg(rows: list[tuple[str, int]], output: Path) -> None:
    row_step, bar_height, x_max, x_tick_step = chart_geometry(rows)
    plot_width = PLOT_RIGHT - PLOT_LEFT
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        '<g font-family="Times New Roman, Times, serif" fill="#333333">',
    ]
    for value in range(0, x_max + 1, x_tick_step):
        x = PLOT_LEFT + value / x_max * plot_width
        parts.append(
            f'<line x1="{x:.2f}" y1="{PLOT_TOP}" x2="{x:.2f}" y2="{PLOT_BOTTOM}" stroke="{GRID}" stroke-width="2" stroke-dasharray="10 10"/>'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{PLOT_BOTTOM + 61}" text-anchor="middle" font-size="43">{value}</text>'
        )
    for index in range(len(rows)):
        y = PLOT_TOP + (index + 0.5) * row_step
        parts.append(
            f'<line x1="{PLOT_LEFT}" y1="{y:.2f}" x2="{PLOT_RIGHT}" y2="{y:.2f}" stroke="{GRID}" stroke-width="2" stroke-dasharray="10 10"/>'
        )
    for index, (category, count) in enumerate(rows):
        center_y = PLOT_TOP + (index + 0.5) * row_step
        x1 = PLOT_LEFT + count / x_max * plot_width
        y0 = center_y - bar_height / 2
        parts.append(
            f'<rect x="{PLOT_LEFT}" y="{y0:.2f}" width="{x1 - PLOT_LEFT:.2f}" height="{bar_height:.2f}" fill="{BAR}" stroke="#FFFFFF" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{PLOT_LEFT - 28}" y="{center_y + 15:.2f}" text-anchor="end" font-size="43">{html.escape(category)}</text>'
        )
        parts.append(
            f'<text x="{x1 + 12:.2f}" y="{center_y + 15:.2f}" font-size="43">{count}</text>'
        )
    parts.extend(
        [
            f'<rect x="{PLOT_LEFT}" y="{PLOT_TOP}" width="{PLOT_RIGHT - PLOT_LEFT}" height="{PLOT_BOTTOM - PLOT_TOP}" fill="none" stroke="{INK}" stroke-width="4"/>',
            f'<text x="{(PLOT_LEFT + PLOT_RIGHT) / 2}" y="{HEIGHT - 72}" text-anchor="middle" font-size="54">Number of Papers</text>',
            "</g>",
            "</svg>",
        ]
    )
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, row_count = load_system_counts(input_path)
    stem = "number_of_papers_for_different_system_types"

    render_png(rows, output_dir / f"{stem}.png")
    pdf_path = output_dir / "scenarios.pdf"
    render_pdf(rows, pdf_path)
    render_svg(rows, output_dir / f"{stem}.svg")

    print(f"Input: {input_path}")
    print(f"Papers: {row_count}")
    for category, count in rows:
        print(f"  {category}: {count}")
    print(f"PNG/SVG: {output_dir / stem}.[png|svg]")
    print(f"PDF: {pdf_path}")


if __name__ == "__main__":
    main()
