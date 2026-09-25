import re
from pathlib import Path

import fitz
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
from django.core.cache import caches
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_POST

from .forms import BookUploadForm
from .models import Book
from .search import find_in_book, index_book


def home(request):
    query = request.GET.get("q", "").strip()[:120]
    books = Book.objects.all()
    if query:
        books = books.filter(Q(title__icontains=query) | Q(author__icontains=query) | Q(description__icontains=query))
    page = Paginator(books, 18).get_page(request.GET.get("page"))
    return render(request, "catalog/home.html", {"page": page, "query": query, "total_books": Book.objects.count()})


def book_detail(request, book_id):
    return render(request, "catalog/detail.html", {"book": get_object_or_404(Book, pk=book_id)})


def read_book(request, book_id):
    return render(request, "catalog/reader.html", {"book": get_object_or_404(Book, pk=book_id)})


@require_GET
def search_book(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    query = request.GET.get("q", "").strip()[:100]
    if not query:
        return JsonResponse({"matches": [], "total": 0, "has_text": True, "limited": False, "complete": True})
    try:
        indexed_pages, pages = index_book(book, max_pages=20)
    except (FileNotFoundError, ValueError, fitz.FileDataError):
        raise Http404("PDF no disponible")
    result = find_in_book(book, query)
    result.update({"indexed_pages": indexed_pages, "pages": pages, "complete": indexed_pages >= pages})
    return JsonResponse(result)


def login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("panel")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not form.get_user().is_staff:
            form.add_error(None, "Esta cuenta no tiene acceso al panel.")
        else:
            login(request, form.get_user())
            return redirect("panel")
    return render(request, "catalog/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


staff_required = user_passes_test(lambda user: user.is_authenticated and user.is_staff, login_url="/login")


@staff_required
def panel(request):
    form = BookUploadForm(request.POST if request.method == "POST" else None, request.FILES if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        book = form.save(commit=False)
        book.pages = form.page_count
        book.file_size = form.cleaned_data["pdf"].size
        book.cover.save(f"{book.id}.jpg", ContentFile(form.cover_bytes), save=False)
        book.save()
        messages.success(request, f"«{book.title}» ya está disponible en la biblioteca.")
        return redirect("panel")
    return render(request, "catalog/panel.html", {"form": form, "books": Book.objects.all(), "max_pdf_mb": settings.MAX_PDF_MB})


@staff_required
@require_POST
def delete_book(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    title = book.title
    pdf_name, cover_name = book.pdf.name, book.cover.name
    book.delete()
    book.pdf.storage.delete(pdf_name)
    book.cover.storage.delete(cover_name)
    messages.success(request, f"«{title}» se eliminó de la biblioteca.")
    return redirect("panel")


def _file_response(request, file_field, *, download=False, title=""):
    try:
        path = Path(file_field.path)
        size = path.stat().st_size
    except (FileNotFoundError, ValueError):
        raise Http404("Archivo no encontrado")
    content_type = "application/pdf"
    filename = f"{title}.pdf" if download else None
    disposition = content_disposition_header(download, filename) if download else 'inline'
    common = {
        "Content-Type": content_type,
        "Content-Disposition": disposition,
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=3600",
    }
    range_header = request.headers.get("Range", "")
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip()) if range_header else None
    if range_header and not match:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response
    if match:
        first, last = match.groups()
        if not first and not last:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            suffix = int(last)
            start, end = max(0, size - suffix), size - 1
        if start >= size or end < start or size == 0:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = end - start + 1

        def chunks():
            with path.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining:
                    chunk = source.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        response = StreamingHttpResponse(chunks(), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(length)
    else:
        response = FileResponse(path.open("rb"), content_type=content_type)
        response["Content-Length"] = str(size)
    for key, value in common.items():
        response[key] = value
    return response


def pdf_file(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    return _file_response(request, book.pdf)


@require_GET
def pdf_page(request, book_id, page_number):
    book = get_object_or_404(Book, pk=book_id)
    if page_number < 1 or page_number > book.pages:
        raise Http404("Página no encontrada")
    try:
        source_path = Path(book.pdf.path)
        stat = source_path.stat()
        key = f"pdf-v1:{book.pk}:{stat.st_size}:{stat.st_mtime_ns}:{page_number}"
        page_cache = caches["pdf_pages"]
        try:
            content = page_cache.get(key)
        except OSError:
            content = None
        if content is None:
            with fitz.open(source_path) as source:
                if page_number > source.page_count:
                    raise Http404("Página no encontrada")
                with fitz.open() as single_page:
                    single_page.insert_pdf(source, from_page=page_number - 1, to_page=page_number - 1)
                    content = single_page.tobytes()
            # Bound disk usage; unusual oversized pages are still served normally.
            if len(content) <= 8 * 1024 * 1024:
                try:
                    page_cache.set(key, content)
                except OSError:
                    pass  # A full/unavailable cache must not break reading.
    except (FileNotFoundError, ValueError, fitz.FileDataError):
        raise Http404("PDF no disponible")
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = "inline"
    response["Content-Length"] = str(len(content))
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def download_book(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    return _file_response(request, book.pdf, download=True, title=book.title)


def cover_file(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    try:
        response = FileResponse(book.cover.open("rb"), content_type="image/jpeg")
    except FileNotFoundError:
        raise Http404("Portada no encontrada")
    response["Cache-Control"] = "public, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def health(request):
    return HttpResponse("ok", content_type="text/plain")
