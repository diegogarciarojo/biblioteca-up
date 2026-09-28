import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Book
from .models import BookPageText


class LibraryFlowTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp.name, CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "pdf_pages": {
                "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                "LOCATION": Path(self.temp.name) / "page-cache",
            },
        })
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

    def test_edit_details_preserves_pdf_cover_and_search_index(self):
        book = self.upload()
        BookPageText.objects.create(book=book, page_number=1, text="Libro de prueba")
        original_pdf, original_cover = book.pdf.name, book.cover.name
        original_version = book.pdf_version
        url = reverse("edit_book", args=[book.id])
        self.assertContains(self.client.get(reverse("panel")), f'{url}#book-form')
        response = self.client.get(url)
        self.assertContains(response, 'value="Libro de prueba"')
        self.assertContains(response, "Guardar cambios")
        self.assertFalse(response.context["form"].fields["pdf"].required)

        with patch("catalog.forms.fitz.open", side_effect=AssertionError("Existing PDF should not be reopened")):
            response = self.client.post(url, {
                "title": "Título actualizado", "author": "Nueva autora", "description": "Nueva descripción",
            })
        self.assertRedirects(response, reverse("panel"))
        book.refresh_from_db()
        self.assertEqual((book.title, book.author, book.description), ("Título actualizado", "Nueva autora", "Nueva descripción"))
        self.assertEqual((book.pdf.name, book.cover.name, book.pdf_version), (original_pdf, original_cover, original_version))
        self.assertEqual(Path(book.pdf.path).read_bytes(), self.pdf_bytes)
        self.assertEqual(BookPageText.objects.filter(book=book).count(), 1)
        self.assertEqual(Book.objects.count(), 1)
        self.assertContains(self.client.get(reverse("home")), "Título actualizado")

    def test_replace_pdf_updates_cover_pages_version_and_search(self):
        book = self.upload()
        BookPageText.objects.create(book=book, page_number=1, text="Libro de prueba")
        old_pdf, old_cover = Path(book.pdf.path), Path(book.cover.path)
        old_cover_bytes, old_version = old_cover.read_bytes(), book.pdf_version
        with fitz.open() as document:
            document.new_page().insert_text((72, 72), "Contenido nuevo")
            document.new_page().insert_text((72, 72), "Segunda pagina nueva")
            replacement_bytes = document.tobytes()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("edit_book", args=[book.id]), {
                "title": "Edición nueva", "author": "Nueva autora", "description": "",
                "pdf": SimpleUploadedFile("edicion.pdf", replacement_bytes, content_type="application/pdf"),
            })
        self.assertRedirects(response, reverse("panel"))
        book.refresh_from_db()
        self.assertEqual(book.pages, 2)
        self.assertEqual(book.file_size, len(replacement_bytes))
        self.assertEqual(Path(book.pdf.path).read_bytes(), replacement_bytes)
        self.assertNotEqual(Path(book.cover.path).read_bytes(), old_cover_bytes)
        self.assertNotEqual(book.pdf_version, old_version)
        self.assertFalse(old_pdf.exists())
        self.assertFalse(old_cover.exists())
        self.assertEqual(BookPageText.objects.filter(book=book).count(), 0)
        self.assertEqual(Book.objects.count(), 1)
        self.assertContains(self.client.get(reverse("book_detail", args=[book.id])), f'?v={book.pdf_version}')
        self.assertContains(self.client.get(reverse("read_book", args=[book.id])), f'data-version="{book.pdf_version}"')
        search_url = reverse("search_book", args=[book.id])
        self.assertEqual(self.client.get(search_url, {"q": "Contenido nuevo"}).json()["matches"], [1])
        self.assertEqual(self.client.get(search_url, {"q": "Libro de prueba"}).json()["matches"], [])
        page_response = self.client.get(reverse("pdf_page", args=[book.id, 2]))
        with fitz.open(stream=page_response.content, filetype="pdf") as document:
            self.assertIn("Segunda pagina nueva", document[0].get_text())

    def test_invalid_replacement_preserves_existing_book_and_inputs(self):
        book = self.upload()
        original_pdf, original_cover = book.pdf.name, book.cover.name
        response = self.client.post(reverse("edit_book", args=[book.id]), {
            "title": "Mi título corregido", "author": "Autora", "description": "Descripción guardada en el formulario",
            "pdf": SimpleUploadedFile("falso.pdf", b"archivo incorrecto", content_type="application/pdf"),
        })
        self.assertContains(response, "cabecera PDF válida")
        self.assertContains(response, "Mi título corregido")
        self.assertContains(response, "Descripción guardada en el formulario")
        book.refresh_from_db()
        self.assertEqual(book.title, "Libro de prueba")
        self.assertEqual((book.pdf.name, book.cover.name), (original_pdf, original_cover))
        self.assertEqual(Path(book.pdf.path).read_bytes(), self.pdf_bytes)
        self.assertTrue(Path(book.cover.path).exists())

    def test_edit_requires_staff_and_csrf(self):
        book = self.upload()
        url = reverse("edit_book", args=[book.id])
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(url).status_code, 302)
        self.client.force_login(get_user_model().objects.create_user("viewer", password="abc"))
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(url).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(url, {"title": "Unauthorized change"}).status_code, 403)
        book.refresh_from_db()
        self.assertEqual(book.title, "Libro de prueba")

    def test_failed_replacement_rolls_back_and_removes_new_files(self):
        book = self.upload()
        original_files = set(Path(self.temp.name).rglob("*.pdf")) | set(Path(self.temp.name).rglob("*.jpg"))
        original_pdf, original_cover = book.pdf.name, book.cover.name
        with fitz.open() as document:
            document.new_page().insert_text((72, 72), "Reemplazo que no debe guardarse")
            replacement = document.tobytes()
        with patch("catalog.models.Book._save_table", side_effect=RuntimeError("Database write failed")):
            with self.assertRaisesRegex(RuntimeError, "Database write failed"):
                self.client.post(reverse("edit_book", args=[book.id]), {
                    "title": "Cambio fallido", "author": "", "description": "",
                    "pdf": SimpleUploadedFile("reemplazo.pdf", replacement, content_type="application/pdf"),
                })
        book.refresh_from_db()
        self.assertEqual(book.title, "Libro de prueba")
        self.assertEqual((book.pdf.name, book.cover.name), (original_pdf, original_cover))
        self.assertEqual(Path(book.pdf.path).read_bytes(), self.pdf_bytes)
        remaining_files = set(Path(self.temp.name).rglob("*.pdf")) | set(Path(self.temp.name).rglob("*.jpg"))
        self.assertEqual(remaining_files, original_files)

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

    def test_reader_search_ignores_accents_in_query_and_saved_text(self):
        book = self.upload()
        BookPageText.objects.create(book=book, page_number=1, text="Sección 2.3; SECCIO\u0301N 2.3; seccion 2.3")
        url = reverse("search_book", args=[book.id])
        for query in ["Seccion 2.3", "Sección 2.3", "SECCIO\u0301N 2.3"]:
            with self.subTest(query=query):
                result = self.client.get(url, {"q": query}).json()
                self.assertEqual(result["matches"], [1, 1, 1])
                self.assertEqual(result["total"], 3)

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

    def test_page_cache_reuses_extraction_and_invalidates_changed_source(self):
        book = self.upload()
        url = reverse("pdf_page", args=[book.id, 1])
        first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        with patch("catalog.views.fitz.open", side_effect=AssertionError("PDF reopened")):
            self.assertEqual(self.client.get(url).content, first.content)
        with fitz.open() as replacement:
            replacement.new_page().insert_text((72, 72), "Contenido reemplazado y diferente")
            Path(book.pdf.path).write_bytes(replacement.tobytes())
        updated = self.client.get(url)
        with fitz.open(stream=updated.content, filetype="pdf") as document:
            self.assertIn("Contenido reemplazado", document[0].get_text())
        Path(book.pdf.path).unlink()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_page_still_loads_when_disk_cache_is_unavailable(self):
        book = self.upload()
        with patch("django.core.cache.backends.filebased.FileBasedCache.get", side_effect=OSError), patch(
            "django.core.cache.backends.filebased.FileBasedCache.set", side_effect=OSError
        ):
            response = self.client.get(reverse("pdf_page", args=[book.id, 1]))
        self.assertEqual(response.status_code, 200)
        with fitz.open(stream=response.content, filetype="pdf") as document:
            self.assertIn("Libro de prueba", document[0].get_text())
