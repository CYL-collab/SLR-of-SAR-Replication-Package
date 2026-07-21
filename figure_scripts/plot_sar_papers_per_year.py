"""Plot the annual number of software aging and rejuvenation (SAR) papers.

The script reads ``final_list_with_venue.csv`` from the repository root and
exports publication-ready PNG, PDF, and SVG versions. It uses Pillow rather
than Matplotlib so it runs in the repository's bundled offline Python runtime.
"""

from __future__ import annotations

import argparse
import csv
import html
from collections import Counter
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "final_list_with_venue.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures"

WIDTH, HEIGHT = 3000, 1440
LEFT, RIGHT, TOP, BOTTOM = 285, 85, 85, 345
PLOT_LEFT, PLOT_RIGHT = LEFT, WIDTH - RIGHT
PLOT_TOP, PLOT_BOTTOM = TOP, HEIGHT - BOTTOM

INK = "#333333"
MUTED = "#666666"
GRID = "#D8D8D8"
BAR = "#E89BA2"
LINE = "#8F4A55"
WHITE = "#FFFFFF"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot the annual number of SAR papers in the final list."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def load_year_counts(csv_path: Path) -> tuple[list[int], list[int], int]:
    counts: Counter[int] = Counter()
    row_count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "year" not in reader.fieldnames:
            raise ValueError(f"Missing required 'year' column in {csv_path}")
        for row_number, row in enumerate(reader, start=2):
            value = (row.get("year") or "").strip()
            if not value:
                raise ValueError(f"Blank year at CSV row {row_number}")
            try:
                year = int(value)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid year {value!r} at CSV row {row_number}"
                ) from exc
            counts[year] += 1
            row_count += 1

    if not counts:
        raise ValueError(f"No publication rows found in {csv_path}")
    years = list(range(min(counts), max(counts) + 1))
    annual_counts = [counts[year] for year in years]
    if sum(annual_counts) != row_count:
        raise AssertionError("Annual paper counts do not sum to the CSV row count")
    return years, annual_counts, row_count


def font_path(bold: bool = False) -> Path:
    windows_fonts = Path("C:/Windows/Fonts")
    candidates = (
        ["timesbd.ttf", "DejaVuSerif-Bold.ttf"]
        if bold
        else ["times.ttf", "DejaVuSerif.ttf"]
    )
    for name in candidates:
        candidate = windows_fonts / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No Times-compatible serif font found")


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path(bold)), size=size)


def centered_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str = INK,
) -> None:
    box = draw.textbbox((0, 0), text, font=text_font)
    draw.text(
        (xy[0] - (box[2] - box[0]) / 2, xy[1] - (box[3] - box[1]) / 2),
        text,
        font=text_font,
        fill=fill,
    )


def rotated_text(
    image: Image.Image,
    center: tuple[float, float],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    angle: float,
    fill: str = INK,
) -> None:
    box = text_font.getbbox(text)
    pad = 12
    text_image = Image.new(
        "RGBA", (box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2), (0, 0, 0, 0)
    )
    text_draw = ImageDraw.Draw(text_image)
    text_draw.text((pad - box[0], pad - box[1]), text, font=text_font, fill=fill)
    rotated = text_image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    image.alpha_composite(
        rotated,
        (round(center[0] - rotated.width / 2), round(center[1] - rotated.height / 2)),
    )


