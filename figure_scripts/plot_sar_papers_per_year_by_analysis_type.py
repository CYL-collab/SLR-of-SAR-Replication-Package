"""Plot annual SAR paper counts by analysis type.

The figure counts papers whose ``repo_analysis_tags`` contain one of the three
analysis approaches: ``model-based``, ``measurement-based`` (including its
parenthesized subtypes), or ``hybrid``.  Other research-theme tags are outside
the scope of this figure.  A paper contributes at most once to one analysis
type in its publication year.
"""

from __future__ import annotations

import argparse
import csv
import html
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

from plot_sar_papers_per_year import (
    GRID,
    INK,
    MUTED,
    WHITE,
    centered_text,
    font,
    rotated_text,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "final_list_with_venue.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures"

WIDTH, HEIGHT = 3000, 1500
PLOT_LEFT, PLOT_RIGHT = 300, WIDTH - 90
PLOT_TOP, PLOT_BOTTOM = 80, HEIGHT - 350

ANALYSIS_TYPES = ["Model-based", "Measurement-based", "Hybrid"]
COLORS = {
    "Model-based": "#CF3F55",
    "Measurement-based": "#E9939D",
    "Hybrid": "#F3C195",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot annual SAR paper counts by analysis type."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def analysis_types_from_tags(value: str) -> set[str]:
    """Extract the three analysis approaches from one semicolon tag field."""
    methods: set[str] = set()
    for raw_token in value.split(";"):
        token = raw_token.strip().casefold()
        if token == "model-based":
            methods.add("Model-based")
        elif "measurement-based" in token:
            methods.add("Measurement-based")
        elif token == "hybrid":
            methods.add("Hybrid")
    return methods


def load_annual_counts(
    csv_path: Path,
) -> tuple[list[int], dict[str, list[int]], int, int]:
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    total_rows = 0
    counted_papers = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"year", "repo_analysis_tags"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Missing required columns {sorted(required)} in {csv_path}")

        all_years: list[int] = []
        for row_number, row in enumerate(reader, start=2):
            year_text = (row.get("year") or "").strip()
            tag_text = (row.get("repo_analysis_tags") or "").strip()
            if not year_text:
                raise ValueError(f"Blank year at CSV row {row_number}")
            if not tag_text:
                raise ValueError(f"Blank repo_analysis_tags at CSV row {row_number}")
            try:
                year = int(year_text)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid year {year_text!r} at CSV row {row_number}"
                ) from exc

            methods = analysis_types_from_tags(tag_text)
            if len(methods) > 1:
                raise ValueError(
                    f"Multiple analysis types {sorted(methods)} at CSV row {row_number}"
                )
            if methods:
                counts[year][next(iter(methods))] += 1
                counted_papers += 1
            all_years.append(year)
            total_rows += 1

    if not all_years:
        raise ValueError(f"No publication rows found in {csv_path}")
    years = list(range(min(all_years), max(all_years) + 1))
    series = {
        method: [counts[year][method] for year in years]
        for method in ANALYSIS_TYPES
    }
    if sum(sum(values) for values in series.values()) != counted_papers:
        raise AssertionError("Annual analysis-type counts do not match counted papers")
    return years, series, total_rows, counted_papers


def nice_y_limit(max_count: int) -> tuple[int, int]:
    if max_count <= 20:
        step = 5
    elif max_count <= 50:
        step = 10
    else:
        step = 20
    y_max = ((max_count + step - 1) // step) * step
    return max(y_max, step), step


def chart_geometry(
    years: list[int], series: dict[str, list[int]]
) -> tuple[float, float, int, int]:
    x_step = (PLOT_RIGHT - PLOT_LEFT) / len(years)
    bar_width = x_step * 0.82
    totals = [
        sum(series[method][index] for method in ANALYSIS_TYPES)
        for index in range(len(years))
    ]
    y_max, y_step = nice_y_limit(max(totals))
    return x_step, bar_width, y_max, y_step


def tick_years_for(years: list[int]) -> list[int]:
    tick_years = [year for year in years if year % 5 == 0]
    if years[0] not in tick_years:
        tick_years.insert(0, years[0])
    if years[-1] not in tick_years:
        tick_years.append(years[-1])
    return tick_years


def draw_legend_png(draw: ImageDraw.ImageDraw) -> None:
    legend_font = font(42)
    box_size, row_gap = 36, 18
    x, y = PLOT_LEFT + 48, PLOT_TOP + 35
    for method in ANALYSIS_TYPES:
        draw.rectangle((x, y, x + box_size, y + box_size), fill=COLORS[method])
        draw.text(
            (x + box_size + 16, y - 2), method, font=legend_font, fill=INK
        )
        y += box_size + row_gap


def render_png(
    years: list[int], series: dict[str, list[int]], output: Path
) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    axis_font = font(54)
    tick_font = font(40)
    note_font = font(34)
    x_step, bar_width, y_max, y_step = chart_geometry(years, series)
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

    tick_years = tick_years_for(years)
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        for y in range(PLOT_TOP, PLOT_BOTTOM, dash + gap):
            draw.line((x, y, x, min(y + dash, PLOT_BOTTOM)), fill=GRID, width=2)

    for index in range(len(years)):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x0, x1 = center_x - bar_width / 2, center_x + bar_width / 2
        cumulative = 0
        for method in ANALYSIS_TYPES:
            count = series[method][index]
            if count == 0:
                continue
            y_bottom = PLOT_BOTTOM - cumulative / y_max * plot_height
            cumulative += count
            y_top = PLOT_BOTTOM - cumulative / y_max * plot_height
            draw.rectangle(
                (x0, y_top, x1, y_bottom),
                fill=COLORS[method],
                outline=WHITE,
                width=2,
            )

    draw.rectangle(
        (PLOT_LEFT, PLOT_TOP, PLOT_RIGHT, PLOT_BOTTOM), outline=INK, width=4
    )
    draw_legend_png(draw)

    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        label = f"{year}*" if year == date.today().year else str(year)
        rotated_text(image, (x + 8, PLOT_BOTTOM + 92), label, tick_font, 45)

    centered_text(draw, (WIDTH / 2, HEIGHT - 125), "Publication Year", axis_font)
    rotated_text(
        image,
        (78, (PLOT_TOP + PLOT_BOTTOM) / 2),
        "Number of SAR Papers",
        axis_font,
        90,
    )
    if date.today().year in years:
        note = f"* {date.today().year} is partial; data snapshot: {date.today():%B %d, %Y}."
        box = draw.textbbox((0, 0), note, font=note_font)
        draw.text(
            (PLOT_RIGHT - (box[2] - box[0]), HEIGHT - 55),
            note,
            font=note_font,
            fill=MUTED,
        )
    image.convert("RGB").save(output, dpi=(300, 300), optimize=True)


def render_pdf(
    years: list[int], series: dict[str, list[int]], output: Path
) -> None:
    scale = 72.0 / 300.0
    pdf = canvas.Canvas(str(output), pagesize=(WIDTH * scale, HEIGHT * scale))
    pdf.scale(scale, scale)
    x_step, bar_width, y_max, y_step = chart_geometry(years, series)
    plot_height = PLOT_BOTTOM - PLOT_TOP

    def py(y: float) -> float:
        return HEIGHT - y

    pdf.setFillColor(HexColor(WHITE))
    pdf.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
    pdf.setStrokeColor(HexColor(GRID))
    pdf.setLineWidth(2)
    pdf.setDash(10, 10)
    pdf.setFillColor(HexColor(INK))
    pdf.setFont("Times-Roman", 40)
    for value in range(0, y_max + 1, y_step):
        y = PLOT_BOTTOM - value / y_max * plot_height
        pdf.line(PLOT_LEFT, py(y), PLOT_RIGHT, py(y))
        pdf.drawRightString(PLOT_LEFT - 28, py(y + 11), str(value))

    tick_years = tick_years_for(years)
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        pdf.line(x, py(PLOT_TOP), x, py(PLOT_BOTTOM))

    pdf.setDash()
    for index in range(len(years)):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x0 = center_x - bar_width / 2
        cumulative = 0
        for method in ANALYSIS_TYPES:
            count = series[method][index]
            if count == 0:
                continue
            y_bottom = PLOT_BOTTOM - cumulative / y_max * plot_height
            cumulative += count
            y_top = PLOT_BOTTOM - cumulative / y_max * plot_height
            pdf.setFillColor(HexColor(COLORS[method]))
            pdf.setStrokeColor(HexColor(WHITE))
            pdf.setLineWidth(2)
            pdf.rect(
                x0,
                py(y_bottom),
                bar_width,
                y_bottom - y_top,
                fill=1,
                stroke=1,
            )

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

    legend_x, legend_y = PLOT_LEFT + 48, PLOT_TOP + 35
    box_size, row_gap = 36, 18
    pdf.setFont("Times-Roman", 42)
    for method in ANALYSIS_TYPES:
        pdf.setFillColor(HexColor(COLORS[method]))
        pdf.rect(legend_x, py(legend_y + box_size), box_size, box_size, fill=1, stroke=0)
        pdf.setFillColor(HexColor(INK))
        pdf.drawString(legend_x + box_size + 16, py(legend_y + 29), method)
        legend_y += box_size + row_gap

    pdf.setFillColor(HexColor(INK))
    pdf.setFont("Times-Roman", 40)
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        label = f"{year}*" if year == date.today().year else str(year)
        pdf.saveState()
        pdf.translate(x + 8, py(PLOT_BOTTOM + 72))
        pdf.rotate(45)
        pdf.drawRightString(0, 0, label)
        pdf.restoreState()

    pdf.setFont("Times-Roman", 54)
    pdf.drawCentredString(WIDTH / 2, py(HEIGHT - 108), "Publication Year")
    pdf.saveState()
    pdf.translate(78, py((PLOT_TOP + PLOT_BOTTOM) / 2))
    pdf.rotate(90)
    pdf.drawCentredString(0, 0, "Number of SAR Papers")
    pdf.restoreState()

    if date.today().year in years:
        note = f"* {date.today().year} is partial; data snapshot: {date.today():%B %d, %Y}."
        pdf.setFillColor(HexColor(MUTED))
        pdf.setFont("Times-Roman", 34)
        pdf.drawRightString(PLOT_RIGHT, py(HEIGHT - 42), note)
    pdf.showPage()
    pdf.save()


def render_svg(
    years: list[int], series: dict[str, list[int]], output: Path
) -> None:
    x_step, bar_width, y_max, y_step = chart_geometry(years, series)
    plot_height = PLOT_BOTTOM - PLOT_TOP
    tick_years = tick_years_for(years)
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
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        parts.append(
            f'<line x1="{x:.2f}" y1="{PLOT_TOP}" x2="{x:.2f}" y2="{PLOT_BOTTOM}" stroke="{GRID}" stroke-width="2" stroke-dasharray="10 10"/>'
        )

    for index in range(len(years)):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x0 = center_x - bar_width / 2
        cumulative = 0
        for method in ANALYSIS_TYPES:
            count = series[method][index]
            if count == 0:
                continue
            y_bottom = PLOT_BOTTOM - cumulative / y_max * plot_height
            cumulative += count
            y_top = PLOT_BOTTOM - cumulative / y_max * plot_height
            parts.append(
                f'<rect x="{x0:.2f}" y="{y_top:.2f}" width="{bar_width:.2f}" height="{y_bottom - y_top:.2f}" fill="{COLORS[method]}" stroke="#FFFFFF" stroke-width="2"/>'
            )

    parts.append(
        f'<rect x="{PLOT_LEFT}" y="{PLOT_TOP}" width="{PLOT_RIGHT - PLOT_LEFT}" height="{PLOT_BOTTOM - PLOT_TOP}" fill="none" stroke="{INK}" stroke-width="4"/>'
    )
    legend_x, legend_y = PLOT_LEFT + 48, PLOT_TOP + 35
    for method in ANALYSIS_TYPES:
        parts.append(
            f'<rect x="{legend_x}" y="{legend_y}" width="36" height="36" fill="{COLORS[method]}"/>'
        )
        parts.append(
            f'<text x="{legend_x + 52}" y="{legend_y + 34}" font-size="42">{html.escape(method)}</text>'
        )
        legend_y += 54

    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        label = f"{year}*" if year == date.today().year else str(year)
        parts.append(
            f'<text x="{x + 8:.2f}" y="{PLOT_BOTTOM + 72}" text-anchor="end" font-size="40" transform="rotate(-45 {x + 8:.2f} {PLOT_BOTTOM + 72})">{label}</text>'
        )
    parts.extend(
        [
            f'<text x="{WIDTH / 2}" y="{HEIGHT - 108}" text-anchor="middle" font-size="54">Publication Year</text>',
            f'<text x="78" y="{(PLOT_TOP + PLOT_BOTTOM) / 2}" text-anchor="middle" font-size="54" transform="rotate(-90 78 {(PLOT_TOP + PLOT_BOTTOM) / 2})">Number of SAR Papers</text>',
        ]
    )
    if date.today().year in years:
        note = f"* {date.today().year} is partial; data snapshot: {date.today():%B %d, %Y}."
        parts.append(
            f'<text x="{PLOT_RIGHT}" y="{HEIGHT - 42}" text-anchor="end" font-size="34" fill="{MUTED}">{html.escape(note)}</text>'
        )
    parts.extend(["</g>", "</svg>"])
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    years, series, total_rows, counted_papers = load_annual_counts(input_path)
    stem = "number_of_sar_papers_per_year_by_analysis_type"

    render_png(years, series, output_dir / f"{stem}.png")
    pdf_path = output_dir / "publications_by_analysis.pdf"
    render_pdf(years, series, pdf_path)
    render_svg(years, series, output_dir / f"{stem}.svg")

    print(f"Input: {input_path}")
    print(f"CSV papers: {total_rows}")
    print(f"Papers with one of the three analysis types: {counted_papers}")
    for method in ANALYSIS_TYPES:
        print(f"  {method}: {sum(series[method])}")
    print(f"Years: {years[0]}-{years[-1]}")
    print(f"PNG/SVG: {output_dir / stem}.[png|svg]")
    print(f"PDF: {pdf_path}")


if __name__ == "__main__":
    main()
