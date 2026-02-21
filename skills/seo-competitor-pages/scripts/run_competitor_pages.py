#!/usr/bin/env python3
"""
Deterministic competitor comparison page builder for the seo-competitor-pages skill.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_FEATURES = [
    "Core capabilities",
    "Ease of onboarding",
    "Integrations",
    "Automation depth",
    "Reporting and analytics",
    "Support and success",
    "Security and compliance",
]


def parse_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or "comparison"


def clip_text(value: str, limit: int) -> str:
    raw = re.sub(r"\s+", " ", value).strip()
    if len(raw) <= limit:
        return raw
    clipped = raw[:limit].rsplit(" ", 1)[0].strip()
    return clipped.rstrip(" ,;:-") + "."


def infer_currency(pricing: str, explicit: str | None) -> str:
    code = (explicit or "").strip().upper()
    if code:
        return code
    if "€" in pricing:
        return "EUR"
    if "£" in pricing:
        return "GBP"
    return "USD"


def extract_price_amount(pricing: str) -> str | None:
    currency_match = re.search(r"(?:[$€£]|USD|EUR|GBP)\s*([0-9][0-9.,]*)", pricing, re.IGNORECASE)
    if currency_match:
        token = currency_match.group(1).strip()
    else:
        contextual = re.search(
            r"(?:price|pricing|starts?\s+at|from)\D{0,20}([0-9][0-9.,]*)",
            pricing,
            re.IGNORECASE,
        )
        if contextual:
            token = contextual.group(1).strip()
        else:
            numeric_tokens = re.findall(r"\d[\d.,]*", pricing)
            if not numeric_tokens:
                return None
            token = numeric_tokens[0]
            # Avoid mistaking year stamps for price values when possible.
            if len(numeric_tokens) > 1 and re.fullmatch(r"(19|20)\d{2}", token):
                token = next(
                    (x for x in numeric_tokens[1:] if not re.fullmatch(r"(19|20)\d{2}", x)),
                    token,
                )
            if re.fullmatch(r"(19|20)\d{2}", token):
                return None

    if not token:
        return None

    if "," in token and "." in token:
        # Decide decimal separator based on whichever appears last.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        parts = token.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            token = f"{parts[0]}.{parts[1]}"
        else:
            token = "".join(parts)
    elif token.count(".") > 1:
        token = token.replace(".", "")

    token = re.sub(r"[^0-9.]", "", token)
    if not token:
        return None
    try:
        value = float(token)
    except ValueError:
        return None
    return f"{value:.2f}".rstrip("0").rstrip(".")


def load_data(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("data-file JSON must be an object")
    return data


def product_record(
    name: str,
    is_your_product: bool,
    products_data: dict[str, Any],
    default_url: str | None = None,
) -> dict[str, Any]:
    seed = products_data.get(name, {})
    if seed and not isinstance(seed, dict):
        raise ValueError(f"Invalid product entry for '{name}': expected object")

    url = (seed.get("url") or default_url or "").strip()
    raw_pricing = seed.get("pricing")
    if raw_pricing is None:
        pricing = "Needs source verification"
    else:
        pricing = str(raw_pricing).strip() or "Needs source verification"
    price_currency = infer_currency(pricing, seed.get("price_currency"))
    price_amount = extract_price_amount(pricing) if "Needs source verification" not in pricing else None
    best_for = str(seed.get("best_for") or "Define ideal customer profile for this option.").strip()
    raw_pros = seed.get("pros")
    if not isinstance(raw_pros, list):
        raw_pros = []
    raw_cons = seed.get("cons")
    if not isinstance(raw_cons, list):
        raw_cons = []
    pros = [str(x).strip() for x in raw_pros if str(x).strip()]
    cons = [str(x).strip() for x in raw_cons if str(x).strip()]
    features = seed.get("features", {})
    if not isinstance(features, dict):
        features = {}
    normalized_features = {str(k).strip(): str(v).strip() for k, v in features.items() if str(k).strip()}

    raw_sources = seed.get("sources")
    if not isinstance(raw_sources, list):
        raw_sources = []
    sources = [str(x).strip() for x in raw_sources if str(x).strip()]
    feature_sources = seed.get("feature_sources", {})
    if not isinstance(feature_sources, dict):
        feature_sources = {}
    feature_sources = {str(k).strip(): str(v).strip() for k, v in feature_sources.items() if str(k).strip() and str(v).strip()}
    pricing_source = str(seed.get("pricing_source") or "").strip()

    rating = seed.get("rating", {})
    if not isinstance(rating, dict):
        rating = {}
    rating_value = rating.get("value")
    rating_count = rating.get("count")
    if not isinstance(rating_value, (int, float)):
        rating_value = None
    if not isinstance(rating_count, int):
        rating_count = None

    if not pros:
        pros = ["Document one clear strength with a public source."]
    if not cons:
        cons = ["Document one limitation honestly with a public source."]

    return {
        "name": name,
        "is_your_product": is_your_product,
        "url": url,
        "pricing": pricing,
        "pricing_source": pricing_source,
        "price_currency": price_currency,
        "price_amount": price_amount,
        "best_for": best_for,
        "pros": pros[:4],
        "cons": cons[:4],
        "features": normalized_features,
        "feature_sources": feature_sources,
        "sources": sources,
        "rating_value": rating_value,
        "rating_count": rating_count,
    }


def compute_feature_order(products: list[dict[str, Any]], data: dict[str, Any]) -> list[str]:
    requested = data.get("feature_order", [])
    if isinstance(requested, list):
        ordered = [str(x).strip() for x in requested if str(x).strip()]
    else:
        ordered = []

    seen = set(ordered)
    for product in products:
        for feature in product["features"].keys():
            if feature not in seen:
                ordered.append(feature)
                seen.add(feature)

    if not ordered:
        ordered = DEFAULT_FEATURES[:]
    return ordered


def row_source_marker(feature_name: str, product: dict[str, Any]) -> str:
    if feature_name == "Pricing (from)":
        return " [src]" if product.get("pricing_source") else ""
    if product["feature_sources"].get(feature_name):
        return " [src]"
    return ""


def markdown_matrix(products: list[dict[str, Any]], features: list[str], pricing_as_of: str) -> tuple[str, dict[str, Any]]:
    headers = ["Feature"] + [p["name"] for p in products]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]

    total_claims = 0
    sourced_claims = 0

    for feature in features:
        cells = [feature]
        for product in products:
            value = product["features"].get(feature, "Needs source verification")
            marker = row_source_marker(feature, product)
            cells.append(f"{value}{marker}".strip())
            total_claims += 1
            if marker:
                sourced_claims += 1
        lines.append("| " + " | ".join(cells) + " |")

    pricing_row = [f"Pricing (from, as of {pricing_as_of})"]
    for product in products:
        marker = row_source_marker("Pricing (from)", product)
        pricing_row.append(f"{product['pricing']}{marker}".strip())
        total_claims += 1
        if marker:
            sourced_claims += 1
    lines.append("| " + " | ".join(pricing_row) + " |")

    raw_pct = (sourced_claims / total_claims) * 100 if total_claims else 0.0
    pct = round(raw_pct, 1)
    return "\n".join(lines), {
        "total_claims": total_claims,
        "sourced_claims": sourced_claims,
        "source_coverage_raw_pct": raw_pct,
        "source_coverage_pct": pct,
    }


def keyword_pack(mode: str, your_product: str, competitors: list[str], category: str, year: int, use_case: str) -> dict[str, Any]:
    if mode == "vs":
        opponent = competitors[0]
        primary = f"{your_product} vs {opponent}"
        secondary = [
            f"{your_product} vs {opponent} pricing",
            f"{your_product} vs {opponent} features",
            f"is {your_product} better than {opponent}",
        ]
        title = f"{your_product} vs {opponent}: Features, Pricing, and Best Fit ({year})"
        h1 = f"{your_product} vs {opponent}: which one is right for {use_case}?"
    elif mode == "alternatives":
        anchor = competitors[0] if competitors else your_product
        primary = f"{anchor} alternatives"
        secondary = [
            f"best alternatives to {anchor}",
            f"{anchor} alternatives {year}",
            f"{category} alternatives",
        ]
        title = f"{max(3, len([your_product] + competitors))} Best {anchor} Alternatives in {year} (Compared)"
        h1 = f"Best {anchor} alternatives for {use_case}"
    elif mode == "roundup":
        primary = f"best {category} tools {year}"
        secondary = [
            f"top {category} software",
            f"{category} comparison",
            f"{category} tools for {use_case}",
        ]
        title = f"{max(3, len([your_product] + competitors))} Best {category} Tools in {year} - Compared and Ranked"
        h1 = f"Best {category} tools for {use_case}"
    else:
        primary = f"{category} comparison"
        secondary = [
            f"{category} comparison chart",
            f"{category} pricing comparison",
            f"{category} software matrix",
        ]
        title = f"{category.title()} Comparison Chart ({year}): Features, Pricing, and Fit"
        h1 = f"{category.title()} comparison chart"

    long_tail = [
        f"{primary} for {use_case}",
        f"{primary} for small teams",
        f"{primary} for enterprise teams",
        f"{primary} migration checklist",
    ]

    meta_description = clip_text(
        (
        f"Compare {', '.join([your_product] + competitors[:3])} across features, pricing, and fit. "
        f"See a source-backed {year} breakdown and choose the best option for {use_case}."
        ),
        160,
    )

    return {
        "primary": primary,
        "secondary": secondary,
        "long_tail": long_tail,
        "title": title,
        "h1": h1,
        "meta_description": meta_description[:160],
    }


def section_word_targets() -> list[tuple[str, int]]:
    return [
        ("Executive summary and who this is for", 180),
        ("Methodology and fairness disclosure", 150),
        ("Feature and pricing comparison table context", 250),
        ("Product-by-product breakdown", 550),
        ("Use-case recommendations", 220),
        ("Migration and implementation notes", 170),
        ("Final verdict and CTA", 120),
    ]


def build_recommendations(
    products: list[dict[str, Any]],
    source_coverage_raw_pct: float,
    related_links: list[str],
) -> tuple[list[str], list[str]]:
    critical: list[str] = []
    improvements: list[str] = []

    if source_coverage_raw_pct < 80:
        critical.append(
            f"Source coverage is {source_coverage_raw_pct:.2f}%. Raise to at least 80% before publishing."
        )

    for product in products:
        if not product["sources"]:
            critical.append(f"Add public sources for {product['name']} (docs, pricing page, release notes, or trusted review site).")
        if not product["url"]:
            improvements.append(f"Set canonical product URL for {product['name']}.")
        if "Needs source verification" in product["pricing"]:
            critical.append(f"Pricing for {product['name']} is unresolved. Add current pricing with date and source.")

    if not related_links:
        improvements.append("Add a related comparisons section with at least 3 internal links.")

    improvements.append("Add one migration case study and one customer quote tied to comparison criteria.")
    improvements.append("Schedule a quarterly refresh check for pricing and feature parity.")
    return critical, improvements


def schema_payload(
    mode: str,
    products: list[dict[str, Any]],
    category: str,
    year: int,
    canonical_url: str,
    title: str,
) -> dict[str, Any]:
    graph: list[dict[str, Any]] = [
        {
            "@type": "WebPage",
            "@id": canonical_url,
            "name": title,
            "url": canonical_url,
            "dateModified": datetime.now(tz=UTC).date().isoformat(),
        }
    ]

    list_elements: list[dict[str, Any]] = []
    for idx, product in enumerate(products, start=1):
        product_id = f"{canonical_url}#product-{slugify(product['name'])}"
        software: dict[str, Any] = {
            "@type": "SoftwareApplication",
            "@id": product_id,
            "name": product["name"],
            "applicationCategory": category or "SoftwareApplication",
            "operatingSystem": "Web",
        }
        if product["url"]:
            software["url"] = product["url"]
        if product["price_amount"]:
            software["offers"] = {
                "@type": "Offer",
                "price": product["price_amount"],
                "priceCurrency": product["price_currency"],
            }
        if product["rating_value"] is not None and product["rating_count"] is not None:
            software["aggregateRating"] = {
                "@type": "AggregateRating",
                "ratingValue": str(product["rating_value"]),
                "reviewCount": product["rating_count"],
                "bestRating": "5",
                "worstRating": "1",
            }
        graph.append(software)

        list_elements.append(
            {
                "@type": "ListItem",
                "position": idx,
                "name": product["name"],
                "url": product["url"] or canonical_url,
            }
        )

    if mode in {"alternatives", "roundup", "table"}:
        graph.append(
            {
                "@type": "ItemList",
                "@id": f"{canonical_url}#item-list",
                "name": f"Best {category} tools {year}".strip(),
                "itemListOrder": "https://schema.org/ItemListOrderDescending",
                "numberOfItems": len(products),
                "itemListElement": list_elements,
            }
        )

    return {"@context": "https://schema.org", "@graph": graph}


def product_sections(products: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for product in products:
        source_lines = "\n".join(f"- {src}" for src in product["sources"]) or "- Add at least one source URL"
        pros = "\n".join(f"- {x}" for x in product["pros"])
        cons = "\n".join(f"- {x}" for x in product["cons"])
        affiliation = "Our product" if product["is_your_product"] else "Competitor"
        chunks.append(
            f"""### {product['name']}
