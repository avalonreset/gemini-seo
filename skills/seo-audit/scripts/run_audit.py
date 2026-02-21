#!/usr/bin/env python3
"""
Self-contained SEO audit runner for the seo-audit skill.

Usage:
    python run_audit.py https://example.com
    python run_audit.py https://example.com --max-pages 200 --visual auto
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import math
import os
import re
import socket
import statistics
import subprocess
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
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

SCORE_LABELS = {
    "technical": "Technical SEO",
    "content": "Content Quality",
    "onpage": "On-Page SEO",
    "schema": "Schema / Structured Data",
    "performance": "Performance",
    "images": "Images",
    "ai_readiness": "AI Search Readiness",
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


def _slugify(value: str, default: str = "section") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return (cleaned[:48] or default).strip("-")


_OCR_ENGINE: Any | None = None
_OCR_ERROR: str = ""


def _get_ocr_engine() -> tuple[Any | None, str]:
    global _OCR_ENGINE, _OCR_ERROR
    if _OCR_ENGINE is False:
        return None, _OCR_ERROR
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE, ""
    try:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
        _OCR_ERROR = ""
        return _OCR_ENGINE, ""
    except Exception as exc:
        _OCR_ENGINE = False
        _OCR_ERROR = str(exc)
        return None, _OCR_ERROR


def _run_ocr_excerpt(image_path: Path) -> dict[str, Any]:
    engine, reason = _get_ocr_engine()
    if engine is None:
        return {
            "status": "not_available",
            "reason": reason or "rapidocr_onnxruntime not installed",
            "text": "",
            "line_count": 0,
            "avg_confidence": None,
        }
    try:
        results, _elapsed = engine(str(image_path))
    except Exception as exc:
        return {
            "status": "failed",
            "reason": str(exc),
            "text": "",
            "line_count": 0,
            "avg_confidence": None,
        }
    if not results:
        return {
            "status": "ok",
            "reason": "",
            "text": "",
            "line_count": 0,
            "avg_confidence": None,
        }

    lines: list[str] = []
    confs: list[float] = []
    for item in results[:60]:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        txt = str(item[1] or "").strip()
        if txt:
            lines.append(re.sub(r"\s+", " ", txt))
        try:
            confs.append(float(item[2]))
        except Exception:
            pass
    excerpt = " ".join(lines).strip()
    if len(excerpt) > 280:
        excerpt = excerpt[:277].rstrip() + "..."
    avg_conf = round(sum(confs) / len(confs), 3) if confs else None
    return {
        "status": "ok",
        "reason": "",
        "text": excerpt,
        "line_count": len(lines),
        "avg_confidence": avg_conf,
    }


def capture_section_intelligence(page: Any, sections_dir: Path, max_sections: int = 8) -> tuple[list[dict[str, Any]], list[str]]:
    sections: list[dict[str, Any]] = []
    screenshots: list[str] = []
    sections_dir.mkdir(parents=True, exist_ok=True)

    candidates = page.query_selector_all("main section, main article, section, article, [role='region'], header, footer")
    seen_buckets: set[int] = set()

    for handle in candidates:
        if len(sections) >= max_sections:
            break

        try:
            box = handle.bounding_box()
        except Exception:
            box = None
        if not box:
            continue

        width = float(box.get("width") or 0.0)
        height = float(box.get("height") or 0.0)
        top = float(box.get("y") or 0.0)
        if width < 480 or height < 160 or top < 0:
            continue

        bucket = int(top // 90)
        if bucket in seen_buckets:
            continue
        seen_buckets.add(bucket)

        try:
            meta = handle.evaluate(
                """(el) => {
                    const headingNode = el.querySelector('h1, h2, h3, h4');
                    const heading = (headingNode?.innerText || el.getAttribute('aria-label') || '').trim();
                    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                    const snippet = text.slice(0, 260);
                    const wordCount = text ? text.split(/\\s+/).length : 0;
                    const ctaCount = el.querySelectorAll("a[href*='signup'],a[href*='demo'],a[href*='contact'],a[href*='start'],button,.cta,[class*='cta']").length;
                    const formCount = el.querySelectorAll('form,input,textarea,select').length;
                    const linkCount = el.querySelectorAll('a[href]').length;
                    const tag = (el.tagName || '').toLowerCase();
                    const role = (el.getAttribute('role') || '').toLowerCase();
                    const id = (el.id || '').toLowerCase();
                    const classes = (typeof el.className === 'string' ? el.className : (el.className?.baseVal || '')).toLowerCase();
                    const hasMedia = !!el.querySelector('img,video,picture,svg,canvas');
                    return {
                        heading,
                        snippet,
                        word_count: wordCount,
                        cta_count: ctaCount,
                        form_count: formCount,
                        link_count: linkCount,
                        tag,
                        role,
                        id,
                        classes,
                        has_media: hasMedia,
                    };
                }"""
            )
        except Exception:
            continue

        heading = re.sub(r"\s+", " ", str(meta.get("heading") or "")).strip()
        notes: list[str] = []
        capture_notes: list[str] = []

        word_count = int(meta.get("word_count") or 0)
        cta_count = int(meta.get("cta_count") or 0)
        form_count = int(meta.get("form_count") or 0)
        link_count = int(meta.get("link_count") or 0)
        snippet = re.sub(r"\s+", " ", str(meta.get("snippet") or "")).strip()
        tag = str(meta.get("tag") or "").lower()
        role = str(meta.get("role") or "").lower()
        identity_blob = " ".join(
            [
                heading,
                str(meta.get("id") or ""),
                str(meta.get("classes") or ""),
                tag,
                role,
            ]
        ).lower()

        semantic_type = "content"
        if top < 260 or "hero" in identity_blob:
            semantic_type = "hero"
        elif tag == "header" or role == "banner":
            semantic_type = "header"
        elif "nav" in identity_blob or role == "navigation":
            semantic_type = "navigation"
        elif form_count > 0:
            semantic_type = "lead-capture"
        elif cta_count > 0:
            semantic_type = "cta-block"
        elif tag == "footer" or role == "contentinfo" or "footer" in identity_blob:
            semantic_type = "footer"
        elif link_count >= 12:
            semantic_type = "link-hub"

        fallback_labels = {
            "hero": "Hero Section",
            "header": "Header Block",
            "navigation": "Navigation Block",
            "lead-capture": "Lead Capture Section",
            "cta-block": "CTA Section",
            "footer": "Footer Section",
            "link-hub": "Link Hub Section",
            "content": "Content Section",
        }
        label = heading or fallback_labels.get(semantic_type, f"Section {len(sections) + 1}")

        if not heading:
            notes.append("No explicit heading detected.")
        if word_count < 35:
            notes.append("Content depth is light in this section.")
        if word_count >= 150:
            notes.append("Dense copy block may need readability chunking.")
        if cta_count == 0 and top < 1400:
            notes.append("No clear CTA in upper-page section.")
        if cta_count >= 2:
            notes.append("Multiple CTA elements compete for attention.")
        if form_count > 0:
            notes.append("Contains form/capture elements.")
        if link_count >= 10:
            notes.append("High link density; review for focus.")
        observation = " ".join(notes) if notes else "Section structure looks balanced."

        if top < 260:
            capture_notes.append("Above-the-fold framing and value proposition review.")
        if semantic_type in ("hero", "header", "navigation"):
            capture_notes.append("Primary orientation block that shapes first impression.")
        if cta_count > 0:
            capture_notes.append("Contains CTA elements for conversion-path evaluation.")
        if form_count > 0:
            capture_notes.append("Contains form controls for friction and trust review.")
        if link_count >= 12:
            capture_notes.append("High-link cluster selected for IA/focus signal review.")
        if word_count >= 120:
            capture_notes.append("Text-heavy block selected for readability and hierarchy checks.")
        if bool(meta.get("has_media")):
            capture_notes.append("Includes media/canvas assets that can hide OCR-only messaging.")
        if "pricing" in identity_blob or "plan" in identity_blob:
            capture_notes.append("Commercial intent area selected for clarity and offer framing.")
        capture_reason = " ".join(capture_notes[:2]) or "Representative section chosen for structural and visual QA."

        shot_path: str | None = None
        ocr = {
            "status": "not_run",
            "reason": "",
            "text": "",
            "line_count": 0,
            "avg_confidence": None,
        }
        shot_file = sections_dir / f"{len(sections) + 1:02d}-{_slugify(label)}.png"
        try:
            handle.screenshot(path=str(shot_file))
            shot_path = str(shot_file)
            screenshots.append(shot_path)
            ocr = _run_ocr_excerpt(shot_file)
        except Exception:
            shot_path = None

        if ocr.get("text") and word_count < 25:
            notes.append("OCR found visual text despite sparse DOM text (possible canvas/image text).")
            observation = " ".join(notes)

        sections.append(
            {
                "label": label,
                "snippet": snippet,
                "observation": observation,
                "top_px": round(top, 1),
                "height_px": round(height, 1),
                "word_count": word_count,
                "cta_count": cta_count,
                "form_count": form_count,
                "link_count": link_count,
                "semantic_type": semantic_type,
                "capture_reason": capture_reason,
                "screenshot": shot_path,
                "ocr_status": ocr.get("status"),
                "ocr_reason": ocr.get("reason"),
                "ocr_excerpt": ocr.get("text", ""),
                "ocr_line_count": int(ocr.get("line_count") or 0),
                "ocr_avg_confidence": ocr.get("avg_confidence"),
            }
        )

    return sections, screenshots


def run_visual_checks(url: str, output_dir: Path, mode: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "screenshots": [],
        "viewport_screenshots": [],
        "section_screenshots": [],
        "sections": [],
        "ocr_status": "not_run",
        "ocr_reason": "",
        "ocr_sections_with_text": 0,
        "ocr_sections_total": 0,
        "ocr_avg_confidence": None,
        "h1_visible_above_fold": None,
        "cta_visible_above_fold": None,
        "viewport_meta_present": None,
        "horizontal_scroll_mobile": None,
        "mobile_touch_targets_small": None,
        "mobile_touch_targets_total": None,
        "mobile_min_font_px": None,
        "mobile_text_readability_ok": None,
        "mobile_nav_accessible": None,
        "desktop_overlap_issues": None,
        "desktop_overflow_issues": None,
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
            desktop_page.screenshot(path=str(desktop_file), full_page=False)
            result["screenshots"].append(str(desktop_file))
            result["viewport_screenshots"].append(
                {
                    "label": "desktop",
                    "path": str(desktop_file),
                    "viewport": {"width": 1920, "height": 1080},
                }
            )

            section_data, section_shots = capture_section_intelligence(desktop_page, shots_dir / "sections", max_sections=8)
            result["sections"] = section_data
            result["section_screenshots"] = section_shots
            result["ocr_sections_total"] = len(section_data)
            ocr_ok = [s for s in section_data if s.get("ocr_status") == "ok" and s.get("ocr_excerpt")]
            result["ocr_sections_with_text"] = len(ocr_ok)
            ocr_conf = [float(s["ocr_avg_confidence"]) for s in section_data if isinstance(s.get("ocr_avg_confidence"), (int, float))]
            result["ocr_avg_confidence"] = round(sum(ocr_conf) / len(ocr_conf), 3) if ocr_conf else None
            ocr_fail = [s for s in section_data if s.get("ocr_status") in ("not_available", "failed")]
            if ocr_fail:
                result["ocr_status"] = "partial"
                reasons = [str(s.get("ocr_reason") or "").strip() for s in ocr_fail if s.get("ocr_reason")]
                result["ocr_reason"] = reasons[0] if reasons else ""
            else:
                result["ocr_status"] = "ok"
                result["ocr_reason"] = ""

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

            desktop_diagnostics = desktop_page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('body *')).slice(0, 1400);
                    const rects = [];
                    let overflow = 0;

                    for (const el of nodes) {
                        const style = getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 20 || r.height < 20) continue;
                        if (r.right > window.innerWidth + 2) overflow += 1;
                        rects.push({x: r.left, y: r.top, w: r.width, h: r.height});
                        if (rects.length >= 260) break;
                    }

                    let overlap = 0;
                    for (let i = 0; i < rects.length && i < 200; i++) {
                        const a = rects[i];
                        for (let j = i + 1; j < Math.min(rects.length, i + 26); j++) {
                            const b = rects[j];
                            const xOverlap = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
                            const yOverlap = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
                            if (xOverlap > 34 && yOverlap > 18) {
                                overlap += 1;
                                if (overlap > 80) break;
                            }
                        }
                        if (overlap > 80) break;
                    }
                    return {overlap_issues: overlap, overflow_issues: overflow};
                }"""
            )
            result["desktop_overlap_issues"] = int(desktop_diagnostics.get("overlap_issues") or 0)
            result["desktop_overflow_issues"] = int(desktop_diagnostics.get("overflow_issues") or 0)

            desktop_context.close()

            for label, width, height in (("laptop", 1366, 768), ("tablet", 768, 1024)):
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(500)
                file_path = shots_dir / f"homepage-{label}.png"
                page.screenshot(path=str(file_path), full_page=False)
                result["screenshots"].append(str(file_path))
                result["viewport_screenshots"].append(
                    {
                        "label": label,
                        "path": str(file_path),
                        "viewport": {"width": width, "height": height},
                    }
                )
                context.close()

            mobile_context = browser.new_context(viewport={"width": 375, "height": 812})
            mobile_page = mobile_context.new_page()
            mobile_page.goto(url, wait_until="networkidle", timeout=30000)
            mobile_page.wait_for_timeout(500)

            mobile_file = shots_dir / "homepage-mobile.png"
            mobile_page.screenshot(path=str(mobile_file), full_page=False)
            result["screenshots"].append(str(mobile_file))
            result["viewport_screenshots"].append(
                {
                    "label": "mobile",
                    "path": str(mobile_file),
                    "viewport": {"width": 375, "height": 812},
                }
            )

            viewport_meta = mobile_page.query_selector('meta[name="viewport"]')
            result["viewport_meta_present"] = viewport_meta is not None

            scroll_width = int(mobile_page.evaluate("document.documentElement.scrollWidth"))
            viewport_width = int(mobile_page.evaluate("window.innerWidth"))
            result["horizontal_scroll_mobile"] = scroll_width > viewport_width

            mobile_diagnostics = mobile_page.evaluate(
                """() => {
                    const candidates = Array.from(document.querySelectorAll("a,button,input,select,textarea,[role='button'],[onclick]")).slice(0, 900);
                    let touchTotal = 0;
                    let touchSmall = 0;
                    for (const el of candidates) {
                        const style = getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width <= 0 || r.height <= 0) continue;
                        if (r.bottom < 0 || r.top > window.innerHeight * 6) continue;
                        touchTotal += 1;
                        if (r.width < 48 || r.height < 48) touchSmall += 1;
                    }

                    const textNodes = Array.from(document.querySelectorAll("p,li,a,button,span,label,h1,h2,h3,h4,h5,h6")).slice(0, 1200);
                    let minFont = null;
                    for (const el of textNodes) {
                        const style = getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        const fs = parseFloat(style.fontSize || "0");
                        if (!Number.isFinite(fs) || fs <= 0) continue;
                        if (minFont === null || fs < minFont) minFont = fs;
                    }

                    const nav = document.querySelector("nav,[role='navigation'],button[aria-label*='menu' i],button[aria-controls*='menu' i],.hamburger,.menu-toggle");
                    return {
                        touch_targets_total: touchTotal,
                        touch_targets_small: touchSmall,
                        min_font_px: minFont,
                        mobile_nav_accessible: !!nav,
                    };
                }"""
            )
            result["mobile_touch_targets_total"] = int(mobile_diagnostics.get("touch_targets_total") or 0)
            result["mobile_touch_targets_small"] = int(mobile_diagnostics.get("touch_targets_small") or 0)
            min_font = mobile_diagnostics.get("min_font_px")
            result["mobile_min_font_px"] = round(float(min_font), 1) if isinstance(min_font, (int, float)) else None
            result["mobile_text_readability_ok"] = (
                (result["mobile_min_font_px"] is not None and result["mobile_min_font_px"] >= 16.0)
            )
            result["mobile_nav_accessible"] = bool(mobile_diagnostics.get("mobile_nav_accessible"))

            mobile_context.close()
            browser.close()

        result["status"] = "ok"
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["reason"] = str(exc)
        return result


