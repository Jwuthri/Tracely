"""Credential classifier: ingest keys must never be mistaken for JWTs and vice-versa."""

from __future__ import annotations

from tracely.auth.classify import looks_like_jwt


def test_ingest_keys_are_not_jwts():
    assert looks_like_jwt("tracely_dev_key") is False
    assert looks_like_jwt("tk_abc123-_DEF") is False  # our minted keys are dot-free


def test_well_formed_jwt():
    assert looks_like_jwt("aaa.bbb.ccc") is True


def test_unsigned_or_alg_none_rejected():
    assert looks_like_jwt("aaa.bbb.") is False  # empty signature segment
    assert looks_like_jwt("aaa..ccc") is False  # empty payload segment


def test_wrong_segment_count():
    assert looks_like_jwt("aaa.bbb") is False
    assert looks_like_jwt("aaaa") is False
    assert looks_like_jwt("a.b.c.d") is False


def test_non_base64url_chars():
    assert looks_like_jwt("aa!.bbb.ccc") is False
    assert looks_like_jwt("aa+.bb/.cc=") is False  # base64 (not url-safe) padding/chars
