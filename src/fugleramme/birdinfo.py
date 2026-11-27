"""Cached English species information for birds recorded in Spain.

The iNaturalist taxa API supplies the scientific name, English name,
conservation status and Wikipedia link. Wikipedia supplies the short English
summary. Files are cached per scientific name under detector/data/species-info.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SPAIN_PLACE_ID = 6774
INATURALIST = "https://api.inaturalist.org/v1"
WIKIPEDIA = "https://en.wikipedia.org/api/rest_v1/page/summary"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
GALICIAN_WIKIPEDIA = "https://gl.wikipedia.org/api/rest_v1/page/summary"
SPANISH_WIKIPEDIA = "https://es.wikipedia.org/api/rest_v1/page/summary"
USER_AGENT = "Paxaros-do-xardin/1.0"
TIMEOUT = 10


def key_for(scientific_name: str, spanish_name: str = "") -> str:
    seed = (scientific_name.strip().lower() + "\n" + spanish_name.strip().lower()).encode()
    return hashlib.sha256(seed).hexdigest()[:16]


def _request(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode())


def _galician_article(wikipedia_url: str, scientific_name: str, common_name: str) -> dict[str, str]:
    """Find the Galician Wikipedia page linked from the English article."""
    title = urllib.parse.unquote(wikipedia_url.rsplit("/", 1)[-1]).replace("_", " ")
    for candidate in (title, common_name):
        if not candidate:
            continue
        query = urllib.parse.urlencode({
            "action": "query",
            "titles": candidate,
            "prop": "langlinks",
            "lllang": "gl|es",
            "format": "json",
            "formatversion": "2",
        })
        try:
            payload = _request(f"{WIKIPEDIA_API}?{query}")
            pages = payload.get("query", {}).get("pages", [])
            langlinks = pages[0].get("langlinks", []) if pages else []
            linked = next((row.get("title") for row in langlinks if row.get("lang") == "gl"), None)
            if linked:
                return _fetch_regional_article("gl", linked)
            linked = next((row.get("title") for row in langlinks if row.get("lang") == "es"), None)
            if linked:
                return _fetch_regional_article("es", linked)
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass

    try:
        query = urllib.parse.urlencode({
            "action": "query",
            "generator": "search",
            "gsrsearch": scientific_name,
            "gsrlimit": "5",
            "format": "json",
            "formatversion": "2",
        })
        payload = _request(f"https://gl.wikipedia.org/w/api.php?{query}")
        pages = payload.get("query", {}).get("pages", [])
        if pages:
            return _fetch_regional_article("gl", str(pages[0].get("title") or ""))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        pass
    return {}


def _fetch_regional_article(language: str, title: str) -> dict[str, str]:
    if not title:
        return {}
    base = GALICIAN_WIKIPEDIA if language == "gl" else SPANISH_WIKIPEDIA
    try:
        article = _request(f"{base}/{urllib.parse.quote(title, safe='')}")
        url = str(article.get("content_urls", {}).get("desktop", {}).get("page") or "")
        name_key = "common_name_gl" if language == "gl" else "common_name_es"
        description_key = "description_gl" if language == "gl" else "description_es"
        summary_key = "summary_gl" if language == "gl" else "summary_es"
        return {
            name_key: str(article.get("title") or title),
            description_key: str(article.get("description") or ""),
            summary_key: str(article.get("extract") or ""),
            "source_url": url,
            "source_language": language,
            "source_name": "Wikipedia galega" if language == "gl" else "Wikipedia en español",
        }
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return {}


def _iucn_status(statuses: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    iucn = next((row for row in statuses if row.get("authority") == "IUCN Red List"), None)
    if iucn is None:
        iucn = next((row for row in statuses if row.get("place") is None), None)
    if iucn is None:
        return None, None
    return str(iucn.get("status") or "") or None, str(iucn.get("url") or "") or None


def google_seo_url(spanish_name: str, scientific_name: str) -> str:
    term = spanish_name.strip() or scientific_name.strip()
    return "https://www.google.com/search?q=" + urllib.parse.quote(f"{term} SEO", safe="")


def fetch(scientific_name: str, spanish_name: str = "") -> dict[str, Any] | None:
    """Return English species information when iNaturalist finds the exact bird in Spain."""
    name = scientific_name.strip()
    if not name:
        return None

    query = urllib.parse.urlencode({"q": name, "rank": "species", "place_id": SPAIN_PLACE_ID, "per_page": 5})
    taxa = _request(f"{INATURALIST}/taxa?{query}").get("results", [])
    taxon = next(
        (row for row in taxa if str(row.get("name", "")).lower() == name.lower()),
        None,
    )
    if taxon is None:
        return None

    taxon_id = taxon.get("id")
    if taxon_id:
        try:
            details = _request(f"{INATURALIST}/taxa/{taxon_id}").get("results", [])
            if details:
                taxon = {**taxon, **details[0]}
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            log.warning("iNaturalist taxon details unavailable for %s", name)

    wikipedia_url = str(taxon.get("wikipedia_url") or "")
    summary = ""
    description = ""
    if wikipedia_url:
        page = urllib.parse.unquote(wikipedia_url.rsplit("/", 1)[-1])
        try:
            article = _request(f"{WIKIPEDIA}/{urllib.parse.quote(page, safe='')}")
            summary = str(article.get("extract") or "")
            description = str(article.get("description") or "")
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            log.warning("Wikipedia summary unavailable for %s", name)

    common_name = str(taxon.get("preferred_common_name") or "")
    galician = _galician_article(wikipedia_url, name, common_name)
    statuses = taxon.get("conservation_statuses", [])
    conservation, conservation_url = _iucn_status(statuses if isinstance(statuses, list) else [])
    return {
        "scientific_name": taxon.get("name", name),
        "common_name": taxon.get("preferred_common_name") or "",
        "description": description,
        "summary": summary,
        "conservation_status": conservation,
        "conservation_url": conservation_url,
        "sources": ["iNaturalist Taxa", "Wikipedia"],
        "google_seo_url": google_seo_url(spanish_name, name),
        "spanish_name": spanish_name,
        **galician,
        "spain_place_id": SPAIN_PLACE_ID,
    }


def lookup(scientific_name: str, cache_dir: Path, spanish_name: str = "") -> dict[str, Any] | None:
    """Fetch once, then serve the species record from a per-Pi cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key_for(scientific_name, spanish_name)}.json"
    try:
        record = json.loads(path.read_text())
        if isinstance(record, dict) and "source_url" in record:
            return record
    except (OSError, json.JSONDecodeError):
        pass

    try:
        record = fetch(scientific_name, spanish_name)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        log.warning("Species information unavailable for %s: %s", scientific_name, error)
        return None
    if record is not None:
        path.write_text(json.dumps(record, ensure_ascii=False))
    return record
