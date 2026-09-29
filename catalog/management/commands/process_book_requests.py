"""Process student book requests with one durable VPS worker."""

from django.core.management.base import BaseCommand, CommandError

from catalog.request_worker import WorkerAlreadyRunning, run_worker


class Command(BaseCommand):
    help = "Procesa solicitudes de libros en segundo plano."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Procesar como máximo una solicitud y salir")
        parser.add_argument("--poll-interval", type=float, default=3.0)

    def handle(self, *args, **options):
        try:
            run_worker(once=options["once"], poll_interval=options["poll_interval"])
        except WorkerAlreadyRunning as error:
            raise CommandError(str(error)) from error
        except ValueError as error:
            raise CommandError(str(error)) from error
