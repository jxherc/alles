# alles

> traducción revisada el 27 de octubre de 2026 · fuente canónica: `README.md` · revisión:
> `davinci-canonical-2026-10-27`

alles es una alternativa privada al ecosistema de Google. tu correo, calendario, documentos, archivos, fotos, contactos, tareas, dinero y contraseñas viven en una sola app, en una máquina que tú controlas, y no en los servidores de otra persona.

alles está pensado para una sola persona. tus datos principales se guardan en una carpeta que tú controlas, y tú decides qué servicios externos conectar. también incluye aide, un asistente de IA que puede trabajar con las apps cuando apruebas sus acciones. úsalo si te resulta útil; las herramientas locales funcionan sin un modelo de IA.

[english](../../README.md) · [français](README.fr.md) · **español** · [简体中文](README.zh-Hans.md) ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

## primeros pasos

en macOS o Linux, ejecuta:

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

descarga solo la app, la instala como servicio en segundo plano y muestra cada paso mientras avanza. alles sigue funcionando cuando cierras la terminal y vuelve a arrancar después de reiniciar el equipo. necesita Python 3.11 o una versión más reciente; en Debian o Ubuntu, el instalador ofrece añadir el módulo venv de Python si falta.

después abre [http://localhost:6769](http://localhost:6769) y sigue la configuración. no necesitas una clave de API para empezar. a partir de ahí, el comando `alles` se encarga del resto: solo, muestra si alles está funcionando y cómo abrirlo, `alles doctor` revisa la instalación y `alles config` abre el archivo de ajustes.

por defecto, solo se puede acceder a alles desde este dispositivo y arranca sin contraseña. **antes de ponerlo en tu red**, ponle una contraseña y elige quién puede abrirlo: `alles access lan` hace ambas cosas. el acceso en la red local y el acceso público tienen requisitos distintos; lee primero la sección de [seguridad](../../specifications.md#security--read-before-exposing-it). justo después de instalarlo, pregunta si quieres una contraseña (8 caracteres o más; `alles password` la crea o la cambia después) y si tus otros dispositivos deben poder abrirlo.

### usarlo desde otro dispositivo

```bash
alles access lan
```

pide una contraseña de propietario, reinicia alles para que tu teléfono y tus otros ordenadores puedan abrirlo y muestra las direcciones que debes usar, por ejemplo `http://100.101.102.103:6769`. `alles access device` vuelve a dejarlo solo para este ordenador.

### ejecutarlo desde el código fuente

para desarrollo, o para ejecutarlo sin el servicio. en Debian o Ubuntu, ejecuta antes `sudo apt install git python3-venv`.

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

`python cli.py access lan` también permite aquí el acceso desde otros dispositivos; después vuelve a iniciar `python app.py`.

si prefieres usar Docker:

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

así el acceso queda limitado a tu dispositivo y tus datos se guardan en el volumen `alles-data`. conserva ese volumen cuando reemplaces el contenedor.

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

en correo, elige gmail, outlook, icloud, yahoo o fastmail y el formulario se rellena solo; gmail inicia sesión con google tras una configuración única de google cloud que alles te guía paso a paso (descarga el json del cliente y suéltalo). la sincronización bancaria está en **finanzas → conexiones bancarias** (plaid para la mayoría de bancos de canadá y ee. uu., o simplefin).

la interfaz está disponible en english, français, español, 简体中文, 繁體中文, 日本語, 한국어 y العربية. elige la tuya en **ajustes → idioma y región**.

[specifications.md](../../specifications.md) explica en detalle el comportamiento de las apps, la arquitectura, la API y la configuración.

## tus datos y copias de seguridad

una vez instalado, alles guarda tu base de datos y los archivos que gestiona en `~/.local/share/alles/data` en Linux o en `~/Library/Application Support/Alles/data` en macOS; `alles status` muestra dónde. si lo ejecutas desde el código fuente, usa `data/`, o `ALLES_DATA` si lo defines. mantén esa carpeta privada y haz copias de seguridad de ella. los proveedores externos reciben las solicitudes que les envías a través de sus conexiones.

abre **settings → backup** para descargar una copia de seguridad cifrada. también puedes enviar una a mano a una carpeta WebDAV por HTTPS que ya exista o a un bucket compatible con S3, o activar copias locales diarias durante la configuración inicial. guarda tu clave de recuperación en algún lugar fuera de alles para poder acceder a ella aunque la app deje de funcionar.

alles comprueba la copia y prepara la restauración antes de aplicarla. detén la app y luego sigue el comando que te indique. lee [los detalles de copia y restauración](../../specifications.md#your-data-where-everything-lives) antes de mover una instalación existente.

## actualizar y desinstalar

`alles update` instala la versión más reciente y guarda la anterior, para que `alles update rollback` pueda volver a ella con tus datos. `alles uninstall` quita alles y conserva tus datos personales. `alles help` muestra todos los comandos.

está hecho con FastAPI, SQLite, JavaScript vanilla y CSS. no hay paso de compilación del frontend. los detalles técnicos están en [specifications.md](../../specifications.md).

## historial de versiones

[davinci](../../docs/releases/davinci.md) documenta el hito completado de flujos de trabajo diarios.

## créditos y licencia

aide se inspiró en [odysseus](https://github.com/pewdiepie-archdaemon/odysseus). alles es una implementación independiente; [acknowledgments.md](../../ACKNOWLEDGMENTS.md) da crédito a ese proyecto y a los demás trabajos que usa. las licencias de terceros están en los [avisos de terceros](../../THIRD_PARTY_NOTICES.md).

alles se publica bajo la [licencia MIT](../../LICENSE).
