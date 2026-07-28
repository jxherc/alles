# alles

> traducción revisada el 21 de julio de 2026 · fuente canónica: `README.md` · revisión:
> `phase10-canonical-2026-07-21`

[english](../../README.md) · [français](README.fr.md) · **español** · [简体中文](README.zh-Hans.md) ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

**alles** es una aplicación personal autoalojada. Un único programa de Python reúne Aide,
búsqueda, correo, documentos Markdown enlazados, diario, archivos, calendario, tareas, finanzas,
fotos, contactos y una bóveda cifrada. Los datos locales permanecen en una carpeta bajo tu control.
No hay telemetría; los proveedores externos solo reciben las solicitudes que tú decides enviarles.

## inicio rápido

Necesitas Python 3.11 o una versión posterior.

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

Abre `http://localhost:6769`. No hace falta una clave API para iniciar. Añade un modelo en
**ajustes → modelos** solo si quieres usar Aide.

Para una instalación administrada en macOS/Linux, ejecuta `./alles install`. `alles update` prepara
y comprueba una versión nueva; `alles update rollback` restaura el par anterior de código y datos.
`./alles uninstall` conserva los datos personales.

Docker:

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

El puerto limitado a la interfaz local mantiene una instalación nueva en este dispositivo.

## datos, red y copias de seguridad

Alles está diseñado para una sola persona. Antes de permitir acceso por red, activa la autenticación,
usa una contraseña de propietario fuerte y define una `secret_key` real. Lee la
[sección de seguridad](../../specifications.md#security--read-before-exposing-it) antes de exponerlo.

En **ajustes → copia de seguridad** puedes crear una copia local cifrada o enviarla manualmente a
WebDAV o a un almacenamiento compatible con S3. Guarda la clave de recuperación por separado. Una
restauración se verifica y prepara antes de modificar los datos activos.

## más información

La lista completa de aplicaciones, rutas y arquitectura está en
[`specifications.md`](../../specifications.md). Las dependencias y sus licencias se enumeran en
[`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

## licencia

MIT. Consulta [`LICENSE`](../../LICENSE).
