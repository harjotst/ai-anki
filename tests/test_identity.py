"""Who the caller is, proved rather than asserted.

The seam here is the JWKS *fetch*, and nothing else — the same choice as
`ClaudeScript`, which fakes the Anthropic HTTP transport and leaves the real SDK
in the loop. These tests generate a real RSA keypair, publish a real JWKS
document, and sign real tokens with it. Every line of verification runs for
real, so a mistake in audience checking or expiry handling fails here rather
than in front of somebody's decks.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import identity

ISSUER = "https://project.supabase.co/auth/v1"
AUDIENCE = "authenticated"
SUBJECT = "3f2b1c88-0000-4000-8000-abcdefabcdef"


class Keyring:
    """A signing key and the JWKS document that publishes its public half."""

    def __init__(self, kid: str = "key-1"):
        self.kid = kid
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.fetches = 0

    def document(self) -> dict:
        return {
            "keys": [
                {
                    **jwt.algorithms.RSAAlgorithm.to_jwk(
                        self._private.public_key(), as_dict=True
                    ),
                    "kid": self.kid,
                    "use": "sig",
                    "alg": "RS256",
                }
            ]
        }

    def fetch(self) -> dict:
        self.fetches += 1
        return self.document()

    def token(self, **claims) -> str:
        now = int(time.time())
        payload = {
            "sub": SUBJECT,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + 3600,
            "email": "someone@example.com",
            **claims,
        }
        return jwt.encode(
            payload,
            self._private,
            algorithm="RS256",
            headers={"kid": claims.pop("kid", self.kid)},
        )


@pytest.fixture
def keys():
    return Keyring()


@pytest.fixture
def verifier(keys):
    return identity.Verifier(issuer=ISSUER, audience=AUDIENCE, fetch_keys=keys.fetch)


def test_a_token_this_issuer_signed_names_its_subject(verifier, keys):
    claims = verifier.verify(keys.token())

    assert claims["sub"] == SUBJECT
    assert claims["email"] == "someone@example.com"


def test_an_expired_token_is_refused(verifier, keys):
    with pytest.raises(identity.NotAuthenticated):
        verifier.verify(keys.token(exp=int(time.time()) - 1))


def test_a_token_signed_by_some_other_key_is_refused(verifier):
    """The whole point of asymmetric verification.

    A stolen shared secret mints valid tokens for every user; a stolen public
    key mints nothing, which is why this reads JWKS rather than an HS256 secret.
    """
    impostor = Keyring(kid="key-1")  # same kid, different private half

    with pytest.raises(identity.NotAuthenticated):
        verifier.verify(impostor.token())


def test_a_token_meant_for_a_different_audience_is_refused(verifier, keys):
    with pytest.raises(identity.NotAuthenticated):
        verifier.verify(keys.token(aud="some-other-service"))


def test_a_token_from_a_different_issuer_is_refused(verifier, keys):
    with pytest.raises(identity.NotAuthenticated):
        verifier.verify(keys.token(iss="https://attacker.example/auth/v1"))


def test_nonsense_is_refused_the_same_way_as_a_bad_signature(verifier):
    for rubbish in ["", "not.a.token", "a.b.c"]:
        with pytest.raises(identity.NotAuthenticated):
            verifier.verify(rubbish)


def test_the_key_set_is_fetched_once_and_then_remembered(verifier, keys):
    """Fetching per request would put the auth provider on the critical path of
    every call, and take the application down with it."""
    for _ in range(5):
        verifier.verify(keys.token())

    assert keys.fetches == 1


def test_an_unfamiliar_key_id_triggers_exactly_one_refetch(keys):
    """Key rotation must not need a deploy, and must not become a way to make
    the application fetch on demand."""
    rotated = Keyring(kid="key-2")
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        # The provider has rotated: the published set no longer contains key-1.
        return rotated.document() if calls["n"] > 1 else keys.document()

    verifier = identity.Verifier(issuer=ISSUER, audience=AUDIENCE, fetch_keys=fetch)
    verifier.verify(keys.token())  # warms the cache with key-1

    assert verifier.verify(rotated.token())["sub"] == SUBJECT
    assert calls["n"] == 2, "one refetch, not one per verification"

    # And a token whose kid is in neither set does not refetch again on every
    # attempt, which would hand anyone a way to hammer the auth provider.
    stranger = Keyring(kid="key-3")
    for _ in range(3):
        with pytest.raises(identity.NotAuthenticated):
            verifier.verify(stranger.token())
    assert calls["n"] == 3, "one refetch for the unknown kid, then cached"
