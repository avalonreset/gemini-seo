#!/usr/bin/env python3
"""Deterministic GEO analysis runner for seo-geo."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
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

CRAWLERS = [
    ("GPTBot", "OpenAI"),
    ("OAI-SearchBot", "OpenAI"),
    ("ChatGPT-User", "OpenAI"),
    ("ClaudeBot", "Anthropic"),
    ("PerplexityBot", "Perplexity"),
    ("CCBot", "Common Crawl"),
    ("anthropic-ai", "Anthropic"),
    ("Bytespider", "ByteDance"),
    ("cohere-ai", "Cohere"),
]
KEY_CRAWLERS = {"gptbot", "oai-searchbot", "chatgpt-user", "claudebot", "perplexitybot"}
PLATFORMS = {
    "Wikipedia": ["wikipedia.org", "wikidata.org"],
    "Reddit": ["reddit.com"],
    "YouTube": ["youtube.com", "youtu.be"],
    "LinkedIn": ["linkedin.com"],
}
MAX_LINK_SCAN = 5000
JSONLD_TYPE_RE = re.compile(r"application/ld\+json", re.IGNORECASE)
MAX_REDIRECT_HOPS = 10



def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))



def tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())



def normalize_url(raw: str) -> str:
    v = raw.strip()
    p = urlparse(v)
    if not p.scheme:
        v = f"https://{v}"
        p = urlparse(v)
    if p.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {p.scheme}")
    netloc = p.netloc or (p.hostname or "")
    path = p.path or "/"
    return urlunparse((p.scheme, netloc, path, "", p.query, ""))



def is_public_target(url: str) -> bool:
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for _, _, _, _, sockaddr in info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_multicast:
            continue
        return True
    return False



def canonical_host(host: str | None) -> str:
    h = (host or "").strip().lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h



def read_file(path: str) -> str:
    p = Path(path).resolve()
    if not p.exists():
        raise ValueError(f"File not found: {p}")
    return p.read_text(encoding="utf-8", errors="ignore")



def load_page(args: argparse.Namespace) -> tuple[str, str]:
    if bool(args.url) == bool(args.html_file):
        raise ValueError("Provide exactly one of --url or --html-file.")
    if args.url:
        target = normalize_url(args.url)
        if not is_public_target(target):
            raise ValueError("target URL resolves to non-public or invalid host")
        current_url = target
        redirects = 0
        while True:
            if not is_public_target(current_url):
                raise ValueError("redirected target URL resolves to non-public or invalid host")
            res = requests.get(current_url, headers=HEADERS, timeout=args.timeout, allow_redirects=False)
            if 300 <= res.status_code < 400:
                location = (res.headers.get("Location") or "").strip()
                if not location:
                    res.raise_for_status()
                    return res.text, normalize_url(current_url)
                if redirects >= MAX_REDIRECT_HOPS:
                    raise ValueError(f"Too many redirects (>{MAX_REDIRECT_HOPS})")
                next_url = normalize_url(urljoin(current_url, location))
                if not is_public_target(next_url):
                    raise ValueError("redirected target URL resolves to non-public or invalid host")
                current_url = next_url
                redirects += 1
                continue
            res.raise_for_status()
            return res.text, normalize_url(current_url)
    html = read_file(args.html_file)
    page_url = normalize_url(args.page_url) if args.page_url else "https://example.com/"
    return html, page_url



def fetch_text(url: str, timeout: int) -> tuple[str, int | None, str]:
    current_url = url
    redirects = 0
    try:
        while True:
            if not is_public_target(current_url):
                return "", None, current_url
            res = requests.get(current_url, headers=HEADERS, timeout=timeout, allow_redirects=False)
            if 300 <= res.status_code < 400:
                location = (res.headers.get("Location") or "").strip()
                if not location:
                    return "", res.status_code, current_url
                if redirects >= MAX_REDIRECT_HOPS:
                    return "", None, current_url
                try:
                    next_url = normalize_url(urljoin(current_url, location))
                except ValueError:
                    return "", None, current_url
                if not is_public_target(next_url):
                    return "", None, next_url
                current_url = next_url
                redirects += 1
                continue
            return (res.text if res.status_code < 400 else ""), res.status_code, current_url
    except requests.exceptions.RequestException:
        return "", None, current_url



def parse_robots(text: str) -> dict[str, list[tuple[str, str]]]:
    rules: dict[str, list[tuple[str, str]]] = {}
    agents: list[str] = []
    collecting_agents = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            agents = []
            collecting_agents = False
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            agent = v.lower()
            if not agent:
                continue
            if collecting_agents:
                if agent not in agents:
                    agents.append(agent)
            else:
                agents = [agent]
                collecting_agents = True
            if agent not in rules:
                rules[agent] = []
        elif k in {"allow", "disallow"}:
            collecting_agents = False
            for a in agents:
                rules.setdefault(a, []).append((k, v))
    return rules



def crawler_status(name: str, rules: dict[str, list[tuple[str, str]]]) -> tuple[str, str]:
    ex = rules.get(name.lower(), [])
    wc = rules.get("*", [])
    if not ex and not wc:
        return "Unknown", "No robots rules found"

    def has(entries: list[tuple[str, str]], kind: str, path: str) -> bool:
        return any(k == kind and v.strip() == path for k, v in entries)

    if has(ex, "disallow", "/") and not has(ex, "allow", "/"):
        return "Blocked", "Explicit Disallow /"
    if has(wc, "disallow", "/") and not has(ex, "allow", "/") and not has(wc, "allow", "/"):
        return "Blocked", "Wildcard Disallow /"
    if any(k == "disallow" and v.strip() and v.strip() != "/" for k, v in ex + wc):
        return "Partial", "Path-level disallow rules"
    return "Allowed", "No blocking rule detected"



def sameas_links(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for script in soup.find_all("script", attrs={"type": JSONLD_TYPE_RE}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack: list[Any] = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if k.lower() == "sameas":
                        vals = v if isinstance(v, list) else [v]
                        out.extend([x.strip() for x in vals if isinstance(x, str) and x.strip()])
                    else:
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
    return out



def brand_signals(soup: BeautifulSoup, page_url: str, brand: str | None) -> dict[str, Any]:
    page_host = canonical_host(urlparse(page_url).hostname)
    text = soup.get_text(" ", strip=True).lower()
    hrefs: set[str] = set()
    for a in soup.find_all("a", href=True):
        hrefs.add(urljoin(page_url, str(a.get("href") or "").strip()))
    for s in sameas_links(soup):
        hrefs.add(urljoin(page_url, s))

    rows: list[dict[str, Any]] = []
    hit = 0
    for platform, markers in PLATFORMS.items():
        ev = []
        for link in sorted(hrefs)[:MAX_LINK_SCAN]:
            p = urlparse(link)
            h = canonical_host(p.hostname)
            if p.scheme not in {"http", "https"} or not h or h == page_host:
                continue
            if any(h == m or h.endswith(f".{m}") for m in markers):
                ev.append(link)
        text_sig = any(m.split(".")[0] in text for m in markers)
        present = bool(ev) or text_sig
        if present:
            hit += 1
        rows.append({"platform": platform, "present": present, "evidence_urls": ev[:3]})

    mention = bool(brand and brand.strip() and brand.strip().lower() in text)
    strength = (hit / max(1, len(PLATFORMS))) * 100.0
    if mention:
        strength += 10.0
    return {
        "brand": brand or "",
        "brand_mention_on_page": mention,
        "platforms_present": hit,
        "platform_total": len(PLATFORMS),
        "strength_score": round(clamp(strength), 1),
        "rows": rows,
    }



def passage_windows(soup: BeautifulSoup) -> list[str]:
    root = soup.find("main") or soup.find("article") or soup.body or soup
    paras = [n.get_text(" ", strip=True) for n in root.find_all(["p", "li", "blockquote"])]
    paras = [p for p in paras if len(tok(p)) >= 18]
    out: list[str] = []
    seen: set[str] = set()
    for i in range(len(paras)):
        wc = 0
        buf: list[str] = []
        for j in range(i, min(len(paras), i + 4)):
            buf.append(paras[j])
            wc += len(tok(paras[j]))
            if wc < 90:
                continue
            if wc > 220:
                break
            txt = " ".join(buf)
            key = " ".join(tok(txt)[:60])
            if key and key not in seen:
                seen.add(key)
                out.append(txt)
    return out[:80]



def score_passage(text: str, keyword: str | None) -> dict[str, Any]:
    words = tok(text)
    wc = len(words)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    first = sents[0].lower() if sents else ""
    lower = text.lower()
    in_target = 134 <= wc <= 167
    direct = bool(re.search(r"\b(is|are|refers to|means|defined as)\b", first))
    data = bool(re.search(r"\b\d+(?:\.\d+)?%?\b", text))
    source = bool(re.search(r"\b(according to|study|report|research|source|official|data)\b", lower))
    kw = bool(keyword and keyword.lower() in lower)
    score = 20.0
    score += 30.0 if in_target else (14.0 if 110 <= wc <= 220 else 0.0)
    score += 16.0 if direct else 0.0
    score += 14.0 if data else 0.0
    score += 12.0 if source else 0.0
    score += 8.0 if kw else 0.0
    score += 6.0 if 2 <= len(sents) <= 8 else 0.0
    snippet = " ".join(sents[:2]).strip()
    if len(snippet) > 260:
        snippet = snippet[:257].rstrip() + "..."
    return {
        "score": round(clamp(score), 1),
        "word_count": wc,
        "in_target_range": in_target,
        "snippet": snippet,
    }



def citability(soup: BeautifulSoup, keyword: str | None) -> dict[str, Any]:
    windows = passage_windows(soup)
    rows = [score_passage(w, keyword) for w in windows]
    rows.sort(key=lambda r: r["score"], reverse=True)
    top = rows[:10]
    score = round(sum(r["score"] for r in top) / max(1, len(top)), 1)
    return {
        "score": score,
        "passage_count": len(rows),
        "optimal_block_count": sum(1 for r in rows if r["in_target_range"]),
        "top_passages": top,
    }



def structure_score(soup: BeautifulSoup) -> dict[str, Any]:
    hs = soup.find_all(re.compile(r"^h[1-6]$"))
    levels = [int(h.name[1]) for h in hs if h.name and len(h.name) == 2]
    jumps = sum(1 for a, b in zip(levels, levels[1:]) if b - a > 1)
    qh = sum(1 for h in hs if h.get_text(" ", strip=True).strip().endswith("?"))
    pwords = [len(tok(p.get_text(" ", strip=True))) for p in soup.find_all("p") if p.get_text(" ", strip=True)]
    avg = round(sum(pwords) / max(1, len(pwords)), 1)
    lists = len(soup.find_all(["ul", "ol"]))
    tables = len(soup.find_all("table"))
    score = 100.0
    if levels.count(1) != 1:
        score -= 10
    if levels.count(2) == 0:
        score -= 14
    score -= min(24, jumps * 7)
    if qh == 0:
        score -= 10
    if avg > 95:
        score -= 12
    elif avg > 70:
        score -= 6
    if lists == 0:
        score -= 8
    if tables == 0:
        score -= 6
    return {
        "score": round(clamp(score), 1),
        "h1_count": levels.count(1),
        "h2_count": levels.count(2),
        "heading_jump_count": jumps,
        "question_heading_count": qh,
        "avg_paragraph_words": avg,
        "list_count": lists,
        "table_count": tables,
    }



def multimodal_score(soup: BeautifulSoup) -> dict[str, Any]:
    imgs = len(soup.find_all("img"))
    videos = len(soup.find_all("video")) + sum(
        1
        for i in soup.find_all("iframe", src=True)
        if any(x in str(i.get("src") or "").lower() for x in ["youtube", "vimeo", "wistia", "loom"])
    )
    figures = len(soup.find_all("figure")) + len(soup.find_all(["svg", "canvas"]))
    inter = len(soup.find_all(["form", "input", "select", "textarea", "button"]))
    score = 20.0 + (35 if imgs else 0) + (10 if imgs >= 3 else 0) + (20 if videos else 0) + (10 if figures else 0) + (10 if inter else 0)
    return {
        "score": round(clamp(score), 1),
        "images": imgs,
        "videos": videos,
        "figures": figures,
        "interactive_elements": inter,
    }



def authority_score(soup: BeautifulSoup, page_url: str, brands: dict[str, Any]) -> dict[str, Any]:
    host = canonical_host(urlparse(page_url).hostname)
    text = soup.get_text(" ", strip=True).lower()
    has_author = bool(
        soup.find("meta", attrs={"name": re.compile("^author$", re.I)})
        or soup.select_one("[class*=author i], [id*=author i], [itemprop=author], [rel=author]")
    )
    has_date = bool(
        soup.find("meta", attrs={"property": re.compile("published|modified", re.I)})
        or soup.find("time")
        or re.search(r"\b(updated|published)\b", text)
    )
    src = 0
    ext = 0
    for a in soup.find_all("a", href=True):
        link = urljoin(page_url, str(a.get("href") or "").strip())
        p = urlparse(link)
        h = canonical_host(p.hostname)
        if p.scheme not in {"http", "https"} or not h or h == host:
            continue
        ext += 1
        if h.endswith(".gov") or h.endswith(".edu") or any(m in h for m in ["wikipedia.org", "nih.gov", "who.int", "data.gov"]):
            src += 1
    score = 25.0 + (20 if has_author else 0) + (15 if has_date else 0) + (20 if src >= 3 else (12 if src >= 1 else 0))
    score += 6 if ext >= 6 else 0
    score += min(25, brands["platforms_present"] * 6.5)
    return {
        "score": round(clamp(score), 1),
        "has_author_signal": has_author,
        "has_date_signal": has_date,
        "source_links": src,
        "external_links": ext,
        "brand_platforms_present": brands["platforms_present"],
    }



def llms_info(args: argparse.Namespace, page_url: str) -> dict[str, Any]:
    if args.llms_file:
        txt, sc, src, mode = read_file(args.llms_file), None, f"file://{Path(args.llms_file).resolve()}", "file"
    elif args.html_file and not args.page_url:
        return {
            "source": "none",
            "url": "",
            "status_code": None,
            "present": False,
            "quality": {"quality_score": 0.0, "section_count": 0, "link_count": 0},
        }
    else:
        base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
        url = f"{base}/llms.txt"
        txt, sc, src = fetch_text(url, args.timeout)
        mode = "http"
    present = bool(txt.strip())
    lines = [x for x in txt.splitlines() if x.strip()]
    q = 0.0
    q += 25 if any(l.startswith("# ") for l in lines) else 0
    q += 15 if any(l.startswith(">") for l in lines) else 0
    q += min(25.0, sum(1 for l in lines if l.startswith("## ")) * 10.0)
    q += min(20.0, len(re.findall(r"\[[^\]]+\]\([^)]+\)", txt)) * 5.0)
    q += min(15.0, sum(1 for l in lines if l.startswith("- ")) * 2.5)
    return {
        "source": mode,
        "url": src,
        "status_code": sc,
        "present": present,
        "quality": {
            "quality_score": round(clamp(q), 1),
            "section_count": sum(1 for l in lines if l.startswith("## ")),
            "link_count": len(re.findall(r"\[[^\]]+\]\([^)]+\)", txt)),
        },
    }



def robots_info(args: argparse.Namespace, page_url: str) -> dict[str, Any]:
    if args.robots_file:
        txt, sc, src, mode = read_file(args.robots_file), None, f"file://{Path(args.robots_file).resolve()}", "file"
    elif args.html_file and not args.page_url:
        rows = [{"crawler": c, "owner": owner, "status": "Unknown", "reason": "No robots source provided in local mode"} for c, owner in CRAWLERS]
        return {"source": "none", "url": "", "status_code": None, "crawlers": rows}
    else:
        base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
        url = f"{base}/robots.txt"
        txt, sc, src = fetch_text(url, args.timeout)
        mode = "http"
    rules = parse_robots(txt)
    rows = []
    for c, owner in CRAWLERS:
        st, why = crawler_status(c, rules)
        rows.append({"crawler": c, "owner": owner, "status": st, "reason": why})
    return {"source": mode, "url": src, "status_code": sc, "crawlers": rows}



def ssr_score(soup: BeautifulSoup) -> dict[str, Any]:
    text = (soup.body or soup).get_text(" ", strip=True)
    words = len(tok(text))
    scripts = len(soup.find_all("script"))
    root_mark = 1 if soup.select_one("#root, #app, [data-reactroot], [id*=__next], [ng-version]") else 0
    score = 50.0 + min(35.0, words / 12.0) - min(30.0, scripts * 1.2) - (14.0 if root_mark and words < 220 else 0.0)
    score = clamp(score)
    return {
        "score": round(score, 1),
        "likely_ssr": score >= 60.0,
        "word_count": words,
        "script_count": scripts,
        "root_marker_count": root_mark,
    }



def technical_score(soup: BeautifulSoup, robots: dict[str, Any], llms: dict[str, Any]) -> dict[str, Any]:
    ssr = ssr_score(soup)
    sel = [r for r in robots["crawlers"] if r["crawler"].lower() in KEY_CRAWLERS] or robots["crawlers"]
    pts = 0.0
    for r in sel:
        pts += 1.0 if r["status"] == "Allowed" else (0.6 if r["status"] == "Partial" else (0.4 if r["status"] == "Unknown" else 0.0))
    crawler = (pts / max(1, len(sel))) * 100.0
    llms_score_val = llms["quality"]["quality_score"] if llms["present"] else 0.0
    html = str(soup).lower()
    rsl_present = bool(soup.find("link", attrs={"rel": re.compile("license", re.I)}) or "rsl 1.0" in html or "really simple licensing" in html)
    rsl = 100.0 if rsl_present else 20.0
    score = ssr["score"] * 0.35 + crawler * 0.35 + llms_score_val * 0.2 + rsl * 0.1
    return {
        "score": round(clamp(score), 1),
        "ssr": ssr,
        "crawler_score": round(clamp(crawler), 1),
        "llms_score": round(clamp(llms_score_val), 1),
        "rsl": {"present": rsl_present, "score": rsl},
    }



def schema_types(soup: BeautifulSoup) -> list[str]:
    out: set[str] = set()
    for script in soup.find_all("script", attrs={"type": JSONLD_TYPE_RE}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack: list[Any] = [payload]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                for k, v in n.items():
                    if k == "@type":
                        vals = v if isinstance(v, list) else [v]
                        for it in vals:
                            if isinstance(it, str) and it.strip():
                                out.add(it.strip().split("/")[-1].split("#")[-1])
                    else:
                        stack.append(v)
            elif isinstance(n, list):
                stack.extend(n)
    return sorted(out)



def platform_scores(criteria: dict[str, float], brands: dict[str, Any]) -> dict[str, float]:
    p = {r["platform"]: r["present"] for r in brands["rows"]}
    w = 100.0 if p.get("Wikipedia") else 35.0
    r = 100.0 if p.get("Reddit") else 35.0
    y = 100.0 if p.get("YouTube") else 35.0
    l = 100.0 if p.get("LinkedIn") else 35.0
    g = criteria["citability"] * 0.4 + criteria["structure"] * 0.25 + criteria["technical"] * 0.2 + criteria["authority"] * 0.15
    c = criteria["authority"] * 0.3 + criteria["technical"] * 0.25 + criteria["citability"] * 0.2 + (w * 0.5 + r * 0.25 + l * 0.25) * 0.25
    ppx = criteria["citability"] * 0.3 + criteria["authority"] * 0.2 + criteria["technical"] * 0.2 + (r * 0.5 + w * 0.3 + y * 0.2) * 0.3
    b = criteria["structure"] * 0.25 + criteria["technical"] * 0.35 + criteria["authority"] * 0.2 + criteria["citability"] * 0.2
    return {
        "Google AI Overviews": round(clamp(g), 1),
        "ChatGPT Search": round(clamp(c), 1),
        "Perplexity": round(clamp(ppx), 1),
        "Bing Copilot": round(clamp(b), 1),
    }



def top_changes(criteria: dict[str, float], robots: dict[str, Any], llms: dict[str, Any], auth: dict[str, Any], struct: dict[str, Any], tech: dict[str, Any], cite: dict[str, Any], brands: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, Any]] = []
    blocked = [r for r in robots["crawlers"] if r["crawler"].lower() in KEY_CRAWLERS and r["status"] == "Blocked"]
    if blocked:
        out.append({"priority": "Critical", "action": "Allow key AI crawlers in robots.txt.", "why": f"{len(blocked)} key crawlers blocked."})
    if not llms["present"]:
        out.append({"priority": "High", "action": "Add /llms.txt with key pages and core facts.", "why": "No llms.txt detected."})
    if not tech["ssr"]["likely_ssr"]:
        out.append({"priority": "High", "action": "Serve key content server-side for crawler readability.", "why": "CSR-heavy render signature detected."})
    if cite["optimal_block_count"] == 0:
        out.append({"priority": "High", "action": "Create 134-167 word self-contained answer blocks.", "why": "No optimal citability blocks found."})
    if struct["question_heading_count"] == 0:
        out.append({"priority": "Medium", "action": "Add question-style H2/H3 headings.", "why": "No question-based headings detected."})
    if not auth["has_author_signal"] or not auth["has_date_signal"]:
        out.append({"priority": "Medium", "action": "Add author credentials and publication/update dates.", "why": "Authority metadata incomplete."})
    if brands["platforms_present"] <= 1:
        out.append({"priority": "Medium", "action": "Increase off-site entity presence on key citation platforms.", "why": "Weak cross-platform brand signals."})
    if criteria["multimodal"] < 65:
        out.append({"priority": "Low", "action": "Add visuals/tables/video for stronger multimodal selection signals.", "why": "Limited multimodal assets."})
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    out.sort(key=lambda x: order.get(x["priority"], 99))
    return out[:5]



def schema_recs(found: list[str], auth: dict[str, Any], struct: dict[str, Any]) -> list[str]:
    n = {x.lower() for x in found}
    recs: list[str] = []
    if "organization" not in n and "localbusiness" not in n:
        recs.append("Add Organization or LocalBusiness schema with sameAs links.")
    if "person" not in n and auth["has_author_signal"]:
        recs.append("Add Person schema for bylined authors.")
    if "article" not in n and "blogposting" not in n:
        recs.append("Add Article or BlogPosting schema with datePublished/dateModified.")
    if "faqpage" not in n and struct["question_heading_count"] > 0:
        recs.append("Consider FAQPage schema only where policy-eligible.")
    if "website" not in n:
        recs.append("Add WebSite schema with SearchAction.")
    return recs or ["Schema coverage is generally healthy; keep data fresh and linked."]



def reformat_suggestions(cite: dict[str, Any], keyword: str | None) -> list[str]:
    out = []
    weak = [r for r in cite["top_passages"] if r["score"] < 70][:3]
    for i, r in enumerate(weak, 1):
        msg = f"Passage {i} ({r['word_count']} words): rewrite with a direct first-sentence answer"
        if keyword:
            msg += f", include '{keyword}' naturally"
        msg += ", and add one sourced numeric fact."
        out.append(msg)
    if cite["optimal_block_count"] == 0:
        out.append("Add at least one 134-167 word answer block under a query-style heading.")
    return out or ["Passage formatting already looks strong; keep claims sourced and current."]



def render_report(path: Path, page_url: str, geo: float, criteria: dict[str, float], plats: dict[str, float], robots: dict[str, Any], llms: dict[str, Any], brands: dict[str, Any], cite: dict[str, Any], tech: dict[str, Any], changes: list[dict[str, str]], schema: list[str], refmt: list[str]) -> None:
    crawler_rows = "\n".join(f"| {r['crawler']} | {r['owner']} | {r['status']} | {r['reason']} |" for r in robots["crawlers"]) or "| None | - | - | - |"
    plat_rows = "\n".join(f"| {k} | {v} |" for k, v in plats.items())
    brand_rows = "\n".join(f"| {r['platform']} | {'Yes' if r['present'] else 'No'} | {', '.join(r['evidence_urls']) if r['evidence_urls'] else '-'} |" for r in brands["rows"]) or "| None | - | - |"
    top_pass = "\n".join(f"- **Score {r['score']} / {r['word_count']} words**: {r['snippet']}" for r in cite["top_passages"][:5]) or "- No qualifying passages."
    change_rows = "\n".join(f"{i}. [{c['priority']}] {c['action']} ({c['why']})" for i, c in enumerate(changes, 1)) or "1. No critical changes identified."

    md = f"""# GEO Analysis

