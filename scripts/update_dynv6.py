"""Update a dynv6 zone's A record without exposing its token in logs."""

import ipaddress
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CONFIG_DIR = Path("/etc/biblioteca-up")
USER_AGENT = {"User-Agent": "biblioteca-up-dynv6-updater/2"}


def public_ipv4():
    with urlopen(Request("https://api.ipify.org", headers=USER_AGENT), timeout=10) as response:
        address = response.read(64).decode("ascii").strip()
    parsed = ipaddress.ip_address(address)
    if not isinstance(parsed, ipaddress.IPv4Address) or not parsed.is_global:
        raise ValueError("No se detectó una IPv4 pública.")
    return address


def main(ipv4=None):
    zone = (CONFIG_DIR / "dynv6.zone").read_text(encoding="utf-8").strip()
    token = (CONFIG_DIR / "dynv6.token").read_text(encoding="utf-8").strip()
    if not zone or not token:
        print("Falta la zona o el token de dynv6.", file=sys.stderr)
        return 2

    try:
        ipv4 = ipv4 or public_ipv4()
        address = ipaddress.ip_address(ipv4)
        if not isinstance(address, ipaddress.IPv4Address) or not address.is_global:
            raise ValueError("No se detectó una IPv4 pública.")
    except (OSError, URLError, ValueError):
        print("No se pudo detectar la IPv4 pública; se intentará de nuevo más tarde.", file=sys.stderr)
        return 1

    query = urlencode({"zone": zone, "token": token, "ipv4": str(address)})
    request = Request(f"https://dynv6.com/api/update?{query}", headers=USER_AGENT)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=10) as response:
                result = response.read(512).decode("utf-8", errors="replace").lower()
        except HTTPError as error:
            if error.code in (401, 403):
                print("dynv6 rechazó el token HTTP de la zona.", file=sys.stderr)
                return 2
        except (OSError, URLError):
            pass
        else:
            if any(word in result for word in ("badauth", "not authorized", "invalid token", "nohost")):
                print("dynv6 rechazó el token o el nombre de la zona.", file=sys.stderr)
                return 2
            if "error" not in result and "abuse" not in result:
                print(f"IPv4 actualizada en dynv6 para {zone}.")
                return 0
        if attempt < 2:
            time.sleep(2)

    print("dynv6 no respondió tras varios intentos; el temporizador volverá a probar.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) == 2 else None))
