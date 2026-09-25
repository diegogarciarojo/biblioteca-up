"""Keep the dynv6 A record pointed at this server's current public IPv4."""
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CONFIG_DIR = Path("/etc/biblioteca-up")


def main():
    zone = (CONFIG_DIR / "dynv6.zone").read_text(encoding="utf-8").strip()
    token = (CONFIG_DIR / "dynv6.token").read_text(encoding="utf-8").strip()
    if not zone or not token:
        raise SystemExit("Falta la zona o el token de dynv6.")
    query = urlencode({"zone": zone, "token": token, "ipv4": "auto"})
    request = Request(
        f"https://ipv4.dynv6.com/api/update?{query}",
        headers={"User-Agent": "biblioteca-up-dynv6-updater/1"},
    )
    try:
        with urlopen(request, timeout=25) as response:
            result = response.read(512).decode("utf-8", errors="replace").lower()
    except (HTTPError, URLError):
        raise SystemExit("No se pudo contactar o autenticar con dynv6.") from None
    if any(word in result for word in ("error", "invalid", "badauth", "not authorized", "nohost", "abuse")):
        raise SystemExit("dynv6 rechazó la actualización; revisa el token de la zona.")
    print(f"Actualización de IPv4 enviada para {zone}.")


if __name__ == "__main__":
    main()
