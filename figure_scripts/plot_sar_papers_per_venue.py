"""Plot the number of SAR papers per publication venue.

The plot follows the repository's venue tags. Per the review protocol used for
this figure, papers tagged ``ISSREW`` are merged into ``WoSAR``. The default
view shows the 15 venues with the most papers and distinguishes journals from
conferences by color.
"""

from __future__ import annotations

import argparse
import csv
import html
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

from plot_sar_papers_per_year import (
    GRID,
    INK,
    WHITE,
    centered_text,
    font,
    rotated_text,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "final_list_with_venue.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures"

WIDTH, HEIGHT = 3000, 1440
PLOT_LEFT, PLOT_RIGHT = 280, WIDTH - 85
PLOT_TOP, PLOT_BOTTOM = 85, HEIGHT - 390

JOURNAL_COLOR = "#D3D3D3"
CONFERENCE_COLOR = "#E89BA2"
JOURNAL_TYPES = {"article", "journal", "journal-article"}
CONFERENCE_TYPES = {"inproceedings", "proceedings-article"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot the number of SAR papers per publication venue."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="Number of highest-count venues to display (default: 15).",
    )
    return parser.parse_args()


def normalize_venue(value: str) -> str:
    venue = value.strip()
    if venue.casefold() in {"issrew", "wosar"}:
        return "WoSAR"
    return venue


def publication_category(publication_type: str) -> str:
    normalized = publication_type.strip().casefold()
    if normalized in JOURNAL_TYPES:
        return "Journal"
    if normalized in CONFERENCE_TYPES:
        return "Conference"
    raise ValueError(f"Unrecognized publication type: {publication_type!r}")


def load_venue_counts(
    csv_path: Path, top_n: int
) -> tuple[list[tuple[str, int, str]], int, int]:
    if top_n <= 0:
        raise ValueError("--top-n must be a positive integer")

    grouped: dict[str, list[str]] = defaultdict(list)
    row_count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"repo_venue_tags", "type"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Missing required columns {sorted(required)} in {csv_path}")

        for row_number, row in enumerate(reader, start=2):
            raw_venue = row.get("repo_venue_tags") or ""
            raw_type = row.get("type") or ""
            if not raw_venue.strip():
                raise ValueError(f"Blank repo_venue_tags at CSV row {row_number}")
            venue = normalize_venue(raw_venue)
            grouped[venue].append(publication_category(raw_type))
            row_count += 1

    venue_rows: list[tuple[str, int, str]] = []
    mixed_venues: set[str] = set()
    for venue, categories in grouped.items():
        category_counts = Counter(categories)
        if len(category_counts) > 1:
            mixed_venues.add(venue)
        category = sorted(
            category_counts,
            key=lambda value: (-category_counts[value], value),
        )[0]
        venue_rows.append((venue, len(categories), category))

    category_rank = {"Journal": 0, "Conference": 1}
    venue_rows.sort(
        key=lambda row: (-row[1], category_rank[row[2]], row[0].casefold())
    )
    displayed_rows = venue_rows[:top_n]
    displayed_mixed = [venue for venue, _, _ in displayed_rows if venue in mixed_venues]
    if displayed_mixed:
        raise ValueError(
            "Displayed venues contain mixed publication categories: "
            + ", ".join(displayed_mixed)
        )
    return displayed_rows, row_count, len(grouped)


def nice_y_limit(max_count: int) -> tuple[int, int]:
    if max_count <= 40:
        step = 5
    elif max_count <= 100:
        step = 10
    else:
        step = 20
    y_max = ((max_count // step) + 1) * step
    return y_max, step


def chart_geometry(
    venue_rows: list[tuple[str, int, str]],
) -> tuple[float, float, int, int]:
    x_step = (PLOT_RIGHT - PLOT_LEFT) / len(venue_rows)
    bar_width = x_step * 0.78
    y_max, y_step = nice_y_limit(max(count for _, count, _ in venue_rows))
    return x_step, bar_width, y_max, y_step


def bar_color(category: str) -> str:
    return JOURNAL_COLOR if category == "Journal" else CONFERENCE_COLOR


def draw_legend_png(draw: ImageDraw.ImageDraw) -> None:
    legend_font = font(42)
    entries = [("Journal", JOURNAL_COLOR), ("Conference", CONFERENCE_COLOR)]
    box_size = 38
    gap = 32
    widths = []
    for label, _ in entries:
        box = draw.textbbox((0, 0), label, font=legend_font)
        widths.append(box_size + 14 + box[2] - box[0])
    total_width = sum(widths) + gap
    x = PLOT_RIGHT - total_width - 22
    y = PLOT_TOP + 26
    for (label, color), entry_width in zip(entries, widths):
        draw.rectangle((x, y, x + box_size, y + box_size), fill=color)
        draw.text((x + box_size + 14, y - 2), label, font=legend_font, fill=INK)
        x += entry_width + gap


def render_png(venue_rows: list[tuple[str, int, str]], output: Path) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    axis_font = font(52)
    tick_font = font(40)
    x_step, bar_width, y_max, y_step = chart_geometry(venue_rows)
    plot_height = PLOT_BOTTOM - PLOT_TOP

    dash, gap = 10, 10
    for value in range(0, y_max + 1, y_step):
        y = PLOT_BOTTOM - value / y_max * plot_height
        for x in range(PLOT_LEFT, PLOT_RIGHT, dash + gap):
            draw.line((x, y, min(x + dash, PLOT_RIGHT), y), fill=GRID, width=2)
        label = str(value)
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text(
            (PLOT_LEFT - 28 - (box[2] - box[0]), y - (box[3] - box[1]) / 2),
            label,
            font=tick_font,
            fill=INK,
        )

    for index in range(len(venue_rows)):
        x = PLOT_LEFT + (index + 0.5) * x_step
        for y in range(PLOT_TOP, PLOT_BOTTOM, dash + gap):
            draw.line((x, y, x, min(y + dash, PLOT_BOTTOM)), fill=GRID, width=2)

    for index, (_, count, category) in enumerate(venue_rows):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x0, x1 = center_x - bar_width / 2, center_x + bar_width / 2
        y0 = PLOT_BOTTOM - count / y_max * plot_height
        draw.rectangle(
            (x0, y0, x1, PLOT_BOTTOM),
            fill=bar_color(category),
            outline=WHITE,
            width=3,
        )

    draw.rectangle(
        (PLOT_LEFT, PLOT_TOP, PLOT_RIGHT, PLOT_BOTTOM), outline=INK, width=4
    )
    draw_legend_png(draw)

    for index, (venue, _, _) in enumerate(venue_rows):
        x = PLOT_LEFT + (index + 0.5) * x_step
        rotated_text(image, (x + 5, PLOT_BOTTOM + 125), venue, tick_font, 45)

    centered_text(draw, (WIDTH / 2, HEIGHT - 105), "Publication Venue", axis_font)
    rotated_text(
        image,
        (76, (PLOT_TOP + PLOT_BOTTOM) / 2),
        "Number of SAR Papers",
        axis_font,
        90,
    )
    image.convert("RGB").save(output, dpi=(300, 300), optimize=True)


def render_pdf(venue_rows: list[tuple[str, int, str]], output: Path) -> None:
    scale = 72.0 / 300.0
    pdf = canvas.Canvas(str(output), pagesize=(WIDTH * scale, HEIGHT * scale))
    pdf.scale(scale, scale)
    x_step, bar_width, y_max, y_step = chart_geometry(venue_rows)
    plot_height = PLOT_BOTTOM - PLOT_TOP

    def py(y: float) -> float:
        return HEIGHT - y

    pdf.setFillColor(HexColor(WHITE))
    pdf.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
    pdf.setStrokeColor(HexColor(GRID))
    pdf.setFillColor(HexColor(INK))
    pdf.setLineWidth(2)
    pdf.setDash(10, 10)
    pdf.setFont("Times-Roman", 40)
    for value in range(0, y_max + 1, y_step):
        y = PLOT_BOTTOM - value / y_max * plot_height
        pdf.line(PLOT_LEFT, py(y), PLOT_RIGHT, py(y))
        pdf.drawRightString(PLOT_LEFT - 28, py(y + 11), str(value))
    for index in range(len(venue_rows)):
        x = PLOT_LEFT + (index + 0.5) * x_step
        pdf.line(x, py(PLOT_TOP), x, py(PLOT_BOTTOM))

    pdf.setDash()
    for index, (_, count, category) in enumerate(venue_rows):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x = center_x - bar_width / 2
        y = PLOT_BOTTOM - count / y_max * plot_height
        pdf.setFillColor(HexColor(bar_color(category)))
        pdf.setStrokeColor(HexColor(WHITE))
        pdf.setLineWidth(3)
        pdf.rect(x, py(PLOT_BOTTOM), bar_width, PLOT_BOTTOM - y, fill=1, stroke=1)

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

    legend_font_size = 42
    pdf.setFont("Times-Roman", legend_font_size)
    entries = [("Journal", JOURNAL_COLOR), ("Conference", CONFERENCE_COLOR)]
    box_size, gap = 38, 32
    widths = [
        box_size + 14 + pdf.stringWidth(label, "Times-Roman", legend_font_size)
        for label, _ in entries
    ]
    x = PLOT_RIGHT - sum(widths) - gap - 22
    y = py(PLOT_TOP + 26 + box_size)
    for (label, color), entry_width in zip(entries, widths):
        pdf.setFillColor(HexColor(color))
        pdf.rect(x, y, box_size, box_size, fill=1, stroke=0)
        pdf.setFillColor(HexColor(INK))
        pdf.drawString(x + box_size + 14, y + 4, label)
        x += entry_width + gap

    pdf.setFillColor(HexColor(INK))
    pdf.setFont("Times-Roman", 40)
    for index, (venue, _, _) in enumerate(venue_rows):
        x = PLOT_LEFT + (index + 0.5) * x_step
        pdf.saveState()
        pdf.translate(x + 5, py(PLOT_BOTTOM + 105))
        pdf.rotate(45)
        pdf.drawRightString(0, 0, venue)
        pdf.restoreState()

    pdf.setFont("Times-Roman", 52)
    pdf.drawCentredString(WIDTH / 2, py(HEIGHT - 88), "Publication Venue")
    pdf.saveState()
    pdf.translate(76, py((PLOT_TOP + PLOT_BOTTOM) / 2))
    pdf.rotate(90)
    pdf.drawCentredString(0, 0, "Number of SAR Papers")
    pdf.restoreState()
    pdf.showPage()
    pdf.save()


def render_svg(venue_rows: list[tuple[str, int, str]], output: Path) -> None:
    x_step, bar_width, y_max, y_step = chart_geometry(venue_rows)
    plot_height = PLOT_BOTTOM - PLOT_TOP
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        '<g font-family="Times New Roman, Times, serif" fill="#333333">',
    ]
    for value in range(0, y_max + 1, y_step):
        y = PLOT_BOTTOM - value / y_max * plot_height
        parts.append(
            f'<line x1="{PLOT_LEFT}" y1="{y:.2f}" x2="{PLOT_RIGHT}" y2="{y:.2f}" stroke="{GRID}" stroke-width="2" stroke-dasharray="10 10"/>'
        )
        parts.append(
            f'<text x="{PLOT_LEFT - 28}" y="{y + 14:.2f}" text-anchor="end" font-size="40">{value}</text>'
        )
    for index in range(len(venue_rows)):
        x = PLOT_LEFT + (index + 0.5) * x_step
        parts.append(
            f'<line x1="{x:.2f}" y1="{PLOT_TOP}" x2="{x:.2f}" y2="{PLOT_BOTTOM}" stroke="{GRID}" stroke-width="2" stroke-dasharray="10 10"/>'
        )
    for index, (_, count, category) in enumerate(venue_rows):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x = center_x - bar_width / 2
        y = PLOT_BOTTOM - count / y_max * plot_height
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{PLOT_BOTTOM - y:.2f}" fill="{bar_color(category)}" stroke="#FFFFFF" stroke-width="3"/>'
        )
    parts.append(
        f'<rect x="{PLOT_LEFT}" y="{PLOT_TOP}" width="{PLOT_RIGHT - PLOT_LEFT}" height="{PLOT_BOTTOM - PLOT_TOP}" fill="none" stroke="{INK}" stroke-width="4"/>'
    )

    legend_x, legend_y = PLOT_RIGHT - 550, PLOT_TOP + 26
    for label, color in [("Journal", JOURNAL_COLOR), ("Conference", CONFERENCE_COLOR)]:
        parts.append(
            f'<rect x="{legend_x}" y="{legend_y}" width="38" height="38" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{legend_x + 52}" y="{legend_y + 34}" font-size="42">{label}</text>'
        )
        legend_x += 255

    for index, (venue, _, _) in enumerate(venue_rows):
        x = PLOT_LEFT + (index + 0.5) * x_step
        parts.append(
            f'<text x="{x + 5:.2f}" y="{PLOT_BOTTOM + 105}" text-anchor="end" font-size="40" transform="rotate(-45 {x + 5:.2f} {PLOT_BOTTOM + 105})">{html.escape(venue)}</text>'
        )
    parts.extend(
        [
            f'<text x="{WIDTH / 2}" y="{HEIGHT - 88}" text-anchor="middle" font-size="52">Publication Venue</text>',
            f'<text x="76" y="{(PLOT_TOP + PLOT_BOTTOM) / 2}" text-anchor="middle" font-size="52" transform="rotate(-90 76 {(PLOT_TOP + PLOT_BOTTOM) / 2})">Number of SAR Papers</text>',
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
    venue_rows, row_count, venue_count = load_venue_counts(input_path, args.top_n)

    stem = "number_of_sar_papers_per_venue"
    render_png(venue_rows, output_dir / f"{stem}.png")
    pdf_path = output_dir / "publications_by_venue.pdf"
    render_pdf(venue_rows, pdf_path)
    render_svg(venue_rows, output_dir / f"{stem}.svg")

    print(f"Input: {input_path}")
    print(f"Rows counted: {row_count}")
    print(f"Normalized venues: {venue_count}")
    print(f"Displayed venues: {len(venue_rows)}")
    for venue, count, category in venue_rows:
        print(f"  {venue}: {count} ({category})")
    print(f"PNG/SVG: {output_dir / stem}.[png|svg]")
    print(f"PDF: {pdf_path}")


if __name__ == "__main__":
    main()
