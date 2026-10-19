"""Recall extensions: Lithuanian/English lure words, derived forms, cross-label context,
multi-word joined affixes and reviewed one-edit aliases. Reserved synthetic names only."""
from __future__ import annotations

from pathlib import Path

import pytest

from hecavex_radar.brands import load_brand_registry, score_domain

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = load_brand_registry(ROOT / "data" / "brands-lt.json")


@pytest.mark.parametrize(
    ("domain", "brand"),
    [
        ("swedbank-grazinimas.example", "Swedbank"),  # Lithuanian lure word
        ("luminor-savitarna.example", "Luminor"),
        ("vinted-verification.example", "Vinted"),  # derived form of a reviewed word
        ("swedbank-prisijungimo.example", "Swedbank"),  # inflected form
        ("dpd-trackparcel.example", "DPD"),  # a reviewed word starting a compound
        ("swedbank-lt.example", "Swedbank"),  # market marker
        ("seb-lt.example", "SEB"),
        ("login.revolut.click", "Revolut"),  # lure word in another label
        ("revolut.secure-zone.example", "Revolut"),
        ("swedbankloginverify.example", "Swedbank"),  # several joined lure words
        ("secureloginrevolut.example", "Revolut"),
        ("dhl-zustellservice.example", "DHL"),  # lure words of multinational parcel kits
        ("dpd-doplata.example", "DPD"),
        ("vinted-seller.example", "Vinted"),  # marketplace kits
        ("lumnor-login.example", "Luminor"),  # one edit on a reviewed long alias
        ("revolutt-login.example", "Revolut"),
    ],
)
def test_recall_extension_admits(domain: str, brand: str) -> None:
    match = score_domain(domain, REGISTRY)
    assert match is not None, domain
    assert match.brand == brand
    assert match.confidence >= 80


@pytest.mark.parametrize(
    "domain",
    [
        "seblogin.example",  # short alias stays boundary-delimited
        "login.seb.example",  # short alias never takes cross-label context
        "revolution-login.example",  # substring is not a token
        "soda-pay.example",  # five-letter aliases are not fuzzed (sodra)
        "maxim-billing.example",  # six-letter aliases are not fuzzed (maxima)
        "policja-login.example",  # Polish police, not ePolicija
        "migracja-login.example",
        "electrum-wallet.example",  # Electrum Bitcoin wallet, not Elektrum
        "customer.portal.telia.net",  # lure in a subdomain of a brand-held name
        "sso.revolut.com.cdn.cloudflare.net",  # first-party CDN target
        "revolut24.example",  # digits alone are not a lure
        "confitelia.example",  # a truncated stem (confi- of confirm) is not a lure
        "mobilier-ergo-posturale.example",  # a five-letter shared stem (mobil-) is not a lure
        "eso-app.example",  # generic words do not qualify short aliases
        "order-bite.example",
        "telia-smartconnect.app.example",  # nor give cross-label context
        "smarti-info.example",  # "info" is too generic to be a lure word
        "vinted.lt.first-party-js.example",  # a market marker in another label is not context
        "vinted.example",  # bare alias label without context
        "vinted.unrelated.example",
    ],
)
def test_recall_extension_rejects(domain: str) -> None:
    assert score_domain(domain, REGISTRY) is None
