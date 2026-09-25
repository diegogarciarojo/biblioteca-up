"""Build a small, persistent text index without keeping whole PDFs in memory."""

import re
import unicodedata

import fitz

from .models import BookPageText


MAX_MATCHES = 10000


def normalize_search(text):
    text = unicodedata.normalize("NFD", text.casefold())
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.category(c).startswith("M")))


def index_book(book, max_pages=None):
    indexed = set(BookPageText.objects.filter(book=book).values_list("page_number", flat=True))
    pending = []
    processed = 0
    with fitz.open(book.pdf.path) as document:
        total_pages = document.page_count
        if book.pages != total_pages:
            book.pages = total_pages
            book.save(update_fields=["pages"])
        if len(indexed) >= total_pages:
            return len(indexed), total_pages
        for index in range(total_pages):
            number = index + 1
            if number in indexed:
                continue
            pending.append(BookPageText(
                book=book,
                page_number=number,
                text=document[index].get_text("text"),
            ))
            processed += 1
            if len(pending) >= 20:
                BookPageText.objects.bulk_create(pending, ignore_conflicts=True)
                pending.clear()
            if max_pages is not None and processed >= max_pages:
                break
    if pending:
        BookPageText.objects.bulk_create(pending, ignore_conflicts=True)
    return BookPageText.objects.filter(book=book).count(), total_pages


def find_in_book(book, query):
    needle = normalize_search(query)
    matches = []
    total = 0
    has_text = False
    for number, text in BookPageText.objects.filter(book=book).order_by("page_number").values_list("page_number", "text").iterator():
        has_text |= bool(text.strip())
        if not needle:
            continue
        searchable = normalize_search(text)
        start = 0
        while (position := searchable.find(needle, start)) != -1:
            total += 1
            if len(matches) < MAX_MATCHES:
                matches.append(number)
            start = position + len(needle)
    return {"matches": matches, "total": total, "has_text": has_text, "limited": total > MAX_MATCHES}