def _tail_lines(text: str, limit: int = 20) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-limit:])


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _coerce_metric_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return str(value)


def _extract_summary_metrics(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    metrics: dict[str, Any] = {}
    for key in (
        "health_score",
        "overall_score",
        "score",
        "health",
        "grade",
        "status",
        "issues_count",
        "total_issues",
        "priority_counts",
        "visual_status",
    ):
        if key in summary:
            metrics[key] = _coerce_metric_value(summary[key])
    if "issues" in summary and isinstance(summary["issues"], list):
        metrics["issues"] = len(summary["issues"])
    if "scores" in summary and isinstance(summary["scores"], dict):
        measured = [float(v) for v in summary["scores"].values() if isinstance(v, (int, float))]
        if measured:
            metrics["avg_category_score"] = round(sum(measured) / len(measured), 1)
    return metrics


def _build_orchestration_tracks(
    target_url: str,
    output_dir: Path,
    timeout: int,
    visual_mode: str,
) -> list[dict[str, Any]]:
    skills_root = Path(__file__).resolve().parents[2]
    tracks_root = output_dir / "tracks"
    tracks_root.mkdir(parents=True, exist_ok=True)

    mobile_mode = "on" if visual_mode == "on" else ("off" if visual_mode == "off" else "auto")

    return [
        {
            "name": "technical",
            "output_dir": tracks_root / "technical",
            "cmd": [
                sys.executable,
                str(skills_root / "seo-technical" / "scripts" / "run_technical_audit.py"),
                target_url,
                "--timeout",
                str(timeout),
                "--mobile-check",
                mobile_mode,
                "--output-dir",
                str(tracks_root / "technical"),
            ],
        },
        {
            "name": "content",
            "output_dir": tracks_root / "content",
            "cmd": [
                sys.executable,
                str(skills_root / "seo-content" / "scripts" / "run_content_audit.py"),
                target_url,
                "--timeout",
                str(timeout),
                "--output-dir",
                str(tracks_root / "content"),
            ],
        },
        {
            "name": "schema",
            "output_dir": tracks_root / "schema",
            "cmd": [
                sys.executable,
                str(skills_root / "seo-schema" / "scripts" / "run_schema.py"),
                "analyze",
                "--url",
                target_url,
                "--timeout",
                str(timeout),
                "--output-dir",
                str(tracks_root / "schema"),
            ],
        },
        {
            "name": "sitemap",
            "output_dir": tracks_root / "sitemap",
            "cmd": [
                sys.executable,
                str(skills_root / "seo-sitemap" / "scripts" / "run_sitemap.py"),
                "analyze",
                "--sitemap-url",
                urljoin(target_url, "/sitemap.xml"),
                "--timeout",
                str(timeout),
                "--output-dir",
                str(tracks_root / "sitemap"),
            ],
        },
        {
            "name": "images",
            "output_dir": tracks_root / "images",
            "cmd": [
                sys.executable,
                str(skills_root / "seo-images" / "scripts" / "run_image_audit.py"),
                "--url",
                target_url,
                "--timeout",
                str(timeout),
                "--output-dir",
                str(tracks_root / "images"),
            ],
        },
        {
            "name": "page",
            "output_dir": tracks_root / "page",
            "cmd": [
                sys.executable,
                str(skills_root / "seo-page" / "scripts" / "run_page_audit.py"),
                target_url,
                "--timeout",
                str(timeout),
                "--visual",
                visual_mode,
                "--output-dir",
                str(tracks_root / "page"),
            ],
        },
        {
            "name": "geo",
            "output_dir": tracks_root / "geo",
            "cmd": [
                sys.executable,
                str(skills_root / "seo-geo" / "scripts" / "run_geo_analysis.py"),
                "--url",
                target_url,
                "--timeout",
                str(timeout),
                "--output-dir",
                str(tracks_root / "geo"),
            ],
        },
    ]


def run_specialist_orchestration(
    target_url: str,
    output_dir: Path,
    timeout: int,
    visual_mode: str,
) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    track_specs = _build_orchestration_tracks(target_url, output_dir, timeout, visual_mode)

    def run_track(track: dict[str, Any]) -> dict[str, Any]:
        name = str(track["name"])
        out_dir = Path(track["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(x) for x in track["cmd"]]
        start_ts = time.perf_counter()
        status = "failed"
        rc = -1
        stdout_text = ""
        stderr_text = ""
        reason = ""

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(Path(__file__).resolve().parents[3]),
                capture_output=True,
                text=True,
                timeout=max(180, timeout * 20),
            )
            rc = int(proc.returncode)
            stdout_text = proc.stdout or ""
            stderr_text = proc.stderr or ""
            status = "ok" if rc == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "failed"
            reason = "timeout"
        except Exception as exc:
            status = "failed"
            reason = str(exc)

        duration = round(time.perf_counter() - start_ts, 2)
        summary_path = out_dir / "SUMMARY.json"
        summary_data = _safe_read_json(summary_path)
        report_files = sorted(p.name for p in out_dir.glob("*.md"))
        primary_report = ""
        for candidate in report_files:
            if "REPORT" in candidate.upper():
                primary_report = candidate
                break
        if not primary_report and report_files:
            primary_report = report_files[0]

        return {
            "name": name,
            "status": status,
            "exit_code": rc,
            "duration_sec": duration,
            "output_dir": str(out_dir),
            "summary_path": str(summary_path) if summary_path.exists() else "",
            "summary_metrics": _extract_summary_metrics(summary_data),
            "report_files": report_files,
            "primary_report": primary_report,
            "reason": reason,
            "stdout_tail": _tail_lines(stdout_text),
            "stderr_tail": _tail_lines(stderr_text),
        }

    indexed: dict[str, int] = {str(item["name"]): idx for idx, item in enumerate(track_specs)}
    results: list[dict[str, Any]] = []
    max_workers = min(7, len(track_specs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(run_track, item) for item in track_specs]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda item: indexed.get(str(item["name"]), 999))
    success_count = sum(1 for item in results if item["status"] == "ok")
    completed = datetime.now(UTC).isoformat()

    orchestration = {
        "enabled": True,
        "started_at": started,
        "completed_at": completed,
        "total_tracks": len(results),
        "success_count": success_count,
        "failed_tracks": [item["name"] for item in results if item["status"] != "ok"],
        "tracks": results,
        "summary_file": str(output_dir / "ORCHESTRATION-SUMMARY.json"),
    }
    summary_path = output_dir / "ORCHESTRATION-SUMMARY.json"
    summary_path.write_text(json.dumps(orchestration, indent=2), encoding="utf-8")
    return orchestration


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


def _extract_metric_percentile(metrics: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        node = metrics.get(key)
        if isinstance(node, dict) and node.get("percentile") is not None:
            try:
                return float(node["percentile"])
            except Exception:
                continue
    return None


def _normalize_cls(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1.0:
        return value / 100.0
    return value


def _score_threshold(value: float | None, good: float, poor: float) -> float | None:
    if value is None:
        return None
    if value <= good:
        return 100.0
    if value >= poor:
        return 30.0
    return round(100.0 - ((value - good) / (poor - good)) * 70.0, 1)


def _fetch_pagespeed_payload(target_url: str, strategy: str, timeout: int, api_key: str) -> dict[str, Any]:
    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params: dict[str, Any] = {
        "url": target_url,
        "strategy": strategy,
        "category": ["performance", "seo", "best-practices", "accessibility"],
        "locale": "en_US",
    }
    if api_key:
        params["key"] = api_key
    try:
        resp = requests.get(endpoint, params=params, timeout=max(30, timeout * 2))
    except requests.exceptions.RequestException as exc:
        return {"status": "error", "reason": str(exc), "http_status": None}
    if resp.status_code != 200:
        reason = f"HTTP {resp.status_code}"
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                err = payload.get("error", {})
                if isinstance(err, dict) and err.get("message"):
                    reason = f"{reason}: {err['message']}"
        except Exception:
            pass
        return {"status": "error", "reason": reason, "http_status": resp.status_code}
    try:
        return {"status": "ok", "payload": resp.json(), "http_status": 200}
    except Exception as exc:
        return {"status": "error", "reason": f"Invalid JSON: {exc}", "http_status": 200}


def run_cwv_assessment(target_url: str, timeout: int, source: str, pagespeed_key: str) -> dict[str, Any]:
    if source == "off":
        return {"status": "disabled", "source": "off", "reason": "CWV API checks disabled"}
    if source not in ("auto", "pagespeed"):
        return {"status": "disabled", "source": source, "reason": "Unsupported CWV source"}

    mobile = _fetch_pagespeed_payload(target_url, "mobile", timeout, pagespeed_key)
    desktop = _fetch_pagespeed_payload(target_url, "desktop", timeout, pagespeed_key)
    if mobile.get("status") != "ok" and desktop.get("status") != "ok":
        reason = mobile.get("reason") or desktop.get("reason") or "PageSpeed request failed"
        return {
            "status": "unavailable",
            "source": "pagespeed",
            "reason": reason,
            "mobile": mobile,
            "desktop": desktop,
        }

    def parse_payload(track: dict[str, Any]) -> dict[str, Any]:
        if track.get("status") != "ok":
            return {}
        payload = track.get("payload") or {}
        lighthouse = payload.get("lighthouseResult") or {}
        categories = lighthouse.get("categories") or {}
        audits = lighthouse.get("audits") or {}

        perf_score = categories.get("performance", {}).get("score")
        perf = round(float(perf_score) * 100.0, 1) if isinstance(perf_score, (int, float)) else None
        lab_lcp = audits.get("largest-contentful-paint", {}).get("numericValue")
        lab_inp = audits.get("interaction-to-next-paint", {}).get("numericValue")
        lab_cls = audits.get("cumulative-layout-shift", {}).get("numericValue")
        lab_lcp = round(float(lab_lcp), 1) if isinstance(lab_lcp, (int, float)) else None
        lab_inp = round(float(lab_inp), 1) if isinstance(lab_inp, (int, float)) else None
        lab_cls = round(float(lab_cls), 3) if isinstance(lab_cls, (int, float)) else None

        load_exp = payload.get("loadingExperience", {}).get("metrics", {}) or {}
        origin_exp = payload.get("originLoadingExperience", {}).get("metrics", {}) or {}
        field_lcp = _extract_metric_percentile(load_exp, ["LARGEST_CONTENTFUL_PAINT_MS"])
        field_inp = _extract_metric_percentile(load_exp, ["INTERACTION_TO_NEXT_PAINT", "INTERACTION_TO_NEXT_PAINT_MS"])
        field_cls = _extract_metric_percentile(load_exp, ["CUMULATIVE_LAYOUT_SHIFT_SCORE"])
        origin_lcp = _extract_metric_percentile(origin_exp, ["LARGEST_CONTENTFUL_PAINT_MS"])
        origin_inp = _extract_metric_percentile(origin_exp, ["INTERACTION_TO_NEXT_PAINT", "INTERACTION_TO_NEXT_PAINT_MS"])
        origin_cls = _extract_metric_percentile(origin_exp, ["CUMULATIVE_LAYOUT_SHIFT_SCORE"])

        field_lcp = field_lcp if field_lcp is not None else origin_lcp
        field_inp = field_inp if field_inp is not None else origin_inp
        field_cls = _normalize_cls(field_cls if field_cls is not None else origin_cls)

        return {
            "lighthouse_perf_score": perf,
            "lab_lcp_ms": lab_lcp,
            "lab_inp_ms": lab_inp,
            "lab_cls": lab_cls,
            "field_lcp_ms": round(field_lcp, 1) if field_lcp is not None else None,
            "field_inp_ms": round(field_inp, 1) if field_inp is not None else None,
            "field_cls": round(field_cls, 3) if field_cls is not None else None,
            "analysis_url": payload.get("analysisUTCTimestamp"),
            "id": payload.get("id"),
        }

    mobile_data = parse_payload(mobile)
    desktop_data = parse_payload(desktop)

    lcp_score = _score_threshold(mobile_data.get("field_lcp_ms"), 2500.0, 4000.0)
    inp_score = _score_threshold(mobile_data.get("field_inp_ms"), 200.0, 500.0)
    cls_score = _score_threshold(mobile_data.get("field_cls"), 0.10, 0.25)
    field_scores = [x for x in (lcp_score, inp_score, cls_score) if x is not None]
    field_score = round(sum(field_scores) / len(field_scores), 1) if field_scores else None

    lab_candidates = [x for x in (mobile_data.get("lighthouse_perf_score"), desktop_data.get("lighthouse_perf_score")) if isinstance(x, (int, float))]
    lab_score = round(sum(float(x) for x in lab_candidates) / len(lab_candidates), 1) if lab_candidates else None

    composite: float | None = None
    if lab_score is not None and field_score is not None:
        composite = round(lab_score * 0.6 + field_score * 0.4, 1)
    elif lab_score is not None:
        composite = lab_score
    elif field_score is not None:
        composite = field_score

    return {
        "status": "ok",
        "source": "pagespeed",
        "reason": "",
        "composite_score": composite,
        "lab_score": lab_score,
        "field_score": field_score,
        "mobile": mobile_data,
        "desktop": desktop_data,
        "raw_http": {
            "mobile_status": mobile.get("http_status"),
            "desktop_status": desktop.get("http_status"),
        },
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
    cwv: dict[str, Any] | None = None,
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

    performance_source = "proxy"
    performance = None
    if cwv and cwv.get("status") == "ok" and isinstance(cwv.get("composite_score"), (int, float)):
        performance = float(cwv["composite_score"])
        performance_source = "pagespeed"
    else:
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
    if cwv and cwv.get("status") == "ok":
        mobile_cwv = cwv.get("mobile", {}) or {}
        lcp = mobile_cwv.get("field_lcp_ms")
        inp = mobile_cwv.get("field_inp_ms")
        cls = mobile_cwv.get("field_cls")
        if isinstance(lcp, (int, float)) and lcp > 4000:
            issues.append(
                make_issue(
                    priority="High",
                    category="Performance",
                    title="Poor field LCP (mobile)",
                    detail=f"Field LCP p75 is {round(float(lcp), 1)}ms (target <= 2500ms).",
                    impact="Slow loading hurts rankings, user retention, and conversion rates.",
                    recommendation="Optimize hero assets, critical CSS, TTFB, and render-blocking scripts.",
                    evidence=[start_url],
                    effort="Medium",
                    expected_lift="High",
                )
            )
        if isinstance(inp, (int, float)) and inp > 500:
            issues.append(
                make_issue(
                    priority="High",
                    category="Performance",
                    title="Poor field INP (mobile)",
                    detail=f"Field INP p75 is {round(float(inp), 1)}ms (target <= 200ms).",
                    impact="Input delay degrades UX and can suppress performance-led ranking gains.",
                    recommendation="Reduce main-thread blocking JS and optimize event handlers.",
                    evidence=[start_url],
                    effort="Medium",
                    expected_lift="High",
                )
            )
        if isinstance(cls, (int, float)) and cls > 0.25:
            issues.append(
                make_issue(
                    priority="High",
                    category="Performance",
                    title="Poor field CLS (mobile)",
                    detail=f"Field CLS p75 is {round(float(cls), 3)} (target <= 0.10).",
                    impact="Layout instability damages perceived quality and engagement.",
                    recommendation="Reserve dimensions for media/embeds and stabilize dynamic UI insertion.",
                    evidence=[start_url],
                    effort="Medium",
                    expected_lift="Medium",
                )
            )
    elif cwv and cwv.get("status") == "unavailable":
        issues.append(
            make_issue(
                priority="Low",
                category="Performance",
                title="Live CWV API data unavailable",
                detail=f"PageSpeed/CrUX fetch failed: {cwv.get('reason', 'unknown error')}.",
                impact="Performance score falls back to response-time proxy and may miss real-user regressions.",
                recommendation="Provide PAGESPEED_API_KEY and rerun for full lab+field CWV coverage.",
                evidence=[start_url],
                effort="Low",
                expected_lift="Low",
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
        "performance_source": performance_source,
        "cwv": cwv or {"status": "disabled", "source": "off", "reason": "not requested"},
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


def _fmt_number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        rounded = round(value, digits)
        if digits == 0:
            return str(int(rounded))
        return f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _bool_label(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "n/a"


def _priority_badge(priority: str) -> str:
    classes = {
        "Critical": "priority-critical",
        "High": "priority-high",
        "Medium": "priority-medium",
        "Low": "priority-low",
    }
    cls = classes.get(priority, "priority-low")
    return f"<span class='priority {cls}'>{escape(priority)}</span>"


def _score_class(value: float | None) -> str:
    if value is None:
        return "score-na"
    if value >= 90:
        return "score-excellent"
    if value >= 80:
        return "score-strong"
    if value >= 70:
        return "score-good"
    if value >= 60:
        return "score-needs"
    return "score-risk"


def _score_fill_color(value: float | None) -> str:
    if value is None:
        return "#b8c7d9"
    if value >= 90:
        return "#0f9d58"
    if value >= 80:
        return "#0b74de"
    if value >= 70:
        return "#2f86d4"
    if value >= 60:
        return "#d5881f"
    return "#b42318"


def _viewport_caption(path: str) -> str:
    name = Path(path).name.lower()
    if "desktop" in name:
        return "Desktop viewport: baseline hierarchy, hero clarity, and primary CTA placement."
    if "laptop" in name:
        return "Laptop viewport: layout compression and menu/CTA behavior at common breakpoint."
    if "tablet" in name:
        return "Tablet viewport: stacking order, spacing rhythm, and touch-friendly navigation."
    if "mobile" in name:
        return "Mobile viewport: fold content, tap target sizing, and text readability."
    return "Viewport capture for layout and rendering verification."


def _status_color(score: float) -> str:
    if score >= 80:
        return "#22c55e"
    if score >= 60:
        return "#f59e0b"
    return "#ef4444"


def _projected_score_series(current_score: float, issues: list[dict[str, Any]]) -> list[float]:
    counts = Counter(str(item.get("priority") or "Low").title() for item in issues)
    c = int(counts.get("Critical", 0))
    h = int(counts.get("High", 0))
    m = int(counts.get("Medium", 0))
    l = int(counts.get("Low", 0))

    after_critical = clamp(current_score + min(10.0, c * 2.6), 0.0, 100.0)
    after_high = clamp(after_critical + min(12.0, h * 1.8), 0.0, 100.0)
    after_medium = clamp(after_high + min(8.0, m * 1.2), 0.0, 100.0)
    full = clamp(after_medium + min(5.0, l * 0.5), 0.0, 100.0)
    return [round(current_score, 1), round(after_critical, 1), round(after_high, 1), round(after_medium, 1), round(full, 1)]


def _estimate_eeat_dimensions(
    scores: dict[str, float | None],
    issues: list[dict[str, Any]],
) -> dict[str, float]:
    content = float(scores.get("content") or 0.0)
    technical = float(scores.get("technical") or 0.0)
    onpage = float(scores.get("onpage") or 0.0)
    ai = float(scores.get("ai_readiness") or 0.0)

    issue_text = " ".join(
        f"{str(item.get('title') or '')} {str(item.get('detail') or '')} {str(item.get('recommendation') or '')}".lower()
        for item in issues
    )
    author_penalty = 12.0 if ("author" in issue_text or "expert" in issue_text) else 0.0
    source_penalty = 10.0 if ("citation" in issue_text or "source" in issue_text or "unsourced" in issue_text) else 0.0
    trust_penalty = 8.0 * sum(1 for i in issues if str(i.get("priority", "")).lower() == "critical")

    experience = clamp((content * 0.42) + (ai * 0.33) + (onpage * 0.25) - author_penalty, 0.0, 100.0)
    expertise = clamp((content * 0.70) + (ai * 0.30) - (author_penalty * 0.6), 0.0, 100.0)
    authority = clamp((content * 0.45) + (onpage * 0.30) + (technical * 0.25) - source_penalty, 0.0, 100.0)
    trust = clamp((technical * 0.62) + (content * 0.38) - trust_penalty, 0.0, 100.0)

    return {
        "Experience": round(experience, 1),
        "Expertise": round(expertise, 1),
        "Authoritativeness": round(authority, 1),
        "Trustworthiness": round(trust, 1),
    }


def _to_rel_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def generate_reference_charts(
    output_dir: Path,
    target_url: str,
    total_score: float,
    scores: dict[str, float | None],
    stats: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Wedge
    except Exception as exc:
        return {
            "enabled": False,
            "reason": f"matplotlib unavailable: {exc}",
            "figures": [],
        }

    def style_axes(ax: Any) -> None:
        ax.set_facecolor("#f3f4f6")
        ax.grid(color="#c5c8cf", alpha=0.35, linewidth=1)
        for spine in ax.spines.values():
            spine.set_color("#374151")
            spine.set_linewidth(1.0)
        ax.tick_params(colors="#111827")

    figures: list[dict[str, str]] = []

    # Figure 1: Health gauge
    fig, ax = plt.subplots(figsize=(6.2, 5.0), dpi=170)
    fig.patch.set_facecolor("#f3f4f6")
    ax.set_facecolor("#f3f4f6")
    score_color = _status_color(total_score)
    ax.add_patch(Wedge((0, 0), 1.0, 0, 180, width=0.30, facecolor="#d1d5db", edgecolor="none"))
    sweep = 180.0 * clamp(total_score, 0.0, 100.0) / 100.0
    ax.add_patch(Wedge((0, 0), 1.0, 180.0 - sweep, 180.0, width=0.30, facecolor=score_color, edgecolor="none"))
    ax.text(0, 1.15, "SEO Health Score", ha="center", va="bottom", fontsize=20, weight="bold", color="#1a1d37")
    ax.text(0, 0.24, f"{int(round(total_score))}", ha="center", va="center", fontsize=50, weight="bold", color="#1a1d37")
    ax.text(0, 0.07, "out of 100", ha="center", va="center", fontsize=20, color="#6b7280")
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-0.08, 1.3)
    ax.axis("off")
    chart1 = charts_dir / "figure-01-health-gauge.png"
    fig.savefig(chart1, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    figures.append(
        {
            "path": str(chart1),
            "title": "SEO Health Score",
            "caption": f"Figure 1: Overall SEO Health Score - {int(round(total_score))}/100",
        }
    )

    # Figure 2: Category breakdown
    cat_keys = ("technical", "content", "onpage", "schema", "performance", "images", "ai_readiness")
    cat_labels = [
        "Technical SEO",
        "Content Quality & E-E-A-T",
        "On-Page SEO",
        "Schema / Structured Data",
        "Performance (CWV)",
        "Images & Media",
        "AI Search Readiness",
    ]
    cat_values = [float(scores.get(k) or 0.0) for k in cat_keys]
    cat_weights = [int(round(WEIGHTS[k] * 100.0)) for k in cat_keys]
    cat_colors = [_status_color(v) for v in cat_values]

    fig, ax = plt.subplots(figsize=(11, 5.8), dpi=170)
    fig.patch.set_facecolor("#f3f4f6")
    style_axes(ax)
    y = list(range(len(cat_labels)))
    ax.barh(y, cat_values, color=cat_colors, edgecolor="#f3f4f6", height=0.62)
    ax.set_yticks(y)
    ax.set_yticklabels(cat_labels, fontsize=13)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Score", fontsize=14, color="#4b5563")
    ax.set_title("SEO Audit - Category Breakdown", fontsize=20, weight="bold", color="#1a1d37", pad=16)
    ax.axvline(60, color="#f59e0b", linestyle="--", linewidth=1.6, alpha=0.45)
    ax.axvline(80, color="#22c55e", linestyle="--", linewidth=1.6, alpha=0.45)
    ax.invert_yaxis()
    for idx, v in enumerate(cat_values):
        ax.text(min(102.0, v + 1.6), idx, f"{int(round(v))}/100  ({cat_weights[idx]}%)", va="center", fontsize=12.5, color="#1a1d37", weight="bold")
    chart2 = charts_dir / "figure-02-category-breakdown.png"
    fig.savefig(chart2, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    figures.append(
        {
            "path": str(chart2),
            "title": "Category Breakdown",
            "caption": "Figure 2: Score breakdown by category with weight percentages",
        }
    )

    # Figure 3: Issues by severity
    sev_labels = ["Low", "Medium", "High", "Critical"]
    sev_colors = ["#3b95cb", "#f1c40f", "#e67e22", "#e74c3c"]
    sev_counts_map = Counter(str(item.get("priority") or "Low").title() for item in issues)
    sev_counts = [int(sev_counts_map.get(lbl, 0)) for lbl in sev_labels]

    fig, ax = plt.subplots(figsize=(6.2, 6.2), dpi=170)
    fig.patch.set_facecolor("#f3f4f6")
    ax.set_facecolor("#f3f4f6")
    if sum(sev_counts) == 0:
        ax.text(0.5, 0.5, "No issues detected", ha="center", va="center", fontsize=16, color="#4b5563")
        ax.axis("off")
    else:
        label_text = [f"{c} issues\n{lbl}" for lbl, c in zip(sev_labels, sev_counts)]
        ax.pie(
            sev_counts,
            labels=label_text,
            autopct=lambda p: f"{int(round(p))}%",
            colors=sev_colors,
            startangle=90,
            counterclock=False,
            wedgeprops={"edgecolor": "#f3f4f6", "linewidth": 2},
            textprops={"fontsize": 11.5, "color": "#374151"},
        )
    ax.set_title("Issues by Severity", fontsize=20, weight="bold", color="#1a1d37", pad=14)
    chart3 = charts_dir / "figure-03-issues-severity.png"
    fig.savefig(chart3, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    figures.append(
        {
            "path": str(chart3),
            "title": "Issues by Severity",
            "caption": "Figure 3: Distribution of issues by severity tier",
        }
    )

    # Figure 4: Weighted contribution
    weighted = [round((float(scores.get(k) or 0.0) * WEIGHTS[k]), 2) for k in cat_keys]
    short_labels = [
        "Technical\n(25%)",
        "Content\n(25%)",
        "On-Page\n(20%)",
        "Schema\n(10%)",
        "Performance\n(10%)",
        "Images\n(5%)",
        "AI Search\n(5%)",
    ]
    fig, ax = plt.subplots(figsize=(11, 5.8), dpi=170)
    fig.patch.set_facecolor("#f3f4f6")
    style_axes(ax)
    bars = ax.bar(short_labels, weighted, color=["#3b95cb", "#9b59b6", "#1abc9c", "#e67e22", "#e74c3c", "#f1c40f", "#95a5a6"], edgecolor="#f3f4f6", width=0.66)
    ax.set_ylabel("Weighted Points", fontsize=16, color="#4b5563")
    ax.set_title(f"Weighted Score Contribution (Total: {round(sum(weighted), 1)}/100)", fontsize=20, weight="bold", color="#1a1d37", pad=14)
    ax.set_ylim(0, max(25.0, max(weighted) + 4))
    ax.tick_params(axis="x", labelsize=12)
    for b, val in zip(bars, weighted):
        ax.text(b.get_x() + b.get_width() / 2.0, b.get_height() + 0.45, f"{val:.1f}", ha="center", va="bottom", fontsize=16, color="#1a1d37", weight="bold")
    chart4 = charts_dir / "figure-04-weighted-contribution.png"
    fig.savefig(chart4, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    figures.append(
        {
            "path": str(chart4),
            "title": "Weighted Score Contribution",
            "caption": "Figure 4: Weighted point contribution by category",
        }
    )

    # Figure 5: Technical signals
    pages_html = int(stats.get("pages_html") or 0)
    missing_canonical = int(stats.get("missing_canonical") or 0)
    canonical_score = 100.0 * ((pages_html - missing_canonical) / max(pages_html, 1))
    headers_present = len(((stats.get("security_headers") or {}).get("present") or []))
    security_score = 100.0 * (headers_present / max(len(SECURITY_HEADERS), 1))
    sitemap_score = 100.0 if bool(stats.get("sitemap_ok")) else 40.0
    median_ttfb = float(stats.get("median_response_ms") or 0.0)
    ttfb_score = clamp(100.0 - max(0.0, median_ttfb - 180.0) / 5.0, 0.0, 100.0)
    cache_issue = any("cache" in f"{str(i.get('title') or '')} {str(i.get('detail') or '')}".lower() for i in issues)
    cache_score = 15.0 if cache_issue else 100.0
    http2_score = 100.0 if int(stats.get("pages_successful") or 0) > 0 else 0.0
    https_score = 100.0 if target_url.startswith("https://") else 40.0

    tech_labels = ["TTFB", "HTTP/2", "HTTPS Redirect", "Security Headers", "Caching", "Canonical Tags", "Sitemap Coverage"]
    tech_values = [ttfb_score, http2_score, https_score, security_score, cache_score, canonical_score, sitemap_score]
    tech_colors = [_status_color(v) for v in tech_values]

    fig, ax = plt.subplots(figsize=(10.6, 5.8), dpi=170)
    fig.patch.set_facecolor("#f3f4f6")
    style_axes(ax)
    y = list(range(len(tech_labels)))
    ax.barh(y, tech_values, color=tech_colors, edgecolor="#f3f4f6", height=0.56)
    ax.set_yticks(y)
    ax.set_yticklabels(tech_labels, fontsize=13)
    ax.set_xlim(0, 115)
    ax.set_xlabel("Score", fontsize=14, color="#4b5563")
    ax.set_title("Technical SEO Signals", fontsize=20, weight="bold", color="#1a1d37", pad=14)
    for idx, val in enumerate(tech_values):
        status = "PASS" if val >= 80 else ("WARN" if val >= 60 else "FAIL")
        ax.text(min(111.5, val + 1.8), idx, status, va="center", fontsize=14, color=tech_colors[idx], weight="bold")
    chart5 = charts_dir / "figure-05-technical-signals.png"
    fig.savefig(chart5, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    figures.append(
        {
            "path": str(chart5),
            "title": "Technical SEO Signals",
            "caption": "Figure 5: Technical pass/warn/fail signal profile",
        }
    )

    # Figure 6: E-E-A-T radar
    eeat = _estimate_eeat_dimensions(scores, issues)
    dims = list(eeat.keys())
    vals = [float(eeat[k]) for k in dims]
    theta = [(2.0 * math.pi * i / len(dims)) for i in range(len(dims))]
    theta += theta[:1]
    vals_closed = vals + vals[:1]
    target = [80.0] * (len(dims) + 1)

    fig = plt.figure(figsize=(6.1, 6.1), dpi=170)
    fig.patch.set_facecolor("#f3f4f6")
    ax = fig.add_subplot(111, polar=True)
    ax.set_facecolor("#f3f4f6")
    ax.set_theta_offset(math.pi / 2.0)
    ax.set_theta_direction(-1)
    ax.set_xticks(theta[:-1])
    ax.set_xticklabels(dims, fontsize=12, fontweight="bold", color="#111827")
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], color="#6b7280")
    ax.grid(color="#c5c8cf", alpha=0.35, linewidth=1)
    ax.plot(theta, target, linestyle="--", color="#7bd9a8", linewidth=2.0, label="Target (80)")
    ax.plot(theta, vals_closed, color="#e84a67", linewidth=2.4, marker="o")
    ax.fill(theta, vals_closed, color="#e84a67", alpha=0.24)
    for ang, v in zip(theta[:-1], vals):
        ax.text(ang, min(100, v + 6), f"{int(round(v))}", color="#e84a67", fontsize=16, weight="bold", ha="center", va="center")
    ax.set_title("E-E-A-T Assessment", fontsize=20, weight="bold", color="#1a1d37", pad=18)
    ax.legend(loc="lower right", frameon=True, facecolor="#f3f4f6", edgecolor="#d1d5db")
    chart6 = charts_dir / "figure-06-eeat-radar.png"
    fig.savefig(chart6, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    figures.append(
        {
            "path": str(chart6),
            "title": "E-E-A-T Assessment",
            "caption": "Figure 6: E-E-A-T dimension assessment vs target score of 80",
        }
    )

    # Figure 7: projected score improvement
    projected = _projected_score_series(total_score, issues)
    phases = ["Current", "After Critical\nFixes", "After High\nFixes", "After Medium\nFixes", "Full\nOptimization"]
    phase_colors = ["#f59e0b", "#f59e0b", "#22c55e", "#22c55e", "#22c55e"]

    fig, ax = plt.subplots(figsize=(10.8, 5.6), dpi=170)
    fig.patch.set_facecolor("#f3f4f6")
    style_axes(ax)
    bars = ax.bar(phases, projected, color=phase_colors, edgecolor="#f3f4f6", width=0.6)
    ax.set_ylim(0, 105)
    ax.set_ylabel("SEO Health Score", fontsize=16, color="#4b5563")
    ax.set_title("Projected Score Improvement", fontsize=20, weight="bold", color="#1a1d37", pad=12)
    ax.axhline(80, color="#7bd9a8", linestyle="--", linewidth=1.8)
    ax.text(len(phases) - 0.6, 80.5, "Good", color="#5cbf88", fontsize=13)
    ax.tick_params(axis="x", labelsize=12)
    for bar, value in zip(bars, projected):
        ax.text(bar.get_x() + bar.get_width() / 2.0, value + 1.3, f"{int(round(value))}", ha="center", va="bottom", fontsize=16, weight="bold", color="#1a1d37")
    chart7 = charts_dir / "figure-07-projected-score.png"
    fig.savefig(chart7, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    figures.append(
        {
            "path": str(chart7),
            "title": "Projected Score Improvement",
            "caption": "Figure 7: Projected SEO Health Score improvement after each fix phase",
        }
    )

    rel_figures = [
        {
            "path": _to_rel_path(Path(item["path"]), output_dir),
            "title": item["title"],
            "caption": item["caption"],
        }
        for item in figures
    ]
    return {
        "enabled": True,
        "reason": "",
        "figures": rel_figures,
        "charts_dir": str(charts_dir),
    }


def _collect_relative_screenshots(visual: dict[str, Any], output_dir: Path) -> list[str]:
    rel_paths: list[str] = []
    for shot in visual.get("screenshots", []):
        try:
            rel = Path(shot).resolve().relative_to(output_dir.resolve()).as_posix()
        except Exception:
            rel = str(shot).replace("\\", "/")
        rel_paths.append(rel)
    return rel_paths


def _collect_relative_sections(visual: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    rel_sections: list[dict[str, Any]] = []
    for item in visual.get("sections", []):
        raw_shot = item.get("screenshot")
        rel_shot: str | None = None
        if raw_shot:
            try:
                rel_shot = Path(raw_shot).resolve().relative_to(output_dir.resolve()).as_posix()
            except Exception:
                rel_shot = str(raw_shot).replace("\\", "/")
        rel_sections.append(
            {
                "label": str(item.get("label") or "Section"),
                "snippet": str(item.get("snippet") or ""),
                "observation": str(item.get("observation") or ""),
                "top_px": item.get("top_px"),
                "height_px": item.get("height_px"),
                "word_count": int(item.get("word_count") or 0),
                "cta_count": int(item.get("cta_count") or 0),
                "form_count": int(item.get("form_count") or 0),
                "link_count": int(item.get("link_count") or 0),
                "semantic_type": str(item.get("semantic_type") or ""),
                "capture_reason": str(item.get("capture_reason") or ""),
                "screenshot": rel_shot,
                "ocr_status": str(item.get("ocr_status") or ""),
                "ocr_reason": str(item.get("ocr_reason") or ""),
                "ocr_excerpt": str(item.get("ocr_excerpt") or ""),
                "ocr_line_count": int(item.get("ocr_line_count") or 0),
                "ocr_avg_confidence": item.get("ocr_avg_confidence"),
            }
        )
    return rel_sections


def build_html_report(
    target_url: str,
    generated_at: str,
    total_score: float,
    grade: str,
    band: str,
    business_label: str,
    business_confidence: float,
    scores: dict[str, float | None],
    stats: dict[str, Any],
    issues: list[dict[str, Any]],
    quick_wins: list[dict[str, Any]],
    visual: dict[str, Any],
    screenshot_paths: list[str],
    section_insights: list[dict[str, Any]],
    chart_figures: list[dict[str, str]] | None = None,
    orchestration: dict[str, Any] | None = None,
) -> str:
    gauge_degrees = round(max(0.0, min(100.0, total_score)) * 3.6, 1)
    score_cards: list[str] = []
    for key in ("technical", "content", "onpage", "schema", "performance", "images", "ai_readiness"):
        value = scores.get(key)
        label = SCORE_LABELS[key]
        pct = max(0.0, min(100.0, float(value))) if value is not None else 0.0
        fill = _score_fill_color(value)
        score_cards.append(
            f"""
            <div class="score-card">
              <div class="score-row">
                <span>{escape(label)}</span>
                <span class="{_score_class(value)}">{'Not Measured' if value is None else escape(_fmt_number(value, 1))}</span>
              </div>
              <div class="score-bar"><span style="width:{pct:.1f}%;background:{fill};"></span></div>
            </div>
            """
        )

    score_chart_rows: list[str] = []
    for key in ("technical", "content", "onpage", "schema", "performance", "images", "ai_readiness"):
        value = scores.get(key)
        if value is None:
            continue
        label = SCORE_LABELS[key]
        pct = max(3.0, min(100.0, float(value)))
        fill = _score_fill_color(value)
        score_chart_rows.append(
            f"""
            <div class="chart-row">
              <span>{escape(label)}</span>
              <div class="chart-bar"><i style="width:{pct:.1f}%;background:{fill};"></i></div>
              <strong>{escape(_fmt_number(value, 1))}</strong>
            </div>
            """
        )
    score_chart_html = "\n".join(score_chart_rows) if score_chart_rows else "<div class='empty'>No score data available.</div>"

    issue_counts = {
        "Critical": sum(1 for i in issues if str(i.get("priority") or "").lower() == "critical"),
        "High": sum(1 for i in issues if str(i.get("priority") or "").lower() == "high"),
        "Medium": sum(1 for i in issues if str(i.get("priority") or "").lower() == "medium"),
        "Low": sum(1 for i in issues if str(i.get("priority") or "").lower() == "low"),
    }
    issue_total = sum(issue_counts.values())
    if issue_total > 0:
        critical_deg = 360.0 * (issue_counts["Critical"] / issue_total)
        high_deg = critical_deg + 360.0 * (issue_counts["High"] / issue_total)
        medium_deg = high_deg + 360.0 * (issue_counts["Medium"] / issue_total)
        issue_donut_style = (
            "conic-gradient("
            f"#b42318 0deg {critical_deg:.2f}deg,"
            f"#d5881f {critical_deg:.2f}deg {high_deg:.2f}deg,"
            f"#0b74de {high_deg:.2f}deg {medium_deg:.2f}deg,"
            f"#0f9d58 {medium_deg:.2f}deg 360deg)"
        )
    else:
        issue_donut_style = "conic-gradient(#d7e3f0 0deg 360deg)"
    issue_legend_html = "".join(
        f"<div class='legend-item'><span class='swatch swatch-{name.lower()}'></span>{name}: <strong>{count}</strong></div>"
        for name, count in issue_counts.items()
    )

    stats_grid = [
        ("Pages crawled", _fmt_number(stats.get("pages_total"), 0)),
        ("HTML pages", _fmt_number(stats.get("pages_html"), 0)),
        ("Fetch errors", _fmt_number(stats.get("fetch_errors"), 0)),
        ("HTTP errors", _fmt_number(stats.get("error_pages"), 0)),
        ("Thin pages", _fmt_number(stats.get("thin_pages"), 0)),
        ("Missing titles", _fmt_number(stats.get("missing_title"), 0)),
        ("Missing meta", _fmt_number(stats.get("missing_meta"), 0)),
        ("Schema pages", _fmt_number(stats.get("schema_pages"), 0)),
        ("Images missing alt", f"{_fmt_number(stats.get('missing_alt'), 0)}/{_fmt_number(stats.get('total_images'), 0)}"),
        ("Median response (ms)", _fmt_number(stats.get("median_response_ms"), 1)),
        ("p90 response (ms)", _fmt_number(stats.get("p90_response_ms"), 1)),
        ("Security headers", f"{len((stats.get('security_headers') or {}).get('present', []))}/{len(SECURITY_HEADERS)}"),
    ]
    cwv = stats.get("cwv", {}) or {}
    if isinstance(cwv, dict):
        mobile = cwv.get("mobile", {}) or {}
        stats_grid.extend(
            [
                ("Perf source", str(stats.get("performance_source", "proxy"))),
                ("CWV status", str(cwv.get("status", "n/a"))),
                ("CWV composite", _fmt_number(cwv.get("composite_score"), 1)),
                ("Field LCP p75 (ms)", _fmt_number(mobile.get("field_lcp_ms"), 1)),
                ("Field INP p75 (ms)", _fmt_number(mobile.get("field_inp_ms"), 1)),
                ("Field CLS p75", _fmt_number(mobile.get("field_cls"), 3)),
                ("Lab perf score", _fmt_number(cwv.get("lab_score"), 1)),
            ]
        )
    stats_cards = "\n".join(
        f"<div class='stat'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>" for label, value in stats_grid
    )

    if issues:
        issue_rows = "\n".join(
            f"""
            <tr>
              <td>{_priority_badge(item.get('priority', 'Low'))}</td>
              <td>{escape(item.get('category', 'General'))}</td>
              <td><strong>{escape(item.get('title', 'Untitled issue'))}</strong><div class='muted'>{escape(item.get('detail', ''))}</div></td>
              <td>{escape(item.get('recommendation', ''))}</td>
              <td>{escape(item.get('effort', 'n/a'))} / {escape(item.get('expected_lift', 'n/a'))}</td>
            </tr>
            """
            for item in issues
        )
    else:
        issue_rows = "<tr><td colspan='5'>No issues detected in sampled crawl.</td></tr>"

    if quick_wins:
        quick_win_items = "\n".join(
            f"<li><strong>{escape(item['title'])}</strong>: {escape(item.get('recommendation', item['detail']))}</li>"
            for item in quick_wins
        )
    else:
        quick_win_items = "<li>No quick wins detected in this sample.</li>"

    evidence = stats.get("example_urls", {})

    def render_evidence(label: str, key: str) -> str:
        urls = evidence.get(key) or []
        if not urls:
            return f"<li><strong>{escape(label)}:</strong> None</li>"
        short = "".join(f"<li><code>{escape(url)}</code></li>" for url in urls[:8])
        return f"<li><strong>{escape(label)}:</strong><ul>{short}</ul></li>"

    evidence_html = "\n".join(
        [
            render_evidence("Missing title examples", "missing_title"),
            render_evidence("Missing meta examples", "missing_meta"),
            render_evidence("Thin content examples", "thin_content"),
            render_evidence("Noindex examples", "noindex"),
            render_evidence("Missing schema examples", "missing_schema"),
            render_evidence("Missing alt examples", "alt_missing"),
        ]
    )

    visual_checks = [
        ("Visual status", str(visual.get("status", "skipped")).title()),
        ("OCR status", str(visual.get("ocr_status", "not_run")).title()),
        (
            "OCR sections with text",
            f"{_fmt_number(visual.get('ocr_sections_with_text'), 0)}/{_fmt_number(visual.get('ocr_sections_total'), 0)}",
        ),
        ("OCR avg confidence", _fmt_number(visual.get("ocr_avg_confidence"), 3)),
        ("H1 above fold", _bool_label(visual.get("h1_visible_above_fold"))),
        ("CTA above fold", _bool_label(visual.get("cta_visible_above_fold"))),
        ("Viewport meta", _bool_label(visual.get("viewport_meta_present"))),
        ("Horizontal mobile scroll", _bool_label(visual.get("horizontal_scroll_mobile"))),
        ("Mobile nav accessible", _bool_label(visual.get("mobile_nav_accessible"))),
        (
            "Touch targets <48px",
            f"{_fmt_number(visual.get('mobile_touch_targets_small'), 0)}/{_fmt_number(visual.get('mobile_touch_targets_total'), 0)}",
        ),
        ("Min mobile font (px)", _fmt_number(visual.get("mobile_min_font_px"), 1)),
        ("Text readability (>=16px)", _bool_label(visual.get("mobile_text_readability_ok"))),
        ("Desktop overlap flags", _fmt_number(visual.get("desktop_overlap_issues"), 0)),
        ("Desktop overflow flags", _fmt_number(visual.get("desktop_overflow_issues"), 0)),
    ]
    if visual.get("ocr_reason"):
        visual_checks.append(("OCR note", str(visual["ocr_reason"])))
    if visual.get("reason"):
        visual_checks.append(("Visual note", str(visual["reason"])))
    visual_chips = "\n".join(
        f"<div class='chip'><span>{escape(k)}</span><strong>{escape(v)}</strong></div>" for k, v in visual_checks
    )
    screenshots_html = "\n".join(
        f"<figure><img src='{escape(path)}' alt='Audit screenshot'><figcaption><strong>{escape(Path(path).name)}</strong><br>{escape(_viewport_caption(path))}</figcaption></figure>"
        for path in screenshot_paths
    )
    if not screenshots_html:
        screenshots_html = "<div class='empty'>No screenshots captured in this run.</div>"

    chart_figure_html = "<div class='empty'>Chart rendering unavailable in this run.</div>"
    if chart_figures:
        chart_figure_html = "\n".join(
            f"""
            <figure class="chart-figure">
              <img src="{escape(item.get('path', ''))}" alt="{escape(item.get('title', 'Audit chart'))}">
              <figcaption><strong>{escape(item.get('title', 'Chart'))}</strong><br>{escape(item.get('caption', ''))}</figcaption>
            </figure>
            """
            for item in chart_figures
        )

    orchestration_html = "<div class='empty'>Specialist orchestration disabled for this run.</div>"
    if orchestration and orchestration.get("enabled"):
        track_rows = []
        for track in orchestration.get("tracks", []):
            status = str(track.get("status", "failed"))
            status_cls = "status-ok" if status == "ok" else "status-failed"
            metrics = track.get("summary_metrics") or {}
            metrics_text = ", ".join(f"{k}={v}" for k, v in metrics.items()) if metrics else "n/a"
            report_link = ""
            primary_report = str(track.get("primary_report") or "")
            if primary_report:
                report_link = f"{escape(track.get('name', 'track'))}/{escape(primary_report)}"
            stderr_tail = str(track.get("stderr_tail") or "")
            error_hint = escape(stderr_tail.splitlines()[-1]) if stderr_tail else ""
            track_rows.append(
                f"""
                <tr>
                  <td>{escape(str(track.get("name", "")))}</td>
                  <td><span class="track-status {status_cls}">{escape(status)}</span></td>
                  <td>{escape(_fmt_number(track.get("duration_sec"), 2))}s</td>
                  <td>{escape(metrics_text)}</td>
                  <td>{escape(report_link) if report_link else "n/a"}</td>
                  <td>{error_hint or "n/a"}</td>
                </tr>
                """
            )
        orchestration_html = f"""
        <div class="orchestration-meta">
          <div><strong>Tracks:</strong> {orchestration.get("success_count", 0)}/{orchestration.get("total_tracks", 0)} succeeded</div>
          <div><strong>Summary file:</strong> <code>ORCHESTRATION-SUMMARY.json</code></div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Track</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Summary Metrics</th>
              <th>Primary Report</th>
              <th>Failure Hint</th>
            </tr>
          </thead>
          <tbody>
            {"".join(track_rows)}
          </tbody>
        </table>
        """

    if section_insights:
        section_cards = []
        for sec in section_insights:
            label = escape(sec["label"])
            snippet = escape(sec["snippet"] or "No text snippet captured.")
            observation = escape(sec["observation"] or "No observation generated.")
            top_px = escape(_fmt_number(sec.get("top_px"), 1))
            height_px = escape(_fmt_number(sec.get("height_px"), 1))
            word_count = escape(_fmt_number(sec.get("word_count"), 0))
            cta_count = escape(_fmt_number(sec.get("cta_count"), 0))
            form_count = escape(_fmt_number(sec.get("form_count"), 0))
            link_count = escape(_fmt_number(sec.get("link_count"), 0))
            ocr_excerpt = escape(sec.get("ocr_excerpt") or "")
            ocr_conf = escape(_fmt_number(sec.get("ocr_avg_confidence"), 3))
            ocr_lines = escape(_fmt_number(sec.get("ocr_line_count"), 0))
            ocr_status = escape(sec.get("ocr_status") or "n/a")
            semantic_type = escape(sec.get("semantic_type") or "content")
            capture_reason = escape(sec.get("capture_reason") or "Representative section selected for layout QA.")
            shot = sec.get("screenshot")
            if shot:
                shot_html = f"<img src='{escape(shot)}' alt='Section snapshot'>"
            else:
                shot_html = "<div class='section-empty'>No section screenshot</div>"
            section_cards.append(
                f"""
                <article class="section-card">
                  <div class="section-shot">{shot_html}</div>
                  <div class="section-body">
                    <h3>{label}</h3>
                    <p class="section-snippet">{snippet}</p>
                    <p class="section-rationale"><strong>Why captured:</strong> {capture_reason}</p>
                    <p class="section-observation"><strong>Finding:</strong> {observation}</p>
                    <p class="section-ocr"><strong>OCR ({ocr_status})</strong>: {ocr_excerpt or 'No OCR text captured.'}</p>
                    <div class="section-metrics">
                      <span>Type: {semantic_type}</span>
                      <span>Top: {top_px}px</span>
                      <span>Height: {height_px}px</span>
                      <span>Words: {word_count}</span>
                      <span>CTA: {cta_count}</span>
                      <span>Forms: {form_count}</span>
                      <span>Links: {link_count}</span>
                      <span>OCR lines: {ocr_lines}</span>
                      <span>OCR conf: {ocr_conf}</span>
                    </div>
                  </div>
                </article>
                """
            )
        section_intelligence_html = "\n".join(section_cards)
    else:
        section_intelligence_html = "<div class='empty'>No section-level insights captured.</div>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SEO Audit Report - {escape(target_url)}</title>
  <style>
    :root {{
      --bg: #f2f6fc;
      --panel: #ffffff;
      --line: #d8e2ef;
      --text: #0f172a;
      --muted: #4b6078;
      --accent: #0b74de;
      --accent-soft: #eaf3ff;
      --good: #0f9d58;
      --warn: #b9750a;
      --danger: #b42318;
    }}
    * {{
      box-sizing: border-box;
      min-width: 0;
    }}
    body {{
      margin: 0;
      font-family: "Inter", "Segoe UI", Arial, sans-serif;
      background: linear-gradient(180deg, #f6f9fc 0%, #edf3fb 100%);
      color: var(--text);
      line-height: 1.45;
      overflow-x: hidden;
    }}
    .page {{
      width: min(1120px, calc(100vw - 28px));
      margin: 16px auto 32px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 18px;
      margin-top: 12px;
      box-shadow: 0 5px 18px rgba(15, 23, 42, 0.07);
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.45fr 1fr;
      gap: 14px;
      align-items: stretch;
    }}
    .title {{
      font-size: 36px;
      font-weight: 800;
      letter-spacing: 0.2px;
      color: #0f2747;
    }}
    .subtitle {{
      color: var(--muted);
      margin-top: 6px;
      font-size: 14px;
    }}
    .kpis {{
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .kpi {{
      border: 1px solid #d3deec;
      border-radius: 10px;
      background: var(--accent-soft);
      padding: 8px 10px;
      font-size: 13px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }}
    .kpi span {{
      color: #355270;
    }}
    .gauge-wrap {{
      display: flex;
      justify-content: center;
      align-items: center;
    }}
    .gauge {{
      width: 196px;
      height: 196px;
      border-radius: 50%;
      background: conic-gradient(var(--accent) {gauge_degrees}deg, #d6e4f4 0deg);
      position: relative;
      border: 1px solid #c6d6ea;
    }}
    .gauge::after {{
      content: "";
      position: absolute;
      inset: 18px;
      border-radius: 50%;
      background: #fff;
      border: 1px solid #cfe0f2;
    }}
    .gauge-inner {{
      position: absolute;
      inset: 0;
      z-index: 2;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 8px;
    }}
    .gauge-score {{
      font-size: 42px;
      font-weight: 800;
      color: #0f9d58;
      line-height: 1;
    }}
    .gauge-meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    .section-title {{
      font-size: 21px;
      font-weight: 750;
      margin: 0 0 12px;
      color: #0d508f;
      border-bottom: 1px solid #d8e2ef;
      padding-bottom: 8px;
    }}
    .scores {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .score-card {{
      border: 1px solid #d4dfec;
      border-radius: 10px;
      background: #f9fbff;
      padding: 10px;
    }}
    .score-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
      margin-bottom: 7px;
    }}
    .score-bar {{
      height: 9px;
      border-radius: 99px;
      background: #e1ebf8;
      overflow: hidden;
    }}
    .score-bar span {{
      display: block;
      height: 100%;
      background: linear-gradient(90deg, #0b74de, #33a0ff);
    }}
    .score-excellent {{
      color: var(--good);
      font-weight: 700;
    }}
    .score-strong {{
      color: #0c62be;
      font-weight: 700;
    }}
    .score-good {{
      color: #2368a2;
      font-weight: 700;
    }}
    .score-needs {{
      color: var(--warn);
      font-weight: 700;
    }}
    .score-risk {{
      color: var(--danger);
      font-weight: 700;
    }}
    .score-na {{
      color: var(--muted);
      font-style: italic;
    }}
    .viz-grid {{
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 12px;
    }}
    .viz-card {{
      border: 1px solid #d4dfec;
      border-radius: 10px;
      background: #f9fbff;
      padding: 10px;
    }}
    .viz-card h3 {{
      margin: 0 0 10px;
      font-size: 15px;
      color: #104782;
    }}
    .chart-stack {{
      display: grid;
      gap: 8px;
    }}
    .chart-row {{
      display: grid;
      grid-template-columns: 150px 1fr 42px;
      gap: 8px;
      align-items: center;
      font-size: 12px;
      color: #1e334b;
    }}
    .chart-row strong {{
      text-align: right;
      color: #0e3158;
    }}
    .chart-bar {{
      height: 10px;
      border-radius: 999px;
      background: #dfebf8;
      overflow: hidden;
      border: 1px solid #d2dfef;
    }}
    .chart-bar i {{
      display: block;
      height: 100%;
      border-radius: 999px;
    }}
    .donut-wrap {{
      display: flex;
      justify-content: center;
      margin-top: 2px;
      margin-bottom: 10px;
    }}
    .donut {{
      width: 180px;
      height: 180px;
      border-radius: 50%;
      position: relative;
      border: 1px solid #d0deee;
    }}
    .donut::after {{
      content: "";
      position: absolute;
      inset: 30px;
      background: #fff;
      border-radius: 50%;
      border: 1px solid #d6e2ef;
    }}
    .donut-inner {{
      position: absolute;
      inset: 0;
      z-index: 2;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      color: #163a63;
      text-align: center;
    }}
    .donut-inner strong {{
      font-size: 34px;
      line-height: 1;
    }}
    .donut-inner span {{
      margin-top: 4px;
      font-size: 12px;
      color: #526982;
    }}
    .legend {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      font-size: 12px;
      color: #2a3f57;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 6px;
      background: #fff;
      border: 1px solid #d7e2ef;
      border-radius: 999px;
      padding: 4px 8px;
    }}
    .swatch {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      flex: 0 0 10px;
    }}
    .swatch-critical {{ background: #b42318; }}
    .swatch-high {{ background: #d5881f; }}
    .swatch-medium {{ background: #0b74de; }}
    .swatch-low {{ background: #0f9d58; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .stat {{
      border: 1px solid #d4dfec;
      border-radius: 8px;
      background: #f9fbff;
      padding: 8px 9px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
    }}
    .stat span {{
      color: #4e6480;
    }}
    .priority {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }}
    .priority-critical {{
      background: #fef1f2;
      border: 1px solid #f7c7cc;
      color: #b42318;
    }}
    .priority-high {{
      background: #fff5e8;
      border: 1px solid #f3cf9f;
      color: #9f580a;
    }}
    .priority-medium {{
      background: #edf6ff;
      border: 1px solid #bfdaf7;
      color: #1e64a8;
    }}
    .priority-low {{
      background: #ebf9ef;
      border: 1px solid #b9e5c6;
      color: #0f763f;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 12px;
    }}
    th, td {{
      border: 1px solid #d5dfec;
      vertical-align: top;
      padding: 8px;
      white-space: normal;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    th {{
      text-align: left;
      color: #17324d;
      background: #f2f7fd;
      font-size: 12px;
    }}
    .muted {{
      color: var(--muted);
      margin-top: 4px;
    }}
    .cols {{
      display: grid;
      grid-template-columns: 1.15fr 1fr;
      gap: 12px;
    }}
    ul {{
      margin: 8px 0 0 18px;
      padding: 0;
    }}
    li {{
      margin-bottom: 6px;
    }}
    code {{
      background: #f3f8ff;
      border: 1px solid #cfe0f3;
      border-radius: 6px;
      padding: 2px 6px;
      color: #0c4f92;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .chip {{
      border: 1px solid #d2deec;
      border-radius: 999px;
      padding: 6px 10px;
      display: flex;
      gap: 8px;
      align-items: center;
      background: #f7faff;
      font-size: 12px;
    }}
    .chip span {{
      color: #536b87;
    }}
    .shots {{
      margin-top: 10px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      align-items: start;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      margin-top: 6px;
    }}
    .chart-figure {{
      background: #f3f4f6;
    }}
    .chart-figure img {{
      width: 100%;
      max-height: none;
      object-fit: contain;
      background: #f3f4f6;
    }}
    figure {{
      margin: 0;
      border: 1px solid #d2deec;
      border-radius: 10px;
      overflow: hidden;
      background: #fff;
      break-inside: avoid;
    }}
    img {{
      width: 100%;
      max-width: 100%;
      height: auto;
      display: block;
    }}
    .shots img {{
      max-height: 360px;
      object-fit: cover;
      object-position: top;
    }}
    figcaption {{
      padding: 7px 9px;
      font-size: 11px;
      color: #4c627b;
      border-top: 1px solid #d2deec;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .empty {{
      border: 1px dashed #b9cae0;
      border-radius: 10px;
      color: #4c627b;
      text-align: center;
      padding: 20px;
      background: #f8fbff;
    }}
    .section-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .section-card {{
      border: 1px solid #d2deec;
      border-radius: 10px;
      overflow: hidden;
      background: #fff;
      break-inside: avoid;
    }}
    .section-shot {{
      border-bottom: 1px solid #d2deec;
      background: #f8fbff;
      min-height: 120px;
    }}
    .section-shot img {{
      width: 100%;
      display: block;
      max-height: 240px;
      object-fit: cover;
      object-position: top;
    }}
    .section-empty {{
      color: #4c627b;
      text-align: center;
      font-size: 12px;
      padding: 18px;
    }}
    .section-body {{
      padding: 10px;
    }}
    .section-body h3 {{
      margin: 0 0 6px;
      color: #104782;
      font-size: 16px;
    }}
    .section-snippet {{
      margin: 0;
      font-size: 12px;
      color: #1f3147;
    }}
    .section-observation {{
      margin: 8px 0 0;
      font-size: 12px;
      color: #215f93;
    }}
    .section-rationale {{
      margin: 8px 0 0;
      font-size: 12px;
      color: #214566;
    }}
    .section-ocr {{
      margin: 8px 0 0;
      font-size: 12px;
      color: #176089;
    }}
    .section-metrics {{
      margin-top: 8px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .section-metrics span {{
      border: 1px solid #ccddef;
      border-radius: 999px;
      padding: 2px 7px;
      font-size: 11px;
      color: #4b6078;
      background: #f6faff;
    }}
    .orchestration-meta {{
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--muted);
    }}
    .track-status {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      border: 1px solid #cedff1;
    }}
    .status-ok {{
      background: #ebf9ef;
      color: #0f763f;
      border-color: #b9e5c6;
    }}
    .status-failed {{
      background: #fef1f2;
      color: #b42318;
      border-color: #f7c7cc;
    }}
    .foot {{
      margin-top: 12px;
      color: #4c627b;
      font-size: 11px;
      text-align: right;
    }}
    @media (max-width: 980px) {{
      .hero,
      .scores,
      .viz-grid,
      .stats,
      .cols,
      .chart-grid,
      .shots,
      .section-grid {{
        grid-template-columns: 1fr;
      }}
      .gauge-wrap {{
        justify-content: flex-start;
      }}
    }}
    @media print {{
      @page {{
        size: A4;
        margin: 10mm;
      }}
      body {{
        margin: 0;
        background: #fff;
        color: var(--text);
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .page {{
        width: 100%;
        margin: 0;
      }}
      .panel {{
        box-shadow: none;
        margin-top: 8px;
        border-color: #d3deec;
        break-inside: auto;
      }}
      .hero,
      .scores,
      .viz-grid,
      .stats,
      .cols,
      .chart-grid,
      .shots,
      .section-grid {{
        grid-template-columns: 1fr;
      }}
      .chart-row {{
        grid-template-columns: 140px 1fr 38px;
      }}
      figure,
      .section-card,
      table,
      .chip,
      .kpi,
      .score-card,
      .stat {{
        break-inside: avoid-page;
      }}
      th {{
        background: #edf4fc;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="panel hero">
      <div>
        <div class="title">Codex SEO Audit Dossier</div>
        <div class="subtitle">Target: {escape(target_url)}</div>
        <div class="subtitle">Generated: {escape(generated_at)}</div>
        <div class="subtitle">Business Type: {escape(business_label)} ({business_confidence:.1f}% confidence)</div>
        <div class="kpis">
          <div class="kpi"><span>Pages Crawled</span><strong>{escape(_fmt_number(stats.get("pages_total"), 0))}</strong></div>
          <div class="kpi"><span>HTML Pages</span><strong>{escape(_fmt_number(stats.get("pages_html"), 0))}</strong></div>
          <div class="kpi"><span>Critical Issues</span><strong>{sum(1 for i in issues if i.get("priority") == "Critical")}</strong></div>
          <div class="kpi"><span>High Issues</span><strong>{sum(1 for i in issues if i.get("priority") == "High")}</strong></div>
        </div>
      </div>
      <div class="gauge-wrap">
        <div class="gauge">
          <div class="gauge-inner">
            <div class="gauge-score">{_fmt_number(total_score, 1)}</div>
            <div class="gauge-meta">Grade {escape(grade)} - {escape(band)}</div>
            <div class="gauge-meta">SEO Health</div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <h2 class="section-title">Category Scores</h2>
      <div class="scores">
        {"".join(score_cards)}
      </div>
    </section>

    <section class="panel">
      <h2 class="section-title">Visual Scorecards</h2>
      <div class="viz-grid">
        <article class="viz-card">
          <h3>Category Distribution</h3>
          <div class="chart-stack">{score_chart_html}</div>
        </article>
        <article class="viz-card">
          <h3>Issue Severity Mix</h3>
          <div class="donut-wrap">
            <div class="donut" style="background:{issue_donut_style}">
              <div class="donut-inner"><strong>{issue_total}</strong><span>findings</span></div>
            </div>
          </div>
          <div class="legend">{issue_legend_html}</div>
        </article>
      </div>
    </section>

    <section class="panel">
      <h2 class="section-title">Reference Figure Pack</h2>
      <div class="chart-grid">{chart_figure_html}</div>
    </section>

    <section class="panel">
      <h2 class="section-title">Crawl and Quality Stats</h2>
      <div class="stats">
        {stats_cards}
      </div>
    </section>

    <section class="panel">
      <h2 class="section-title">Prioritized Findings</h2>
      <table>
        <thead>
          <tr>
            <th>Priority</th>
            <th>Category</th>
            <th>Issue</th>
            <th>Recommendation</th>
            <th>Effort / Lift</th>
          </tr>
        </thead>
        <tbody>
          {issue_rows}
        </tbody>
      </table>
    </section>

    <section class="panel cols">
      <div>
        <h2 class="section-title">Quick Wins</h2>
        <ul>{quick_win_items}</ul>
      </div>
      <div>
        <h2 class="section-title">Evidence Appendix</h2>
        <ul>{evidence_html}</ul>
      </div>
    </section>

    <section class="panel">
      <h2 class="section-title">Visual Evidence</h2>
      <div class="chips">{visual_chips}</div>
      <div class="shots">{screenshots_html}</div>
    </section>

    <section class="panel">
      <h2 class="section-title">Section Intelligence</h2>
      <div class="section-grid">{section_intelligence_html}</div>
    </section>

    <section class="panel">
      <h2 class="section-title">Specialist Orchestration</h2>
      {orchestration_html}
    </section>

    <div class="foot">Generated by codex-seo audit runner | template audit-dossier-v4</div>
  </div>
</body>
</html>
"""


def write_html_and_pdf_reports(
    output_dir: Path,
    html_content: str,
) -> dict[str, str | None]:
    html_report = output_dir / "FULL-AUDIT-REPORT.html"
    pdf_report = output_dir / "FULL-AUDIT-REPORT.pdf"
    html_report.write_text(html_content, encoding="utf-8")

    pdf_status = "skipped"
    pdf_reason = "Playwright unavailable. Install with: pip install playwright && python -m playwright install chromium"
    pdf_path: str | None = None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "html_report": str(html_report),
            "pdf_report": pdf_path,
            "pdf_status": pdf_status,
            "pdf_reason": pdf_reason,
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 2100})
            page.goto(html_report.resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_report),
                format="A4",
                print_background=True,
                margin={"top": "10mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
            )
            browser.close()
        pdf_status = "ok"
        pdf_reason = ""
        pdf_path = str(pdf_report)
    except Exception as exc:
        pdf_status = "skipped"
        pdf_reason = f"PDF render failed: {exc}"

    return {
        "html_report": str(html_report),
        "pdf_report": pdf_path,
        "pdf_status": pdf_status,
        "pdf_reason": pdf_reason,
    }


def write_reports(
    output_dir: Path,
    target_url: str,
    pages: list[PageResult],
    scores: dict[str, float | None],
    stats: dict[str, Any],
    issues: list[dict[str, Any]],
    visual: dict[str, Any],
    orchestration: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    for key in ("technical", "content", "onpage", "schema", "performance", "images", "ai_readiness"):
        value = scores[key]
        label = SCORE_LABELS[key]
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
    screenshot_rel_paths = _collect_relative_screenshots(visual, output_dir)
    section_rel_data = _collect_relative_sections(visual, output_dir)
    if screenshot_rel_paths:
        for rel in screenshot_rel_paths:
            visual_lines.append(f"- Screenshot: `{rel}`")
    if section_rel_data:
        visual_lines.append(f"- Section snapshots analyzed: {len(section_rel_data)}")
        for sec in section_rel_data[:6]:
            visual_lines.append(
                f"- Section `{sec['label']}`: {sec['observation']} (words={sec['word_count']}, cta={sec['cta_count']}, forms={sec['form_count']})"
            )
            if sec.get("capture_reason"):
                visual_lines.append(f"  - Why captured: {sec['capture_reason']}")
            if sec.get("ocr_excerpt"):
                visual_lines.append(
                    f"  - OCR: {sec['ocr_excerpt'][:180]} (lines={sec.get('ocr_line_count')}, conf={sec.get('ocr_avg_confidence')})"
                )
    if visual.get("h1_visible_above_fold") is not None:
        visual_lines.append(f"- H1 visible above fold: {visual['h1_visible_above_fold']}")
    if visual.get("cta_visible_above_fold") is not None:
        visual_lines.append(f"- CTA visible above fold: {visual['cta_visible_above_fold']}")
    if visual.get("viewport_meta_present") is not None:
        visual_lines.append(f"- Viewport meta present: {visual['viewport_meta_present']}")
    if visual.get("horizontal_scroll_mobile") is not None:
        visual_lines.append(f"- Horizontal scroll on mobile: {visual['horizontal_scroll_mobile']}")
    if visual.get("mobile_nav_accessible") is not None:
        visual_lines.append(f"- Mobile navigation detected: {visual['mobile_nav_accessible']}")
    if visual.get("mobile_touch_targets_total") is not None and visual.get("mobile_touch_targets_small") is not None:
        visual_lines.append(
            f"- Touch targets below 48px: {visual['mobile_touch_targets_small']}/{visual['mobile_touch_targets_total']}"
        )
    if visual.get("mobile_min_font_px") is not None:
        visual_lines.append(f"- Minimum mobile font size (px): {visual['mobile_min_font_px']}")
    if visual.get("mobile_text_readability_ok") is not None:
        visual_lines.append(f"- Text readability (>=16px): {visual['mobile_text_readability_ok']}")
    if visual.get("desktop_overlap_issues") is not None:
        visual_lines.append(f"- Desktop overlap signal count: {visual['desktop_overlap_issues']}")
    if visual.get("desktop_overflow_issues") is not None:
        visual_lines.append(f"- Desktop overflow signal count: {visual['desktop_overflow_issues']}")
    if visual.get("ocr_status"):
        visual_lines.append(f"- OCR status: {visual.get('ocr_status')}")
    if visual.get("ocr_sections_total") is not None and visual.get("ocr_sections_with_text") is not None:
        visual_lines.append(
            f"- OCR sections with text: {visual.get('ocr_sections_with_text')}/{visual.get('ocr_sections_total')}"
        )
    if visual.get("ocr_avg_confidence") is not None:
        visual_lines.append(f"- OCR average confidence: {visual.get('ocr_avg_confidence')}")
    if visual.get("ocr_reason"):
        visual_lines.append(f"- OCR note: {visual.get('ocr_reason')}")

    orchestration_lines: list[str] = []
    if orchestration and orchestration.get("enabled"):
        orchestration_lines.append(
            f"- Specialist tracks succeeded: {orchestration.get('success_count', 0)}/{orchestration.get('total_tracks', 0)}"
        )
        orchestration_lines.append("- Summary file: `ORCHESTRATION-SUMMARY.json`")
        orchestration_lines.append("")
        orchestration_lines.append("| Track | Status | Duration (s) | Primary Report | Metrics |")
        orchestration_lines.append("|---|---|---:|---|---|")
        for track in orchestration.get("tracks", []):
            metrics = track.get("summary_metrics") or {}
            metrics_text = ", ".join(f"{k}={v}" for k, v in metrics.items()) if metrics else "n/a"
            primary_report = str(track.get("primary_report") or "")
            if primary_report:
                primary_report = f"`tracks/{track.get('name')}/{primary_report}`"
            else:
                primary_report = "n/a"
            orchestration_lines.append(
                f"| {track.get('name')} | {track.get('status')} | {track.get('duration_sec')} | {primary_report} | {metrics_text} |"
            )
        failed = orchestration.get("failed_tracks") or []
        if failed:
            orchestration_lines.append("")
            orchestration_lines.append(f"- Failed tracks: {', '.join(str(x) for x in failed)}")
    else:
        orchestration_lines.append("- Specialist orchestration disabled for this run.")

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
- Performance data source: {stats.get('performance_source', 'proxy')}
- CWV status: {(stats.get('cwv') or {}).get('status', 'n/a')}
- Mobile field LCP p75 (ms): {((stats.get('cwv') or {}).get('mobile') or {}).get('field_lcp_ms')}
- Mobile field INP p75 (ms): {((stats.get('cwv') or {}).get('mobile') or {}).get('field_inp_ms')}
- Mobile field CLS p75: {((stats.get('cwv') or {}).get('mobile') or {}).get('field_cls')}
- Lighthouse performance score (avg): {(stats.get('cwv') or {}).get('lab_score')}
- Word count p25 / median / p75: {stats['word_count_p25']} / {stats['word_count_median']} / {stats['word_count_p75']}
- Security headers present: {len(stats['security_headers']['present'])}/{len(SECURITY_HEADERS)}

## Visual Checks

{chr(10).join(visual_lines)}

## Specialist Orchestration

{chr(10).join(orchestration_lines)}

## Notes

- Performance score uses live Lighthouse + CrUX when available, otherwise response-time proxy fallback.
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
Performance scored **{scores['performance']}** using **{stats.get('performance_source', 'proxy')}** data. Current latency baseline is median **{_fmt_number(stats['median_response_ms'], 1)} ms** and p90 **{_fmt_number(stats['p90_response_ms'], 1)} ms**. Mobile field CWV p75 currently reads LCP **{_fmt_number((((stats.get('cwv') or {}).get('mobile') or {}).get('field_lcp_ms')), 1)} ms**, INP **{_fmt_number((((stats.get('cwv') or {}).get('mobile') or {}).get('field_inp_ms')), 1)} ms**, CLS **{_fmt_number((((stats.get('cwv') or {}).get('mobile') or {}).get('field_cls')), 3)}** when available.

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

    chart_pack = generate_reference_charts(
        output_dir=output_dir,
        target_url=target_url,
        total_score=total_score,
        scores=scores,
        stats=stats,
        issues=issues,
    )
    chart_figures = chart_pack.get("figures") if isinstance(chart_pack, dict) else []

    html_content = build_html_report(
        target_url=target_url,
        generated_at=generated_at,
        total_score=total_score,
        grade=grade,
        band=band,
        business_label=business_label,
        business_confidence=business_confidence,
        scores=scores,
        stats=stats,
        issues=issues,
        quick_wins=quick_wins,
        visual=visual,
        screenshot_paths=screenshot_rel_paths,
        section_insights=section_rel_data,
        chart_figures=chart_figures,
        orchestration=orchestration,
    )
    rendered_outputs = write_html_and_pdf_reports(output_dir=output_dir, html_content=html_content)

    artifacts = {
        "markdown_report": str(full_report),
        "action_plan": str(action_plan),
        "summary_json": str(summary_json),
        "issues_json": str(issues_json),
        "html_report": rendered_outputs["html_report"],
        "pdf_report": rendered_outputs["pdf_report"],
        "pdf_status": rendered_outputs["pdf_status"],
        "pdf_reason": rendered_outputs["pdf_reason"],
        "charts_enabled": bool(chart_pack.get("enabled")) if isinstance(chart_pack, dict) else False,
        "charts_reason": str(chart_pack.get("reason") or "") if isinstance(chart_pack, dict) else "",
        "chart_figures": chart_figures if isinstance(chart_figures, list) else [],
        "charts_dir": (str(output_dir / "charts") if bool(chart_pack.get("enabled")) else None) if isinstance(chart_pack, dict) else None,
        "orchestration_summary": (
            str(output_dir / "ORCHESTRATION-SUMMARY.json")
            if (output_dir / "ORCHESTRATION-SUMMARY.json").exists()
            else None
        ),
    }

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
                "orchestration": orchestration or {"enabled": False},
                "artifacts": artifacts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    issues_json.write_text(json.dumps(issues, indent=2), encoding="utf-8")
    return artifacts


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
    parser.add_argument(
        "--orchestrate",
        choices=["on", "off"],
        default="on",
        help="Run specialist deterministic tracks in parallel and merge outputs.",
    )
    parser.add_argument(
        "--cwv-source",
        choices=["auto", "pagespeed", "off"],
        default="auto",
        help="CWV data source (auto/pagespeed/off).",
    )
    parser.add_argument(
        "--pagespeed-key",
        default=os.getenv("PAGESPEED_API_KEY", ""),
        help="Optional Google PageSpeed API key (or set PAGESPEED_API_KEY).",
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

    print("Fetching CWV...")
    cwv_data = run_cwv_assessment(
        target_url=target_url,
        timeout=args.timeout,
        source=args.cwv_source,
        pagespeed_key=str(args.pagespeed_key or "").strip(),
    )
    print(f"CWV status: {cwv_data.get('status')} ({cwv_data.get('source', args.cwv_source)})")
    if cwv_data.get("reason"):
        print(f"CWV note: {cwv_data.get('reason')}")

    print("Scoring...")
    scores, stats, issues = compute_scores(
        pages,
        target_url,
        crawl_info,
        timeout=args.timeout,
        cwv=cwv_data,
    )

    print("Running visual checks...")
    visual = run_visual_checks(target_url, output_dir, args.visual)

    orchestration: dict[str, Any] | None = None
    if args.orchestrate == "on":
        print("Running specialist orchestration...")
        orchestration = run_specialist_orchestration(
            target_url=target_url,
            output_dir=output_dir,
            timeout=args.timeout,
            visual_mode=args.visual,
        )
        print(
            f"Specialist tracks: {orchestration.get('success_count', 0)}/{orchestration.get('total_tracks', 0)} succeeded"
        )

    print("Writing reports...")
    artifacts = write_reports(output_dir, target_url, pages, scores, stats, issues, visual, orchestration=orchestration)
    health_score, not_measured = aggregate_health_score(scores)

    print(f"Done. Health score: {health_score}/100")
    if not_measured:
        print(f"Not measured: {', '.join(not_measured)}")
    print(f"Report: {artifacts['markdown_report']}")
    print(f"Action plan: {artifacts['action_plan']}")
    print(f"HTML report: {artifacts['html_report']}")
    if artifacts.get("pdf_report"):
        print(f"PDF report: {artifacts['pdf_report']}")
    else:
        print(f"PDF report: skipped ({artifacts.get('pdf_reason')})")
    if artifacts.get("orchestration_summary"):
        print(f"Orchestration summary: {artifacts['orchestration_summary']}")
    print(f"Summary: {artifacts['summary_json']}")
    print(f"Issues: {artifacts['issues_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
