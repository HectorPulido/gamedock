# Validación de GameDock

Suite completa ejecutada el 9 de octubre de 2026 en `hector-server`, Linux x86_64,
Docker 29.8.2. Proyecto Compose independiente `gamedock-qa`.

| Requisito | Evidencia ejecutada |
|---|---|
| Registro, login y logout | 4 pruebas API y Chromium: creación de cuenta, login posterior, token revocado y WebSocket cerrado al salir |
| Asignación a un usuario | API rechaza consultar/terminar escritorios ajenos; el usuario normal sólo lista sus instancias |
| Abrir con un comando | CLI registra una cuenta y lanza el perfil nativo; el comando configurado crea un archivo dentro del contenedor |
| Escritorios independientes | Dos contenedores simultáneos con redes separadas; conexión directa entre redes rechazada; ningún puerto de sesión publicado |
| Resolución | `xdpyinfo` dentro de ambas instancias verifica 1280×720 y 1920×1080 |
| Nombres y banners | Chromium guarda nombre, mensaje e imagen desde Administración; verifica que la imagen se carga |
| Administración básica | API prueba permisos, registro cerrado, límites, desactivación de cuenta, revocación de tokens y cierre de instancias; Chromium edita perfiles |
| Conexión real | Chromium espera píxeles renderizados, escribe un comando mediante teclado y verifica el archivo resultante usando Docker |
| Juegos | OpenTTD + OpenGFX construidos desde el repositorio; menú real renderizado a través de Xpra/WebSocket y cierre desde el portal |
| Persistencia | Recreación del portal conserva token, cuenta y PID del juego; reemplazo de instancia conserva un marcador en el volumen |
| Instalaciones separadas | Prueba Docker confirma volúmenes con namespace `gamedock-qa`; despliegue limpio independiente usa `gamedock-cleancheck-user-2-desktop` |
| Interfaz móvil | Captura a 390 px y comprobación de ausencia de desbordamiento horizontal |

Ejecutar `./scripts/qa.sh` reproduce la suite y genera capturas en
`/tmp/gamedock-artifacts`. El resultado final fue `QA passed`.

Tras añadir namespaces se repitió la prueba real de Docker/CLI y persistencia.
Además, un clon Git limpio del commit `f34ddc6` construyó runtime y portal,
desplegó un proyecto Compose independiente con una base vacía, creó administrador
y usuario y sirvió un escritorio Xpra autenticado. El árbol Git del clon siguió
limpio. No se copiaron bases de datos, clientes ni archivos `.runtime`.

Minecraft y Wine se entregan como adaptadores configurables; no se distribuyen
clientes comerciales ni se afirma haber probado esos clientes. El runtime base
usa renderizado de software, sin audio ni acceso a GPU. Los requisitos propios
de cada juego se resuelven en su imagen y perfil, como describe el README.

La extracción no modificó ni reinició Dofus. Su código original se conserva como
referencia no ejecutable en `upstream/`, con el commit de origen registrado.
