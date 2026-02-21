#!/usr/bin/env python3
"""
Technical SEO runner for the seo-technical skill.

Usage:
    python run_technical_audit.py https://example.com
    python run_technical_audit.py https://example.com --mobile-check auto
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import time
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
MAX_REDIRECT_HOPS = 10

AI_CRAWLERS = [
    "GPTBot",
    "ChatGPT-User",
    "ClaudeBot",
    "PerplexityBot",
    "Bytespider",
    "Google-Extended",
    "CCBot",
]

SECURITY_HEADERS = [
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
]

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def request_public(method: str, url: str, timeout: int) -> tuple[requests.Response, str, int]:
    current_url = url
    redirects = 0
    while True:
        if not is_public_target(current_url):
            raise ValueError("redirected target URL resolves to non-public or invalid host")
        response = requests.request(method, current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
        if 300 <= response.status_code < 400:
            location = (response.headers.get("Location") or "").strip()
            if not location:
                return response, current_url, redirects
            if redirects >= MAX_REDIRECT_HOPS:
                raise ValueError(f"Too many redirects (>{MAX_REDIRECT_HOPS})")
            next_url = normalize_url(urljoin(current_url, location))
            if not is_public_target(next_url):
                raise ValueError("redirected target URL resolves to non-public or invalid host")
            current_url = next_url
            redirects += 1
            continue
        return response, current_url, redirects


def fetch_url(url: str, timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response, final_url, redirects = request_public("GET", url, timeout)
    except (requests.exceptions.RequestException, ValueError) as exc:
        return {"error": str(exc)}
    return {
        "status_code": response.status_code,
        "final_url": final_url,
        "headers": {k.lower(): v for k, v in dict(response.headers).items()},
        "text": response.text,
        "redirect_hops": redirects,
        "response_ms": round((time.perf_counter() - started) * 1000, 2),
        "error": None,
    }


def fetch_text(url: str, timeout: int) -> dict[str, Any]:
    try:
        response, _final_url, _redirects = request_public("GET", url, timeout)
        return {"ok": response.status_code < 400, "status_code": response.status_code, "text": response.text}
    except (requests.exceptions.RequestException, ValueError):
        return {"ok": False, "status_code": None, "text": ""}


def try_head(url: str, timeout: int) -> dict[str, Any]:
    try:
        response, _final_url, _redirects = request_public("HEAD", url, timeout)
        headers = {k.lower(): v for k, v in dict(response.headers).items()}
        return {"ok": response.status_code < 400, "status_code": response.status_code, "headers": headers}
    except (requests.exceptions.RequestException, ValueError):
        return {"ok": False, "status_code": None, "headers": {}}


def probe_url(url: str, timeout: int) -> dict[str, Any]:
    probe = try_head(url, timeout)
    if probe["ok"]:
        return {"exists": True, "restricted": False, "status_code": probe["status_code"]}
    if probe["status_code"] in (405, 403, 401, None):
        check = fetch_text(url, timeout)
        if check["ok"]:
            return {"exists": True, "restricted": False, "status_code": check["status_code"]}
        if check["status_code"] in (401, 403):
            return {"exists": True, "restricted": True, "status_code": check["status_code"]}
    return {"exists": False, "restricted": False, "status_code": probe["status_code"]}


def resolve_canonical(base_url: str, canonical_value: str | None) -> str | None:
    if not canonical_value:
        return None
    merged = urljoin(base_url, canonical_value.strip())
    parsed = urlparse(merged)
    if parsed.scheme not in ("http", "https"):
        return None
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def soup_of(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return str(tag.get("content")).strip()
    return None


def parse_robots(robots_text: str) -> dict[str, Any]:
    lines = robots_text.splitlines()
    entries: dict[str, dict[str, list[str]]] = {}
    current_agents: list[str] = []
    seen_directive_in_group = False
    sitemaps: list[str] = []

    for raw_line in lines:
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            agent = value.lower()
            if seen_directive_in_group:
                current_agents = [agent]
                seen_directive_in_group = False
            else:
                if agent not in current_agents:
                    current_agents.append(agent)
            if agent not in entries:
                entries[agent] = {"allow": [], "disallow": []}
        elif key in ("allow", "disallow"):
            if not current_agents:
                continue
            for agent in current_agents:
                if agent not in entries:
                    entries[agent] = {"allow": [], "disallow": []}
                entries[agent][key].append(value)
            seen_directive_in_group = True
        elif key == "sitemap":
            sitemaps.append(value)

    ai_policy: dict[str, str] = {}
    for crawler in AI_CRAWLERS:
        crawler_key = crawler.lower()
        data = entries.get(crawler_key)
        wildcard = entries.get("*")
        if data is None and wildcard is None:
            ai_policy[crawler] = "unspecified"
            continue
        use = data if data is not None else wildcard
        disallow_all = "/" in [x.strip() for x in use["disallow"]]
        allow_all = "/" in [x.strip() for x in use["allow"]]
        if disallow_all and not allow_all:
            ai_policy[crawler] = "blocked"
        elif allow_all:
            ai_policy[crawler] = "allowed"
        else:
            ai_policy[crawler] = "partial"

    return {"entries": entries, "sitemaps": sitemaps, "ai_policy": ai_policy}


def evaluate_sitemaps(base_url: str, robots_sitemaps: list[str], timeout: int) -> dict[str, Any]:
    checked: list[str] = []
    working: list[str] = []
    restricted: list[str] = []

    candidates = [urljoin(base_url, item) for item in robots_sitemaps if item.strip()]
    if not candidates:
        candidates = [urljoin(base_url, "/sitemap.xml")]

    for candidate in candidates:
        if candidate in checked:
            continue
        checked.append(candidate)
        if not is_public_target(candidate):
            continue
        state = probe_url(candidate, timeout)
        if state["exists"] and not state["restricted"]:
            working.append(candidate)
        elif state["exists"] and state["restricted"]:
            restricted.append(candidate)

    return {
        "exists": len(working) > 0 or len(restricted) > 0,
        "checked_urls": checked,
        "working_urls": working,
        "restricted_urls": restricted,
        "source": "robots" if robots_sitemaps else "default",
    }


def evaluate_indexnow(base_url: str, robots_text: str, timeout: int) -> dict[str, Any]:
    endpoint = urljoin(base_url, "/indexnow")
    robots_mentions = "indexnow" in robots_text.lower()
    probe = try_head(endpoint, timeout)
    status = probe["status_code"]
    body = ""
    body_mentions = False

    # GET fallback for environments where HEAD is blocked or inconclusive.
    if status is None or status in (400, 401, 403, 405, 422, 200):
        text_probe = fetch_text(endpoint, timeout)
        if text_probe["status_code"] is not None:
            status = text_probe["status_code"]
        body = (text_probe["text"] or "").lower()
        body_mentions = "indexnow" in body

    endpoint_signal = status in (202, 204, 405, 422) or (status == 200 and body_mentions)
    likely_supported = robots_mentions or endpoint_signal
    possible_supported = not likely_supported and status in (400, 401, 403)

    confidence = "low"
    if likely_supported and robots_mentions and endpoint_signal:
        confidence = "high"
    elif likely_supported:
        confidence = "medium"
    elif possible_supported:
        confidence = "low"

    return {
        "endpoint_url": endpoint,
        "endpoint_status_code": status,
        "robots_mentions_indexnow": robots_mentions,
        "endpoint_mentions_indexnow": body_mentions,
        "likely_supported": likely_supported,
        "possible_support": possible_supported,
        "confidence": confidence,
    }


def extract_main_text(soup: BeautifulSoup) -> str:
    region = soup.find("main") or soup.find("article") or soup.body or soup
    clone = BeautifulSoup(str(region), "html.parser")
    for node in clone(["script", "style", "noscript", "svg", "canvas", "nav", "header", "footer", "aside"]):
        node.decompose()
    text = clone.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def parse_schema(soup: BeautifulSoup) -> dict[str, Any]:
    blocks = soup.find_all("script", type="application/ld+json")
    types: list[str] = []
    invalid = 0
    for block in blocks:
        payload = (block.string or "").strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            invalid += 1
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if "@type" in item:
                    t = item["@type"]
                    if isinstance(t, list):
                        types.extend([str(x) for x in t])
                    else:
                        types.append(str(t))
                if "@graph" in item:
                    stack.append(item["@graph"])
            elif isinstance(item, list):
                stack.extend(item)
    normalized = sorted(set([t for t in [x.strip() for x in types] if t]))
    return {
        "block_count": len(blocks),
        "invalid_count": invalid,
        "types": normalized,
        "has_deprecated_howto": any(t.lower() == "howto" for t in normalized),
        "has_restricted_faq": any(t.lower() == "faqpage" for t in normalized),
    }


def image_risk(soup: BeautifulSoup, base_url: str, timeout: int) -> dict[str, Any]:
    images = soup.find_all("img")
    missing_dims = 0
    oversize_warn = 0
    oversize_critical = 0
    checked = 0
    for img in images:
        if not img.get("width") or not img.get("height"):
            missing_dims += 1
        src = (img.get("src") or "").strip()
        if not src:
            continue
        if checked >= 20:
            continue
        full = urljoin(base_url, src)
        if not full.startswith(("http://", "https://")):
            continue
        head = try_head(full, timeout)
        cl = head["headers"].get("content-length")
        if cl and str(cl).isdigit():
            size = int(cl)
            if size > 500_000:
                oversize_critical += 1
            elif size > 200_000:
                oversize_warn += 1
        checked += 1
    return {
        "count": len(images),
        "missing_dimensions": missing_dims,
        "oversize_warn": oversize_warn,
        "oversize_critical": oversize_critical,
    }


def mobile_checks(url: str, mode: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": "skipped",
        "reason": "",
        "horizontal_scroll": None,
        "base_font_size": None,
    }
    if mode == "off":
        out["reason"] = "mobile check disabled"
        return out
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        out["status"] = "not_available" if mode == "auto" else "failed"
        out["reason"] = "Playwright unavailable. Install with: pip install playwright && python -m playwright install chromium"
        return out

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 375, "height": 812})
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(600)
            scroll_width = int(page.evaluate("document.documentElement.scrollWidth"))
            viewport_width = int(page.evaluate("window.innerWidth"))
            font_size = float(
                page.evaluate(
                    """() => {
                        const style = window.getComputedStyle(document.body);
                        return parseFloat(style.fontSize || "16");
                    }"""
                )
            )
            context.close()
            browser.close()
        out["status"] = "ok"
        out["horizontal_scroll"] = scroll_width > viewport_width
        out["base_font_size"] = round(font_size, 2)
        return out
    except Exception as exc:
        out["status"] = "failed"
        out["reason"] = str(exc)
        return out


def status_icon(score: float) -> str:
    if score >= 85:
        return "✅"
    if score >= 60:
        return "⚠️"
    return "❌"


def add_issue(issues: list[dict[str, str]], priority: str, title: str, detail: str) -> None:
    issues.append({"priority": priority, "title": title, "detail": detail})


def compute_scores(data: dict[str, Any]) -> tuple[dict[str, float], float, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []

    crawlability = 100.0
    if not data["robots"]["exists"]:
        crawlability -= 30
        add_issue(issues, "High", "Missing robots.txt", "Create robots.txt and define crawler policy.")
    if not data["sitemap"]["exists"]:
        crawlability -= 20
        if data["sitemap"]["source"] == "robots" and data["sitemap"]["checked_urls"]:
            add_issue(
                issues,
                "High",
                "Robots.txt sitemap URLs are unreachable",
                "Fix or replace declared sitemap URLs in robots.txt.",
            )
        else:
            add_issue(issues, "High", "Missing sitemap.xml", "Publish sitemap.xml and reference it in robots.txt.")
    elif data["sitemap"]["restricted_urls"] and not data["sitemap"]["working_urls"]:
        crawlability -= 5
        add_issue(
            issues,
            "Medium",
            "Sitemap access restricted",
            "Declared sitemap URL responds with access restrictions (401/403) for this agent.",
        )
    if data["meta_robots"] and "noindex" in data["meta_robots"].lower():
        crawlability -= 20
        add_issue(issues, "Critical", "Page marked noindex", "Remove noindex if this page should rank.")
    blocked_ai = [k for k, v in data["robots"]["ai_policy"].items() if v == "blocked"]
    if len(blocked_ai) == len(AI_CRAWLERS) and len(blocked_ai) > 0:
        crawlability -= 8
        add_issue(
            issues,
            "Low",
            "All known AI crawlers are blocked",
            "Verify this aligns with your AI visibility strategy.",
        )
    if data["robots"]["ai_policy"].get("Google-Extended") == "blocked":
        add_issue(
            issues,
            "Low",
            "Google-Extended blocked",
            "This blocks Gemini training use only and does not affect Google Search indexing.",
        )
    if data["robots"]["ai_policy"].get("GPTBot") == "blocked" and data["robots"]["ai_policy"].get("ChatGPT-User") != "blocked":
        add_issue(
            issues,
            "Low",
            "GPTBot blocked but ChatGPT-User not blocked",
            "Training is blocked while ChatGPT browsing access may still occur.",
        )
    if not data["indexnow"]["likely_supported"]:
        crawlability -= 3
        add_issue(
            issues,
            "Low",
            "IndexNow not detected",
            "Optional: add IndexNow support for faster recrawl signals on Bing/Yandex/Naver.",
        )
    crawlability = clamp(crawlability, 0, 100)

    indexability = 100.0
    if not data["canonical"]:
        indexability -= 25
        add_issue(issues, "High", "Missing canonical tag", "Add a self-referencing canonical URL.")
    else:
        c_host = urlparse(data["canonical"]).hostname
        f_host = urlparse(data["final_url"]).hostname
        if c_host and f_host and c_host.lower() != f_host.lower():
            indexability -= 20
            add_issue(issues, "High", "Canonical points to another host", "Verify canonical domain alignment.")
    if data["meta_robots"] and "noindex" in data["meta_robots"].lower():
        indexability -= 30
    if data["query_present"]:
        indexability -= 10
        add_issue(issues, "Medium", "Query-string URL", "Use clean canonical URLs for indexable pages.")
    if data["hreflang_count"] > 0 and not data["canonical"]:
        indexability -= 8
        add_issue(issues, "Medium", "hreflang without canonical", "Pair hreflang with canonical implementation.")
    indexability = clamp(indexability, 0, 100)

    security = 100.0
    if urlparse(data["final_url"]).scheme != "https":
        security -= 20
        add_issue(issues, "High", "Site not using HTTPS", "Redirect all traffic to HTTPS.")
    missing_headers = [h for h in SECURITY_HEADERS if h not in data["headers"]]
    if missing_headers:
        security -= min(40, len(missing_headers) * 8)
        add_issue(
            issues,
            "Medium",
            "Missing security headers",
            "Missing: " + ", ".join(missing_headers),
        )
    security = clamp(security, 0, 100)

    url_score = 100.0
    if data["url_length"] > 100:
        url_score -= 15
        add_issue(issues, "Medium", "Long URL", f"URL length is {data['url_length']} characters.")
    if data["query_present"]:
        url_score -= 10
    if data["redirect_hops"] > 1:
        url_score -= 15
        add_issue(issues, "Medium", "Redirect chain", f"{data['redirect_hops']} redirect hops detected.")
    if data["has_uppercase_path"]:
        url_score -= 5
        add_issue(issues, "Low", "Uppercase URL path", "Prefer lowercase URL paths.")
    if data["has_underscore_path"]:
        url_score -= 5
        add_issue(issues, "Low", "Underscore in URL path", "Prefer hyphens in URL slugs.")
    url_score = clamp(url_score, 0, 100)

    mobile = 100.0
    if not data["viewport_meta"]:
        mobile -= 25
        add_issue(issues, "High", "Missing viewport meta tag", "Add viewport meta for responsive layout.")
    if data["mobile_probe"]["status"] == "ok":
        if data["mobile_probe"]["horizontal_scroll"]:
            mobile -= 20
            add_issue(issues, "High", "Horizontal scroll on mobile", "Fix overflow and responsive width constraints.")
        if data["mobile_probe"]["base_font_size"] is not None and data["mobile_probe"]["base_font_size"] < 16:
            mobile -= 10
            add_issue(
                issues,
                "Medium",
                "Small mobile base font size",
                f"Detected {data['mobile_probe']['base_font_size']}px base font size.",
            )
    elif data["mobile_probe"]["status"] in ("failed", "not_available"):
        mobile -= 5
    mobile = clamp(mobile, 0, 100)

    cwv = 100.0
    if data["blocking_scripts"] > 5:
        cwv -= 20
        add_issue(issues, "Medium", "High blocking script count", f"{data['blocking_scripts']} blocking scripts detected.")
    if data["image_risk"]["oversize_critical"] > 0:
        cwv -= 20
        add_issue(
            issues,
            "High",
            "Oversized images detected",
            f"{data['image_risk']['oversize_critical']} images exceed 500KB.",
        )
    if data["image_risk"]["missing_dimensions"] > 0:
        cwv -= 15
        add_issue(
            issues,
            "Medium",
            "Images missing width/height",
            f"{data['image_risk']['missing_dimensions']} images missing dimensions.",
        )
    if data["response_ms"] > 1200:
        cwv -= 12
        add_issue(issues, "Medium", "Slow initial response", f"Response time is {data['response_ms']} ms.")
    cwv = clamp(cwv, 0, 100)

    structured_data = 100.0
    if data["schema"]["block_count"] == 0:
        structured_data -= 40
        add_issue(issues, "Medium", "No JSON-LD schema found", "Add schema relevant to this page type.")
    if data["schema"]["invalid_count"] > 0:
        structured_data -= 20
        add_issue(issues, "High", "Invalid schema blocks", f"{data['schema']['invalid_count']} schema blocks failed parsing.")
    if data["schema"]["has_deprecated_howto"]:
        structured_data -= 20
        add_issue(issues, "High", "Deprecated HowTo schema detected", "Remove HowTo schema usage.")
    if data["schema"]["has_restricted_faq"]:
        structured_data -= 10
        add_issue(issues, "Medium", "FAQPage schema detected", "Use FAQ schema only when eligibility rules are met.")
    structured_data = clamp(structured_data, 0, 100)

    js_render = 100.0
    if data["framework_detected"]:
        js_render -= 10
    if data["script_count"] > 20:
        js_render -= 10
        add_issue(issues, "Medium", "Very high script volume", f"{data['script_count']} script tags detected.")
    if data["script_count"] > 10 and data["main_word_count"] < 150:
        js_render -= 25
        add_issue(
            issues,
            "High",
            "Potential JS-only rendering risk",
            "Low initial text content with heavy script usage can hurt indexing.",
        )
    js_render = clamp(js_render, 0, 100)

    scores = {
        "Crawlability": round(crawlability, 1),
        "Indexability": round(indexability, 1),
        "Security": round(security, 1),
        "URL Structure": round(url_score, 1),
        "Mobile": round(mobile, 1),
        "Core Web Vitals": round(cwv, 1),
        "Structured Data": round(structured_data, 1),
        "JS Rendering": round(js_render, 1),
    }
    overall = round(sum(scores.values()) / len(scores), 1)
    return scores, overall, issues


def write_outputs(output_dir: Path, data: dict[str, Any], scores: dict[str, float], overall: float, issues: list[dict[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "TECHNICAL-AUDIT-REPORT.md"
    plan_file = output_dir / "TECHNICAL-ACTION-PLAN.md"
    summary_file = output_dir / "SUMMARY.json"

    ordered_issues = sorted(issues, key=lambda x: PRIORITY_ORDER.get(x["priority"], 99))
    grouped = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for issue in ordered_issues:
        grouped[issue["priority"]].append(issue)

    rows = []
    for category, score in scores.items():
        rows.append(f"| {category} | {status_icon(score)} | {score}/100 |")

    ai_rows = []
    for crawler in AI_CRAWLERS:
        ai_rows.append(f"| {crawler} | {data['robots']['ai_policy'].get(crawler, 'unspecified')} |")

    report = f"""# Technical SEO Audit Report

