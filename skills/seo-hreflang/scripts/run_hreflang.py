
#!/usr/bin/env python3
"""Deterministic hreflang validator/generator for seo-hreflang."""

from __future__ import annotations

import argparse
import gzip
import ipaddress
import json
import re
import socket
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
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

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NS = "http://www.w3.org/1999/xhtml"
SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
HREFLANG_CODE_RE = re.compile(r"^[A-Za-z]{2}(?:-[A-Za-z]{2}|-[A-Za-z]{4}|-[A-Za-z]{4}-[A-Za-z]{2})?$")

COMMON_INVALID_LANGUAGE_CODES = {
    "eng": "Use en",
    "jp": "Use ja",
    "sp": "Use es",
    "chn": "Use zh-Hans or zh-Hant",
}
COMMON_INVALID_REGION_CODES = {
    "UK": "Use GB",
    "LA": "Use specific countries like MX/AR/CL",
    "EU": "Use specific country code",
    "EMEA": "Use specific country code",
    "APAC": "Use specific country code",
}


@dataclass
class PageRecord:
    page_url: str
    alternates: dict[str, list[str]]
    canonical_url: str | None
    source: str


def normalize_url(raw: str, *, require_host: bool = True) -> str:
    value = raw.strip()
    parsed = urlparse(value)
    if not parsed.scheme:
        value = f"https://{value}"
        parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    netloc = parsed.netloc or (parsed.hostname or "")
    if require_host and not netloc:
        raise ValueError("URL is missing host")
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, netloc, path, "", parsed.query, ""))


def compare_key(url: str) -> str:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    host = canonical_host(parsed.hostname)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, host, path, "", parsed.query, ""))


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


def load_iso_sets() -> tuple[set[str], set[str], bool]:
    try:
        import pycountry  # type: ignore

        lang_codes = {
            item.alpha_2.lower()
            for item in pycountry.languages
            if hasattr(item, "alpha_2") and str(getattr(item, "alpha_2", "")).strip()
        }
        region_codes = {
            item.alpha_2.upper()
            for item in pycountry.countries
            if hasattr(item, "alpha_2") and str(getattr(item, "alpha_2", "")).strip()
        }
        return lang_codes, region_codes, True
    except Exception:
        return set(), set(), False


def normalize_hreflang_code(raw_code: str) -> str:
    code = raw_code.strip()
    if code.lower() == "x-default":
        return "x-default"
    parts = [p for p in code.split("-") if p]
    if not parts:
        return code.lower()
    if len(parts) == 1:
        return parts[0].lower()
    if len(parts) == 2:
        if len(parts[1]) == 2:
            return f"{parts[0].lower()}-{parts[1].upper()}"
        return f"{parts[0].lower()}-{parts[1].title()}"
    if len(parts) >= 3:
        mid = parts[1].title() if len(parts[1]) == 4 else parts[1].upper()
        tail = parts[2].upper()
        return f"{parts[0].lower()}-{mid}-{tail}"
    return code


