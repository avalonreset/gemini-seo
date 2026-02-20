#!/usr/bin/env python3
"""
Deterministic analyzer and planner for the seo-programmatic skill.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlparse, urlunparse

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
QUALITY_THRESHOLDS = {
    "review_warning_pages": 100,
    "review_hard_stop_pages": 500,
    "minimum_review_rate": 0.05,
    "hard_stop_unique_pct": 30.0,
}

PATTERN_PRESETS: dict[str, dict[str, Any]] = {
    "tool": {
        "base_path": "/tools",
        "fields": [
            ("name", "Tool name used in URL/title/H1"),
            ("category", "Category for hub routing and related links"),
            ("primary_use_case", "Intent-specific usage context"),
            ("last_updated", "Data freshness field"),
        ],
        "url_template": "/tools/{slug}",
    },
    "location-service": {
        "base_path": "/locations",
        "fields": [
            ("city", "City or area value"),
            ("service", "Service offering"),
            ("proof_point", "Local proof signal or credential"),
            ("last_updated", "Refresh timestamp"),
        ],
        "url_template": "/{city}/{service}",
    },
    "integration": {
        "base_path": "/integrations",
        "fields": [
            ("integration_name", "Integrated platform name"),
            ("supported_features", "Feature matrix or compatibility data"),
            ("setup_steps", "Unique implementation guidance"),
            ("last_updated", "Release freshness"),
        ],
        "url_template": "/integrations/{slug}",
    },
    "glossary": {
        "base_path": "/glossary",
        "fields": [
            ("term", "Canonical glossary term"),
            ("definition", "Primary explanation text"),
            ("examples", "Concrete usage examples"),
            ("related_terms", "Graph relationship metadata"),
        ],
        "url_template": "/glossary/{slug}",
    },
    "template": {
        "base_path": "/templates",
        "fields": [
            ("template_name", "Template name and target role"),
            ("format", "Delivery format"),
            ("use_case", "Problem scenario"),
            ("last_updated", "Revision freshness"),
        ],
        "url_template": "/templates/{slug}",
    },
    "custom": {
        "base_path": "/pages",
        "fields": [
            ("primary_entity", "Primary programmatic entity"),
            ("secondary_attribute", "Differentiator attribute"),
            ("proof_point", "Unique evidence field"),
            ("last_updated", "Data recency"),
        ],
        "url_template": "/pages/{slug}",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Programmatic SEO analyzer and planner.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze dataset and programmatic page inventory.")
    analyze.add_argument("--dataset-file", required=True, help="CSV or JSON dataset used to generate pages.")
    analyze.add_argument("--pages-file", help="Optional CSV or JSON page inventory.")
    analyze.add_argument("--sample-size", type=int, default=300, help="Row sample size for near-duplicate checks.")
    analyze.add_argument(
        "--minimum-unique-pct",
        dest="analyze_minimum_unique_pct",
        type=float,
        default=40.0,
        help="Minimum unique content percent.",
    )
    analyze.add_argument(
        "--minimum-word-count",
        dest="analyze_minimum_word_count",
        type=int,
        default=300,
        help="Minimum word count threshold.",
    )
    analyze.add_argument("--justified-scale", action="store_true", help="Mark high-volume rollout as approved.")
    analyze.add_argument("--output-dir", default="seo-programmatic-output", help="Directory for output artifacts.")

    plan = subparsers.add_parser("plan", help="Generate a programmatic rollout blueprint.")
    plan.add_argument("--plan-file", help="Optional JSON plan input; CLI args override file values.")
    plan.add_argument("--project-name", help="Project name.")
    plan.add_argument(
        "--pattern",
        choices=sorted(PATTERN_PRESETS.keys()),
        help="Programmatic pattern type.",
    )
    plan.add_argument("--entity-singular", help="Entity singular label.")
    plan.add_argument("--entity-plural", help="Entity plural label.")
    plan.add_argument("--base-path", help="Base path for generated pages.")
    plan.add_argument("--expected-pages", type=int, help="Expected page count.")
    plan.add_argument("--batch-size", type=int, help="Rollout batch size.")
    plan.add_argument(
        "--minimum-unique-pct",
        dest="plan_minimum_unique_pct",
        type=float,
        default=None,
        help="Minimum unique content percent.",
    )
    plan.add_argument(
        "--minimum-word-count",
        dest="plan_minimum_word_count",
        type=int,
        default=None,
        help="Minimum word count threshold.",
    )
    plan.add_argument("--output-dir", default="seo-programmatic-output", help="Directory for output artifacts.")
    return parser.parse_args()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_div(num: float, den: float) -> float:
    return (num / den) if den else 0.0


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def read_records(path_value: str) -> list[dict[str, Any]]:
    path = Path(path_value).resolve()
    if not path.exists():
        raise ValueError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]
    if suffix == ".json":
        payload = load_json(path)
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("records", "rows", "items", "pages", "data"):
                maybe = payload.get(key)
                if isinstance(maybe, list):
                    return [dict(item) for item in maybe if isinstance(item, dict)]
            return [dict(payload)]
        raise ValueError(f"Unsupported JSON structure in {path}")

    raise ValueError("Supported file types: .csv, .json")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, sort_keys=True)


def normalize_url(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path or "/"
    netloc = parsed.netloc.lower()
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def compare_url_key(raw: str | None) -> str | None:
    if not raw:
        return None
    normalized = normalize_url(raw)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def map_record_keys(record: dict[str, Any]) -> dict[str, Any]:
    return {str(k).strip().lower(): v for k, v in record.items()}


def pick_field(record: dict[str, Any], keys: list[str]) -> Any:
    mapped = map_record_keys(record)
    for key in keys:
        if key in mapped:
            return mapped[key]
    return None


def row_signature(record: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    normalized = []
    for key in sorted(record.keys()):
        text = normalize_text(record.get(key))
        if text:
            normalized.append((key.lower(), text.lower()))
    return tuple(normalized)


def row_token_set(record: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key, value in record.items():
        text = normalize_text(value).lower()
        if not text:
            continue
        truncated = text[:80]
        tokens.add(f"{key.lower()}={truncated}")
    return tokens


def analyze_dataset(records: list[dict[str, Any]], sample_size: int) -> dict[str, Any]:
    row_count = len(records)
    columns = sorted({str(key).strip() for row in records for key in row.keys() if str(key).strip()})
    missing_by_column = {column: 0 for column in columns}
    sparse_rows = 0

    for row in records:
        missing = 0
        for column in columns:
            text = normalize_text(row.get(column))
            if not text:
                missing += 1
                missing_by_column[column] += 1
        if columns and safe_div(missing, len(columns)) > 0.5:
            sparse_rows += 1

    uniqueness_by_column: dict[str, float] = {}
    for column in columns:
        values = [normalize_text(row.get(column)).lower() for row in records]
        non_empty = [value for value in values if value]
        distinct = len(set(non_empty))
        uniqueness_by_column[column] = round(safe_div(distinct, row_count) * 100, 2) if row_count else 0.0

    signatures = Counter(row_signature(row) for row in records)
    exact_duplicate_rows = sum(count - 1 for count in signatures.values() if count > 1)

    sample = records[: max(0, sample_size)]
    token_rows = [row_token_set(row) for row in sample]
    near_duplicate_pairs = 0
    near_duplicate_examples: list[tuple[int, int, float]] = []
    for left in range(len(token_rows)):
        a = token_rows[left]
        if not a:
            continue
        for right in range(left + 1, len(token_rows)):
            b = token_rows[right]
            if not b:
                continue
            union = len(a | b)
            if not union:
                continue
            jaccard = safe_div(len(a & b), union)
            if jaccard >= 0.8:
                near_duplicate_pairs += 1
                if len(near_duplicate_examples) < 5:
                    near_duplicate_examples.append((left + 1, right + 1, round(jaccard, 3)))

    low_uniqueness_columns = [
        column
        for column, ratio in uniqueness_by_column.items()
        if ratio <= 10.0 and column.lower() not in {"country", "language", "region"}
    ]

    return {
        "row_count": row_count,
        "columns": columns,
        "missing_by_column": missing_by_column,
        "sparse_rows": sparse_rows,
        "sparse_row_rate": safe_div(sparse_rows, row_count),
        "uniqueness_by_column": uniqueness_by_column,
        "low_uniqueness_columns": low_uniqueness_columns,
        "exact_duplicate_rows": exact_duplicate_rows,
        "exact_duplicate_rate": safe_div(exact_duplicate_rows, row_count),
        "near_duplicate_pairs": near_duplicate_pairs,
        "near_duplicate_examples": near_duplicate_examples,
    }


def parse_pages(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    parsed: list[dict[str, Any]] = []
    warnings: list[str] = []
    for idx, record in enumerate(records, start=1):
        url_raw = normalize_text(pick_field(record, ["url", "page_url", "page", "loc"]))
        if not url_raw:
            warnings.append(f"Row {idx}: missing URL; skipped")
            continue

        normalized = normalize_url(url_raw)
        if not normalized:
            warnings.append(f"Row {idx}: invalid URL '{url_raw}'; kept as invalid")

        canonical_raw = normalize_text(pick_field(record, ["canonical_url", "canonical", "rel_canonical"]))
        canonical_norm = normalize_url(canonical_raw) if canonical_raw else None

        unique_pct = to_float(
            pick_field(record, ["unique_content_pct", "uniqueness_pct", "unique_pct", "unique_percent"])
        )
        if unique_pct is not None and 0.0 <= unique_pct <= 1.0:
            unique_pct *= 100.0

        reviewed = to_bool(pick_field(record, ["reviewed", "content_reviewed", "qa_reviewed"]))
        reviewed = reviewed if reviewed is not None else False

        noindex_value = to_bool(pick_field(record, ["noindex"]))
        indexable_value = to_bool(pick_field(record, ["indexable", "is_indexable"]))
        if indexable_value is None:
            indexable = not bool(noindex_value)
        else:
            indexable = indexable_value

        parsed.append(
            {
                "url_raw": url_raw,
                "url": normalized,
                "url_key": compare_url_key(url_raw),
                "canonical_raw": canonical_raw,
                "canonical": canonical_norm,
                "canonical_key": compare_url_key(canonical_raw) if canonical_raw else None,
                "word_count": to_int(pick_field(record, ["word_count", "words", "content_word_count"])),
                "unique_pct": unique_pct,
                "reviewed": reviewed,
                "indexable": indexable,
                "internal_links": to_int(pick_field(record, ["internal_links", "inlinks"])),
                "status_code": to_int(pick_field(record, ["status_code", "status"])),
            }
        )

    return parsed, warnings


def analyze_pages(
    pages: list[dict[str, Any]],
    minimum_unique_pct: float,
    minimum_word_count: int,
) -> dict[str, Any]:
    total = len(pages)
    metrics: dict[str, Any] = {
        "total_pages": total,
        "invalid_urls": 0,
        "duplicate_urls": 0,
        "duplicate_slugs": 0,
        "query_urls": 0,
        "long_urls": 0,
        "non_hyphen_lower_urls": 0,
        "low_unique_pages": 0,
        "very_low_unique_pages": 0,
        "low_word_pages": 0,
        "reviewed_pages": 0,
        "canonical_mismatches": 0,
        "indexable_low_quality": 0,
        "weak_internal_link_pages": 0,
        "missing_internal_link_data": 0,
        "non_200_pages": 0,
        "missing_quality_data": 0,
        "examples": defaultdict(list),
    }

    seen_urls: Counter[str] = Counter()
    seen_slugs: Counter[str] = Counter()
    url_pattern = re.compile(r"^/[a-z0-9/-]*$")

    for page in pages:
        url = page["url"]
        if page["reviewed"]:
            metrics["reviewed_pages"] += 1

        if not url:
            metrics["invalid_urls"] += 1
            if len(metrics["examples"]["invalid_urls"]) < 5:
                metrics["examples"]["invalid_urls"].append(page["url_raw"])
            continue

        key = page["url_key"]
        if key:
            seen_urls[key] += 1

        parsed = urlparse(url)
        if parsed.query:
            metrics["query_urls"] += 1
            if len(metrics["examples"]["query_urls"]) < 5:
                metrics["examples"]["query_urls"].append(url)

        if len(url) > 100:
            metrics["long_urls"] += 1
            if len(metrics["examples"]["long_urls"]) < 5:
                metrics["examples"]["long_urls"].append(url)

        path = parsed.path or "/"
        if not url_pattern.fullmatch(path):
            metrics["non_hyphen_lower_urls"] += 1
            if len(metrics["examples"]["non_hyphen_lower_urls"]) < 5:
                metrics["examples"]["non_hyphen_lower_urls"].append(url)

        slug = path.rstrip("/").split("/")[-1]
        if slug:
            seen_slugs[slug] += 1

        unique_pct = page["unique_pct"]
        word_count = page["word_count"]
        if unique_pct is None or word_count is None:
            metrics["missing_quality_data"] += 1
        else:
            if unique_pct < minimum_unique_pct:
                metrics["low_unique_pages"] += 1
                if len(metrics["examples"]["low_unique_pages"]) < 5:
                    metrics["examples"]["low_unique_pages"].append(url)
            if unique_pct < QUALITY_THRESHOLDS["hard_stop_unique_pct"]:
                metrics["very_low_unique_pages"] += 1
                if len(metrics["examples"]["very_low_unique_pages"]) < 5:
                    metrics["examples"]["very_low_unique_pages"].append(url)
            if word_count < minimum_word_count:
                metrics["low_word_pages"] += 1
                if len(metrics["examples"]["low_word_pages"]) < 5:
                    metrics["examples"]["low_word_pages"].append(url)

            if page["indexable"] and (
                unique_pct < minimum_unique_pct or word_count < minimum_word_count
            ):
                metrics["indexable_low_quality"] += 1
                if len(metrics["examples"]["indexable_low_quality"]) < 5:
                    metrics["examples"]["indexable_low_quality"].append(url)

        canonical_key = page["canonical_key"]
        if canonical_key and key and canonical_key != key:
            metrics["canonical_mismatches"] += 1
            if len(metrics["examples"]["canonical_mismatches"]) < 5:
                metrics["examples"]["canonical_mismatches"].append(f"{url} -> {page['canonical_raw']}")

        links = page["internal_links"]
        if links is None:
            metrics["missing_internal_link_data"] += 1
        elif links < 3:
            metrics["weak_internal_link_pages"] += 1
            if len(metrics["examples"]["weak_internal_link_pages"]) < 5:
                metrics["examples"]["weak_internal_link_pages"].append(url)

        status_code = page["status_code"]
        if status_code is not None and status_code not in {200, 301, 302}:
            metrics["non_200_pages"] += 1
            if len(metrics["examples"]["non_200_pages"]) < 5:
                metrics["examples"]["non_200_pages"].append(f"{url} ({status_code})")

    metrics["duplicate_urls"] = sum(count - 1 for count in seen_urls.values() if count > 1)
    metrics["duplicate_slugs"] = sum(count - 1 for count in seen_slugs.values() if count > 1)
    metrics["review_rate"] = safe_div(metrics["reviewed_pages"], total)
    metrics["low_unique_rate"] = safe_div(metrics["low_unique_pages"], total)
    metrics["very_low_unique_rate"] = safe_div(metrics["very_low_unique_pages"], total)
    metrics["low_word_rate"] = safe_div(metrics["low_word_pages"], total)
    metrics["indexable_low_quality_rate"] = safe_div(metrics["indexable_low_quality"], total)
    metrics["weak_internal_link_rate"] = safe_div(metrics["weak_internal_link_pages"], total)
    metrics["canonical_mismatch_rate"] = safe_div(metrics["canonical_mismatches"], total)
    metrics["invalid_url_rate"] = safe_div(metrics["invalid_urls"], total)
    return metrics


def add_issue(issues: list[dict[str, str]], severity: str, title: str, detail: str) -> None:
    issues.append({"severity": severity, "title": title, "detail": detail})


def score_card(dataset: dict[str, Any], pages: dict[str, Any], projected_pages: int, hard_stop_scale: bool) -> dict[str, Any]:
    data_quality = 100.0
    if dataset["row_count"] == 0:
        data_quality = 0.0
    else:
        data_quality -= dataset["sparse_row_rate"] * 35
        data_quality -= dataset["exact_duplicate_rate"] * 35
        data_quality -= min(20.0, len(dataset["low_uniqueness_columns"]) * 4.0)
        if dataset["near_duplicate_pairs"] > 0:
            data_quality -= 10.0
    data_quality = clamp(data_quality, 0.0, 100.0)

    if pages["total_pages"] == 0:
        template_uniqueness = 65.0
        url_structure = 70.0
        internal_linking = 65.0
        thin_content_risk = 65.0
        index_management = 65.0
    else:
        template_uniqueness = 100.0
        template_uniqueness -= pages["low_unique_rate"] * 70
        template_uniqueness -= pages["very_low_unique_rate"] * 40
        template_uniqueness -= pages["low_word_rate"] * 30
        template_uniqueness -= safe_div(pages["missing_quality_data"], pages["total_pages"]) * 20

        url_structure = 100.0
        url_structure -= pages["invalid_url_rate"] * 80
        url_structure -= min(25.0, pages["duplicate_urls"] * 5.0)
        url_structure -= min(20.0, pages["duplicate_slugs"] * 3.0)
        url_structure -= safe_div(pages["query_urls"], pages["total_pages"]) * 20
        url_structure -= safe_div(pages["long_urls"], pages["total_pages"]) * 20
        url_structure -= safe_div(pages["non_hyphen_lower_urls"], pages["total_pages"]) * 20

        internal_linking = 100.0
        internal_linking -= pages["weak_internal_link_rate"] * 70
        internal_linking -= safe_div(pages["missing_internal_link_data"], pages["total_pages"]) * 25

        thin_content_risk = 100.0
        thin_content_risk -= pages["low_unique_rate"] * 80
        thin_content_risk -= pages["low_word_rate"] * 50
        thin_content_risk -= pages["indexable_low_quality_rate"] * 60

        index_management = 100.0
        index_management -= pages["canonical_mismatch_rate"] * 70
        index_management -= pages["indexable_low_quality_rate"] * 70
        if projected_pages >= QUALITY_THRESHOLDS["review_warning_pages"] and pages["review_rate"] < QUALITY_THRESHOLDS["minimum_review_rate"]:
            index_management -= 10
        if hard_stop_scale:
            index_management -= 10

    categories = {
        "Data Quality": clamp(data_quality, 0.0, 100.0),
        "Template Uniqueness": clamp(template_uniqueness, 0.0, 100.0),
        "URL Structure": clamp(url_structure, 0.0, 100.0),
        "Internal Linking": clamp(internal_linking, 0.0, 100.0),
        "Thin Content Risk": clamp(thin_content_risk, 0.0, 100.0),
        "Index Management": clamp(index_management, 0.0, 100.0),
    }
    overall = round(mean(categories.values()), 1)
    return {"overall": overall, "categories": {k: round(v, 1) for k, v in categories.items()}}


def status_for_score(score: float) -> str:
    if score >= 85:
        return "✅"
    if score >= 70:
        return "⚠️"
    return "❌"


def build_analyze_issues(
    dataset: dict[str, Any],
    pages: dict[str, Any],
    projected_pages: int,
    justified_scale: bool,
    minimum_unique_pct: float,
    minimum_word_count: int,
    page_parse_warnings: list[str],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    issues: list[dict[str, str]] = []

    review_warning = projected_pages >= QUALITY_THRESHOLDS["review_warning_pages"] and pages["review_rate"] < QUALITY_THRESHOLDS["minimum_review_rate"]
    hard_stop_scale = projected_pages >= QUALITY_THRESHOLDS["review_hard_stop_pages"] and not justified_scale
    hard_stop_uniqueness = pages["very_low_unique_rate"] >= 0.3 and pages["total_pages"] >= 100

    if dataset["row_count"] == 0:
        add_issue(issues, "Critical", "Empty data source", "No records found. Programmatic generation cannot proceed.")
    if dataset["exact_duplicate_rate"] > 0.2:
        add_issue(
            issues,
            "High",
            "High duplicate record ratio",
            f"Exact duplicate rows are {round(dataset['exact_duplicate_rate'] * 100, 1)}% of dataset.",
        )
    if dataset["sparse_row_rate"] > 0.3:
        add_issue(
            issues,
            "High",
            "Sparse data rows",
            f"{round(dataset['sparse_row_rate'] * 100, 1)}% of rows are missing more than half of fields.",
        )
    if len(dataset["low_uniqueness_columns"]) >= 4:
        add_issue(
            issues,
            "Medium",
            "Low-differentiation columns",
            f"{len(dataset['low_uniqueness_columns'])} columns have <=10% uniqueness. Risk of templated duplication.",
        )
    if dataset["near_duplicate_pairs"] > 0:
        add_issue(
            issues,
            "Medium",
            "Near-duplicate records detected",
            f"Sample check found {dataset['near_duplicate_pairs']} near-duplicate row pairs (>=80% overlap).",
        )

    if pages["total_pages"] > 0:
        if pages["invalid_urls"] > 0:
            add_issue(issues, "High", "Invalid URLs in inventory", f"{pages['invalid_urls']} pages have invalid URLs.")
        if pages["duplicate_urls"] > 0:
            add_issue(issues, "High", "Duplicate URLs", f"{pages['duplicate_urls']} duplicate canonical URL instances detected.")
        if pages["duplicate_slugs"] > 0:
            add_issue(issues, "High", "Duplicate slugs", f"{pages['duplicate_slugs']} duplicate end-slugs detected.")
        if pages["canonical_mismatches"] > 0:
            add_issue(
                issues,
                "High",
                "Canonical mismatches",
                f"{pages['canonical_mismatches']} pages canonicalize to a different URL than themselves.",
            )
        if pages["indexable_low_quality"] > 0:
            severity = "Critical" if pages["indexable_low_quality_rate"] >= 0.25 else "High"
            add_issue(
                issues,
                severity,
                "Indexable low-quality pages",
                (
                    f"{pages['indexable_low_quality']} indexable pages fall below uniqueness ({minimum_unique_pct}%) "
                    f"or word-count ({minimum_word_count}) thresholds."
                ),
            )
        if pages["low_unique_pages"] > 0:
            severity = "High" if pages["low_unique_rate"] >= 0.2 else "Medium"
            add_issue(
                issues,
                severity,
                "Thin uniqueness risk",
                f"{pages['low_unique_pages']} pages are below {minimum_unique_pct}% uniqueness.",
            )
        if pages["low_word_pages"] > 0:
            add_issue(
                issues,
                "Medium",
                "Low word-count risk",
                f"{pages['low_word_pages']} pages are below {minimum_word_count} words.",
            )
        if pages["weak_internal_link_rate"] > 0.4:
            add_issue(
                issues,
                "Medium",
                "Weak internal linking density",
                f"{round(pages['weak_internal_link_rate'] * 100, 1)}% of pages have fewer than 3 internal links.",
            )
        if pages["non_200_pages"] > 0:
            add_issue(
                issues,
                "Medium",
                "Non-200/30x status coverage",
                f"{pages['non_200_pages']} pages report status codes outside 200/301/302.",
            )

    if review_warning:
        add_issue(
            issues,
            "High",
            "Review sample below minimum at scale",
            (
                f"Projected pages={projected_pages} and review rate={round(pages['review_rate'] * 100, 2)}%, "
                f"below {QUALITY_THRESHOLDS['minimum_review_rate'] * 100:.0f}% minimum."
            ),
        )
    if hard_stop_scale:
        add_issue(
            issues,
            "Critical",
            "Hard stop: high-volume rollout without approval",
            (
                f"Projected pages={projected_pages} exceeds {QUALITY_THRESHOLDS['review_hard_stop_pages']} "
                "without `--justified-scale`."
            ),
        )
    if hard_stop_uniqueness:
        add_issue(
            issues,
            "Critical",
            "Hard stop: very low uniqueness concentration",
            (
                f"{round(pages['very_low_unique_rate'] * 100, 1)}% of pages are below "
                f"{QUALITY_THRESHOLDS['hard_stop_unique_pct']}% uniqueness."
            ),
        )

    if page_parse_warnings:
        add_issue(
            issues,
            "Medium",
            "Input normalization warnings",
            f"{len(page_parse_warnings)} page rows had missing/invalid fields during parsing.",
        )

    gate_status = {
        "review_warning_triggered": review_warning,
        "hard_stop_scale_triggered": hard_stop_scale,
        "hard_stop_uniqueness_triggered": hard_stop_uniqueness,
    }
    return sorted(issues, key=lambda issue: SEVERITY_ORDER[issue["severity"]]), gate_status


def render_analyze_report(
    score: dict[str, Any],
    dataset: dict[str, Any],
    pages: dict[str, Any],
    projected_pages: int,
    issues: list[dict[str, str]],
    gate_status: dict[str, bool],
    minimum_unique_pct: float,
    minimum_word_count: int,
) -> str:
    summary_rows = []
    for name, category_score in score["categories"].items():
        summary_rows.append(f"| {name} | {status_for_score(category_score)} | {category_score}/100 |")

    issues_by_severity: dict[str, list[dict[str, str]]] = defaultdict(list)
    for issue in issues:
        issues_by_severity[issue["severity"]].append(issue)

    issue_sections = []
    for severity in ("Critical", "High", "Medium", "Low", "Info"):
        bucket = issues_by_severity.get(severity, [])
        if not bucket:
            continue
        issue_sections.append(f"### {severity} Issues")
        for item in bucket:
            issue_sections.append(f"- **{item['title']}**: {item['detail']}")
        issue_sections.append("")

    if not issue_sections:
        issue_sections = ["No blocking issues detected in current input sample.", ""]

    recommendation_lines = [
        "- Enforce staged rollouts in batches of 50-100 pages with QA sampling before expansion.",
        f"- Keep pages below {minimum_unique_pct}% uniqueness or {minimum_word_count} words as noindex until remediated.",
        "- Require explicit pre-publish review checkpoints on representative page samples.",
        "- Re-run this audit after each major template change or dataset refresh.",
    ]

    return (
        "# Programmatic SEO Report\n\n"
        f"- Generated: {datetime.now(UTC).isoformat()}\n"
        f"- Programmatic SEO Score: **{score['overall']}/100**\n"
        f"- Projected Page Volume: **{projected_pages}**\n\n"
        "## Assessment Summary\n\n"
        "| Category | Status | Score |\n"
        "|---|---|---|\n"
        f"{chr(10).join(summary_rows)}\n\n"
        "## Data Snapshot\n\n"
        f"- Dataset rows: **{dataset['row_count']}**\n"
        f"- Dataset columns: **{len(dataset['columns'])}**\n"
        f"- Exact duplicate rows: **{dataset['exact_duplicate_rows']}**\n"
        f"- Near-duplicate pairs (sample): **{dataset['near_duplicate_pairs']}**\n"
        f"- Sparse rows (>50% missing fields): **{dataset['sparse_rows']}**\n"
        f"- Pages analyzed: **{pages['total_pages']}**\n"
        f"- Pages reviewed: **{pages['reviewed_pages']}** ({round(pages['review_rate'] * 100, 2)}%)\n"
        f"- Low uniqueness pages (<{minimum_unique_pct}%): **{pages['low_unique_pages']}**\n"
        f"- Very low uniqueness pages (<{QUALITY_THRESHOLDS['hard_stop_unique_pct']}%): **{pages['very_low_unique_pages']}**\n"
        f"- Low word-count pages (<{minimum_word_count}): **{pages['low_word_pages']}**\n"
        f"- Indexable low-quality pages: **{pages['indexable_low_quality']}**\n\n"
        "## Quality Gate Outcomes\n\n"
        f"- Review warning triggered (100+ pages with low sample): **{gate_status['review_warning_triggered']}**\n"
        f"- Hard stop triggered (500+ pages without approval): **{gate_status['hard_stop_scale_triggered']}**\n"
        f"- Hard stop triggered (very low uniqueness concentration): **{gate_status['hard_stop_uniqueness_triggered']}**\n\n"
        "## Findings\n\n"
        f"{chr(10).join(issue_sections)}\n"
        "## Recommendations\n\n"
        f"{chr(10).join(recommendation_lines)}\n"
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2))


def sanitize_csv_cell(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return text
    if text[0] in {"=", "+", "-", "@", "\t"}:
        # Prevent spreadsheet formula execution when opening exported CSV in Excel/Sheets.
        return "'" + text
    return text


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: sanitize_csv_cell(row.get(key, "")) for key in fieldnames})


def build_plan_config(args: argparse.Namespace) -> dict[str, Any]:
    source = {}
    if args.plan_file:
        payload = load_json(Path(args.plan_file).resolve())
        if not isinstance(payload, dict):
            raise ValueError("plan-file JSON root must be an object")
        source = payload

    pattern = (args.pattern or source.get("pattern") or "custom").strip().lower()
    if pattern not in PATTERN_PRESETS:
        raise ValueError(f"Unsupported pattern: {pattern}")

    project_name = (args.project_name or source.get("project_name") or "").strip()
    if not project_name:
        raise ValueError("project-name is required (or provide project_name in plan-file)")

    expected_pages_raw = args.expected_pages if args.expected_pages is not None else source.get("expected_pages", 250)
    batch_size_raw = args.batch_size if args.batch_size is not None else source.get("batch_size", 100)

    try:
        expected_pages = int(expected_pages_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected-pages must be an integer") from exc
    try:
        batch_size = int(batch_size_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("batch-size must be an integer") from exc

    expected_pages = max(1, expected_pages)
    batch_size = max(1, batch_size)

    minimum_unique_raw = (
        args.plan_minimum_unique_pct
        if args.plan_minimum_unique_pct is not None
        else source.get("minimum_unique_pct", 40.0)
    )
    minimum_word_raw = (
        args.plan_minimum_word_count
        if args.plan_minimum_word_count is not None
        else source.get("minimum_word_count", 300)
    )
    try:
        minimum_unique = float(minimum_unique_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("minimum-unique-pct must be numeric") from exc
    try:
        minimum_word = int(minimum_word_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("minimum-word-count must be an integer") from exc
    minimum_unique = clamp(minimum_unique, 0.0, 100.0)
    minimum_word = max(1, minimum_word)

    base_path = (args.base_path or source.get("base_path") or PATTERN_PRESETS[pattern]["base_path"]).strip()
    if not base_path.startswith("/"):
        base_path = f"/{base_path}"
    base_path = "/" + base_path.strip("/")

    entity_singular = (args.entity_singular or source.get("entity_singular") or "entity").strip()
    entity_plural = (args.entity_plural or source.get("entity_plural") or f"{entity_singular}s").strip()

    return {
        "project_name": project_name,
        "pattern": pattern,
        "entity_singular": entity_singular,
        "entity_plural": entity_plural,
        "base_path": base_path,
        "expected_pages": expected_pages,
        "batch_size": batch_size,
        "minimum_unique_pct": minimum_unique,
        "minimum_word_count": minimum_word,
    }


def generate_url_examples(config: dict[str, Any]) -> list[dict[str, str]]:
    pattern = config["pattern"]
    base_path = config["base_path"]
    primary_terms = [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "omega",
        "atlas",
        "nova",
        "pulse",
        "vector",
        "apex",
    ]
    secondary_terms = [
        "starter",
        "pro",
        "enterprise",
        "guide",
        "advanced",
        "best-practices",
        "workflow",
        "integration",
        "examples",
        "playbook",
    ]

    rows: list[dict[str, str]] = []
    for idx in range(10):
        primary = primary_terms[idx]
        secondary = secondary_terms[idx]
        if pattern == "location-service":
            url = f"{base_path}/{primary}/{secondary}".replace("//", "/")
            title = f"{secondary.replace('-', ' ').title()} in {primary.title()}"
            h1 = f"{secondary.replace('-', ' ').title()} - {primary.title()}"
        else:
            slug = f"{primary}-{secondary}"
            url = f"{base_path}/{slug}".replace("//", "/")
            title = f"{config['entity_singular'].title()} {primary.title()} {secondary.replace('-', ' ').title()}"
            h1 = f"{config['entity_singular'].title()} {primary.title()} {secondary.replace('-', ' ').title()}"

        rows.append(
            {
                "pattern": pattern,
                "url": url,
                "title_template": title,
                "h1_template": h1,
                "primary_attribute": primary,
                "secondary_attribute": secondary,
            }
        )
    return rows


def render_plan_blueprint(config: dict[str, Any]) -> str:
    preset = PATTERN_PRESETS[config["pattern"]]
    batches = math.ceil(config["expected_pages"] / config["batch_size"])
    review_sample = max(5, math.ceil(config["batch_size"] * QUALITY_THRESHOLDS["minimum_review_rate"]))

    field_lines = [
        f"| `{name}` | {description} |"
        for name, description in preset["fields"]
    ]

    rollout_rows = []
    remaining = config["expected_pages"]
    for batch_idx in range(1, batches + 1):
        count = min(config["batch_size"], remaining)
        remaining -= count
        rollout_rows.append(
            f"| Batch {batch_idx} | {count} pages | {review_sample} pages | Publish -> indexation check -> QA signoff |"
        )

    return (
        "# Programmatic Blueprint\n\n"
        f"- Project: **{config['project_name']}**\n"
        f"- Pattern: **{config['pattern']}**\n"
        f"- Base Path: **{config['base_path']}**\n"
        f"- Expected Page Volume: **{config['expected_pages']}**\n"
        f"- Batch Size: **{config['batch_size']}**\n\n"
        "## Data Model Requirements\n\n"
        "| Field | Purpose |\n"
        "|---|---|\n"
        f"{chr(10).join(field_lines)}\n\n"
        "## Template Architecture\n\n"
        "- Static blocks: trust signals, navigation, compliance sections, base schema context.\n"
        "- Dynamic blocks: title/H1, entity attributes, comparison sections, supporting facts.\n"
        "- Conditional blocks: sections that render only when source data meets completeness thresholds.\n"
        "- Related-links block: 3-5 links to nearest-neighbor entities by shared attributes.\n\n"
        "## URL Rules\n\n"
        "- Lowercase, hyphenated slugs; no query parameters for canonical pages.\n"
        "- Keep URLs <= 100 characters and enforce unique final slugs.\n"
        "- Canonical must self-reference each generated page URL.\n"
        "- Keep trailing slash strategy consistent globally.\n\n"
        "## Quality Gates\n\n"
        f"- Warning gate: 100+ pages without review sample >= {int(QUALITY_THRESHOLDS['minimum_review_rate'] * 100)}%.\n"
        f"- Hard stop gate: 500+ pages without explicit approval.\n"
        f"- Thin content gate: block indexation below {config['minimum_unique_pct']}% uniqueness.\n"
        f"- Word-count gate: block indexation below {config['minimum_word_count']} words.\n\n"
        "## Rollout Schedule\n\n"
        "| Batch | Volume | QA Sample | Exit Criteria |\n"
        "|---|---|---|---|\n"
        f"{chr(10).join(rollout_rows)}\n\n"
        "## Operational KPIs\n\n"
        "- Indexed page ratio vs intended pages\n"
        "- Low-quality indexable page count\n"
        "- Internal-link coverage compliance\n"
        "- Non-brand query coverage growth\n"
        "- Conversion contribution from programmatic landings\n"
    )


def run_analyze(args: argparse.Namespace) -> int:
    minimum_unique_pct = clamp(float(args.analyze_minimum_unique_pct), 0.0, 100.0)
    minimum_word_count = max(1, int(args.analyze_minimum_word_count))

    dataset_records = read_records(args.dataset_file)
    pages_records = read_records(args.pages_file) if args.pages_file else []

    dataset_metrics = analyze_dataset(dataset_records, max(1, int(args.sample_size)))
    pages_parsed, page_parse_warnings = parse_pages(pages_records)
    pages_metrics = analyze_pages(
        pages_parsed,
        minimum_unique_pct=minimum_unique_pct,
        minimum_word_count=minimum_word_count,
    )

    projected_pages = max(dataset_metrics["row_count"], pages_metrics["total_pages"])
    issues, gate_status = build_analyze_issues(
        dataset_metrics,
        pages_metrics,
        projected_pages=projected_pages,
        justified_scale=bool(args.justified_scale),
        minimum_unique_pct=minimum_unique_pct,
        minimum_word_count=minimum_word_count,
        page_parse_warnings=page_parse_warnings,
    )
    scores = score_card(
        dataset_metrics,
        pages_metrics,
        projected_pages=projected_pages,
        hard_stop_scale=gate_status["hard_stop_scale_triggered"],
    )

    report = render_analyze_report(
        score=scores,
        dataset=dataset_metrics,
        pages=pages_metrics,
        projected_pages=projected_pages,
        issues=issues,
        gate_status=gate_status,
        minimum_unique_pct=minimum_unique_pct,
        minimum_word_count=minimum_word_count,
    )

    output_dir = Path(args.output_dir).resolve()
    report_path = output_dir / "PROGRAMMATIC-SEO-REPORT.md"
    quality_path = output_dir / "QUALITY-GATES.json"
    summary_path = output_dir / "SUMMARY.json"
    write_text(report_path, report)

    quality_payload = {
        "mode": "analyze",
        "thresholds": {
            "review_warning_pages": QUALITY_THRESHOLDS["review_warning_pages"],
            "review_hard_stop_pages": QUALITY_THRESHOLDS["review_hard_stop_pages"],
            "minimum_review_rate": QUALITY_THRESHOLDS["minimum_review_rate"],
            "hard_stop_unique_pct": QUALITY_THRESHOLDS["hard_stop_unique_pct"],
            "minimum_unique_pct": minimum_unique_pct,
            "minimum_word_count": minimum_word_count,
        },
        "observed": {
            "projected_pages": projected_pages,
            "review_rate": round(pages_metrics["review_rate"], 4),
            "low_unique_pages": pages_metrics["low_unique_pages"],
            "very_low_unique_pages": pages_metrics["very_low_unique_pages"],
            "low_word_pages": pages_metrics["low_word_pages"],
            "indexable_low_quality": pages_metrics["indexable_low_quality"],
        },
        "gate_status": gate_status,
    }
    write_json(quality_path, quality_payload)

    severity_counts = Counter(issue["severity"] for issue in issues)
    summary_payload = {
        "mode": "analyze",
        "generated_at": datetime.now(UTC).isoformat(),
        "score": scores["overall"],
        "category_scores": scores["categories"],
        "dataset_rows": dataset_metrics["row_count"],
        "pages_analyzed": pages_metrics["total_pages"],
        "projected_pages": projected_pages,
        "issue_counts": {
            severity: severity_counts.get(severity, 0)
            for severity in ("Critical", "High", "Medium", "Low", "Info")
        },
        "outputs": {
            "PROGRAMMATIC-SEO-REPORT.md": report_path.as_posix(),
            "QUALITY-GATES.json": quality_path.as_posix(),
            "SUMMARY.json": summary_path.as_posix(),
        },
    }
    write_json(summary_path, summary_payload)
    print(f"Generated programmatic analysis artifacts in: {output_dir}")
    return 0


def run_plan(args: argparse.Namespace) -> int:
    config = build_plan_config(args)
    blueprint = render_plan_blueprint(config)
    examples = generate_url_examples(config)
    output_dir = Path(args.output_dir).resolve()

    blueprint_path = output_dir / "PROGRAMMATIC-BLUEPRINT.md"
    urls_path = output_dir / "URL-PATTERN-EXAMPLES.csv"
    quality_path = output_dir / "QUALITY-GATES.json"
    summary_path = output_dir / "SUMMARY.json"

    write_text(blueprint_path, blueprint)
    write_csv(
        urls_path,
        examples,
        ["pattern", "url", "title_template", "h1_template", "primary_attribute", "secondary_attribute"],
    )

    batches = math.ceil(config["expected_pages"] / config["batch_size"])
    quality_payload = {
        "mode": "plan",
        "thresholds": {
            "review_warning_pages": QUALITY_THRESHOLDS["review_warning_pages"],
            "review_hard_stop_pages": QUALITY_THRESHOLDS["review_hard_stop_pages"],
            "minimum_review_rate": QUALITY_THRESHOLDS["minimum_review_rate"],
            "hard_stop_unique_pct": QUALITY_THRESHOLDS["hard_stop_unique_pct"],
            "minimum_unique_pct": config["minimum_unique_pct"],
            "minimum_word_count": config["minimum_word_count"],
        },
        "rollout": {
            "expected_pages": config["expected_pages"],
            "batch_size": config["batch_size"],
            "batches_required": batches,
            "minimum_review_sample_per_batch": max(5, math.ceil(config["batch_size"] * QUALITY_THRESHOLDS["minimum_review_rate"])),
        },
    }
    write_json(quality_path, quality_payload)

    summary_payload = {
        "mode": "plan",
        "generated_at": datetime.now(UTC).isoformat(),
        "project_name": config["project_name"],
        "pattern": config["pattern"],
        "expected_pages": config["expected_pages"],
        "batch_size": config["batch_size"],
        "outputs": {
            "PROGRAMMATIC-BLUEPRINT.md": blueprint_path.as_posix(),
            "URL-PATTERN-EXAMPLES.csv": urls_path.as_posix(),
            "QUALITY-GATES.json": quality_path.as_posix(),
            "SUMMARY.json": summary_path.as_posix(),
        },
    }
    write_json(summary_path, summary_payload)
    print(f"Generated programmatic planning artifacts in: {output_dir}")
    return 0


def main() -> int:
    args = parse_args()
    if args.mode == "analyze":
        return run_analyze(args)
    return run_plan(args)


if __name__ == "__main__":
    raise SystemExit(main())