def nice_y_limit(max_count: int) -> tuple[int, int]:
    step = 5 if max_count <= 40 else 10
    y_max = ((max_count + step - 1) // step) * step
    return max(y_max, step), step


def chart_geometry(
    years: list[int], annual_counts: list[int]
) -> tuple[float, float, int, int]:
    x_step = (PLOT_RIGHT - PLOT_LEFT) / len(years)
    bar_width = x_step * 0.82
    y_max, y_step = nice_y_limit(max(annual_counts))
    return x_step, bar_width, y_max, y_step


def render_png(years: list[int], annual_counts: list[int], output: Path) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    axis_font = font(52)
    tick_font = font(40)
    note_font = font(34)

    x_step, bar_width, y_max, y_step = chart_geometry(years, annual_counts)
    plot_height = PLOT_BOTTOM - PLOT_TOP

    # Quiet dashed grid, matching the supplied reference style.
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

    tick_years = [year for year in years if year % 5 == 0]
    if years[-1] not in tick_years:
        tick_years.append(years[-1])
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        for y in range(PLOT_TOP, PLOT_BOTTOM, dash + gap):
            draw.line((x, y, x, min(y + dash, PLOT_BOTTOM)), fill=GRID, width=2)

    for index, count in enumerate(annual_counts):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x0, x1 = center_x - bar_width / 2, center_x + bar_width / 2
        y0 = PLOT_BOTTOM - count / y_max * plot_height
        draw.rectangle((x0, y0, x1, PLOT_BOTTOM), fill=BAR, outline=WHITE, width=3)

    line_points = []
    for index, count in enumerate(annual_counts):
        x = PLOT_LEFT + (index + 0.5) * x_step
        y = PLOT_BOTTOM - count / y_max * plot_height
        line_points.append((x, y))
    draw.line(line_points, fill=LINE, width=7, joint="curve")
    for x, y in line_points:
        radius = 7
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=WHITE,
            outline=LINE,
            width=4,
        )

    # Full dark frame, as in the reference figure.
    draw.rectangle((PLOT_LEFT, PLOT_TOP, PLOT_RIGHT, PLOT_BOTTOM), outline=INK, width=4)

    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        label = f"{year}*" if year == date.today().year else str(year)
        rotated_text(image, (x + 8, PLOT_BOTTOM + 92), label, tick_font, 45)

    centered_text(draw, (WIDTH / 2, HEIGHT - 118), "Publication Year", axis_font)
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

    rgb_image = image.convert("RGB")
    rgb_image.save(output, dpi=(300, 300), optimize=True)


def render_pdf(years: list[int], annual_counts: list[int], output: Path) -> None:
    """Render the same chart as a vector PDF using ReportLab."""
    scale = 72.0 / 300.0
    pdf = canvas.Canvas(str(output), pagesize=(WIDTH * scale, HEIGHT * scale))
    pdf.scale(scale, scale)
    x_step, bar_width, y_max, y_step = chart_geometry(years, annual_counts)
    plot_height = PLOT_BOTTOM - PLOT_TOP

    # ReportLab's origin is at the lower left; convert top-origin y coordinates.
    def py(y: float) -> float:
        return HEIGHT - y

    pdf.setFillColor(HexColor(WHITE))
    pdf.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
    pdf.setLineWidth(2)
    pdf.setDash(10, 10)
    pdf.setStrokeColor(HexColor(GRID))
    pdf.setFillColor(HexColor(INK))
    pdf.setFont("Times-Roman", 40)
    for value in range(0, y_max + 1, y_step):
        y = PLOT_BOTTOM - value / y_max * plot_height
        pdf.line(PLOT_LEFT, py(y), PLOT_RIGHT, py(y))
        pdf.drawRightString(PLOT_LEFT - 28, py(y + 11), str(value))

    tick_years = [year for year in years if year % 5 == 0]
    if years[-1] not in tick_years:
        tick_years.append(years[-1])
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        pdf.line(x, py(PLOT_TOP), x, py(PLOT_BOTTOM))

    pdf.setDash()
    for index, count in enumerate(annual_counts):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x = center_x - bar_width / 2
        y = PLOT_BOTTOM - count / y_max * plot_height
        pdf.setFillColor(HexColor(BAR))
        pdf.setStrokeColor(HexColor(WHITE))
        pdf.setLineWidth(3)
        pdf.rect(x, py(PLOT_BOTTOM), bar_width, PLOT_BOTTOM - y, fill=1, stroke=1)

    line_points = []
    for index, count in enumerate(annual_counts):
        x = PLOT_LEFT + (index + 0.5) * x_step
        y = PLOT_BOTTOM - count / y_max * plot_height
        line_points.append((x, py(y)))
    pdf.setStrokeColor(HexColor(LINE))
    pdf.setLineWidth(7)
    path = pdf.beginPath()
    path.moveTo(*line_points[0])
    for point in line_points[1:]:
        path.lineTo(*point)
    pdf.drawPath(path, stroke=1, fill=0)
    for x, y in line_points:
        pdf.setFillColor(HexColor(WHITE))
        pdf.setStrokeColor(HexColor(LINE))
        pdf.setLineWidth(4)
        pdf.circle(x, y, 7, stroke=1, fill=1)

    pdf.setFillColor(HexColor(INK))
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

    pdf.setFont("Times-Roman", 40)
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        label = f"{year}*" if year == date.today().year else str(year)
        pdf.saveState()
        pdf.translate(x + 8, py(PLOT_BOTTOM + 75))
        pdf.rotate(45)
        pdf.drawRightString(0, 0, label)
        pdf.restoreState()

    pdf.setFont("Times-Roman", 52)
    pdf.drawCentredString(WIDTH / 2, py(HEIGHT - 100), "Publication Year")
    pdf.saveState()
    pdf.translate(78, py((PLOT_TOP + PLOT_BOTTOM) / 2))
    pdf.rotate(90)
    pdf.drawCentredString(0, 0, "Number of SAR Papers")
    pdf.restoreState()

    if date.today().year in years:
        note = f"* {date.today().year} is partial; data snapshot: {date.today():%B %d, %Y}."
        pdf.setFillColor(HexColor(MUTED))
        pdf.setFont("Times-Roman", 34)
        pdf.drawRightString(PLOT_RIGHT, py(HEIGHT - 40), note)

    pdf.showPage()
    pdf.save()


