#!/usr/bin/env python3
"""
Deterministic strategic SEO planner for the seo-plan skill.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

INDUSTRY_ALIASES = {
    "saas": "saas",
    "software": "saas",
    "local": "local-service",
    "localservice": "local-service",
    "local-service": "local-service",
    "service": "local-service",
    "ecommerce": "ecommerce",
    "e-commerce": "ecommerce",
    "publisher": "publisher",
    "media": "publisher",
    "news": "publisher",
    "agency": "agency",
    "consultancy": "agency",
    "generic": "generic",
    "general": "generic",
}

INDUSTRY_PROFILES = {
    "saas": {
        "label": "SaaS",
        "audience": "Decision makers evaluating software solutions",
        "goals": [
            "Increase non-brand traffic to product and pricing pages",
            "Grow trial/demo conversions from organic search",
            "Win comparison and alternatives query clusters",
        ],
        "pillars": [
            "Use-case landing pages",
            "Comparison pages",
            "Integration content",
            "Customer proof assets",
        ],
        "base_path": "/solutions",
        "schema": "Organization, SoftwareApplication, Offer",
    },
    "local-service": {
        "label": "Local Service",
        "audience": "Local customers with urgent service intent",
        "goals": [
            "Increase local pack and map visibility",
            "Grow calls and high-intent leads from organic",
            "Scale city/service pages without doorway risk",
        ],
        "pillars": [
            "Core service pages",
            "City and neighborhood pages",
            "FAQ and trust pages",
            "Review and proof content",
        ],
        "base_path": "/services",
        "schema": "LocalBusiness, Service, FAQPage (where eligible)",
    },
    "ecommerce": {
        "label": "E-commerce",
        "audience": "Buyers comparing products and categories",
        "goals": [
            "Increase category and product-page visibility",
            "Grow organic revenue from commercial intent queries",
            "Improve rich-result eligibility with complete schema",
        ],
        "pillars": [
            "Category buying guides",
            "Product detail depth",
            "Comparison and alternatives",
            "Brand and use-case hubs",
        ],
        "base_path": "/collections",
        "schema": "Product, Offer, AggregateRating, BreadcrumbList",
    },
    "publisher": {
        "label": "Publisher/Media",
        "audience": "Readers seeking timely and trustworthy coverage",
        "goals": [
            "Increase visibility across topic hubs and evergreen guides",
            "Improve engagement and subscriber-assisted conversion",
            "Strengthen author and editorial trust signals",
        ],
        "pillars": [
            "Topic hubs",
            "Evergreen explainers",
            "Original data and analysis",
            "Author and editorial trust pages",
        ],
        "base_path": "/topics",
        "schema": "Article/NewsArticle, Person, Organization",
    },
    "agency": {
        "label": "Agency/Consultancy",
        "audience": "Prospects evaluating expertise and delivery capability",
        "goals": [
            "Increase visibility of service and industry pages",
            "Grow qualified consultations from organic traffic",
            "Expand authority with case studies and thought leadership",
        ],
        "pillars": [
            "Service pages",
            "Industry expertise pages",
            "Case studies",
            "Thought leadership",
        ],
        "base_path": "/services",
        "schema": "ProfessionalService, Service, Person",
    },
    "generic": {
        "label": "Generic Business",
        "audience": "Potential customers comparing options and providers",
        "goals": [
            "Increase qualified non-brand traffic",
            "Build topical authority through intent clusters",
            "Improve conversion quality from organic landings",
        ],
        "pillars": [
            "Core products/services",
            "Resource hub content",
            "Proof and trust assets",
            "Buyer FAQ content",
        ],
        "base_path": "/resources",
        "schema": "Organization, WebSite, Service/Product",
    },
}

COMPETITOR_STRENGTHS = [
    "Strong topical architecture in commercial intent clusters",
    "Consistent publishing cadence and freshness updates",
    "Clear internal linking from informational to transactional pages",
]
COMPETITOR_GAPS = [
    "Thin differentiation on high-intent pages",
    "Inconsistent proof and trust signals in key templates",
    "Limited depth in intent-specific long-tail coverage",
]
COUNTER_MOVES = [
    "Build deeper pillar pages with clearer conversion pathways",
    "Add first-party proof and stronger schema coverage",
    "Publish intent-specific supporting assets on a fixed cadence",
]

RISK_LINES = [
    "| High | Thin or duplicated templates on scaled pages | Enforce content QA and uniqueness gates before publishing. |",
    "| Medium | Internal-link structure drifts as page count grows | Run monthly crawl + orphan checks and fix routing. |",
    "| Medium | KPI tracking gaps hide true performance trends | Maintain dashboard ownership and monthly KPI reviews. |",
]

PHASES = [
    (
        "Phase 1 - Foundation (Weeks 1-4)",
        "SEO + Engineering",
        [
            "Capture baseline KPIs and crawl/index status.",
            "Finalize URL architecture, canonical rules, and templates.",
            "Ship top-priority technical fixes and schema baseline.",
        ],
    ),
    (
        "Phase 2 - Expansion (Weeks 5-12)",
        "SEO + Content",
        [
            "Launch initial content clusters from the calendar.",
            "Implement hub/spoke internal linking across pillars.",
            "Run QA pass on metadata, schema, and thin-content risks.",
        ],
    ),
    (
        "Phase 3 - Scale (Weeks 13-24)",
        "SEO + Editorial",
        [
            "Scale winning clusters and expand long-tail variants.",
            "Publish authority assets and conversion-oriented supporting pages.",
            "Refresh underperforming pages with intent-aligned rewrites.",
        ],
    ),
    (
        "Phase 4 - Authority (Months 7-12)",
        "SEO + Leadership",
        [
            "Operationalize freshness updates and quarterly architecture reviews.",
            "Expand entity consistency and citation-ready content patterns.",
            "Codify SEO operating model, ownership, and SLAs.",
        ],
    ),
]

STAGES = ["Awareness", "Consideration", "Decision", "Authority"]
FORMATS = ["Guide", "Checklist", "Comparison", "Case Study", "FAQ", "Template"]
GROWTH = {"3m": 0.22, "6m": 0.48, "12m": 0.9}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic SEO plan artifacts.")
    parser.add_argument("--industry")
    parser.add_argument("--brief-file")
    parser.add_argument("--baseline-kpis-file")
    parser.add_argument("--business-name")
    parser.add_argument("--website")
    parser.add_argument("--audience")
    parser.add_argument("--goals")
    parser.add_argument("--competitors")
    parser.add_argument("--content-pillars")
    parser.add_argument("--markets")
    parser.add_argument("--budget")
    parser.add_argument("--timeline-months", type=int)
    parser.add_argument("--cadence", choices=["weekly", "biweekly", "monthly"])
    parser.add_argument("--start-date")
    parser.add_argument("--output-dir", default="seo-plan-output")
    return parser.parse_args()


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or "topic"


def normalize_industry(raw: str | None) -> str:
    key = (raw or "generic").strip().lower()
    normalized = INDUSTRY_ALIASES.get(key)
    if normalized:
        return normalized
    raise ValueError("Unsupported industry value")


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path).resolve()
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {file_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def ensure_url(raw: str | None) -> str | None:
    if not raw:
        return None
    parsed = urlparse(raw.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("website must be a valid http/https URL")
    return raw.strip()


def ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return parse_csv(value)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("Expected list or comma-separated string")


def ensure_competitors(value: Any) -> list[dict[str, str]]:
    competitors = []
    if value is None:
        return competitors
    if isinstance(value, list) and any(isinstance(item, dict) for item in value):
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                url = str(item.get("url") or "").strip()
                if not name and url:
                    host = (urlparse(url).netloc or url).replace("www.", "")
                    name = host
                if name:
                    competitors.append({"name": name, "url": url})
                continue
            token = str(item).strip()
            if token:
                competitors.extend(ensure_competitors(token))
        return competitors
    items = ensure_list(value)
    for token in items:
        if token.startswith("http://") or token.startswith("https://"):
            parsed = urlparse(token)
            name = (parsed.netloc or token).replace("www.", "")
            competitors.append({"name": name, "url": token})
        elif "." in token and " " not in token:
            name = token.replace("www.", "")
            competitors.append({"name": name, "url": f"https://{token}"})
        else:
            competitors.append({"name": token, "url": ""})
    return competitors


def parse_date(raw: str | None) -> date:
    if not raw:
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError("start-date must use YYYY-MM-DD") from exc


def extract_section(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def extract_architecture(markdown: str) -> str:
    pattern = re.compile(r"^## Recommended Site Architecture\s*$\n```(?:\w+)?\n(.*?)```", re.MULTILINE | re.DOTALL)
    match = pattern.search(markdown)
    return match.group(1).strip() if match else "/\n├── Home\n└── /contact"


def to_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        clean = value.replace(",", "").replace("%", "").strip()
        return float(clean) if clean and re.match(r"^-?\d+(\.\d+)?$", clean) else None
    return None


def fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.1f}"


def build_config(args: argparse.Namespace, brief: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    industry = normalize_industry(args.industry or brief.get("industry"))
    profile = INDUSTRY_PROFILES[industry]

    goals = ensure_list(args.goals if args.goals is not None else brief.get("goals")) or profile["goals"][:]
    pillars = ensure_list(args.content_pillars if args.content_pillars is not None else brief.get("content_pillars")) or profile["pillars"][:]
    competitors = ensure_competitors(args.competitors if args.competitors is not None else brief.get("competitors"))
    if not competitors:
        competitors = [{"name": "Competitor A", "url": ""}, {"name": "Competitor B", "url": ""}, {"name": "Competitor C", "url": ""}]

    raw_timeline = args.timeline_months if args.timeline_months is not None else brief.get("timeline_months", 12)
    try:
        timeline = int(raw_timeline)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeline-months must be an integer") from exc
    timeline = max(1, min(24, timeline))
    cadence = (args.cadence or brief.get("cadence") or "weekly").strip().lower()
    if cadence not in {"weekly", "biweekly", "monthly"}:
        raise ValueError("cadence must be weekly, biweekly, or monthly")

    return {
        "industry": industry,
        "profile": profile,
        "business_name": str(args.business_name or brief.get("business_name") or "Business Name").strip(),
        "website": ensure_url(args.website or brief.get("website")),
        "audience": str(args.audience or brief.get("audience") or profile["audience"]).strip(),
        "goals": goals,
        "pillars": pillars,
        "competitors": competitors,
        "markets": ensure_list(args.markets if args.markets is not None else brief.get("markets")) or ["Primary market"],
        "budget": str(args.budget or brief.get("budget") or "Define monthly/quarterly budget envelope.").strip(),
        "timeline_months": timeline,
        "cadence": cadence,
        "start_date": parse_date(args.start_date if args.start_date is not None else brief.get("start_date")),
        "baseline": baseline,
    }


def build_kpis(config: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    baseline = config["baseline"]
    traffic = to_number(baseline.get("organic_traffic"))
    keywords = to_number(baseline.get("ranking_keywords"))
    indexed = to_number(baseline.get("indexed_pages"))
    cwv = to_number(baseline.get("core_web_vitals_pass_rate"))
    authority = to_number(baseline.get("domain_authority"))

    def project(value: float | None, growth: float) -> str:
        if value is None:
            return f"+{int(growth * 100)}% vs baseline capture"
        return fmt_num(value * (1 + growth))

    return [
        ("Organic Traffic (sessions/month)", fmt_num(traffic) if traffic is not None else "Capture week 1", project(traffic, GROWTH["3m"]), project(traffic, GROWTH["6m"]), project(traffic, GROWTH["12m"])),
        ("Ranking Keywords (Top 20)", fmt_num(keywords) if keywords is not None else "Capture week 1", project(keywords, 0.15), project(keywords, 0.3), project(keywords, 0.55)),
        (
            "Domain Authority / Authority Score",
            fmt_num(authority) if authority is not None else "Benchmark week 1",
            fmt_num(min(100.0, (authority or 25) + 3)),
            fmt_num(min(100.0, (authority or 25) + 7)),
            fmt_num(min(100.0, (authority or 25) + 12)),
        ),
        ("Indexed Pages", fmt_num(indexed) if indexed is not None else "Capture week 1", project(indexed, 0.12), project(indexed, 0.25), project(indexed, 0.45)),
        ("Core Web Vitals Pass Rate", f"{fmt_num(cwv)}%" if cwv is not None else "Benchmark week 1", f"{fmt_num(min(98.0, (cwv or 70) + 8))}%", f"{fmt_num(min(98.0, (cwv or 70) + 16))}%", f"{fmt_num(min(98.0, (cwv or 70) + 24))}%"),
    ]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    brief = load_json(args.brief_file)
    baseline = load_json(args.baseline_kpis_file)
    if isinstance(brief.get("baseline_kpis"), dict):
        baseline = {**brief["baseline_kpis"], **baseline}

    config = build_config(args, brief, baseline)
    template_path = Path(__file__).resolve().parent.parent / "assets" / f"{config['industry']}.md"
    template_text = template_path.read_text(encoding="utf-8")

    cadence_slots = {"weekly": (12, 7), "biweekly": (6, 14), "monthly": (3, 30)}[config["cadence"]]
    kpi_rows = build_kpis(config)
    output_dir = Path(args.output_dir).resolve()

    strategy = [
        "# SEO Strategy",
        "",
        f"- Business: **{config['business_name']}**",
        f"- Industry: **{config['profile']['label']}**",
        f"- Website: **{config['website'] or 'Not provided'}**",
        f"- Planning Horizon: **{config['timeline_months']} months**",
        f"- Content Cadence: **{config['cadence']}**",
        f"- Template Source: `{template_path.as_posix()}`",
        "",
        "## Strategic Goals",
        "",
        *[f"- {goal}" for goal in config["goals"]],
        "",
        "## KPI Targets",
        "",
        "| Metric | Baseline | 3 Month | 6 Month | 12 Month |",
        "|---|---|---|---|---|",
        *[f"| {m} | {b} | {m3} | {m6} | {m12} |" for m, b, m3, m6, m12 in kpi_rows],
        "",
        "## Operating Rhythm",
        "",
        "- Weekly execution + indexation checks",
        "- Monthly KPI review and reprioritization",
        "- Quarterly architecture and taxonomy refresh",
    ]
    write(output_dir / "SEO-STRATEGY.md", "\n".join(strategy))

    competitor_rows = []
    for i, comp in enumerate(config["competitors"]):
        competitor_rows.append(
            f"| {comp['name']} | {comp['url'] or 'Manual discovery required'} | "
            f"{COMPETITOR_STRENGTHS[i % len(COMPETITOR_STRENGTHS)]} | "
            f"{COMPETITOR_GAPS[i % len(COMPETITOR_GAPS)]} | "
            f"{COUNTER_MOVES[i % len(COUNTER_MOVES)]} |"
        )
    competitor_md = [
        "# Competitor Analysis",
        "",
        "> Planning assumptions only. Validate claims before publishing.",
        "",
        "| Competitor | Source | Likely Strength | Potential Gap | Counter-Move |",
        "|---|---|---|---|---|",
        *competitor_rows,
        "",
        "## Gap Themes by Pillar",
        "",
        *[f"- {pillar}: publish one differentiated asset per quarter." for pillar in config["pillars"]],
    ]
    write(output_dir / "COMPETITOR-ANALYSIS.md", "\n".join(competitor_md))

    entries = []
    count, step = cadence_slots
    for i in range(count):
        stage = STAGES[i % len(STAGES)]
        fmt = FORMATS[i % len(FORMATS)]
        pillar = config["pillars"][i % len(config["pillars"])]
        goal = config["goals"][i % len(config["goals"])]
        title = f"{fmt}: {pillar}" if stage != "Decision" else f"{fmt}: {pillar} for buyers"
        path = f"{config['profile']['base_path']}/{slugify(title)}"
        if stage == "Decision":
            path = f"/compare/{slugify(title)}"
        publish = config["start_date"] + timedelta(days=step * i)
        entries.append((f"Slot {i + 1}", publish.isoformat(), stage, fmt, title, path, goal))

    calendar_md = [
        "# Content Calendar",
        "",
        f"- Cadence: **{config['cadence']}**",
        f"- Start Date: **{config['start_date'].isoformat()}**",
        "",
        "| Slot | Publish Date | Stage | Format | Working Title | Target URL | Goal Link |",
        "|---|---|---|---|---|---|---|",
        *[f"| {slot} | {d} | {s} | {f} | {t} | {u} | {g} |" for slot, d, s, f, t, u, g in entries],
    ]
    write(output_dir / "CONTENT-CALENDAR.md", "\n".join(calendar_md))

    roadmap_md = ["# Implementation Roadmap", "", f"- Timeline: **{config['timeline_months']} months**", f"- Budget Context: **{config['budget']}**", ""]
    for name, owner, tasks in PHASES:
        roadmap_md.extend([f"## {name}", "", f"- Owner: {owner}", "", "### Core Work", ""])
        roadmap_md.extend([f"- {task}" for task in tasks])
        roadmap_md.append("")
    roadmap_md.extend(["## Risk Register", "", "| Severity | Risk | Mitigation |", "|---|---|---|", *RISK_LINES])
    write(output_dir / "IMPLEMENTATION-ROADMAP.md", "\n".join(roadmap_md))

    architecture = extract_architecture(template_text)
    schema_section = extract_section(template_text, "Schema Recommendations") or "Schema section not found in template."
    quality_section = extract_section(template_text, "Quality Gates") or "No explicit quality gates in this template."
    priorities_section = extract_section(template_text, "Content Priorities") or "No explicit priorities in this template."

    pillar_rows = [
        f"| {pillar} | {config['profile']['base_path']}/{slugify(pillar)} | "
        f"{config['profile']['base_path']}/{slugify(pillar)}/[topic-slug] | {config['profile']['schema']} |"
        for pillar in config["pillars"]
    ]
    structure_md = [
        "# Site Structure",
        "",
        f"- Industry Template: **{config['profile']['label']}**",
        "",
        "## Recommended Architecture",
        "",
        "```text",
        architecture,
        "```",
        "",
        "## Pillar to URL Mapping",
        "",
        "| Pillar | Hub URL | Spoke URL Pattern | Schema Priority |",
        "|---|---|---|---|",
        *pillar_rows,
        "",
        "## Template Quality Gates",
        "",
        quality_section,
        "",
        "## Template Content Priorities",
        "",
        priorities_section,
        "",
        "## Template Schema Baseline",
        "",
        schema_section,
    ]
    write(output_dir / "SITE-STRUCTURE.md", "\n".join(structure_md))

    score = 0
    score += 15 if config["business_name"] != "Business Name" else 0
    score += 10 if config["website"] else 0
    score += 20 if len(config["goals"]) >= 3 else 10
    score += 20 if len(config["competitors"]) >= 3 else 10
    score += 15 if len(config["pillars"]) >= 4 else 10
    score += 5 if "Define monthly/quarterly budget envelope." not in config["budget"] else 0
    score += 5 if config["timeline_months"] >= 6 else 0

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "business_name": config["business_name"],
        "industry": config["industry"],
        "cadence": config["cadence"],
        "timeline_months": config["timeline_months"],
        "template_asset": template_path.as_posix(),
        "readiness_score": min(100, score),
        "competitor_count": len(config["competitors"]),
        "content_pillar_count": len(config["pillars"]),
        "calendar_entries": len(entries),
        "outputs": {
            "SEO-STRATEGY.md": (output_dir / "SEO-STRATEGY.md").as_posix(),
            "COMPETITOR-ANALYSIS.md": (output_dir / "COMPETITOR-ANALYSIS.md").as_posix(),
            "CONTENT-CALENDAR.md": (output_dir / "CONTENT-CALENDAR.md").as_posix(),
            "IMPLEMENTATION-ROADMAP.md": (output_dir / "IMPLEMENTATION-ROADMAP.md").as_posix(),
            "SITE-STRUCTURE.md": (output_dir / "SITE-STRUCTURE.md").as_posix(),
        },
    }
    write(output_dir / "SUMMARY.json", json.dumps(summary, indent=2))
    print(f"Generated SEO plan artifacts in: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
