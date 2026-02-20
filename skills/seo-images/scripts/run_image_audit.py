#!/usr/bin/env python3
"""
Deterministic image SEO/performance auditor for the seo-images skill.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CodexSEO/1.0; +https://github.com/avalonreset/codex-seo)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}
MAX_REDIRECT_HOPS = 10

GENERIC_ALT = {
    "image",
    "photo",
    "picture",
    "logo",
    "click here",
    "graphic",
}

FORMAT_MODERN = {"webp", "avif", "svg"}
FORMAT_LEGACY = {"jpg", "jpeg", "png", "gif", "bmp"}
CDN_MARKERS = ["cdn", "cloudfront", "imgix", "cloudinary", "akamai", "fastly"]

SIZE_THRESHOLDS_KB = {
    "thumbnail": {"target": 50, "warning": 100, "critical": 200},
    "content": {"target": 100, "warning": 200, "critical": 500},
    "hero": {"target": 200, "warning": 300, "critical": 700},
}

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


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


def parse_html_input(args: argparse.Namespace) -> tuple[str, str]:
    if bool(args.url) == bool(args.html_file):
        raise ValueError("Provide exactly one of --url or --html-file.")
    if args.url:
        target = normalize_url(args.url)
        if not is_public_target(target):
            raise ValueError("target URL resolves to non-public or invalid host")
        html, final_url = fetch_html(target, args.timeout)
        if not is_public_target(final_url):
            raise ValueError("redirected target URL resolves to non-public or invalid host")
        return html, final_url

    path = Path(args.html_file).resolve()
    if not path.exists():
        raise ValueError(f"HTML file not found: {path}")
    html = path.read_text(encoding="utf-8", errors="ignore")
    if args.page_url:
        page_url = normalize_url(args.page_url)
    else:
        page_url = "https://example.com/"
    return html, page_url


def parse_dimension(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    raw = raw.replace("px", "")
    match = re.match(r"^\d+$", raw)
    if not match:
        return None
    try:
        num = int(raw)
    except ValueError:
        return None
    return num if num > 0 else None


def has_aspect_ratio(img: Tag) -> bool:
    style = str(img.get("style") or "").lower()
    return "aspect-ratio" in style


def image_extension(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix


def filename_score(url: str) -> tuple[bool, str]:
    name = Path(urlparse(url).path).name.lower()
    if not name:
        return False, "Missing file name."
    stem = Path(name).stem
    if re.fullmatch(r"(img|dsc|image|photo|screenshot)[-_]?\d*", stem):
        return False, "Generic file name pattern."
    if re.fullmatch(r"[a-z0-9]{16,}", stem):
        return False, "Opaque hash-like file name."
    if "_" in stem:
        return False, "Prefer hyphen-separated file names."
    return True, "Descriptive enough."


def alt_quality(alt: str | None, decorative: bool, keyword: str | None) -> list[str]:
    if decorative:
        return []
    issues: list[str] = []
    if alt is None:
        return ["Missing alt attribute."]
    value = alt.strip()
    if not value:
        return ["Empty alt text."]
    if len(value) < 10:
        issues.append("Alt text shorter than 10 characters.")
    if len(value) > 125:
        issues.append("Alt text longer than 125 characters.")
    low = value.lower()
    if low in GENERIC_ALT:
        issues.append("Generic alt text; not descriptive.")
    if re.search(r"\.(jpg|jpeg|png|webp|avif|gif|svg)$", low):
        issues.append("Alt text looks like a file name.")
    tokens = re.findall(r"[a-z0-9']+", low)
    if len(tokens) >= 4:
        top = Counter(tokens).most_common(1)[0][1]
        if top / max(1, len(tokens)) > 0.5:
            issues.append("Possible keyword stuffing in alt text.")
    if keyword and keyword.lower() not in low and len(tokens) >= 6:
        issues.append("Focus keyword not reflected in descriptive alt text.")
    return issues


def classify_category(img: Tag, index: int) -> str:
    classes = " ".join([str(x).lower() for x in img.get("class", [])])
    identifier = f"{img.get('id','')} {classes}".lower()
    width = parse_dimension(img.get("width")) or 0
    height = parse_dimension(img.get("height")) or 0
    area = width * height
    if any(marker in identifier for marker in ["hero", "banner", "lcp"]):
        return "hero"
    if index == 0 and (area >= 300_000 or width >= 1000):
        return "hero"
    if any(marker in identifier for marker in ["thumb", "thumbnail", "avatar", "icon"]):
        return "thumbnail"
    if width and width <= 220:
        return "thumbnail"
    return "content"


def image_source_url(img: Tag, base_url: str) -> str | None:
    candidates = [
        img.get("src"),
        img.get("data-src"),
        img.get("data-original"),
        img.get("data-lazy-src"),
    ]
    for raw in candidates:
        value = str(raw or "").strip()
        if not value:
            continue
        if value.startswith("data:"):
            continue
        return urljoin(base_url, value)

    srcset = str(img.get("srcset") or "").strip()
    if srcset:
        for part in srcset.split(","):
            candidate = part.strip().split(" ", 1)[0]
            if not candidate or candidate.startswith("data:"):
                continue
            return urljoin(base_url, candidate)
    return None


def picture_support(img: Tag) -> tuple[bool, bool]:
    parent = img.parent
    while parent is not None and isinstance(parent, Tag):
        if parent.name and parent.name.lower() == "picture":
            avif = False
            webp = False
            for source in parent.find_all("source"):
                type_attr = str(source.get("type") or "").lower()
                srcset = str(source.get("srcset") or "").lower()
                if "avif" in type_attr or ".avif" in srcset:
                    avif = True
                if "webp" in type_attr or ".webp" in srcset:
                    webp = True
            return avif, webp
        parent = parent.parent
    return False, False


def probe_image(url: str, timeout: int) -> dict[str, Any]:
    if not is_public_target(url):
        return {
            "status_code": None,
            "size_bytes": None,
            "content_type": None,
            "cache_control": None,
            "host": canonical_host(urlparse(url).hostname),
            "sampled": True,
        }
    try:
        current_url = url
        redirects = 0
        while True:
            with requests.head(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False) as response:
                status = response.status_code
                headers = dict(response.headers)
            if 300 <= status < 400:
                location = (headers.get("Location") or "").strip()
                if not location or redirects >= MAX_REDIRECT_HOPS:
                    break
                try:
                    next_url = normalize_url(urljoin(current_url, location))
                except ValueError:
                    return {
                        "status_code": None,
                        "size_bytes": None,
                        "content_type": None,
                        "cache_control": None,
                        "host": canonical_host(urlparse(url).hostname),
                        "sampled": True,
                    }
                if not is_public_target(next_url):
                    return {
                        "status_code": None,
                        "size_bytes": None,
                        "content_type": None,
                        "cache_control": None,
                        "host": canonical_host(urlparse(url).hostname),
                        "sampled": True,
                    }
                current_url = next_url
                redirects += 1
                continue
            break
        if status in (405, 501):
            current_url = url
            redirects = 0
            while True:
                with requests.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False, stream=True) as response:
                    status = response.status_code
                    headers = dict(response.headers)
                if 300 <= status < 400:
                    location = (headers.get("Location") or "").strip()
                    if not location or redirects >= MAX_REDIRECT_HOPS:
                        break
                    try:
                        next_url = normalize_url(urljoin(current_url, location))
                    except ValueError:
                        return {
                            "status_code": None,
                            "size_bytes": None,
                            "content_type": None,
                            "cache_control": None,
                            "host": canonical_host(urlparse(url).hostname),
                            "sampled": True,
                        }
                    if not is_public_target(next_url):
                        return {
                            "status_code": None,
                            "size_bytes": None,
                            "content_type": None,
                            "cache_control": None,
                            "host": canonical_host(urlparse(url).hostname),
                            "sampled": True,
                        }
                    current_url = next_url
                    redirects += 1
                    continue
                break
        content_length = headers.get("Content-Length")
        size_bytes = int(content_length) if content_length and str(content_length).isdigit() else None
        return {
            "status_code": status,
            "size_bytes": size_bytes,
            "content_type": headers.get("Content-Type"),
            "cache_control": headers.get("Cache-Control"),
            "host": canonical_host(urlparse(current_url).hostname),
            "sampled": True,
        }
    except requests.exceptions.RequestException:
        return {
            "status_code": None,
            "size_bytes": None,
            "content_type": None,
            "cache_control": None,
            "host": canonical_host(urlparse(url).hostname),
            "sampled": True,
        }


def estimate_savings_kb(size_kb: float | None, category: str, ext: str) -> float:
    thresholds = SIZE_THRESHOLDS_KB[category]
    estimate = 0.0
    if size_kb is not None and size_kb > thresholds["target"]:
        estimate += max(0.0, size_kb - thresholds["target"])
    if ext in {"jpg", "jpeg", "png"} and size_kb is not None:
        estimate += size_kb * 0.25
    return round(estimate, 1)


def score_images(metrics: dict[str, Any]) -> float:
    total = max(1, metrics["total_images"])
    score = 100.0
    score -= (metrics["missing_alt"] / total) * 30
    score -= (metrics["oversized_critical"] / total) * 25
    score -= (metrics["oversized_warning"] / total) * 10
    score -= (metrics["no_dimensions"] / total) * 20
    score -= (metrics["below_fold_not_lazy"] / total) * 10
    score -= (metrics["legacy_format"] / total) * 10
    return round(clamp(score, 0.0, 100.0), 1)


def build_recommendations(metrics: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    if metrics["convert_candidates"] > 0:
        recs.append(
            f"Convert {metrics['convert_candidates']} legacy-format images to WebP/AVIF where suitable."
        )
    if metrics["missing_alt"] > 0:
        recs.append(f"Add descriptive alt text to {metrics['missing_alt']} images.")
    if metrics["no_dimensions"] > 0:
        recs.append(f"Set width/height or aspect-ratio for {metrics['no_dimensions']} images to reduce CLS.")
    if metrics["below_fold_not_lazy"] > 0:
        recs.append(f"Enable loading=\"lazy\" on {metrics['below_fold_not_lazy']} below-fold images.")
    if metrics["hero_lazy"] > 0:
        recs.append(f"Remove lazy loading from {metrics['hero_lazy']} hero/LCP images.")
    if metrics["oversized_critical"] > 0:
        recs.append(f"Compress {metrics['oversized_critical']} critically oversized images first.")
    if metrics["cdn_used"] is False and metrics["total_images"] >= 20:
        recs.append("Serve images via a CDN with strong caching headers for image-heavy pages.")
    if not recs:
        recs.append("Image implementation looks healthy; continue periodic checks for new assets.")
    return recs


def render_report(
    out_report: Path,
    out_plan: Path,
    page_url: str,
    score: float,
    metrics: dict[str, Any],
    issues: list[dict[str, str]],
    prioritized: list[dict[str, Any]],
    recommendations: list[str],
) -> None:
    ordered = {"Critical": [], "High": [], "Medium": [], "Low": [], "Info": []}
    for issue in issues:
        ordered[issue["priority"]].append(issue)

    top_rows = prioritized[:25]
    top_table = "\n".join(
        f"| {row['url']} | {row['size_kb']} KB | {row['format']} | {', '.join(row['issues']) or 'None'} | {row['est_savings_kb']} KB |"
        for row in top_rows
    ) or "| None | - | - | - | - |"

    report = f"""# Image SEO Audit Report

