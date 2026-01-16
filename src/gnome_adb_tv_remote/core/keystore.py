"""
ADB RSA Key Generation and Storage.

This module handles the generation and storage of RSA keys for ADB authentication.
Keys are stored in XDG config directory and are compatible with the Android 
ADB protocol format.

The implementation avoids the `cryptography` library by using `rsa` and `pyasn1`
for key generation, making it lighter-weight for Flatpak distribution.
"""

from __future__ import annotations

import base64
import os
import socket
import struct
from dataclasses import dataclass
from pathlib import Path

import rsa
from pyasn1.codec.der import encoder as der_encoder
from pyasn1.type import univ


@dataclass(frozen=True)
class AdbKeyPaths:
    private_key: Path
    public_key: Path


def _config_dir(app_dir_name: str = "android-tv-remote") -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / app_dir_name
    return Path.home() / ".config" / app_dir_name


def get_adb_key_paths(app_dir_name: str = "android-tv-remote") -> AdbKeyPaths:
    base = _config_dir(app_dir_name) / "adb"
    return AdbKeyPaths(private_key=base / "adbkey", public_key=base / "adbkey.pub")


# ─────────────────────────────────────────────────────────────────────────────
# Custom ADB key generation using `rsa` + `pyasn1` packages.
# This avoids importing `adb_shell.auth.keygen` which requires `cryptography`.
# ─────────────────────────────────────────────────────────────────────────────

#: Size of an RSA modulus (2048 bits = 256 bytes)
_ANDROID_PUBKEY_MODULUS_SIZE = 2048 // 8

#: Size of the RSA modulus in 32-bit words
_ANDROID_PUBKEY_MODULUS_SIZE_WORDS = _ANDROID_PUBKEY_MODULUS_SIZE // 4

#: Struct format for Android's RSAPublicKey binary format
_ANDROID_RSAPUBLICKEY_STRUCT = (
    "<"  # Little-endian
    "L"  # uint32_t modulus_size_words
    "L"  # uint32_t n0inv
    f"{_ANDROID_PUBKEY_MODULUS_SIZE}s"  # uint8_t modulus[...]
    f"{_ANDROID_PUBKEY_MODULUS_SIZE}s"  # uint8_t rr[...]
    "L"  # uint32_t exponent
)


def _modinv(a: int, m: int) -> int:
    """Compute modular multiplicative inverse of a modulo m using extended Euclidean algorithm."""
    if m == 1:
        return 0
    m0, x0, x1 = m, 0, 1
    while a > 1:
        q = a // m
        m, a = a % m, m
        x0, x1 = x1 - q * x0, x0
    return x1 + m0 if x1 < 0 else x1


def _get_user_info() -> str:
    """Return ' user@hostname' string for the public key suffix."""
    try:
        username = os.getlogin()
    except (FileNotFoundError, OSError):
        username = "unknown"
    if not username:
        username = "unknown"

    hostname = socket.gethostname()
    if not hostname:
        hostname = "unknown"

    return f" {username}@{hostname}"


def _encode_android_pubkey(n: int, e: int) -> bytes:
    """Encode RSA public key (n, e) into Android's custom binary format."""
    # Compute n0inv = -1 / N[0] mod 2^32
    r32 = 1 << 32
    n0inv = n % r32
    n0inv = _modinv(n0inv, r32)
    n0inv = r32 - n0inv

    # Compute rr = (2^(modulus_size * 8))^2 mod N
    rr = 1 << (_ANDROID_PUBKEY_MODULUS_SIZE * 8)
    rr = (rr**2) % n

    return struct.pack(
        _ANDROID_RSAPUBLICKEY_STRUCT,
        _ANDROID_PUBKEY_MODULUS_SIZE_WORDS,
        n0inv,
        n.to_bytes(_ANDROID_PUBKEY_MODULUS_SIZE, "little"),
        rr.to_bytes(_ANDROID_PUBKEY_MODULUS_SIZE, "little"),
        e,
    )


def _wrap_pkcs1_to_pkcs8(pkcs1_der: bytes) -> bytes:
    """Wrap PKCS#1 DER-encoded private key in PKCS#8 envelope.

    PKCS#8 structure:
        SEQUENCE {
            INTEGER 0  (version)
            SEQUENCE { OID 1.2.840.113549.1.1.1, NULL }  (RSA algorithm)
            OCTET STRING { <PKCS#1 DER> }
        }
    """
    # RSA algorithm OID: 1.2.840.113549.1.1.1
    rsa_oid = univ.ObjectIdentifier((1, 2, 840, 113549, 1, 1, 1))

    # Algorithm identifier: SEQUENCE { OID, NULL }
    algo_id = univ.Sequence()
    algo_id.setComponentByPosition(0, rsa_oid)
    algo_id.setComponentByPosition(1, univ.Null())

    # PKCS#8 PrivateKeyInfo structure
    pkcs8 = univ.Sequence()
    pkcs8.setComponentByPosition(0, univ.Integer(0))  # version
    pkcs8.setComponentByPosition(1, algo_id)  # algorithm
    pkcs8.setComponentByPosition(2, univ.OctetString(pkcs1_der))  # privateKey

    return bytes(der_encoder.encode(pkcs8))


def _generate_adb_keypair(private_key_path: str) -> None:
    """Generate an ADB-compatible RSA 2048-bit keypair.

    - Private key: PKCS#8 PEM format (compatible with adb_shell.auth.sign_pythonrsa)
    - Public key: Android's custom binary format (base64 + user info)
    """
    # Generate RSA 2048-bit key pair
    pub_key, priv_key = rsa.newkeys(2048)

    # Export private key as PKCS#1 DER, then wrap in PKCS#8
    pkcs1_der = priv_key.save_pkcs1(format="DER")
    pkcs8_der = _wrap_pkcs1_to_pkcs8(pkcs1_der)

    # Write PKCS#8 PEM file
    pem_data = (
        b"-----BEGIN PRIVATE KEY-----\n"
        + base64.encodebytes(pkcs8_der)
        + b"-----END PRIVATE KEY-----\n"
    )
    with open(private_key_path, "wb") as f:
        f.write(pem_data)
    
    # Secure the private key file by restricting permissions to owner-only
    try:
        os.chmod(private_key_path, 0o600)
    except OSError:
        pass  # Best effort if filesystem doesn't support permissions

    # Write Android public key file
    android_pubkey = _encode_android_pubkey(pub_key.n, pub_key.e)
    with open(private_key_path + ".pub", "wb") as f:
        f.write(base64.b64encode(android_pubkey))
        f.write(_get_user_info().encode())


def ensure_adb_keys_exist(app_dir_name: str = "android-tv-remote") -> AdbKeyPaths:
    """Ensure ADB RSA keypair exists and return paths.

    Keys are stored inside the Flatpak sandbox under XDG config.
    """
    paths = get_adb_key_paths(app_dir_name)
    paths.private_key.parent.mkdir(parents=True, exist_ok=True)

    if paths.private_key.exists() and paths.public_key.exists():
        # Ensure private key is secure (0o600)
        try:
            current_mode = paths.private_key.stat().st_mode
            if (current_mode & 0o777) != 0o600:
                paths.private_key.chmod(0o600)
        except OSError:
            pass  # Best effort
        return paths

    # Generate new keypair using our custom implementation (no cryptography dep)
    _generate_adb_keypair(str(paths.private_key))
    return paths
