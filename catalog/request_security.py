"""Validation and storage of student-submitted viewer links.

Viewer links can contain short-lived access tokens. Keep them out of logs,
responses, and plaintext database columns.
"""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError


def validate_viewer_url(url):
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise ValidationError("Pega un enlace válido del visor.")
    if url != url.strip() or any(ord(char) < 32 for char in url):
        raise ValidationError("Pega un enlace válido del visor.")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=30)
    except ValueError as exc:
        raise ValidationError("Pega un enlace válido del visor.") from exc

    allowed_hosts = {host.lower() for host in settings.EBOOKS724_ALLOWED_HOSTS}
    if (
        parsed.scheme.lower() != "https"
        or hostname not in allowed_hosts
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.lower().endswith("/visorbook.aspx")
        or "\\" in parsed.path
    ):
        raise ValidationError("Solo se aceptan enlaces HTTPS del visor Ebooks 7-24.")

    for parameter in ("i", "t"):
        values = query.get(parameter, [])
        if len(values) != 1 or not values[0] or len(values[0]) > 1024:
            raise ValidationError("El enlace del visor debe incluir los parámetros i y t.")
        if any(not char.isprintable() or char.isspace() for char in values[0]):
            raise ValidationError("El enlace del visor contiene parámetros inválidos.")
    return url


def _fernet():
    digest = hashlib.sha256(
        b"biblioteca-up-viewer-url-v1\0" + settings.SECRET_KEY.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_viewer_url(url):
    validated = validate_viewer_url(url)
    return _fernet().encrypt(validated.encode("utf-8")).decode("ascii")


def decrypt_viewer_url(ciphertext):
    try:
        url = _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, AttributeError, ValueError) as exc:
        raise ValueError("El enlace del visor no se puede descifrar.") from exc
    return validate_viewer_url(url)
