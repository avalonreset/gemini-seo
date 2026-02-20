#!/usr/bin/env python3
"""
Deep single-page SEO analyzer for the seo-page skill.
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

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "you",
    "your",
}


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
    normalized = (host or "").strip().lower().rstrip(".")
    if normalized.startswith("www."):
        return normalized[4:]
    return normalized


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


def fetch(url: str, timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    current_url = url
    redirects = 0
    resp: requests.Response | None = None
    try:
        while True:
            if not is_public_target(current_url):
                return {"error": "redirected target URL resolves to non-public or invalid host"}
            resp = requests.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
            if 300 <= resp.status_code < 400:
                location = (resp.headers.get("Location") or "").strip()
                if not location:
                    break
                if redirects >= MAX_REDIRECT_HOPS:
                    return {"error": f"Too many redirects (>{MAX_REDIRECT_HOPS})"}
                try:
                    next_url = normalize_url(urljoin(current_url, location))
                except ValueError as exc:
                    return {"error": f"Invalid redirect URL: {exc}"}
                if not is_public_target(next_url):
                    return {"error": "redirected target URL resolves to non-public or invalid host"}
                current_url = next_url
                redirects += 1
                continue
            break
    except requests.exceptions.RequestException as exc:
        return {"error": str(exc)}
    if resp is None:
        return {"error": "No response returned"}
    return {
        "status_code": resp.status_code,
        "final_url": current_url,
        "headers": dict(resp.headers),
        "text": resp.text,
        "response_ms": round((time.perf_counter() - started) * 1000, 2),
        "redirect_hops": redirects,
        "error": None,
    }


def soup_of(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def meta(soup: BeautifulSoup, name: str | None = None, prop: str | None = None) -> str | None:
    tag = None
    if name:
        tag = soup.find("meta", attrs={"name": name})
    elif prop:
        tag = soup.find("meta", attrs={"property": prop})
    if tag and tag.get("content"):
        return str(tag.get("content")).strip()
    return None


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


def extract_content_text(soup: BeautifulSoup) -> str:
    region = soup.find("main") or soup.find("article") or soup.body or soup
    clone = BeautifulSoup(str(region), "html.parser")
    for node in clone(["script", "style", "noscript", "svg", "canvas", "nav", "header", "footer", "aside"]):
        node.decompose()
    text = clone.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 1
    count = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def readability(text: str) -> dict[str, float]:
    words = tokenize(text)
    wc = len(words)
    sc = max(1, len(re.findall(r"[.!?]+", text)))
    if wc == 0:
        return {"flesch": 0.0, "grade": 0.0}
    spw = sum(syllables(w) for w in words) / wc
    wps = wc / sc
    flesch = 206.835 - (1.015 * wps) - (84.6 * spw)
    grade = (0.39 * wps) + (11.8 * spw) - 15.59
    return {"flesch": round(flesch, 2), "grade": round(grade, 2)}


def infer_keyword(title: str | None, h1: str | None, url: str) -> str | None:
    blob = " ".join(filter(None, [title, h1, urlparse(url).path.replace("/", " ")]))
    tokens = [t for t in tokenize(blob) if len(t) > 2 and t not in STOPWORDS]
    if not tokens:
        return None
    counts: dict[str, int] = {}
    for tok in tokens:
        counts[tok] = counts.get(tok, 0) + 1
    ordered = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top = [x[0] for x in ordered[:2]]
    return " ".join(top) if top else None


def keyword_density(text: str, keyword: str | None) -> dict[str, Any]:
    words = tokenize(text)
    if not words or not keyword:
        return {"keyword": keyword, "occurrences": 0, "density_pct": 0.0}
    occurrences = len(re.findall(rf"\b{re.escape(keyword.lower())}\b", text.lower()))
    return {"keyword": keyword, "occurrences": occurrences, "density_pct": round((occurrences / len(words)) * 100, 2)}


def normalize_schema_type(value: str) -> str:
    cleaned = str(value or "").strip().rstrip("/")
    if not cleaned:
        return ""
    if "#" in cleaned:
        cleaned = cleaned.rsplit("#", 1)[-1]
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    return cleaned.strip().lower()


def parse_schema(soup: BeautifulSoup) -> dict[str, Any]:
    blocks = soup.find_all("script", type="application/ld+json")
    types: list[str] = []
    invalid = 0
    for b in blocks:
        raw = (b.string or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            invalid += 1
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@type" in node:
                    t = node["@type"]
                    if isinstance(t, list):
                        types.extend([str(x) for x in t])
                    else:
                        types.append(str(t))
                if "@graph" in node:
                    stack.append(node["@graph"])
    unique = sorted(set(t.strip() for t in types if t and str(t).strip()))
    normalized_types = sorted(set(t for t in (normalize_schema_type(x) for x in unique) if t))
    return {
        "block_count": len(blocks),
        "invalid_count": invalid,
        "types": unique,
        "normalized_types": normalized_types,
        "deprecated_howto": "howto" in normalized_types,
        "restricted_faq": "faqpage" in normalized_types,
    }


def analyze_images(soup: BeautifulSoup, base_url: str, timeout: int) -> dict[str, Any]:
    imgs = soup.find_all("img")
    missing_alt = 0
    missing_dims = 0
    lazy = 0
    oversized_warn = 0
    oversized_crit = 0
    modern = 0
    checked = 0
    for img in imgs:
        src = (img.get("src") or "").strip()
        if not src:
            continue
        full = urljoin(base_url, src)
        ext = Path(urlparse(full).path).suffix.lower()
        if ext in (".webp", ".avif"):
            modern += 1
        if not (img.get("alt") and str(img.get("alt")).strip()):
            missing_alt += 1
        if not img.get("width") or not img.get("height"):
            missing_dims += 1
        if str(img.get("loading") or "").lower() == "lazy":
            lazy += 1
        if checked < 15 and full.startswith(("http://", "https://")):
            if not is_public_target(full):
                checked += 1
                continue
            try:
                current_url = full
                redirects = 0
                while True:
                    r = requests.head(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
                    if 300 <= r.status_code < 400:
                        location = (r.headers.get("Location") or "").strip()
                        if not location or redirects >= MAX_REDIRECT_HOPS:
                            break
                        try:
                            next_url = normalize_url(urljoin(current_url, location))
                        except ValueError:
                            break
                        if not is_public_target(next_url):
                            break
                        current_url = next_url
                        redirects += 1
                        continue
                    break
                cl = r.headers.get("Content-Length")
                if cl and str(cl).isdigit():
                    size = int(cl)
                    if size > 500_000:
                        oversized_crit += 1
                    elif size > 200_000:
                        oversized_warn += 1
            except requests.exceptions.RequestException:
                pass
            checked += 1
    return {
        "count": len(imgs),
        "missing_alt": missing_alt,
        "missing_dimensions": missing_dims,
        "lazy_count": lazy,
        "oversized_warn": oversized_warn,
        "oversized_critical": oversized_crit,
        "modern_format_count": modern,
    }


def eeat_signals(text: str, internal_links: list[str], external_count: int) -> dict[str, Any]:
    low = text.lower()
    author = bool(re.search(r"\bby\s+[A-Z][a-z]+", text))
    experience = bool(re.search(r"\b(we tested|i tested|our experience|case study|hands-on)\b", low))
    credentials = bool(re.search(r"\b(phd|md|cpa|certified|licensed)\b", low))
    trust = any(x in link.lower() for link in internal_links for x in ("/about", "/contact", "/privacy", "/terms"))
    citations = external_count > 0
    score = round(((author + experience + credentials + trust + citations) / 5) * 100, 1)
    return {"author": author, "experience": experience, "credentials": credentials, "trust": trust, "citations": citations, "score": score}


def score_page(data: dict[str, Any]) -> tuple[dict[str, float], float, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    onpage = 100.0
    if not data["title"]:
        onpage -= 30
        issues.append({"priority": "Critical", "title": "Missing title tag", "detail": "Add a unique title (50-60 chars)."})
    if not data["meta_description"]:
        onpage -= 20
        issues.append({"priority": "High", "title": "Missing meta description", "detail": "Add a compelling 140-160 char description."})
    if data["h1_count"] != 1:
        onpage -= 20
        issues.append({"priority": "High", "title": "H1 structure issue", "detail": f"Detected {data['h1_count']} H1 tags; use exactly one."})
    if data["heading_skips"] > 0:
        onpage -= 8
        issues.append({"priority": "Medium", "title": "Heading hierarchy skips", "detail": "Avoid skipped heading levels (e.g., H2->H4)."})
    if data["query_present"]:
        onpage -= 6
        issues.append({"priority": "Low", "title": "Query-string URL", "detail": "Prefer a clean canonical URL for ranking pages."})

    content = 100.0
    if data["word_count"] < 300:
        content -= 30
        issues.append({"priority": "High", "title": "Thin content risk", "detail": f"Only {data['word_count']} words detected."})
    if data["readability"]["flesch"] < 45:
        content -= 10
        issues.append({"priority": "Medium", "title": "Low readability", "detail": f"Flesch score is {data['readability']['flesch']}."})
    kd = data["keyword_density"]["density_pct"]
    if data["keyword_density"]["keyword"] and data["keyword_source"] == "user":
        if kd < 0.3:
            content -= 10
            issues.append({"priority": "Medium", "title": "Keyword underused", "detail": f"Density {kd}% is low for focus phrase."})
        elif kd > 3.5:
            content -= 12
            issues.append({"priority": "Medium", "title": "Possible keyword stuffing", "detail": f"Density {kd}% is high."})
    if data["eeat"]["score"] < 40:
        content -= 12
        issues.append({"priority": "Medium", "title": "Weak E-E-A-T signals", "detail": "Add author/trust/citation signals."})

    technical = 100.0
    if not data["canonical"]:
        technical -= 18
        issues.append({"priority": "High", "title": "Missing canonical", "detail": "Add rel=canonical."})
    if "noindex" in (data["meta_robots"] or "").lower():
        technical -= 35
        issues.append({"priority": "Critical", "title": "Page marked noindex", "detail": "Remove noindex if page should rank."})
    if not data["og_complete"]:
        technical -= 12
        issues.append({"priority": "Medium", "title": "Open Graph incomplete", "detail": "Add og:title, og:description, og:image, og:url."})
    if not data["twitter_complete"]:
        technical -= 8
        issues.append({"priority": "Low", "title": "Twitter Card incomplete", "detail": "Add twitter:card/title/description."})

    schema = 100.0
    if data["schema"]["block_count"] == 0:
        schema -= 45
        issues.append({"priority": "Medium", "title": "No schema detected", "detail": "Add schema for page type."})
    if data["schema"]["invalid_count"] > 0:
        schema -= 20
        issues.append({"priority": "High", "title": "Invalid schema detected", "detail": "Fix JSON-LD syntax/structure."})
    if data["schema"]["deprecated_howto"]:
        schema -= 20
        issues.append({"priority": "High", "title": "Deprecated HowTo schema", "detail": "Remove/replace HowTo schema."})

    images = 100.0
    count = max(1, data["images"]["count"])
    images -= (data["images"]["missing_alt"] / count) * 45
    images -= (data["images"]["missing_dimensions"] / count) * 25
    images -= (data["images"]["oversized_warn"] / count) * 10
    images -= (data["images"]["oversized_critical"] / count) * 20
    if data["images"]["missing_alt"] > 0:
        issues.append({"priority": "Medium", "title": "Images missing alt", "detail": f"{data['images']['missing_alt']}/{data['images']['count']} missing alt text."})
    if data["images"]["oversized_critical"] > 0:
        issues.append({"priority": "High", "title": "Oversized images >500KB", "detail": "Compress/convert large images."})
    if data["cwv_cls_risk"]:
        issues.append({"priority": "Medium", "title": "Potential CLS risk", "detail": "Images missing dimensions can shift layout."})

    scores = {
        "onpage": round(clamp(onpage, 0, 100), 1),
        "content": round(clamp(content, 0, 100), 1),
        "technical": round(clamp(technical, 0, 100), 1),
        "schema": round(clamp(schema, 0, 100), 1),
        "images": round(clamp(images, 0, 100), 1),
    }
    overall = round(scores["onpage"] * 0.25 + scores["content"] * 0.25 + scores["technical"] * 0.25 + scores["schema"] * 0.15 + scores["images"] * 0.10, 1)
    return scores, overall, issues


def visual_capture(url: str, out_dir: Path, mode: str) -> dict[str, Any]:
    if mode == "off":
        return {"status": "skipped", "reason": "visual mode disabled", "screenshot": None}
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {
            "status": "not_available" if mode == "auto" else "failed",
            "reason": "Playwright unavailable. Install with: pip install playwright && python -m playwright install chromium",
            "screenshot": None,
        }
    shots = out_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    shot = shots / "page-desktop.png"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(800)
            page.screenshot(path=str(shot), full_page=True)
            context.close()
            browser.close()
        return {"status": "ok", "reason": "", "screenshot": str(shot)}
    except Exception as exc:
        return {"status": "failed", "reason": str(exc), "screenshot": None}


def bar(score: float) -> str:
    blocks = int(round(score / 10))
    return ("█" * blocks) + ("░" * (10 - blocks))


def main() -> int:
    p = argparse.ArgumentParser(description="Run deep single-page SEO analysis.")
    p.add_argument("url")
    p.add_argument("--keyword", help="Optional focus keyword/phrase")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--visual", choices=["auto", "on", "off"], default="auto")
    p.add_argument("--output-dir", default="seo-page-output")
    args = p.parse_args()

    try:
        target = normalize_url(args.url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    if not is_public_target(target):
        print("Error: target URL resolves to non-public or invalid host")
        return 2

    fetched = fetch(target, args.timeout)
    if fetched["error"]:
        print(f"Error: {fetched['error']}")
        return 1
    status_code = int(fetched.get("status_code") or 0)
    if status_code < 200 or status_code >= 300:
        print(f"Error: non-success HTTP status from target: {status_code}")
        return 1
    if not fetched["text"]:
        print("Error: empty response")
        return 1

    final_url = normalize_url(fetched["final_url"])
    if not is_public_target(final_url):
        print("Error: redirected target URL resolves to non-public or invalid host")
        return 1
    soup = soup_of(fetched["text"])
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    h1_tags = soup.find_all("h1")
    h1_text = h1_tags[0].get_text(" ", strip=True) if h1_tags else None
    text = extract_content_text(soup)
    words = tokenize(text)
    heading_seq = [int(tag.name[1]) for tag in soup.find_all(re.compile("^h[1-6]$"))]
    heading_skips = 0
    for i in range(1, len(heading_seq)):
        if heading_seq[i] > heading_seq[i - 1] + 1:
            heading_skips += 1

    links_internal: list[str] = []
    links_external = 0
    host = canonical_host(urlparse(final_url).hostname)
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a.get("href", ""))
        h = canonical_host(urlparse(href).hostname)
        if h == host:
            links_internal.append(href)
        elif h:
            links_external += 1

    keyword_source = "user" if args.keyword else "inferred"
    keyword = args.keyword.lower().strip() if args.keyword else infer_keyword(title, h1_text, final_url)
    schema = parse_schema(soup)
    images = analyze_images(soup, final_url, args.timeout)
    eeat = eeat_signals(text, links_internal, links_external)
    read = readability(text)

    data = {
        "final_url": final_url,
        "status_code": fetched["status_code"],
        "response_ms": fetched["response_ms"],
        "title": title,
        "meta_description": meta(soup, name="description"),
        "meta_robots": meta(soup, name="robots"),
        "canonical": (soup.find("link", rel="canonical").get("href") if soup.find("link", rel="canonical") else None),
        "h1_count": len(h1_tags),
        "heading_skips": heading_skips,
        "query_present": bool(urlparse(final_url).query),
        "word_count": len(words),
        "readability": read,
        "keyword_density": keyword_density(text, keyword),
        "keyword_source": keyword_source,
        "og_complete": all(meta(soup, prop=x) for x in ("og:title", "og:description", "og:image", "og:url")),
        "twitter_complete": all(meta(soup, name=x) for x in ("twitter:card", "twitter:title", "twitter:description")),
        "schema": schema,
        "images": images,
        "eeat": eeat,
        "cwv_cls_risk": images["missing_dimensions"] > 0,
    }

    scores, overall, issues = score_page(data)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    visual = visual_capture(final_url, out, args.visual)

    suggestions = []
    existing = set(schema.get("normalized_types") or [])
    if "organization" not in existing and "website" not in existing:
        suggestions.append(
            {
                "type": "Organization",
                "reason": "No org-level schema detected.",
                "jsonld": {
                    "@context": "https://schema.org",
                    "@type": "Organization",
                    "name": "Your Brand",
                    "url": f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}",
                },
            }
        )
    if "article" not in existing and any(k in text.lower() for k in ("published", "author", "updated", "read time")):
        suggestions.append(
            {
                "type": "Article",
                "reason": "Editorial cues detected and no Article schema found.",
                "jsonld": {
                    "@context": "https://schema.org",
                    "@type": "Article",
                    "headline": title or "Page Title",
                    "mainEntityOfPage": final_url,
                },
            }
        )

    ordered = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for issue in issues:
        ordered[issue["priority"]].append(issue)

    report = out / "PAGE-AUDIT-REPORT.md"
    summary = out / "SUMMARY.json"
    report.write_text(
        f"""# Single-Page SEO Report

