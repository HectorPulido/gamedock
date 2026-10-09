# GameDock

Framework para ofrecer escritorios de juegos desde un navegador, extraído del
harness de Starloco. Tiene cuentas y configuración independientes de Dofus.

Incluye registro/login/logout, administrador inicial, catálogo editable, nombre y
banner, resoluciones por juego, límites globales y por cuenta, habilitación de
usuarios, cierre de instancias y CLI. Cada instancia ejecuta un comando en un
contenedor propio. El portal autentica HTTP y WebSocket hacia Xpra; las sesiones
no publican puertos al host.

## Primer inicio

Requisitos: servidor Linux con Docker Engine 26+ y Docker Compose. Arquitectura x86_64
probada. No requiere Dofus, Wine ni Python en el host para servir la plataforma.

```sh
git clone git@github.com:HectorPulido/gamedock.git
cd gamedock
cp .env.example .env
# Edita .env: ADMIN_PASSWORD debe tener al menos 12 caracteres.
docker build -t gamedock-runtime:local runtime
docker compose up -d --build
```

Abre `http://localhost:8080` y entra con `ADMIN_USER` y `ADMIN_PASSWORD`. El
administrador se crea en el primer arranque; cambiar `.env` no cambia contraseñas
existentes. La biblioteca inicial incluye un escritorio con xterm para comprobar
pantalla, teclado y ratón. En Administración puedes cambiar nombre, mensaje de
bienvenida, registro, límites, perfiles y estado de las cuentas.

Para acceso remoto configura `PUBLIC_URL` con el origen HTTPS exacto y coloca un
proxy HTTPS delante del portal, conservando rutas y query y permitiendo WebSocket
(Upgrade/Connection). Las cookies usan Secure cuando PUBLIC_URL usa HTTPS. El
portal se publica sólo en loopback por defecto. No publiques puertos de sesiones
ni el socket Docker. Los administradores son operadores de confianza: eligen
imágenes y comandos y el portal tiene acceso al daemon Docker.

## Lanzamiento con un comando

La CLI necesita Python 3 y no tiene dependencias adicionales.

```sh
python3 cli/gamedock.py --url http://localhost:8080 register jugador
python3 cli/gamedock.py login jugador
python3 cli/gamedock.py launch desktop --resolution 1920x1080
python3 cli/gamedock.py list
python3 cli/gamedock.py stop ID_DE_INSTANCIA
python3 cli/gamedock.py logout
```

`launch` imprime el ID y enlace al escritorio. Inicia sesión con la misma cuenta
en el navegador para conectarte. La contraseña se solicita sin incluirla en
argumentos. El token de CLI expira en 24 horas y se guarda con permisos 0600 en
`~/.config/gamedock/session.json`. `GAMEDOCK_URL` o `--url` eligen el servidor;
`--credentials` permite mantener sesiones separadas.

## Añadir un juego

Deriva una imagen de `gamedock-runtime:local`, instala el programa y mantén el
usuario `player` (UID 1000). El directorio de trabajo es `/data`, persistente por
cuenta y juego. Crea un perfil desde Administración o con la CLI como admin:

```json
{
  "id": "mi-juego",
  "name": "Mi juego",
  "description": "Un juego para tu comunidad",
  "banner": "https://example.com/banner.jpg",
  "image": "mi-juego:local",
  "command": ["/opt/game/start", "--server", "example.com"],
  "resolutions": ["1280x720", "1920x1080"],
  "env": { "LANG": "es_ES.UTF-8" }
}
```

```sh
python3 cli/gamedock.py profile mi-juego.json
python3 cli/gamedock.py launch mi-juego --resolution 1280x720
```

`command` es una lista de argumentos sin shell implícito. Si hace falta un shell,
el administrador puede indicar `["sh", "-c", "comando explícito"]`. Construye o
descarga la imagen en el servidor antes de lanzar: no se hacen pulls automáticos.
El banner por juego es una URL HTTP(S) de imagen opcional; la plataforma permite
mensaje de bienvenida e imagen de banner. Comandos, imágenes y variables de
lanzamiento sólo son visibles al administrador. No
uses las variables de perfiles para secretos individuales de usuarios.

El runtime usa Xvfb, Openbox y Xpra sin audio. Sirve para programas X11 y juegos
compatibles con renderizado de software. GPU, mandos, audio, anti-cheat y
aceleración 3D requieren adaptar la imagen y dispositivos; no se garantiza
compatibilidad con todos los juegos. Los límites iniciales por sesión son 4 GiB,
2 CPU y 256 procesos, configurados en `server/app.py`.

### Ejemplo listo para jugar: OpenTTD

```sh
docker build -t gamedock-openttd:local examples/openttd
./bin/gamedock profile examples/openttd/profile.json
./bin/gamedock launch openttd --resolution 1280x720
```

Incluye el juego libre y los gráficos OpenGFX desde los repositorios de Fedora.
No necesita archivos de un cliente comercial. La configuración y partidas viven
en `/data`. `./bin/gamedock` también acepta todos los comandos de la CLI anterior.

### Minecraft y Windows

`examples/minecraft/` incluye imagen y perfil para un launcher Java Linux.
Aporta tu cliente/launcher con librerías y recursos en
`examples/minecraft/client/launcher.jar`. Debe abrir una interfaz gráfica y ser
compatible con Java 21; adapta el comando si usa otro formato. No incluye cliente
ni omite autenticación/licencia. No es un launcher oficial universal.

