"""Plot the proportion of research themes in the SAR study set.

The repository uses multi-label ``repo_analysis_tags``. Each paper contributes
at most once to each mapped research theme, and proportions use the total
number of unique paper-theme assignments as the denominator.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

from plot_sar_papers_per_year import INK, MUTED, WHITE, centered_text, font


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "final_list_with_venue.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figures"

WIDTH, HEIGHT = 2700, 1800
CENTER_X, CENTER_Y = 1320, 880
OUTER_RADIUS, INNER_RADIUS = 570, 315
GROUP_RADIUS = 655
START_ANGLE = -90.0
OUTER_LABEL_RADIUS = 820
OUTER_LEADER_END_RADIUS = 690
GROUP_LABEL_RADIUS = 850
GROUP_LEADER_END_RADIUS = 735

THEME_ORDER = [
    "Understanding",
    "Testing",
    "Prediction",
    "Measurement",
    "Other Mitigation Methods",
    "Rejuvenation",
    "Aging Process Analysis",
]

NON_MITIGATION_THEMES = (
    "Understanding",
    "Testing",
    "Prediction",
    "Measurement",
)

MITIGATION_THEME_ORDER = (
    "Other Mitigation Methods",
    "Rejuvenation",
    "Aging Process Analysis",
)

NON_MITIGATION_COLORS_DARK_TO_LIGHT = (
    "#D9675A",
    "#E98B59",
    "#F2B75F",
    "#F5CE7A",
)

MITIGATION_COLORS = {
    "Other Mitigation Methods": "#9C64A7",
    "Rejuvenation": "#704185",
    "Aging Process Analysis": "#4C2D63",
}

DISPLAY_LABELS = {
    "Prediction": "ARBP",
}

MITIGATION_THEMES = {
    "Aging Process Analysis",
    "Rejuvenation",
    "Other Mitigation Methods",
}

# Explicit, reviewable mapping from the repository taxonomy to figure themes.
UNDERSTANDING_TAGS = {
    "udn",
    "现象分析",
    "分析bug报告",
    "classification",
    "其他",
    "其他（逻辑分析）",
}

INTERNAL_LABEL_RADII = {
    "Aging Process Analysis": 195,
    "Rejuvenation": 185,
    "Other Mitigation Methods": 95,
}

INTERNAL_LEADER_END_RADII = {
    "Aging Process Analysis": 280,
    "Rejuvenation": 260,
    "Other Mitigation Methods": 160,
}

# Wrapped internal labels keep the three text blocks inside the donut hole
# while their centres remain exactly on their corresponding slice radii.
INTERNAL_TITLE_LINES = {
    "Aging Process Analysis": (("Aging Process", -38), ("Analysis (ANA)", 0)),
    "Rejuvenation": (("Rejuvenation (REJ)", -20),),
    "Other Mitigation Methods": (
        ("Other Mitigation", -38),
        ("Methods (OTH)", 0),
    ),
}

INTERNAL_VALUE_OFFSETS = {
    "Aging Process Analysis": 42,
    "Rejuvenation": 26,
    "Other Mitigation Methods": 42,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot proportions of research themes in the SAR study set."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def map_tokens_to_themes(value: str) -> set[str]:
    themes: set[str] = set()
    for raw_token in value.split(";"):
        token = raw_token.strip().casefold()
        if token in UNDERSTANDING_TAGS:
            themes.add("Understanding")
        elif token == "testing":
            themes.add("Testing")
        elif token == "arb prediction":
            themes.add("Prediction")
        elif token == "度量":
            themes.add("Measurement")
        elif token == "rej":
            themes.add("Rejuvenation")
        elif token == "other mitigation":
            themes.add("Other Mitigation Methods")
        elif (
            token == "model-based"
            or token == "hybrid"
            or token.startswith("measurement-based")
            or token == "综述（measurement-based）"
        ):
            themes.add("Aging Process Analysis")
        else:
            raise ValueError(f"Unmapped repo_analysis_tags token: {raw_token!r}")
    return themes


def load_theme_counts(csv_path: Path) -> tuple[Counter[str], int, int, int]:
    counts: Counter[str] = Counter()
    paper_count = 0
    multi_theme_papers = 0
    mitigation_papers = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "repo_analysis_tags" not in reader.fieldnames:
            raise ValueError(f"Missing repo_analysis_tags column in {csv_path}")
        for row_number, row in enumerate(reader, start=2):
            value = (row.get("repo_analysis_tags") or "").strip()
            if not value:
                raise ValueError(f"Blank repo_analysis_tags at CSV row {row_number}")
            themes = map_tokens_to_themes(value)
            if not themes:
                raise ValueError(f"No mapped research theme at CSV row {row_number}")
            counts.update(themes)
            paper_count += 1
            multi_theme_papers += len(themes) > 1
            mitigation_papers += bool(themes & MITIGATION_THEMES)

    missing = set(THEME_ORDER) - set(counts)
    if missing:
        raise ValueError(f"Themes with no assignments: {sorted(missing)}")
    return counts, paper_count, multi_theme_papers, mitigation_papers


def theme_angles(counts: Counter[str]) -> dict[str, tuple[float, float]]:
    total = sum(counts.values())
    angles: dict[str, tuple[float, float]] = {}
    start = START_ANGLE
    for theme in ordered_themes(counts):
        end = start + 360.0 * counts[theme] / total
        angles[theme] = (start, end)
        start = end
    return angles


def ordered_themes(counts: Counter[str]) -> list[str]:
    """Sort major themes by count and keep the mitigation block contiguous."""
    stable_index = {theme: index for index, theme in enumerate(NON_MITIGATION_THEMES)}
    major_themes = sorted(
        NON_MITIGATION_THEMES,
        key=lambda theme: (-counts[theme], stable_index[theme]),
    )
    return [*major_themes, *MITIGATION_THEME_ORDER]


def theme_colors(counts: Counter[str]) -> dict[str, str]:
    """Assign darker major-theme shades to categories with more papers."""
    major_themes = ordered_themes(counts)[: len(NON_MITIGATION_THEMES)]
    colors = dict(MITIGATION_COLORS)
    colors.update(zip(major_themes, NON_MITIGATION_COLORS_DARK_TO_LIGHT))
    return colors


def polar_point(angle_degrees: float, radius: float) -> tuple[float, float]:
    radians = math.radians(angle_degrees)
    return (
        CENTER_X + radius * math.cos(radians),
        CENTER_Y + radius * math.sin(radians),
    )


def radial_leader(
    angle_degrees: float,
    start_radius: float,
    end_radius: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return one straight leader lying exactly on a donut radius."""
    return polar_point(angle_degrees, start_radius), polar_point(
        angle_degrees, end_radius
    )


