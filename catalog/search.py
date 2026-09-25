"""Build a small, persistent text index without keeping whole PDFs in memory."""

import re

import fitz

from .models import BookPageText


MAX_MATCHES = 10000


def index_book(book):
    indexed = set(BookPageText.objects.filter(book=book).values_list("page_number", flat=True))
    if len(indexed) >= book.pages:
        return
    pending = []
    with fitz.open(book.pdf.path) as document:
        for index in range(document.page_count):
            number = index + 1
            if number in indexed:
                continue
            pending.append(BookPageText(
                book=book,
                page_number=number,
                text=document[index].get_text("text"),
            ))
            if len(pending) >= 20:
                BookPageText.objects.bulk_create(pending, ignore_conflicts=True)
                pending.clear()
    if pending:
        BookPageText.objects.bulk_create(pending, ignore_conflicts=True)


def find_in_book(book, query):
    needle = re.sub(r"\s+", " ", query).casefold()
    matches = []
    total = 0
    has_text = False
    for number, text in BookPageText.objects.filter(book=book).order_by("page_number").values_list("page_number", "text").iterator():
        has_text |= bool(text.strip())
        if not needle:
            continue
        searchable = re.sub(r"\s+", " ", text).casefold()
        start = 0
        while (position := searchable.find(needle, start)) != -1:
            total += 1
            if len(matches) < MAX_MATCHES:
                matches.append(number)
            start = position + len(needle)
    return {"matches": matches, "total": total, "has_text": has_text, "limited": total > MAX_MATCHES}