def validate_hreflang_code(raw_code: str, strict_iso: bool) -> tuple[str, list[dict[str, str]]]:
    code = raw_code.strip()
    normalized = normalize_hreflang_code(code)
    issues: list[dict[str, str]] = []

    if normalized == "x-default":
        return normalized, issues

    low = code.lower()
    if low in COMMON_INVALID_LANGUAGE_CODES:
        issues.append(
            {
                "severity": "High",
                "detail": f"Invalid language code '{code}'. {COMMON_INVALID_LANGUAGE_CODES[low]}.",
            }
        )
        return normalized, issues

    if not HREFLANG_CODE_RE.fullmatch(code):
        issues.append(
            {
                "severity": "High",
                "detail": f"Invalid hreflang format '{code}'. Use language or language-region/script format.",
            }
        )
        return normalized, issues

    lang_codes, region_codes, has_pycountry = load_iso_sets()

    parts = normalized.split("-")
    language = parts[0]
    if has_pycountry and language not in lang_codes:
        issues.append({"severity": "High", "detail": f"Unknown ISO 639-1 language code '{language}' in '{code}'"})

    region = None
    script = None
    if len(parts) == 2:
        if len(parts[1]) == 2:
            region = parts[1]
        elif len(parts[1]) == 4:
            script = parts[1]
    elif len(parts) >= 3:
        script = parts[1]
        region = parts[2]

    if language == "zh" and region is None and script is None:
        issues.append(
            {
                "severity": "Low",
                "detail": "Use zh-Hans or zh-Hant for Chinese when possible to avoid ambiguity.",
            }
        )

    if region:
        if region in COMMON_INVALID_REGION_CODES:
            issues.append(
                {
                    "severity": "High",
                    "detail": f"Invalid region code '{region}' in '{code}'. {COMMON_INVALID_REGION_CODES[region]}",
                }
            )
        elif has_pycountry and region not in region_codes:
            issues.append({"severity": "High", "detail": f"Unknown ISO 3166-1 region code '{region}' in '{code}'"})

    if script and script.lower() not in {"hans", "hant", "latn", "cyrl", "arab"}:
        issues.append(
            {
                "severity": "Medium",
                "detail": f"Uncommon script subtag '{script}' in '{code}'. Verify script is intentional.",
            }
        )

    if code != normalized:
        issues.append(
            {
                "severity": "Low",
                "detail": f"Prefer normalized casing '{normalized}' instead of '{code}'.",
            }
        )

    if strict_iso and not has_pycountry:
        issues.append(
            {
                "severity": "Low",
                "detail": "Install pycountry for strict ISO language/region validation.",
            }
        )

    return normalized, issues