## 1. GEO Readiness Score
- URL: `{page_url}`
- GEO readiness: **{geo}/100**

| Criteria | Weight | Score |
|---|---:|---:|
| Citability | 25% | {criteria['citability']} |
| Structural readability | 20% | {criteria['structure']} |
| Multi-modal content | 15% | {criteria['multimodal']} |
| Authority and brand signals | 20% | {criteria['authority']} |
| Technical accessibility | 20% | {criteria['technical']} |

## 2. Platform Breakdown
| Platform | Score |
|---|---:|
{plat_rows}

## 3. AI Crawler Access Status
- robots.txt source: `{robots['source']}`
- robots.txt URL: `{robots['url']}`
- robots.txt HTTP status: {robots['status_code'] if robots['status_code'] is not None else 'n/a'}

| Crawler | Owner | Status | Reason |
|---|---|---|---|
{crawler_rows}

## 4. llms.txt Status
- Present: **{'Yes' if llms['present'] else 'No'}**
- Source: `{llms['source']}`
- URL: `{llms['url']}`
- HTTP status: {llms['status_code'] if llms['status_code'] is not None else 'n/a'}
- Quality score: **{llms['quality']['quality_score']}/100**
- Sections: {llms['quality']['section_count']}
- Markdown links: {llms['quality']['link_count']}