## Executive Summary

- URL: `{data['final_url']}`
- HTTP Status: `{data['status_code']}`
- Response Time: `{data['response_ms']} ms`
- Technical Score: **{overall}/100**

## Category Breakdown

| Category | Status | Score |
|---|---|---|
{chr(10).join(rows)}

## Crawlability Details

- robots.txt: {data['robots']['exists']}
- sitemap.xml: {data['sitemap']['exists']}
- Sitemap source: {data['sitemap']['source']}
- Sitemaps in robots.txt: {len(data['robots']['sitemaps'])}
- Sitemap URLs checked: {len(data['sitemap']['checked_urls'])}
- Working sitemap URLs: {len(data['sitemap']['working_urls'])}
- Restricted sitemap URLs (401/403): {len(data['sitemap']['restricted_urls'])}
- Meta robots: `{data['meta_robots']}`

### AI Crawler Policy

| Crawler | Policy |
|---|---|
{chr(10).join(ai_rows)}

## Technical Signals

- Canonical: `{data['canonical']}`
- Hreflang tags: {data['hreflang_count']}
- Security headers present: {len(data['security_headers_present'])}/{len(SECURITY_HEADERS)}
- Redirect hops: {data['redirect_hops']}
- URL length: {data['url_length']}
- Viewport meta: {data['viewport_meta']}
- Mobile probe status: {data['mobile_probe']['status']}
- Mobile horizontal scroll: {data['mobile_probe']['horizontal_scroll']}
- Mobile base font size: {data['mobile_probe']['base_font_size']}
- Script count: {data['script_count']}
- Blocking scripts: {data['blocking_scripts']}
- Main content word count: {data['main_word_count']}
- Framework detected: {data['framework_detected']}
- JSON-LD blocks: {data['schema']['block_count']}
- Schema types: {", ".join(data['schema']['types']) if data['schema']['types'] else "None"}