def render_svg(years: list[int], annual_counts: list[int], output: Path) -> None:
    x_step, bar_width, y_max, y_step = chart_geometry(years, annual_counts)
    plot_height = PLOT_BOTTOM - PLOT_TOP
    tick_years = [year for year in years if year % 5 == 0]
    if years[-1] not in tick_years:
        tick_years.append(years[-1])

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
    for index, count in enumerate(annual_counts):
        center_x = PLOT_LEFT + (index + 0.5) * x_step
        x = center_x - bar_width / 2
        y = PLOT_BOTTOM - count / y_max * plot_height
        height = PLOT_BOTTOM - y
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{height:.2f}" fill="{BAR}" stroke="#FFFFFF" stroke-width="3"/>'
        )
    line_points = []
    for index, count in enumerate(annual_counts):
        x = PLOT_LEFT + (index + 0.5) * x_step
        y = PLOT_BOTTOM - count / y_max * plot_height
        line_points.append((x, y))
    point_string = " ".join(f"{x:.2f},{y:.2f}" for x, y in line_points)
    parts.append(
        f'<polyline points="{point_string}" fill="none" stroke="{LINE}" stroke-width="7" stroke-linejoin="round" stroke-linecap="round"/>'
    )
    for x, y in line_points:
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7" fill="#FFFFFF" stroke="{LINE}" stroke-width="4"/>'
        )
    parts.append(
        f'<rect x="{PLOT_LEFT}" y="{PLOT_TOP}" width="{PLOT_RIGHT - PLOT_LEFT}" height="{PLOT_BOTTOM - PLOT_TOP}" fill="none" stroke="{INK}" stroke-width="4"/>'
    )
    for year in tick_years:
        index = year - years[0]
        x = PLOT_LEFT + (index + 0.5) * x_step
        label = f"{year}*" if year == date.today().year else str(year)
        parts.append(
            f'<text x="{x + 8:.2f}" y="{PLOT_BOTTOM + 75}" text-anchor="end" font-size="40" transform="rotate(-45 {x + 8:.2f} {PLOT_BOTTOM + 75})">{html.escape(label)}</text>'
        )
    parts.extend(
        [
            f'<text x="{WIDTH / 2}" y="{HEIGHT - 100}" text-anchor="middle" font-size="52">Publication Year</text>',
            f'<text x="78" y="{(PLOT_TOP + PLOT_BOTTOM) / 2}" text-anchor="middle" font-size="52" transform="rotate(-90 78 {(PLOT_TOP + PLOT_BOTTOM) / 2})">Number of SAR Papers</text>',
        ]
    )
    if date.today().year in years:
        note = html.escape(
            f"* {date.today().year} is partial; data snapshot: {date.today():%B %d, %Y}."
        )
        parts.append(
            f'<text x="{PLOT_RIGHT}" y="{HEIGHT - 40}" text-anchor="end" font-size="34" fill="{MUTED}">{note}</text>'
        )
    parts.extend(["</g>", "</svg>"])
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    years, annual_counts, row_count = load_year_counts(input_path)
    stem = "number_of_sar_papers_per_year"
    png_path = output_dir / f"{stem}.png"
    pdf_path = output_dir / "publications_by_year.pdf"
    svg_path = output_dir / f"{stem}.svg"

    render_png(years, annual_counts, png_path)
    render_pdf(years, annual_counts, pdf_path)
    render_svg(years, annual_counts, svg_path)

    print(f"Input: {input_path}")
    print(f"Rows counted: {row_count}")
    print(f"Year range: {years[0]}-{years[-1]}")
    print(f"PNG/SVG: {output_dir / stem}.[png|svg]")
    print(f"PDF: {pdf_path}")


if __name__ == "__main__":
    main()
