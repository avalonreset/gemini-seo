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
from datetime import UTC, datetime
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

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

SECURITY_HEADERS = [
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
]

BUSINESS_PATH_SIGNALS = {
    "saas": ["/pricing", "/features", "/integrations", "/docs", "/platform", "/product"],
    "ecommerce": ["/products", "/product/", "/collections", "/shop", "/cart", "/checkout", "/store"],
    "publisher": ["/blog", "/news", "/articles", "/author", "/category", "/topics"],
    "agency": ["/case-studies", "/portfolio", "/our-work", "/industries", "/clients"],
    "local_service": ["/locations", "/service-area", "/services", "/contact", "/book"],
}

BUSINESS_KEYWORD_SIGNALS = {
    "saas": ["free trial", "book demo", "start free", "software", "platform", "api"],
    "ecommerce": ["add to cart", "buy now", "shop now", "free shipping", "product"],
    "publisher": ["newsletter", "editorial", "read more", "published", "article"],
    "agency": ["case study", "our clients", "results", "portfolio", "growth marketing"],
    "local_service": ["call now", "service area", "licensed", "near you", "schedule service"],
}


@dataclass
class PageResult:
    url: str
    status_code: int | None
    response_ms: float | None
    title: str | None
    meta_description: str | None
    meta_robots: str | None
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
    meta_robots = None
    for meta in soup.find_all("meta"):
        name = meta.get("name", "").lower()
        if name == "description" and meta_description is None:
            meta_description = meta.get("content")
        elif name == "robots" and meta_robots is None:
            meta_robots = meta.get("content")

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
        "meta_robots": meta_robots,
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
                    meta_robots=None,
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
            "meta_robots": None,
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
                meta_robots=parsed["meta_robots"],
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


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = round((len(ordered) - 1) * p)
    return float(ordered[int(idx)])


def sample_urls(pages: list[PageResult], predicate: Any, limit: int = 8) -> list[str]:
    picked: list[str] = []
    for page in pages:
        if predicate(page):
            picked.append(page.url)
            if len(picked) >= limit:
                break
    return picked


def detect_business_type(start_url: str, pages_html: list[PageResult]) -> dict[str, Any]:
    scores: dict[str, int] = {key: 0 for key in BUSINESS_PATH_SIGNALS}
    signals: dict[str, list[str]] = {key: [] for key in BUSINESS_PATH_SIGNALS}

    for page in pages_html[:300]:
        path = (urlparse(page.url).path or "/").lower()
        for business_type, patterns in BUSINESS_PATH_SIGNALS.items():
            for pattern in patterns:
                if pattern in path:
                    scores[business_type] += 2
                    if len(signals[business_type]) < 8:
                        signals[business_type].append(f"path signal: {pattern} ({path})")
                    break

    homepage = pages_html[0] if pages_html else None
    homepage_text = " ".join(
        [
            (homepage.title or "") if homepage else "",
            (homepage.meta_description or "") if homepage else "",
            start_url,
        ]
    ).lower()

    for business_type, keywords in BUSINESS_KEYWORD_SIGNALS.items():
        for keyword in keywords:
            if keyword in homepage_text:
                scores[business_type] += 1
                if len(signals[business_type]) < 8:
                    signals[business_type].append(f"keyword signal: {keyword}")

    winner = max(scores, key=scores.get) if scores else "generic"
    if not scores or scores[winner] == 0:
        return {"type": "generic", "confidence": 0.0, "signals": []}

    total_points = sum(scores.values()) or 1
    return {
        "type": winner,
        "confidence": round(scores[winner] / total_points, 3),
        "signals": signals[winner],
    }


def fetch_security_headers(target_url: str, timeout: int) -> dict[str, Any]:
    session = requests.Session()
    fetched = fetch_page(session, target_url, timeout)
    if fetched.get("error"):
        return {
            "status": "unavailable",
            "reason": fetched.get("error"),
            "present": [],
            "missing": SECURITY_HEADERS,
            "final_url": target_url,
        }

    headers = {key.lower(): value for key, value in (fetched.get("headers") or {}).items()}
    present = [header for header in SECURITY_HEADERS if header in headers]
    missing = [header for header in SECURITY_HEADERS if header not in headers]
    return {
        "status": "ok",
        "reason": "",
        "present": present,
        "missing": missing,
        "final_url": fetched.get("final_url", target_url),
    }


