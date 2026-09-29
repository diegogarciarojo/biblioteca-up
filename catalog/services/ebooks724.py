"""Export an authenticated Ebooks724 viewer with Chromium's PDF engine.

The page rendering, cache validation, and final assembly are adapted from the
provided ``descargar_libro_local.py``. This module accepts only a validated
viewer URL and runs in an isolated headless browser owned by the VPS.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import TYPE_CHECKING, Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from catalog.request_security import validate_viewer_url

if TYPE_CHECKING:
    from playwright.sync_api import Page

VERSION = "chromium-pdf-1"
LOG = logging.getLogger(__name__)
PAGE_SELECTOR = "#page-container .pf"
DISK_RESERVE_BYTES = 256 * 1024 * 1024


class ExportError(Exception):
    """A safe, token-free failure message suitable for a job status."""


def browser_environment() -> dict[str, str]:
    """Pass OS runtime paths to Chromium without Django or OAuth secrets."""
    names = (
        "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "TZ",
        "SYSTEMROOT", "WINDIR", "USERPROFILE", "LOCALAPPDATA",
    )
    return {name: os.environ[name] for name in names if name in os.environ}


def provider_route_guard(permitted_host: str, timeout_ms: int):
    """Check redirect destinations before following them, including assets.

    Playwright's normal route continuation intercepts only the first request
    of an HTTP redirect chain. Fetch each step without automatic redirects and
    fulfill the browser request only after every destination is approved.
    """
    def permitted(url: str) -> bool:
        try:
            parts = urlsplit(url)
            return (
                parts.scheme == "https" and parts.hostname == permitted_host
                and parts.port in (None, 443)
                and parts.username is None and parts.password is None
            )
        except ValueError:
            return False

    def guard(route) -> None:
        target = route.request.url
        deadline = time.monotonic() + timeout_ms / 1000
        if not permitted(target):
            route.abort()
            return
        response = None
        try:
            for _ in range(6):
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining <= 0:
                    route.abort()
                    return
                response = route.fetch(url=target, max_redirects=0, timeout=remaining)
                if 300 <= response.status < 400:
                    location = response.headers.get("location")
                    destination = urljoin(target, location) if location else ""
                    response.dispose()
                    response = None
                    if not permitted(destination):
                        route.abort()
                        return
                    target = destination
                    continue
                route.fulfill(response=response)
                return
            route.abort()
        except Exception:
            # APIRequest errors can include viewer session tokens.
            route.abort()
        finally:
            if response is not None:
                response.dispose()

    return guard

# El DOM interior y sus estilos permanecen intactos. Se eliminan solamente
# los márgenes y controles externos que no forman parte de la hoja del libro.
PREPARE_PAGE_JS = r"""() => {
  const sheets = [...document.querySelectorAll('#page-container .pf')]
    .filter(e => e.getBoundingClientRect().width > 0 &&
                 e.getBoundingClientRect().height > 0);
  if (sheets.length !== 1) throw Error('Se esperaba exactamente una hoja visible');
  const pf = sheets[0];
  const rootStyle = getComputedStyle(pf);
  if (rootStyle.transform !== 'none' &&
      !new DOMMatrixReadOnly(rootStyle.transform).isIdentity)
    throw Error('La hoja tiene una transformación exterior; requiere inspección');
  const keep = new Set();
  for (let e = pf; e; e = e.parentElement) keep.add(e);
  for (const e of keep) {
    if (e === pf) continue;
    for (const child of [...e.children]) {
      if (!keep.has(child) && !['STYLE','LINK','SCRIPT','HEAD'].includes(child.tagName))
        child.style.setProperty('display', 'none', 'important');
    }
    for (const node of [...e.childNodes]) {
      if (node.nodeType === Node.TEXT_NODE) node.textContent = '';
    }
    const values = {margin:'0', padding:'0', border:'0', position:'static',
      transform:'none', zoom:'1', overflow:'visible', width:'auto', height:'auto',
      'min-width':'0', 'min-height':'0', 'max-width':'none', 'max-height':'none',
      display:'block'};
    for (const [name, value] of Object.entries(values))
      e.style.setProperty(name, value, 'important');
  }
  for (const [name,value] of Object.entries({margin:'0', left:'0', top:'0',
      right:'auto', bottom:'auto', position:'relative', 'box-shadow':'none',
      'break-inside':'avoid', 'break-after':'auto', 'break-before':'auto'}))
    pf.style.setProperty(name, value, 'important');
  window.scrollTo(0,0);
  const r = pf.getBoundingClientRect();
  if (Math.abs(r.x) > .1 || Math.abs(r.y) > .1)
    throw Error('No se pudo alinear la hoja al origen');
  const style = document.createElement('style');
  style.textContent = `@page { size: ${r.width}px ${r.height}px; margin: 0; }
    html, body { width:${r.width}px !important; height:${r.height}px !important; }
    #page-container .pf { overflow:hidden !important; }
    * { -webkit-print-color-adjust:exact !important; print-color-adjust:exact !important; }`;
  document.head.appendChild(style);
  return {width:r.width, height:r.height};
}"""

WAIT_RESOURCES_JS = r"""async (timeoutMs) => {
  const pf = document.querySelector('#page-container .pf');
  let timer;
  const ready = async () => {
    // Fuerza el cálculo de estilos antes de esperar las fuentes utilizadas.
    pf.getBoundingClientRect();
    await document.fonts.ready;
    // Algunos subconjuntos defectuosos del visor solo se asignan a espacios.
    // Bloquear únicamente si afectan a texto real de esta hoja.
    const familiesWithText = new Set();
    const walker = document.createTreeWalker(pf, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!/\S/u.test(node.data) || !node.parentElement) continue;
      for (const family of getComputedStyle(node.parentElement).fontFamily.split(','))
        familiesWithText.add(family.trim().replace(/^['"]|['"]$/g, ''));
    }
    const failed = [...document.fonts].filter(f => f.status === 'error' &&
      familiesWithText.has(f.family.trim().replace(/^['"]|['"]$/g, '')));
    if (failed.length)
      throw Error('Fuentes de texto sin cargar: ' + failed.map(f => f.family).join(', '));
    await Promise.all([...pf.querySelectorAll('img')].map(async img => {
      if (!img.complete) await new Promise((resolve,reject) => {
        img.addEventListener('load', resolve, {once:true});
        img.addEventListener('error', () => reject(Error('Imagen incompleta')), {once:true});
      });
      if (!img.naturalWidth) throw Error('Imagen sin contenido');
      await img.decode();
    }));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  };
  try {
    await Promise.race([ready(), new Promise((_,reject) => {
      timer = setTimeout(() => reject(Error('Recursos sin terminar de cargar')), timeoutMs);
    })]);
  } finally { clearTimeout(timer); }
}"""


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(path.parent).free < len(data) + DISK_RESERVE_BYTES:
        raise ExportError("No hay espacio suficiente para guardar el libro.")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Metadatos inválidos: {path.name}")
    return value


def book_identity(viewer_url: str) -> dict:
    parts = urlsplit(viewer_url)
    query = parse_qs(parts.query)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError("Se requiere una URL HTTP(S) del visor")
    if not re.search(r"/visorBook\.aspx$", parts.path, re.I):
        raise ValueError("La URL no corresponde a visorBook.aspx")
    book = query.get("i", [""])[0]
    if not book:
        raise ValueError("La URL no contiene el identificador i del libro")
    return {"origin": f"{parts.scheme}://{parts.netloc.lower()}",
            "path": parts.path.lower(), "book": book}


def direct_page_url(viewer_url: str, number: int) -> str:
    book_identity(viewer_url)
    parts = urlsplit(viewer_url)
    query = parse_qs(parts.query)
    if not query.get("t", [""])[0]:
        raise ValueError("La URL no contiene el parámetro de sesión t")
    query.update(p=[str(number)], z=["1"])
    path = parts.path.rsplit("/", 1)[0] + "/VisorPage.aspx"
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query, doseq=True), ""))


def pdf_info(data: bytes, expected_size: tuple[float, float] | None = None) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data), strict=True)
    if len(reader.pages) != 1:
        raise ValueError(f"La exportación produjo {len(reader.pages)} hojas en vez de una")
    page = reader.pages[0]
    size = (float(page.mediabox.width), float(page.mediabox.height))
    if not all(math.isfinite(v) and v > 0 for v in size):
        raise ValueError("Dimensiones PDF inválidas")
    if expected_size and any(abs(a - b * .75) > 1 for a, b in zip(size, expected_size)):
        raise ValueError("Chromium cambió el tamaño esperado de la hoja")
    if page.get_contents() is None:
        raise ValueError("PDF sin contenido")
    return {"width_pt": size[0], "height_pt": size[1],
            "sha256": hashlib.sha256(data).hexdigest()}


def initialize_cache(cache: Path, identity: dict) -> None:
    manifest = cache / "manifest.json"
    expected = {"version": VERSION, "book": identity}
    if manifest.exists():
        if read_json(manifest) != expected:
            raise ValueError("La caché pertenece a otro libro o motor. Elige otra carpeta")
    elif cache.exists() and any(cache.iterdir()):
        raise ValueError("La carpeta no es una caché vacía o compatible con este motor")
    else:
        write_json(manifest, expected)
    (cache / "pages").mkdir(exist_ok=True)


def cached_page(cache: Path, number: int, visual_required: bool = False) -> bool:
    path = cache / "pages" / f"page-{number:06d}.pdf"
    try:
        meta = read_json(path.with_suffix(".json"))
        if meta.get("version") != VERSION or meta.get("number") != number:
            return False
        if visual_required and not meta.get("visual", {}).get("passed"):
            return False
        info = pdf_info(path.read_bytes())
        return all(meta.get(k) == v for k, v in info.items())
    except (OSError, ValueError, TypeError, KeyError):
        return False
    except Exception:
        # Los lectores PDF pueden lanzar excepciones propias ante un archivo truncado.
        return False


def verify_visual(pdf: bytes, screenshot: bytes) -> dict:
    """Compara dos renderizadores; tolera antialiasing, rechaza desplazamientos grandes.

    Es una alarma cuantitativa, no una demostración de equivalencia semántica.
    """
    import pypdfium2 as pdfium
    from PIL import Image, ImageChops, ImageFilter, ImageStat
    with pdfium.PdfDocument(pdf) as document:
        page = document[0]
        bitmap = page.render(scale=96 / 72)
        try:
            rendered = bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
            page.close()
    reference = Image.open(io.BytesIO(screenshot)).convert("RGB")
    if abs(rendered.width - reference.width) > 2 or abs(rendered.height - reference.height) > 2:
        raise ValueError("La imagen del PDF y la hoja tienen dimensiones distintas")
    rendered = rendered.resize(reference.size)
    difference = ImageChops.difference(
        reference.filter(ImageFilter.GaussianBlur(1)),
        rendered.filter(ImageFilter.GaussianBlur(1))).convert("L")
    histogram = difference.histogram()
    changed = sum(histogram[41:]) / (reference.width * reference.height)
    mean = ImageStat.Stat(difference).mean[0]
    result = {"passed": mean <= 4 and changed <= .025,
              "mean_difference": round(mean, 4), "changed_fraction": round(changed, 6)}
    if not result["passed"]:
        raise ValueError(f"El PDF difiere de la vista del navegador: {result}")
    return result


def render_page(page: Page, visual: bool = False, timeout_ms: int = 30000) -> tuple[bytes, dict]:
    page.emulate_media(media="screen")
    page.wait_for_selector(PAGE_SELECTOR, state="visible", timeout=timeout_ms)
    page.evaluate(WAIT_RESOURCES_JS, timeout_ms)
    reference = None
    if visual:
        # Se usa únicamente como control de calidad; el PDF sigue siendo nativo.
        # Capturar ANTES de normalizar permite detectar cambios de maquetación.
        reference = page.locator(PAGE_SELECTOR).screenshot(scale="css", timeout=timeout_ms)
    size = page.evaluate(PREPARE_PAGE_JS)
    page.evaluate(WAIT_RESOURCES_JS, timeout_ms)
    data = page.pdf(width=f"{size['width']}px", height=f"{size['height']}px",
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                    print_background=True, display_header_footer=False,
                    prefer_css_page_size=True, scale=1)
    info = pdf_info(data, (size["width"], size["height"]))
    if reference:
        info["visual"] = verify_visual(data, reference)
    return data, info


def export_pages(page: Page, viewer_url: str, numbers: list[int], cache: Path,
                 visual: bool, attempts: int, timeout_ms: int,
                 progress: Callable[[int, int], None], max_cache_bytes: int) -> list[int]:
    failed = []
    completed = 0
    cache_bytes = 0
    consecutive_failures = 0
    for number in numbers:
        if cached_page(cache, number, visual):
            LOG.info("[%s] caché verificada", number)
            cache_bytes += (cache / "pages" / f"page-{number:06d}.pdf").stat().st_size
            if cache_bytes > max_cache_bytes:
                raise ExportError("El libro supera el límite de tamaño permitido.")
            completed += 1
            consecutive_failures = 0
            progress(completed, len(numbers))
            continue
        for attempt in range(1, attempts + 1):
            try:
                target = direct_page_url(viewer_url, number)
                response = page.goto(target, wait_until="commit", timeout=timeout_ms)
                if response is None or not response.ok:
                    if response is not None and response.status in (401, 403):
                        raise ExportError("La sesión del visor ha expirado.")
                    raise ValueError("Respuesta HTTP incompleta o fallida")
                actual = urlsplit(page.url)
                wanted = urlsplit(target)
                if (actual.scheme, actual.netloc, actual.path.lower(), parse_qs(actual.query).get("p")) != (
                        wanted.scheme, wanted.netloc, wanted.path.lower(), [str(number)]):
                    raise ExportError("La sesión del visor ha expirado.")
                data, info = render_page(page, visual, timeout_ms)
                if cache_bytes + len(data) > max_cache_bytes:
                    raise ExportError("El libro supera el límite de tamaño permitido.")
                path = cache / "pages" / f"page-{number:06d}.pdf"
                atomic_write(path, data)
                write_json(path.with_suffix(".json"), dict(info, version=VERSION, number=number))
                cache_bytes += len(data)
                completed += 1
                consecutive_failures = 0
                progress(completed, len(numbers))
                LOG.info("[%s] PDF guardado%s", number, " y comparado visualmente" if visual else "")
                break
            except ExportError:
                raise
            except Exception as error:
                # Browser exception messages can contain the viewer's session token.
                LOG.warning("[%s] intento %s/%s: %s", number, attempt,
                            attempts, type(error).__name__)
                if attempt == attempts:
                    failed.append(number)
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        raise ExportError("La sesión del visor dejó de responder.") from error
                else:
                    page.wait_for_timeout(min(attempt * 1500, 5000))
    return failed


def merge_pages(cache: Path, output: Path, numbers: list[int], visual: bool = False,
                max_output_bytes: int | None = None) -> None:
    from pypdf import PdfReader, PdfWriter
    if not numbers or numbers != sorted(set(numbers)):
        raise ValueError("La lista de páginas debe ser creciente y no contener duplicados")
    missing = [n for n in numbers if not cached_page(cache, n, visual)]
    if missing:
        raise ValueError(f"Faltan páginas válidas: {missing[:30]}. El PDF final no se modificó")
    output = output.resolve()
    if output == cache.resolve() or cache.resolve() in output.parents:
        raise ValueError("El PDF final debe quedar fuera de la caché")
    output.parent.mkdir(parents=True, exist_ok=True)
    estimated = sum((cache / "pages" / f"page-{number:06d}.pdf").stat().st_size
                    for number in numbers)
    if max_output_bytes is not None and estimated > max_output_bytes:
        raise ExportError("El libro supera el límite de tamaño permitido.")
    if shutil.disk_usage(output.parent).free < estimated + DISK_RESERVE_BYTES:
        raise ExportError("No hay espacio suficiente para ensamblar el libro.")
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".pdf", dir=output.parent)
    os.close(fd)
    try:
        LOG.info("Ensamblando %s páginas. Esta fase puede tardar varios minutos...", len(numbers))
        with PdfWriter() as writer:
            for index, number in enumerate(numbers, 1):
                writer.append(str(cache / "pages" / f"page-{number:06d}.pdf"), import_outline=False)
                if index % 50 == 0 or index == len(numbers):
                    LOG.info("Ensamblado: %s/%s páginas", index, len(numbers))
            writer.add_metadata({"/Producer": f"descargar_libro_local / {VERSION}"})
            LOG.info("Escribiendo el PDF final en disco...")
            writer.write(temporary)
        if max_output_bytes is not None and Path(temporary).stat().st_size > max_output_bytes:
            raise ExportError("El libro supera el límite de tamaño permitido.")
        LOG.info("Comprobando el PDF ensamblado...")
        with open(temporary, "rb") as stream:
            reader = PdfReader(stream, strict=True)
            if len(reader.pages) != len(numbers):
                raise ValueError("El ensamblado produjo un número incorrecto de páginas")
            for number, sheet in zip(numbers, reader.pages):
                meta = read_json(cache / "pages" / f"page-{number:06d}.json")
                if (float(sheet.mediabox.width), float(sheet.mediabox.height)) != (
                        meta["width_pt"], meta["height_pt"]):
                    raise ValueError(f"Cambió el tamaño de la página {number} al ensamblar")
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def export_book(viewer_url: str, output: Path, cache: Path,
                progress: Callable[[int, int], None], *, max_pages: int = 1500,
                max_bytes: int = 1024 * 1024 * 1024, timeout_ms: int = 45000,
                attempts: int = 3) -> int:
    """Export a whole viewer PDF, resuming verified pages after worker restarts.

    Network traffic is confined to the requested, approved provider host. An
    expired session is reported as a failed job; Google credentials are never
    requested by this worker.
    """
    from django.core.exceptions import ValidationError
    from playwright.sync_api import sync_playwright

    try:
        viewer_url = validate_viewer_url(viewer_url)
    except ValidationError as error:
        raise ExportError("El enlace del visor no es válido.") from error
    if max_pages < 1 or max_bytes < 1 or timeout_ms < 1000 or not 1 <= attempts <= 10:
        raise ValueError("Límites de exportación inválidos")
    identity = book_identity(viewer_url)
    permitted_host = urlsplit(viewer_url).hostname
    initialize_cache(cache, identity)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, chromium_sandbox=True, env=browser_environment(),
        )
        try:
            context = browser.new_context(service_workers="block", accept_downloads=False)
            context.route("**/*", provider_route_guard(permitted_host, timeout_ms))
            context.route_web_socket("**/*", lambda socket: socket.close())
            viewer = context.new_page()
            response = viewer.goto(viewer_url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                actual_identity = book_identity(viewer.url)
            except ValueError:
                actual_identity = None
            if response is None or not response.ok or actual_identity != identity:
                raise ExportError("La sesión del visor no está disponible o ha expirado.")
            total_label = viewer.locator("#controlsBottomtotpages")
            total_label.wait_for(state="visible", timeout=timeout_ms)
            digits = re.findall(r"\d[\d.,]*", total_label.inner_text())
            if not digits:
                raise ExportError("No se pudo leer el número de páginas del visor.")
            total = int(re.sub(r"[.,]", "", digits[-1]))
            if not 1 <= total <= max_pages:
                raise ExportError("El libro supera el límite de páginas permitido.")
            progress(0, total)
            extractor = context.new_page()
            try:
                failed = export_pages(extractor, viewer.url, list(range(1, total + 1)),
                                      cache, False, attempts, timeout_ms, progress, max_bytes)
            finally:
                extractor.close()
            if failed:
                raise ExportError(f"No se pudieron exportar {len(failed)} páginas del libro.")
        finally:
            browser.close()
    merge_pages(cache, output, list(range(1, total + 1)), max_output_bytes=max_bytes)
    return total
