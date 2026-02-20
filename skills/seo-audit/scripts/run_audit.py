#!/usr/bin/env python3
"""
Self-contained SEO audit runner for the seo-audit skill.

Usage:
    python run_audit.py https://example.com
    python run_audit.py https://example.com --max-pages 200 --visual auto
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import statistics
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import robotparser
from urllib.parse import urljoin, urlparse, urlunparse

try:
    import requests
except ImportError:
    print("Error: requests is required. Install with: pip install requests")
    raise SystemExit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 is required. Install with: pip install beautifulsoup4")
    raise SystemExit(1)


USER_AGENT = "Mozilla/5.0 (compatible; CodexSEO/1.0; +https://github.com/avalonreset/codex-seo)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Connection": "keep-alive",
}
MAX_REDIRECT_HOPS = 10

WEIGHTS = {
    "technical": 0.25,
    "content": 0.25,
    "onpage": 0.20,
    "schema": 0.10,
    "performance": 0.10,
    "images": 0.05,
    "ai_readiness": 0.05,
}


@dataclass
class PageResult:
    url: str
    status_code: int | None
    response_ms: float | None
    title: str | None
    meta_description: str | None
    canonical: str | None
    h1_count: int
    word_count: int
    schema_count: int
    image_count: int
    missing_alt_count: int
    internal_links: list[str]
    fetch_error: str | None
    redirect_hops: int
    content_type: str | None
    is_html: bool


def clamp(num: float, low: float, high: float) -> float:
    return max(low, min(high, num))


def normalize_url(raw: str) -> str:
    value = raw.strip()
    parsed = urlparse(value)
    if not parsed.scheme:
        value = f"https://{value}"
        parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    netloc = parsed.netloc or (parsed.hostname or "")
    clean_path = parsed.path or "/"
    return urlunparse((parsed.scheme, netloc, clean_path, "", parsed.query, ""))


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


def normalize_host(host: str) -> str:
    lowered = host.lower().strip(".")
    if lowered.startswith("www."):
        return lowered[4:]
    return lowered


def same_site(url_a: str, url_b: str) -> bool:
    a = normalize_host(urlparse(url_a).hostname or "")
    b = normalize_host(urlparse(url_b).hostname or "")
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def strip_fragment(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, p.query, ""))


def build_robots(start_url: str, timeout: int) -> tuple[robotparser.RobotFileParser | None, str]:
    robots_url = urljoin(start_url, "/robots.txt")
    rp = robotparser.RobotFileParser()
    rp.set_url(robots_url)
    current_url = robots_url
    redirects = 0
    try:
        while True:
            if not is_public_target(current_url):
                return None, current_url
            response = requests.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
            if 300 <= response.status_code < 400:
                location = (response.headers.get("Location") or "").strip()
                if not location:
                    return None, current_url
                if redirects >= MAX_REDIRECT_HOPS:
                    return None, current_url
                try:
                    next_url = normalize_url(urljoin(current_url, location))
                except ValueError:
                    return None, current_url
                if not is_public_target(next_url):
                    return None, next_url
                current_url = next_url
                redirects += 1
                continue
            if response.status_code >= 400:
                return None, current_url
            rp.parse((response.text or "").splitlines())
            rp.set_url(current_url)
            return rp, current_url
    except Exception:
        return None, current_url


def fetch_page(session: requests.Session, url: str, timeout: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "status_code": None,
        "text": None,
        "headers": {},
        "redirect_hops": 0,
        "error": None,
        "final_url": url,
        "response_ms": None,
    }
    started = time.perf_counter()
    current_url = url
    redirect_hops = 0
    resp: requests.Response | None = None
    try:
        while True:
            if not is_public_target(current_url):
                result["error"] = "redirected target URL resolves to non-public or invalid host"
                return result
            resp = session.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
            if 300 <= resp.status_code < 400:
                location = (resp.headers.get("Location") or "").strip()
                if not location:
                    break
                if redirect_hops >= MAX_REDIRECT_HOPS:
                    result["error"] = f"Too many redirects (>{MAX_REDIRECT_HOPS})"
                    return result
                try:
                    next_url = normalize_url(urljoin(current_url, location))
                except ValueError as exc:
                    result["error"] = f"Invalid redirect URL: {exc}"
                    return result
                if not is_public_target(next_url):
                    result["error"] = "redirected target URL resolves to non-public or invalid host"
                    return result
                current_url = next_url
                redirect_hops += 1
                continue
            break
        if resp is None:
            result["error"] = "No response returned"
            return result
        elapsed = (time.perf_counter() - started) * 1000.0
        result["status_code"] = resp.status_code
        result["text"] = resp.text
        result["headers"] = dict(resp.headers)
        result["redirect_hops"] = redirect_hops
        result["final_url"] = current_url
        result["response_ms"] = round(elapsed, 2)
    except requests.exceptions.RequestException as exc:
        result["error"] = str(exc)
    return result


def parse_html(html: str, base_url: str) -> dict[str, Any]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    meta_description = None
    for meta in soup.find_all("meta"):
        if meta.get("name", "").lower() == "description":
            meta_description = meta.get("content")
            break

    canonical = None
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag:
        canonical = canonical_tag.get("href")

    h1_count = len(soup.find_all("h1"))

    schema_count = 0
    for script in soup.find_all("script", type="application/ld+json"):
        payload = script.string or ""
        if payload.strip():
            schema_count += 1

    images = soup.find_all("img")
    missing_alt_count = 0
    for image in images:
        if image.get("alt") is None or str(image.get("alt")).strip() == "":
            missing_alt_count += 1

    internal_links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        full = strip_fragment(urljoin(base_url, href))
        if full.startswith("http"):
            if same_site(base_url, full):
                internal_links.append(full)

    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    word_count = len(re.findall(r"\b\w+\b", text))

    return {
        "title": title,
        "meta_description": meta_description,
        "canonical": canonical,
        "h1_count": h1_count,
        "word_count": word_count,
        "schema_count": schema_count,
        "image_count": len(images),
        "missing_alt_count": missing_alt_count,
        "internal_links": sorted(set(internal_links)),
    }


def crawl_site(start_url: str, max_pages: int, timeout: int, delay: float) -> tuple[list[PageResult], dict[str, Any]]:
    session = requests.Session()
    queue = deque([start_url])
    seen: set[str] = set()
    pages: list[PageResult] = []
    crawl_info: dict[str, Any] = {
        "skipped_by_robots": 0,
        "fetch_errors": 0,
        "visited": 0,
    }

    rp, robots_url = build_robots(start_url, timeout)
    crawl_info["robots_url"] = robots_url

    while queue and len(seen) < max_pages:
        current = queue.popleft()
        if current in seen:
            continue

        if rp is not None:
            try:
                if not rp.can_fetch(USER_AGENT, current):
                    crawl_info["skipped_by_robots"] += 1
                    seen.add(current)
                    continue
            except Exception:
                pass

        seen.add(current)
        fetched = fetch_page(session, current, timeout)
        if fetched["error"]:
            crawl_info["fetch_errors"] += 1
            pages.append(
                PageResult(
                    url=current,
                    status_code=None,
                    response_ms=fetched["response_ms"],
                    title=None,
                    meta_description=None,
                    canonical=None,
                    h1_count=0,
                    word_count=0,
                    schema_count=0,
                    image_count=0,
                    missing_alt_count=0,
                    internal_links=[],
                    fetch_error=fetched["error"],
                    redirect_hops=0,
                    content_type=None,
                    is_html=False,
                )
            )
            continue

        final_url = normalize_url(fetched["final_url"])
        if final_url not in seen:
            seen.add(final_url)

        content_type = str(fetched["headers"].get("Content-Type", ""))
        content_type_lower = content_type.lower()
        is_html = "text/html" in content_type_lower or "application/xhtml+xml" in content_type_lower
        if not is_html:
            # Content-Type can be wrong or absent; fallback to document sniffing.
            is_html = "<html" in (fetched["text"] or "").lower()
        parsed = {
            "title": None,
            "meta_description": None,
            "canonical": None,
            "h1_count": 0,
            "word_count": 0,
            "schema_count": 0,
            "image_count": 0,
            "missing_alt_count": 0,
            "internal_links": [],
        }
        if is_html:
            parsed = parse_html(fetched["text"] or "", final_url)

        pages.append(
            PageResult(
                url=final_url,
                status_code=fetched["status_code"],
                response_ms=fetched["response_ms"],
                title=parsed["title"],
                meta_description=parsed["meta_description"],
                canonical=parsed["canonical"],
                h1_count=parsed["h1_count"],
                word_count=parsed["word_count"],
                schema_count=parsed["schema_count"],
                image_count=parsed["image_count"],
                missing_alt_count=parsed["missing_alt_count"],
                internal_links=parsed["internal_links"],
                fetch_error=None,
                redirect_hops=int(fetched["redirect_hops"]),
                content_type=content_type,
                is_html=is_html,
            )
        )

        for link in parsed["internal_links"]:
            if link not in seen and same_site(start_url, link):
                queue.append(link)

        crawl_info["visited"] = len(seen)
        if delay > 0:
            time.sleep(delay)

    return pages, crawl_info


def try_fetch_exists(url: str, timeout: int) -> bool:
    current_url = url
    redirects = 0
    while True:
        if not is_public_target(current_url):
            return False
        try:
            response = requests.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
        except requests.exceptions.RequestException:
            return False
        if 300 <= response.status_code < 400:
            location = (response.headers.get("Location") or "").strip()
            if not location:
                return False
            if redirects >= MAX_REDIRECT_HOPS:
                return False
            try:
                next_url = normalize_url(urljoin(current_url, location))
            except ValueError:
                return False
            if not is_public_target(next_url):
                return False
            current_url = next_url
            redirects += 1
            continue
        return response.status_code < 400


def run_visual_checks(url: str, output_dir: Path, mode: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "screenshots": [],
        "h1_visible_above_fold": None,
        "cta_visible_above_fold": None,
        "viewport_meta_present": None,
        "horizontal_scroll_mobile": None,
    }

    if mode == "off":
        result["reason"] = "visual mode disabled"
        return result

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        result["status"] = "not_available"
        result["reason"] = "Playwright unavailable. Install with: pip install playwright && playwright install chromium"
        if mode == "on":
            result["status"] = "failed"
        return result

    shots_dir = output_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            desktop_context = browser.new_context(viewport={"width": 1920, "height": 1080})
            desktop_page = desktop_context.new_page()
            desktop_page.goto(url, wait_until="networkidle", timeout=30000)
            desktop_page.wait_for_timeout(800)

            desktop_file = shots_dir / "homepage-desktop.png"
            desktop_page.screenshot(path=str(desktop_file), full_page=True)
            result["screenshots"].append(str(desktop_file))

            h1 = desktop_page.query_selector("h1")
            if h1:
                box = h1.bounding_box()
                result["h1_visible_above_fold"] = bool(box and box["y"] < 1080)
            else:
                result["h1_visible_above_fold"] = False

            cta = desktop_page.query_selector(
                "a[href*='signup'],a[href*='demo'],a[href*='contact'],button,.cta,[class*='cta']"
            )
            if cta:
                cta_box = cta.bounding_box()
                result["cta_visible_above_fold"] = bool(cta_box and cta_box["y"] < 1080)
            else:
                result["cta_visible_above_fold"] = False

            desktop_context.close()

            mobile_context = browser.new_context(viewport={"width": 375, "height": 812})
            mobile_page = mobile_context.new_page()
            mobile_page.goto(url, wait_until="networkidle", timeout=30000)
            mobile_page.wait_for_timeout(500)

            mobile_file = shots_dir / "homepage-mobile.png"
            mobile_page.screenshot(path=str(mobile_file), full_page=True)
            result["screenshots"].append(str(mobile_file))

            viewport_meta = mobile_page.query_selector('meta[name="viewport"]')
            result["viewport_meta_present"] = viewport_meta is not None

            scroll_width = int(mobile_page.evaluate("document.documentElement.scrollWidth"))
            viewport_width = int(mobile_page.evaluate("window.innerWidth"))
            result["horizontal_scroll_mobile"] = scroll_width > viewport_width

            mobile_context.close()
            browser.close()

        result["status"] = "ok"
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["reason"] = str(exc)
        return result


def compute_scores(
    pages: list[PageResult],
    start_url: str,
    crawl_info: dict[str, Any],
    timeout: int,
) -> tuple[dict[str, float | None], dict[str, Any], list[dict[str, Any]]]:
    pages_ok = [p for p in pages if p.fetch_error is None]
    pages_html = [p for p in pages_ok if p.is_html]
    html_count = len(pages_html)
    total = html_count if html_count else 1
    all_count = len(pages)

    missing_title = sum(1 for p in pages_html if not p.title)
    missing_meta = sum(1 for p in pages_html if not p.meta_description)
    missing_canonical = sum(1 for p in pages_html if not p.canonical)
    invalid_h1 = sum(1 for p in pages_html if p.h1_count != 1)
    thin_pages = sum(1 for p in pages_html if p.word_count < 300)
    schema_pages = sum(1 for p in pages_html if p.schema_count > 0)
    total_images = sum(p.image_count for p in pages_html)
    missing_alt = sum(p.missing_alt_count for p in pages_html)
    error_pages = sum(1 for p in pages if (p.status_code is not None and p.status_code >= 400) or p.fetch_error)
    long_redirects = sum(1 for p in pages_ok if p.redirect_hops > 2)

    title_counts = Counter((p.title or "").strip().lower() for p in pages_html if p.title)
    duplicate_titles = sum(c - 1 for c in title_counts.values() if c > 1)

    response_times = [p.response_ms for p in pages_ok if p.response_ms is not None]
    median_response = statistics.median(response_times) if response_times else None

    robots_ok = try_fetch_exists(urljoin(start_url, "/robots.txt"), timeout)
    sitemap_ok = try_fetch_exists(urljoin(start_url, "/sitemap.xml"), timeout)
    llms_ok = try_fetch_exists(urljoin(start_url, "/llms.txt"), timeout)

    about_or_contact = any(
        any(part in (urlparse(link).path or "").lower() for part in ("/about", "/contact", "/team", "/company"))
        for page in pages_html
        for link in page.internal_links
    )

    technical = 100.0
    technical -= 20.0 * (error_pages / max(all_count, 1))
    technical -= 20.0 * (missing_canonical / total)
    technical -= 15.0 * (long_redirects / total)
    if not robots_ok:
        technical -= 10.0
    if not sitemap_ok:
        technical -= 10.0
    technical = clamp(technical, 0.0, 100.0)

    content: float | None = None
    onpage: float | None = None
    schema: float | None = None
    images: float | None = None
    ai_readiness: float | None = None
    if html_count > 0:
        content = 100.0
        content -= 35.0 * (thin_pages / total)
        content -= 20.0 * (duplicate_titles / total)
        content -= 15.0 * (invalid_h1 / total)
        content = clamp(content, 0.0, 100.0)

        onpage = 100.0
        onpage -= 35.0 * (missing_title / total)
        onpage -= 25.0 * (missing_meta / total)
        onpage -= 20.0 * (invalid_h1 / total)
        onpage = clamp(onpage, 0.0, 100.0)

        schema = 100.0
        schema -= 50.0 * (1.0 - (schema_pages / total))
        schema = clamp(schema, 0.0, 100.0)

    if median_response is None:
        performance = None
    elif median_response <= 500:
        performance = 95.0
    elif median_response <= 900:
        performance = 80.0
    elif median_response <= 1500:
        performance = 65.0
    elif median_response <= 2500:
        performance = 45.0
    else:
        performance = 25.0

    if html_count > 0:
        if total_images == 0:
            images = 100.0
        else:
            images = clamp(100.0 - (missing_alt / total_images) * 70.0, 0.0, 100.0)

        ai_readiness = 100.0
        if not llms_ok:
            ai_readiness -= 20.0
        if not about_or_contact:
            ai_readiness -= 20.0
        ai_readiness -= 20.0 * (1.0 - (schema_pages / total))
        ai_readiness -= 15.0 * (thin_pages / total)
        ai_readiness = clamp(ai_readiness, 0.0, 100.0)

    scores: dict[str, float | None] = {
        "technical": round(technical, 1),
        "content": round(content, 1) if content is not None else None,
        "onpage": round(onpage, 1) if onpage is not None else None,
        "schema": round(schema, 1) if schema is not None else None,
        "performance": round(performance, 1) if performance is not None else None,
        "images": round(images, 1) if images is not None else None,
        "ai_readiness": round(ai_readiness, 1) if ai_readiness is not None else None,
    }

    issues: list[dict[str, Any]] = []
    if html_count == 0:
        issues.append(
            {
                "priority": "High",
                "title": "No HTML pages crawled",
                "detail": "Crawl did not find HTML documents in scope. Verify start URL and crawl scope.",
            }
        )
    if error_pages > 0:
        issues.append(
            {"priority": "Critical", "title": "HTTP errors during crawl", "detail": f"{error_pages} pages returned errors."}
        )
    if missing_title > 0:
        issues.append(
            {
                "priority": "High",
                "title": "Missing title tags",
                "detail": f"{missing_title}/{total} crawled HTML pages have no title tag.",
            }
        )
    if missing_meta > 0:
        issues.append(
            {
                "priority": "High",
                "title": "Missing meta descriptions",
                "detail": f"{missing_meta}/{total} crawled HTML pages are missing meta descriptions.",
            }
        )
    if html_count > 0 and thin_pages > max(3, int(0.2 * total)):
        issues.append(
            {
                "priority": "High",
                "title": "Thin content footprint",
                "detail": f"{thin_pages}/{total} pages are below 300 words.",
            }
        )
    if not robots_ok:
        issues.append({"priority": "Medium", "title": "Missing robots.txt", "detail": "No valid robots.txt detected."})
    if not sitemap_ok:
        issues.append(
            {"priority": "Medium", "title": "Missing sitemap.xml", "detail": "No valid sitemap.xml detected."}
        )
    if not llms_ok:
        issues.append({"priority": "Low", "title": "Missing llms.txt", "detail": "No llms.txt detected."})
    if total_images > 0 and missing_alt > 0:
        issues.append(
            {
                "priority": "Medium",
                "title": "Images missing alt text",
                "detail": f"{missing_alt}/{total_images} images are missing alt text.",
            }
        )

    stats = {
        "pages_total": all_count,
        "pages_successful": len(pages_ok),
        "pages_html": html_count,
        "pages_non_html": len(pages_ok) - html_count,
        "robots_ok": robots_ok,
        "sitemap_ok": sitemap_ok,
        "llms_ok": llms_ok,
        "missing_title": missing_title,
        "missing_meta": missing_meta,
        "missing_canonical": missing_canonical,
        "invalid_h1": invalid_h1,
        "thin_pages": thin_pages,
        "schema_pages": schema_pages,
        "duplicate_titles": duplicate_titles,
        "total_images": total_images,
        "missing_alt": missing_alt,
        "error_pages": error_pages,
        "median_response_ms": median_response,
        "about_or_contact_links": about_or_contact,
        "skipped_by_robots": crawl_info["skipped_by_robots"],
        "fetch_errors": crawl_info["fetch_errors"],
    }
    return scores, stats, issues


def aggregate_health_score(scores: dict[str, float | None]) -> tuple[float, list[str]]:
    used_weights = 0.0
    weighted_sum = 0.0
    not_measured: list[str] = []
    for name, score in scores.items():
        if score is None:
            not_measured.append(name)
            continue
        weight = WEIGHTS[name]
        weighted_sum += score * weight
        used_weights += weight
    if used_weights == 0:
        return 0.0, list(scores.keys())
    return round(weighted_sum / used_weights, 1), not_measured


def write_reports(
    output_dir: Path,
    target_url: str,
    pages: list[PageResult],
    scores: dict[str, float | None],
    stats: dict[str, Any],
    issues: list[dict[str, Any]],
    visual: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    full_report = output_dir / "FULL-AUDIT-REPORT.md"
    action_plan = output_dir / "ACTION-PLAN.md"
    summary_json = output_dir / "SUMMARY.json"

    total_score, not_measured = aggregate_health_score(scores)

    issue_lines = "\n".join(
        f"- **{item['priority']}**: {item['title']} - {item['detail']}" for item in issues
    ) or "- No material issues detected in this crawl sample."

    score_lines = []
    for key in ("technical", "content", "onpage", "schema", "performance", "images", "ai_readiness"):
        value = scores[key]
        label = key.replace("_", " ").title()
        score_lines.append(f"| {label} | {'Not Measured' if value is None else value} |")
    score_table = "\n".join(score_lines)

    visual_lines = []
    visual_lines.append(f"- Status: {visual.get('status', 'skipped')}")
    if visual.get("reason"):
        visual_lines.append(f"- Note: {visual['reason']}")
    if visual.get("screenshots"):
        for shot in visual["screenshots"]:
            visual_lines.append(f"- Screenshot: `{shot}`")
    if visual.get("h1_visible_above_fold") is not None:
        visual_lines.append(f"- H1 visible above fold: {visual['h1_visible_above_fold']}")
    if visual.get("cta_visible_above_fold") is not None:
        visual_lines.append(f"- CTA visible above fold: {visual['cta_visible_above_fold']}")
    if visual.get("viewport_meta_present") is not None:
        visual_lines.append(f"- Viewport meta present: {visual['viewport_meta_present']}")
    if visual.get("horizontal_scroll_mobile") is not None:
        visual_lines.append(f"- Horizontal scroll on mobile: {visual['horizontal_scroll_mobile']}")

    full_content = f"""# Full SEO Audit Report

