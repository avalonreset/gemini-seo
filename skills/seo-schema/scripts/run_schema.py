#!/usr/bin/env python3
"""
Schema detection, validation, and generation runner for seo-schema.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CodexSEO/1.0; +https://github.com/avalonreset/codex-seo)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}

PLACEHOLDER_RE = re.compile(r"(\[[^\]]+\]|<[^>]+>|__\w+__|\bTBD\b|\bTODO\b)", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[Tt ][0-9:\-+.Zz]+)?$")
PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}

DEPRECATED_TYPES = {
    "howto",
    "specialannouncement",
    "courseinfo",
    "estimatedsalary",
    "learningvideo",
    "claimreview",
    "vehiclelisting",
    "practiceproblem",
    "dataset",
}
RESTRICTED_TYPES = {"faqpage"}
URL_FIELDS = {"url", "logo", "image", "@id", "sameas", "contenturl", "embedurl", "thumbnailurl"}
DATE_FIELDS = {"datepublished", "datemodified", "datecreated", "uploaddate", "startdate", "enddate"}
JSONLD_TYPE_RE = re.compile(r"application/ld\+json", re.IGNORECASE)
MAX_REDIRECT_HOPS = 10

REQUIRED_FIELDS: dict[str, list[str]] = {
    "organization": ["name", "url"],
    "localbusiness": ["name", "address"],
    "softwareapplication": ["name", "applicationCategory"],
    "webapplication": ["name", "applicationCategory"],
    "article": ["headline", "author", "datePublished"],
    "blogposting": ["headline", "author", "datePublished"],
    "newsarticle": ["headline", "datePublished"],
    "product": ["name", "offers"],
    "service": ["name"],
    "faqpage": ["mainEntity"],
    "breadcrumblist": ["itemListElement"],
    "website": ["name", "url"],
    "webpage": ["name"],
    "person": ["name"],
}


@dataclass
class NodeValidation:
    block_index: int
    node_index: int
    schema_type: str
    status: str
    issues: list[str]


def normalize_url(raw: str) -> str:
    value = raw.strip()
    parsed = urlparse(value)
    if not parsed.scheme:
        value = f"https://{value}"
        parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    netloc = parsed.netloc or (parsed.hostname or "")
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, netloc, path, "", parsed.query, ""))


def canonical_host(host: str | None) -> str:
    value = (host or "").strip().lower().rstrip(".")
    if value.startswith("www."):
        return value[4:]
    return value


def is_public_target(url: str) -> bool:
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for _, _, _, _, sockaddr in info:
        ip_text = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_multicast:
            continue
        return True
    return False


def fetch_html(url: str, timeout: int) -> tuple[str, str]:
    current_url = url
    redirects = 0
    while True:
        if not is_public_target(current_url):
            raise ValueError("redirected target URL resolves to non-public or invalid host")
        response = requests.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
        if 300 <= response.status_code < 400:
            location = (response.headers.get("Location") or "").strip()
            if not location:
                response.raise_for_status()
                return response.text, normalize_url(current_url)
            if redirects >= MAX_REDIRECT_HOPS:
                raise ValueError(f"Too many redirects (>{MAX_REDIRECT_HOPS})")
            next_url = normalize_url(urljoin(current_url, location))
            if not is_public_target(next_url):
                raise ValueError("redirected target URL resolves to non-public or invalid host")
            current_url = next_url
            redirects += 1
            continue
        response.raise_for_status()
        return response.text, normalize_url(current_url)


def normalize_type(value: str) -> str:
    cleaned = str(value or "").strip().rstrip("/")
    if not cleaned:
        return ""
    if "#" in cleaned:
        cleaned = cleaned.rsplit("#", 1)[-1]
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    return cleaned.lower().strip()


def type_list(raw_type: Any) -> list[str]:
    if isinstance(raw_type, list):
        return [normalize_type(x) for x in raw_type if normalize_type(str(x))]
    normalized = normalize_type(str(raw_type))
    return [normalized] if normalized else []


def context_valid(ctx: Any) -> bool:
    if isinstance(ctx, list):
        return any(context_valid(item) for item in ctx)
    if isinstance(ctx, str):
        value = ctx.strip().rstrip("/")
        return value.lower() == "https://schema.org"
    return False


def iter_schema_nodes(value: Any, inherited_context: Any = None):
    if isinstance(value, dict):
        context = value.get("@context", inherited_context)
        if "@type" in value:
            yield value, context
        for child in value.values():
            yield from iter_schema_nodes(child, context)
    elif isinstance(value, list):
        for child in value:
            yield from iter_schema_nodes(child, inherited_context)


def iter_strings(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_strings(child)
    elif isinstance(value, str):
        yield value


def get_field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for k, child in value.items():
            if k.lower() == key.lower():
                return child
    return None


def values_for_key(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for k, child in value.items():
            if k.lower() == key.lower():
                found.append(child)
            found.extend(values_for_key(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(values_for_key(child, key))
    return found


def absolute_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_authority_domain(host: str) -> bool:
    if host.endswith(".gov"):
        return True
    markers = ["health", "hospital", "clinic", "medical", "nhs", "cdc", "nih", "who.int"]
    return any(marker in host for marker in markers)


def extract_jsonld_blocks(soup: BeautifulSoup) -> tuple[list[dict[str, Any]], list[str]]:
    blocks: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    scripts = soup.find_all("script", attrs={"type": JSONLD_TYPE_RE})
    for idx, script in enumerate(scripts, start=1):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            parse_errors.append(f"Block {idx}: empty JSON-LD script")
            continue
        try:
            payload = json.loads(raw)
            blocks.append({"index": idx, "payload": payload})
        except json.JSONDecodeError as exc:
            parse_errors.append(f"Block {idx}: invalid JSON ({exc})")
    return blocks, parse_errors


def validate_node(
    node: dict[str, Any],
    context: Any,
    host: str,
    block_index: int,
    node_index: int,
) -> list[NodeValidation]:
    issues: list[NodeValidation] = []
    types = type_list(node.get("@type"))
    if not types:
        issues.append(
            NodeValidation(
                block_index=block_index,
                node_index=node_index,
                schema_type="unknown",
                status="fail",
                issues=["Missing or invalid @type value."],
            )
        )
        return issues

    for schema_type in types:
        node_issues: list[str] = []
        if not context_valid(context):
            node_issues.append("@context should be https://schema.org (inherited context accepted).")
        if schema_type in DEPRECATED_TYPES:
            node_issues.append(f"{schema_type} is deprecated/restricted for rich results.")
        if schema_type in RESTRICTED_TYPES and not is_authority_domain(host):
            node_issues.append("FAQPage is restricted to government/health authority sites.")

        required = REQUIRED_FIELDS.get(schema_type, [])
        for field_name in required:
            if get_field(node, field_name) in (None, "", [], {}):
                node_issues.append(f"Missing required property for {schema_type}: {field_name}")

        for string_value in iter_strings(node):
            if PLACEHOLDER_RE.search(string_value):
                node_issues.append("Placeholder-like values detected; replace with verifiable values.")
                break

        for key in URL_FIELDS:
            for val in values_for_key(node, key):
                values = val if isinstance(val, list) else [val]
                for item in values:
                    if isinstance(item, str) and item.strip() and not absolute_url(item):
                        node_issues.append(f"{key} should be an absolute URL: {item}")

        for key in DATE_FIELDS:
            for val in values_for_key(node, key):
                if isinstance(val, str) and val.strip() and not ISO_DATE_RE.match(val.strip()):
                    node_issues.append(f"{key} should use ISO-8601 date format: {val}")

        status = "pass" if not node_issues else "warn"
        if any("deprecated" in issue.lower() or "missing required property" in issue.lower() for issue in node_issues):
            status = "fail"
        issues.append(
            NodeValidation(
                block_index=block_index,
                node_index=node_index,
                schema_type=schema_type,
                status=status,
                issues=sorted(set(node_issues)),
            )
        )
    return issues


def detect_content_signals(soup: BeautifulSoup, text: str) -> dict[str, bool]:
    low = text.lower()
    has_article_cues = any(marker in low for marker in ["published", "updated", "by ", "read time"])
    has_product_cues = any(marker in low for marker in ["price", "buy", "pricing", "plan", "add to cart"])
    has_breadcrumb = bool(soup.select("nav[aria-label*=breadcrumb i], .breadcrumb"))
    has_faq_cues = bool(soup.find_all(re.compile("^h[2-4]$"), string=re.compile(r"\?$")))
    return {
        "article": has_article_cues,
        "product": has_product_cues,
        "breadcrumb": has_breadcrumb,
        "faq": has_faq_cues,
    }


def template_payload(template: str, host_url: str, title: str | None, metadata: dict[str, Any]) -> dict[str, Any]:
    url = metadata.get("url") or host_url
    site_name = metadata.get("site_name") or "__REPLACE_SITE_NAME__"
    if template == "organization":
        return {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": metadata.get("name") or "__REPLACE_ORG_NAME__",
            "url": url,
            "logo": metadata.get("logo") or "__REPLACE_LOGO_URL__",
            "sameAs": metadata.get("sameAs") or [],
        }
    if template == "localbusiness":
        return {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": metadata.get("name") or "__REPLACE_BUSINESS_NAME__",
            "url": url,
            "telephone": metadata.get("telephone") or "__REPLACE_PHONE__",
            "address": metadata.get("address")
            or {
                "@type": "PostalAddress",
                "streetAddress": "__REPLACE_STREET__",
                "addressLocality": "__REPLACE_CITY__",
                "addressRegion": "__REPLACE_REGION__",
                "postalCode": "__REPLACE_POSTAL_CODE__",
                "addressCountry": metadata.get("addressCountry") or "US",
            },
        }
    if template == "article":
        return {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": metadata.get("headline") or title or "__REPLACE_HEADLINE__",
            "author": metadata.get("author") or {"@type": "Person", "name": "__REPLACE_AUTHOR__"},
            "datePublished": metadata.get("datePublished") or "__REPLACE_YYYY-MM-DD__",
            "dateModified": metadata.get("dateModified") or "__REPLACE_YYYY-MM-DD__",
            "mainEntityOfPage": url,
            "publisher": metadata.get("publisher")
            or {
                "@type": "Organization",
                "name": site_name,
                "logo": {"@type": "ImageObject", "url": "__REPLACE_PUBLISHER_LOGO_URL__"},
            },
        }
    if template == "product":
        return {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": metadata.get("name") or "__REPLACE_PRODUCT_NAME__",
            "description": metadata.get("description") or "__REPLACE_PRODUCT_DESCRIPTION__",
            "brand": metadata.get("brand") or {"@type": "Brand", "name": site_name},
            "offers": metadata.get("offers")
            or {
                "@type": "Offer",
                "price": "__REPLACE_PRICE__",
                "priceCurrency": metadata.get("priceCurrency") or "USD",
                "availability": "https://schema.org/InStock",
                "url": url,
            },
        }
    if template == "website":
        return {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": site_name,
            "url": url,
        }
    if template == "breadcrumb":
        return {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": metadata.get("itemListElement")
            or [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": url},
                {"@type": "ListItem", "position": 2, "name": "__REPLACE_SECTION__", "item": "__REPLACE_SECTION_URL__"},
                {"@type": "ListItem", "position": 3, "name": title or "__REPLACE_PAGE_TITLE__", "item": url},
            ],
        }
    if template == "faq":
        return {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": metadata.get("mainEntity")
            or [
                {
                    "@type": "Question",
                    "name": "__REPLACE_QUESTION__",
                    "acceptedAnswer": {"@type": "Answer", "text": "__REPLACE_ANSWER__"},
                }
            ],
        }
    raise ValueError(f"Unsupported template: {template}")


def build_suggestions(
    normalized_types: set[str],
    signals: dict[str, bool],
    page_url: str,
    title: str | None,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    if "organization" not in normalized_types and "localbusiness" not in normalized_types:
        suggestions.append(
            {
                "type": "Organization",
                "reason": "No Organization/LocalBusiness schema detected.",
                "jsonld": template_payload("organization", page_url, title, {}),
            }
        )
    if signals["article"] and not {"article", "blogposting", "newsarticle"} & normalized_types:
        suggestions.append(
            {
                "type": "Article",
                "reason": "Article-like content signals detected without Article schema.",
                "jsonld": template_payload("article", page_url, title, {}),
            }
        )
    if signals["product"] and "product" not in normalized_types:
        suggestions.append(
            {
                "type": "Product",
                "reason": "Product/pricing cues detected without Product schema.",
                "jsonld": template_payload("product", page_url, title, {}),
            }
        )
    if signals["breadcrumb"] and "breadcrumblist" not in normalized_types:
        suggestions.append(
            {
                "type": "BreadcrumbList",
                "reason": "Breadcrumb-like navigation detected without BreadcrumbList schema.",
                "jsonld": template_payload("breadcrumb", page_url, title, {}),
            }
        )
    if signals["faq"] and "faqpage" not in normalized_types:
        suggestions.append(
            {
                "type": "FAQPage",
                "reason": "Question-like headings detected; FAQPage is restricted to authority sites.",
                "jsonld": template_payload("faq", page_url, title, {}),
            }
        )
    return suggestions


def load_metadata(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("metadata-file must be a JSON object")
    return data


def render_report(
    out_path: Path,
    source: str,
    detections: dict[str, Any],
    validations: list[NodeValidation],
    parse_errors: list[str],
    suggestions: list[dict[str, Any]],
) -> None:
    by_status: dict[str, list[NodeValidation]] = {"pass": [], "warn": [], "fail": []}
    for item in validations:
        by_status.setdefault(item.status, []).append(item)
    pass_count = len(by_status.get("pass", []))
    warn_count = len(by_status.get("warn", []))
    fail_count = len(by_status.get("fail", []))

    def issue_lines(nodes: list[NodeValidation]) -> str:
        lines: list[str] = []
        for node in nodes:
            if node.issues:
                details = "; ".join(node.issues[:4])
                lines.append(
                    f"- Block {node.block_index}, node {node.node_index}, `{node.schema_type}`: {details}"
                )
        return "\n".join(lines) if lines else "- None"

    report = f"""# Schema Report