def localname(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag

def find_canonical_url(soup: BeautifulSoup, page_url: str) -> str | None:
    for node in soup.find_all("link", href=True):
        rel_attr = node.get("rel") or []
        rel_values = [str(item).lower() for item in rel_attr] if isinstance(rel_attr, list) else str(rel_attr).lower().split()
        if "canonical" not in rel_values:
            continue
        href = str(node.get("href") or "").strip()
        if not href:
            continue
        try:
            return normalize_url(urljoin(page_url, href))
        except ValueError:
            return None
    return None


def extract_html_alternates(soup: BeautifulSoup, page_url: str) -> dict[str, list[str]]:
    alternates: dict[str, list[str]] = defaultdict(list)
    for node in soup.find_all("link", href=True):
        rel_attr = node.get("rel") or []
        rel_values = [str(item).lower() for item in rel_attr] if isinstance(rel_attr, list) else str(rel_attr).lower().split()
        if "alternate" not in rel_values:
            continue
        code = str(node.get("hreflang") or "").strip()
        href = str(node.get("href") or "").strip()
        if not code or not href:
            continue
        try:
            resolved = normalize_url(urljoin(page_url, href))
        except ValueError:
            continue
        alternates[code].append(resolved)
    return dict(alternates)


def parse_page_html(html: str, page_url: str, source: str) -> PageRecord:
    soup = BeautifulSoup(html, "lxml")
    canonical = find_canonical_url(soup, page_url)
    alternates = extract_html_alternates(soup, page_url)
    return PageRecord(page_url=page_url, canonical_url=canonical, alternates=alternates, source=source)


def fetch_html(url: str, timeout: int) -> tuple[str, str]:
    response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.text, normalize_url(response.url)


def read_sitemap_file_text(path_value: str) -> str:
    path = Path(path_value).resolve()
    if not path.exists():
        raise ValueError(f"Sitemap file not found: {path}")
    raw = path.read_bytes()
    if str(path).lower().endswith(".gz"):
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            raise ValueError(f"Invalid gzip sitemap file: {path}") from exc
    return raw.decode("utf-8", errors="ignore")


def decode_sitemap_response(response: requests.Response) -> str:
    content = response.content
    encoding = str(response.headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding:
        try:
            content = gzip.decompress(content)
        except OSError:
            pass
    return content.decode("utf-8", errors="ignore")


def fetch_sitemap_text(url: str, timeout: int) -> tuple[str, str]:
    response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    text = decode_sitemap_response(response)
    return text, normalize_url(response.url)


def parse_sitemap_document(xml_text: str, source: str) -> tuple[str, list[PageRecord], list[str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML in {source}: {exc}") from exc

    root_name = localname(root.tag)
    if root_name == "sitemapindex":
        children: list[str] = []
        for node in root:
            if localname(node.tag) != "sitemap":
                continue
            loc = None
            for child in node:
                if localname(child.tag) == "loc" and child.text:
                    loc = child.text.strip()
                    break
            if not loc:
                continue
            children.append(loc)
        return "sitemapindex", [], children

    if root_name != "urlset":
        raise ValueError(f"Unsupported sitemap root in {source}: {root_name}")

    records: list[PageRecord] = []
    for url_node in root:
        if localname(url_node.tag) != "url":
            continue
        loc = None
        alternates: dict[str, list[str]] = defaultdict(list)
        for child in url_node:
            child_name = localname(child.tag)
            if child_name == "loc" and child.text:
                loc = child.text.strip()
                continue
            if child_name != "link":
                continue
            rel = str(child.attrib.get("rel") or "").strip().lower()
            code = str(child.attrib.get("hreflang") or "").strip()
            href = str(child.attrib.get("href") or "").strip()
            if rel != "alternate" or not code or not href:
                continue
            try:
                normalized_href = normalize_url(href)
            except ValueError:
                continue
            alternates[code].append(normalized_href)

        if not loc:
            continue
        try:
            normalized_loc = normalize_url(loc)
        except ValueError:
            continue
        records.append(
            PageRecord(
                page_url=normalized_loc,
                canonical_url=normalized_loc,
                alternates=dict(alternates),
                source=f"sitemap:{source}",
            )
        )

    return "urlset", records, []


def load_sitemap_records(args: argparse.Namespace) -> tuple[list[PageRecord], list[dict[str, str]]]:
    warnings: list[dict[str, str]] = []
    queue: list[tuple[str, str]] = []

    if args.sitemap_file:
        file_path = Path(args.sitemap_file).resolve()
        if not file_path.exists():
            raise ValueError(f"Sitemap file not found: {file_path}")
        queue.append(("file", str(file_path)))
    else:
        start_url = normalize_url(args.sitemap_url)
        if not is_public_target(start_url):
            raise ValueError("sitemap URL resolves to non-public or invalid host")
        queue.append(("url", start_url))

    records: list[PageRecord] = []
    visited: set[str] = set()

    while queue and len(visited) < args.max_sitemaps:
        source_type, source_value = queue.pop(0)
        if source_value in visited:
            continue
        visited.add(source_value)

        try:
            if source_type == "file":
                xml_text = read_sitemap_file_text(source_value)
                source_label = source_value
            else:
                xml_text, final_url = fetch_sitemap_text(source_value, args.timeout)
                source_label = final_url
        except (requests.exceptions.RequestException, OSError, ValueError) as exc:
            warnings.append(
                {
                    "severity": "Info",
                    "page_url": source_value,
                    "check": "Sitemap fetch",
                    "detail": f"Could not load sitemap source: {exc}",
                }
            )
            continue

        kind, parsed_records, children = parse_sitemap_document(xml_text, source_label)
        if kind == "urlset":
            records.extend(parsed_records)
        else:
            for child in children:
                if child in visited:
                    continue
                child_parsed = urlparse(child)
                if child_parsed.scheme in {"http", "https"}:
                    child_url = normalize_url(child)
                    if not is_public_target(child_url):
                        warnings.append(
                            {
                                "severity": "Info",
                                "page_url": child_url,
                                "check": "Sitemap index",
                                "detail": "Skipped non-public child sitemap target.",
                            }
                        )
                        continue
                    queue.append(("url", child_url))
                    continue

                if source_type == "url":
                    resolved = normalize_url(urljoin(source_label, child))
                    if not is_public_target(resolved):
                        warnings.append(
                            {
                                "severity": "Info",
                                "page_url": resolved,
                                "check": "Sitemap index",
                                "detail": "Skipped non-public child sitemap target.",
                            }
                        )
                        continue
                    queue.append(("url", resolved))
                    continue

                if source_type == "file":
                    base_dir = Path(source_value).resolve().parent
                    child_path = (base_dir / child).resolve()
                    if child_path.exists():
                        queue.append(("file", str(child_path)))
                        continue
                warnings.append(
                    {
                        "severity": "Info",
                        "page_url": child,
                        "check": "Sitemap index",
                        "detail": "Skipped unsupported child sitemap reference.",
                    }
                )

    return records, warnings


def merge_records(records: list[PageRecord]) -> dict[str, PageRecord]:
    merged: dict[str, PageRecord] = {}
    for item in records:
        existing = merged.get(item.page_url)
        if existing is None:
            merged[item.page_url] = PageRecord(
                page_url=item.page_url,
                canonical_url=item.canonical_url,
                alternates={k: list(v) for k, v in item.alternates.items()},
                source=item.source,
            )
            continue

        if not existing.canonical_url and item.canonical_url:
            existing.canonical_url = item.canonical_url
        for code, urls in item.alternates.items():
            existing.alternates.setdefault(code, [])
            for value in urls:
                if value not in existing.alternates[code]:
                    existing.alternates[code].append(value)
    return merged

def collect_records_from_page_source(args: argparse.Namespace) -> tuple[list[PageRecord], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    if bool(args.url) == bool(args.html_file):
        raise ValueError("Provide exactly one of --url or --html-file for page validation mode.")

    records: list[PageRecord] = []
    if args.url:
        start_url = normalize_url(args.url)
        if not is_public_target(start_url):
            raise ValueError("target URL resolves to non-public or invalid host")
        html, final_url = fetch_html(start_url, args.timeout)
        if not is_public_target(final_url):
            raise ValueError("redirected target URL resolves to non-public or invalid host")
        root = parse_page_html(html, final_url, "html:url")
        records.append(root)

        targets: list[str] = []
        for values in root.alternates.values():
            for href in values:
                if href not in targets and href != root.page_url:
                    targets.append(href)

        for href in targets[: args.max_fetch]:
            if not is_public_target(href):
                issues.append(
                    {
                        "severity": "Info",
                        "page_url": root.page_url,
                        "check": "Return tags",
                        "detail": f"Skipped non-public alternate target: {href}",
                    }
                )
                continue
            try:
                alt_html, alt_final = fetch_html(href, args.timeout)
                records.append(parse_page_html(alt_html, alt_final, "html:alternate"))
            except (requests.exceptions.RequestException, ValueError) as exc:
                issues.append(
                    {
                        "severity": "Info",
                        "page_url": root.page_url,
                        "check": "Return tags",
                        "detail": f"Could not fetch alternate target {href}: {exc}",
                    }
                )
    else:
        file_path = Path(args.html_file).resolve()
        if not file_path.exists():
            raise ValueError(f"HTML file not found: {file_path}")
        html = file_path.read_text(encoding="utf-8", errors="ignore")
        page_url = normalize_url(args.page_url) if args.page_url else "https://example.com/"
        records.append(parse_page_html(html, page_url, "html:file"))

    return records, issues


def issue(issues: list[dict[str, str]], severity: str, page_url: str, check: str, detail: str) -> None:
    issues.append({"severity": severity, "page_url": page_url, "check": check, "detail": detail})


def validate_records(
    page_map: dict[str, PageRecord],
    strict_iso: bool,
    strict_return: bool,
    seed_issues: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
    issues = list(seed_issues)
    rows: list[dict[str, Any]] = []
    all_codes: set[str] = set()
    page_lookup: dict[str, PageRecord] = {}
    for key, record in page_map.items():
        try:
            page_lookup[compare_key(key)] = record
        except ValueError:
            page_lookup[key] = record

    for page_url in sorted(page_map.keys()):
        record = page_map[page_url]
        page_url_key = compare_key(page_url)
        page_issue_levels: list[str] = []

        if record.canonical_url:
            try:
                canonical_mismatch = compare_key(record.canonical_url) != page_url_key
            except ValueError:
                canonical_mismatch = record.canonical_url != page_url
        else:
            canonical_mismatch = False
        if canonical_mismatch:
            issue(
                issues,
                "High",
                page_url,
                "Canonical alignment",
                f"Canonical URL points to {record.canonical_url}, so hreflang on this URL may be ignored.",
            )
            page_issue_levels.append("High")

        if not record.alternates:
            issue(issues, "High", page_url, "Implementation", "No hreflang alternates found on this page.")
            page_issue_levels.append("High")

        self_ref = False
        x_default_count = 0
        return_missing = 0
        unresolved_targets = 0

        protocols = {urlparse(page_url).scheme}
        hosts = {canonical_host(urlparse(page_url).hostname)}

        normalized_map: dict[str, list[str]] = defaultdict(list)
        for raw_code, urls in record.alternates.items():
            normalized_code, code_issues = validate_hreflang_code(raw_code, strict_iso)
            all_codes.add(normalized_code)
            for entry in code_issues:
                issue(issues, entry["severity"], page_url, "Code validation", entry["detail"])
                page_issue_levels.append(entry["severity"])

            for href in urls:
                if href not in normalized_map[normalized_code]:
                    normalized_map[normalized_code].append(href)
                try:
                    if compare_key(href) == page_url_key:
                        self_ref = True
                except ValueError:
                    if href == page_url:
                        self_ref = True
                protocols.add(urlparse(href).scheme)
                hosts.add(canonical_host(urlparse(href).hostname))

            if normalized_code == "x-default":
                x_default_count += len(urls)

        for code, targets in normalized_map.items():
            if len(targets) > 1:
                issue(
                    issues,
                    "High",
                    page_url,
                    "Duplicate code",
                    f"hreflang '{code}' maps to multiple URLs: {', '.join(targets)}",
                )
                page_issue_levels.append("High")

        if not self_ref:
            issue(
                issues,
                "Critical",
                page_url,
                "Self-reference",
                "Missing self-referencing hreflang URL for this page.",
            )
            page_issue_levels.append("Critical")

        if x_default_count == 0:
            issue(issues, "High", page_url, "x-default", "Missing x-default fallback hreflang tag.")
            page_issue_levels.append("High")
        elif x_default_count > 1:
            issue(issues, "High", page_url, "x-default", "Multiple x-default values detected for this page.")
            page_issue_levels.append("High")

        if len(protocols) > 1:
            issue(issues, "Medium", page_url, "Protocol consistency", "Mixed HTTP/HTTPS URLs in hreflang set.")
            page_issue_levels.append("Medium")

        if len({host for host in hosts if host}) > 1:
            issue(
                issues,
                "Info",
                page_url,
                "Cross-domain",
                "Cross-domain hreflang detected; ensure return tags and Search Console verification on all hosts.",
            )

        for code, targets in normalized_map.items():
            if code == "x-default":
                continue
            for target in targets:
                try:
                    target_key = compare_key(target)
                except ValueError:
                    unresolved_targets += 1
                    continue
                peer = page_lookup.get(target_key)
                if peer is None:
                    unresolved_targets += 1
                    continue
                has_back = False
                for peer_targets in peer.alternates.values():
                    for peer_target in peer_targets:
                        try:
                            peer_key = compare_key(peer_target)
                        except ValueError:
                            continue
                        if peer_key == page_url_key:
                            has_back = True
                            break
                    if has_back:
                        break
                if not has_back:
                    return_missing += 1
                    issue(
                        issues,
                        "Critical",
                        page_url,
                        "Return tags",
                        f"{target} does not include a return hreflang link back to {page_url}",
                    )
                    page_issue_levels.append("Critical")

        if unresolved_targets > 0:
            severity = "High" if strict_return else "Info"
            issue(
                issues,
                severity,
                page_url,
                "Return tags",
                f"Could not verify return tags for {unresolved_targets} alternate URL(s) not present in scan set.",
            )
            page_issue_levels.append(severity)

        primary_lang = "-"
        for code, targets in normalized_map.items():
            if code == "x-default":
                continue
            if page_url in targets:
                primary_lang = code
                break
        if primary_lang == "-":
            primary_lang = next((code for code in normalized_map.keys() if code != "x-default"), "-")

        severity_rank = min((SEVERITY_ORDER.get(level, 99) for level in page_issue_levels), default=99)
        status = "✅"
        if severity_rank <= SEVERITY_ORDER["High"]:
            status = "❌"
        elif severity_rank == SEVERITY_ORDER["Medium"]:
            status = "⚠️"

        rows.append(
            {
                "language": primary_lang,
                "url": page_url,
                "self_ref": self_ref,
                "return_ok": return_missing == 0 and unresolved_targets == 0,
                "x_default_ok": x_default_count == 1,
                "status": status,
            }
        )

    issues.sort(key=lambda item: SEVERITY_ORDER.get(item["severity"], 99))
    counts = Counter(item["severity"] for item in issues)

    summary = {
        "pages_scanned": len(page_map),
        "language_variants_detected": len({code for code in all_codes if code != "x-default"}),
        "issues_total": len(issues),
        "issues_by_severity": {level: counts.get(level, 0) for level in ["Critical", "High", "Medium", "Low", "Info"]},
        "strict_iso_validation": strict_iso,
        "strict_return_validation": strict_return,
    }
    return issues, rows, summary

def write_validation_report(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]], issues: list[dict[str, str]]) -> None:
    by_severity: dict[str, list[dict[str, str]]] = {"Critical": [], "High": [], "Medium": [], "Low": [], "Info": []}
    for item in issues:
        by_severity.setdefault(item["severity"], []).append(item)

    table_rows = "\n".join(
        f"| {row['language']} | {row['url']} | {'✅' if row['self_ref'] else '❌'} | {'✅' if row['return_ok'] else '❌'} | {'✅' if row['x_default_ok'] else '❌'} | {row['status']} |"
        for row in rows
    )
    if not table_rows:
        table_rows = "| - | - | - | - | - | - |"

    report = f"""# Hreflang Validation Report

## Summary
- Total pages scanned: {summary['pages_scanned']}
- Language variants detected: {summary['language_variants_detected']}
- Issues found: {summary['issues_total']} (Critical: {summary['issues_by_severity']['Critical']}, High: {summary['issues_by_severity']['High']}, Medium: {summary['issues_by_severity']['Medium']}, Low: {summary['issues_by_severity']['Low']})

## Validation Results
| Language | URL | Self-Ref | Return Tags | x-default | Status |
|---|---|---|---|---|---|
{table_rows}

## Issues
### Critical
{chr(10).join(f"- `{item['page_url']}` ({item['check']}): {item['detail']}" for item in by_severity['Critical']) or '- None'}

### High
{chr(10).join(f"- `{item['page_url']}` ({item['check']}): {item['detail']}" for item in by_severity['High']) or '- None'}

### Medium
{chr(10).join(f"- `{item['page_url']}` ({item['check']}): {item['detail']}" for item in by_severity['Medium']) or '- None'}

### Low
{chr(10).join(f"- `{item['page_url']}` ({item['check']}): {item['detail']}" for item in by_severity['Low']) or '- None'}

### Info
{chr(10).join(f"- `{item['page_url']}` ({item['check']}): {item['detail']}" for item in by_severity['Info']) or '- None'}
"""
    path.write_text(report, encoding="utf-8")


def load_generate_mapping(path_value: str) -> list[dict[str, Any]]:
    path = Path(path_value).resolve()
    if not path.exists():
        raise ValueError(f"Mapping file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict) and isinstance(raw.get("sets"), list):
        sets = raw["sets"]
    elif isinstance(raw, list):
        sets = raw
    else:
        raise ValueError("Mapping file must be a JSON list or {\"sets\": [...]} object")

    normalized_sets: list[dict[str, Any]] = []
    for idx, entry in enumerate(sets, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid mapping set at index {idx}: expected object")
        set_id = str(entry.get("id") or entry.get("set_id") or f"set-{idx}")

        if isinstance(entry.get("alternates"), dict):
            alternates_raw = entry["alternates"]
        else:
            alternates_raw = {
                key: value
                for key, value in entry.items()
                if key not in {"id", "set_id", "name", "description"}
            }

        if not alternates_raw:
            raise ValueError(f"Mapping set '{set_id}' has no alternates")

        normalized_sets.append({"id": set_id, "alternates": alternates_raw})

    return normalized_sets


def serialize_xml(elem: ET.Element) -> bytes:
    try:
        ET.indent(ET.ElementTree(elem), space="  ")  # type: ignore[attr-defined]
    except Exception:
        pass
    return ET.tostring(elem, encoding="utf-8", xml_declaration=True)


def run_generate(args: argparse.Namespace) -> int:
    try:
        sets = load_generate_mapping(args.mapping_file)
    except Exception as exc:
        print(f"Error: {exc}")
        return 2

    warnings: list[str] = []
    page_map: dict[str, dict[str, str]] = {}
    output_sets: list[dict[str, Any]] = []

    for entry in sets:
        set_id = entry["id"]
        alts: dict[str, str] = {}
        for raw_code, raw_url in entry["alternates"].items():
            code = str(raw_code).strip()
            url = str(raw_url).strip()
            if not code or not url:
                continue
            try:
                normalized_url = normalize_url(url)
            except ValueError as exc:
                print(f"Error: set '{set_id}' has invalid URL for {code}: {exc}")
                return 2

            normalized_code, code_issues = validate_hreflang_code(code, strict_iso=args.strict_iso)
            hard_fail = [item for item in code_issues if item["severity"] in {"Critical", "High"}]
            if hard_fail:
                print(f"Error: set '{set_id}' has invalid hreflang '{code}': {hard_fail[0]['detail']}")
                return 2
            for item in code_issues:
                if item["severity"] in {"Medium", "Low", "Info"}:
                    warnings.append(f"{set_id}: {item['detail']}")

            if normalized_code in alts and alts[normalized_code] != normalized_url:
                print(
                    f"Error: set '{set_id}' maps '{normalized_code}' to multiple URLs: "
                    f"{alts[normalized_code]} and {normalized_url}"
                )
                return 2
            alts[normalized_code] = normalized_url

        if not alts:
            print(f"Error: set '{set_id}' has no valid alternates")
            return 2

        if "x-default" not in alts:
            fallback_code = normalize_hreflang_code(args.default_locale) if args.default_locale else ""
            if fallback_code and fallback_code in alts:
                alts["x-default"] = alts[fallback_code]
            else:
                alts["x-default"] = next(iter(alts.values()))
            warnings.append(f"{set_id}: added x-default automatically")

        if len(alts) < 2:
            warnings.append(f"{set_id}: only one hreflang variant detected")

        output_sets.append({"id": set_id, "alternates": dict(sorted(alts.items()))})

        for _, page_url in alts.items():
            existing = page_map.get(page_url)
            if existing and existing != alts:
                warnings.append(f"{set_id}: page {page_url} appears in multiple sets with different alternates")
            page_map[page_url] = dict(sorted(alts.items()))

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    output_files: list[str] = []
    if args.method == "html":
        html_path = out_dir / "hreflang-tags.html"
        lines: list[str] = []
        for page_url in sorted(page_map.keys()):
            lines.append(f"<!-- {page_url} -->")
            for code, href in page_map[page_url].items():
                lines.append(f'<link rel="alternate" hreflang="{code}" href="{href}" />')
            lines.append("")
        html_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        output_files.append(str(html_path))

    elif args.method == "header":
        header_path = out_dir / "hreflang-headers.txt"
        blocks: list[str] = []
        for page_url in sorted(page_map.keys()):
            parts = [f"<{href}>; rel=\"alternate\"; hreflang=\"{code}\"" for code, href in page_map[page_url].items()]
            blocks.append(f"{page_url}\nLink: {', '.join(parts)}\n")
        header_path.write_text("\n".join(blocks).strip() + "\n", encoding="utf-8")
        output_files.append(str(header_path))

    else:
        ET.register_namespace("", SITEMAP_NS)
        ET.register_namespace("xhtml", XHTML_NS)
        urlset = ET.Element(f"{{{SITEMAP_NS}}}urlset")
        for page_url in sorted(page_map.keys()):
            url_node = ET.SubElement(urlset, f"{{{SITEMAP_NS}}}url")
            loc = ET.SubElement(url_node, f"{{{SITEMAP_NS}}}loc")
            loc.text = page_url
            for code, href in page_map[page_url].items():
                link = ET.SubElement(url_node, f"{{{XHTML_NS}}}link")
                link.set("rel", "alternate")
                link.set("hreflang", code)
                link.set("href", href)
        sitemap_path = out_dir / "hreflang-sitemap.xml"
        sitemap_path.write_bytes(serialize_xml(urlset))
        output_files.append(str(sitemap_path))

    report_path = out_dir / "HREFLANG-GENERATION-REPORT.md"
    summary_path = out_dir / "SUMMARY.json"

    report = f"""# Hreflang Generation Report

## Summary
- Sets processed: {len(output_sets)}
- Pages generated: {len(page_map)}
- Method: {args.method}
- Warnings: {len(warnings)}

## Outputs
{chr(10).join(f"- `{item}`" for item in output_files)}

## Warnings
{chr(10).join(f"- {item}" for item in warnings) if warnings else '- None'}
"""
    report_path.write_text(report, encoding="utf-8")

    summary = {
        "mode": "generate",
        "method": args.method,
        "sets_processed": len(output_sets),
        "pages_generated": len(page_map),
        "warnings": warnings,
        "output_files": output_files,
        "sets": output_sets,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Sets processed: {len(output_sets)}")
    print(f"Pages generated: {len(page_map)}")
    print(f"Method: {args.method}")
    print(f"Report: {report_path}")
    print(f"Summary: {summary_path}")
    return 0

def run_validate(args: argparse.Namespace) -> int:
    page_mode_requested = bool(args.url or args.html_file)
    sitemap_mode_requested = bool(args.sitemap_url or args.sitemap_file)

    if page_mode_requested and sitemap_mode_requested:
        print("Error: choose either page source (--url/--html-file) or sitemap source (--sitemap-url/--sitemap-file), not both")
        return 2
    if not page_mode_requested and not sitemap_mode_requested:
        print("Error: provide a validation source")
        return 2

    try:
        if sitemap_mode_requested:
            if bool(args.sitemap_url) == bool(args.sitemap_file):
                raise ValueError("Provide exactly one of --sitemap-url or --sitemap-file")
            records, seed_issues = load_sitemap_records(args)
        else:
            records, seed_issues = collect_records_from_page_source(args)
    except (ValueError, requests.exceptions.RequestException) as exc:
        print(f"Error: {exc}")
        return 2

    if not records:
        print("Error: no pages with hreflang data were found")
        return 1

    page_map = merge_records(records)
    issues, rows, summary = validate_records(
        page_map=page_map,
        strict_iso=args.strict_iso,
        strict_return=args.strict_return,
        seed_issues=seed_issues,
    )

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "HREFLANG-VALIDATION-REPORT.md"
    summary_path = out_dir / "SUMMARY.json"

    write_validation_report(report_path, summary, rows, issues)

    payload = {
        "mode": "validate",
        "summary": summary,
        "rows": rows,
        "issues": issues,
    }
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Pages scanned: {summary['pages_scanned']}")
    print(f"Language variants detected: {summary['language_variants_detected']}")
    print(
        "Issues: "
        f"{summary['issues_total']} "
        f"(Critical={summary['issues_by_severity']['Critical']}, "
        f"High={summary['issues_by_severity']['High']}, "
        f"Medium={summary['issues_by_severity']['Medium']}, "
        f"Low={summary['issues_by_severity']['Low']})"
    )
    print(f"Validation report: {report_path}")
    print(f"Summary: {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic hreflang validator/generator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate hreflang implementation from page or sitemap source")
    p_validate.add_argument("--url", default="", help="Target page URL")
    p_validate.add_argument("--html-file", default="", help="Local HTML file for page validation mode")
    p_validate.add_argument("--page-url", default="", help="Canonical URL when using --html-file")
    p_validate.add_argument("--sitemap-url", default="", help="Sitemap URL for sitemap validation mode")
    p_validate.add_argument("--sitemap-file", default="", help="Local sitemap XML file")
    p_validate.add_argument("--max-fetch", type=int, default=25, help="Max alternate pages to fetch in URL mode")
    p_validate.add_argument("--max-sitemaps", type=int, default=20, help="Max sitemap files to traverse from index")
    p_validate.add_argument("--strict-return", action="store_true", help="Treat unresolved return-tag targets as High severity")
    p_validate.add_argument("--strict-iso", action="store_true", help="Emit strict ISO notes if pycountry is unavailable")
    p_validate.add_argument("--timeout", type=int, default=20)
    p_validate.add_argument("--output-dir", default="seo-hreflang-output")
    p_validate.set_defaults(func=run_validate)

    p_generate = sub.add_parser("generate", help="Generate hreflang output from mapping JSON")
    p_generate.add_argument("--mapping-file", required=True, help="JSON file describing hreflang sets")
    p_generate.add_argument("--method", choices=["html", "header", "sitemap"], default="sitemap")
    p_generate.add_argument("--default-locale", default="", help="Locale to use for x-default fallback if missing")
    p_generate.add_argument("--strict-iso", action="store_true", help="Emit strict ISO notes if pycountry is unavailable")
    p_generate.add_argument("--output-dir", default="seo-hreflang-output")
    p_generate.set_defaults(func=run_generate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
