"""Durable, single-process worker for student book requests."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import shutil
import time
import uuid

import fitz
from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage
from django.db import OperationalError, close_old_connections, transaction
from django.utils import timezone

from .models import Book, BookRequest
from .request_security import decrypt_viewer_url
from .services.ebooks724 import DISK_RESERVE_BYTES, ExportError, atomic_write, export_book


LOG = logging.getLogger(__name__)
GENERIC_ERROR = "No se pudo procesar el libro. Vuelve a solicitarlo con un enlace vigente."


class WorkerAlreadyRunning(Exception):
    """Another process owns this data directory's book request worker."""


def requests_root() -> Path:
    root = (Path(settings.DATA_DIR) / "requests").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def request_directory(request_id: uuid.UUID) -> Path:
    root = requests_root()
    destination = (root / str(request_id)).resolve()
    if destination.parent != root:
        raise ValueError("Directorio de solicitud inválido")
    return destination


def remove_request_directory(request_id: uuid.UUID) -> None:
    directory = request_directory(request_id)
    if directory.is_dir():
        shutil.rmtree(directory)


@contextmanager
def exclusive_worker_lock():
    """Keep one worker per SQLite database, including during crash recovery."""
    lock_path = requests_root() / "worker.lock"
    with open(lock_path, "a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt

                if lock_path.stat().st_size == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            raise WorkerAlreadyRunning("Ya hay un procesador de solicitudes activo.") from error
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def recover_interrupted_requests() -> int:
    """Call only while owning the exclusive worker lock."""
    close_old_connections()
    BookRequest.objects.filter(
        status=BookRequest.Status.PROCESSING, book__isnull=False,
    ).update(status=BookRequest.Status.COMPLETED, error_message="",
             encrypted_viewer_url="", updated_at=timezone.now())
    return BookRequest.objects.filter(
        status=BookRequest.Status.PROCESSING, book__isnull=True,
    ).update(status=BookRequest.Status.QUEUED, error_message="", updated_at=timezone.now())


def claim_next_request() -> BookRequest | None:
    """Compare-and-set a queued row in a short SQLite transaction."""
    for _ in range(5):
        close_old_connections()
        try:
            with transaction.atomic():
                candidate = BookRequest.objects.filter(
                    status=BookRequest.Status.QUEUED,
                ).order_by("created_at", "id").values_list("pk", flat=True).first()
                if candidate is None:
                    return None
                changed = BookRequest.objects.filter(
                    pk=candidate, status=BookRequest.Status.QUEUED,
                ).update(status=BookRequest.Status.PROCESSING,
                         error_message="", updated_at=timezone.now())
                if changed:
                    return BookRequest.objects.get(pk=candidate)
        except OperationalError:
            time.sleep(0.1)
    raise OperationalError("No se pudo reclamar una solicitud de libro.")


def _pdf_cover_and_count(path: Path, expected_pages: int, max_bytes: int) -> tuple[bytes, int, int]:
    size = path.stat().st_size
    if size < 5 or size > max_bytes:
        raise ExportError("El PDF generado supera el límite permitido o está vacío.")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ExportError("El PDF generado no es válido.")
    try:
        with fitz.open(path) as document:
            if document.is_encrypted or document.page_count != expected_pages:
                raise ExportError("El PDF generado está incompleto o protegido.")
            first = document.load_page(0)
            bounds = first.rect
            scale = min(2.0, 640 / max(bounds.width, bounds.height, 1))
            cover = first.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes(
                "jpeg", jpg_quality=84,
            )
            return cover, document.page_count, size
    except ExportError:
        raise
    except Exception as error:
        raise ExportError("No se pudo validar el PDF generado.") from error


def publish_book(request: BookRequest, output: Path, expected_pages: int) -> Book:
    """Publish the complete PDF and cover, then complete the request atomically."""
    max_bytes = settings.MAX_PDF_MB * 1024 * 1024
    cover_bytes, pages, size = _pdf_cover_and_count(output, expected_pages, max_bytes)
    # A stable id lets crash recovery replace uncommitted files rather than
    # create new, unreachable copies of large books.
    book = Book(id=request.pk, title=request.title, author=request.author, pages=pages, file_size=size)
    saved_files = []
    try:
        if Book.objects.filter(pk=book.pk).exists():
            raise RuntimeError("Ya existe un libro para esta solicitud.")
        if isinstance(book.pdf.storage, FileSystemStorage) and isinstance(book.cover.storage, FileSystemStorage):
            book.pdf.name = f"books/{book.id}.pdf"
            book.cover.name = f"covers/{book.id}.jpg"
            pdf_destination = Path(book.pdf.path)
            cover_destination = Path(book.cover.path)
            pdf_destination.parent.mkdir(parents=True, exist_ok=True)
            cover_destination.parent.mkdir(parents=True, exist_ok=True)
            same_filesystem = output.stat().st_dev == pdf_destination.parent.stat().st_dev
            needed = DISK_RESERVE_BYTES + len(cover_bytes) + (0 if same_filesystem else size)
            if shutil.disk_usage(pdf_destination.parent).free < needed:
                raise ExportError("No hay espacio suficiente para publicar el libro.")
            atomic_write(cover_destination, cover_bytes)
            saved_files.append((book.cover.storage, book.cover.name))
            if same_filesystem:
                os.replace(output, pdf_destination)
            else:
                # FileSystemStorage streams this copy; it does not load the
                # complete PDF into memory.
                with output.open("rb") as source:
                    book.pdf.save(f"{book.id}.pdf", File(source), save=False)
            saved_files.append((book.pdf.storage, book.pdf.name))
        else:
            with output.open("rb") as source:
                book.pdf.save(f"{book.id}.pdf", File(source), save=False)
            saved_files.append((book.pdf.storage, book.pdf.name))
            book.cover.save(f"{book.id}.jpg", ContentFile(cover_bytes), save=False)
            saved_files.append((book.cover.storage, book.cover.name))
        with transaction.atomic():
            current = BookRequest.objects.select_for_update().get(pk=request.pk)
            if current.status != BookRequest.Status.PROCESSING or current.book_id is not None:
                raise RuntimeError("La solicitud cambió de estado durante la publicación.")
            book.save()
            current.book = book
            current.status = BookRequest.Status.COMPLETED
            current.pages_done = pages
            current.total_pages = pages
            current.error_message = ""
            current.encrypted_viewer_url = ""
            current.save(update_fields=[
                "book", "status", "pages_done", "total_pages", "error_message",
                "encrypted_viewer_url", "updated_at",
            ])
        return book
    except Exception:
        for storage, name in saved_files:
            storage.delete(name)
        raise


def process_request(request: BookRequest) -> bool:
    """Return true on successful publication and store safe failures in DB."""
    if request.status != BookRequest.Status.PROCESSING:
        raise ValueError("La solicitud debe estar en proceso")
    directory = request_directory(request.pk)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "book.pdf"
    cache = directory / "cache"

    def progress(done: int, total: int) -> None:
        close_old_connections()
        changed = BookRequest.objects.filter(
            pk=request.pk, status=BookRequest.Status.PROCESSING,
        ).update(pages_done=done, total_pages=total, updated_at=timezone.now())
        if not changed:
            raise RuntimeError("La solicitud dejó de estar en proceso.")

    succeeded = False
    try:
        if not Book.objects.filter(pk=request.pk).exists():
            storage = Book._meta.get_field("pdf").storage
            cover_storage = Book._meta.get_field("cover").storage
            storage.delete(f"books/{request.pk}.pdf")
            cover_storage.delete(f"covers/{request.pk}.jpg")
        url = decrypt_viewer_url(request.encrypted_viewer_url)
        total = export_book(
            url, output, cache, progress,
            max_bytes=settings.MAX_PDF_MB * 1024 * 1024,
        )
        publish_book(request, output, total)
        succeeded = True
    except Exception as error:
        message = str(error) if isinstance(error, ExportError) else GENERIC_ERROR
        BookRequest.objects.filter(
            pk=request.pk, status=BookRequest.Status.PROCESSING,
        ).update(status=BookRequest.Status.FAILED, error_message=message[:500],
                 encrypted_viewer_url="", updated_at=timezone.now())
        LOG.warning("Solicitud %s falló: %s", request.pk, type(error).__name__)
    finally:
        try:
            current_status = BookRequest.objects.values_list("status", flat=True).get(pk=request.pk)
            if current_status in (BookRequest.Status.COMPLETED, BookRequest.Status.FAILED):
                remove_request_directory(request.pk)
        except Exception as error:
            LOG.warning("No se pudo limpiar la solicitud %s: %s", request.pk, type(error).__name__)
    return succeeded


def cleanup_finished_directories() -> None:
    root = requests_root()
    BookRequest.objects.filter(
        status__in=(BookRequest.Status.COMPLETED, BookRequest.Status.FAILED),
    ).exclude(encrypted_viewer_url="").update(encrypted_viewer_url="")
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            request_id = uuid.UUID(entry.name)
        except ValueError:
            continue
        if str(request_id) != entry.name:
            continue
        status = BookRequest.objects.filter(pk=request_id).values_list("status", flat=True).first()
        if status in (BookRequest.Status.COMPLETED, BookRequest.Status.FAILED):
            remove_request_directory(request_id)


def run_worker(*, once: bool = False, poll_interval: float = 3.0) -> None:
    if poll_interval <= 0 or poll_interval > 60:
        raise ValueError("El intervalo de sondeo debe estar entre 0 y 60 segundos.")
    with exclusive_worker_lock():
        recovered = recover_interrupted_requests()
        if recovered:
            LOG.info("Se reanudaron %s solicitudes interrumpidas.", recovered)
        cleanup_finished_directories()
        while True:
            job = claim_next_request()
            if job is not None:
                process_request(job)
                if once:
                    break
            elif once:
                break
            else:
                time.sleep(poll_interval)