## Source
- `{source}`

## Detection Summary
- JSON-LD scripts: {detections['jsonld_script_count']}
- Parsed JSON-LD blocks: {detections['parsed_jsonld_blocks']}
- Schema nodes with `@type`: {detections['typed_nodes']}
- Unique schema types: {", ".join(sorted(detections['unique_types'])) if detections['unique_types'] else "None"}
- Microdata markers: {detections['microdata_markers']}
- RDFa markers: {detections['rdfa_markers']}

## Validation Summary
- Pass: {pass_count}
- Warn: {warn_count}
- Fail: {fail_count}
- Parse errors: {len(parse_errors)}

### Failures
{issue_lines(by_status.get("fail", []))}

### Warnings
{issue_lines(by_status.get("warn", []))}

### Parse Errors
{chr(10).join(f"- {x}" for x in parse_errors) if parse_errors else "- None"}

## Opportunities
{chr(10).join(f"- **{x['type']}**: {x['reason']}" for x in suggestions) if suggestions else "- No additional schema opportunities detected."}
"""
    out_path.write_text(report, encoding="utf-8")


def run_analyze(args: argparse.Namespace) -> int:
    if bool(args.url) == bool(args.html_file):
        print("Error: provide exactly one of --url or --html-file")
        return 2

    source = ""
    host = ""
    page_url = "https://example.com/"
    html = ""

    if args.url:
        try:
            target = normalize_url(args.url)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 2
        if not is_public_target(target):
            print("Error: target URL resolves to non-public or invalid host")
            return 2
        try:
            html, final_url = fetch_html(target, args.timeout)
        except requests.exceptions.RequestException as exc:
            print(f"Error: failed to fetch URL: {exc}")
            return 1
        except ValueError as exc:
            print(f"Error: {exc}")
            return 2
        if not is_public_target(final_url):
            print("Error: redirected target URL resolves to non-public or invalid host")
            return 2
        source = final_url
        page_url = final_url
        host = canonical_host(urlparse(final_url).hostname)
    else:
        path = Path(args.html_file).resolve()
        if not path.exists():
            print(f"Error: HTML file not found: {path}")
            return 2
        html = path.read_text(encoding="utf-8", errors="ignore")
        source = str(path)
        if args.page_url:
            try:
                page_url = normalize_url(args.page_url)
            except ValueError as exc:
                print(f"Error: {exc}")
                return 2
        host = canonical_host(urlparse(page_url).hostname)

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    title = soup.title.get_text(" ", strip=True) if soup.title else None

    blocks, parse_errors = extract_jsonld_blocks(soup)
    validations: list[NodeValidation] = []
    unique_types: set[str] = set()

    for block in blocks:
        payload = block["payload"]
        block_index = block["index"]
        node_counter = 0
        for node, context in iter_schema_nodes(payload, None):
            node_counter += 1
            results = validate_node(node=node, context=context, host=host, block_index=block_index, node_index=node_counter)
            validations.extend(results)
            unique_types.update(item.schema_type for item in results if item.schema_type != "unknown")

    microdata_markers = len(soup.select("[itemscope], [itemprop]"))
    rdfa_markers = len(soup.select("[typeof], [property]"))
    signals = detect_content_signals(soup, text)
    suggestions = build_suggestions(unique_types, signals, page_url, title)

    detections = {
        "jsonld_script_count": len(soup.find_all("script", attrs={"type": JSONLD_TYPE_RE})),
        "parsed_jsonld_blocks": len(blocks),
        "typed_nodes": len(validations),
        "unique_types": sorted(unique_types),
        "microdata_markers": microdata_markers,
        "rdfa_markers": rdfa_markers,
    }

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "SCHEMA-REPORT.md"
    generated_path = out_dir / "generated-schema.json"
    summary_path = out_dir / "SUMMARY.json"

    render_report(
        out_path=report_path,
        source=source,
        detections=detections,
        validations=validations,
        parse_errors=parse_errors,
        suggestions=suggestions,
    )
    generated_payload = {
        "source": source,
        "suggestions": suggestions,
    }
    generated_path.write_text(json.dumps(generated_payload, indent=2), encoding="utf-8")

    pass_count = sum(1 for item in validations if item.status == "pass")
    warn_count = sum(1 for item in validations if item.status == "warn")
    fail_count = sum(1 for item in validations if item.status == "fail")
    summary = {
        "source": source,
        "detections": detections,
        "validation": {
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "parse_errors": len(parse_errors),
        },
        "opportunity_count": len(suggestions),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Source: {source}")
    print(f"Schema nodes validated: {len(validations)}")
    print(f"Pass/Warn/Fail: {pass_count}/{warn_count}/{fail_count}")
    print(f"Opportunities: {len(suggestions)}")
    print(f"Report: {report_path}")
    print(f"Generated schema: {generated_path}")
    print(f"Summary: {summary_path}")
    return 0


def run_generate(args: argparse.Namespace) -> int:
    try:
        page_url = normalize_url(args.page_url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    try:
        metadata = load_metadata(args.metadata_file)
    except Exception as exc:
        print(f"Error: failed to read metadata-file: {exc}")
        return 2

    title = metadata.get("title")
    if title is not None:
        title = str(title)

    schema = template_payload(args.template, page_url, title, metadata)
    warnings: list[str] = []
    if args.template == "faq":
        host = canonical_host(urlparse(page_url).hostname)
        if not is_authority_domain(host):
            warnings.append("FAQPage is restricted for non-authority domains; use only when eligible.")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_path = out_dir / "generated-schema.json"
    summary_path = out_dir / "SUMMARY.json"

    generated_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    summary = {
        "template": args.template,
        "page_url": page_url,
        "warning_count": len(warnings),
        "warnings": warnings,
        "output_file": str(generated_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Template: {args.template}")
    print(f"Output: {generated_path}")
    print(f"Warnings: {len(warnings)}")
    print(f"Summary: {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Schema detection, validation, and generation runner.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Analyze schema on a URL or local HTML file")
    p_analyze.add_argument("--url", default="", help="Target page URL")
    p_analyze.add_argument("--html-file", default="", help="Local HTML file path")
    p_analyze.add_argument("--page-url", default="", help="Canonical page URL when using --html-file")
    p_analyze.add_argument("--timeout", type=int, default=20)
    p_analyze.add_argument("--output-dir", default="seo-schema-output")
    p_analyze.set_defaults(func=run_analyze)

    p_generate = sub.add_parser("generate", help="Generate JSON-LD template")
    p_generate.add_argument(
        "--template",
        required=True,
        choices=["organization", "localbusiness", "article", "product", "website", "breadcrumb", "faq"],
    )
    p_generate.add_argument("--page-url", required=True)
    p_generate.add_argument("--metadata-file", default="", help="Optional JSON file with replacement values")
    p_generate.add_argument("--output-dir", default="seo-schema-output")
    p_generate.set_defaults(func=run_generate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
