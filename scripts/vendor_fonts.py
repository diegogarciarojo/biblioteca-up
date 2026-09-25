"""Download the pinned Google Fonts used by the interface."""
from pathlib import Path
from urllib.request import urlopen


DEST = Path(__file__).resolve().parents[1] / "static" / "fonts"
SOURCES = {
    "dm-sans-latin.woff2": "https://fonts.gstatic.com/s/dmsans/v17/rP2Yp2ywxg089UriI5-g4vlH9VoD8Cmcqbu0-K4.woff2",
    "dm-sans-latin-ext.woff2": "https://fonts.gstatic.com/s/dmsans/v17/rP2Yp2ywxg089UriI5-g4vlH9VoD8Cmcqbu6-K6h9Q.woff2",
    "dm-serif-normal-latin.woff2": "https://fonts.gstatic.com/s/dmserifdisplay/v17/-nFnOHM81r4j6k0gjAW3mujVU2B2G_Bx0g.woff2",
    "dm-serif-normal-latin-ext.woff2": "https://fonts.gstatic.com/s/dmserifdisplay/v17/-nFnOHM81r4j6k0gjAW3mujVU2B2G_5x0ujy.woff2",
    "dm-serif-italic-latin.woff2": "https://fonts.gstatic.com/s/dmserifdisplay/v17/-nFhOHM81r4j6k0gjAW3mujVU2B2G_VB0PD2.woff2",
    "dm-serif-italic-latin-ext.woff2": "https://fonts.gstatic.com/s/dmserifdisplay/v17/-nFhOHM81r4j6k0gjAW3mujVU2B2G_VB3vD212k.woff2",
    "LICENSE-DM-Sans.txt": "https://raw.githubusercontent.com/google/fonts/main/ofl/dmsans/OFL.txt",
    "LICENSE-DM-Serif-Display.txt": "https://raw.githubusercontent.com/google/fonts/main/ofl/dmserifdisplay/OFL.txt",
}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        with urlopen(url, timeout=30) as response:
            (DEST / name).write_bytes(response.read())
        print(name)


if __name__ == "__main__":
    main()