## Executive Summary
- URL: `{data['final_url']}`
- HTTP Status: `{data['status_code']}`
- Response Time: `{data['response_ms']} ms`
- Overall Score: **{overall}/100**

## Page Score Card
Overall Score: {overall}/100

On-Page SEO:     {scores['onpage']}/100  {bar(scores['onpage'])}
Content Quality: {scores['content']}/100  {bar(scores['content'])}
Technical:       {scores['technical']}/100  {bar(scores['technical'])}
Schema:          {scores['schema']}/100  {bar(scores['schema'])}
Images:          {scores['images']}/100  {bar(scores['images'])}

## Key Metrics
- Title length: {len(data['title'] or '')}
- Meta description length: {len(data['meta_description'] or '')}
- H1 count: {data['h1_count']}
- Word count: {data['word_count']}
- Keyword: `{data['keyword_density']['keyword']}`
- Keyword source: `{data['keyword_source']}`
- Keyword density: {data['keyword_density']['density_pct']}%
- E-E-A-T score: {data['eeat']['score']}%
- Schema types: {", ".join(data['schema']['types']) if data['schema']['types'] else "None"}
- Images missing alt: {data['images']['missing_alt']}/{data['images']['count']}
- Images missing dimensions: {data['images']['missing_dimensions']}/{data['images']['count']}