## 5. Brand Mention Analysis
- Brand mention on page: {'Yes' if brands['brand_mention_on_page'] else 'No'}
- Platform coverage: {brands['platforms_present']}/{brands['platform_total']}
- Brand signal strength: **{brands['strength_score']}/100**

| Platform | Present | Evidence |
|---|---|---|
{brand_rows}

## 6. Passage-Level Citability
- Citability score: **{criteria['citability']}/100**
- Candidate passages analyzed: {cite['passage_count']}
- Optimal 134-167 word blocks: {cite['optimal_block_count']}

Top passage samples:
{top_pass}

## 7. Server-Side Rendering Check
- SSR likelihood: **{'Likely SSR' if tech['ssr']['likely_ssr'] else 'Likely CSR-heavy'}**
- SSR score: {tech['ssr']['score']}/100
- Visible text words: {tech['ssr']['word_count']}
- Script tags: {tech['ssr']['script_count']}
- Root app marker count: {tech['ssr']['root_marker_count']}

## 8. Top 5 Highest-Impact Changes
{change_rows}

## 9. Schema Recommendations
{chr(10).join(f'- {x}' for x in schema)}

## 10. Content Reformatting Suggestions
{chr(10).join(f'- {x}' for x in refmt)}
"""
    path.write_text(md, encoding="utf-8")



def run(args: argparse.Namespace) -> int:
    try:
        html, page_url = load_page(args)
    except requests.exceptions.RequestException as exc:
        print(f"Error: failed to fetch target: {exc}")
        return 1
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    soup = BeautifulSoup(html, "lxml")
    brand = args.brand.strip() if args.brand else ""
    keyword = args.keyword.strip() if args.keyword else ""

    try:
        robots = robots_info(args, page_url)
        llms = llms_info(args, page_url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    cite = citability(soup, keyword or None)
    struct = structure_score(soup)
    multi = multimodal_score(soup)
    brands = brand_signals(soup, page_url, brand or None)
    auth = authority_score(soup, page_url, brands)
    tech = technical_score(soup, robots, llms)

    criteria = {
        "citability": cite["score"],
        "structure": struct["score"],
        "multimodal": multi["score"],
        "authority": auth["score"],
        "technical": tech["score"],
    }
    geo = round(clamp(criteria["citability"] * 0.25 + criteria["structure"] * 0.20 + criteria["multimodal"] * 0.15 + criteria["authority"] * 0.20 + criteria["technical"] * 0.20), 1)

    plats = platform_scores(criteria, brands)
    changes = top_changes(criteria, robots, llms, auth, struct, tech, cite, brands)
    found_schema = schema_types(soup)
    s_recs = schema_recs(found_schema, auth, struct)
    reform = reformat_suggestions(cite, keyword or None)

    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rep = out / "GEO-ANALYSIS.md"
    summ = out / "SUMMARY.json"
    cstat = out / "CRAWLER-STATUS.json"
    bstat = out / "BRAND-SIGNALS.json"

    render_report(rep, page_url, geo, criteria, plats, robots, llms, brands, cite, tech, changes, s_recs, reform)
    cstat.write_text(json.dumps({"robots_source": robots["source"], "robots_url": robots["url"], "status_code": robots["status_code"], "rows": robots["crawlers"]}, indent=2), encoding="utf-8")
    bstat.write_text(json.dumps({"brand": brands["brand"], "brand_mention_on_page": brands["brand_mention_on_page"], "strength_score": brands["strength_score"], "rows": brands["rows"]}, indent=2), encoding="utf-8")
    summary = {
        "url": page_url,
        "geo_score": geo,
        "criteria_scores": criteria,
        "platform_scores": plats,
        "citability": {"passage_count": cite["passage_count"], "optimal_block_count": cite["optimal_block_count"], "top_passages": cite["top_passages"][:10]},
        "structure": struct,
        "multimodal": multi,
        "authority": auth,
        "technical": tech,
        "llms": llms,
        "schema_types_detected": found_schema,
        "top_changes": changes,
        "artifact_paths": {"report": str(rep), "summary": str(summ), "crawler_status": str(cstat), "brand_signals": str(bstat)},
    }
    summ.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"URL: {page_url}")
    print(f"GEO score: {geo}/100")
    print(f"Criteria scores: citability={criteria['citability']}, structure={criteria['structure']}, multimodal={criteria['multimodal']}, authority={criteria['authority']}, technical={criteria['technical']}")
    print(f"Report: {rep}")
    print(f"Summary: {summ}")
    print(f"Crawler status: {cstat}")
    print(f"Brand signals: {bstat}")
    return 0



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run deterministic GEO analysis.")
    p.add_argument("--url", default="", help="Target URL to analyze")
    p.add_argument("--html-file", default="", help="Local HTML file path")
    p.add_argument("--page-url", default="", help="Canonical page URL for --html-file mode")
    p.add_argument("--brand", default="", help="Brand name for mention signal")
    p.add_argument("--keyword", default="", help="Optional keyword/topic for passage scoring")
    p.add_argument("--robots-file", default="", help="Optional local robots.txt path")
    p.add_argument("--llms-file", default="", help="Optional local llms.txt path")
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--output-dir", default="seo-geo-output")
    return p



def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())


