import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0002_bookpagetext"),
    ]

    operations = [
        migrations.CreateModel(
            name="BookRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=240, verbose_name="título")),
                ("author", models.CharField(blank=True, max_length=180, verbose_name="autor")),
                ("encrypted_viewer_url", models.TextField(blank=True, verbose_name="URL cifrada del visor")),
                ("status", models.CharField(choices=[("queued", "En espera"), ("processing", "Procesando"), ("completed", "Completado"), ("failed", "Fallido")], db_index=True, default="queued", max_length=12, verbose_name="estado")),
                ("pages_done", models.PositiveIntegerField(default=0, verbose_name="páginas procesadas")),
                ("total_pages", models.PositiveIntegerField(default=0, verbose_name="páginas totales")),
                ("error_message", models.CharField(blank=True, max_length=500, verbose_name="mensaje de error")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="fecha de solicitud")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="última actualización")),
                ("book", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requests", to="catalog.book")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="book_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(status__in=["queued", "processing"]),
                        fields=["user"],
                        name="one_active_book_request_per_user",
                    ),
                ],
            },
        ),
    ]
