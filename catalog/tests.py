import tempfile
from pathlib import Path

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Book


class LibraryFlowTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temp.cleanup)
        self.admin = get_user_model().objects.create_user("diego", password="una-clave-segura", is_staff=True)
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Libro de prueba")
        self.pdf_bytes = document.tobytes()
        document.close()

    def upload(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("panel"), {
            "title": "Libro de prueba",
            "author": "Autora de ejemplo",
            "description": "Historia de ejemplo",
            "pdf": SimpleUploadedFile("libro.pdf", self.pdf_bytes, content_type="application/pdf"),
        })
        self.assertRedirects(response, reverse("panel"))
        return Book.objects.get()

    def test_upload_catalog_reader_range_download_and_delete(self):
        book = self.upload()
        self.assertEqual(book.pages, 1)
        self.assertTrue(Path(book.cover.path).exists())
        self.assertEqual(self.client.get(reverse("home"), {"q": "Autora"}).status_code, 200)
        self.assertContains(self.client.get(reverse("home"), {"q": "Autora"}), book.title)
        self.assertContains(self.client.get(reverse("read_book", args=[book.id])), book.title)

        pdf_url = reverse("pdf_file", args=[book.id])
        response = self.client.get(pdf_url, HTTP_RANGE="bytes=0-4")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-")
        self.assertEqual(response["Content-Range"], f"bytes 0-4/{len(self.pdf_bytes)}")
        response = self.client.get(pdf_url, HTTP_RANGE="bytes=-5")
        self.assertEqual(b"".join(response.streaming_content), self.pdf_bytes[-5:])
        response = self.client.get(pdf_url, HTTP_RANGE=f"bytes={len(self.pdf_bytes)}-")
        self.assertEqual(response.status_code, 416)

        response = self.client.get(reverse("download_book", args=[book.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), self.pdf_bytes)

        pdf_path, cover_path = Path(book.pdf.path), Path(book.cover.path)
        self.assertRedirects(self.client.post(reverse("delete_book", args=[book.id])), reverse("panel"))
        self.assertFalse(pdf_path.exists())
        self.assertFalse(cover_path.exists())
        self.assertFalse(Book.objects.exists())

    def test_only_staff_can_publish_and_bad_pdf_is_rejected(self):
        self.assertEqual(self.client.get(reverse("panel")).status_code, 302)
        self.client.force_login(get_user_model().objects.create_user("reader", password="abc"))
        self.assertEqual(self.client.get(reverse("panel")).status_code, 302)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("panel"), {
            "title": "Archivo falso",
            "pdf": SimpleUploadedFile("falso.pdf", b"no es un pdf", content_type="application/pdf"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cabecera PDF válida")
        self.assertFalse(Book.objects.exists())

    def test_admin_login_and_logout(self):
        response = self.client.post(reverse("login"), {
            "username": "diego",
            "password": "una-clave-segura",
        })
        self.assertRedirects(response, reverse("panel"))
        self.assertEqual(self.client.get(reverse("panel")).status_code, 200)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("home"))
        self.assertEqual(self.client.get(reverse("panel")).status_code, 302)
