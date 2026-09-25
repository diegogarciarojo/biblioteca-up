import tempfile
from pathlib import Path

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Book
from .models import BookPageText


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

    def test_reader_search_builds_and_reuses_page_index(self):
        book = self.upload()
        url = reverse("search_book", args=[book.id])
        response = self.client.get(url, {"q": "Libro"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matches"], [1])
        self.assertEqual(response.json()["total"], 1)
        self.assertTrue(response.json()["has_text"])
        self.assertEqual(BookPageText.objects.filter(book=book).count(), 1)
        self.assertEqual(self.client.get(url, {"q": "prueba"}).json()["matches"], [1])
        self.assertEqual(BookPageText.objects.filter(book=book).count(), 1)
        self.assertEqual(self.client.get(url, {"q": "no aparece"}).json()["total"], 0)

    def test_reader_search_repairs_stale_page_count(self):
        document = fitz.open()
        document.new_page().insert_text((72, 72), "Primera pagina")
        document.new_page().insert_text((72, 72), "Segunda pagina")
        self.pdf_bytes = document.tobytes()
        document.close()
        book = self.upload()
        page_response = self.client.get(reverse("pdf_page", args=[book.id, 2]))
        self.assertEqual(page_response.status_code, 200)
        with fitz.open(stream=page_response.content, filetype="pdf") as single_page:
            self.assertEqual(single_page.page_count, 1)
            self.assertIn("Segunda", single_page[0].get_text())
        self.assertEqual(self.client.get(reverse("pdf_page", args=[book.id, 3])).status_code, 404)
        Book.objects.filter(pk=book.pk).update(pages=1)
        BookPageText.objects.create(book=book, page_number=1, text="Primera pagina")

        response = self.client.get(reverse("search_book", args=[book.id]), {"q": "Segunda"})
        self.assertEqual(response.json()["matches"], [2])
        self.assertEqual(BookPageText.objects.filter(book=book).count(), 2)
        book.refresh_from_db()
        self.assertEqual(book.pages, 2)

    def test_reader_search_indexes_large_book_in_small_batches(self):
        document = fitz.open()
        for number in range(22):
            document.new_page().insert_text((72, 72), f"Pagina {number + 1} prueba")
        self.pdf_bytes = document.tobytes()
        document.close()
        book = self.upload()
        url = reverse("search_book", args=[book.id])

        first = self.client.get(url, {"q": "Pagina 22"}).json()
        self.assertFalse(first["complete"])
        self.assertEqual(first["indexed_pages"], 20)
        self.assertEqual(first["total"], 0)
        second = self.client.get(url, {"q": "Pagina 22"}).json()
        self.assertTrue(second["complete"])
        self.assertEqual(second["indexed_pages"], 22)
        self.assertEqual(second["matches"], [22])
