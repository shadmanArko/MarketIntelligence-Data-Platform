"""Fixture tests: real responses saved once; parsers are tested against them so a platform change shows up as
a failing test with a clear diff."""

import json
from copy import deepcopy
from pathlib import Path

from mip.connectors.google_maps import Place, safe, strip_tokens
from mip.connectors.lieferando import RestaurantListing, split_restaurant
from mip.connectors.web_crawl import canonical, extract
from mip.connectors.wolt import VenueListing, split_item

FX = Path(__file__).parent / "fixtures"


def _merge(stable: dict, variant: dict) -> dict:
    out = deepcopy(stable)
    for k, v in variant.items():
        if k == "venue":
            out.setdefault("venue", {}).update(v)
        elif k not in ("venue_id", "section"):
            out[k] = v
    return out


def test_wolt_split_is_lossless_and_valid():
    for item in json.loads((FX / "wolt" / "list_items.json").read_text()):
        stable, variant = split_item(item)
        VenueListing.model_validate(stable)
        assert "estimate" not in stable["venue"] and "sorting" not in stable
        assert _merge(stable, variant) == item


def test_lieferando_split_is_lossless_and_valid():
    for rest in json.loads((FX / "lieferando" / "restaurants.json").read_text()):
        stable, variant = split_restaurant(rest)
        RestaurantListing.model_validate(stable)
        assert "deliveryCost" not in stable
        merged = {**stable, **{k: v for k, v in variant.items() if k != "id"}}
        assert merged == rest


def test_google_place_fields_at_known_positions():
    payload = json.loads((FX / "google_maps" / "place.json").read_text())
    Place.model_validate(payload)
    e = payload["entry"]
    assert safe(e, 11) == "Imren Grill"
    assert 52.3 < safe(e, 9, 2) < 52.7 and 13.0 < safe(e, 9, 3) < 13.8
    assert safe(e, 10).startswith("0x")
    assert isinstance(safe(e, 13), list)


def test_google_strip_tokens_removes_request_ids_only():
    entry = ["2ahUKEwjTxumgmJyXAxWDVfEDHf7AGcUQ8BcoFXoECAQQKQ", "Imren Grill", [None, ",AOvVaw2mo6MSq,,x"]]
    stable, tokens = strip_tokens(entry)
    assert stable == ["~", "Imren Grill", [None, "~"]]
    assert len(tokens) == 2


def test_web_extract_finds_schema_org_socials_and_ordering():
    html = (FX / "web_crawl" / "page.html").read_text()
    out = extract(html, "https://imren-grill.de/")
    assert out["social_links"] == {"instagram": ["imren.grill"]}          # share buttons ignored
    assert "lieferando" in out["ordering_providers"]
    types = [e.get("@type") for e in out["structured"]["json-ld"]]
    assert "Restaurant" in types
    assert "Döner" in (out["main_text"] or "")
    assert out["lang_attr"] == "de"


def test_canonical_url_drops_tracking():
    assert canonical("HTTPS://Example.de//karte/?utm_source=x&a=1#top") == "https://example.de/karte/?a=1"
