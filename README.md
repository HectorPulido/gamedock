# GameDock

Framework para asignar escritorios de juegos a usuarios desde un navegador.

## Estado
Extracción en curso; todavía no es un producto desplegable.

La referencia original está en `upstream/`, extraída sin secretos de
`HectorPulido/starloco-private`; `upstream/REVISION` identifica el commit.
Estos archivos son referencia histórica, no se ejecutan en el framework.

## Contrato del framework
- Registro, login y logout con cuentas propias, contraseñas con hash y sesiones revocables.
- Cada usuario sólo puede consultar, conectar y terminar sus propias instancias.
- Administradores configuran nombre, banner, registro, catálogo y límites; pueden terminar instancias.
- Perfiles de juegos con imagen Docker, comando como lista de argumentos, variables y resolución.
- Creación por interfaz, API y CLI; una instancia es un contenedor con escritorio y datos del usuario.
- Proxy HTTP/WebSocket autenticado hacia Xpra, sin publicar puertos de sesiones.
- Persistencia de cuentas y configuración; reconciliación del estado con Docker tras reinicios.
- Ejemplo nativo y perfil Minecraft; Minecraft requiere aportar el cliente y la licencia correspondientes.

## Separación
`runtime/` contiene el escritorio genérico. Las imágenes de juegos derivan de él.
`server/` contendrá autenticación, catálogo, asignación y proxy.
`cli/` contendrá el comando de lanzamiento.
El portal y la base de datos de Dofus no son dependencias del framework.
