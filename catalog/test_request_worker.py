import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import Book, BookRequest
from .request_security import encrypt_viewer_url
from .request_worker import (
    claim_next_request,
    process_request,
    recover_interrupted_requests,
    request_directory,
)
from .services.ebooks724 import (
    DISK_RESERVE_BYTES,
    ExportError,
    atomic_write,
    browser_environment,
    export_pages,
    provider_route_guard,
)


VIEWER_URL = "https://ebooks724.up.elogim.com/visorBook.aspx?i=11946&t=sample-session"


class BookRequestWorkerTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data_dir = Path(temporary.name)
        override = override_settings(
            DATA_DIR=self.data_dir, MEDIA_ROOT=self.data_dir / "media", MAX_PDF_MB=10,
        )
        override.enable()
        self.addCleanup(override.disable)
        user = get_user_model().objects.create_user(
            username="google_student", email="student@up.edu.mx", password=None,
        )
        self.request = BookRequest.objects.create(
            user=user, title="Libro solicitado", author="Autora de prueba",
            encrypted_viewer_url=encrypt_viewer_url(VIEWER_URL),
        )
        with fitz.open() as document:
            for number in range(2):
                page = document.new_page()
                page.insert_text((72, 72), f"Página {number + 1}")
            self.pdf_bytes = document.tobytes()

    def test_claim_and_publish_complete_book(self):
        job = claim_next_request()
        self.assertEqual(job.pk, self.request.pk)
        self.assertEqual(job.status, BookRequest.Status.PROCESSING)
        self.assertIsNone(claim_next_request())

        def fake_export(url, output, cache, progress, **kwargs):
            self.assertEqual(url, VIEWER_URL)
            self.assertEqual(kwargs["max_bytes"], 10 * 1024 * 1024)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(self.pdf_bytes)
            progress(0, 2)
            progress(1, 2)
            progress(2, 2)
            return 2

        with patch("catalog.request_worker.export_book", side_effect=fake_export):
            self.assertTrue(process_request(job))

        self.request.refresh_from_db()
        self.assertEqual(self.request.status, BookRequest.Status.COMPLETED)
        self.assertEqual(self.request.encrypted_viewer_url, "")
        self.assertEqual((self.request.pages_done, self.request.total_pages), (2, 2))
        self.assertEqual(Book.objects.count(), 1)
        book = self.request.book
        self.assertEqual((book.title, book.author, book.pages),
                         ("Libro solicitado", "Autora de prueba", 2))
        self.assertEqual(Path(book.pdf.path).read_bytes(), self.pdf_bytes)
        self.assertTrue(Path(book.cover.path).read_bytes().startswith(b"\xff\xd8"))
        self.assertFalse(request_directory(self.request.pk).exists())

    def test_export_error_never_publishes_a_book(self):
        job = claim_next_request()
        with patch("catalog.request_worker.export_book", side_effect=ExportError("La sesión ha expirado.")):
            self.assertFalse(process_request(job))
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, BookRequest.Status.FAILED)
        self.assertEqual(self.request.encrypted_viewer_url, "")
        self.assertEqual(self.request.error_message, "La sesión ha expirado.")
        self.assertFalse(Book.objects.exists())
        self.assertFalse(request_directory(self.request.pk).exists())

    def test_page_count_mismatch_is_not_published(self):
        job = claim_next_request()

        def incomplete_export(url, output, cache, progress, **kwargs):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(self.pdf_bytes)
            progress(2, 3)
            return 3

        with patch("catalog.request_worker.export_book", side_effect=incomplete_export):
            self.assertFalse(process_request(job))
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, BookRequest.Status.FAILED)
        self.assertFalse(Book.objects.exists())

    def test_recovery_requeues_interrupted_work(self):
        job = claim_next_request()
        self.assertEqual(recover_interrupted_requests(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, BookRequest.Status.QUEUED)
        self.assertEqual(claim_next_request().pk, job.pk)

    def test_viewer_redirect_stops_export_without_exposing_session(self):
        class RedirectedPage:
            url = "https://accounts.google.com/signin"
            calls = 0

            def goto(self, target, **kwargs):
                self.calls += 1
                return type("Response", (), {"ok": True, "status": 200})()

        page = RedirectedPage()
        with self.assertRaises(ExportError) as caught:
            export_pages(page, VIEWER_URL, [1, 2], self.data_dir / "cache", False,
                         3, 1000, lambda done, total: None, 1024)
        self.assertEqual(page.calls, 1)
        self.assertNotIn("sample-session", str(caught.exception))

    def test_redirect_to_unapproved_host_is_never_fetched(self):
        response = Mock(status=302, headers={"location": "https://localhost/private"})
        route = Mock()
        route.request.url = VIEWER_URL
        route.fetch.return_value = response
        provider_route_guard("ebooks724.up.elogim.com", 1000)(route)
        self.assertEqual(route.fetch.call_count, 1)
        self.assertEqual(route.fetch.call_args.kwargs["max_redirects"], 0)
        response.dispose.assert_called_once()
        route.abort.assert_called_once()
        route.fulfill.assert_not_called()

    def test_redirect_on_provider_host_is_checked_and_completed(self):
        redirected = Mock(status=302, headers={"location": "/asset.css"})
        final = Mock(status=200, headers={})
        route = Mock()
        route.request.url = "https://ebooks724.up.elogim.com/style.css"
        route.fetch.side_effect = [redirected, final]
        provider_route_guard("ebooks724.up.elogim.com", 1000)(route)
        self.assertEqual(route.fetch.call_count, 2)
        self.assertEqual(route.fetch.call_args.kwargs["url"], "https://ebooks724.up.elogim.com/asset.css")
        route.fulfill.assert_called_once_with(response=final)
        redirected.dispose.assert_called_once()
        final.dispose.assert_called_once()
        route.abort.assert_not_called()

    def test_browser_environment_excludes_server_secrets(self):
        with patch.dict("os.environ", {
            "PATH": "os-runtime-path", "TEMP": "temporary-browser-files",
            "DJANGO_SECRET_KEY": "fake-test-only", "GOOGLE_OAUTH_CLIENT_SECRET": "fake-test-only",
        }, clear=True):
            self.assertEqual(browser_environment(), {
                "PATH": "os-runtime-path", "TEMP": "temporary-browser-files",
            })

    def test_low_disk_rejects_page_before_writing(self):
        destination = self.data_dir / "cache" / "page.pdf"
        with patch("catalog.services.ebooks724.shutil.disk_usage", return_value=Mock(free=DISK_RESERVE_BYTES)):
            with self.assertRaises(ExportError):
                atomic_write(destination, b"%PDF-")
        self.assertFalse(destination.exists())

    def test_low_disk_does_not_publish_a_book(self):
        job = claim_next_request()

        def fake_export(url, output, cache, progress, **kwargs):
            output.write_bytes(self.pdf_bytes)
            return 2

        with patch("catalog.request_worker.export_book", side_effect=fake_export), patch(
            "catalog.request_worker.shutil.disk_usage", return_value=Mock(free=DISK_RESERVE_BYTES - 1),
        ):
            self.assertFalse(process_request(job))
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, BookRequest.Status.FAILED)
        self.assertFalse(Book.objects.exists())
        self.assertFalse(request_directory(self.request.pk).exists())
