# Biblioteca UP

Catálogo público de libros PDF: búsqueda, portada generada desde la primera página, lectura con PDF.js y descarga del archivo original. El administrador entra por `/login` para subir y eliminar libros. Los PDFs, portadas y la base de datos se guardan en un volumen de la VPS, no en GitHub.

## Instalación en Ubuntu (AWS)

Pega **una sola línea** en la terminal de tu VPS:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/diegogarciarojo/biblioteca-up/main/install.sh)"
```

El instalador pregunta si quieres dominio, propone `biblioteca.dns.army`, prepara Docker, descarga la aplicación, configura el proxy y te pide el usuario y contraseña de administrador. Primero comprueba que el registro A apunte a la IPv4 pública de la VPS; si ya coincide, no espera una actualización de dynv6. Si eliges un dominio de dynv6, puede pedirte el **token HTTP de esa zona** para corregir el registro A y mantenerlo actualizado cada 10 minutos. El token se introduce de forma oculta y se guarda solo en la VPS. Si dynv6 tarda en responder, la instalación continúa y el temporizador vuelve a intentarlo. Si no proporcionas token, el dominio debe apuntar ya a la IPv4 de la VPS. Para un proveedor distinto de dynv6, crea el registro A en su panel antes de instalar.

Abre los puertos **TCP 80 y 443** en el Security Group de AWS. Si UFW está activo, el instalador configura esos puertos automáticamente. Los puertos deben estar libres en la VPS; si 3x-ui u otro servicio los usa, el instalador se detiene sin modificarlo. Si eliges continuar sin dominio, sirve la web por HTTP en la IP pública y solo requiere el puerto 80.

Con dominio y DNS correcto, [Caddy solicita y renueva el certificado HTTPS automáticamente](https://caddyserver.com/docs/automatic-https). Los certificados se conservan en un volumen Docker al actualizar o reiniciar. No necesitas Certbot. La [documentación de 3x-ui](https://github.com/MHSanaei/3x-ui/blob/main/docs/content/docs/en/config/ssl-certificates.mdx) también exige DNS correcto antes de emitir el certificado y recomienda que Caddy lo gestione cuando hay un proxy. [dynv6 requiere el token HTTP de la zona](https://dynv6.com/docs/apis) para que el instalador cambie el DNS; el nombre del dominio por sí solo no da permiso para hacerlo.

Al terminar, abre `https://biblioteca.dns.army` y `https://biblioteca.dns.army/login` (o el dominio que elegiste). Si no configuraste dominio, usa la URL `http://IP` que imprime el instalador. Sin HTTPS, la contraseña viajará sin cifrar; configura un dominio antes de usar la cuenta de administrador desde redes externas.

## Actualizaciones y datos

Para actualizar, ejecuta **la misma línea**. El instalador conserva la clave de Django, la base de datos, los PDFs, las portadas, el token dynv6 y los certificados. Si ya existe un superusuario, no vuelve a pedir credenciales. La aplicación y Caddy se reinician automáticamente tras reiniciar la VPS.

Para consultar los contenedores y sus registros:

```bash
sudo docker ps --filter label=org.biblioteca-up.managed=true
sudo docker logs --tail 80 biblioteca-up-app
sudo docker logs --tail 80 biblioteca-up-caddy
```

Respalda periódicamente el volumen `biblioteca-up_library_data` y `/opt/biblioteca-up/.env`. Si configuraste dynv6, respalda también `/etc/biblioteca-up/dynv6.token`. Un clon del repositorio no contiene los libros subidos.

```bash
sudo docker stop biblioteca-up-app
sudo docker run --rm -v biblioteca-up_library_data:/source:ro -v "$PWD:/backup" alpine tar czf /backup/biblioteca-datos.tar.gz -C /source .
sudo docker start biblioteca-up-app
```

## Desarrollo local

Con Python 3.12: crea un entorno virtual, instala `requirements.txt`, configura `.env` con `sh scripts/init-env.sh`, ejecuta `python manage.py migrate` y `python manage.py runserver` con `DJANGO_DEBUG=1`. Los recursos de PDF.js y las fuentes se incluyen en el repositorio; sus licencias están en `static/pdfjs/LICENSE` y `static/fonts/LICENSE-*.txt`.

El límite predeterminado por PDF es 1 GB, configurable en `.env` con `MAX_PDF_MB`. Para aumentar el tamaño máximo también hay que ajustar `max_size` en `deploy/Caddyfile.runtime` de la VPS. Los PDFs dañados, vacíos o protegidos con contraseña se rechazan. El lector usa solicitudes por rangos y PDF.js para verse de forma consistente en distintos navegadores; los formularios interactivos, firmas y multimedia avanzados quedan disponibles solo en el PDF descargado.
