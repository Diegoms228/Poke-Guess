# Servidor principal
import os
import secrets
import sys
import time
from datetime import timedelta

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from database import JugadorSala, Usuario, db
from game_mode import motor, salas

app = Flask(__name__)

# VERSIÓN DE LA WEB: (grande, menor, mínimo). Se muestra en el menú como "v3.0".
# Al publicar un cambio se sube UNO de los tres números, según su importancia:
#   grande  -> modo de juego nuevo o un archivo rehecho por completo   v3.0 -> v4.0
#   menor   -> añadido pequeño, como un icono de contacto              v3.0 -> v3.1
#   mínimo  -> retoque visual, una palabra, algo casi irrelevante      v3.0 -> v3.01
# Al subir un número, los que tiene a su derecha vuelven a 0 (v3.12 -> v3.2 -> v4.0).
VERSION = (3, 0, 0)


def texto_version():
    grande, menor, minimo = VERSION
    return f'v{grande}.{menor}' + (str(minimo) if minimo else '')


@app.context_processor
def datos_para_plantillas():
    return {'version': texto_version()}


# CONFIGURACIÓN Y SEGURIDAD

def clave_secreta():
    """La clave que firma las sesiones. Nunca se escribe en el código.

    Se toma de la variable de entorno SECRET_KEY y, si no existe, de un archivo
    que se genera solo la primera vez dentro de `instance/` (carpeta que no se
    sube al repositorio).
    """
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    os.makedirs(app.instance_path, exist_ok=True)
    ruta = os.path.join(app.instance_path, 'secret_key')
    try:
        with open(ruta, 'x', encoding='ascii') as archivo:
            archivo.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    with open(ruta, encoding='ascii') as archivo:
        return archivo.read().strip()


app.config.update(
    SECRET_KEY=clave_secreta(),
    SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///pokeguess.db'),
    # Las cookies de sesión solo viajan por HTTPS, no las lee JavaScript y no
    # se envían desde otras webs. (Al arrancar en local se relaja la primera.)
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    WTF_CSRF_TIME_LIMIT=None,          # el token dura lo que dure la sesión
    MAX_CONTENT_LENGTH=16 * 1024,      # nadie necesita enviar más de 16 KB
)

# El hosting pone un proxy delante: esto recupera la IP y el https reales.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Todo formulario o petición POST debe traer un token que solo conoce nuestra
# página; así otra web no puede enviar acciones en nombre del usuario (CSRF).
csrf = CSRFProtect(app)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


# Crear tablas al arrancar
with app.app_context():
    db.create_all()


@app.after_request
def cabeceras_de_seguridad(respuesta):
    respuesta.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "img-src 'self' https://cdn-icons-png.flaticon.com; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    respuesta.headers['X-Frame-Options'] = 'DENY'
    respuesta.headers['Referrer-Policy'] = 'same-origin'
    if request.is_secure:
        respuesta.headers['Strict-Transport-Security'] = 'max-age=31536000'
    if request.path.startswith('/api/'):
        respuesta.headers['Cache-Control'] = 'no-store'
    return respuesta


def error(codigo, mensaje):
    if request.path.startswith('/api/'):
        return jsonify(error=mensaje), codigo
    return render_template('error.html', mensaje=mensaje), codigo


@app.errorhandler(CSRFError)
def error_csrf(_):
    return error(400, 'La página ha caducado. Vuelve atrás, recárgala e inténtalo otra vez.')


@app.errorhandler(400)
def error_400(_):
    return error(400, 'Petición incorrecta.')


@app.errorhandler(404)
def error_404(_):
    return error(404, 'Esta página no existe.')


@app.errorhandler(413)
def error_413(_):
    return error(413, 'Demasiados datos.')


@app.errorhandler(500)
def error_500(_):
    return error(500, 'Algo ha fallado en el servidor.')


# Freno a quien prueba contraseñas: tras varios fallos seguidos hay que esperar.
MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 5
_intentos = {}   # (ip, usuario) -> [fallos, momento en que se desbloquea]


def _clave_intentos(username):
    return (request.remote_addr, username.lower())


def login_bloqueado(username):
    fallos, hasta = _intentos.get(_clave_intentos(username), (0, 0))
    return fallos >= MAX_INTENTOS and time.time() < hasta


def anotar_login(username, correcto):
    clave = _clave_intentos(username)
    if correcto:
        _intentos.pop(clave, None)
        return
    fallos, hasta = _intentos.get(clave, (0, 0))
    if time.time() >= hasta:   # los fallos antiguos ya no cuentan
        fallos = 0
    if len(_intentos) > 10000:   # que la lista no crezca sin límite
        _intentos.clear()
    _intentos[clave] = (fallos + 1, time.time() + MINUTOS_BLOQUEO * 60)


