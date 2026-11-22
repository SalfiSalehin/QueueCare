"""Which address the rate limiter attributes a request to, with and without trusted proxies in front of the API."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.ratelimit import get_client_ip


def _request(forwarded: str | None, peer: str = "10.0.0.9"):
    headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


def _settings(trust: bool, hops: int = 1):
    return SimpleNamespace(trust_proxy_headers=trust, trusted_proxy_hops=hops)


def test_forwarded_header_is_ignored_unless_proxies_are_trusted():
    assert get_client_ip(_request("203.0.113.5"), _settings(False)) == "10.0.0.9"
    assert get_client_ip(_request(None), _settings(False)) == "10.0.0.9"


def test_one_trusted_proxy_uses_the_rightmost_entry_and_ignores_forged_ones():
    # A client sent "1.2.3.4"; our proxy appended the address it actually saw.
    assert get_client_ip(_request("1.2.3.4, 203.0.113.5"), _settings(True, 1)) == "203.0.113.5"
    assert get_client_ip(_request("203.0.113.5"), _settings(True, 1)) == "203.0.113.5"


def test_two_trusted_proxies_use_the_visitor_not_the_first_proxy():
    # visitor -> Vercel -> Render -> API: the chain ends "<visitor>, <Vercel>"; a forged value sits further left.
    assert get_client_ip(_request("198.51.100.7, 203.0.113.5"), _settings(True, 2)) == "198.51.100.7"
    assert get_client_ip(_request("9.9.9.9, 198.51.100.7, 203.0.113.5"), _settings(True, 2)) == "198.51.100.7"


def test_a_chain_shorter_than_configured_falls_back_to_the_peer():
    assert get_client_ip(_request("203.0.113.5", peer="10.0.0.9"), _settings(True, 2)) == "10.0.0.9"


def test_garbage_is_not_an_address():
    assert get_client_ip(_request("not-an-ip, still-not"), _settings(True, 1)) is None
    assert get_client_ip(_request("2001:db8::1, 2001:db8::2"), _settings(True, 1)) == "2001:db8::2"
