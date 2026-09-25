"""Copy the pinned official PDF.js distribution into static/pdfjs."""
import io
import tarfile
import urllib.request
from pathlib import Path


VERSION = "6.3.289"
URL = f"https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-{VERSION}.tgz"
DEST = Path(__file__).resolve().parents[1] / "static" / "pdfjs"
FILES = {
    "package/LICENSE": "LICENSE",
    "package/build/pdf.mjs": "pdf.mjs",
    "package/build/pdf.worker.mjs": "pdf.worker.mjs",
}


def main():
    with urllib.request.urlopen(URL, timeout=60) as response:
        archive = tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")
    for member in archive.getmembers():
        if not member.isfile():
            continue
        relative = FILES.get(member.name)
        if relative is None:
            for folder in ("cmaps", "standard_fonts"):
                prefix = f"package/{folder}/"
                if member.name.startswith(prefix):
                    relative = f"{folder}/{member.name[len(prefix):]}"
                    break
        if relative is None:
            continue
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.extractfile(member) as source, target.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
    print(f"PDF.js {VERSION} instalado en {DEST}")


if __name__ == "__main__":
    main()
