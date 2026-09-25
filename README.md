# Biblioteca UP

Catálogo público de libros PDF para `biblioteca.dns.army`. Permite buscar por título, autor o descripción; muestra la primera página como portada; ofrece lectura en línea con PDF.js y descarga del PDF original. El administrador entra en `/login` para publicar y eliminar libros.

Los PDFs, portadas y la base SQLite viven en el volumen persistente `library_data`. No se guardan en GitHub. PDF.js y las fuentes se distribuyen con el proyecto, por lo que el lector no necesita cargar recursos desde terceros. Sus licencias están en `static/pdfjs/LICENSE` y `static/fonts/LICENSE-*.txt`.

## Puesta en marcha en Ubuntu (AWS)

### 1. Dominio y puertos

En la terminal de la VPS, consulta su IPv4 pública:

```bash
curl -4 https://api.ipify.org; echo
```

En dynv6, abre la zona `biblioteca.dns.army` y pon esa IP en el campo de dirección IPv4 (registro A). Si no configuraste IPv6 en la VPS, deja el registro AAAA vacío. En el **Security Group** de AWS permite tráfico entrante TCP 80 y 443 desde `0.0.0.0/0`. Si usas IPv6, permite también `::/0` en esos puertos. Si tienes UFW activo, permite igualmente 80 y 443. Puedes comprobar el DNS desde Ubuntu con `getent ahostsv4 biblioteca.dns.army`; debe mostrar la misma IP.

Si la VPS usa una IP pública que cambia al detenerla, reserva una Elastic IP o configura la actualización dinámica de dynv6. La renovación del certificado necesita que el dominio siga apuntando a esta VPS.

Comprueba que 80 y 443 estén libres antes de arrancar Caddy, sobre todo si 3x-ui u otro proxy está en la misma VPS:

```bash
sudo ss -ltnp | grep -E ':(80|443)[[:space:]]' || true
```

Si aparece un proceso usando esos puertos, resuelve ese conflicto antes de iniciar esta aplicación.

### 2. Docker

Si `docker compose version` funciona, pasa al paso 3. Si Docker no está instalado, usa el [repositorio oficial para Ubuntu](https://docs.docker.com/engine/install/ubuntu/):

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Si ya tienes otra instalación de Docker pero no funciona Compose, revisa ese caso antes de ejecutar el bloque de instalación, para evitar conflictos con paquetes existentes.

### 3. Aplicación y administrador

```bash
git clone https://github.com/diegogarciarojo/biblioteca-up.git biblioteca-up
cd biblioteca-up
sh scripts/init-env.sh
sudo docker compose up -d --build
sudo docker compose exec app python manage.py createsuperuser
```

En `createsuperuser` eliges tu usuario y contraseña. Luego abre `https://biblioteca.dns.army/login`. Comprueba el estado con `sudo docker compose ps`, los mensajes de certificados con `sudo docker compose logs caddy --tail=80` y HTTPS con `curl -I https://biblioteca.dns.army`.

[Caddy obtiene, renueva y guarda automáticamente los certificados](https://caddyserver.com/docs/automatic-https) en el volumen persistente `caddy_data`, siempre que el DNS apunte a la VPS y 80/443 sigan accesibles. No necesitas Certbot ni una tarea cron. Docker y los contenedores vuelven a iniciar tras reinicios (`restart: unless-stopped`).

## Actualizar y respaldar

Para actualizar el código: `git pull && sudo docker compose up -d --build`. El volumen de libros se conserva. Antes de cambios importantes, respalda el volumen `library_data` y el archivo `.env`; un clon de Git por sí solo no contiene la biblioteca subida. Para exportar los datos con Docker:

```bash
sudo docker compose stop app
sudo docker run --rm -v "$(basename "$PWD")_library_data:/source:ro" -v "$PWD:/backup" alpine tar czf /backup/biblioteca-datos.tar.gz -C /source .
sudo docker compose start app
```

Comprueba el nombre real del volumen con `docker volume ls` si cambiaste el nombre del proyecto Compose. Conserva la copia fuera de la VPS.

## Desarrollo local

Con Python 3.12: crea un entorno virtual, instala `requirements.txt`, ejecuta `python manage.py migrate` y `python manage.py runserver` con `DJANGO_DEBUG=1`. Los recursos de PDF.js ya están en `static/pdfjs`. La administración de Django también está disponible en `/django-admin/` para gestionar cuentas; los libros se publican desde `/panel/`.

## Límites y funcionamiento

- El límite predeterminado por PDF es 1 GB; se puede ajustar con `MAX_PDF_MB` en `.env` y `max_size` en `deploy/Caddyfile`.
- La primera página se convierte a JPEG al publicar. Se rechazan PDFs dañados, vacíos o protegidos con contraseña.
- La lectura usa peticiones HTTP por rangos y dibuja las páginas con PDF.js, lo que evita depender del visor PDF propio del navegador. Algunas características avanzadas del PDF (formularios interactivos, firmas, multimedia) se conservan en el archivo descargado, pero no se ofrecen en el lector integrado.
- La aplicación está pensada para una VPS y un administrador. Para catálogos o tráfico masivos sería aconsejable migrar SQLite a PostgreSQL y los archivos a almacenamiento de objetos.