Role: {affiliation}

Best for: {product['best_for']}

Strengths:
{pros}

Limitations:
{cons}

Source links:
{source_lines}
"""
        )
    return "\n".join(chunks).strip()


def render_comparison_page(
    mode: str,
    products: list[dict[str, Any]],
    matrix_md: str,
    keywords: dict[str, Any],
    features: list[str],
    related_links: list[str],
    pricing_as_of: str,
    methodology: str,
    disclosure: str,
    source_coverage: dict[str, Any],
    critical: list[str],
    improvements: list[str],
    canonical_url: str,
) -> str:
    word_targets = section_word_targets()
    total_target = sum(x[1] for x in word_targets)

    related_block = "\n".join(f"- {link}" for link in related_links) if related_links else "- Add related internal comparison links"
    critical_block = "\n".join(f"- {x}" for x in critical) if critical else "- None"
    improvement_block = "\n".join(f"- {x}" for x in improvements) if improvements else "- None"

    sections_block = "\n".join(f"- {name}: {target} words" for name, target in word_targets)
    products_block = product_sections(products)
    product_names = ", ".join([p["name"] for p in products])
    today = datetime.now(tz=UTC).date().isoformat()

    return f"""# {keywords['title']}

## SEO Metadata Draft
- Canonical URL: `{canonical_url}`
- Suggested title tag: `{keywords['title']}`
- Suggested H1: `{keywords['h1']}`
- Meta description (<=160 chars): `{keywords['meta_description']}`
- Primary keyword: `{keywords['primary']}`

