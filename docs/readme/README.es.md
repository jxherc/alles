# alles

> traducción revisada el 27 de octubre de 2026 · fuente canónica: `README.md` · revisión:
> `davinci-canonical-2026-10-27`

alles es una alternativa privada al ecosistema de Google. tu correo, calendario, documentos, archivos, fotos, contactos, tareas, dinero y contraseñas viven en una sola app, en una máquina que tú controlas, y no en los servidores de otra persona.

alles está pensado para una sola persona. tus datos principales se guardan en una carpeta que tú controlas, y tú decides qué servicios externos conectar. también incluye aide, un asistente de IA que puede trabajar con las apps cuando apruebas sus acciones. úsalo si te resulta útil; las herramientas locales funcionan sin un modelo de IA.

[english](../../README.md) · [français](README.fr.md) · **español** · [简体中文](README.zh-Hans.md) ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

## primeros pasos

necesitas git y Python 3.11 o una versión más reciente. en Debian o Ubuntu, ejecuta antes `sudo apt install git python3-venv`. después, en macOS o Linux:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

abre [http://localhost:6769](http://localhost:6769) y sigue la configuración. no necesitas una clave de API para empezar.

de forma predeterminada, a alles solo se puede acceder desde este dispositivo, y arranca sin contraseña. **antes de ponerlo en tu red**, activa la autenticación, define una contraseña de propietario segura y una `SECRET_KEY`, y elige el perfil de acceso adecuado. el acceso desde la red local y el acceso público tienen requisitos distintos; lee primero [seguridad](../../specifications.md#security--read-before-exposing-it) y [.env.example](../../.env.example).

si prefieres usar Docker:

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

así el acceso queda limitado a tu dispositivo y tus datos se guardan en el volumen `alles-data`. conserva ese volumen cuando reemplaces el contenedor.

### usarlo desde otro dispositivo

para abrir alles desde tu teléfono u otro ordenador, en tu red local o a través de [Tailscale](https://tailscale.com), ponle primero una contraseña. escribe estas líneas en un archivo `.env` dentro de la carpeta de alles:

```dotenv
ALLES_ACCESS_PROFILE=lan
AUTH_ENABLED=true
AUTH_PASSWORD=a-long-password-only-you-know
SECRET_KEY=paste-a-random-key-here
ALLES_HOST=100.101.102.103
```

genera la clave con `python3 -c "import secrets; print(secrets.token_hex(32))"`. pon en `ALLES_HOST` la dirección que usan tus otros dispositivos, por ejemplo la IP de Tailscale del servidor, para que alles no escuche en ningún otro sitio. luego vuelve a iniciar `python app.py` y abre esa dirección en el puerto 6769, por ejemplo `http://100.101.102.103:6769`.

## qué puedes hacer

| app | para qué sirve |
| --- | --- |
| home | ver tu día, abrir tus apps y apuntar una tarea al vuelo |
| aide | chatear con un modelo configurado y aprobar acciones en tu espacio de trabajo |
| andromeda | buscar en la web y, si quieres, obtener un resumen con fuentes |
| plan | llevar un calendario, tareas, recordatorios y cuentas atrás |
| inbox | leer el correo y gestionar contactos después de conectar tu cuenta |
| docs | escribir notas en Markdown y entradas de diario |
| files | explorar almacenamiento local o conectado, copias sin conexión y fotos |
| library | guardar artículos y listas de lectura |
| health | registrar hábitos y datos de salud |
| finance | controlar cuentas, transacciones, presupuestos y suscripciones |
| vault | guardar secretos, contraseñas y llaves de acceso cifrados |
| server | revisar el estado, los ajustes de acceso, las copias de seguridad y las actualizaciones |

las transacciones manuales nuevas que guardas en el registro financiero local se pueden deshacer.
deshacer elimina solo esa transacción concreta, y solo mientras sus datos guardados no hayan cambiado;
si la respuesta se corta, queda un reintento disponible para la misma transacción. las transacciones de Actual,
las importaciones y las transferencias siguen sus flujos habituales de revisión y eliminación.

algunas cosas necesitan una conexión antes de funcionar. añade tu cuenta IMAP/SMTP para el correo, conecta un servicio para el almacenamiento en línea o la banca, y añade un modelo en **settings → models** si quieres usar aide. también funcionan los modelos locales con Ollama.

la interfaz está disponible en english, français, español, 简体中文, 繁體中文, 日本語, 한국어 y العربية. elige la tuya en **ajustes → idioma y región**.

[specifications.md](../../specifications.md) explica en detalle el comportamiento de las apps, la arquitectura, la API y la configuración.

## tus datos y copias de seguridad

tu base de datos y los archivos que gestiona alles están en `data/` de forma predeterminada. define `ALLES_DATA` si los quieres en otro sitio. mantén esa carpeta privada y haz copias de seguridad de ella. los proveedores externos reciben las solicitudes que les envías a través de sus conexiones.

abre **settings → backup** para descargar una copia de seguridad cifrada. también puedes enviar una a mano a una carpeta WebDAV por HTTPS que ya exista o a un bucket compatible con S3, o activar copias locales diarias durante la configuración inicial. guarda tu clave de recuperación en algún lugar fuera de alles para poder acceder a ella aunque la app deje de funcionar.

alles comprueba la copia y prepara la restauración antes de aplicarla. detén la app y luego sigue el comando que te indique. lee [los detalles de copia y restauración](../../specifications.md#your-data-where-everything-lives) antes de mover una instalación existente.

## instalarlo como servicio

si quieres que alles se ejecute como servicio en macOS o Linux, ejecuta `bash alles install`. crea su propio entorno de Python y añade el comando `alles`. usa `alles update` para actualizarlo, o `alles update rollback` para volver al código y los datos anteriores. `bash alles uninstall` conserva tus datos personales. `bash alles --help` muestra la lista de comandos.

está hecho con FastAPI, SQLite, JavaScript vanilla y CSS. no hay paso de compilación del frontend. los detalles técnicos están en [specifications.md](../../specifications.md).

## historial de versiones

[davinci](../../docs/releases/davinci.md) documenta el hito completado de flujos de trabajo diarios.

## créditos y licencia

aide se inspiró en [odysseus](https://github.com/pewdiepie-archdaemon/odysseus). alles es una implementación independiente; [acknowledgments.md](../../ACKNOWLEDGMENTS.md) da crédito a ese proyecto y a los demás trabajos que usa. las licencias de terceros están en los [avisos de terceros](../../THIRD_PARTY_NOTICES.md).

alles se publica bajo la [licencia MIT](../../LICENSE).
