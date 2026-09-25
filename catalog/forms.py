import fitz
from django import forms
from django.conf import settings

from .models import Book


class BookUploadForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ["title", "author", "description", "pdf"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ej. Cálculo diferencial"}),
            "author": forms.TextInput(attrs={"placeholder": "Autor o institución"}),
            "description": forms.Textarea(attrs={"placeholder": "Una breve descripción del contenido", "rows": 4}),
            "pdf": forms.ClearableFileInput(attrs={"accept": ".pdf,application/pdf"}),
        }

    def clean_pdf(self):
        uploaded = self.cleaned_data["pdf"]
        if not uploaded.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Selecciona un archivo con extensión .pdf.")
        if uploaded.size > settings.MAX_PDF_MB * 1024 * 1024:
            raise forms.ValidationError(f"El archivo supera el límite de {settings.MAX_PDF_MB} MB.")
        uploaded.seek(0)
        if uploaded.read(5) != b"%PDF-":
            raise forms.ValidationError("El archivo no tiene una cabecera PDF válida.")
        uploaded.seek(0)
        try:
            if hasattr(uploaded, "temporary_file_path"):
                document = fitz.open(uploaded.temporary_file_path())
            else:
                document = fitz.open(stream=uploaded.read(), filetype="pdf")
            with document:
                if document.is_encrypted or document.page_count < 1:
                    raise forms.ValidationError("El PDF está protegido o no tiene páginas.")
                first_page = document.load_page(0)
                bounds = first_page.rect
                scale = min(2.0, 640 / max(bounds.width, bounds.height, 1))
                pixmap = first_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                self.cover_bytes = pixmap.tobytes("jpeg", jpg_quality=84)
                self.page_count = document.page_count
        except forms.ValidationError:
            raise
        except Exception as exc:
            raise forms.ValidationError("No se pudo leer el PDF. Verifica que no esté dañado.") from exc
        finally:
            uploaded.seek(0)
        return uploaded