def make_issue(
    *,
    priority: str,
    category: str,
    title: str,
    detail: str,
    impact: str,
    recommendation: str,
    evidence: list[str] | None = None,
    effort: str = "Medium",
    expected_lift: str = "Medium",
) -> dict[str, Any]:
    return {
        "priority": priority,
        "category": category,
        "title": title,
        "detail": detail,
        "impact": impact,
        "recommendation": recommendation,
        "evidence": list(dict.fromkeys(evidence or [])),
        "effort": effort,
        "expected_lift": expected_lift,
    }


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

    missing_title = sum(1 for p in pages_html if not p.title or not p.title.strip())
    missing_meta = sum(1 for p in pages_html if not p.meta_description or not p.meta_description.strip())
    missing_canonical = sum(1 for p in pages_html if not p.canonical)
    invalid_h1 = sum(1 for p in pages_html if p.h1_count != 1)
    thin_pages = sum(1 for p in pages_html if p.word_count < 300)
    schema_pages = sum(1 for p in pages_html if p.schema_count > 0)
    total_images = sum(p.image_count for p in pages_html)
    missing_alt = sum(p.missing_alt_count for p in pages_html)
    noindex_pages = sum(
        1 for p in pages_html if p.meta_robots and "noindex" in p.meta_robots.lower()
    )
    weak_internal_link_pages = sum(1 for p in pages_html if len(p.internal_links) < 2)
    error_pages = sum(1 for p in pages if (p.status_code is not None and p.status_code >= 400) or p.fetch_error)
    long_redirects = sum(1 for p in pages_ok if p.redirect_hops > 2)
    status_4xx = sum(1 for p in pages if p.status_code is not None and 400 <= p.status_code < 500)
    status_5xx = sum(1 for p in pages if p.status_code is not None and p.status_code >= 500)

    title_counts = Counter((p.title or "").strip().lower() for p in pages_html if p.title)
    duplicate_titles = sum(c - 1 for c in title_counts.values() if c > 1)
    short_titles = sum(1 for p in pages_html if p.title and len(p.title.strip()) < 30)
    long_titles = sum(1 for p in pages_html if p.title and len(p.title.strip()) > 60)
    short_meta = sum(1 for p in pages_html if p.meta_description and len(p.meta_description.strip()) < 70)
    long_meta = sum(1 for p in pages_html if p.meta_description and len(p.meta_description.strip()) > 160)

    response_times = [float(p.response_ms) for p in pages_ok if p.response_ms is not None]
    median_response = statistics.median(response_times) if response_times else None
    p90_response = percentile(response_times, 0.90)
    word_counts = [float(p.word_count) for p in pages_html]
    word_count_p25 = percentile(word_counts, 0.25)
    word_count_median = statistics.median(word_counts) if word_counts else None
    word_count_p75 = percentile(word_counts, 0.75)

    robots_ok = try_fetch_exists(urljoin(start_url, "/robots.txt"), timeout)
    sitemap_ok = try_fetch_exists(urljoin(start_url, "/sitemap.xml"), timeout)
    llms_ok = try_fetch_exists(urljoin(start_url, "/llms.txt"), timeout)
    security = fetch_security_headers(start_url, timeout)
    security_missing = security["missing"]
    business_type = detect_business_type(start_url, pages_html)

    about_or_contact = any(
        any(part in (urlparse(link).path or "").lower() for part in ("/about", "/contact", "/team", "/company"))
        for page in pages_html
        for link in page.internal_links
    )

    technical = 100.0
    technical -= 22.0 * (error_pages / max(all_count, 1))
    technical -= 16.0 * (missing_canonical / total)
    technical -= 14.0 * (long_redirects / total)
    technical -= 18.0 * (noindex_pages / total)
    technical -= min(18.0, len(security_missing) * 3.0)
    if not robots_ok:
        technical -= 8.0
    if not sitemap_ok:
        technical -= 8.0
    technical = clamp(technical, 0.0, 100.0)

    content: float | None = None
    onpage: float | None = None
    schema: float | None = None
    images: float | None = None
    ai_readiness: float | None = None
    if html_count > 0:
        content = 100.0
        content -= 36.0 * (thin_pages / total)
        content -= 18.0 * (duplicate_titles / total)
        content -= 14.0 * (invalid_h1 / total)
        content -= 8.0 * (weak_internal_link_pages / total)
        content = clamp(content, 0.0, 100.0)

        onpage = 100.0
        onpage -= 32.0 * (missing_title / total)
        onpage -= 24.0 * (missing_meta / total)
        onpage -= 18.0 * (invalid_h1 / total)
        onpage -= 8.0 * ((short_titles + long_titles) / total)
        onpage -= 8.0 * ((short_meta + long_meta) / total)
        onpage = clamp(onpage, 0.0, 100.0)

        schema = clamp(50.0 + 50.0 * (schema_pages / total), 0.0, 100.0)

    if median_response is None:
        performance = None
    elif median_response <= 500:
        performance = 96.0
    elif median_response <= 900:
        performance = 84.0
    elif median_response <= 1500:
        performance = 70.0
    elif median_response <= 2500:
        performance = 52.0
    else:
        performance = 30.0
    if performance is not None and p90_response is not None and p90_response > 2500:
        performance = clamp(performance - 8.0, 0.0, 100.0)

    if html_count > 0:
        if total_images == 0:
            images = 100.0
        else:
            images = clamp(100.0 - (missing_alt / total_images) * 70.0, 0.0, 100.0)

        ai_readiness = 100.0
        if not llms_ok:
            ai_readiness -= 18.0
        if not about_or_contact:
            ai_readiness -= 16.0
        ai_readiness -= 20.0 * (1.0 - (schema_pages / total))
        ai_readiness -= 14.0 * (thin_pages / total)
        ai_readiness -= 12.0 * (noindex_pages / total)
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
            make_issue(
                priority="High",
                category="Crawl Coverage",
                title="No HTML pages crawled",
                detail="Crawl did not find HTML documents in scope. Verify start URL and crawl scope.",
                impact="Most SEO checks are blocked when no indexable HTML is collected.",
                recommendation="Validate the canonical start URL, then rerun with a larger crawl budget.",
                evidence=[start_url],
                effort="Low",
                expected_lift="High",
            )
        )
    if error_pages > 0:
        issues.append(
            make_issue(
                priority="Critical",
                category="Technical SEO",
                title="HTTP errors during crawl",
                detail=f"{error_pages} pages returned errors ({status_4xx}x 4xx, {status_5xx}x 5xx).",
                impact="Error URLs waste crawl budget and suppress organic visibility.",
                recommendation="Repair broken URLs and eliminate server-side failures on key templates first.",
                evidence=sample_urls(
                    pages,
                    lambda p: p.fetch_error is not None or (p.status_code is not None and p.status_code >= 400),
                ),
                effort="Medium",
                expected_lift="High",
            )
        )
    if noindex_pages > 0:
        issues.append(
            make_issue(
                priority="Critical" if noindex_pages > max(2, int(0.1 * total)) else "High",
                category="Indexability",
                title="Noindex directives detected",
                detail=f"{noindex_pages}/{total} HTML pages include noindex directives.",
                impact="Important pages can be dropped from the index despite internal links.",
                recommendation="Remove unintended noindex tags from pages intended to rank.",
                evidence=sample_urls(
                    pages_html,
                    lambda p: bool(p.meta_robots and "noindex" in p.meta_robots.lower()),
                ),
                effort="Low",
                expected_lift="High",
            )
        )
    if missing_title > 0:
        issues.append(
            make_issue(
                priority="High",
                category="On-Page SEO",
                title="Missing title tags",
                detail=f"{missing_title}/{total} crawled HTML pages have no title tag.",
                impact="Pages lose core relevance and CTR signals in search results.",
                recommendation="Set unique, intent-matched titles (30-60 chars) for all indexable pages.",
                evidence=sample_urls(pages_html, lambda p: not p.title or not p.title.strip()),
                effort="Low",
                expected_lift="High",
            )
        )
    if missing_meta > 0:
        issues.append(
            make_issue(
                priority="High",
                category="On-Page SEO",
                title="Missing meta descriptions",
                detail=f"{missing_meta}/{total} crawled HTML pages are missing meta descriptions.",
                impact="Search snippets become less controlled and usually underperform on CTR.",
                recommendation="Write concise, differentiated descriptions aligned to page intent.",
                evidence=sample_urls(
                    pages_html,
                    lambda p: not p.meta_description or not p.meta_description.strip(),
                ),
                effort="Low",
                expected_lift="Medium",
            )
        )
    if html_count > 0 and thin_pages > max(3, int(0.2 * total)):
        issues.append(
            make_issue(
                priority="High",
                category="Content Quality",
                title="Thin content footprint",
                detail=f"{thin_pages}/{total} pages are below 300 words.",
                impact="Thin pages are less competitive and less citable in AI answers.",
                recommendation="Expand high-value pages and consolidate low-value overlaps.",
                evidence=sample_urls(pages_html, lambda p: p.word_count < 300),
                effort="Medium",
                expected_lift="High",
            )
        )
    if not robots_ok:
        issues.append(
            make_issue(
                priority="Medium",
                category="Crawl Control",
                title="Missing robots.txt",
                detail="No valid robots.txt detected.",
                impact="Crawler policy is ambiguous and difficult to manage.",
                recommendation="Publish robots.txt with allow/disallow policy and sitemap pointers.",
                evidence=[urljoin(start_url, "/robots.txt")],
                effort="Low",
                expected_lift="Medium",
            )
        )
    if not sitemap_ok:
        issues.append(
            make_issue(
                priority="Medium",
                category="Crawl Control",
                title="Missing sitemap.xml",
                detail="No valid sitemap.xml detected.",
                impact="Search engines discover deep URLs less reliably.",
                recommendation="Generate and submit XML sitemap(s) with canonical URLs only.",
                evidence=[urljoin(start_url, "/sitemap.xml")],
                effort="Low",
                expected_lift="Medium",
            )
        )
    if security_missing:
        issues.append(
            make_issue(
                priority="High" if len(security_missing) >= 3 else "Medium",
                category="Security Signals",
                title="Missing security headers",
                detail=f"Missing {len(security_missing)}/{len(SECURITY_HEADERS)} security headers: {', '.join(security_missing)}.",
                impact="Weakens trust signals and increases security risk surface.",
                recommendation="Set missing headers at the edge or server and validate on primary templates.",
                evidence=[security["final_url"]],
                effort="Medium",
                expected_lift="Medium",
            )
        )
    if not llms_ok:
        issues.append(
            make_issue(
                priority="Low",
                category="AI Readiness",
                title="Missing llms.txt",
                detail="No llms.txt detected.",
                impact="No explicit AI retrieval guidance is available at the root.",
                recommendation="Publish llms.txt with clear citation and crawl guidance.",
                evidence=[urljoin(start_url, "/llms.txt")],
                effort="Low",
                expected_lift="Low",
            )
        )
    if total_images > 0 and missing_alt > 0:
        issues.append(
            make_issue(
                priority="Medium",
                category="Images",
                title="Images missing alt text",
                detail=f"{missing_alt}/{total_images} images are missing alt text.",
                impact="Hurts accessibility and weakens image relevance context.",
                recommendation="Add descriptive alt text to informative images; keep decorative images empty-alt.",
                evidence=sample_urls(pages_html, lambda p: p.missing_alt_count > 0),
                effort="Low",
                expected_lift="Medium",
            )
        )
    issues.sort(key=lambda issue: (PRIORITY_ORDER.get(issue["priority"], 99), issue["title"]))

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
        "noindex_pages": noindex_pages,
        "weak_internal_link_pages": weak_internal_link_pages,
        "short_titles": short_titles,
        "long_titles": long_titles,
        "short_meta": short_meta,
        "long_meta": long_meta,
        "total_images": total_images,
        "missing_alt": missing_alt,
        "error_pages": error_pages,
        "status_4xx": status_4xx,
        "status_5xx": status_5xx,
        "long_redirects": long_redirects,
        "median_response_ms": median_response,
        "p90_response_ms": p90_response,
        "word_count_p25": word_count_p25,
        "word_count_median": word_count_median,
        "word_count_p75": word_count_p75,
        "about_or_contact_links": about_or_contact,
        "business_type": business_type,
        "security_headers": security,
        "example_urls": {
            "missing_title": sample_urls(pages_html, lambda p: not p.title or not p.title.strip()),
            "missing_meta": sample_urls(
                pages_html,
                lambda p: not p.meta_description or not p.meta_description.strip(),
            ),
            "thin_content": sample_urls(pages_html, lambda p: p.word_count < 300),
            "noindex": sample_urls(
                pages_html,
                lambda p: bool(p.meta_robots and "noindex" in p.meta_robots.lower()),
            ),
            "missing_schema": sample_urls(pages_html, lambda p: p.schema_count == 0),
            "alt_missing": sample_urls(pages_html, lambda p: p.missing_alt_count > 0),
        },
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