def label_text(theme: str, count: int, total: int) -> tuple[str, str]:
    return DISPLAY_LABELS.get(theme, theme), f"{100.0 * count / total:.1f}% ({count})"


def internal_label_lines(
    theme: str, count: int, total: int
) -> list[tuple[str, int, int, str]]:
    lines = [(text, offset, 31, INK) for text, offset in INTERNAL_TITLE_LINES[theme]]
    lines.append(
        (
            f"{100.0 * count / total:.1f}% ({count})",
            INTERNAL_VALUE_OFFSETS[theme],
            30,
            MUTED,
        )
    )
    return lines


def mitigation_angles(
    angles: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    return (
        angles["Other Mitigation Methods"][0] + 2.5,
        angles["Aging Process Analysis"][1] - 2.5,
    )


def draw_mitigation_group_png(
    draw: ImageDraw.ImageDraw,
    angles: dict[str, tuple[float, float]],
    mitigation_papers: int,
    paper_count: int,
) -> None:
    start, end = mitigation_angles(angles)
    group_box = (
        CENTER_X - GROUP_RADIUS,
        CENTER_Y - GROUP_RADIUS,
        CENTER_X + GROUP_RADIUS,
        CENTER_Y + GROUP_RADIUS,
    )
    draw.arc(group_box, start=start, end=end, fill=INK, width=6)
    for angle in (start, end):
        inner = polar_point(angle, GROUP_RADIUS - 20)
        outer = polar_point(angle, GROUP_RADIUS + 20)
        draw.line((inner, outer), fill=INK, width=6)

    label_x, label_y = polar_point(137, GROUP_LABEL_RADIUS)
    anchor, end_point = radial_leader(137, GROUP_RADIUS, GROUP_LEADER_END_RADIUS)
    draw.line((anchor, end_point), fill=INK, width=5)
    centered_text(draw, (label_x, label_y - 20), "Mitigation", font(50), fill=INK)
    centered_text(
        draw,
        (label_x, label_y + 36),
        f"{100.0 * mitigation_papers / paper_count:.1f}% ({mitigation_papers})",
        font(38),
        fill=MUTED,
    )


def draw_png_label(
    draw: ImageDraw.ImageDraw,
    theme: str,
    count: int,
    total: int,
    mid_angle: float,
) -> None:
    label_font = font(47)
    value_font = font(40)
    label_x, label_y = polar_point(mid_angle, OUTER_LABEL_RADIUS)
    anchor, end_point = radial_leader(
        mid_angle, OUTER_RADIUS - 3, OUTER_LEADER_END_RADIUS
    )
    draw.line((anchor, end_point), fill="#555555", width=4)
    title, value = label_text(theme, count, total)
    centered_text(draw, (label_x, label_y - 20), title, label_font, fill=INK)
    centered_text(draw, (label_x, label_y + 34), value, value_font, fill=MUTED)


def draw_internal_png_label(
    draw: ImageDraw.ImageDraw,
    theme: str,
    count: int,
    total: int,
    mid_angle: float,
) -> None:
    label_x, label_y = polar_point(mid_angle, INTERNAL_LABEL_RADII[theme])
    anchor, end_point = radial_leader(
        mid_angle, INNER_RADIUS + 4, INTERNAL_LEADER_END_RADII[theme]
    )
    draw.line((anchor, end_point), fill="#777777", width=4)
    for text, offset, size, color in internal_label_lines(theme, count, total):
        centered_text(draw, (label_x, label_y + offset), text, font(size), fill=color)


def render_png(
    counts: Counter[str],
    paper_count: int,
    multi_theme_papers: int,
    mitigation_papers: int,
    output: Path,
) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    angles = theme_angles(counts)
    colors = theme_colors(counts)
    outer_box = (
        CENTER_X - OUTER_RADIUS,
        CENTER_Y - OUTER_RADIUS,
        CENTER_X + OUTER_RADIUS,
        CENTER_Y + OUTER_RADIUS,
    )

    for theme in angles:
        start, end = angles[theme]
        draw.pieslice(
            outer_box,
            start=start,
            end=end,
            fill=colors[theme],
            outline=WHITE,
            width=5,
        )
    draw.ellipse(
        (
            CENTER_X - INNER_RADIUS,
            CENTER_Y - INNER_RADIUS,
            CENTER_X + INNER_RADIUS,
            CENTER_Y + INNER_RADIUS,
        ),
        fill=WHITE,
        outline=WHITE,
        width=4,
    )

    total = sum(counts.values())
    for theme in angles:
        start, end = angles[theme]
        if theme in MITIGATION_THEMES:
            draw_internal_png_label(
                draw, theme, counts[theme], total, (start + end) / 2
            )
        else:
            draw_png_label(draw, theme, counts[theme], total, (start + end) / 2)

    draw_mitigation_group_png(draw, angles, mitigation_papers, paper_count)
    image.convert("RGB").save(output, dpi=(300, 300), optimize=True)


def render_pdf(
    counts: Counter[str],
    paper_count: int,
    multi_theme_papers: int,
    mitigation_papers: int,
    output: Path,
) -> None:
    scale = 72.0 / 300.0
    pdf = canvas.Canvas(str(output), pagesize=(WIDTH * scale, HEIGHT * scale))
    pdf.scale(scale, scale)
    angles = theme_angles(counts)
    colors = theme_colors(counts)
    total = sum(counts.values())

    def py(y: float) -> float:
        return HEIGHT - y

    pdf.setFillColor(HexColor(WHITE))
    pdf.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
    for theme in angles:
        start, end = angles[theme]
        pdf.setFillColor(HexColor(colors[theme]))
        pdf.setStrokeColor(HexColor(WHITE))
        pdf.setLineWidth(5)
        # ReportLab angles are counter-clockwise from 3 o'clock; top-origin
        # Pillow angles are clockwise, so negate and swap the bounds.
        pdf.wedge(
            CENTER_X - OUTER_RADIUS,
            py(CENTER_Y + OUTER_RADIUS),
            CENTER_X + OUTER_RADIUS,
            py(CENTER_Y - OUTER_RADIUS),
            -end,
            end - start,
            fill=1,
            stroke=1,
        )
    pdf.setFillColor(HexColor(WHITE))
    pdf.setStrokeColor(HexColor(WHITE))
    pdf.circle(CENTER_X, py(CENTER_Y), INNER_RADIUS, fill=1, stroke=1)

    for theme in angles:
        start, end = angles[theme]
        mid = (start + end) / 2
        if theme in MITIGATION_THEMES:
            label_x, label_y_top = polar_point(mid, INTERNAL_LABEL_RADII[theme])
            anchor, end_point = radial_leader(
                mid, INNER_RADIUS + 4, INTERNAL_LEADER_END_RADII[theme]
            )
            pdf.setStrokeColor(HexColor("#777777"))
            pdf.setLineWidth(4)
            pdf.line(anchor[0], py(anchor[1]), end_point[0], py(end_point[1]))
            for text, offset, size, color in internal_label_lines(
                theme, counts[theme], total
            ):
                pdf.setFillColor(HexColor(color))
                pdf.setFont("Times-Roman", size)
                pdf.drawCentredString(label_x, py(label_y_top + offset + 15), text)
            continue
        label_x, label_y_top = polar_point(mid, OUTER_LABEL_RADIUS)
        anchor, end_point = radial_leader(
            mid, OUTER_RADIUS - 3, OUTER_LEADER_END_RADIUS
        )
        pdf.setStrokeColor(HexColor("#555555"))
        pdf.setLineWidth(4)
        pdf.line(anchor[0], py(anchor[1]), end_point[0], py(end_point[1]))

        title, value = label_text(theme, counts[theme], total)
        pdf.setFillColor(HexColor(INK))
        pdf.setFont("Times-Roman", 47)
        pdf.drawCentredString(label_x, py(label_y_top - 5), title)
        pdf.setFillColor(HexColor(MUTED))
        pdf.setFont("Times-Roman", 40)
        pdf.drawCentredString(label_x, py(label_y_top + 47), value)

    group_start, group_end = mitigation_angles(angles)
    pdf.setStrokeColor(HexColor(INK))
    pdf.setLineWidth(6)
    pdf.arc(
        CENTER_X - GROUP_RADIUS,
        py(CENTER_Y + GROUP_RADIUS),
        CENTER_X + GROUP_RADIUS,
        py(CENTER_Y - GROUP_RADIUS),
        -group_end,
        group_end - group_start,
    )
    for angle in (group_start, group_end):
        inner = polar_point(angle, GROUP_RADIUS - 20)
        outer = polar_point(angle, GROUP_RADIUS + 20)
        pdf.line(inner[0], py(inner[1]), outer[0], py(outer[1]))
    label_x, label_y_top = polar_point(137, GROUP_LABEL_RADIUS)
    anchor, end_point = radial_leader(137, GROUP_RADIUS, GROUP_LEADER_END_RADIUS)
    pdf.line(anchor[0], py(anchor[1]), end_point[0], py(end_point[1]))
    pdf.setFillColor(HexColor(INK))
    pdf.setFont("Times-Roman", 50)
    pdf.drawCentredString(label_x, py(label_y_top - 4), "Mitigation")
    pdf.setFillColor(HexColor(MUTED))
    pdf.setFont("Times-Roman", 38)
    pdf.drawCentredString(
        label_x,
        py(label_y_top + 48),
        f"{100.0 * mitigation_papers / paper_count:.1f}% ({mitigation_papers})",
    )

    pdf.showPage()
    pdf.save()


def annular_svg_path(start: float, end: float) -> str:
    outer_start = polar_point(start, OUTER_RADIUS)
    outer_end = polar_point(end, OUTER_RADIUS)
    inner_end = polar_point(end, INNER_RADIUS)
    inner_start = polar_point(start, INNER_RADIUS)
    large_arc = 1 if end - start > 180 else 0
    return (
        f"M {outer_start[0]:.2f} {outer_start[1]:.2f} "
        f"A {OUTER_RADIUS} {OUTER_RADIUS} 0 {large_arc} 1 {outer_end[0]:.2f} {outer_end[1]:.2f} "
        f"L {inner_end[0]:.2f} {inner_end[1]:.2f} "
        f"A {INNER_RADIUS} {INNER_RADIUS} 0 {large_arc} 0 {inner_start[0]:.2f} {inner_start[1]:.2f} Z"
    )


def render_svg(
    counts: Counter[str],
    paper_count: int,
    multi_theme_papers: int,
    mitigation_papers: int,
    output: Path,
) -> None:
    angles = theme_angles(counts)
    colors = theme_colors(counts)
    total = sum(counts.values())
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        '<g font-family="Times New Roman, Times, serif">',
    ]
    for theme in angles:
        start, end = angles[theme]
        parts.append(
            f'<path d="{annular_svg_path(start, end)}" fill="{colors[theme]}" stroke="#FFFFFF" stroke-width="5"/>'
        )
    for theme in angles:
        start, end = angles[theme]
        if theme in MITIGATION_THEMES:
            mid = (start + end) / 2
            anchor, end_point = radial_leader(
                mid, INNER_RADIUS + 4, INTERNAL_LEADER_END_RADII[theme]
            )
            label_x, label_y = polar_point(mid, INTERNAL_LABEL_RADII[theme])
            parts.append(
                f'<line x1="{anchor[0]:.2f}" y1="{anchor[1]:.2f}" x2="{end_point[0]:.2f}" y2="{end_point[1]:.2f}" stroke="#777777" stroke-width="4"/>'
            )
            for text, offset, size, color in internal_label_lines(
                theme, counts[theme], total
            ):
                parts.append(
                    f'<text x="{label_x:.2f}" y="{label_y + offset + 15:.2f}" text-anchor="middle" font-size="{size}" fill="{color}">{html.escape(text)}</text>'
                )
            continue
        mid = (start + end) / 2
        label_x, label_y = polar_point(mid, OUTER_LABEL_RADIUS)
        anchor, end_point = radial_leader(
            mid, OUTER_RADIUS - 3, OUTER_LEADER_END_RADIUS
        )
        title, value = label_text(theme, counts[theme], total)
        parts.append(
            f'<line x1="{anchor[0]:.2f}" y1="{anchor[1]:.2f}" x2="{end_point[0]:.2f}" y2="{end_point[1]:.2f}" stroke="#555555" stroke-width="4"/>'
        )
        parts.append(
            f'<text x="{label_x:.2f}" y="{label_y - 5:.2f}" text-anchor="middle" font-size="47" fill="{INK}">{html.escape(title)}</text>'
        )
        parts.append(
            f'<text x="{label_x:.2f}" y="{label_y + 47:.2f}" text-anchor="middle" font-size="40" fill="{MUTED}">{html.escape(value)}</text>'
        )

    group_start, group_end = mitigation_angles(angles)
    arc_start = polar_point(group_start, GROUP_RADIUS)
    arc_end = polar_point(group_end, GROUP_RADIUS)
    group_span = group_end - group_start
    large_arc = 1 if group_span > 180 else 0
    parts.append(
        f'<path d="M {arc_start[0]:.2f} {arc_start[1]:.2f} A {GROUP_RADIUS} {GROUP_RADIUS} 0 {large_arc} 1 {arc_end[0]:.2f} {arc_end[1]:.2f}" fill="none" stroke="{INK}" stroke-width="6"/>'
    )
    for angle in (group_start, group_end):
        inner = polar_point(angle, GROUP_RADIUS - 20)
        outer = polar_point(angle, GROUP_RADIUS + 20)
        parts.append(
            f'<line x1="{inner[0]:.2f}" y1="{inner[1]:.2f}" x2="{outer[0]:.2f}" y2="{outer[1]:.2f}" stroke="{INK}" stroke-width="6"/>'
        )
    mitigation_label_x, mitigation_label_y = polar_point(137, GROUP_LABEL_RADIUS)
    anchor, end_point = radial_leader(137, GROUP_RADIUS, GROUP_LEADER_END_RADIUS)
    parts.append(
        f'<line x1="{anchor[0]:.2f}" y1="{anchor[1]:.2f}" x2="{end_point[0]:.2f}" y2="{end_point[1]:.2f}" stroke="{INK}" stroke-width="5"/>'
    )
    parts.append(
        f'<text x="{mitigation_label_x:.2f}" y="{mitigation_label_y - 4:.2f}" text-anchor="middle" font-size="50" fill="{INK}">Mitigation</text>'
    )
    parts.append(
        f'<text x="{mitigation_label_x:.2f}" y="{mitigation_label_y + 48:.2f}" text-anchor="middle" font-size="38" fill="{MUTED}">{100.0 * mitigation_papers / paper_count:.1f}% ({mitigation_papers})</text>'
    )
    parts.extend(
        [
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
    counts, paper_count, multi_theme_papers, mitigation_papers = load_theme_counts(
        input_path
    )
    total = sum(counts.values())
    stem = "proportion_of_research_themes_in_sar"

    render_png(
        counts,
        paper_count,
        multi_theme_papers,
        mitigation_papers,
        output_dir / f"{stem}.png",
    )
    render_pdf(
        counts,
        paper_count,
        multi_theme_papers,
        mitigation_papers,
        output_dir / "content.pdf",
    )
    render_svg(
        counts,
        paper_count,
        multi_theme_papers,
        mitigation_papers,
        output_dir / f"{stem}.svg",
    )

    print(f"Input: {input_path}")
    print(f"Papers: {paper_count}")
    print(f"Theme assignments: {total}")
    print(f"Multi-theme papers: {multi_theme_papers}")
    print(
        f"Mitigation papers: {mitigation_papers} "
        f"({100.0 * mitigation_papers / paper_count:.1f}%)"
    )
    for theme in ordered_themes(counts):
        print(f"  {theme}: {counts[theme]} ({100.0 * counts[theme] / total:.1f}%)")
    print(f"PNG/SVG: {output_dir / stem}.[png|svg]")
    print(f"PDF: {output_dir / 'content.pdf'}")


if __name__ == "__main__":
    main()
