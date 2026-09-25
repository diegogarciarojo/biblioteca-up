# Biblioteca UP

Catálogo público de libros PDF para `biblioteca.dns.army`. Permite buscar por título, autor o descripción; muestra la primera página como portada; ofrece lectura en línea con PDF.js y descarga del PDF original. El administrador entra en `/login` para publicar y eliminar libros.

Los PDFs, portadas y la base SQLite viven en el volumen persistente `library_data`. No se guardan en GitHub. PDF.js y las fuentes se distribuyen con el proyecto, por lo que el lector no necesita cargar recursos desde terceros. Sus licencias están en `static/pdfjs/LICENSE` y `static/fonts/LICENSE-*.txt`.

## Puesta en marcha en Ubuntu (AWS)

Necesitas Docker Engine con el plugin Docker Compose, un registro A de `biblioteca.dns.army` apuntando a la IP pública de la VPS y los puertos TCP 80 y 443 abiertos en el Security Group de AWS y en el firewall del sistema. Si tu IP pública cambia, actualiza el registro de dynv6 o usa una Elastic IP. [Caddy obtiene y renueva HTTPS automáticamente](https://caddyserver.com/docs/automatic-https) cuando el dominio apunta a la VPS y esos puertos son accesibles.

```bash
git clone URL_DE_TU_REPOSITORIO biblioteca-up
cd biblioteca-up
sh scripts/init-env.sh
docker compose up -d --build
docker compose exec app python manage.py createsuperuser
```

En `createsuperuser` eliges tu usuario y contraseña de administrador. Luego abre `https://biblioteca.dns.army/login`. El contenedor vuelve a iniciar tras reinicios de la VPS (`restart: unless-stopped`). Puedes ver su estado con `docker compose ps` y sus registros con `docker compose logs -f`.

## Actualizar y respaldar

Para actualizar el código: `git pull && docker compose up -d --build`. El volumen de libros se conserva. Antes de cambios importantes, respalda el volumen `library_data` y el archivo `.env`; un clon de Git por sí solo no contiene la biblioteca subida. Para exportar los datos con Docker:

```bash
docker compose stop app
docker run --rm -v "$(basename "$PWD")_library_data:/source:ro" -v "$PWD:/backup" alpine tar czf /backup/biblioteca-datos.tar.gz -C /source .
docker compose start app
```

Comprueba el nombre real del volumen con `docker volume ls` si cambiaste el nombre del proyecto Compose. Conserva la copia fuera de la VPS.

## Desarrollo local

Con Python 3.12: crea un entorno virtual, instala `requirements.txt`, ejecuta `python manage.py migrate` y `python manage.py runserver` con `DJANGO_DEBUG=1`. Los recursos de PDF.js ya están en `static/pdfjs`. La administración de Django también está disponible en `/django-admin/` para gestionar cuentas; los libros se publican desde `/panel/`.

## Límites y funcionamiento

- El límite predeterminado por PDF es 1 GB; se puede ajustar con `MAX_PDF_MB` en `.env` y `max_size` en `deploy/Caddyfile`.
- La primera página se convierte a JPEG al publicar. Se rechazan PDFs dañados, vacíos o protegidos con contraseña.
- La lectura usa peticiones HTTP por rangos y dibuja las páginas con PDF.js, lo que evita depender del visor PDF propio del navegador. Algunas características avanzadas del PDF (formularios interactivos, firmas, multimedia) se conservan en el archivo descargado, pero no se ofrecen en el lector integrado.
- La aplicación está pensada para una VPS y un administrador. Para catálogos o tráfico masivos sería aconsejable migrar SQLite a PostgreSQL y los archivos a almacenamiento de objetos.