## Executive Summary

- Target: `{target_url}`
- SEO Health Score: **{total_score}/100**
- Pages crawled: **{stats['pages_total']}**
- Successful fetches: **{stats['pages_successful']}**
- HTML pages analyzed: **{stats['pages_html']}**
- Non-HTML pages seen: **{stats['pages_non_html']}**
- Categories not measured: {", ".join(not_measured) if not_measured else "None"}

## Category Scores

| Category | Score |
|---|---|
{score_table}

## Top Findings

{issue_lines}

## Crawl Stats

- robots.txt present: {stats['robots_ok']}
- sitemap.xml present: {stats['sitemap_ok']}
- llms.txt present: {stats['llms_ok']}
- Fetch errors: {stats['fetch_errors']}
- Pages skipped by robots: {stats['skipped_by_robots']}
- Missing title tags: {stats['missing_title']}
- Missing meta descriptions: {stats['missing_meta']}
- Missing canonical tags: {stats['missing_canonical']}
- Invalid H1 structure: {stats['invalid_h1']}
- Thin content pages (<300 words): {stats['thin_pages']}
- Pages with schema: {stats['schema_pages']}
- Duplicate titles: {stats['duplicate_titles']}
- Images missing alt: {stats['missing_alt']}/{stats['total_images']}
- Median response time (ms): {stats['median_response_ms']}