## Issues Found
### Critical
{chr(10).join([f"- **{i['title']}**: {i['detail']}" for i in ordered['Critical']]) or "- None"}
### High
{chr(10).join([f"- **{i['title']}**: {i['detail']}" for i in ordered['High']]) or "- None"}
### Medium
{chr(10).join([f"- **{i['title']}**: {i['detail']}" for i in ordered['Medium']]) or "- None"}
### Low
{chr(10).join([f"- **{i['title']}**: {i['detail']}" for i in ordered['Low']]) or "- None"}

## Schema Suggestions
{chr(10).join([f"### {s['type']}{chr(10)}- Why: {s['reason']}{chr(10)}```json{chr(10)}{json.dumps(s['jsonld'], indent=2)}{chr(10)}```" for s in suggestions]) or "No additional schema suggestions generated."}

## Visual Capture
- Status: {visual['status']}
- Note: {visual['reason']}
- Screenshot: `{visual['screenshot']}`
""",
        encoding="utf-8",
    )
    summary.write_text(
        json.dumps(
            {
                "url": data["final_url"],
                "scores": scores,
                "overall": overall,
                "keyword_source": data["keyword_source"],
                "issues": issues,
                "schema_suggestions": suggestions,
                "visual": visual,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"URL: {data['final_url']}")
    print(f"Overall score: {overall}/100")
    print(f"Report: {report}")
    print(f"Summary: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