## Executive Summary
- URL: `{page_url}`
- Image score: **{score}/100**
- Total images: {metrics['total_images']}

## Metrics
| Metric | Status | Count |
|---|---|---:|
| Missing alt text | {'❌' if metrics['missing_alt'] else '✅'} | {metrics['missing_alt']} |
| Alt quality warnings | {'⚠️' if metrics['alt_quality_warnings'] else '✅'} | {metrics['alt_quality_warnings']} |
| Oversized warning | {'⚠️' if metrics['oversized_warning'] else '✅'} | {metrics['oversized_warning']} |
| Oversized critical | {'❌' if metrics['oversized_critical'] else '✅'} | {metrics['oversized_critical']} |
| Legacy format images | {'⚠️' if metrics['legacy_format'] else '✅'} | {metrics['legacy_format']} |
| Missing dimensions | {'⚠️' if metrics['no_dimensions'] else '✅'} | {metrics['no_dimensions']} |
| Below-fold not lazy | {'⚠️' if metrics['below_fold_not_lazy'] else '✅'} | {metrics['below_fold_not_lazy']} |
| Hero images lazy-loaded | {'❌' if metrics['hero_lazy'] else '✅'} | {metrics['hero_lazy']} |

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

## Prioritized Optimization List
| Image | Current Size | Format | Issues | Est. Savings |
|---|---:|---|---|---:|
{top_table}
"""
    out_report.write_text(report, encoding="utf-8")

    plan = f"""# Image Optimization Plan

