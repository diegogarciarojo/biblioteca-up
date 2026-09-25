from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("catalog.urls")),
    path("django-admin/", admin.site.urls),
]
