import uuid

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
    def size_mb(self):
        return round(self.file_size / (1024 * 1024), 1)

    @property
    def size_label(self):
        if self.file_size < 1024 * 1024:
            return f"{max(1, round(self.file_size / 1024))} KB"
        return f"{self.size_mb} MB"
