"""Student book requests and Google sign-in for Bibliotecario."""

import re
from datetime import timedelta

from authlib.integrations.django_client import OAuth
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods

from .models import BookRequest
from .request_security import encrypt_viewer_url, validate_viewer_url


SEARCH_URL = (
    "https://inventio.up.edu.mx/nde/search?query=Algebra&tab=Everything"
    "&search_scope=MyInst_and_CI&mfacet=tlevel,include,online_resources"
    "&offset=0&lang=es&vid=52UNIPAN_INST:52UNIPAN_INST_NDE"
)
GOOGLE_DOMAIN = "up.edu.mx"
STUDENT_SUB_SESSION_KEY = "book_request_google_sub"
STUDENT_NEXT_SESSION_KEY = "book_request_after_login"


class BookRequestForm(forms.Form):
    title = forms.CharField(max_length=240)
    author = forms.CharField(max_length=180, required=False)
    viewer_url = forms.CharField(max_length=4096, strip=False)

    def clean_viewer_url(self):
        return validate_viewer_url(self.cleaned_data["viewer_url"])


def google_oauth_configured():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def student_authenticated(request):
    sub = request.session.get(STUDENT_SUB_SESSION_KEY)
    return bool(
        request.user.is_authenticated
        and not request.user.is_staff
        and sub
        and request.user.get_username() == f"google_{sub}"
        and request.user.email.lower().endswith(f"@{GOOGLE_DOMAIN}")
    )


def _google_client():
    oauth = OAuth()
    return oauth.register(
        "google",
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
            "default_timeout": 15,
        },
    )


def _safe_next(request, candidate):
    if (
        isinstance(candidate, str)
        and candidate.startswith("/solicitar/")
        and not candidate.startswith("//")
        and url_has_allowed_host_and_scheme(
            candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        )
    ):
        return candidate
    return ""