## Publishing Controls
- Last updated: {today}
- Pricing reviewed as of: {pricing_as_of}
- Affiliation disclosure: {disclosure}
- Methodology: {methodology}

## Executive Summary (Draft)
This page compares {product_names} for buyers evaluating options in {mode} intent. Keep the tone balanced, source every factual claim, and make trade-offs explicit.

## Feature and Pricing Matrix
{matrix_md}

Source coverage: **{source_coverage['source_coverage_pct']}%** ({source_coverage['sourced_claims']}/{source_coverage['total_claims']} claims source-tagged)

## Product Breakdowns
{products_block}

## Recommended Structure and Word Targets
Minimum target: **{max(1500, total_target)} words**

{sections_block}

## Conversion Layout
1. Above fold: 2-3 sentence comparison summary + primary CTA.
2. Mid page: CTA immediately after feature matrix.
3. Keep one trust element near each CTA (case study snippet, testimonial, or source citation).
4. Bottom: final recommendation and next-step CTA.
5. Keep competitor sections informational before CTA.

## Internal Linking Plan
{related_block}

## Compliance and Fairness Checklist
- Use source links for every pricing and feature claim.
- Include one honest competitor strength for each option.
- Mark uncertain claims as unverified until sourced.
- Keep "pricing as of" timestamp current on each refresh.
- Avoid defamatory or unverifiable language.

