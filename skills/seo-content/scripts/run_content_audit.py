#!/usr/bin/env python3
"""
Content quality and E-E-A-T audit runner for the seo-content skill.

Usage:
    python run_content_audit.py https://example.com/blog/post
    python run_content_audit.py https://example.com --keyword "project management software"
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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

WORD_FLOORS = {
    "homepage": 500,
    "service_page": 800,
    "blog_post": 1500,
    "product_page": 300,
    "location_page": 550,
    "generic_page": 400,
}

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

GENERIC_AI_PHRASES = [
    "in today's fast-paced world",
    "unlock the power of",
    "delve into",
    "it is important to note",
    "in conclusion",
    "without further ado",
    "in the ever-evolving landscape",
    "let's dive in",
]

EXPERIENCE_MARKERS = [
    "we tested",
    "i tested",
    "our experience",
    "case study",
    "we implemented",
    "hands-on",
    "from our work",
    "we observed",
]

CREDENTIAL_PATTERNS = [
    re.compile(r"\bph\.?d\.?\b"),
    re.compile(r"\bm\.?d\.?\b"),
    re.compile(r"\bcpa\b"),
    re.compile(r"\bcertified\b"),
    re.compile(r"\blicensed\b"),
    re.compile(r"\bboard[- ]certified\b"),
    re.compile(r"\bprofessor\b"),
    re.compile(r"\bengineer\b"),
    re.compile(r"\bspecialist\b"),
]

TRUST_LINK_MARKERS = ["/about", "/contact", "/privacy", "/terms", "/editorial", "/team"]


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


def fetch_page(url: str, timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    current_url = url
    redirect_hops = 0
    response: requests.Response | None = None
    while True:
        if not is_public_target(current_url):
            return {"error": "redirected target URL resolves to non-public or invalid host"}
        try:
            response = requests.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
        except requests.exceptions.RequestException as exc:
            return {"error": str(exc)}
        if 300 <= response.status_code < 400:
            location = (response.headers.get("Location") or "").strip()
            if not location:
                break
            if redirect_hops >= MAX_REDIRECT_HOPS:
                return {"error": f"Too many redirects (>{MAX_REDIRECT_HOPS})"}
            try:
                next_url = normalize_url(urljoin(current_url, location))
            except ValueError as exc:
                return {"error": f"Invalid redirect URL: {exc}"}
            if not is_public_target(next_url):
                return {"error": "redirected target URL resolves to non-public or invalid host"}
            current_url = next_url
            redirect_hops += 1
            continue
        break
    if response is None:
        return {"error": "No response returned"}
    return {
        "status_code": response.status_code,
        "final_url": current_url,
        "headers": dict(response.headers),
        "text": response.text,
        "response_ms": round((time.perf_counter() - started) * 1000, 2),
        "error": None,
    }


def soup_of(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


def extract_main_text(soup: BeautifulSoup) -> str:
    region = soup.find("main") or soup.find("article") or soup.body or soup
    clone = BeautifulSoup(str(region), "html.parser")
    for node in clone(["script", "style", "noscript", "svg", "canvas", "nav", "header", "footer", "aside"]):
        node.decompose()
    text = clone.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def count_syllables(word: str) -> int:
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 1
    count = len(re.findall(r"[aeiouy]+", cleaned))
    if cleaned.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def readability_metrics(text: str) -> dict[str, float]:
    words = tokenize(text)
    word_count = len(words)
    sentence_count = max(1, len(extract_sentences(text)))
    if word_count == 0:
        return {"flesch": 0.0, "grade": 0.0, "avg_sentence_words": 0.0}
    avg_sentence_words = word_count / sentence_count
    avg_syllables = sum(count_syllables(word) for word in words) / word_count
    flesch = 206.835 - (1.015 * avg_sentence_words) - (84.6 * avg_syllables)
    grade = (0.39 * avg_sentence_words) + (11.8 * avg_syllables) - 15.59
    return {
        "flesch": round(flesch, 2),
        "grade": round(grade, 2),
        "avg_sentence_words": round(avg_sentence_words, 2),
    }


def extract_links(soup: BeautifulSoup, base_url: str) -> dict[str, Any]:
    base_host = (urlparse(base_url).hostname or "").lower()
    internal: list[str] = []
    external: list[str] = []
    external_authority = 0
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        host = (parsed.hostname or "").lower()
        if not host:
            continue
        if host == base_host:
            internal.append(full)
        else:
            external.append(full)
            if host.endswith(".gov") or host.endswith(".edu") or host.endswith(".org"):
                external_authority += 1
    return {
        "internal": sorted(set(internal)),
        "external": sorted(set(external)),
        "external_authority_count": external_authority,
    }


def detect_page_type(url: str, title: str | None, h1: str | None) -> str:
    path = (urlparse(url).path or "/").lower()
    title_text = (title or "").lower()
    h1_text = (h1 or "").lower()
    text = " ".join(filter(None, [title_text, h1_text]))

    def has_word_terms(value: str, terms: list[str]) -> bool:
        return any(re.search(rf"\b{re.escape(term)}\b", value) for term in terms)

    if path == "/" or path == "":
        return "homepage"

    if any(x in path for x in ["/product", "/products", "/pricing", "/shop"]):
        return "product_page"
    if any(x in path for x in ["/service", "/services", "/solutions", "/consulting"]):
        return "service_page"
    # Keep location detection strict to avoid misclassifying generic narrative pages.
    if any(x in path for x in ["/location", "/locations", "/near-", "/city/"]):
        return "location_page"
    if any(x in path for x in ["/blog", "/article", "/articles", "/news", "/guides", "/guide", "/tutorial", "/insights"]):
        return "blog_post"

    if has_word_terms(text, ["blog", "article", "news", "guide", "guides", "tutorial", "insights", "case study"]):
        return "blog_post"
    if "add to cart" in text or has_word_terms(text, ["product", "pricing", "shop", "sku"]):
        return "product_page"
    if has_word_terms(text, ["service", "services", "solutions", "consulting", "agency"]):
        return "service_page"
    return "generic_page"


def extract_schema_types(soup: BeautifulSoup) -> dict[str, Any]:
    blocks = soup.find_all("script", type="application/ld+json")
    types: list[str] = []
    invalid = 0
    for block in blocks:
        raw = (block.string or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            invalid += 1
            continue
        stack = [data]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                if "@type" in current:
                    value = current["@type"]
                    if isinstance(value, list):
                        types.extend([str(v) for v in value])
                    else:
                        types.append(str(value))
                if "@graph" in current:
                    stack.append(current["@graph"])
            elif isinstance(current, list):
                stack.extend(current)
    return {"count": len(blocks), "types": sorted(set(types)), "invalid_count": invalid}


def extract_author_signals(soup: BeautifulSoup, _text: str) -> dict[str, Any]:
    region = soup.find("article") or soup.find("main") or soup.body or soup
    byline = None
    author_meta = soup.find("meta", attrs={"name": "author"})
    if author_meta and author_meta.get("content"):
        byline = str(author_meta.get("content")).strip()
    if not byline:
        maybe = region.find(string=re.compile(r"\bby\s+[A-Z][a-z]+"))
        if maybe:
            byline = str(maybe).strip()

    class_hits = 0
    author_scope_fragments: list[str] = []
    for tag in region.find_all(True):
        classes = " ".join([str(c).lower() for c in tag.get("class", [])])
        if any(x in classes for x in ["author", "bio", "editor", "reviewed"]):
            class_hits += 1
            snippet = tag.get_text(" ", strip=True)
            if snippet:
                author_scope_fragments.append(snippet[:500])
            if class_hits > 3:
                break

    scoped_text = " ".join(filter(None, [byline or ""] + author_scope_fragments)).lower()
    credentials = any(pattern.search(scoped_text) for pattern in CREDENTIAL_PATTERNS)
    return {
        "author_present": bool(byline) or class_hits > 0,
        "byline": byline,
        "credentials_present": credentials,
        "author_markup_hits": class_hits,
    }


def extract_freshness_signals(soup: BeautifulSoup, headers: dict[str, Any]) -> dict[str, Any]:
    dates: list[datetime] = []
    date_strings: list[str] = []

    def try_parse(value: str) -> None:
        if not value:
            return
        raw = value.strip()
        if not raw:
            return
        date_strings.append(raw)
        parsed: datetime | None = None
        try:
            normalized = raw.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            parsed = None
        if parsed is None:
            try:
                parsed = parsedate_to_datetime(raw)
            except Exception:
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            dates.append(parsed.astimezone(UTC))

    meta_candidates = [
        ("name", "last-modified"),
        ("name", "date"),
        ("name", "publish_date"),
        ("property", "article:published_time"),
        ("property", "article:modified_time"),
    ]
    for attr, key in meta_candidates:
        tag = soup.find("meta", attrs={attr: key})
        if tag and tag.get("content"):
            try_parse(str(tag.get("content")))

    for tag in soup.find_all("time"):
        if tag.get("datetime"):
            try_parse(str(tag.get("datetime")))

    if isinstance(headers, dict):
        value = headers.get("Last-Modified") or headers.get("last-modified")
        if value:
            try_parse(str(value))

    latest = max(dates) if dates else None
    age_days = None
    if latest is not None:
        age_days = max(0, (datetime.now(tz=UTC) - latest).days)

    return {
        "date_strings": date_strings[:10],
        "latest_utc": latest.isoformat() if latest else None,
        "age_days": age_days,
    }


def ai_quality_markers(text: str) -> dict[str, Any]:
    low = text.lower()
    generic_hits = sum(low.count(phrase) for phrase in GENERIC_AI_PHRASES)

    sentences = extract_sentences(text)
    starters: dict[str, int] = {}
    for sentence in sentences[:120]:
        words = tokenize(sentence)
        if len(words) < 3:
            continue
        key = " ".join(words[:2])
        starters[key] = starters.get(key, 0) + 1
    repetitive_openings = sum(1 for _, count in starters.items() if count >= 3)

    numbers = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", text))
    specificity_score = clamp(min(100.0, numbers * 4.0), 0.0, 100.0)

    risk = 0.0
    risk += min(35.0, generic_hits * 8.0)
    risk += min(25.0, repetitive_openings * 7.0)
    risk += max(0.0, 25.0 - (specificity_score * 0.25))
    risk = clamp(risk, 0.0, 100.0)

    return {
        "generic_phrase_hits": generic_hits,
        "repetitive_openings": repetitive_openings,
        "specificity_score": round(specificity_score, 1),
        "ai_risk_score": round(risk, 1),
    }


def citation_readiness_score(
    soup: BeautifulSoup,
    text: str,
    links: dict[str, Any],
    schema: dict[str, Any],
    has_clear_heading_hierarchy: bool,
) -> tuple[float, dict[str, Any]]:
    list_items = len(soup.find_all("li"))
    table_count = len(soup.find_all("table"))
    heading_count = len(soup.find_all(re.compile("^h[1-6]$")))
    fact_points = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", text))
    external_citations = len(links["external"])
    answer_first = bool(re.search(r"^\s*(what|how|why|when|where)\b", text.lower()))

    score = 100.0
    if heading_count < 3:
        score -= 15.0
    if not has_clear_heading_hierarchy:
        score -= 10.0
    if list_items < 3:
        score -= 10.0
    if table_count == 0 and fact_points >= 10:
        score -= 5.0
    if external_citations == 0:
        score -= 20.0
    if schema["count"] == 0:
        score -= 15.0
    if fact_points < 3:
        score -= 10.0
    if not answer_first:
        score -= 5.0

    return round(clamp(score, 0.0, 100.0), 1), {
        "heading_count": heading_count,
        "list_items": list_items,
        "table_count": table_count,
        "fact_points": fact_points,
        "external_citations": external_citations,
        "answer_first_pattern": answer_first,
    }


def score_eeat(signals: dict[str, Any]) -> tuple[dict[str, float], float]:
    experience_signals = 0
    experience_signals += 1 if signals["experience_markers"] >= 2 else 0
    experience_signals += 1 if signals["media_count"] >= 2 else 0
    experience_signals += 1 if signals["fact_points"] >= 5 else 0
    experience_signals += 1 if signals["first_person_signals"] >= 2 else 0
    experience = (experience_signals / 4) * 100

    expertise_signals = 0
    expertise_signals += 1 if signals["author_present"] else 0
    expertise_signals += 1 if signals["credentials_present"] else 0
    expertise_signals += 1 if signals["external_citations"] >= 2 else 0
    expertise_signals += 1 if signals["word_count"] >= 600 else 0
    expertise = (expertise_signals / 4) * 100

    authority_signals = 0
    authority_signals += 1 if signals["external_citations"] >= 3 else 0
    authority_signals += 1 if signals["external_authority_count"] >= 1 else 0
    authority_signals += 1 if signals["schema_count"] > 0 else 0
    authority_signals += 1 if signals["internal_links"] >= 3 else 0
    authority = (authority_signals / 4) * 100

    trust_signals = 0.0
    trust_signals += 1 if signals["https"] else 0
    trust_signals += 1 if signals["trust_links"] >= 2 else 0
    trust_signals += 1 if signals["author_present"] else 0
    freshness_age_days = signals["freshness_age_days"]
    if freshness_age_days is not None:
        if freshness_age_days <= 180:
            trust_signals += 1
        elif freshness_age_days <= 365:
            trust_signals += 0.5
    trust = (trust_signals / 4) * 100

    total = (experience * 0.20) + (expertise * 0.25) + (authority * 0.25) + (trust * 0.30)
    factors = {
        "experience": round(experience, 1),
        "expertise": round(expertise, 1),
        "authoritativeness": round(authority, 1),
        "trustworthiness": round(trust, 1),
    }
    return factors, round(total, 1)


def heading_hierarchy_ok(soup: BeautifulSoup) -> tuple[bool, int, list[str]]:
    levels = [int(tag.name[1]) for tag in soup.find_all(re.compile("^h[1-6]$"))]
    skips = []
    for idx in range(1, len(levels)):
        if levels[idx] > levels[idx - 1] + 1:
            skips.append(f"H{levels[idx - 1]}->H{levels[idx]}")
    return len(skips) == 0, len(skips), skips[:6]


def score_content_quality(data: dict[str, Any]) -> float:
    coverage = 100.0 if data["word_count"] >= data["word_floor"] else clamp((data["word_count"] / max(1, data["word_floor"])) * 100, 0.0, 100.0)

    flesch = data["readability"]["flesch"]
    if flesch >= 60:
        readability = 95.0
    elif flesch >= 45:
        readability = 80.0
    elif flesch >= 30:
        readability = 65.0
    else:
        readability = 45.0

    structure = 100.0
    if not data["has_single_h1"]:
        structure -= 20.0
    if not data["heading_hierarchy_ok"]:
        structure -= 15.0
    if data["internal_links"] < 2:
        structure -= 10.0
    structure = clamp(structure, 0.0, 100.0)

    keyword_score = 100.0
    if data["keyword"] is not None:
        density = data["keyword_density_pct"]
        if density < 0.3:
            keyword_score -= 25.0
        elif density > 3.5:
            keyword_score -= 25.0

    overall = (
        (coverage * 0.30)
        + (readability * 0.15)
        + (structure * 0.15)
        + (data["eeat_total"] * 0.25)
        + (keyword_score * 0.15)
    )
    return round(clamp(overall, 0.0, 100.0), 1)


def prioritize_issues(data: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    if data["word_count"] < int(data["word_floor"] * 0.7):
        issues.append(
            {
                "priority": "High",
                "title": "Thin content for page intent",
                "detail": f"{data['word_count']} words vs {data['word_floor']} minimum guideline for {data['page_type']}.",
            }
        )
    elif data["word_count"] < data["word_floor"]:
        issues.append(
            {
                "priority": "Medium",
                "title": "Coverage depth below guideline",
                "detail": f"{data['word_count']} words vs {data['word_floor']} minimum guideline for {data['page_type']}.",
            }
        )

    if not data["author"]["author_present"]:
        author_priority = "High" if data["page_type"] == "blog_post" else "Medium"
        issues.append(
            {
                "priority": author_priority,
                "title": "Missing author attribution",
                "detail": "No clear author/byline signals detected.",
            }
        )
    if not data["author"]["credentials_present"]:
        issues.append(
            {
                "priority": "Medium",
                "title": "Weak expertise signals",
                "detail": "No visible credential or qualification markers detected.",
            }
        )
    if data["trust_links"] < 2:
        issues.append(
            {
                "priority": "Medium",
                "title": "Limited trust/transparency links",
                "detail": "Add clear About, Contact, Privacy, and Terms links.",
            }
        )

    if data["readability"]["flesch"] < 35:
        issues.append(
            {
                "priority": "Medium",
                "title": "Readability is difficult",
                "detail": f"Flesch score is {data['readability']['flesch']}.",
            }
        )

    if data["keyword"] is not None:
        if data["keyword_density_pct"] < 0.3:
            issues.append(
                {
                    "priority": "Medium",
                    "title": "Focus keyword underused",
                    "detail": f"Keyword density is {data['keyword_density_pct']}%.",
                }
            )
        elif data["keyword_density_pct"] > 3.5:
            issues.append(
                {
                    "priority": "Medium",
                    "title": "Possible keyword stuffing",
                    "detail": f"Keyword density is {data['keyword_density_pct']}%.",
                }
            )

    if data["ai_quality"]["ai_risk_score"] >= 60:
        issues.append(
            {
                "priority": "High",
                "title": "Potential low-quality AI content pattern",
                "detail": f"AI-risk score is {data['ai_quality']['ai_risk_score']}/100.",
            }
        )
    elif data["ai_quality"]["ai_risk_score"] >= 40:
        issues.append(
            {
                "priority": "Medium",
                "title": "Some generic AI-style content patterns",
                "detail": f"AI-risk score is {data['ai_quality']['ai_risk_score']}/100.",
            }
        )

    if data["citation_readiness"] < 60:
        issues.append(
            {
                "priority": "High",
                "title": "Low AI citation readiness",
                "detail": f"Citation readiness is {data['citation_readiness']}/100.",
            }
        )
    elif data["citation_readiness"] < 75:
        issues.append(
            {
                "priority": "Medium",
                "title": "AI citation readiness can be improved",
                "detail": f"Citation readiness is {data['citation_readiness']}/100.",
            }
        )

    if data["freshness"]["age_days"] is not None and data["freshness"]["age_days"] > 365:
        issues.append(
            {
                "priority": "Medium",
                "title": "Content may be stale",
                "detail": f"Latest detected content date is {data['freshness']['age_days']} days old.",
            }
        )

    if data["schema"]["count"] == 0:
        issues.append(
            {
                "priority": "Low",
                "title": "No structured data found",
                "detail": "Add schema for stronger machine readability and AI extraction.",
            }
        )
    elif data["schema"]["invalid_count"] > 0:
        issues.append(
            {
                "priority": "Medium",
                "title": "Invalid structured data blocks",
                "detail": f"{data['schema']['invalid_count']} JSON-LD blocks failed parsing.",
            }
        )

    return sorted(issues, key=lambda item: PRIORITY_ORDER.get(item["priority"], 99))


def recommendations_from_issues(issues: list[dict[str, str]]) -> list[str]:
    mapping = {
        "Thin content for page intent": "Expand topical coverage with original examples, data, and direct answers to core user intent.",
        "Coverage depth below guideline": "Add missing subtopics and FAQs to satisfy search intent comprehensively.",
        "Missing author attribution": "Add an author byline and short bio with role and expertise.",
        "Weak expertise signals": "Show credentials, hands-on experience, certifications, or documented methodology.",
        "Limited trust/transparency links": "Add visible About, Contact, Privacy, Terms, and editorial policy links.",
        "Readability is difficult": "Shorten sentences, simplify phrasing, and break dense sections into scannable blocks.",
        "Focus keyword underused": "Integrate the focus phrase naturally in title/H1/introduction and relevant subheadings.",
        "Possible keyword stuffing": "Reduce repetitive phrase usage and replace with natural semantic variants.",
        "Potential low-quality AI content pattern": "Rewrite generic sections with concrete, first-hand specifics and unique insights.",
        "Some generic AI-style content patterns": "Add concrete numbers, examples, and source-backed claims to increase specificity.",
        "Low AI citation readiness": "Add answer-first summaries, fact-rich lists/tables, and explicit source citations.",
        "AI citation readiness can be improved": "Increase structured fact blocks and clarify entity/claim attribution.",
        "Content may be stale": "Refresh the page with updated data, examples, and a visible updated date.",
        "No structured data found": "Add relevant JSON-LD (Article, Organization, Product, etc.).",
        "Invalid structured data blocks": "Fix malformed JSON-LD and validate required properties.",
    }
    output: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        rec = mapping.get(issue["title"])
        if rec and rec not in seen:
            seen.add(rec)
            output.append(rec)
    if not output:
        output.append("Maintain current quality and continue regular freshness updates.")
    return output


def write_outputs(output_dir: Path, data: dict[str, Any], issues: list[dict[str, str]], recommendations: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "CONTENT-AUDIT-REPORT.md"
    plan_path = output_dir / "CONTENT-ACTION-PLAN.md"
    summary_path = output_dir / "SUMMARY.json"

    buckets = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for issue in issues:
        buckets[issue["priority"]].append(issue)

    eeat = data["eeat_factors"]
    issue_text = []
    for priority in ("Critical", "High", "Medium", "Low"):
        issue_text.append(f"### {priority}")
        if not buckets[priority]:
            issue_text.append("- None")
        else:
            for item in buckets[priority]:
                issue_text.append(f"- **{item['title']}**: {item['detail']}")

    rec_lines = [f"{i}. {rec}" for i, rec in enumerate(recommendations, start=1)]

    report = f"""# Content Quality & E-E-A-T Report