def _render_request_page(request, *, form_error="", status=200):
    response = render(request, "catalog/request_book.html", {
        "search_url": SEARCH_URL,
        "google_oauth_configured": google_oauth_configured(),
        "student_authenticated": student_authenticated(request),
        "form_error": form_error,
        "form_title": request.POST.get("title", "")[:240] if request.method == "POST" else "",
        "form_author": request.POST.get("author", "")[:180] if request.method == "POST" else "",
        "viewer_url": "",
    }, status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def privacy(request):
    return render(request, "catalog/privacy.html")


@require_http_methods(["GET", "POST"])
def request_book(request):
    if request.method == "GET":
        return _render_request_page(request)
    if not google_oauth_configured():
        return _render_request_page(
            request,
            form_error="El acceso institucional aún no está configurado.",
            status=503,
        )
    if not student_authenticated(request):
        return redirect("student_login")
    form = BookRequestForm(request.POST)
    if not form.is_valid():
        first_error = next(iter(form.errors.values()))[0]
        return _render_request_page(request, form_error=str(first_error), status=400)
    if BookRequest.objects.filter(
        user=request.user,
        status__in=[BookRequest.Status.QUEUED, BookRequest.Status.PROCESSING],
    ).exists():
        return _render_request_page(request, form_error="Ya tienes una solicitud en proceso.", status=429)
    recent_finished = BookRequest.objects.filter(
        user=request.user,
        status__in=[BookRequest.Status.COMPLETED, BookRequest.Status.FAILED],
        created_at__gte=timezone.now() - timedelta(days=1),
    ).count()
    if recent_finished >= 5:
        return _render_request_page(
            request,
            form_error="Has alcanzado el máximo de cinco solicitudes en 24 horas.",
            status=429,
        )
    try:
        book_request = BookRequest.objects.create(
            user=request.user,
            title=form.cleaned_data["title"],
            author=form.cleaned_data["author"],
            encrypted_viewer_url=encrypt_viewer_url(form.cleaned_data["viewer_url"]),
        )
    except IntegrityError:
        return _render_request_page(request, form_error="Ya tienes una solicitud en proceso.", status=429)
    return redirect("request_book_wait", request_id=book_request.pk)


@require_GET
def student_login(request):
    next_url = _safe_next(request, request.GET.get("next", ""))
    if student_authenticated(request):
        return redirect(next_url or "request_book")
    if not google_oauth_configured():
        return _render_request_page(
            request,
            form_error="El acceso institucional aún no está configurado.",
            status=503,
        )
    callback_url = request.build_absolute_uri(reverse("student_callback"))
    request.session[STUDENT_NEXT_SESSION_KEY] = next_url
    try:
        return _google_client().authorize_redirect(request, callback_url, hd=GOOGLE_DOMAIN)
    except Exception:
        return _render_request_page(request, form_error="No se pudo conectar con Google. Inténtalo más tarde.", status=502)


@require_GET
def student_callback(request):
    if not google_oauth_configured():
        return _render_request_page(request, form_error="El acceso institucional aún no está configurado.", status=503)
    if not request.GET.get("code") or not request.GET.get("state"):
        return _render_request_page(request, form_error="No se completó el acceso con Google.", status=400)
    try:
        # Authlib validates OAuth state, PKCE, the signed ID token and nonce.
        claims = _google_client().authorize_access_token(request)["userinfo"]
    except Exception:
        return _render_request_page(request, form_error="No se pudo verificar el acceso con Google.", status=400)

    email = str(claims.get("email", "")).strip().lower()
    sub = str(claims.get("sub", ""))
    if (
        claims.get("email_verified") is not True
        or str(claims.get("hd", "")).lower() != GOOGLE_DOMAIN
        or not email.endswith(f"@{GOOGLE_DOMAIN}")
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", sub)
    ):
        return _render_request_page(request, form_error="Utiliza una cuenta institucional verificada.", status=403)

    username = f"google_{sub}"
    user, created = get_user_model().objects.get_or_create(
        username=username,
        defaults={"email": email, "password": make_password(None)},
    )
    if not user.is_active or user.is_staff or user.is_superuser:
        return _render_request_page(request, form_error="Esta cuenta no puede realizar solicitudes.", status=403)
    if not created and user.email != email:
        user.email = email
        user.save(update_fields=["email"])
    next_url = _safe_next(request, request.session.pop(STUDENT_NEXT_SESSION_KEY, ""))
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[STUDENT_SUB_SESSION_KEY] = sub
    return redirect(next_url or "request_book")


@require_GET
def request_book_wait(request, request_id):
    if not student_authenticated(request):
        return redirect(f"{reverse('student_login')}?next={request.path}")
    book_request = get_object_or_404(BookRequest, pk=request_id, user=request.user)
    response = render(request, "catalog/request_wait.html", {
        "book_request": book_request,
        "status_url": reverse("request_book_status", kwargs={"request_id": book_request.pk}),
    })
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def request_book_status(request, request_id):
    if not student_authenticated(request):
        response = JsonResponse({"error": "Inicia sesión con tu cuenta institucional."}, status=403)
    else:
        book_request = get_object_or_404(
            BookRequest.objects.select_related("book"), pk=request_id, user=request.user,
        )
        messages = {
            BookRequest.Status.QUEUED: "Tu solicitud está en espera.",
            BookRequest.Status.PROCESSING: "Estamos preparando el libro.",
            BookRequest.Status.COMPLETED: "El libro está disponible.",
            BookRequest.Status.FAILED: book_request.error_message or "No se pudo preparar el libro.",
        }
        response = JsonResponse({
            "status": book_request.status,
            "pages_done": book_request.pages_done,
            "pages_total": book_request.total_pages,
            "message": messages.get(book_request.status, "Estamos procesando tu solicitud."),
            "book_url": (
                reverse("read_book", kwargs={"book_id": book_request.book_id})
                if book_request.status == BookRequest.Status.COMPLETED and book_request.book_id else None
            ),
        })
    response["Cache-Control"] = "no-store"
    return response
