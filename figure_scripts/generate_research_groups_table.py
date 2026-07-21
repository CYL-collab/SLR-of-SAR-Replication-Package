"""Generate a LaTeX table of research groups and their contributions.

The script performs four reproducible steps:

1. normalize author strings and merge high-confidence aliases;
2. build a fractional, weighted co-authorship network;
3. detect non-overlapping author communities with deterministic modularity
   local moving; and
4. assign each paper once to a community and count its research themes.

Audit CSV files are written alongside the table so that every alias, group
membership, paper assignment, and total can be inspected independently.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import random
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "final_list_with_venue.csv"
DEFAULT_TEX_OUTPUT = REPO_ROOT / "figures" / "research_groups_and_contributions.tex"
DEFAULT_AUDIT_DIR = REPO_ROOT / "outputs" / "research_groups"

THEME_ORDER = (
    "Understanding",
    "Measurement",
    "Testing",
    "ANA",
    "REJ",
    "OTM",
    "Prediction",
)

UNDERSTANDING_TAGS = {
    "udn",
    "现象分析",
    "分析bug报告",
    "classification",
    "其他",
    "其他（逻辑分析）",
}

# Only aliases that cannot be resolved safely from normalized spelling,
# full-first-name + surname, or a unique surname/initial candidate belong here.
# Both names must occur in the input; this keeps the list auditable.
MANUAL_AUTHOR_ALIASES = {
    "K-Y Cai": "Kai-Yuan Cai",
    "Cai Kai-Yuan": "Kai-Yuan Cai",
    "Dong Seong Kim": "Dong-Seong Kim",
    "Wei Yue Li": "Weiyue Li",
    "Yun Sheng Wang": "Yunsheng Wang",
    "Xiaolin Changa": "Xiaolin Chang",
    "Lalita Bhanu Murthy Neti": "Lalita Bhanu Murthy",
    "L. Li": "Lei Li",
    "Daniel Sadoc Menasch": "Daniel Sadoc Menasche",
}

AUTHOR_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
AUTHOR_PARTICLES = {"da", "de", "del", "della", "di", "dos", "du", "la", "le", "van", "von"}

# Expert-reviewed constraints supplement the data-driven partition. They are
# intentionally explicit because recurring cross-laboratory collaborations can
# otherwise absorb a recognizable research group into a larger community.
REVIEWED_GROUP_MERGES = (
    ("Zheng Zheng", "Kai-Yuan Cai"),
    ("Paulo Maciel", "Matheus Torquato"),
)
REVIEWED_SPLIT_ANCHORS = ("Rivalino Matias",)
PAPER_ASSIGNMENT_PRIORITY = ("Rivalino Matias",)
PARTITION_STABILITY_PAIRS = (
    ("Kishor S. Trivedi", "Rivalino Matias"),
    ("Zheng Zheng", "Kai-Yuan Cai"),
    ("Paulo Maciel", "Jean Teixeira de Araujo"),
    ("Tadashi Dohi", "Hiroyuki Okamura"),
    ("Domenico Cotroneo", "Roberto Pietrantuono"),
    ("Fumio Machida", "Ermeson Andrade"),
    ("Jianwen Xiang", "Dongdong Zhao"),
)

# Source-data affiliation accidentally stored as an author on one record.
EXCLUDED_NON_AUTHOR_STRINGS = {
    "Tianjin Key Laboratory for Advanced Signal Processing, Civil Aviation University of China, Tianjin 300300, China",
}

# The repository row for this DOI contains only the first three authors as
# initials. The complete list was checked against the publisher-formatted
# paper and DBLP record. Keeping this correction here avoids silently changing
# the source CSV and makes the intervention reproducible.
AUTHOR_LIST_OVERRIDES_BY_DOI = {
    "10.1109/tetc.2025.3546549": (
        "Dongdong Zhao",
        "Zhihui Liu",
        "Fengji Zhang",
        "Lei Liu",
        "Jacky Wai Keung",
        "Xiao Yu",
    ),
}
@dataclass(frozen=True)
class Paper:
    row_number: int
    doi: str
    title: str
    year: str
    raw_authors: tuple[str, ...]
    authors: tuple[str, ...]
    raw_tags: str
    themes: frozenset[str]


@dataclass(frozen=True)
class AliasRecord:
    raw_author: str
    canonical_author: str
    occurrences: int
    method: str
    confidence: str
    candidates: str = ""


@dataclass
class GroupSummary:
    community: int
    group_id: str
    label: str
    members: list[str]
    paper_indices: list[int]
    counts: Counter[str]

    @property
    def paper_count(self) -> int:
        return len(self.paper_indices)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the Research Groups and Their Contributions TeX table."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--tex-output", type=Path, default=DEFAULT_TEX_OUTPUT)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--top-groups", type=int, default=8)
    parser.add_argument(
        "--resolution",
        type=float,
        default=2.0,
        help="Community resolution; larger values produce smaller groups.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--restarts", type=int, default=12)
    return parser.parse_args()


def fold_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).casefold()


def author_tokens(author: str) -> tuple[str, ...]:
    value = fold_ascii(author).strip()
    if "," in value:
        # Bibliographic surname-first forms: "Araujo, Jean" and the related
        # suffix-first form "Jr., Rivalino Matias".
        left, right = value.split(",", 1)
        value = f"{right.strip()} {left.strip()}"
    # Hyphens and apostrophes inside names are typographic variants here:
    # Kai-Yuan == Kaiyuan, Yan-Bin == YanBin.
    value = re.sub(r"(?<=\w)[\-'](?=\w)", "", value)
    tokens = re.findall(r"[a-z0-9]+", value)
    if tokens and tokens[-1] in AUTHOR_SUFFIXES:
        tokens = tokens[:-1]
    return tuple(tokens)


def author_profile(author: str) -> tuple[str, tuple[str, ...], str]:
    tokens = author_tokens(author)
    if not tokens:
        return "", (), ""
    surname = tokens[-1]
    given_list = list(tokens[:-1])
    while given_list and given_list[-1] in AUTHOR_PARTICLES:
        given_list.pop()
    given = tuple(given_list)
    initials = "".join(token[0] for token in given if token)
    return surname, given, initials


def is_abbreviated(author: str) -> bool:
    _, given, _ = author_profile(author)
    return bool(given) and all(len(token) == 1 for token in given)


def canonical_name_score(author: str, occurrences: Counter[str]) -> tuple[int, int, int, str]:
    _, given, _ = author_profile(author)
    full_tokens = sum(len(token) > 1 for token in given)
    return (full_tokens, occurrences[author], len(author), author)


def resolve_author_aliases(
    raw_occurrences: Counter[str],
) -> tuple[dict[str, str], list[AliasRecord]]:
    """Resolve conservative, high-confidence author aliases.

    Ambiguous initials (for example, ``J. Liu`` when multiple J. Liu candidates
    exist) are deliberately retained as separate authors and flagged in the
    audit file instead of being guessed.
    """

    names = sorted(raw_occurrences)
    exact_buckets: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for name in names:
        tokens = author_tokens(name)
        if not tokens:
            raise ValueError(f"Author name has no usable tokens: {name!r}")
        exact_buckets[tokens].append(name)

    exact_representative: dict[str, str] = {}
    for bucket in exact_buckets.values():
        representative = max(
            bucket, key=lambda name: canonical_name_score(name, raw_occurrences)
        )
        for name in bucket:
            exact_representative[name] = representative

    representatives = sorted(set(exact_representative.values()))
    full_buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name in representatives:
        surname, given, _ = author_profile(name)
        if given and len(given[0]) > 1:
            full_buckets[(surname, given[0])].append(name)

    full_representative: dict[str, str] = {}
    for bucket in full_buckets.values():
        representative = max(
            bucket, key=lambda name: canonical_name_score(name, raw_occurrences)
        )
        for name in bucket:
            full_representative[name] = representative

    mapping: dict[str, str] = {}
    methods: dict[str, str] = {}
    candidates_by_name: dict[str, str] = {}

    for raw_name in names:
        exact_name = exact_representative[raw_name]
        canonical = full_representative.get(exact_name, exact_name)
        mapping[raw_name] = canonical
        if raw_name != exact_name:
            methods[raw_name] = "normalized_spelling"
        elif exact_name != canonical:
            methods[raw_name] = "same_full_first_surname"
        else:
            methods[raw_name] = "unchanged"

    canonical_full_names = sorted(
        {
            full_representative.get(name, name)
            for name in representatives
            if author_profile(name)[1]
            and len(author_profile(name)[1][0]) > 1
        }
    )

    for raw_name in names:
        exact_name = exact_representative[raw_name]
        if not is_abbreviated(exact_name):
            continue
        surname, given, initials = author_profile(exact_name)
        compatible: list[str] = []
        for full_name in canonical_full_names:
            full_surname, full_given, full_initials = author_profile(full_name)
            if full_surname != surname or not full_given:
                continue
            if not full_given[0].startswith(given[0]):
                continue
            if initials.startswith(full_initials) or full_initials.startswith(initials):
                compatible.append(full_name)
        compatible = sorted(set(compatible))
        if len(compatible) == 1:
            mapping[raw_name] = compatible[0]
            methods[raw_name] = "unique_initial_expansion"
        elif len(compatible) > 1:
            methods[raw_name] = "unresolved_ambiguous_initial"
            candidates_by_name[raw_name] = " | ".join(compatible)

    for alias, canonical in MANUAL_AUTHOR_ALIASES.items():
        if alias not in raw_occurrences:
            continue
        if canonical not in raw_occurrences:
            raise ValueError(
                f"Manual alias target {canonical!r} is absent for alias {alias!r}"
            )
        mapping[alias] = mapping.get(canonical, canonical)
        methods[alias] = "manual_review"

    # Collapse mapping chains introduced by manual aliases.
    for raw_name in names:
        canonical = mapping[raw_name]
        visited = {raw_name}
        while canonical in mapping and mapping[canonical] != canonical:
            if canonical in visited:
                raise ValueError(f"Cycle in author aliases involving {raw_name!r}")
            visited.add(canonical)
            canonical = mapping[canonical]
        mapping[raw_name] = canonical

    records: list[AliasRecord] = []
    for raw_name in names:
        method = methods[raw_name]
        if method in {
            "normalized_spelling",
            "same_full_first_surname",
            "unique_initial_expansion",
            "manual_review",
        }:
            confidence = "high"
        elif method == "unresolved_ambiguous_initial":
            confidence = "unresolved"
        else:
            confidence = "not_applicable"
        records.append(
            AliasRecord(
                raw_author=raw_name,
                canonical_author=mapping[raw_name],
                occurrences=raw_occurrences[raw_name],
                method=method,
                confidence=confidence,
                candidates=candidates_by_name.get(raw_name, ""),
            )
        )
    return mapping, records


def map_tags_to_themes(value: str) -> frozenset[str]:
    themes: set[str] = set()
    for raw_token in value.split(";"):
        token = raw_token.strip().casefold()
        if not token:
            continue
        if token in UNDERSTANDING_TAGS:
            themes.add("Understanding")
        elif token == "testing":
            themes.add("Testing")
        elif token == "arb prediction":
            themes.add("Prediction")
        elif token == "度量":
            themes.add("Measurement")
        elif token == "rej":
            themes.add("REJ")
        elif token == "other mitigation":
            themes.add("OTM")
        elif (
            token == "model-based"
            or token == "hybrid"
            or token.startswith("measurement-based")
            or token == "综述（measurement-based）"
        ):
            themes.add("ANA")
        else:
            raise ValueError(f"Unmapped repo_analysis_tags token: {raw_token!r}")
    if not themes:
        raise ValueError(f"No research theme mapped from {value!r}")
    return frozenset(themes)


def read_raw_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"doi", "title", "year", "author", "repo_analysis_tags"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing CSV columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"No papers found in {csv_path}")
    return rows


def effective_authors(row: dict[str, str]) -> tuple[str, ...]:
    doi = (row.get("doi") or "").strip().casefold()
    override = AUTHOR_LIST_OVERRIDES_BY_DOI.get(doi)
    if override is not None:
        return override
    return tuple(
        author.strip()
        for author in (row.get("author") or "").split(";")
        if author.strip() and author.strip() not in EXCLUDED_NON_AUTHOR_STRINGS
    )


def build_papers(
    rows: list[dict[str, str]], mapping: dict[str, str]
) -> list[Paper]:
    papers: list[Paper] = []
    for row_number, row in enumerate(rows, start=2):
        raw_authors = effective_authors(row)
        if not raw_authors:
            raise ValueError(f"Blank author list at CSV row {row_number}")
        authors = tuple(dict.fromkeys(mapping[author] for author in raw_authors))
        raw_tags = (row.get("repo_analysis_tags") or "").strip()
        if not raw_tags:
            raise ValueError(f"Blank repo_analysis_tags at CSV row {row_number}")
        papers.append(
            Paper(
                row_number=row_number,
                doi=(row.get("doi") or "").strip(),
                title=(row.get("title") or "").strip(),
                year=(row.get("year") or "").strip(),
                raw_authors=raw_authors,
                authors=authors,
                raw_tags=raw_tags,
                themes=map_tags_to_themes(raw_tags),
            )
        )
    return papers


def build_coauthor_graph(
    papers: Iterable[Paper],
) -> tuple[dict[str, dict[str, float]], Counter[str], Counter[tuple[str, str]]]:
    mentions: Counter[str] = Counter()
    pair_papers: Counter[tuple[str, str]] = Counter()
    adjacency: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for paper in papers:
        mentions.update(paper.authors)
        for author in paper.authors:
            adjacency[author]
        if len(paper.authors) < 2:
            continue
        # Fractional weighting gives every author one unit of collaboration
        # strength per multi-author paper, regardless of author-list length.
        edge_weight = 1.0 / (len(paper.authors) - 1)
        for left, right in itertools.combinations(sorted(paper.authors), 2):
            adjacency[left][right] += edge_weight
            adjacency[right][left] += edge_weight
            pair_papers[(left, right)] += 1

    return (
        {author: dict(neighbors) for author, neighbors in adjacency.items()},
        mentions,
        pair_papers,
    )


def modularity_score(
    adjacency: dict[str, dict[str, float]],
    communities: dict[str, int],
    resolution: float,
) -> float:
    degrees = {author: sum(neighbors.values()) for author, neighbors in adjacency.items()}
    total_edge_weight = sum(degrees.values()) / 2.0
    if total_edge_weight == 0:
        return 0.0
    totals: dict[int, float] = defaultdict(float)
    internal: dict[int, float] = defaultdict(float)
    for author, degree in degrees.items():
        totals[communities[author]] += degree
        for neighbor, weight in adjacency[author].items():
            if author < neighbor and communities[author] == communities[neighbor]:
                internal[communities[author]] += weight
    return sum(
        internal[community] / total_edge_weight
        - resolution * (totals[community] / (2.0 * total_edge_weight)) ** 2
        for community in totals
    )


def local_modularity_partition(
    adjacency: dict[str, dict[str, float]],
    resolution: float,
    seed: int,
) -> dict[str, int]:
    """Run one deterministic-seed modularity local-moving partition."""

    authors = sorted(adjacency)
    communities = {author: index for index, author in enumerate(authors)}
    degrees = {author: sum(adjacency[author].values()) for author in authors}
    total_edge_weight = sum(degrees.values()) / 2.0
    if total_edge_weight == 0:
        return communities

    totals = {communities[author]: degrees[author] for author in authors}
    rng = random.Random(seed)

    for _ in range(100):
        changed = 0
        order = authors[:]
        rng.shuffle(order)
        for author in order:
            old_community = communities[author]
            degree = degrees[author]
            if degree == 0:
                continue
            totals[old_community] -= degree
            neighbor_weights: dict[int, float] = defaultdict(float)
            for neighbor, weight in adjacency[author].items():
                neighbor_weights[communities[neighbor]] += weight

            best_community = old_community
            best_gain = 0.0
            for candidate, internal_weight in neighbor_weights.items():
                gain = internal_weight - (
                    resolution
                    * degree
                    * totals.get(candidate, 0.0)
                    / (2.0 * total_edge_weight)
                )
                if gain > best_gain + 1e-12 or (
                    math.isclose(gain, best_gain, abs_tol=1e-12)
                    and candidate < best_community
                ):
                    best_community = candidate
                    best_gain = gain

            communities[author] = best_community
            totals[best_community] = totals.get(best_community, 0.0) + degree
            changed += best_community != old_community
        if changed == 0:
            break

    # Replace implementation-dependent numeric labels with stable integers.
    members: dict[int, list[str]] = defaultdict(list)
    for author, community in communities.items():
        members[community].append(author)
    ordered = sorted(
        members,
        key=lambda community: (-len(members[community]), tuple(sorted(members[community]))),
    )
    relabel = {community: index for index, community in enumerate(ordered)}
    return {author: relabel[community] for author, community in communities.items()}


def select_partition(
    adjacency: dict[str, dict[str, float]],
    resolution: float,
    seed: int,
    restarts: int,
) -> tuple[dict[str, int], float, int]:
    if restarts < 1:
        raise ValueError("--restarts must be at least 1")
    candidates: list[tuple[float, tuple[tuple[str, int], ...], int, dict[str, int]]] = []
    for restart in range(restarts):
        partition = local_modularity_partition(
            adjacency, resolution=resolution, seed=seed + restart
        )
        score = modularity_score(adjacency, partition, resolution)
        signature = tuple(sorted(partition.items()))
        candidates.append((score, signature, seed + restart, partition))
    score, _, chosen_seed, partition = max(candidates, key=lambda item: (item[0], item[1]))
    return partition, score, chosen_seed


def apply_reviewed_group_constraints(
    partition: dict[str, int],
    adjacency: dict[str, dict[str, float]],
    mentions: Counter[str],
    pair_papers: Counter[tuple[str, str]],
) -> dict[str, int]:
    """Apply expert-reviewed community merges and anchor-group splits."""

    constrained = dict(partition)
    for left_anchor, right_anchor in REVIEWED_GROUP_MERGES:
        if left_anchor not in constrained or right_anchor not in constrained:
            raise ValueError(
                f"Reviewed group merge references an absent author: "
                f"{left_anchor!r}, {right_anchor!r}"
            )
        target = constrained[left_anchor]
        source = constrained[right_anchor]
        if target != source:
            for author in constrained:
                if constrained[author] == source:
                    constrained[author] = target

    for anchor in REVIEWED_SPLIT_ANCHORS:
        if anchor not in constrained:
            raise ValueError(f"Reviewed split anchor is absent: {anchor!r}")
        new_community = max(constrained.values(), default=-1) + 1
        constrained[anchor] = new_community
        # Keep satellite coauthors whose entire publication record in this
        # corpus is linked to the anchor. Authors with independent papers stay
        # in their data-driven communities.
        for neighbor in adjacency[anchor]:
            pair = tuple(sorted((anchor, neighbor)))
            if pair_papers[pair] == mentions[neighbor]:
                constrained[neighbor] = new_community

    return constrained


def surname_for_label(author: str) -> str:
    display_tokens = author.replace(",", " ").split()
    if not display_tokens:
        return author
    while display_tokens and fold_ascii(display_tokens[-1]).rstrip(".") in AUTHOR_SUFFIXES:
        display_tokens.pop()
    return display_tokens[-1]


def make_group_label(
    members: list[str],
    mentions: Counter[str],
    degrees: dict[str, float],
    pair_papers: Counter[tuple[str, str]],
) -> str:
    if {"Zheng Zheng", "Kai-Yuan Cai"}.issubset(members):
        return "Cai, Zheng et al."
    ranked = sorted(
        members,
        key=lambda author: (mentions[author], degrees[author], author),
        reverse=True,
    )
    leader = ranked[0]
    surnames = [surname_for_label(leader)]
    if len(ranked) > 1:
        second = ranked[1]
        pair = tuple(sorted((leader, second)))
        if (
            mentions[second] >= 0.70 * mentions[leader]
            and pair_papers[pair] >= 2
        ):
            second_surname = surname_for_label(second)
            if second_surname not in surnames:
                surnames.append(second_surname)
    return f"{', '.join(surnames)} et al."


def summarize_groups(
    papers: list[Paper],
    partition: dict[str, int],
    adjacency: dict[str, dict[str, float]],
    mentions: Counter[str],
    pair_papers: Counter[tuple[str, str]],
) -> tuple[list[GroupSummary], dict[int, int], dict[int, str]]:
    degrees = {author: sum(adjacency[author].values()) for author in adjacency}
    community_members: dict[int, list[str]] = defaultdict(list)
    for author, community in partition.items():
        community_members[community].append(author)

    paper_community: dict[int, int] = {}
    paper_lead: dict[int, str] = {}
    assigned: dict[int, list[int]] = defaultdict(list)
    for paper_index, paper in enumerate(papers):
        # Cross-community collaborations are assigned once to the community of
        # the paper's most prolific author. This produces mutually exclusive
        # group totals while keeping the rule deterministic and auditable.
        priority_authors = [
            author for author in PAPER_ASSIGNMENT_PRIORITY if author in paper.authors
        ]
        if priority_authors:
            lead = priority_authors[0]
        else:
            lead = max(
                paper.authors,
                key=lambda author: (mentions[author], degrees[author], author),
            )
        community = partition[lead]
        paper_community[paper_index] = community
        paper_lead[paper_index] = lead
        assigned[community].append(paper_index)

    ordered_communities = sorted(
        community_members,
        key=lambda community: (
            len(assigned[community]),
            sum(mentions[author] for author in community_members[community]),
            tuple(sorted(community_members[community])),
        ),
        reverse=True,
    )

    summaries: list[GroupSummary] = []
    community_to_group_id: dict[int, str] = {}
    for rank, community in enumerate(ordered_communities, start=1):
        group_id = f"G{rank:02d}"
        members = sorted(
            community_members[community],
            key=lambda author: (mentions[author], degrees[author], author),
            reverse=True,
        )
        counts: Counter[str] = Counter()
        for paper_index in assigned[community]:
            counts.update(papers[paper_index].themes)
        summary = GroupSummary(
            community=community,
            group_id=group_id,
            label=make_group_label(members, mentions, degrees, pair_papers),
            members=members,
            paper_indices=assigned[community],
            counts=counts,
        )
        summaries.append(summary)
        community_to_group_id[community] = group_id

    return summaries, paper_community, paper_lead


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def heat_cell(value: int, column_maximum: int) -> str:
    if value <= 0 or column_maximum <= 0:
        return str(value)
    intensity = round(12 + 68 * value / column_maximum)
    return rf"\cellcolor{{SARHeat!{intensity}}} {value}"


def render_tex(top_groups: list[GroupSummary], source_name: str) -> str:
    if not top_groups:
        raise ValueError("No research groups available for the table")
    maxima = {
        theme: max(group.counts[theme] for group in top_groups) for theme in THEME_ORDER
    }
    totals = Counter()
    for group in top_groups:
        totals.update(group.counts)
    unique_total = sum(group.paper_count for group in top_groups)

    lines = [
        "% Auto-generated by figure_scripts/generate_research_groups_table.py.",
        "% Required packages: \\usepackage[table]{xcolor}, \\usepackage{booktabs},",
        "% \\usepackage{multirow}, and \\usepackage{graphicx}.",
        r"\definecolor{SARHeat}{HTML}{E58B7B}",
        r"\begin{table*}[t]",
        r"  \centering",
        r"  \caption{Research Groups and Their Contributions}",
        r"  \label{tab:research-groups-contributions}",
        r"  \small",
        r"  \setlength{\tabcolsep}{5.2pt}",
        r"  \renewcommand{\arraystretch}{1.08}",
        r"  \resizebox{\textwidth}{!}{%",
        r"  \begin{tabular}{lrrrrrrrr}",
        r"    \toprule",
        r"    \multirow{2}{*}{Group} & \multirow{2}{*}{Understanding} & \multirow{2}{*}{Measurement} & \multirow{2}{*}{Testing} & \multicolumn{3}{c}{Mitigation} & \multirow{2}{*}{Prediction} & \multirow{2}{*}{$\Sigma$} \\",
        r"    \cmidrule(lr){5-7}",
        r"    & & & & ANA & REJ & OTM & & \\",
        r"    \midrule",
    ]

    for group in top_groups:
        cells = [tex_escape(group.label)]
        cells.extend(heat_cell(group.counts[theme], maxima[theme]) for theme in THEME_ORDER)
        cells.append(str(group.paper_count))
        lines.append("    " + " & ".join(cells) + r" \\")

    lines.extend(
        [
            r"    \midrule",
            "    "
            + " & ".join(
                [r"$\Sigma$"]
                + [str(totals[theme]) for theme in THEME_ORDER]
                + [str(unique_total)]
            )
            + r" \\",
            r"    \bottomrule",
            r"  \end{tabular}%",
            r"  }",
            r"  \vspace{2pt}",
            r"  \begin{minipage}{\textwidth}",
            r"    \footnotesize\textit{Notes.} ANA = aging-process analysis; REJ = rejuvenation; OTM = other mitigation methods. Papers with multiple research-theme tags can contribute to multiple thematic columns, whereas $\Sigma$ counts unique papers. Each paper is assigned once using reviewed anchor-group constraints and otherwise the community of its most prolific coauthor. Source: \texttt{" + tex_escape(source_name) + r"}.",
            r"  \end{minipage}",
            r"\end{table*}",
            "",
        ]
    )
    return "\n".join(lines)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_audit_outputs(
    audit_dir: Path,
    source_rows: list[dict[str, str]],
    alias_records: list[AliasRecord],
    papers: list[Paper],
    summaries: list[GroupSummary],
    paper_community: dict[int, int],
    paper_lead: dict[int, str],
    partition: dict[str, int],
    algorithmic_partition: dict[str, int],
    adjacency: dict[str, dict[str, float]],
    mentions: Counter[str],
    pair_papers: Counter[tuple[str, str]],
    algorithmic_modularity: float,
    constrained_modularity: float,
    resolution: float,
    chosen_seed: int,
    base_seed: int,
    restarts: int,
    top_groups: int,
) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    summary_by_community = {summary.community: summary for summary in summaries}

    write_csv(
        audit_dir / "author_aliases.csv",
        [
            "raw_author",
            "canonical_author",
            "occurrences",
            "merge_method",
            "confidence",
            "candidates_if_ambiguous",
        ],
        (
            {
                "raw_author": record.raw_author,
                "canonical_author": record.canonical_author,
                "occurrences": record.occurrences,
                "merge_method": record.method,
                "confidence": record.confidence,
                "candidates_if_ambiguous": record.candidates,
            }
            for record in alias_records
        ),
    )

    write_csv(
        audit_dir / "source_author_corrections.csv",
        [
            "doi",
            "source_author_value",
            "effective_author_value",
            "reason",
        ],
        (
            {
                "doi": doi,
                "source_author_value": next(
                    (row.get("author") or "" for row in source_rows if (row.get("doi") or "").strip().casefold() == doi),
                    "",
                ),
                "effective_author_value": "; ".join(authors),
                "reason": "Source row contains only the first three authors as initials; completed from DOI metadata.",
            }
            for doi, authors in AUTHOR_LIST_OVERRIDES_BY_DOI.items()
        ),
    )

    stability_partitions = [
        local_modularity_partition(adjacency, resolution, base_seed + restart)
        for restart in range(restarts)
    ]
    write_csv(
        audit_dir / "partition_stability.csv",
        [
            "author_a",
            "author_b",
            "coauthored_papers",
            "same_community_restarts",
            "total_restarts",
            "same_community_rate",
            "selected_algorithmic_partition",
            "reviewed_partition",
        ],
        (
            {
                "author_a": left,
                "author_b": right,
                "coauthored_papers": pair_papers[tuple(sorted((left, right)))],
                "same_community_restarts": sum(
                    candidate[left] == candidate[right]
                    for candidate in stability_partitions
                ),
                "total_restarts": restarts,
                "same_community_rate": f"{sum(candidate[left] == candidate[right] for candidate in stability_partitions) / restarts:.3f}",
                "selected_algorithmic_partition": algorithmic_partition[left]
                == algorithmic_partition[right],
                "reviewed_partition": partition[left] == partition[right],
            }
            for left, right in PARTITION_STABILITY_PAIRS
        ),
    )

    degrees = {author: sum(adjacency[author].values()) for author in adjacency}
    membership_rows: list[dict[str, object]] = []
    for author in sorted(
        partition,
        key=lambda item: (
            summary_by_community[partition[item]].group_id,
            -mentions[item],
            item,
        ),
    ):
        summary = summary_by_community[partition[author]]
        membership_rows.append(
            {
                "group_id": summary.group_id,
                "group_label": summary.label,
                "canonical_author": author,
                "paper_mentions": mentions[author],
                "weighted_degree": f"{degrees[author]:.6f}",
            }
        )
    write_csv(
        audit_dir / "group_membership.csv",
        [
            "group_id",
            "group_label",
            "canonical_author",
            "paper_mentions",
            "weighted_degree",
        ],
        membership_rows,
    )

    paper_rows: list[dict[str, object]] = []
    for paper_index, paper in enumerate(papers):
        summary = summary_by_community[paper_community[paper_index]]
        paper_rows.append(
            {
                "csv_row": paper.row_number,
                "doi": paper.doi,
                "title": paper.title,
                "year": paper.year,
                "group_id": summary.group_id,
                "group_label": summary.label,
                "assignment_lead_author": paper_lead[paper_index],
                "canonical_authors": "; ".join(paper.authors),
                "repo_analysis_tags": paper.raw_tags,
                "themes": "; ".join(theme for theme in THEME_ORDER if theme in paper.themes),
            }
        )
    write_csv(
        audit_dir / "paper_assignments.csv",
        [
            "csv_row",
            "doi",
            "title",
            "year",
            "group_id",
            "group_label",
            "assignment_lead_author",
            "canonical_authors",
            "repo_analysis_tags",
            "themes",
        ],
        paper_rows,
    )

    contribution_rows: list[dict[str, object]] = []
    for summary in summaries:
        row: dict[str, object] = {
            "group_id": summary.group_id,
            "group_label": summary.label,
            "number_of_authors": len(summary.members),
            "number_of_papers": summary.paper_count,
            "included_in_tex": summary.group_id in {f"G{rank:02d}" for rank in range(1, top_groups + 1)},
        }
        row.update({theme: summary.counts[theme] for theme in THEME_ORDER})
        contribution_rows.append(row)
    write_csv(
        audit_dir / "group_contributions.csv",
        [
            "group_id",
            "group_label",
            "number_of_authors",
            "number_of_papers",
            *THEME_ORDER,
            "included_in_tex",
        ],
        contribution_rows,
    )

    unresolved = sum(
        record.method == "unresolved_ambiguous_initial" for record in alias_records
    )
    methodology = f"""# Research-group table methodology