# PÁGINAS

@app.route('/')
def menu():
    return render_template('menu_tfp.html')


@app.route('/normas')
def normas():
    return render_template('normas.html', motor=motor, salas=salas)


@app.route('/creador')
def creador():
    return render_template('creador.html')


@app.route('/ranking')
def ranking():
    mejores = (Usuario.query.filter(Usuario.partidas > 0)
               .order_by(Usuario.puntuacion.desc()).limit(10).all())
    return render_template('ranking.html', mejores=mejores)


# REGISTRO
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        aviso = None
        if not username or not email or not password:
            aviso = 'Rellena todos los campos'
        elif len(username) > 20:
            aviso = 'El nombre no puede tener más de 20 letras'
        elif '@' not in email or len(email) > 120:
            aviso = 'Ese email no es válido'
        elif len(password) < 8:
            aviso = 'La contraseña debe tener al menos 8 caracteres'
        # Comprobación de existencia
        elif Usuario.query.filter_by(username=username).first():
            aviso = 'Ese nombre de usuario ya existe'
        elif Usuario.query.filter_by(email=email).first():
            aviso = 'Ese email ya está registrado'

        if aviso:
            return render_template('registro.html', error=aviso,
                                   username=username, email=email)

        # Guardar contraseña (cifrada)
        nuevo = Usuario(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
        )
        db.session.add(nuevo)
        db.session.commit()
        login_user(nuevo)
        return redirect(url_for('menu'))

    return render_template('registro.html')


# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if login_bloqueado(username):
            return render_template('login.html', username=username, error=(
                f'Demasiados intentos. Espera {MINUTOS_BLOQUEO} minutos.')), 429

        usuario = Usuario.query.filter_by(username=username).first()
        correcto = bool(usuario and check_password_hash(usuario.password_hash, password))
        anotar_login(username, correcto)
        if not correcto:
            return render_template('login.html', username=username,
                                   error='Usuario o contraseña incorrectos')
        login_user(usuario)
        return redirect(url_for('menu'))

    return render_template('login.html')


# LOGOUT (por POST: un simple enlace no debe poder cerrar la sesión)
@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('menu'))


# JUEGO EN UN SOLO MÓVIL

# Página de selección de modo
@app.route('/game_mode')
def selector_modo():
    return render_template('Ngame.html')


# La partida: sirve para cualquier número de jugadores
@app.route('/jugar/<int:jugadores>')
def jugar(jugadores):
    if not motor.MIN_JUGADORES <= jugadores <= motor.MAX_JUGADORES:
        abort(404)
    datos = {
        'jugadores': jugadores,
        'categorias': motor.elegir_categorias(),
        'segundos': motor.SEGUNDOS_POR_TURNO,
        'urlRonda': url_for('corregir_ronda'),
    }
    return render_template('juego.html', datos=datos)


# El navegador envía las respuestas de una ronda y recibe la corrección
@app.route('/api/ronda', methods=['POST'])
def corregir_ronda():
    datos = request.get_json(silent=True) or {}
    tipo = datos.get('tipo')
    respuestas = datos.get('respuestas')

    if tipo not in motor.TIPOS or not isinstance(respuestas, list):
        abort(400)
    if not motor.MIN_JUGADORES <= len(respuestas) <= motor.MAX_JUGADORES:
        abort(400)

    respuestas = [str(r)[:40] if r is not None else '' for r in respuestas]
    return jsonify(resultados=motor.puntuar_ronda(tipo, respuestas))


# JUEGO ONLINE: CADA UNO EN SU MÓVIL

def jugador_actual(sala):
    """El jugador de esta sala que corresponde a este navegador, o None.

    Al entrar en una sala se apunta en la sesión (una cookie firmada que el
    usuario no puede falsificar) qué jugador es.
    """
    jugador_id = session.get('salas', {}).get(sala.codigo)
    if jugador_id is None:
        return None
    jugador = db.session.get(JugadorSala, jugador_id)
    return jugador if jugador is not None and jugador.sala_id == sala.id else None


def recordar_jugador(jugador):
    codigo = jugador.sala.codigo
    session['salas'] = {codigo: jugador.id}   # solo se está en una sala a la vez
    session.permanent = True


@app.route('/online')
def online():
    return render_template('online.html', codigo=request.args.get('codigo', '')[:4])