## Visual Checks

{chr(10).join(visual_lines)}

## Notes

- Performance score is based on server response-time proxy only, not lab CWV (LCP/INP/CLS).
- This audit is sample-based and depends on crawl reach within the max-page budget.
"""

    by_priority = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for item in issues:
        by_priority[item["priority"]].append(item)

    plan_lines = [
        "# SEO Action Plan",
        "",
        f"- Target: `{target_url}`",
        f"- Generated from crawl of {stats['pages_total']} pages",
        "",
    ]
    for priority in ("Critical", "High", "Medium", "Low"):
        plan_lines.append(f"## {priority}")
        if not by_priority[priority]:
            plan_lines.append("- No actions in this tier.")
        else:
            for idx, item in enumerate(by_priority[priority], start=1):
                plan_lines.append(f"{idx}. {item['title']} - {item['detail']}")
        plan_lines.append("")

    full_report.write_text(full_content, encoding="utf-8")
    action_plan.write_text("\n".join(plan_lines).strip() + "\n", encoding="utf-8")
    summary_json.write_text(
        json.dumps(
            {
                "target_url": target_url,
                "health_score": total_score,
                "scores": scores,
                "stats": stats,
                "issues": issues,
                "visual": visual,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a full SEO audit with bounded crawling.")
    parser.add_argument("url", help="Target site URL")
    parser.add_argument("--max-pages", type=int, default=500, help="Crawl page cap (max 500)")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds")
    parser.add_argument(
        "--visual",
        choices=["auto", "on", "off"],
        default="auto",
        help="Run visual checks with Playwright (auto=run if available).",
    )
    parser.add_argument("--output-dir", default="seo-audit-output", help="Output directory")
    args = parser.parse_args()

    if args.max_pages < 1:
        print("Error: --max-pages must be >= 1")
        return 2
    max_pages = min(args.max_pages, 500)

    try:
        target_url = normalize_url(args.url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    if not is_public_target(target_url):
        print("Error: target URL resolves to non-public or invalid host")
        return 2

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Audit target: {target_url}")
    print(f"Crawl max pages: {max_pages}")
    print("Crawling...")
    pages, crawl_info = crawl_site(target_url, max_pages=max_pages, timeout=args.timeout, delay=args.delay)
    if not pages:
        print("Error: crawl returned no pages")
        return 1

    print("Scoring...")
    scores, stats, issues = compute_scores(pages, target_url, crawl_info, timeout=args.timeout)

    print("Running visual checks...")
    visual = run_visual_checks(target_url, output_dir, args.visual)

    print("Writing reports...")
    write_reports(output_dir, target_url, pages, scores, stats, issues, visual)
    health_score, not_measured = aggregate_health_score(scores)

    print(f"Done. Health score: {health_score}/100")
    if not_measured:
        print(f"Not measured: {', '.join(not_measured)}")
    print(f"Report: {output_dir / 'FULL-AUDIT-REPORT.md'}")
    print(f"Action plan: {output_dir / 'ACTION-PLAN.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
