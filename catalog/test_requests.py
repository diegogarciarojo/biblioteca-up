import uuid
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Book, BookRequest
from .request_security import decrypt_viewer_url, encrypt_viewer_url, validate_viewer_url
from .request_views import STUDENT_NEXT_SESSION_KEY, STUDENT_SUB_SESSION_KEY


VIEWER_URL = "https://ebooks724.up.elogim.com/visorBook.aspx?i=123&t=temporary-token"


class ViewerSecurityTests(TestCase):
    def test_only_expected_https_viewers_with_i_and_t_are_accepted(self):
        self.assertEqual(validate_viewer_url(VIEWER_URL), VIEWER_URL)
        bad_urls = [
            "http://ebooks724.up.elogim.com/visorBook.aspx?i=123&t=token",
            "https://evil.example/visorBook.aspx?i=123&t=token",
            "https://ebooks724.up.elogim.com.evil.example/visorBook.aspx?i=123&t=token",
            "https://user:pass@ebooks724.up.elogim.com/visorBook.aspx?i=123&t=token",
            "https://ebooks724.up.elogim.com:8443/visorBook.aspx?i=123&t=token",
            "https://ebooks724.up.elogim.com/other.aspx?i=123&t=token",
            "https://ebooks724.up.elogim.com/visorBook.aspx?i=123",
            "https://ebooks724.up.elogim.com/visorBook.aspx?i=123&t=one&t=two",
            "https://ebooks724.up.elogim.com/visorBook.aspx?i=123&t=token#fragment",
        ]
        for url in bad_urls:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                validate_viewer_url(url)

    def test_encryption_is_authenticated_and_does_not_store_plaintext(self):
        encrypted = encrypt_viewer_url(VIEWER_URL)
        self.assertNotIn(VIEWER_URL, encrypted)
        self.assertEqual(decrypt_viewer_url(encrypted), VIEWER_URL)
        with self.assertRaises(ValueError):
            decrypt_viewer_url(encrypted[:-2] + "xx")


