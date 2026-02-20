#!/usr/bin/env python3
"""
Sitemap analyzer and generator for the seo-sitemap skill.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
import xml.etree.ElementTree as ET

import requests

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CodexSEO/1.0; +https://github.com/avalonreset/codex-seo)",
    "Accept": "application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}
PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
PRIVATE_NOINDEX_RE = re.compile(r'(?i)<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex')


@dataclass
class SitemapFile:
    source: str
    kind: str
    url_count: int
    deprecated_tag_count: int
    identical_lastmod: bool
    urls: list[dict[str, str | None]]
    children: list[str]


def canonical_host(host: str | None) -> str:
    value = (host or "").strip().lower().rstrip(".")
    if value.startswith("www."):
        return value[4:]
    return value


def same_sitemap_target(a: str, b: str) -> bool:
    pa = urlparse(a)
    pb = urlparse(b)
    return (
        canonical_host(pa.hostname) == canonical_host(pb.hostname)
        and (pa.path or "/") == (pb.path or "/")
        and (pa.query or "") == (pb.query or "")
    )


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


def fetch_text(url: str, timeout: int) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.text


def localname(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if localname(child.tag) == name and child.text:
            return child.text.strip()
    return None


def parse_sitemap_xml(xml_text: str, source: str) -> SitemapFile:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML in {source}: {exc}") from exc

    root_name = localname(root.tag)
    if root_name not in {"urlset", "sitemapindex"}:
        raise ValueError(f"Unsupported sitemap root element in {source}: {root_name}")

    deprecated_count = 0
    urls: list[dict[str, str | None]] = []
    children: list[str] = []
    identical_lastmod = False

    if root_name == "urlset":
        for url_node in root:
            if localname(url_node.tag) != "url":
                continue
            loc = child_text(url_node, "loc")
            if not loc:
                continue
            lastmod = child_text(url_node, "lastmod")
            urls.append({"loc": loc, "lastmod": lastmod})
            for child in url_node:
                child_name = localname(child.tag)
                if child_name in {"priority", "changefreq"}:
                    deprecated_count += 1
        lastmods = [entry["lastmod"] for entry in urls if entry["lastmod"]]
        identical_lastmod = len(lastmods) > 1 and len(set(lastmods)) == 1
        return SitemapFile(
            source=source,
            kind="urlset",
            url_count=len(urls),
            deprecated_tag_count=deprecated_count,
            identical_lastmod=identical_lastmod,
            urls=urls,
            children=[],
        )

    for child_node in root:
        if localname(child_node.tag) != "sitemap":
            continue
        loc = child_text(child_node, "loc")
        if loc:
            children.append(loc)
    return SitemapFile(
        source=source,
        kind="sitemapindex",
        url_count=0,
        deprecated_tag_count=0,
        identical_lastmod=False,
        urls=[],
        children=children,
    )


def read_crawl_urls(path: str | None) -> set[str]:
    if not path:
        return set()
    file_path = Path(path).resolve()
    if not file_path.exists():
        raise ValueError(f"crawl URL file not found: {file_path}")
    lines = file_path.read_text(encoding="utf-8").splitlines()
    urls = set()
    for raw in lines:
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        try:
            urls.add(normalize_url(value))
        except ValueError:
            continue
    return urls


def detect_noindex(target_url: str, timeout: int, include_meta: bool) -> tuple[bool, str | None]:
    try:
        response = requests.get(target_url, headers=HEADERS, timeout=timeout, allow_redirects=False, stream=True)
    except requests.exceptions.RequestException:
        return False, None
    try:
        x_robots = (response.headers.get("X-Robots-Tag") or "").lower()
        if "noindex" in x_robots:
            return True, "x-robots-tag"
        if not include_meta:
            return False, None
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            return False, None
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= 65536:
                break
        if not chunks:
            return False, None
        preview = b"".join(chunks).decode(response.encoding or "utf-8", errors="ignore")
        if PRIVATE_NOINDEX_RE.search(preview):
            return True, "meta-robots"
        return False, None
    finally:
        response.close()


def probe_status(target_url: str, timeout: int) -> tuple[int | None, str | None]:
    try:
        response = requests.head(target_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
        status = response.status_code
        location = response.headers.get("Location")
        if status in (405, 501):
            response = requests.get(target_url, headers=HEADERS, timeout=timeout, allow_redirects=False, stream=True)
            status = response.status_code
            location = response.headers.get("Location")
            response.close()
        return status, location
    except requests.exceptions.RequestException:
        return None, None


def analyze_sitemaps(
    start_source: str,
    timeout: int,
    max_sitemaps: int,
    status_sample_limit: int,
    noindex_scan_limit: int,
    include_meta_noindex: bool,
    crawl_urls: set[str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    queue: deque[str] = deque([start_source])
    visited: set[str] = set()
    files: list[SitemapFile] = []
    parse_errors: list[str] = []

    while queue and len(files) < max_sitemaps:
        source = queue.popleft()
        if source in visited:
            continue
        visited.add(source)
        try:
            xml_text = fetch_text(source, timeout)
            parsed = parse_sitemap_xml(xml_text, source)
        except Exception as exc:
            parse_errors.append(str(exc))
            continue
        files.append(parsed)
        for child in parsed.children:
            try:
                child_url = normalize_url(child)
            except ValueError:
                parse_errors.append(f"Skipped child sitemap with unsupported URL scheme: {child} (from {source})")
                continue
            if not is_public_target(child_url):
                parse_errors.append(f"Skipped non-public child sitemap URL: {child_url} (from {source})")
                continue
            if child_url not in visited:
                queue.append(child_url)

    all_urls: list[str] = []
    deprecated_count = 0
    large_files: list[tuple[str, int]] = []
    identical_lastmod_files: list[str] = []

    for file in files:
        deprecated_count += file.deprecated_tag_count
        if file.url_count > 50000:
            large_files.append((file.source, file.url_count))
        if file.identical_lastmod:
            identical_lastmod_files.append(file.source)
        all_urls.extend([entry["loc"] for entry in file.urls if entry["loc"]])

    normalized_urls: list[str] = []
    for raw in all_urls:
        try:
            normalized_urls.append(normalize_url(raw))
        except ValueError:
            continue
    unique_urls = sorted(set(normalized_urls))

    non_https = [u for u in unique_urls if urlparse(u).scheme != "https"]
    sample = unique_urls[: max(0, status_sample_limit)]
    non_200: list[str] = []
    redirected: list[str] = []
    noindex_urls: list[str] = []

    for idx, url in enumerate(sample):
        status, location = probe_status(url, timeout)
        if status is None:
            non_200.append(f"{url} (unreachable)")
            continue
        if 300 <= status < 400:
            redirected.append(f"{url} -> {location or '(missing location header)'} ({status})")
            continue
        if status != 200:
            non_200.append(f"{url} ({status})")
            continue
        if idx < noindex_scan_limit:
            is_noindex, origin = detect_noindex(url, timeout, include_meta_noindex)
            if is_noindex:
                noindex_urls.append(f"{url} ({origin})")

    issues: list[dict[str, str]] = []

    if parse_errors:
        for err in parse_errors:
            issues.append({"priority": "Critical", "title": "Invalid sitemap XML", "detail": err})
    if large_files:
        for source, count in large_files:
            issues.append(
                {
                    "priority": "Critical",
                    "title": "Sitemap exceeds protocol URL limit",
                    "detail": f"{source} has {count} URLs (max 50,000). Split this sitemap.",
                }
            )
    if non_200:
        issues.append(
            {
                "priority": "High",
                "title": "Non-200 URLs in sitemap sample",
                "detail": f"{len(non_200)} sampled URLs returned non-200 or were unreachable.",
            }
        )
    if noindex_urls:
        issues.append(
            {
                "priority": "High",
                "title": "Noindex URLs found in sitemap sample",
                "detail": f"{len(noindex_urls)} sampled URLs include noindex signals.",
            }
        )
    if non_https:
        issues.append(
            {
                "priority": "High",
                "title": "HTTP URLs found in sitemap",
                "detail": f"{len(non_https)} URLs are not HTTPS.",
            }
        )
    if redirected:
        issues.append(
            {
                "priority": "Medium",
                "title": "Redirected URLs in sitemap sample",
                "detail": f"{len(redirected)} sampled URLs returned redirects.",
            }
        )
    if identical_lastmod_files:
        issues.append(
            {
                "priority": "Low",
                "title": "Identical lastmod values detected",
                "detail": f"{len(identical_lastmod_files)} sitemap files have identical lastmod values for all URLs.",
            }
        )
    if deprecated_count > 0:
        issues.append(
            {
                "priority": "Info",
                "title": "Deprecated sitemap tags used",
                "detail": f"Detected {deprecated_count} instances of <priority>/<changefreq> (ignored by Google).",
            }
        )

    robots_sitemap_ref = None
    robots_checked = False
    if urlparse(start_source).scheme in ("http", "https"):
        robots_checked = True
        parsed = urlparse(start_source)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            robots_body = fetch_text(robots_url, timeout)
            declared: set[str] = set()
            for raw_line in robots_body.splitlines():
                line = raw_line.strip()
                if not line.lower().startswith("sitemap:"):
                    continue
                candidate = line.split(":", 1)[1].strip()
                try:
                    declared.add(normalize_url(candidate))
                except ValueError:
                    continue
            robots_sitemap_ref = start_source in declared or any(same_sitemap_target(start_source, item) for item in declared)
            if not robots_sitemap_ref:
                issues.append(
                    {
                        "priority": "Medium",
                        "title": "Sitemap not referenced in robots.txt",
                        "detail": f"robots.txt does not include an explicit reference to {start_source}.",
                    }
                )
        except Exception:
            robots_sitemap_ref = False
            issues.append(
                {
                    "priority": "Low",
                    "title": "Could not verify robots.txt sitemap reference",
                    "detail": f"Failed to fetch robots.txt for {parsed.netloc}.",
                }
            )

    missing_from_sitemap: list[str] = []
    extra_vs_crawl: list[str] = []
    if crawl_urls:
        sitemap_set = set(unique_urls)
        missing_from_sitemap = sorted(crawl_urls - sitemap_set)
        extra_vs_crawl = sorted(sitemap_set - crawl_urls)
        if missing_from_sitemap:
            priority = "High" if len(missing_from_sitemap) > 50 else "Medium"
            issues.append(
                {
                    "priority": priority,
                    "title": "Crawled pages missing from sitemap",
                    "detail": f"{len(missing_from_sitemap)} crawled URLs were not found in the sitemap set.",
                }
            )

    issues.sort(key=lambda item: PRIORITY_ORDER.get(item["priority"], 99))

    summary = {
        "start_source": start_source,
        "files_analyzed": len(files),
        "url_count_total": len(unique_urls),
        "sample_checked": len(sample),
        "parse_error_count": len(parse_errors),
        "non_200_count": len(non_200),
        "redirected_count": len(redirected),
        "noindex_count": len(noindex_urls),
        "http_url_count": len(non_https),
        "deprecated_tag_count": deprecated_count,
        "identical_lastmod_file_count": len(identical_lastmod_files),
        "robots_checked": robots_checked,
        "robots_sitemap_reference_present": robots_sitemap_ref,
        "crawl_input_count": len(crawl_urls),
        "missing_from_sitemap_count": len(missing_from_sitemap),
        "extra_vs_crawl_count": len(extra_vs_crawl),
        "issues": issues,
    }

    evidence = {
        "parse_errors": parse_errors[:50],
        "non_200": non_200[:200],
        "redirected": redirected[:200],
        "noindex_urls": noindex_urls[:200],
        "http_urls": non_https[:200],
        "missing_from_sitemap": missing_from_sitemap[:200],
        "extra_vs_crawl": extra_vs_crawl[:200],
        "identical_lastmod_files": identical_lastmod_files[:100],
    }
    return {"summary": summary, "evidence": evidence, "files": [file.__dict__ for file in files]}, issues


def location_like(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    markers = ["/location", "/locations", "/city/", "/near-", "/areas/", "/service-area", "/in-"]
    return any(marker in path for marker in markers)


def load_url_list(path: str) -> list[str]:
    values = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        values.append(value)
    return values


def split_chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_urlset(urls: list[str], lastmod_value: str | None) -> ET.Element:
    root = ET.Element("urlset", xmlns=SITEMAP_NS)
    for url in urls:
        url_node = ET.SubElement(root, "url")
        loc_node = ET.SubElement(url_node, "loc")
        loc_node.text = url
        if lastmod_value:
            lastmod_node = ET.SubElement(url_node, "lastmod")
            lastmod_node.text = lastmod_value
    return root


def build_index(entries: list[tuple[str, str]]) -> ET.Element:
    root = ET.Element("sitemapindex", xmlns=SITEMAP_NS)
    for loc, lastmod in entries:
        sitemap_node = ET.SubElement(root, "sitemap")
        loc_node = ET.SubElement(sitemap_node, "loc")
        loc_node.text = loc
        lastmod_node = ET.SubElement(sitemap_node, "lastmod")
        lastmod_node.text = lastmod
    return root


def write_xml(path: Path, root: ET.Element) -> None:
    try:
        ET.indent(root, space="  ")  # type: ignore[attr-defined]
    except Exception:
        pass
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    path.write_bytes(xml_bytes)


def render_validation_report(result: dict[str, Any], output_path: Path) -> None:
    summary = result["summary"]
    evidence = result["evidence"]

    ordered = {"Critical": [], "High": [], "Medium": [], "Low": [], "Info": []}
    for issue in summary["issues"]:
        ordered[issue["priority"]].append(issue)

    report = f"""# Sitemap Validation Report

