from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="BookPageText",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("page_number", models.PositiveIntegerField()),
                ("text", models.TextField(blank=True)),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="indexed_pages", to="catalog.book")),
            ],
        ),
        migrations.AddConstraint(
            model_name="bookpagetext",
            constraint=models.UniqueConstraint(fields=("book", "page_number"), name="unique_book_page_text"),
        ),
    ]
