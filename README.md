# Poke-Guess

El "Stop" / "Alto el lápiz" llevado al mundo Pokémon. En cada ronda se sortea un
tipo y cada jugador escribe un Pokémon de ese tipo: cuanto menos repetida sea la
respuesta, más puntos.

- **Online**: cada jugador en su móvil, unidos por un código de sala de 4 letras.
- **Entrenamiento**: tú contra 1, 2 o 3 bots, en tres dificultades.
- **Local**: todos en el mismo móvil, pasándolo por turnos.

Hecho con Python (Flask), HTML, CSS y JavaScript sin librerías.

## Cómo está organizado

| Archivo o carpeta | Qué contiene |
|---|---|
| `App.py` | El servidor: rutas, cuentas y medidas de seguridad |
| `database.py` | Las tablas de la base de datos (usuarios y salas) |
| `game_mode/motor.py` | Las reglas: tipos, validación de respuestas y puntuación |
| `game_mode/salas.py` | Las partidas online: fases, reloj y guardado del progreso |
| `game_mode/bots.py` | Los bots del entrenamiento: qué contestan y cuánto tardan |
| `templates/` | Las páginas HTML (todas heredan de `base.html`) |
| `static/` | Estilos, JavaScript, fuente y vídeo de fondo |
| `data/pokemon.json` | Los 1025 Pokémon con sus tipos |
| `data/noticias.json` | Las noticias que se ven en el menú |
| `herramientas/` | Scripts para regenerar `pokemon.json` y el vídeo promocional |
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

## Versiones y noticias

Cada vez que publiques un cambio:

1. Sube la versión en `App.py` (`VERSION`). La regla está explicada justo encima:
   cambio grande v3.0 → v4.0, menor v3.0 → v3.1, mínimo v3.0 → v3.01.
2. Añade la noticia **al principio** de `data/noticias.json`, copiando la forma
   de las que ya hay:

```json
{
 "version": "v4.1",
 "fecha": "25/11/2026",
 "titulo": "Título corto",
 "cambios": [
  "Primera novedad.",
  "Segunda novedad."
 ]
},
```

   Cuidado con las comas: cada bloque `{...}` va separado del siguiente por una
   coma, y el último no la lleva. Si el archivo queda mal escrito, la página de
   noticias dará error.

Si cambias la base de datos (por ejemplo, una columna nueva), apúntala en
`COLUMNAS_NUEVAS` de `database.py`: así la base de datos del servidor se
actualiza sola al reiniciar, sin perder cuentas ni ranking.

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

## Publicarlo en internet

Hay dos piezas: **GitHub** guarda el código (así no dependes de tener los
archivos en tu ordenador) y un **hosting** lo mantiene encendido en una dirección
pública. Esta guía usa PythonAnywhere porque tiene plan gratuito, conserva la
base de datos SQLite entre reinicios y no necesita configuración especial.
Las condiciones de los planes gratuitos cambian: revísalas al crear la cuenta.

### 1. Subir el código a GitHub

1. Crea un repositorio vacío en https://github.com/new (por ejemplo `poke-guess`).
2. En la carpeta del proyecto:

```
git init
git add .
git commit -m "Poke-Guess"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/poke-guess.git
git push -u origin main
```

El `.gitignore` ya excluye el entorno virtual, la base de datos y la clave.

### 2. Crear la web en PythonAnywhere

1. Crea una cuenta en https://www.pythonanywhere.com
2. Abre una consola **Bash** y descarga el código:

```
git clone https://github.com/TU-USUARIO/poke-guess.git
cd poke-guess
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

   Si `pip` no encuentra alguna versión, es que el Python del servidor es más
   antiguo que el tuyo: crea el entorno con la versión más nueva que ofrezcan.

3. Pestaña **Web** → *Add a new web app* → *Manual configuration* → la misma
   versión de Python con la que creaste el entorno.
4. En esa misma pestaña:
   - **Source code**: `/home/TU-USUARIO/poke-guess`
   - **Virtualenv**: `/home/TU-USUARIO/poke-guess/venv`
   - **Force HTTPS**: activado
5. Pulsa en el enlace del **WSGI configuration file**, borra su contenido y deja:

```python
import sys
sys.path.insert(0, '/home/TU-USUARIO/poke-guess')
from wsgi import application
```

6. Pulsa **Reload**. El juego estará en `https://TU-USUARIO.pythonanywhere.com`

### 3. Actualizarlo cuando cambies algo

En tu ordenador:

```
git add .
git commit -m "Describe el cambio"
git push
```

En la consola de PythonAnywhere:

```
cd poke-guess
git pull
```

y pulsa **Reload** en la pestaña Web.

### Si algún día cambias de hosting

- El servidor debe arrancar `wsgi:application` (por ejemplo `gunicorn wsgi:application`).
- Define la variable de entorno `SECRET_KEY` con un valor largo y aleatorio.
- Si el disco del hosting se borra en cada despliegue, SQLite no sirve: usa una
  base de datos externa y pon su dirección en la variable `DATABASE_URL`.
