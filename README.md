# Poke-Guess

El "Stop" / "Alto el lápiz" llevado al mundo Pokémon. En cada ronda se sortea un
tipo y cada jugador escribe un Pokémon de ese tipo: cuanto menos repetida sea la
respuesta, más puntos.

- **Online**: cada jugador en su móvil, unidos por un código de sala de 4 letras.
- **Local**: todos en el mismo móvil, pasándolo por turnos.

Hecho con Python (Flask), HTML, CSS y JavaScript sin librerías.

## Cómo está organizado

| Archivo o carpeta | Qué contiene |
|---|---|
| `App.py` | El servidor: rutas, cuentas y medidas de seguridad |
| `database.py` | Las tablas de la base de datos (usuarios y salas) |
| `game_mode/motor.py` | Las reglas: tipos, validación de respuestas y puntuación |
| `game_mode/salas.py` | Las partidas online: fases, reloj y guardado del progreso |
| `templates/` | Las páginas HTML (todas heredan de `base.html`) |
| `static/` | Estilos, JavaScript, fuente y vídeo de fondo |
| `data/pokemon.json` | Los 1025 Pokémon con sus tipos |
| `herramientas/` | Script que regenera `pokemon.json` desde PokeAPI |
| `pruebas/` | Pruebas automáticas |
| `wsgi.py` | Punto de entrada para el hosting |

## Ejecutarlo en tu ordenador

La primera vez:

```
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Cada vez que quieras arrancarlo (con el entorno activado):

```
python App.py
```

y abre http://127.0.0.1:5000

- `python App.py --red` lo abre también a los móviles de tu misma wifi. Entra
  desde el móvil a `http://LA-IP-DE-TU-PC:5000` (la IP sale con `ipconfig`).
- `python App.py --debug` recarga al guardar y muestra los errores con detalle.

Pruebas:

```
python -m unittest discover pruebas
```

## Seguridad

- Las contraseñas se guardan cifradas (hash), nunca en texto.
- La clave que firma las sesiones no está en el código: se lee de la variable de
  entorno `SECRET_KEY` o se genera sola en `instance/secret_key`.
- Todos los formularios y peticiones POST llevan token CSRF.
- Las cookies de sesión solo viajan por HTTPS y no son accesibles desde JavaScript.
- Cabeceras de seguridad (CSP, anti-iframe, HSTS) en todas las respuestas.
- Tras 5 contraseñas incorrectas seguidas hay que esperar 5 minutos.
- La puntuación del ranking la calcula y guarda el servidor; el navegador no
  puede inventársela. Por eso solo cuentan las partidas online.
- `instance/` (base de datos y clave) no se sube al repositorio.
