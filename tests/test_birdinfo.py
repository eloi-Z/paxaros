from __future__ import annotations

import json

from fugleramme import birdinfo


def test_fetch_uses_spain_place_and_caches(monkeypatch, tmp_path):
    calls = []

    def request(url):
        calls.append(url)
        if "/taxa?" in url:
            assert "place_id=6774" in url
            return {
                "results": [{
                    "id": 12716,
                    "name": "Turdus merula",
                    "preferred_common_name": "Eurasian Blackbird",
                    "wikipedia_url": "https://en.wikipedia.org/wiki/Common_blackbird",
                    "conservation_statuses": [{
                        "authority": "IUCN Red List",
                        "status": "LC",
                        "url": "https://example.test/iucn",
                    }],
                }]
            }
        if "/taxa/12716" in url:
            return {
                "results": [{
                    "id": 12716,
                    "name": "Turdus merula",
                    "preferred_common_name": "Eurasian Blackbird",
                    "wikipedia_url": "https://en.wikipedia.org/wiki/Common_blackbird",
                    "conservation_statuses": [{
                        "authority": "IUCN Red List",
                        "status": "LC",
                        "url": "https://example.test/iucn",
                    }],
                }]
            }
        return {
            "description": "Thrush native to Europe",
            "extract": "The common blackbird is a species of true thrush.",
        }

    monkeypatch.setattr(birdinfo, "_request", request)
    cache = tmp_path / "species-info"

    first = birdinfo.lookup("Turdus merula", cache)
    second = birdinfo.lookup("Turdus merula", cache)

    assert first == second
    assert first["spain_place_id"] == 6774
    assert first["conservation_status"] == "LC"
    assert any("/taxa?" in url for url in calls)


def test_fetch_rejects_a_taxon_not_returned_for_spain(monkeypatch):
    monkeypatch.setattr(birdinfo, "_request", lambda _url: {"results": [{"name": "Other bird"}]})
    assert birdinfo.fetch("Turdus merula") is None