## IndexNow Readiness (Optional)

- Endpoint: `{data['indexnow']['endpoint_url']}`
- Endpoint status: `{data['indexnow']['endpoint_status_code']}`
- Mentioned in robots.txt: `{data['indexnow']['robots_mentions_indexnow']}`
- Mentioned in endpoint response: `{data['indexnow']['endpoint_mentions_indexnow']}`
- Likely supported: `{data['indexnow']['likely_supported']}`
- Confidence: `{data['indexnow']['confidence']}`

## Prioritized Issues

### Critical
{chr(10).join([f"- **{x['title']}**: {x['detail']}" for x in grouped['Critical']]) or "- None"}

### High
{chr(10).join([f"- **{x['title']}**: {x['detail']}" for x in grouped['High']]) or "- None"}

### Medium
{chr(10).join([f"- **{x['title']}**: {x['detail']}" for x in grouped['Medium']]) or "- None"}

### Low
{chr(10).join([f"- **{x['title']}**: {x['detail']}" for x in grouped['Low']]) or "- None"}

## Notes

- LCP/INP/CLS are evaluated as technical risk indicators, not field/lab CWV measurements.
- INP is the interactivity metric; this report never uses FID.
"""

    action_lines = [
        "# Technical SEO Action Plan",
        "",
        f"- Target URL: `{data['final_url']}`",
        f"- Technical Score: **{overall}/100**",
        "",
    ]
    for priority in ("Critical", "High", "Medium", "Low"):
        action_lines.append(f"## {priority}")
        bucket = grouped[priority]
        if not bucket:
            action_lines.append("- No actions in this tier.")
        else:
            for idx, item in enumerate(bucket, start=1):
                action_lines.append(f"{idx}. {item['title']} - {item['detail']}")
        action_lines.append("")

    report_file.write_text(report, encoding="utf-8")
    plan_file.write_text("\n".join(action_lines).strip() + "\n", encoding="utf-8")
    summary_file.write_text(
        json.dumps(
            {
                "url": data["final_url"],
                "technical_score": overall,
                "scores": scores,
                "issues": ordered_issues,
                "signals": {
                    "robots": data["robots"],
                    "sitemap": data["sitemap"],
                    "indexnow": data["indexnow"],
                    "security_headers_present": data["security_headers_present"],
                    "mobile_probe": data["mobile_probe"],
                    "schema": data["schema"],
                    "script_count": data["script_count"],
                    "blocking_scripts": data["blocking_scripts"],
                    "main_word_count": data["main_word_count"],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run technical SEO audit for one URL.")
    parser.add_argument("url", help="Target URL")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument(
        "--mobile-check",
        choices=["auto", "on", "off"],
        default="auto",
        help="Run Playwright-based mobile checks when available",
    )
    parser.add_argument("--output-dir", default="seo-technical-output", help="Output directory")
    args = parser.parse_args()

    try:
        normalized = normalize_url(args.url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    if not is_public_target(normalized):
        print("Error: target URL resolves to non-public or invalid host")
        return 2

    fetched = fetch_url(normalized, args.timeout)
    if fetched["error"]:
        print(f"Error: failed to fetch target: {fetched['error']}")
        return 1
    if not fetched["text"]:
        print("Error: empty response body")
        return 1

    final_url = normalize_url(fetched["final_url"])
    if not is_public_target(final_url):
        print("Error: redirected target URL resolves to non-public or invalid host")
        return 1
    soup = soup_of(fetched["text"])

    robots_url = urljoin(final_url, "/robots.txt")
    robots_resp = fetch_text(robots_url, args.timeout)
    robots_exists = bool(robots_resp["ok"])
    robots_parsed = parse_robots(robots_resp["text"]) if robots_exists else parse_robots("")
    sitemap_state = evaluate_sitemaps(final_url, robots_parsed["sitemaps"], args.timeout)
    indexnow_state = evaluate_indexnow(final_url, robots_resp["text"] if robots_exists else "", args.timeout)

    canonical_tag = soup.find("link", rel="canonical")
    canonical_raw = str(canonical_tag.get("href")).strip() if canonical_tag and canonical_tag.get("href") else None
    canonical = resolve_canonical(final_url, canonical_raw)

    hreflang_count = 0
    for link in soup.find_all("link", rel="alternate"):
        if link.get("hreflang"):
            hreflang_count += 1

    viewport_meta = soup.find("meta", attrs={"name": "viewport"}) is not None

    scripts = soup.find_all("script")
    script_count = len(scripts)
    blocking_scripts = 0
    for script in scripts:
        if script.get("src") and not script.get("async") and not script.get("defer"):
            blocking_scripts += 1

    html_lower = fetched["text"].lower()
    framework_detected = any(marker in html_lower for marker in ["react", "next.js", "nextjs", "vue", "angular", "svelte", "__nuxt"])

    main_text = extract_main_text(soup)
    main_word_count = len(re.findall(r"\b\w+\b", main_text))

    schema = parse_schema(soup)
    img_risk = image_risk(soup, final_url, args.timeout)
    m_probe = mobile_checks(final_url, args.mobile_check)

    data = {
        "status_code": fetched["status_code"],
        "final_url": final_url,
        "response_ms": fetched["response_ms"],
        "headers": fetched["headers"],
        "redirect_hops": fetched["redirect_hops"],
        "meta_robots": meta(soup, "robots"),
        "canonical": canonical,
        "query_present": bool(urlparse(final_url).query),
        "hreflang_count": hreflang_count,
        "robots": {
            "exists": robots_exists,
            "url": robots_url,
            "sitemaps": robots_parsed["sitemaps"],
            "ai_policy": robots_parsed["ai_policy"],
        },
        "indexnow": indexnow_state,
        "sitemap": {
            "exists": sitemap_state["exists"],
            "checked_urls": sitemap_state["checked_urls"],
            "working_urls": sitemap_state["working_urls"],
            "restricted_urls": sitemap_state["restricted_urls"],
            "source": sitemap_state["source"],
        },
        "security_headers_present": [h for h in SECURITY_HEADERS if h in fetched["headers"]],
        "url_length": len(final_url),
        "has_uppercase_path": bool(re.search(r"[A-Z]", urlparse(final_url).path)),
        "has_underscore_path": "_" in (urlparse(final_url).path or ""),
        "viewport_meta": viewport_meta,
        "mobile_probe": m_probe,
        "script_count": script_count,
        "blocking_scripts": blocking_scripts,
        "framework_detected": framework_detected,
        "main_word_count": main_word_count,
        "schema": schema,
        "image_risk": img_risk,
    }

    scores, overall, issues = compute_scores(data)
    output_dir = Path(args.output_dir).resolve()
    write_outputs(output_dir, data, scores, overall, issues)

    print(f"URL: {final_url}")
    print(f"Technical score: {overall}/100")
    print(f"Report: {output_dir / 'TECHNICAL-AUDIT-REPORT.md'}")
    print(f"Action plan: {output_dir / 'TECHNICAL-ACTION-PLAN.md'}")
    print(f"Summary: {output_dir / 'SUMMARY.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
