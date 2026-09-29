from django.urls import path
from . import request_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("privacidad/", request_views.privacy, name="privacy"),
    path("solicitar/", request_views.request_book, name="request_book"),
    path("solicitar/acceso/", request_views.student_login, name="student_login"),
    path("solicitar/acceso/callback/", request_views.student_callback, name="student_callback"),
    path("solicitar/<uuid:request_id>/", request_views.request_book_wait, name="request_book_wait"),
    path("solicitar/<uuid:request_id>/estado/", request_views.request_book_status, name="request_book_status"),
    path("login", views.login_view, name="login"),
    path("login/", views.login_view),
    path("salir/", views.logout_view, name="logout"),
    path("panel/", views.panel, name="panel"),
    path("panel/libro/<uuid:book_id>/editar/", views.edit_book, name="edit_book"),
    path("panel/libro/<uuid:book_id>/eliminar/", views.delete_book, name="delete_book"),
    path("libro/<uuid:book_id>/", views.book_detail, name="book_detail"),
    path("libro/<uuid:book_id>/leer/", views.read_book, name="read_book"),
    path("libro/<uuid:book_id>/buscar/", views.search_book, name="search_book"),
    path("libro/<uuid:book_id>/pagina/<int:page_number>/", views.pdf_page, name="pdf_page"),
    path("libro/<uuid:book_id>/archivo/", views.pdf_file, name="pdf_file"),
    path("libro/<uuid:book_id>/descargar/", views.download_book, name="download_book"),
    path("libro/<uuid:book_id>/portada/", views.cover_file, name="cover_file"),
    path("health/", views.health, name="health"),
]