## Executive Summary
- Start source: `{summary['start_source']}`
- Files analyzed: {summary['files_analyzed']}
- Total unique URLs in sitemap set: {summary['url_count_total']}
- Status sample checked: {summary['sample_checked']}

## Key Checks
- Non-200 URLs: {summary['non_200_count']}
- Redirected URLs: {summary['redirected_count']}
- Noindex URLs (sample): {summary['noindex_count']}
- HTTP URLs: {summary['http_url_count']}
- Deprecated tags (`priority`/`changefreq`): {summary['deprecated_tag_count']}
- Identical lastmod files: {summary['identical_lastmod_file_count']}
- robots.txt checked: {summary['robots_checked']}
- robots.txt contains sitemap reference: {summary['robots_sitemap_reference_present']}

## Issues
### Critical
{chr(10).join(f"- **{x['title']}**: {x['detail']}" for x in ordered['Critical']) or "- None"}
### High
{chr(10).join(f"- **{x['title']}**: {x['detail']}" for x in ordered['High']) or "- None"}
### Medium
{chr(10).join(f"- **{x['title']}**: {x['detail']}" for x in ordered['Medium']) or "- None"}
### Low
{chr(10).join(f"- **{x['title']}**: {x['detail']}" for x in ordered['Low']) or "- None"}
### Info
{chr(10).join(f"- **{x['title']}**: {x['detail']}" for x in ordered['Info']) or "- None"}