- Input papers: {len(papers)}
- Raw author strings: {len(alias_records)}
- Canonical authors: {len(set(record.canonical_author for record in alias_records))}
- Ambiguous initial-only names intentionally left unresolved: {unresolved}
- Non-author affiliation strings excluded: {len(EXCLUDED_NON_AUTHOR_STRINGS)}
- Coauthorship edge weighting: `1 / (authors_on_paper - 1)` per author pair
- Community method: weighted modularity local moving with {resolution:.2f} resolution
- Selected restart seed: {chosen_seed}
- Partition stability was audited across seeds {base_seed}--{base_seed + restarts - 1}; see `partition_stability.csv`
- Algorithmic partition modularity at selected resolution: {algorithmic_modularity:.6f}
- Reviewed group merges: Zheng Zheng--Kai-Yuan Cai and Paulo Maciel--Matheus Torquato communities
- Reviewed group split: Rivalino Matias and satellite coauthors whose corpus papers all include Matias
- Constrained partition modularity: {constrained_modularity:.6f}
- Paper assignment: Matias-authored papers use the reviewed Matias anchor group; all other papers use the community of the most prolific coauthor, with weighted degree and name as tie-breakers
- TeX rows: top {top_groups} groups by mutually exclusive paper assignment count
- Theme counts: one count per paper-theme pair; a multi-label paper can appear in several theme columns
- Sigma: unique papers assigned to the displayed groups
"""
    (audit_dir / "README.md").write_text(methodology, encoding="utf-8")


def validate_outputs(
    papers: list[Paper],
    summaries: list[GroupSummary],
    top_groups: list[GroupSummary],
    tex: str,
) -> None:
    assigned_indices = [index for summary in summaries for index in summary.paper_indices]
    if len(assigned_indices) != len(papers) or len(set(assigned_indices)) != len(papers):
        raise AssertionError("Every paper must be assigned to exactly one research group")
    expected_themes = set(THEME_ORDER)
    observed_themes = set().union(*(paper.themes for paper in papers))
    if observed_themes != expected_themes:
        raise AssertionError(
            f"Theme coverage mismatch: expected {expected_themes}, observed {observed_themes}"
        )
    for summary in summaries:
        for theme in THEME_ORDER:
            recomputed = sum(
                theme in papers[paper_index].themes
                for paper_index in summary.paper_indices
            )
            if recomputed != summary.counts[theme]:
                raise AssertionError(
                    f"Count mismatch for {summary.group_id} / {theme}: "
                    f"{summary.counts[theme]} != {recomputed}"
                )
    if tex.count(r"\begin{table*}") != 1 or tex.count(r"\end{table*}") != 1:
        raise AssertionError("Generated TeX table environment is unbalanced")
    if len(top_groups) == 0:
        raise AssertionError("At least one group must be displayed")


def main() -> None:
    args = parse_args()
    if args.top_groups < 1:
        raise ValueError("--top-groups must be at least 1")
    if args.resolution <= 0:
        raise ValueError("--resolution must be positive")

    rows = read_raw_rows(args.input)
    raw_occurrences = Counter(
        author
        for row in rows
        for author in effective_authors(row)
    )
    mapping, alias_records = resolve_author_aliases(raw_occurrences)
    papers = build_papers(rows, mapping)
    adjacency, mentions, pair_papers = build_coauthor_graph(papers)
    algorithmic_partition, algorithmic_modularity, chosen_seed = select_partition(
        adjacency,
        resolution=args.resolution,
        seed=args.seed,
        restarts=args.restarts,
    )
    partition = apply_reviewed_group_constraints(
        algorithmic_partition, adjacency, mentions, pair_papers
    )
    constrained_modularity = modularity_score(adjacency, partition, args.resolution)
    summaries, paper_community, paper_lead = summarize_groups(
        papers, partition, adjacency, mentions, pair_papers
    )
    top_groups = summaries[: min(args.top_groups, len(summaries))]
    tex = render_tex(top_groups, args.input.name)
    validate_outputs(papers, summaries, top_groups, tex)

    args.tex_output.parent.mkdir(parents=True, exist_ok=True)
    args.tex_output.write_text(tex, encoding="utf-8")
    write_audit_outputs(
        args.audit_dir,
        rows,
        alias_records,
        papers,
        summaries,
        paper_community,
        paper_lead,
        partition,
        algorithmic_partition,
        adjacency,
        mentions,
        pair_papers,
        algorithmic_modularity,
        constrained_modularity,
        args.resolution,
        chosen_seed,
        args.seed,
        args.restarts,
        len(top_groups),
    )

    print(
        f"Generated {args.tex_output}\n"
        f"Papers: {len(papers)}; raw names: {len(raw_occurrences)}; "
        f"canonical authors: {len(mentions)}; communities: {len(summaries)}\n"
        f"Resolution: {args.resolution:.2f}; algorithmic modularity: "
        f"{algorithmic_modularity:.6f}; constrained modularity: "
        f"{constrained_modularity:.6f}; "
        f"selected seed: {chosen_seed}\n"
        f"Top groups: "
        + ", ".join(
            f"{summary.label}={summary.paper_count}" for summary in top_groups
        )
    )


if __name__ == "__main__":
    main()
