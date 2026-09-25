from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login", views.login_view, name="login"),
    path("login/", views.login_view),
    path("salir/", views.logout_view, name="logout"),
    path("panel/", views.panel, name="panel"),
    path("panel/libro/<uuid:book_id>/eliminar/", views.delete_book, name="delete_book"),
    path("libro/<uuid:book_id>/", views.book_detail, name="book_detail"),
    path("libro/<uuid:book_id>/leer/", views.read_book, name="read_book"),
    path("libro/<uuid:book_id>/buscar/", views.search_book, name="search_book"),
    path("libro/<uuid:book_id>/archivo/", views.pdf_file, name="pdf_file"),
    path("libro/<uuid:book_id>/descargar/", views.download_book, name="download_book"),
    path("libro/<uuid:book_id>/portada/", views.cover_file, name="cover_file"),
    path("health/", views.health, name="health"),
]