## Priority Actions
{chr(10).join(f"{idx}. {item}" for idx, item in enumerate(recommendations, start=1))}

## Tracking
- Estimated total savings (top candidates): {round(sum(x['est_savings_kb'] for x in prioritized), 1)} KB
- CDN used: {metrics['cdn_used']}
- Cache headers present on sampled images: {metrics['cache_header_coverage_pct']}%
"""
    out_plan.write_text(plan, encoding="utf-8")


def run_audit(args: argparse.Namespace) -> int:
    try:
        html, page_url = parse_html_input(args)
    except requests.exceptions.RequestException as exc:
        print(f"Error: failed to fetch page: {exc}")
        return 1
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    soup = BeautifulSoup(html, "lxml")
    image_tags = soup.find_all("img")

    page_host = canonical_host(urlparse(page_url).hostname)
    image_rows: list[dict[str, Any]] = []
    host_counter: Counter[str] = Counter()
    cache_checked = 0
    cache_with_header = 0

    total_images = len(image_tags)
    missing_alt = 0
    alt_quality_warnings = 0
    oversized_warning = 0
    oversized_critical = 0
    legacy_format = 0
    no_dimensions = 0
    below_fold_not_lazy = 0
    hero_lazy = 0
    hero_missing_fetchpriority = 0
    decoding_missing_nonhero = 0
    missing_srcset = 0
    missing_sizes = 0
    poor_filenames = 0
    convert_candidates = 0

    probe_cache: dict[str, dict[str, Any]] = {}

    for idx, img in enumerate(image_tags):
        src = image_source_url(img, page_url)
        if not src:
            continue
        parsed_host = canonical_host(urlparse(src).hostname)
        if parsed_host:
            host_counter[parsed_host] += 1

        decorative = str(img.get("role") or "").lower() == "presentation" or str(img.get("aria-hidden") or "").lower() == "true"
        alt_issues = alt_quality(img.get("alt"), decorative, args.keyword)
        if not decorative and ("Missing alt attribute." in alt_issues or "Empty alt text." in alt_issues):
            missing_alt += 1
        elif alt_issues:
            alt_quality_warnings += 1

        category = classify_category(img, idx)
        ext = image_extension(src)
        format_label = ext or "unknown"
        if ext in FORMAT_LEGACY:
            legacy_format += 1
            if ext in {"jpg", "jpeg", "png"}:
                convert_candidates += 1

        width = parse_dimension(img.get("width"))
        height = parse_dimension(img.get("height"))
        if not (width and height) and not has_aspect_ratio(img):
            no_dimensions += 1

        loading = str(img.get("loading") or "").lower()
        fetchpriority = str(img.get("fetchpriority") or "").lower()
        decoding = str(img.get("decoding") or "").lower()
        if category != "hero" and loading != "lazy":
            below_fold_not_lazy += 1
        if category == "hero" and loading == "lazy":
            hero_lazy += 1
        if category == "hero" and fetchpriority != "high":
            hero_missing_fetchpriority += 1
        if category != "hero" and decoding != "async":
            decoding_missing_nonhero += 1

        srcset = str(img.get("srcset") or "").strip()
        sizes = str(img.get("sizes") or "").strip()
        if category != "thumbnail" and not srcset:
            missing_srcset += 1
        if srcset and not sizes and category != "thumbnail":
            missing_sizes += 1

        filename_ok, filename_note = filename_score(src)
        if not filename_ok:
            poor_filenames += 1

        avif_source, webp_source = picture_support(img)

        probe = probe_cache.get(src)
        if probe is None and len(probe_cache) < args.head_sample_limit:
            probe = probe_image(src, args.timeout)
            probe_cache[src] = probe
        elif probe is None:
            probe = {
                "status_code": None,
                "size_bytes": None,
                "content_type": None,
                "cache_control": None,
                "host": parsed_host,
                "sampled": False,
            }

        if probe.get("sampled"):
            cache_checked += 1
            cc = str(probe.get("cache_control") or "").lower()
            if "max-age" in cc or "s-maxage" in cc:
                cache_with_header += 1

        size_bytes = probe.get("size_bytes")
        size_kb = round(size_bytes / 1024, 1) if isinstance(size_bytes, int) and size_bytes > 0 else None
        thresholds = SIZE_THRESHOLDS_KB[category]

        row_issues = list(alt_issues)
        if size_kb is not None:
            if size_kb > thresholds["critical"]:
                oversized_critical += 1
                row_issues.append(f"Critical size for {category} ({size_kb}KB > {thresholds['critical']}KB)")
            elif size_kb > thresholds["warning"]:
                oversized_warning += 1
                row_issues.append(f"Oversized {category} image ({size_kb}KB > {thresholds['warning']}KB)")

        if ext in {"jpg", "jpeg", "png"} and not (avif_source or webp_source):
            row_issues.append("Legacy format without AVIF/WebP fallback.")
        if not (width and height) and not has_aspect_ratio(img):
            row_issues.append("Missing explicit dimensions/aspect-ratio.")
        if category != "hero" and loading != "lazy":
            row_issues.append('Below-fold image should use loading="lazy".')
        if category == "hero" and loading == "lazy":
            row_issues.append("Hero image is lazy-loaded (LCP risk).")
        if category == "hero" and fetchpriority != "high":
            row_issues.append('Hero image missing fetchpriority="high".')
        if category != "hero" and decoding != "async":
            row_issues.append('Non-hero image missing decoding="async".')
        if category != "thumbnail" and not srcset:
            row_issues.append("Missing srcset for responsive delivery.")
        if srcset and not sizes and category != "thumbnail":
            row_issues.append("srcset present but sizes attribute missing.")
        if not filename_ok:
            row_issues.append(filename_note)

        est_savings = estimate_savings_kb(size_kb, category, ext)
        image_rows.append(
            {
                "url": src,
                "category": category,
                "format": format_label,
                "size_kb": size_kb if size_kb is not None else "unknown",
                "issues": row_issues,
                "est_savings_kb": est_savings,
            }
        )

    unique_hosts = sorted(host_counter.keys())
    cdn_used = any(host != page_host and any(marker in host for marker in CDN_MARKERS) for host in unique_hosts)

    cache_header_coverage_pct = round((cache_with_header / cache_checked) * 100, 1) if cache_checked else 0.0

    metrics = {
        "total_images": total_images,
        "missing_alt": missing_alt,
        "alt_quality_warnings": alt_quality_warnings,
        "oversized_warning": oversized_warning,
        "oversized_critical": oversized_critical,
        "legacy_format": legacy_format,
        "no_dimensions": no_dimensions,
        "below_fold_not_lazy": below_fold_not_lazy,
        "hero_lazy": hero_lazy,
        "hero_missing_fetchpriority": hero_missing_fetchpriority,
        "decoding_missing_nonhero": decoding_missing_nonhero,
        "missing_srcset": missing_srcset,
        "missing_sizes": missing_sizes,
        "poor_filenames": poor_filenames,
        "convert_candidates": convert_candidates,
        "cdn_used": cdn_used,
        "cache_header_coverage_pct": cache_header_coverage_pct,
    }

    issues: list[dict[str, str]] = []
    if hero_lazy > 0:
        issues.append({"priority": "Critical", "title": "Hero images are lazy-loaded", "detail": f"{hero_lazy} hero images use loading=\"lazy\"."})
    if missing_alt > 0:
        issues.append({"priority": "High", "title": "Missing alt text", "detail": f"{missing_alt} images are missing useful alt text."})
    if oversized_critical > 0:
        issues.append({"priority": "High", "title": "Critically oversized images", "detail": f"{oversized_critical} images exceed critical size thresholds."})
    if no_dimensions > 0:
        issues.append({"priority": "High", "title": "Images missing dimensions", "detail": f"{no_dimensions} images can cause layout shifts."})
    if below_fold_not_lazy > 0:
        issues.append({"priority": "Medium", "title": "Below-fold images not lazy-loaded", "detail": f"{below_fold_not_lazy} non-hero images are not lazy-loaded."})
    if hero_missing_fetchpriority > 0:
        issues.append({"priority": "Medium", "title": "Hero images missing fetchpriority", "detail": f"{hero_missing_fetchpriority} hero images lack fetchpriority=\"high\"."})
    if missing_srcset > 0:
        issues.append({"priority": "Medium", "title": "Missing responsive srcset", "detail": f"{missing_srcset} non-thumbnail images have no srcset."})
    if missing_sizes > 0:
        issues.append({"priority": "Low", "title": "Missing sizes with srcset", "detail": f"{missing_sizes} images have srcset but no sizes attribute."})
    if poor_filenames > 0:
        issues.append({"priority": "Low", "title": "Non-descriptive file names", "detail": f"{poor_filenames} images use poor filename conventions."})
    if metrics["cdn_used"] is False and total_images >= 20:
        issues.append({"priority": "Info", "title": "No CDN evidence for image delivery", "detail": "Consider CDN delivery for image-heavy pages."})
    if cache_checked > 0 and cache_header_coverage_pct < 60:
        issues.append({"priority": "Low", "title": "Weak image cache headers", "detail": f"Only {cache_header_coverage_pct}% sampled images expose max-age/s-maxage."})

    issues.sort(key=lambda item: PRIORITY_ORDER.get(item["priority"], 99))
    score = score_images(metrics)
    recommendations = build_recommendations(metrics)

    prioritized = sorted(image_rows, key=lambda row: row["est_savings_kb"], reverse=True)

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "IMAGE-AUDIT-REPORT.md"
    plan_path = out_dir / "IMAGE-OPTIMIZATION-PLAN.md"
    summary_path = out_dir / "SUMMARY.json"

    render_report(
        out_report=report_path,
        out_plan=plan_path,
        page_url=page_url,
        score=score,
        metrics=metrics,
        issues=issues,
        prioritized=prioritized,
        recommendations=recommendations,
    )

    summary = {
        "url": page_url,
        "image_score": score,
        "metrics": metrics,
        "issue_count": len(issues),
        "issues": issues,
        "recommendations": recommendations,
        "top_candidates": prioritized[:50],
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"URL: {page_url}")
    print(f"Image score: {score}/100")
    print(f"Total images: {metrics['total_images']}")
    print(f"Issues: {len(issues)}")
    print(f"Report: {report_path}")
    print(f"Plan: {plan_path}")
    print(f"Summary: {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic image SEO/performance audit.")
    parser.add_argument("--url", default="", help="Target URL to audit")
    parser.add_argument("--html-file", default="", help="Local HTML file path")
    parser.add_argument("--page-url", default="", help="Canonical page URL when using --html-file")
    parser.add_argument("--keyword", default="", help="Optional focus keyword for alt-text checks")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--head-sample-limit", type=int, default=30, help="Max image URLs probed for size/header checks")
    parser.add_argument("--output-dir", default="seo-images-output")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.keyword = args.keyword.strip() or None
    return run_audit(args)


if __name__ == "__main__":
    raise SystemExit(main())
