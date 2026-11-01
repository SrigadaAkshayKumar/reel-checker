"""AdMob rewarded-ad server-side verification (SSV).

After a user finishes a rewarded ad, AdMob calls our callback URL with a GET whose
query string ends in `&signature=...&key_id=...`. The signature is ECDSA (P-256,
SHA-256, DER, web-safe base64) over everything before `&signature=`, made with one
of Google's keys published at `admob_keys_url`. Only a verified callback for one of
our own ad units grants a credit, and each transaction id counts once, so credits
cannot be faked by calling the URL, replaying a callback, or pointing another
AdMob account's ad unit at us.
https://developers.google.com/admob/android/ssv
"""
from __future__ import annotations

import base64
from urllib.parse import parse_qs

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ..core.config import Settings
from ..core.http import Http, HttpError
from ..db.store import Store

KEYS_CACHE = "admob:verifier-keys"


class SsvError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _keys(settings: Settings, http: Http, store: Store, refresh: bool) -> dict[str, str]:
    cached = None if refresh else store.cache_get(KEYS_CACHE, ttl_days=1)
    if cached is None:
        try:
            body = http.get_json(settings.admob_keys_url)
        except HttpError:
            raise SsvError(503, "keys_unavailable", "Could not load AdMob's verification keys.") from None
        cached = {str(k["keyId"]): k["pem"] for k in body.get("keys", []) if "keyId" in k and "pem" in k}
        store.cache_put(KEYS_CACHE, cached)
    return cached


def ad_unit_allowed(settings: Settings, ad_unit: str) -> bool:
    """Configured ids may be full ('ca-app-pub-123/456') or bare ('456'); callbacks carry the bare one."""
    allowed = {u.strip().rsplit("/", 1)[-1] for u in settings.admob_ad_unit_ids.split(",") if u.strip()}
    return bool(ad_unit) and ad_unit in allowed


def verify(raw_query: str, settings: Settings, http: Http, store: Store) -> dict[str, str]:
    """Check the signature on a raw callback query string. Returns the parameters."""
    if "&signature=" not in raw_query:
        raise SsvError(400, "unsigned", "Missing signature.")
    message, signed_part = raw_query.split("&signature=", 1)
    tail = parse_qs("signature=" + signed_part)
    signature, key_id = tail.get("signature", [""])[0], tail.get("key_id", [""])[0]
    if not signature or not key_id:
        raise SsvError(400, "unsigned", "Missing signature or key id.")
    keys = _keys(settings, http, store, refresh=False)
    if key_id not in keys:  # Google rotates keys: refetch once
        keys = _keys(settings, http, store, refresh=True)
    if key_id not in keys:
        raise SsvError(403, "bad_signature", "Unknown verification key.")
    try:
        public = serialization.load_pem_public_key(keys[key_id].encode())
        if not isinstance(public, ec.EllipticCurvePublicKey):
            raise SsvError(403, "bad_signature", "Unexpected key type.")
        public.verify(_b64(signature), message.encode(), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise SsvError(403, "bad_signature", "Signature does not verify.") from None
    return {k: v[0] for k, v in parse_qs(message, keep_blank_values=True).items()}


def handle_callback(raw_query: str, settings: Settings, http: Http, store: Store) -> str:
    """Verify, then grant one credit. Returns granted | duplicate | unknown_user | capped | ignored."""
    params = verify(raw_query, settings, http, store)
    if not ad_unit_allowed(settings, params.get("ad_unit", "")):
        raise SsvError(403, "wrong_ad_unit", "Not one of this app's ad units.")
    transaction = params.get("transaction_id", "")
    if not transaction:
        return "ignored"  # AdMob's "verify URL" test callback carries no transaction
    return store.ssv_grant(transaction, params.get("user_id", ""), settings.app_max_ad_credits)