@app.route('/online/crear', methods=['POST'])
def online_crear():
    try:
        jugador = salas.crear(request.form.get('nombre'), current_user)
    except salas.ErrorSala as fallo:
        return render_template('online.html', error_crear=str(fallo)), 400
    recordar_jugador(jugador)
    return redirect(url_for('sala', codigo=jugador.sala.codigo))


@app.route('/online/unirse', methods=['POST'])
def online_unirse():
    codigo = request.form.get('codigo', '').strip().upper()[:4]
    nombre = request.form.get('nombre')

    existente = salas.buscar(codigo)
    if existente is not None and jugador_actual(existente) is not None:
        return redirect(url_for('sala', codigo=existente.codigo))   # ya estaba dentro

    try:
        jugador = salas.unirse(codigo, nombre, current_user)
    except salas.ErrorSala as fallo:
        return render_template('online.html', error_unirse=str(fallo), codigo=codigo,
                               nombre=salas.limpiar_nombre(nombre)), 400
    recordar_jugador(jugador)
    return redirect(url_for('sala', codigo=jugador.sala.codigo))


@app.route('/sala/<codigo>')
def sala(codigo):
    encontrada = salas.buscar(codigo)
    if encontrada is None:
        abort(404)
    if jugador_actual(encontrada) is None:
        return redirect(url_for('online', codigo=encontrada.codigo))
    datos = {
        'codigo': encontrada.codigo,
        'urlEstado': url_for('api_sala', codigo=encontrada.codigo),
        'urlEmpezar': url_for('api_sala_empezar', codigo=encontrada.codigo),
        'urlResponder': url_for('api_sala_responder', codigo=encontrada.codigo),
        'urlReiniciar': url_for('api_sala_reiniciar', codigo=encontrada.codigo),
    }
    return render_template('sala.html', datos=datos)


def sala_y_jugador(codigo):
    encontrada = salas.buscar(codigo)
    if encontrada is None:
        abort(404)
    jugador = jugador_actual(encontrada)
    if jugador is None:
        abort(403)
    return encontrada, jugador


def responder_estado(encontrada, jugador, accion=None):
    """Ejecuta una acción (si la hay) y devuelve cómo queda la sala."""
    aviso = None
    if accion is not None:
        try:
            accion()
        except salas.ErrorSala as fallo:
            aviso = str(fallo)
    salas.avanzar(encontrada)
    estado = salas.estado_para(encontrada, jugador)
    if aviso:
        estado['aviso'] = aviso
    return jsonify(estado)


@app.errorhandler(403)
def error_403(_):
    return error(403, 'No estás en esta sala.')


# Cada móvil pregunta aquí cada segundo y medio cómo va la partida
@app.route('/api/sala/<codigo>')
def api_sala(codigo):
    encontrada, jugador = sala_y_jugador(codigo)
    return responder_estado(encontrada, jugador)


@app.route('/api/sala/<codigo>/empezar', methods=['POST'])
def api_sala_empezar(codigo):
    encontrada, jugador = sala_y_jugador(codigo)
    return responder_estado(encontrada, jugador, lambda: salas.empezar(encontrada, jugador))


@app.route('/api/sala/<codigo>/responder', methods=['POST'])
def api_sala_responder(codigo):
    encontrada, jugador = sala_y_jugador(codigo)
    texto = str((request.get_json(silent=True) or {}).get('texto') or '')
    return responder_estado(encontrada, jugador,
                            lambda: salas.responder(encontrada, jugador, texto))


@app.route('/api/sala/<codigo>/reiniciar', methods=['POST'])
def api_sala_reiniciar(codigo):
    encontrada, jugador = sala_y_jugador(codigo)
    return responder_estado(encontrada, jugador, lambda: salas.reiniciar(encontrada, jugador))


if __name__ == '__main__':
    # Arranque en tu ordenador. En el hosting no se ejecuta esta parte.
    #   python App.py          -> solo este ordenador (http://127.0.0.1:5000)
    #   python App.py --red    -> también los móviles de tu wifi
    #   python App.py --debug  -> recarga al guardar y muestra errores detallados
    app.config['SESSION_COOKIE_SECURE'] = False    # en local no hay HTTPS
    app.config['REMEMBER_COOKIE_SECURE'] = False
    en_red = '--red' in sys.argv
    depurar = '--debug' in sys.argv
    if en_red and depurar:
        sys.exit('No combines --red y --debug: el depurador no debe quedar a la vista de la red.')
    app.run(host='0.0.0.0' if en_red else '127.0.0.1', debug=depurar)