## Executive Summary

- URL: `{data['final_url']}`
- HTTP Status: `{data['status_code']}`
- Response Time: `{data['response_ms']} ms`
- Detected page type: `{data['page_type']}`
- Content Quality Score: **{data['content_quality_score']}/100**
- AI Citation Readiness: **{data['citation_readiness']}/100**
- AI Content Risk (lower is better): **{data['ai_quality']['ai_risk_score']}/100**

## E-E-A-T Breakdown

| Factor | Score | Key Signals |
|---|---|---|
| Experience | {eeat['experience']}/100 | Experience markers: {data['experience_markers']}, media: {data['media_count']}, fact points: {data['fact_points']} |
| Expertise | {eeat['expertise']}/100 | Author present: {data['author']['author_present']}, credentials: {data['author']['credentials_present']} |
| Authoritativeness | {eeat['authoritativeness']}/100 | External citations: {data['external_links']}, authority domains: {data['external_authority_count']} |
| Trustworthiness | {eeat['trustworthiness']}/100 | HTTPS: {data['https']}, trust links: {data['trust_links']}, freshness signal: {data['freshness']['latest_utc'] is not None} |

- Weighted E-E-A-T Total: **{data['eeat_total']}/100**

## Content Metrics

- Word count: {data['word_count']} (guideline floor: {data['word_floor']})
- Readability (Flesch): {data['readability']['flesch']}
- Grade level estimate: {data['readability']['grade']}
- Avg sentence length: {data['readability']['avg_sentence_words']} words
- H1 count: {data['h1_count']}
- Heading hierarchy valid: {data['heading_hierarchy_ok']}
- Heading skips found: {data['heading_skip_count']}
- Internal links: {data['internal_links']}
- External links: {data['external_links']}
- Schema blocks: {data['schema']['count']}
- Schema types: {", ".join(data['schema']['types']) if data['schema']['types'] else "None"}

