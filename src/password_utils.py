"""Password hashing utilities — no FastAPI/DB dependency so both src/auth.py and
src/db.py (which needs to hash the bootstrap director password) can import this
without any risk of circular imports."""
import hashlib
import hmac
import os
import binascii

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex). Pass salt=None to generate a fresh random salt
    (new account); pass the stored salt back in to verify an existing password."""
    if salt is None:
        salt = binascii.hexlify(os.urandom(16)).decode("ascii")
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return binascii.hexlify(pwd_hash).decode("ascii"), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    computed_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(computed_hash, stored_hash)