## Sample Evidence
- Non-200 sample: {len(evidence['non_200'])}
- Redirect sample: {len(evidence['redirected'])}
- Noindex sample: {len(evidence['noindex_urls'])}
- HTTP URLs sample: {len(evidence['http_urls'])}
- Missing-from-sitemap sample: {len(evidence['missing_from_sitemap'])}
"""
    output_path.write_text(report, encoding="utf-8")


def render_structure_doc(
    output_path: Path,
    base_url: str,
    urls: list[str],
    chunks: list[list[str]],
    split_size: int,
    location_count: int,
    warnings: list[str],
) -> None:
    example_chunks = [f"- Chunk {idx + 1}: {len(chunk)} URLs" for idx, chunk in enumerate(chunks[:10])]
    if len(chunks) > 10:
        example_chunks.append(f"- ... {len(chunks) - 10} more chunks")
    content = f"""# Sitemap Structure

- Base URL: `{base_url}`
- Total URLs: {len(urls)}
- Split size: {split_size}
- Generated sitemap files: {len(chunks)}
- Location-like URLs: {location_count}

## Split Summary
{chr(10).join(example_chunks) if example_chunks else "- No URL chunks generated"}

## Warnings
{chr(10).join(f"- {w}" for w in warnings) if warnings else "- None"}
"""
    output_path.write_text(content, encoding="utf-8")


def run_analyze(args: argparse.Namespace) -> int:
    if args.sitemap_url:
        try:
            start_source = normalize_url(args.sitemap_url)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 2
        if not is_public_target(start_source):
            print("Error: sitemap URL resolves to non-public or invalid host")
            return 2
    elif args.sitemap_file:
        path = Path(args.sitemap_file).resolve()
        if not path.exists():
            print(f"Error: sitemap file not found: {path}")
            return 2
        start_source = path.as_uri()
    else:
        print("Error: provide either --sitemap-url or --sitemap-file")
        return 2

    if args.sitemap_file:
        xml_text = Path(args.sitemap_file).read_text(encoding="utf-8")
        try:
            first = parse_sitemap_xml(xml_text, args.sitemap_file)
        except Exception as exc:
            print(f"Error: {exc}")
            return 1
        files = [first]
        all_urls_set: set[str] = set()
        malformed_loc_count = 0
        for entry in first.urls:
            raw_loc = entry.get("loc")
            if not raw_loc:
                continue
            try:
                all_urls_set.add(normalize_url(raw_loc))
            except ValueError:
                malformed_loc_count += 1
        all_urls = sorted(all_urls_set)
        try:
            crawl_urls = read_crawl_urls(args.crawl_urls_file)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 2
        issues: list[dict[str, str]] = []
        if first.url_count > 50000:
            issues.append(
                {
                    "priority": "Critical",
                    "title": "Sitemap exceeds protocol URL limit",
                    "detail": f"{args.sitemap_file} has {first.url_count} URLs (max 50,000). Split this sitemap.",
                }
            )
        if first.identical_lastmod:
            issues.append(
                {
                    "priority": "Low",
                    "title": "Identical lastmod values detected",
                    "detail": "All URLs in this sitemap share the same lastmod value.",
                }
            )
        if first.deprecated_tag_count > 0:
            issues.append(
                {
                    "priority": "Info",
                    "title": "Deprecated sitemap tags used",
                    "detail": f"Detected {first.deprecated_tag_count} instances of <priority>/<changefreq>.",
                }
            )
        if malformed_loc_count > 0:
            issues.append(
                {
                    "priority": "High",
                    "title": "Malformed URLs found in sitemap loc entries",
                    "detail": f"{malformed_loc_count} <loc> entries could not be normalized and were skipped.",
                }
            )
        missing = sorted(crawl_urls - set(all_urls))
        if missing:
            issues.append(
                {
                    "priority": "Medium",
                    "title": "Crawled pages missing from sitemap",
                    "detail": f"{len(missing)} crawled URLs were not found in the local sitemap.",
                }
            )
        issues.sort(key=lambda item: PRIORITY_ORDER.get(item["priority"], 99))
        result = {
            "summary": {
                "start_source": args.sitemap_file,
                "files_analyzed": len(files),
                "url_count_total": len(all_urls),
                "sample_checked": 0,
                "parse_error_count": 0,
                "non_200_count": 0,
                "redirected_count": 0,
                "noindex_count": 0,
                "http_url_count": len([u for u in all_urls if urlparse(u).scheme != "https"]),
                "deprecated_tag_count": first.deprecated_tag_count,
                "identical_lastmod_file_count": 1 if first.identical_lastmod else 0,
                "robots_checked": False,
                "robots_sitemap_reference_present": None,
                "crawl_input_count": len(crawl_urls),
                "missing_from_sitemap_count": len(missing),
                "extra_vs_crawl_count": len(set(all_urls) - crawl_urls) if crawl_urls else 0,
                "issues": issues,
            },
            "evidence": {
                "parse_errors": [],
                "non_200": [],
                "redirected": [],
                "noindex_urls": [],
                "http_urls": [u for u in all_urls if urlparse(u).scheme != "https"][:200],
                "missing_from_sitemap": missing[:200],
                "extra_vs_crawl": sorted(set(all_urls) - crawl_urls)[:200] if crawl_urls else [],
                "identical_lastmod_files": [args.sitemap_file] if first.identical_lastmod else [],
            },
            "files": [first.__dict__],
        }
    else:
        try:
            crawl_urls = read_crawl_urls(args.crawl_urls_file)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 2
        result, _ = analyze_sitemaps(
            start_source=start_source,
            timeout=args.timeout,
            max_sitemaps=args.max_sitemaps,
            status_sample_limit=args.status_sample_limit,
            noindex_scan_limit=args.noindex_scan_limit,
            include_meta_noindex=args.include_meta_noindex,
            crawl_urls=crawl_urls,
        )

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "VALIDATION-REPORT.md"
    summary_path = out_dir / "SUMMARY.json"

    render_validation_report(result, report_path)
    summary_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Sitemap source: {result['summary']['start_source']}")
    print(f"Files analyzed: {result['summary']['files_analyzed']}")
    print(f"Total URLs: {result['summary']['url_count_total']}")
    print(f"Issues found: {len(result['summary']['issues'])}")
    print(f"Validation report: {report_path}")
    print(f"Summary: {summary_path}")
    return 0


def run_generate(args: argparse.Namespace) -> int:
    try:
        base_url = normalize_url(args.base_url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    if not is_public_target(base_url):
        print("Error: base URL resolves to non-public or invalid host")
        return 2

    raw_urls = load_url_list(args.urls_file)
    if not raw_urls:
        print("Error: urls-file is empty")
        return 2

    base_host = canonical_host(urlparse(base_url).hostname)
    normalized: list[str] = []
    skipped_out_of_scope = 0
    for raw in raw_urls:
        try:
            url = normalize_url(raw)
        except ValueError:
            continue
        if canonical_host(urlparse(url).hostname) != base_host:
            skipped_out_of_scope += 1
            continue
        normalized.append(url)

    urls = sorted(set(normalized))
    if not urls:
        print("Error: no valid in-scope URLs to include in sitemap")
        return 2

    if args.split_size <= 0 or args.split_size > 50000:
        print("Error: split-size must be between 1 and 50000")
        return 2

    location_count = sum(1 for url in urls if location_like(url))
    warnings: list[str] = []
    if location_count >= 50 and not args.allow_location_scale:
        print(
            "Error: hard stop triggered: 50+ location-like URLs detected. "
            "Pass --allow-location-scale only with explicit business justification."
        )
        return 2
    if location_count >= 30:
        warnings.append(
            "Location page warning: 30+ location-like URLs detected. Ensure at least 60% unique content per page."
        )
    if skipped_out_of_scope > 0:
        warnings.append(f"Skipped {skipped_out_of_scope} out-of-scope URLs (host mismatch).")

    chunked = split_chunks(urls, args.split_size)
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    lastmod_value = args.default_lastmod or date.today().isoformat()
    written_files: list[str] = []
    index_entries: list[tuple[str, str]] = []

    if len(chunked) == 1:
        sitemap_path = out_dir / "sitemap.xml"
        write_xml(sitemap_path, build_urlset(chunked[0], lastmod_value))
        written_files.append(str(sitemap_path))
    else:
        for idx, chunk in enumerate(chunked, start=1):
            part_name = f"sitemap-{idx}.xml"
            part_path = out_dir / part_name
            write_xml(part_path, build_urlset(chunk, lastmod_value))
            written_files.append(str(part_path))
            part_url = f"{base_url.rstrip('/')}/{part_name}"
            index_entries.append((part_url, lastmod_value))
        index_path = out_dir / "sitemap_index.xml"
        write_xml(index_path, build_index(index_entries))
        written_files.append(str(index_path))

    structure_path = out_dir / "STRUCTURE.md"
    render_structure_doc(
        output_path=structure_path,
        base_url=base_url,
        urls=urls,
        chunks=chunked,
        split_size=args.split_size,
        location_count=location_count,
        warnings=warnings,
    )
    written_files.append(str(structure_path))

    summary = {
        "base_url": base_url,
        "total_urls": len(urls),
        "split_size": args.split_size,
        "sitemap_files": len(chunked),
        "location_like_url_count": location_count,
        "warnings": warnings,
        "output_files": written_files,
    }
    summary_path = out_dir / "SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Base URL: {base_url}")
    print(f"Total URLs included: {len(urls)}")
    print(f"Sitemap files: {len(chunked)}")
    print(f"Location-like URLs: {location_count}")
    print(f"Structure doc: {structure_path}")
    print(f"Summary: {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze or generate XML sitemaps.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Analyze an existing sitemap URL or local file")
    p_analyze.add_argument("--sitemap-url", default="", help="Sitemap URL to analyze")
    p_analyze.add_argument("--sitemap-file", default="", help="Local sitemap file to analyze")
    p_analyze.add_argument("--crawl-urls-file", default="", help="Optional newline-delimited crawl URL list")
    p_analyze.add_argument("--timeout", type=int, default=20)
    p_analyze.add_argument("--max-sitemaps", type=int, default=20, help="Max sitemap files to fetch from index chains")
    p_analyze.add_argument("--status-sample-limit", type=int, default=200, help="Max URLs sampled for status checks")
    p_analyze.add_argument("--noindex-scan-limit", type=int, default=50, help="Max URLs sampled for noindex checks")
    p_analyze.add_argument("--include-meta-noindex", action="store_true", help="Parse HTML snippets for meta robots noindex")
    p_analyze.add_argument("--output-dir", default="seo-sitemap-output")
    p_analyze.set_defaults(func=run_analyze)

    p_generate = sub.add_parser("generate", help="Generate sitemap XML from a URL list")
    p_generate.add_argument("--base-url", required=True, help="Canonical base URL")
    p_generate.add_argument("--urls-file", required=True, help="Newline-delimited URLs to include")
    p_generate.add_argument("--split-size", type=int, default=50000, help="URLs per sitemap file (max 50000)")
    p_generate.add_argument("--default-lastmod", default="", help="Optional YYYY-MM-DD for lastmod")
    p_generate.add_argument("--allow-location-scale", action="store_true", help="Allow 50+ location-like URLs")
    p_generate.add_argument("--output-dir", default="seo-sitemap-output")
    p_generate.set_defaults(func=run_generate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