## Freshness Signals

- Latest detected content date (UTC): {data['freshness']['latest_utc']}
- Age in days: {data['freshness']['age_days']}
- Date signals seen: {", ".join(data['freshness']['date_strings']) if data['freshness']['date_strings'] else "None"}

## AI Citation Readiness Signals

- Headings: {data['citation_signals']['heading_count']}
- List items: {data['citation_signals']['list_items']}
- Tables: {data['citation_signals']['table_count']}
- Fact points (numbers/%): {data['citation_signals']['fact_points']}
- External citations: {data['citation_signals']['external_citations']}
- Answer-first pattern: {data['citation_signals']['answer_first_pattern']}

## Issues Found

{chr(10).join(issue_text)}

## Recommendations

{chr(10).join(rec_lines)}
"""
    report_path.write_text(report, encoding="utf-8")

    action_lines = ["# Content SEO Action Plan", "", f"- Target: `{data['final_url']}`", ""]
    for priority in ("Critical", "High", "Medium", "Low"):
        action_lines.append(f"## {priority}")
        if not buckets[priority]:
            action_lines.append("- No actions in this tier.")
        else:
            for idx, item in enumerate(buckets[priority], start=1):
                action_lines.append(f"{idx}. {item['title']} - {item['detail']}")
        action_lines.append("")
    plan_path.write_text("\n".join(action_lines).strip() + "\n", encoding="utf-8")

    summary = {
        "url": data["final_url"],
        "content_quality_score": data["content_quality_score"],
        "eeat_total": data["eeat_total"],
        "eeat_factors": data["eeat_factors"],
        "citation_readiness": data["citation_readiness"],
        "ai_quality": data["ai_quality"],
        "issues": issues,
        "recommendations": recommendations,
        "signals": {
            "page_type": data["page_type"],
            "word_count": data["word_count"],
            "word_floor": data["word_floor"],
            "readability": data["readability"],
            "freshness": data["freshness"],
            "author": data["author"],
            "schema": data["schema"],
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run content quality and E-E-A-T audit for one URL.")
    parser.add_argument("url", help="Target page URL")
    parser.add_argument("--keyword", help="Optional focus keyword/phrase")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument("--output-dir", default="seo-content-output", help="Output directory")
    args = parser.parse_args()

    try:
        target = normalize_url(args.url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    if not is_public_target(target):
        print("Error: target URL resolves to non-public or invalid host")
        return 2

    fetched = fetch_page(target, args.timeout)
    if fetched["error"]:
        print(f"Error: failed to fetch page: {fetched['error']}")
        return 1
    if not fetched["text"]:
        print("Error: empty response body")
        return 1

    final_url = normalize_url(fetched["final_url"])
    soup = soup_of(fetched["text"])
    content_type = str((fetched["headers"] or {}).get("Content-Type", ""))
    is_html = "text/html" in content_type.lower() or "<html" in (fetched["text"] or "").lower()
    if not is_html:
        print("Error: target is not HTML content")
        return 1

    title = soup.title.get_text(" ", strip=True) if soup.title else None
    h1_tags = soup.find_all("h1")
    h1_text = h1_tags[0].get_text(" ", strip=True) if h1_tags else None
    main_text = extract_main_text(soup)
    words = tokenize(main_text)
    word_count = len(words)

    page_type = detect_page_type(final_url, title, h1_text)
    word_floor = WORD_FLOORS.get(page_type, WORD_FLOORS["generic_page"])
    readability = readability_metrics(main_text)

    links = extract_links(soup, final_url)
    schema = extract_schema_types(soup)
    author = extract_author_signals(soup, main_text)
    freshness = extract_freshness_signals(soup, fetched["headers"])

    hierarchy_ok, heading_skip_count, heading_skips = heading_hierarchy_ok(soup)
    keyword = args.keyword.lower().strip() if args.keyword else None
    keyword_density_pct = 0.0
    if keyword:
        occurrences = len(re.findall(rf"\b{re.escape(keyword)}\b", main_text.lower()))
        keyword_density_pct = round((occurrences / max(1, word_count)) * 100, 2)

    first_person_signals = len(re.findall(r"\b(i|we|our|my)\b", main_text.lower()))
    experience_markers = sum(main_text.lower().count(marker) for marker in EXPERIENCE_MARKERS)
    media_count = len(soup.find_all("img")) + len(soup.find_all("video"))
    fact_points = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", main_text))
    trust_links = sum(
        1
        for link in links["internal"]
        if any(marker in (urlparse(link).path or "").lower() for marker in TRUST_LINK_MARKERS)
    )

    eeat_signal_bundle = {
        "experience_markers": experience_markers,
        "media_count": media_count,
        "fact_points": fact_points,
        "first_person_signals": first_person_signals,
        "author_present": author["author_present"],
        "credentials_present": author["credentials_present"],
        "external_citations": len(links["external"]),
        "external_authority_count": links["external_authority_count"],
        "word_count": word_count,
        "internal_links": len(links["internal"]),
        "https": urlparse(final_url).scheme == "https",
        "trust_links": trust_links,
        "freshness_age_days": freshness["age_days"],
        "schema_count": schema["count"],
    }
    eeat_factors, eeat_total = score_eeat(eeat_signal_bundle)

    ai_quality = ai_quality_markers(main_text)
    citation_readiness, citation_signals = citation_readiness_score(
        soup=soup,
        text=main_text,
        links=links,
        schema=schema,
        has_clear_heading_hierarchy=hierarchy_ok,
    )

    data = {
        "status_code": fetched["status_code"],
        "response_ms": fetched["response_ms"],
        "final_url": final_url,
        "title": title,
        "h1_count": len(h1_tags),
        "has_single_h1": len(h1_tags) == 1,
        "heading_hierarchy_ok": hierarchy_ok,
        "heading_skip_count": heading_skip_count,
        "heading_skips": heading_skips,
        "page_type": page_type,
        "word_count": word_count,
        "word_floor": word_floor,
        "readability": readability,
        "keyword": keyword,
        "keyword_density_pct": keyword_density_pct,
        "internal_links": len(links["internal"]),
        "external_links": len(links["external"]),
        "external_authority_count": links["external_authority_count"],
        "experience_markers": experience_markers,
        "first_person_signals": first_person_signals,
        "media_count": media_count,
        "fact_points": fact_points,
        "trust_links": trust_links,
        "https": urlparse(final_url).scheme == "https",
        "schema": schema,
        "author": author,
        "freshness": freshness,
        "eeat_factors": eeat_factors,
        "eeat_total": eeat_total,
        "ai_quality": ai_quality,
        "citation_readiness": citation_readiness,
        "citation_signals": citation_signals,
    }
    data["content_quality_score"] = score_content_quality(data)

    issues = prioritize_issues(data)
    recommendations = recommendations_from_issues(issues)

    output_dir = Path(args.output_dir).resolve()
    write_outputs(output_dir, data, issues, recommendations)

    print(f"URL: {final_url}")
    print(f"Content quality score: {data['content_quality_score']}/100")
    print(f"E-E-A-T total: {eeat_total}/100")
    print(f"AI citation readiness: {citation_readiness}/100")
    print(f"Report: {output_dir / 'CONTENT-AUDIT-REPORT.md'}")
    print(f"Action plan: {output_dir / 'CONTENT-ACTION-PLAN.md'}")
    print(f"Summary: {output_dir / 'SUMMARY.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
