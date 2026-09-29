import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def pdf_path(instance, filename):
    return f"books/{instance.id}.pdf"


def cover_path(instance, filename):
    return f"covers/{instance.id}.jpg"


class Book(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField("título", max_length=240)
    author = models.CharField("autor", max_length=180, blank=True)
    description = models.TextField("descripción", max_length=3000, blank=True)
    pdf = models.FileField("PDF", upload_to=pdf_path)
    cover = models.FileField("portada", upload_to=cover_path)
    pages = models.PositiveIntegerField("páginas")
    file_size = models.PositiveBigIntegerField("tamaño en bytes")
    created_at = models.DateTimeField("fecha de carga", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def pdf_version(self):
        try:
            stat = Path(self.pdf.path).stat()
        except (OSError, ValueError):
            return ""
        return f"{stat.st_size}-{stat.st_mtime_ns}"

    @property
    def size_mb(self):
        return round(self.file_size / (1024 * 1024), 1)

    @property
    def size_label(self):
        if self.file_size < 1024 * 1024:
            return f"{max(1, round(self.file_size / 1024))} KB"
        return f"{self.size_mb} MB"


class BookPageText(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="indexed_pages")
    page_number = models.PositiveIntegerField()
    text = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["book", "page_number"], name="unique_book_page_text")]


class BookRequest(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "En espera"
        PROCESSING = "processing", "Procesando"
        COMPLETED = "completed", "Completado"
        FAILED = "failed", "Fallido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_requests")
    title = models.CharField("título", max_length=240)
    author = models.CharField("autor", max_length=180, blank=True)
    encrypted_viewer_url = models.TextField("URL cifrada del visor", blank=True)
    status = models.CharField("estado", max_length=12, choices=Status.choices, default=Status.QUEUED, db_index=True)
    pages_done = models.PositiveIntegerField("páginas procesadas", default=0)
    total_pages = models.PositiveIntegerField("páginas totales", default=0)
    error_message = models.CharField("mensaje de error", max_length=500, blank=True)
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests")
    created_at = models.DateTimeField("fecha de solicitud", auto_now_add=True)
    updated_at = models.DateTimeField("última actualización", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status__in=["queued", "processing"]),
                name="one_active_book_request_per_user",
            ),
        ]

    def __str__(self):
        return self.title