## Critical Pre-Publish Fixes
{critical_block}

## Improvement Backlog
{improvement_block}
"""


def write_keyword_strategy(
    out_dir: Path,
    mode: str,
    keywords: dict[str, Any],
    category: str,
    year: int,
) -> None:
    path = out_dir / "KEYWORD-STRATEGY.md"
    path.write_text(
        f"""# Keyword Strategy

Mode: `{mode}`
Category: `{category}`
Year: `{year}`

## Primary Keyword
- {keywords['primary']}

## Secondary Keywords
{chr(10).join(f"- {x}" for x in keywords['secondary'])}

## Long-Tail Opportunities
{chr(10).join(f"- {x}" for x in keywords['long_tail'])}

## Title/H1 Drafts
- Title: `{keywords['title']}`
- H1: `{keywords['h1']}`
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate competitor comparison pages and schema artifacts.")
    parser.add_argument("--mode", choices=["vs", "alternatives", "roundup", "table"], required=True)
    parser.add_argument("--your-product", required=True, help="Your product/service name")
    parser.add_argument("--competitors", required=True, help="Comma-separated competitor names")
    parser.add_argument("--category", default="software", help="Category label, e.g. project management")
    parser.add_argument("--year", type=int, default=datetime.now(tz=UTC).year)
    parser.add_argument("--use-case", default="your target buyer", help="Primary buyer/use-case segment")
    parser.add_argument("--canonical-url", default="https://example.com/comparisons/new-page")
    parser.add_argument("--pricing-as-of", default=datetime.now(tz=UTC).date().isoformat())
    parser.add_argument("--methodology", default="Compared published pricing, product docs, and independent reviews.")
    parser.add_argument("--disclosure", default="We may be affiliated with one product listed on this page.")
    parser.add_argument("--related-links", default="", help="Comma-separated internal links to related comparison pages")
    parser.add_argument("--data-file", default="", help="Optional JSON file with product facts/sources")
    parser.add_argument("--output-dir", default="seo-competitor-pages-output")
    args = parser.parse_args()

    competitors = parse_list(args.competitors)
    if not competitors:
        print("Error: provide at least one competitor in --competitors.")
        return 2

    if args.mode == "vs" and len(competitors) != 1:
        print("Error: --mode vs requires exactly one competitor.")
        return 2
    if args.mode in {"alternatives", "roundup", "table"} and len(competitors) < 2:
        print("Error: this mode requires at least two competitors.")
        return 2

    try:
        data = load_data(args.data_file or None)
    except Exception as exc:
        print(f"Error: failed to parse data-file: {exc}")
        return 2

    products_data = data.get("products", {})
    if products_data and not isinstance(products_data, dict):
        print("Error: data-file key 'products' must be an object")
        return 2

    products = [
        product_record(args.your_product, True, products_data),
        *[product_record(name, False, products_data) for name in competitors],
    ]

    features = compute_feature_order(products, data)
    matrix_md, source_coverage = markdown_matrix(products, features, args.pricing_as_of)

    related_links = parse_list(args.related_links)
    critical, improvements = build_recommendations(
        products,
        source_coverage["source_coverage_raw_pct"],
        related_links,
    )

    keywords = keyword_pack(
        mode=args.mode,
        your_product=args.your_product,
        competitors=competitors,
        category=args.category,
        year=args.year,
        use_case=args.use_case,
    )

    schema = schema_payload(
        mode=args.mode,
        products=products,
        category=args.category,
        year=args.year,
        canonical_url=args.canonical_url,
        title=keywords["title"],
    )

    page = render_comparison_page(
        mode=args.mode,
        products=products,
        matrix_md=matrix_md,
        keywords=keywords,
        features=features,
        related_links=related_links,
        pricing_as_of=args.pricing_as_of,
        methodology=args.methodology,
        disclosure=args.disclosure,
        source_coverage=source_coverage,
        critical=critical,
        improvements=improvements,
        canonical_url=args.canonical_url,
    )

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "COMPARISON-PAGE.md").write_text(page, encoding="utf-8")
    (out_dir / "comparison-schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    write_keyword_strategy(out_dir, args.mode, keywords, args.category, args.year)

    summary = {
        "mode": args.mode,
        "products": [p["name"] for p in products],
        "category": args.category,
        "year": args.year,
        "primary_keyword": keywords["primary"],
        "source_coverage_pct": source_coverage["source_coverage_pct"],
        "critical_prepublish_count": len(critical),
        "output_files": [
            str(out_dir / "COMPARISON-PAGE.md"),
            str(out_dir / "comparison-schema.json"),
            str(out_dir / "KEYWORD-STRATEGY.md"),
        ],
    }
    (out_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Mode: {args.mode}")
    print(f"Products: {', '.join(summary['products'])}")
    print(f"Source coverage: {source_coverage['source_coverage_pct']}%")
    print(f"Comparison page: {out_dir / 'COMPARISON-PAGE.md'}")
    print(f"Schema: {out_dir / 'comparison-schema.json'}")
    print(f"Keyword strategy: {out_dir / 'KEYWORD-STRATEGY.md'}")
    print(f"Summary: {out_dir / 'SUMMARY.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