def score_band(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Strong"
    if score >= 70:
        return "Good"
    if score >= 60:
        return "Needs Improvement"
    return "At Risk"


def score_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def pick_quick_wins(issues: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(
        issues,
        key=lambda item: (
            PRIORITY_ORDER.get(item["priority"], 99),
            0 if item.get("effort") == "Low" else 1,
            0 if item.get("expected_lift") == "High" else (1 if item.get("expected_lift") == "Medium" else 2),
        ),
    )
    return [item for item in ranked if item.get("effort") in ("Low", "Medium")][:limit]


def markdown_issue_list(items: list[dict[str, Any]], with_details: bool = False) -> str:
    if not items:
        return "- No issues in this section."
    lines: list[str] = []
    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. **[{item['priority']}] {item['title']}** - {item['detail']}")
        if with_details:
            lines.append(f"   - Impact: {item.get('impact', 'n/a')}")
            lines.append(f"   - Recommendation: {item.get('recommendation', 'n/a')}")
            if item.get("evidence"):
                lines.append(f"   - Evidence: {', '.join(item['evidence'][:3])}")
    return "\n".join(lines)


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
    issues_json = output_dir / "ISSUES.json"

    total_score, not_measured = aggregate_health_score(scores)
    generated_at = datetime.now(UTC).isoformat()
    grade = score_grade(total_score)
    band = score_band(total_score)
    business = stats.get("business_type", {"type": "generic", "confidence": 0.0, "signals": []})
    business_label = str(business.get("type", "generic")).replace("_", " ").title()
    business_confidence = round(float(business.get("confidence", 0.0)) * 100, 1)
    critical = [item for item in issues if item["priority"] == "Critical"][:5]
    quick_wins = pick_quick_wins(issues, limit=5)
    title_completeness = (stats["pages_html"] - stats["missing_title"]) / max(stats["pages_html"], 1)
    meta_completeness = (stats["pages_html"] - stats["missing_meta"]) / max(stats["pages_html"], 1)
    metadata_completeness = round(((title_completeness + meta_completeness) / 2) * 100, 1)
    checklist_rows = [
        ("robots.txt available", stats["robots_ok"], "Crawl policy"),
        ("sitemap.xml available", stats["sitemap_ok"], "Discovery"),
        ("llms.txt available", stats["llms_ok"], "AI guidance"),
        ("No HTTP crawl errors", stats["error_pages"] == 0, "Reliability"),
        ("No noindex leakage", stats["noindex_pages"] == 0, "Indexability"),
        ("Title completeness > 95%", (stats["missing_title"] / max(stats["pages_html"], 1)) <= 0.05, "On-page"),
        ("Meta completeness > 90%", (stats["missing_meta"] / max(stats["pages_html"], 1)) <= 0.10, "On-page"),
        ("Canonical completeness > 90%", (stats["missing_canonical"] / max(stats["pages_html"], 1)) <= 0.10, "Canonicalization"),
        ("Schema coverage > 70%", (stats["schema_pages"] / max(stats["pages_html"], 1)) >= 0.70, "Structured data"),
        ("Thin page share < 25%", (stats["thin_pages"] / max(stats["pages_html"], 1)) < 0.25, "Content depth"),
        ("Alt coverage > 95%", (1 - (stats["missing_alt"] / max(stats["total_images"], 1))) >= 0.95 if stats["total_images"] else True, "Accessibility"),
        ("Median response < 900ms", (stats["median_response_ms"] or 0) < 900 if stats["median_response_ms"] is not None else False, "Performance"),
    ]

    issue_lines = markdown_issue_list(issues[:10], with_details=True)
    critical_lines = markdown_issue_list(critical, with_details=True)
    quick_win_lines = (
        "\n".join(
            f"{idx}. **{item['title']}** ({item.get('effort', 'n/a')} effort, {item.get('expected_lift', 'n/a')} lift) - {item.get('recommendation', item['detail'])}"
            for idx, item in enumerate(quick_wins, start=1)
        )
        if quick_wins
        else "- No quick wins detected in this sample."
    )

    score_lines = []
    label_map = {
        "technical": "Technical SEO",
        "content": "Content Quality",
        "onpage": "On-Page SEO",
        "schema": "Schema / Structured Data",
        "performance": "Performance",
        "images": "Images",
        "ai_readiness": "AI Search Readiness",
    }
    for key in ("technical", "content", "onpage", "schema", "performance", "images", "ai_readiness"):
        value = scores[key]
        label = label_map[key]
        if value is None:
            score_lines.append(f"| {label} | Not Measured | Not enough evidence |")
        else:
            score_lines.append(f"| {label} | {value} | {score_band(float(value))} |")
    score_table = "\n".join(score_lines)
    checklist_table = "\n".join(
        f"| {name} | {'Pass' if passed else 'Fail'} | {track} |"
        for name, passed, track in checklist_rows
    )

    visual_lines = []
    visual_lines.append(f"- Status: {visual.get('status', 'skipped')}")
    if visual.get("reason"):
        visual_lines.append(f"- Note: {visual['reason']}")
    if visual.get("screenshots"):
        for shot in visual["screenshots"]:
            try:
                rel = Path(shot).resolve().relative_to(output_dir.resolve()).as_posix()
            except Exception:
                rel = str(shot).replace("\\", "/")
            visual_lines.append(f"- Screenshot: `{rel}`")
    if visual.get("h1_visible_above_fold") is not None:
        visual_lines.append(f"- H1 visible above fold: {visual['h1_visible_above_fold']}")
    if visual.get("cta_visible_above_fold") is not None:
        visual_lines.append(f"- CTA visible above fold: {visual['cta_visible_above_fold']}")
    if visual.get("viewport_meta_present") is not None:
        visual_lines.append(f"- Viewport meta present: {visual['viewport_meta_present']}")
    if visual.get("horizontal_scroll_mobile") is not None:
        visual_lines.append(f"- Horizontal scroll on mobile: {visual['horizontal_scroll_mobile']}")

    full_content = f"""# FULL SEO AUDIT REPORT

## Executive Summary

- Generated: `{generated_at}`
- Target: `{target_url}`
- SEO Health Score: **{total_score}/100** (Grade **{grade}**, Band **{band}**)
- Detected business type: **{business_label}** ({business_confidence}% confidence)
- Pages crawled: **{stats['pages_total']}**
- Successful fetches: **{stats['pages_successful']}**
- HTML pages analyzed: **{stats['pages_html']}**
- Non-HTML pages seen: **{stats['pages_non_html']}**
- Categories not measured: {", ".join(not_measured) if not_measured else "None"}

### Top 5 Critical Issues

{critical_lines}

### Top 5 Quick Wins

{quick_win_lines}

## Category Scores

| Category | Score | Status |
|---|---:|---|
{score_table}

## Top Findings

{issue_lines}

## Crawl Stats

- robots.txt present: {stats['robots_ok']}
- sitemap.xml present: {stats['sitemap_ok']}
- llms.txt present: {stats['llms_ok']}
- Fetch errors: {stats['fetch_errors']}
- Pages skipped by robots: {stats['skipped_by_robots']}
- HTTP errors: {stats['error_pages']} ({stats['status_4xx']}x 4xx, {stats['status_5xx']}x 5xx)
- Missing title tags: {stats['missing_title']}
- Missing meta descriptions: {stats['missing_meta']}
- Missing canonical tags: {stats['missing_canonical']}
- Invalid H1 structure: {stats['invalid_h1']}
- Thin content pages (<300 words): {stats['thin_pages']}
- Noindex pages: {stats['noindex_pages']}
- Duplicate titles: {stats['duplicate_titles']}
- Weakly linked pages (<2 internal links): {stats['weak_internal_link_pages']}
- Pages with schema: {stats['schema_pages']}
- Images missing alt: {stats['missing_alt']}/{stats['total_images']}
- Median response time (ms): {stats['median_response_ms']}
- p90 response time (ms): {stats['p90_response_ms']}
- Word count p25 / median / p75: {stats['word_count_p25']} / {stats['word_count_median']} / {stats['word_count_p75']}
- Security headers present: {len(stats['security_headers']['present'])}/{len(SECURITY_HEADERS)}

## Visual Checks

{chr(10).join(visual_lines)}

## Notes

- Performance score is based on server response-time proxy only, not lab CWV (LCP/INP/CLS).
- This audit is sample-based and depends on crawl reach within the max-page budget.
"""

    full_content += f"""

## Business-Type Signals

{chr(10).join(f"- {signal}" for signal in business.get("signals", [])) if business.get("signals") else "- No high-confidence business-type signals were detected."}

## Technical SEO Findings

{markdown_issue_list([i for i in issues if i.get("category") in ("Technical SEO", "Indexability", "Canonicalization", "Crawl Control", "Security Signals")], with_details=True)}

## Content Quality Findings

{markdown_issue_list([i for i in issues if i.get("category") in ("Content Quality", "Content Structure", "Trust Signals")], with_details=True)}

## On-Page SEO Findings

{markdown_issue_list([i for i in issues if i.get("category") == "On-Page SEO"], with_details=True)}

## Schema Findings

{markdown_issue_list([i for i in issues if i.get("category") == "Schema"], with_details=True)}

## Performance Findings

{markdown_issue_list([i for i in issues if i.get("category") == "Performance"], with_details=True)}

## Image Findings

{markdown_issue_list([i for i in issues if i.get("category") == "Images"], with_details=True)}

## AI Readiness Findings

{markdown_issue_list([i for i in issues if i.get("category") in ("AI Readiness", "Trust Signals")], with_details=True)}

## URL Evidence Appendix

- Missing title examples: {", ".join(stats["example_urls"]["missing_title"]) if stats["example_urls"]["missing_title"] else "None"}
- Missing meta examples: {", ".join(stats["example_urls"]["missing_meta"]) if stats["example_urls"]["missing_meta"] else "None"}
- Thin content examples: {", ".join(stats["example_urls"]["thin_content"]) if stats["example_urls"]["thin_content"] else "None"}
- Noindex examples: {", ".join(stats["example_urls"]["noindex"]) if stats["example_urls"]["noindex"] else "None"}
- Missing schema examples: {", ".join(stats["example_urls"]["missing_schema"]) if stats["example_urls"]["missing_schema"] else "None"}
- Missing alt examples: {", ".join(stats["example_urls"]["alt_missing"]) if stats["example_urls"]["alt_missing"] else "None"}
"""

    full_content += f"""

## Strategic Narrative

### Technical Track Narrative
Technical health scored **{scores['technical']}**, with crawl policy signals (`robots.txt`: {stats['robots_ok']}, `sitemap.xml`: {stats['sitemap_ok']}) and indexability checks (`noindex`: {stats['noindex_pages']}) as the strongest determinants. Even when no severe defects are present, maintain canonical consistency, prevent redirect chain growth, and revalidate security headers on every deployment.

### Content Track Narrative
Content quality scored **{scores['content']}** with thin-page count at **{stats['thin_pages']}** and median word count at **{stats['word_count_median']}**. For the next optimization pass, focus on intent-complete content blocks (problem, solution, proof, CTA) and reinforce E-E-A-T elements such as author evidence, references, and freshness cues.

### On-Page Track Narrative
On-page score is **{scores['onpage']}**. Current completeness: titles missing (**{stats['missing_title']}**), meta descriptions missing (**{stats['missing_meta']}**), H1 anomalies (**{stats['invalid_h1']}**). Keep title and meta uniqueness above 90% on indexable templates and monitor template regressions in CI.

### Schema Track Narrative
Schema score is **{scores['schema']}** with coverage of **{stats['schema_pages']}/{max(stats['pages_html'], 1)}** crawled HTML pages. Expand schema depth by template class (Organization, WebSite, BreadcrumbList, plus Article/Product/Service variants) and validate serialization for every major template family.

### Performance Track Narrative
Performance scored **{scores['performance']}** based on HTTP response proxy. Current latency baseline is median **{stats['median_response_ms']}ms** and p90 **{stats['p90_response_ms']}ms**. Treat this as a directional benchmark and pair it with field CWV for production prioritization.

### AI Readiness Track Narrative
AI readiness scored **{scores['ai_readiness']}**. Root-level AI control files (`llms.txt`: {stats['llms_ok']}) and trust navigation signals (`about/contact`: {stats['about_or_contact_links']}) remain core levers for citation quality and answer inclusion.

## KPI Baseline Snapshot

| KPI | Baseline | Interpretation |
|---|---:|---|
| Crawl success rate | {round((stats['pages_successful'] / max(stats['pages_total'], 1)) * 100, 1)}% | How much of the crawl budget returned usable responses |
| HTML coverage | {round((stats['pages_html'] / max(stats['pages_successful'], 1)) * 100, 1)}% | Fraction of successful responses that were parseable HTML |
| Schema coverage | {round((stats['schema_pages'] / max(stats['pages_html'], 1)) * 100, 1)}% | Structured-data penetration across templates |
| Metadata completeness | {metadata_completeness}% | Combined title/meta readiness proxy |
| Image accessibility readiness | {round((1 - (stats['missing_alt'] / max(stats['total_images'], 1))) * 100, 1) if stats['total_images'] else 100.0}% | Alt-text coverage across discovered media |

## Audit Checklist Matrix

| Check | Result | Track |
|---|---|---|
{checklist_table}

## Interpretation Notes

- A `Pass` in this matrix means the crawl sample met a baseline threshold, not that the entire domain is perfect.
- A `Fail` should be treated as a directional signal to investigate templates and URL clusters, not only isolated pages.
- Repeat this same checklist after each remediation sprint to verify measurable movement.
- Keep crawl settings consistent between runs for valid historical comparison.

## 30-60-90 Day Execution Model

### Days 0-30
- Stabilize crawl/index signals: resolve Critical and High issues from `ACTION-PLAN.md`.
- Lock metadata and canonical rules at template level.
- Publish monitoring checks for robots, sitemap, and major status-code shifts.

### Days 31-60
- Expand depth on thin but strategic pages and consolidate low-value duplicates.
- Increase schema breadth on high-traffic templates with validation in pre-release checks.
- Improve internal linking pathways to money pages and strategic informational hubs.

### Days 61-90
- Refine entity clarity and source attribution for higher citation probability.
- Benchmark against top competitors for coverage gaps and query-intent mismatch.
- Move from reactive fixes to release-gated SEO quality controls.
"""

    by_priority = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for item in issues:
        by_priority[item["priority"]].append(item)

    plan_lines = [
        "# SEO Action Plan",
        "",
        f"Generated: `{generated_at}`",
        f"Target: `{target_url}`",
        f"Baseline health score: **{total_score}/100**",
        "",
        "## Roadmap",
        "",
    ]
    phase_map = [
        ("Phase 1 (0-48h): Critical Risk Remediation", "Critical"),
        ("Phase 2 (Days 3-7): High Impact Work", "High"),
        ("Phase 3 (Weeks 2-4): Structural Optimization", "Medium"),
        ("Backlog: Ongoing Improvements", "Low"),
    ]
    default_phase_tasks = {
        "Critical": [
            "Validate indexability controls on all money pages (robots/meta/canonical consistency).",
            "Run smoke tests for robots.txt, sitemap.xml, and status-code integrity after each deployment.",
        ],
        "High": [
            "Expand thin but high-intent pages with deeper topical sections and supporting entities.",
            "Review template metadata for uniqueness and query-intent alignment.",
        ],
        "Medium": [
            "Increase schema richness by template type and revalidate JSON-LD output.",
            "Improve internal linking depth from authority pages to conversion pages.",
        ],
        "Low": [
            "Establish monthly AI-readiness checks (llms.txt, attribution pages, citation-friendly formatting).",
            "Track leaderboard terms and competitor SERP shifts for opportunity discovery.",
        ],
    }
    for phase_label, priority in phase_map:
        plan_lines.append(f"### {phase_label}")
        if not by_priority[priority]:
            plan_lines.append("- No urgent defects in this tier from the sampled crawl.")
            for task in default_phase_tasks[priority]:
                plan_lines.append(f"- Baseline task: {task}")
            plan_lines.append("")
            continue
        for idx, item in enumerate(by_priority[priority], start=1):
            plan_lines.append(f"{idx}. **{item['title']}** ({item.get('category', 'General')})")
            plan_lines.append(f"   - Why it matters: {item.get('impact', item['detail'])}")
            plan_lines.append(f"   - Action: {item.get('recommendation', item['detail'])}")
            plan_lines.append(f"   - Effort / lift: {item.get('effort', 'n/a')} / {item.get('expected_lift', 'n/a')}")
            if item.get("evidence"):
                plan_lines.append(f"   - Evidence: {', '.join(item['evidence'][:5])}")
        plan_lines.append("")

    plan_lines.extend(
        [
            "## Success Criteria",
            "",
            "- Resolve all Critical items before next crawl.",
            "- Reduce High-priority issue count by at least 50% in the first remediation cycle.",
            "- Push title/meta/schema completeness above 90% on indexable templates.",
            "- Validate improvements with a rerun under the same crawl settings for apples-to-apples comparison.",
            "",
        ]
    )

    full_report.write_text(full_content, encoding="utf-8")
    action_plan.write_text("\n".join(plan_lines).strip() + "\n", encoding="utf-8")
    summary_json.write_text(
        json.dumps(
            {
                "target_url": target_url,
                "generated_at": generated_at,
                "health_score": total_score,
                "health_grade": grade,
                "health_band": band,
                "scores": scores,
                "stats": stats,
                "issues": issues,
                "visual": visual,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    issues_json.write_text(json.dumps(issues, indent=2), encoding="utf-8")


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
    print(f"Summary: {output_dir / 'SUMMARY.json'}")
    print(f"Issues: {output_dir / 'ISSUES.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