@override_settings(GOOGLE_OAUTH_CLIENT_ID="test-client", GOOGLE_OAUTH_CLIENT_SECRET="test-secret")
class StudentRequestTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user(
            username="google_123456", email="student@up.edu.mx", password=None,
        )

    def sign_in(self, user=None, sub="123456"):
        self.client.force_login(user or self.student)
        session = self.client.session
        session[STUDENT_SUB_SESSION_KEY] = sub
        session.save()

    def submit(self, url=VIEWER_URL):
        return self.client.post(reverse("request_book"), {
            "title": "Álgebra",
            "author": "Autor de prueba",
            "viewer_url": url,
        })

    def test_get_is_public_and_post_requires_verified_student_session(self):
        self.assertEqual(self.client.get(reverse("request_book")).status_code, 200)
        self.assertRedirects(self.submit(), reverse("student_login"), fetch_redirect_response=False)
        self.assertFalse(BookRequest.objects.exists())
        local_user = get_user_model().objects.create_user("local", password="not-used")
        self.client.force_login(local_user)
        self.assertRedirects(self.submit(), reverse("student_login"), fetch_redirect_response=False)
        self.assertFalse(BookRequest.objects.exists())

    def test_student_logout_requires_post_and_csrf(self):
        self.sign_in()
        page = self.client.get(reverse("request_book"))
        self.assertContains(page, 'action="/salir/"')
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.session[STUDENT_SUB_SESSION_KEY], "123456")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.student)
        self.assertEqual(csrf_client.post(reverse("logout")).status_code, 403)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("home"))
        self.assertNotIn(STUDENT_SUB_SESSION_KEY, self.client.session)
        self.assertEqual(
            self.client.get(reverse("request_book")).context["student_authenticated"], False,
        )

    def test_public_privacy_explains_storage_and_is_linked(self):
        page = self.client.get(reverse("privacy"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "No guardamos tu contraseña")
        self.assertContains(page, "guarda cifrado")
        self.assertContains(page, "Cualquier visitante puede leer o descargar")
        self.assertContains(self.client.get(reverse("request_book")), reverse("privacy"))

    def test_submission_encrypts_link_and_status_is_private(self):
        self.sign_in()
        response = self.submit()
        book_request = BookRequest.objects.get()
        self.assertRedirects(
            response, reverse("request_book_wait", kwargs={"request_id": book_request.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(book_request.status, BookRequest.Status.QUEUED)
        self.assertNotIn(VIEWER_URL, book_request.encrypted_viewer_url)
        self.assertEqual(decrypt_viewer_url(book_request.encrypted_viewer_url), VIEWER_URL)
        wait_url = reverse("request_book_wait", kwargs={"request_id": book_request.pk})
        status_url = reverse("request_book_status", kwargs={"request_id": book_request.pk})
        self.assertEqual(self.client.get(wait_url).status_code, 200)
        status_response = self.client.get(status_url)
        self.assertEqual(status_response.json(), {
            "status": "queued", "pages_done": 0, "pages_total": 0,
            "message": "Tu solicitud está en espera.", "book_url": None,
        })
        self.assertEqual(status_response["Cache-Control"], "no-store")
        self.assertNotIn(VIEWER_URL, status_response.content.decode())

        other = get_user_model().objects.create_user("google_987", email="other@up.edu.mx", password=None)
        self.sign_in(other, "987")
        self.assertEqual(self.client.get(wait_url).status_code, 404)
        self.assertEqual(self.client.get(status_url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(status_url).status_code, 403)

    def test_invalid_url_is_rejected_without_queueing(self):
        self.sign_in()
        response = self.submit("https://example.com/visorBook.aspx?i=123&t=token")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BookRequest.objects.exists())
        self.assertContains(response, "Solo se aceptan enlaces HTTPS", status_code=400)
        self.assertNotIn("https://example.com/visorBook.aspx", response.content.decode())

    def test_one_active_request_and_five_finished_per_day(self):
        self.sign_in()
        self.submit()
        response = self.submit()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Ya tienes una solicitud en proceso", status_code=429)
        self.assertEqual(BookRequest.objects.count(), 1)
        BookRequest.objects.all().update(status=BookRequest.Status.COMPLETED)
        for _ in range(4):
            BookRequest.objects.create(
                user=self.student, title="Libro anterior", encrypted_viewer_url="",
                status=BookRequest.Status.FAILED,
            )
        response = self.submit()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "cinco solicitudes en 24 horas", status_code=429)
        self.assertEqual(BookRequest.objects.count(), 5)

    def test_completed_status_links_to_reader(self):
        self.sign_in()
        self.submit()
        book_request = BookRequest.objects.get()
        book = Book.objects.create(
            title="Álgebra", author="Autor", pdf="books/test.pdf", cover="covers/test.jpg",
            pages=2, file_size=100,
        )
        book_request.status = BookRequest.Status.COMPLETED
        book_request.pages_done = 2
        book_request.total_pages = 2
        book_request.book = book
        book_request.save()
        response = self.client.get(reverse("request_book_status", kwargs={"request_id": book_request.pk})).json()
        self.assertEqual(response["book_url"], reverse("read_book", kwargs={"book_id": book.pk}))
        self.assertEqual(response["pages_done"], 2)
        self.assertEqual(response["pages_total"], 2)

    def test_oauth_callback_requires_verified_institutional_claims(self):
        callback = reverse("student_callback")
        valid_claims = {
            "sub": "555555", "email": "student@up.edu.mx", "email_verified": True,
            "hd": "up.edu.mx",
        }
        for changed in ({"hd": "gmail.com"}, {"email_verified": False}, {"email": "student@gmail.com"}):
            claims = {**valid_claims, **changed}
            remote = Mock()
            remote.authorize_access_token.return_value = {"userinfo": claims}
            with patch("catalog.request_views._google_client", return_value=remote):
                response = self.client.get(callback, {"code": "code", "state": "state"})
            self.assertEqual(response.status_code, 403)
            self.assertFalse(BookRequest.objects.exists())
            self.assertFalse(self.client.session.get(STUDENT_SUB_SESSION_KEY))

        remote = Mock()
        remote.authorize_access_token.return_value = {"userinfo": valid_claims}
        with patch("catalog.request_views._google_client", return_value=remote):
            response = self.client.get(callback, {"code": "code", "state": "state"})
        self.assertRedirects(response, reverse("request_book"), fetch_redirect_response=False)
        user = get_user_model().objects.get(username="google_555555")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.client.session[STUDENT_SUB_SESSION_KEY], "555555")

    def test_oauth_login_preserves_only_same_site_request_destination(self):
        destination = reverse("request_book_wait", kwargs={"request_id": uuid.uuid4()})
        remote = Mock()
        remote.authorize_redirect.return_value = HttpResponseRedirect("https://accounts.google.com/example")
        with patch("catalog.request_views._google_client", return_value=remote):
            response = self.client.get(reverse("student_login"), {"next": destination})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[STUDENT_NEXT_SESSION_KEY], destination)

        remote.authorize_access_token.return_value = {"userinfo": {
            "sub": "555555", "email": "student@up.edu.mx", "email_verified": True,
            "hd": "up.edu.mx",
        }}
        with patch("catalog.request_views._google_client", return_value=remote):
            response = self.client.get(reverse("student_callback"), {"code": "code", "state": "state"})
        self.assertRedirects(response, destination, fetch_redirect_response=False)

        self.client.logout()
        with patch("catalog.request_views._google_client", return_value=remote):
            self.client.get(reverse("student_login"), {"next": "https://evil.example/steal"})
        self.assertEqual(self.client.session[STUDENT_NEXT_SESSION_KEY], "")

    def test_google_network_timeout_is_bounded_and_recoverable(self):
        from .request_views import _google_client

        self.assertEqual(_google_client().client_kwargs["default_timeout"], 15)
        remote = Mock()
        remote.authorize_redirect.side_effect = TimeoutError("Google timeout")
        with patch("catalog.request_views._google_client", return_value=remote):
            response = self.client.get(reverse("student_login"))
        self.assertContains(response, "No se pudo conectar con Google", status_code=502)
        self.assertFalse(self.client.session.get(STUDENT_SUB_SESSION_KEY))


class UnconfiguredRequestTests(TestCase):
    @override_settings(GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_get_remains_available_and_post_does_not_queue(self):
        self.assertEqual(self.client.get(reverse("request_book")).status_code, 200)
        response = self.client.post(reverse("request_book"), {
            "title": "Álgebra", "viewer_url": VIEWER_URL,
        })
        self.assertEqual(response.status_code, 503)
        self.assertFalse(BookRequest.objects.exists())