```sh
docker build -t gamedock-minecraft:local examples/minecraft
python3 cli/gamedock.py profile examples/minecraft/profile.json
python3 cli/gamedock.py launch minecraft --resolution 1280x720
```

`examples/wine/` aporta un adaptador Windows: coloca los archivos del juego en
`examples/wine/client/`, ajusta `Game.exe`, construye `gamedock-wine:local` e importa
su `profile.json`. Conserva el prefijo Wine en `/data/wine`. La imagen histórica
Dofus de `upstream/` es sólo referencia, no una dependencia ejecutable.

## Persistencia y operación

- El volumen `gamedock_gamedock-data` guarda SQLite: cuentas, hashes scrypt,
  tokens revocables, perfiles, configuración e historial.
- `NAMESPACE-user-UID-JUEGO` guarda `/data`; el namespace es el nombre del proyecto
  Compose por defecto (`gamedock`). `GAMEDOCK_NAMESPACE` permite fijarlo de forma
  explícita con 1–40 letras minúsculas, números o guiones. Mantenlo estable y usa
  nombres distintos para instalaciones que no deban compartir archivos.
  Varias sesiones de la misma cuenta y
  juego comparten archivos. Para juegos que bloquean su perfil usa límite por
  usuario 1 o perfiles diferentes. Guarda antes de terminar; el cierre elimina
  el contenedor pero conserva el volumen.
- El estado se reconcilia con Docker al consultar/crear instancias. Reiniciar
  el portal conserva escritorios y cuentas. Logout revoca la conexión, no mata
  el juego. Desactivar una cuenta revoca tokens y termina sus instancias.
- `docker compose logs -f portal` muestra errores. No imprime tokens ni claves.
  Antes de retirar la plataforma termina las instancias desde Administración:
  `docker compose down` sólo detiene el portal, no sus contenedores de sesiones.
- Haz backup consistente de SQLite y volúmenes. No versiones `.env`, bases,
  sesiones ni clientes de juegos. Los archivos de código y los builds están
  completamente definidos por el repositorio.

## API

Mutaciones: `Content-Type: application/json`; usa `{}` si no llevan datos.
Autenticación: cookie HttpOnly o `Authorization: Bearer TOKEN`. No uses tokens en
URLs. Las instancias ajenas responden 404; el administrador puede gestionarlas.

| Método     | Ruta                                    | Uso                                     |
| ---------- | --------------------------------------- | --------------------------------------- |
| GET        | `/api/catalog`                          | Configuración pública, cuenta y juegos  |
| POST       | `/api/auth/register`, `/api/auth/login` | `{username, password}`                  |
| POST       | `/api/logout`                           | Revocar sesión actual                   |
| GET / POST | `/api/instances`                        | Listar / crear con `{game, resolution}` |
| DELETE     | `/api/instances/ID`                     | Terminar instancia                      |
| GET / WS   | `/desktop/ID/…`                         | Escritorio autenticado                  |
| PUT        | `/api/admin/settings`                   | Nombre, banner, registro, límites       |
| PUT        | `/api/admin/games`                      | Crear/reemplazar perfil                 |
| DELETE     | `/api/admin/games/ID`                   | Quitar perfil                           |
| GET        | `/api/admin/users`                      | Cuentas                                 |
| PATCH      | `/api/admin/users/ID`                   | `{enabled: true/false}`                 |

## Validación

Para ejecutar la suite completa en Linux, usando sólo el proyecto QA de Docker:

```sh
./scripts/qa.sh
```

Necesita Python 3 y Docker Compose con `--wait`, conserva credenciales QA fuera
del repositorio y deja capturas en `/tmp/gamedock-artifacts`. Comprueba también
que recrear el portal no reinicia los juegos y que los volúmenes sobreviven al
reemplazo de instancias. Ejecuta las pruebas del navegador secuencialmente, en
una red Docker estable; no uses la red del host mientras creas redes de sesiones.

```sh
docker build -t gamedock-portal:local .
docker run --rm -v "$PWD:/app:ro" gamedock-portal:local python -m unittest discover -s tests -v
```

`tests/live.py` comprueba API/CLI, comando nativo, dos escritorios reales,
resoluciones Xvfb, persistencia, proxy, aislamiento y puertos. Se ejecuta en el host
con Python 3 y CLI Docker contra un despliegue QA desechable en localhost:18088;
lee el bootstrap de `/tmp/gamedock-qa.env`. No lo uses contra cuentas reales.
`tests/browser.py` prueba registro, lanzamiento, píxeles del escritorio, entrada
real de teclado, revocación WebSocket, cierre y móvil. `tests/game_browser.py`
verifica los formularios de administración, el banner de imagen y OpenTTD real.
Construye su entorno con `tests/Dockerfile.browser`; escribe capturas en
`/artifacts`. El portal QA usa `PUBLIC_URL=http://gamedock-qa-portal-1:8080` y el
navegador recibe ese origen mediante `QA_URL`; la CLI QA accede por loopback:18088.

## Procedencia

`upstream/` contiene código extraído de `HectorPulido/starloco-private`;
`upstream/REVISION` identifica el commit. No se modificó ni reinició Dofus para
esta extracción. El framework funciona sin acceder a sus servicios o base de datos.
