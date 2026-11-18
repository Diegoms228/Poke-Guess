"""Pruebas de la web: seguridad y partidas online con varios jugadores simulados.

    python -m unittest discover pruebas

Usan una base de datos temporal; no tocan las cuentas reales.
"""

import html
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_carpeta = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(_carpeta, 'pruebas.db').replace('\\', '/')
os.environ['SECRET_KEY'] = 'clave-de-pruebas'

from sqlalchemy import inspect, text

import App
from database import Sala, Usuario, actualizar_esquema, db
from game_mode import bots, motor, salas

App.app.config['SESSION_COOKIE_SECURE'] = False   # las pruebas van por http


class Navegador:
    """Un jugador con su propio navegador (sus propias cookies)."""

    def __init__(self):
        self.cliente = App.app.test_client()
        self.token = None

    def get(self, ruta):
        return self.cliente.get(ruta)

    def _token(self):
        if self.token is None:
            pagina = self.get('/').get_data(as_text=True)
            self.token = re.search(r'name="csrf-token" content="([^"]+)"', pagina).group(1)
        return self.token

    def formulario(self, ruta, **campos):
        return self.cliente.post(ruta, data=campos, headers={'X-CSRFToken': self._token()})

    def json(self, ruta, **cuerpo):
        return self.cliente.post(ruta, json=cuerpo, headers={'X-CSRFToken': self._token()})

    def estado(self, codigo):
        return self.get(f'/api/sala/{codigo}').get_json()


class Base(unittest.TestCase):
    def setUp(self):
        with App.app.app_context():
            db.drop_all()
            db.create_all()
        App._intentos.clear()
        self.desfase = timedelta(0)
        self._ahora_real = salas.ahora
        salas.ahora = lambda: self._ahora_real() + self.desfase

    def tearDown(self):
        salas.ahora = self._ahora_real

    def pasar_tiempo(self, segundos):
        self.desfase += timedelta(seconds=segundos)

    def crear_sala(self, *nombres):
        """Crea una sala con esos jugadores. Devuelve (código, navegadores)."""
        navegadores = [Navegador() for _ in nombres]
        respuesta = navegadores[0].formulario('/online/crear', nombre=nombres[0])
        codigo = respuesta.headers['Location'].rsplit('/', 1)[-1]
        for navegador, nombre in zip(navegadores[1:], nombres[1:]):
            self.assertEqual(
                navegador.formulario('/online/unirse', codigo=codigo, nombre=nombre).status_code, 302)
        return codigo, navegadores


class TestSeguridad(Base):
    def test_post_sin_token_csrf_se_rechaza(self):
        cliente = App.app.test_client()
        self.assertEqual(cliente.post('/login', data={'username': 'a', 'password': 'b'}).status_code, 400)
        self.assertEqual(cliente.post('/online/crear', data={'nombre': 'a'}).status_code, 400)
        self.assertEqual(cliente.post('/api/ronda', json={'tipo': 'agua', 'respuestas': ['a', 'b']}).status_code, 400)

    def test_cabeceras(self):
        cabeceras = Navegador().get('/').headers
        self.assertIn("default-src 'self'", cabeceras['Content-Security-Policy'])
        self.assertEqual(cabeceras['X-Frame-Options'], 'DENY')
        self.assertEqual(cabeceras['X-Content-Type-Options'], 'nosniff')

    def test_cookie_de_sesion_protegida(self):
        self.assertTrue(App.app.config['SESSION_COOKIE_HTTPONLY'])
        self.assertEqual(App.app.config['SESSION_COOKIE_SAMESITE'], 'Lax')

    def test_logout_solo_por_post(self):
        self.assertEqual(Navegador().get('/logout').status_code, 405)

    def test_registro_login_y_bloqueo_por_intentos(self):
        ana = Navegador()
        corta = ana.formulario('/registro', username='ana', email='ana@prueba.test', password='1234567')
        self.assertIn('al menos 8', corta.get_data(as_text=True))
        self.assertEqual(
            ana.formulario('/registro', username='ana', email='ana@prueba.test', password='secreta123').status_code, 302)
        self.assertIn('Hola, ana', ana.get('/').get_data(as_text=True))
        self.assertEqual(ana.formulario('/logout').status_code, 302)

        intruso = Navegador()
        for _ in range(App.MAX_INTENTOS):
            self.assertEqual(intruso.formulario('/login', username='ana', password='mala').status_code, 200)
        # A partir de aquí ni la contraseña buena entra hasta que pase el bloqueo
        self.assertEqual(intruso.formulario('/login', username='ana', password='secreta123').status_code, 429)

    def test_paginas_cargan(self):
        navegador = Navegador()
        for ruta in ['/', '/normas', '/creador', '/ranking', '/game_mode', '/online',
                     '/noticias', '/entrenamiento',
                     '/login', '/registro', '/jugar/2', '/jugar/5']:
            self.assertEqual(navegador.get(ruta).status_code, 200, ruta)
        self.assertEqual(navegador.get('/jugar/1').status_code, 404)
        self.assertEqual(navegador.get('/no-existe').status_code, 404)

    def test_version_visible_solo_en_el_menu(self):
        navegador = Navegador()
        self.assertIn(f'<p class="version">{App.texto_version()}</p>', navegador.get('/').get_data(as_text=True))
        self.assertNotIn('class="version"', navegador.get('/normas').get_data(as_text=True))

    def test_formato_de_la_version(self):
        original = App.VERSION
        try:
            for numeros, texto in [((3, 0, 0), 'v3.0'), ((3, 1, 0), 'v3.1'),
                                   ((3, 0, 1), 'v3.01'), ((4, 2, 5), 'v4.25')]:
                App.VERSION = numeros
                self.assertEqual(App.texto_version(), texto)
        finally:
            App.VERSION = original

    def test_partida_local_sigue_funcionando(self):
        respuesta = Navegador().json('/api/ronda', tipo='agua', respuestas=['squirtle', 'Squirtle', 'pikachu'])
        self.assertEqual([r['puntos'] for r in respuesta.get_json()['resultados']], [50, 50, 0])


class TestSalas(Base):
    def test_entrar_en_la_sala(self):
        codigo, (ana, luis) = self.crear_sala('Ana', 'Luis')
        estado = luis.estado(codigo)
        self.assertEqual(estado['estado'], 'espera')
        self.assertEqual([j['nombre'] for j in estado['jugadores']], ['Ana', 'Luis'])
        self.assertFalse(estado['soyAnfitrion'])
        self.assertTrue(ana.estado(codigo)['soyAnfitrion'])
        self.assertEqual(ana.get(f'/sala/{codigo}').status_code, 200)

    def test_quien_no_esta_en_la_sala_no_ve_nada(self):
        codigo, _ = self.crear_sala('Ana', 'Luis')
        extrano = Navegador()
        self.assertEqual(extrano.get(f'/api/sala/{codigo}').status_code, 403)
        self.assertEqual(extrano.json(f'/api/sala/{codigo}/empezar').status_code, 403)
        self.assertEqual(extrano.get(f'/sala/{codigo}').status_code, 302)   # le manda a unirse
        self.assertEqual(extrano.get('/api/sala/ZZZZ').status_code, 404)

    def test_reglas_para_unirse_y_empezar(self):
        codigo, (ana,) = self.crear_sala('Ana')
        self.assertIn('al menos', ana.json(f'/api/sala/{codigo}/empezar').get_json()['aviso'])

        repetido = Navegador().formulario('/online/unirse', codigo=codigo.lower(), nombre='ANA')
        self.assertIn('Ya hay alguien', repetido.get_data(as_text=True))
        self.assertIn('No existe', Navegador().formulario(
            '/online/unirse', codigo='ZZZZ', nombre='Eva').get_data(as_text=True))

        luis = Navegador()
        luis.formulario('/online/unirse', codigo=codigo, nombre='Luis')
        self.assertIn('Solo el anfitrión', luis.json(f'/api/sala/{codigo}/empezar').get_json()['aviso'])

        self.assertEqual(ana.json(f'/api/sala/{codigo}/empezar').get_json()['estado'], 'jugando')
        tarde = Navegador().formulario('/online/unirse', codigo=codigo, nombre='Eva')
        self.assertIn('ya ha empezado', tarde.get_data(as_text=True))

    def test_partida_completa(self):
        with App.app.app_context():
            db.session.add(Usuario(username='ana', email='a@prueba.test', password_hash='x'))
            db.session.commit()

        # Ana juega con cuenta; Luis y Eva, sin ella.
        ana = Navegador()
        with ana.cliente.session_transaction() as sesion:
            sesion['_user_id'] = '1'
        codigo = ana.formulario('/online/crear', nombre='Ana').headers['Location'].rsplit('/', 1)[-1]
        luis, eva = Navegador(), Navegador()
        luis.formulario('/online/unirse', codigo=codigo, nombre='Luis')
        eva.formulario('/online/unirse', codigo=codigo, nombre='Eva')

        estado = ana.json(f'/api/sala/{codigo}/empezar').get_json()
        self.assertEqual((estado['estado'], estado['ronda'], estado['rondas']), ('jugando', 1, motor.RONDAS))
        self.assertEqual(estado['segundos'], salas.SEGUNDOS_RONDA)

        # Un Pokémon válido de cada tipo sorteado
        with App.app.app_context():
            tipos = Sala.query.one().categorias.split(',')
        de_tipo = {t: [p['nombre'] for p in motor.POKEDEX.values() if t in p['tipos']] for t in tipos}

        for numero, tipo in enumerate(tipos, start=1):
            self.assertEqual(eva.estado(codigo)['tipo'], tipo)
            uno, otro = de_tipo[tipo][0], de_tipo[tipo][1]

            ana.json(f'/api/sala/{codigo}/responder', texto=uno)
            # Mientras se juega, Luis sabe que Ana ha contestado pero no qué
            visto = luis.estado(codigo)
            self.assertNotIn('resultados', visto)
            self.assertEqual([j['respondio'] for j in visto['jugadores']], [True, False, False])
            # Una segunda respuesta de Ana no sustituye a la primera
            ana.json(f'/api/sala/{codigo}/responder', texto=otro)

            luis.json(f'/api/sala/{codigo}/responder', texto=uno)
            self.assertEqual(eva.estado(codigo)['estado'], 'jugando')    # falta Eva

            if numero == 1:
                eva.json(f'/api/sala/{codigo}/responder', texto=otro)   # responde: cierra la ronda
            else:
                self.pasar_tiempo(salas.SEGUNDOS_RONDA + 2)              # se le acaba el tiempo

            estado = eva.estado(codigo)
            self.assertEqual(estado['estado'], 'final' if numero == motor.RONDAS else 'resultados')
            puntos = {r['nombre']: r['puntos'] for r in estado['resultados']}
            self.assertEqual(puntos, {'Ana': 50, 'Luis': 50, 'Eva': 100 if numero == 1 else 0})

            if numero < motor.RONDAS:
                self.assertEqual(ana.estado(codigo)['estado'], 'resultados')   # aún no toca avanzar
                self.pasar_tiempo(salas.SEGUNDOS_RESULTADOS + 1)
                self.assertEqual(ana.estado(codigo)['ronda'], numero + 1)

        final = luis.estado(codigo)
        self.assertEqual(final['ganadores'], ['Ana', 'Luis'])
        self.assertEqual({j['nombre']: j['puntos'] for j in final['jugadores']},
                         {'Ana': 200, 'Luis': 200, 'Eva': 100})
        self.assertFalse(final['guardado'])
        self.assertTrue(ana.estado(codigo)['guardado'])

        # El progreso se guarda una sola vez, por muchas veces que se consulte
        for _ in range(3):
            ana.estado(codigo)
        with App.app.app_context():
            usuario = Usuario.query.one()
            self.assertEqual((usuario.partidas, usuario.aciertos, usuario.fallos, usuario.puntuacion),
                             (1, motor.RONDAS, 0, 200))

        # Revancha: solo el anfitrión, y los marcadores vuelven a cero
        self.assertIn('Solo el anfitrión', luis.json(f'/api/sala/{codigo}/reiniciar').get_json()['aviso'])
        estado = ana.json(f'/api/sala/{codigo}/reiniciar').get_json()
        self.assertEqual(estado['estado'], 'espera')
        self.assertEqual([j['puntos'] for j in estado['jugadores']], [0, 0, 0])
        self.assertEqual(ana.json(f'/api/sala/{codigo}/empezar').get_json()['ronda'], 1)

    def test_respuesta_fuera_de_tiempo(self):
        codigo, (ana, luis) = self.crear_sala('Ana', 'Luis')
        ana.json(f'/api/sala/{codigo}/empezar')
        self.pasar_tiempo(salas.SEGUNDOS_RONDA + 5)
        estado = luis.json(f'/api/sala/{codigo}/responder', texto='pikachu').get_json()
        self.assertEqual(estado['aviso'], 'Se acabó el tiempo')
        self.assertEqual(estado['estado'], 'resultados')
        self.assertEqual([r['motivo'] for r in estado['resultados']], ['Sin respuesta', 'Sin respuesta'])

    def test_las_salas_viejas_se_borran(self):
        codigo, _ = self.crear_sala('Ana', 'Luis')
        self.pasar_tiempo(salas.HORAS_DE_VIDA * 3600 + 60)
        self.crear_sala('Eva')
        with App.app.app_context():
            self.assertIsNone(salas.buscar(codigo))
            self.assertEqual(Sala.query.count(), 1)


class TestNoticias(Base):
    def test_el_menu_enlaza_a_las_noticias(self):
        self.assertIn('href="/noticias"', Navegador().get('/').get_data(as_text=True))

    def test_se_ven_todas_las_noticias(self):
        with open(App.RUTA_NOTICIAS, encoding='utf-8') as archivo:
            lista = json.load(archivo)
        pagina = Navegador().get('/noticias').get_data(as_text=True)
        for noticia in lista:
            self.assertIn(noticia['version'], pagina)
            for cambio in noticia['cambios']:
                self.assertIn(html.escape(cambio), pagina)

    def test_la_noticia_mas_reciente_es_la_version_actual(self):
        with open(App.RUTA_NOTICIAS, encoding='utf-8') as archivo:
            self.assertEqual(json.load(archivo)[0]['version'], App.texto_version())


class TestEntrenamiento(Base):
    def crear(self, cantidad=2, dificultad='normal', navegador=None):
        yo = navegador or Navegador()
        respuesta = yo.formulario('/entrenamiento', nombre='Diego', bots=str(cantidad),
                                  dificultad=dificultad)
        self.assertEqual(respuesta.status_code, 302)
        return respuesta.headers['Location'].rsplit('/', 1)[-1], yo

    def jugar_hasta_el_final(self, codigo, yo):
        for ronda in range(1, motor.RONDAS + 1):
            estado = yo.json(f'/api/sala/{codigo}/responder', texto='pikachu').get_json()
            if ronda < motor.RONDAS:
                self.assertEqual(estado['estado'], 'resultados')
                self.pasar_tiempo(salas.SEGUNDOS_RESULTADOS + 1)
                self.assertEqual(yo.estado(codigo)['ronda'], ronda + 1)
        self.assertEqual(estado['estado'], 'final')
        return estado

    def test_empieza_al_momento_con_los_bots(self):
        codigo, yo = self.crear(3, 'facil')
        estado = yo.estado(codigo)
        self.assertEqual(estado['estado'], 'jugando')
        self.assertTrue(estado['entrenamiento'])
        self.assertEqual([j['bot'] for j in estado['jugadores']], [False, True, True, True])
        self.assertEqual([j['nombre'] for j in estado['jugadores']],
                         ['Diego', 'Novato', 'Aprendiz', 'Pupilo'])

    def test_los_bots_piensan_y_luego_responden(self):
        codigo, yo = self.crear(2, 'dificil')
        self.assertEqual([j['respondio'] for j in yo.estado(codigo)['jugadores']], [False, False, False])

        self.pasar_tiempo(bots.DIFICULTADES['dificil']['espera'][1] + 1)
        estado = yo.estado(codigo)
        self.assertEqual([j['respondio'] for j in estado['jugadores']], [False, True, True])
        self.assertEqual(estado['estado'], 'jugando')     # falta la persona
        self.assertNotIn('resultados', estado)            # y no ve lo que han puesto

    def test_si_respondes_los_bots_contestan_ya(self):
        codigo, yo = self.crear(2, 'facil')
        estado = yo.json(f'/api/sala/{codigo}/responder', texto='pikachu').get_json()
        self.assertEqual(estado['estado'], 'resultados')
        self.assertEqual(len(estado['resultados']), 3)
        self.assertTrue(all(r['respuesta'] for r in estado['resultados']))

    def test_no_cuenta_para_el_ranking(self):
        with App.app.app_context():
            db.session.add(Usuario(username='diego', email='d@prueba.test', password_hash='x'))
            db.session.commit()
        yo = Navegador()
        with yo.cliente.session_transaction() as sesion:
            sesion['_user_id'] = '1'
        codigo, yo = self.crear(1, 'normal', navegador=yo)

        final = self.jugar_hasta_el_final(codigo, yo)
        self.assertTrue(final['entrenamiento'])
        self.assertFalse(final['guardado'])
        with App.app.app_context():
            self.assertEqual(Usuario.query.one().partidas, 0)
        self.assertNotIn('diego', yo.get('/ranking').get_data(as_text=True))

    def test_la_revancha_empieza_sola(self):
        codigo, yo = self.crear(1, 'facil')
        self.jugar_hasta_el_final(codigo, yo)
        estado = yo.json(f'/api/sala/{codigo}/reiniciar').get_json()
        self.assertEqual((estado['estado'], estado['ronda']), ('jugando', 1))
        self.assertEqual([j['puntos'] for j in estado['jugadores']], [0, 0])

    def test_nadie_puede_colarse_en_un_entrenamiento(self):
        codigo, _ = self.crear(1, 'facil')
        intruso = Navegador().formulario('/online/unirse', codigo=codigo, nombre='Eva')
        self.assertIn('entrenamiento', intruso.get_data(as_text=True))

    def test_datos_no_validos(self):
        navegador = Navegador()
        for campos, aviso in [({'bots': '9', 'dificultad': 'facil'}, 'Elige entre'),
                              ({'bots': 'dos', 'dificultad': 'facil'}, 'Elige entre'),
                              ({'bots': '2', 'dificultad': 'imposible'}, 'Elige una dificultad'),
                              ({'bots': '2', 'dificultad': 'facil', 'nombre': ''}, 'Escribe tu nombre')]:
            campos.setdefault('nombre', 'Diego')
            respuesta = navegador.formulario('/entrenamiento', **campos)
            self.assertEqual(respuesta.status_code, 400, campos)
            self.assertIn(aviso, respuesta.get_data(as_text=True), campos)

    def test_bot_con_el_mismo_nombre_que_la_persona(self):
        respuesta = Navegador().formulario('/entrenamiento', nombre='Novato', bots='1', dificultad='facil')
        codigo = respuesta.headers['Location'].rsplit('/', 1)[-1]
        with App.app.app_context():
            sala = salas.buscar(codigo)
            self.assertEqual([j.nombre for j in sala.jugadores], ['Novato', 'Novato 2'])


class TestRondas(Base):
    def test_sala_online_con_las_rondas_elegidas(self):
        ana, luis = Navegador(), Navegador()
        respuesta = ana.formulario('/online/crear', nombre='Ana', rondas='3')
        codigo = respuesta.headers['Location'].rsplit('/', 1)[-1]
        luis.formulario('/online/unirse', codigo=codigo, nombre='Luis')
        self.assertEqual(ana.estado(codigo)['rondas'], 3)

        ana.json(f'/api/sala/{codigo}/empezar')
        for ronda in range(1, 4):
            ana.json(f'/api/sala/{codigo}/responder', texto='pikachu')
            estado = luis.json(f'/api/sala/{codigo}/responder', texto='pikachu').get_json()
            if ronda < 3:
                self.assertEqual(estado['estado'], 'resultados')
                self.pasar_tiempo(salas.SEGUNDOS_RESULTADOS + 1)
                self.assertEqual(ana.estado(codigo)['ronda'], ronda + 1)   # el móvil ve la ronda nueva
        self.assertEqual((estado['estado'], estado['ronda']), ('final', 3))

    def test_rondas_no_validas(self):
        navegador = Navegador()
        for rondas in ['7', '0', '99', 'muchas']:
            respuesta = navegador.formulario('/online/crear', nombre='Ana', rondas=rondas)
            self.assertEqual(respuesta.status_code, 400, rondas)
            self.assertIn('Elige cuántas rondas', respuesta.get_data(as_text=True))

    def test_sin_elegir_se_juegan_las_de_siempre(self):
        respuesta = Navegador().formulario('/online/crear', nombre='Ana')
        codigo = respuesta.headers['Location'].rsplit('/', 1)[-1]
        with App.app.app_context():
            self.assertEqual(salas.buscar(codigo).rondas, motor.RONDAS)

    def test_entrenamiento_con_las_rondas_elegidas(self):
        respuesta = Navegador().formulario('/entrenamiento', nombre='Diego', bots='1',
                                           dificultad='facil', rondas='8')
        codigo = respuesta.headers['Location'].rsplit('/', 1)[-1]
        with App.app.app_context():
            sala = salas.buscar(codigo)
            self.assertEqual(sala.rondas, 8)
            self.assertEqual(len(set(sala.categorias.split(','))), 8)

    def test_partida_local_recibe_todos_los_tipos(self):
        pagina = Navegador().get('/jugar/3').get_data(as_text=True)
        datos = json.loads(re.search(r'id="datos-partida"[^>]*>(.*?)</script>', pagina, re.S).group(1))
        self.assertEqual(sorted(datos['categorias']), sorted(motor.TIPOS))
        for n in motor.OPCIONES_RONDAS:
            self.assertIn(f'<option value="{n}"', pagina)


class TestFrenesi(Base):
    def crear(self):
        yo = Navegador()
        respuesta = yo.formulario('/entrenamiento', nombre='Diego', bots='2', dificultad='facil',
                                  rondas=str(salas.FRENESI))
        self.assertEqual(respuesta.status_code, 302)
        return respuesta.headers['Location'].rsplit('/', 1)[-1], yo

    def responder_bien(self, codigo, yo):
        tipo = yo.estado(codigo)['tipo']
        return yo.json(f'/api/sala/{codigo}/responder', texto=motor.POR_TIPO[tipo][-1]['nombre']).get_json()

    def responder_mal(self, codigo, yo):
        return yo.json(f'/api/sala/{codigo}/responder', texto='agumon').get_json()

    def siguiente_ronda(self, codigo, yo):
        self.pasar_tiempo(salas.SEGUNDOS_RESULTADOS_FRENESI + 1)
        return yo.estado(codigo)

    def test_empieza_con_vidas_y_poco_tiempo(self):
        codigo, yo = self.crear()
        estado = yo.estado(codigo)
        self.assertTrue(estado['frenesi'])
        self.assertEqual(estado['rondas'], 0)
        self.assertEqual(estado['misVidas'], salas.VIDAS)
        self.assertEqual(estado['segundos'], salas.SEGUNDOS_FRENESI_INICIO)
        self.assertEqual([j['vidas'] for j in estado['jugadores']], [salas.VIDAS, None, None])

    def test_cada_ronda_hay_menos_tiempo(self):
        codigo, yo = self.crear()
        for ronda in range(1, 16):
            estado = yo.estado(codigo)
            esperado = max(salas.SEGUNDOS_FRENESI_MINIMO, salas.SEGUNDOS_FRENESI_INICIO - (ronda - 1))
            self.assertEqual((estado['ronda'], estado['segundos']), (ronda, esperado))
            self.responder_bien(codigo, yo)
            self.siguiente_ronda(codigo, yo)

    def test_se_pierde_una_vida_por_fallo_y_acaba_sin_vidas(self):
        codigo, yo = self.crear()
        self.assertEqual(self.responder_mal(codigo, yo)['misVidas'], 2)
        self.siguiente_ronda(codigo, yo)
        estado = self.responder_bien(codigo, yo)
        self.assertEqual((estado['estado'], estado['misVidas']), ('resultados', 2))
        self.siguiente_ronda(codigo, yo)
        self.assertEqual(self.responder_mal(codigo, yo)['misVidas'], 1)
        self.siguiente_ronda(codigo, yo)
        final = self.responder_mal(codigo, yo)
        self.assertEqual((final['estado'], final['misVidas'], final['ronda']), ('final', 0, 4))

    def test_quedarse_sin_contestar_tambien_quita_vida(self):
        codigo, yo = self.crear()
        self.pasar_tiempo(salas.SEGUNDOS_FRENESI_INICIO + 2)
        self.assertEqual(yo.estado(codigo)['misVidas'], 2)

    def test_va_mas_alla_de_los_18_tipos(self):
        codigo, yo = self.crear()
        vistos = []
        for _ in range(len(motor.TIPOS) + 5):
            vistos.append(yo.estado(codigo)['tipo'])
            self.responder_bien(codigo, yo)
            self.siguiente_ronda(codigo, yo)
        self.assertEqual(sorted(vistos[:len(motor.TIPOS)]), sorted(motor.TIPOS))
        self.assertTrue(all(t in motor.TIPOS for t in vistos))
        self.assertEqual(yo.estado(codigo)['estado'], 'jugando')

    def test_revancha_con_las_vidas_llenas(self):
        codigo, yo = self.crear()
        for _ in range(salas.VIDAS):
            estado = self.responder_mal(codigo, yo)
            if estado['estado'] != 'final':
                self.siguiente_ronda(codigo, yo)
        estado = yo.json(f'/api/sala/{codigo}/reiniciar').get_json()
        self.assertEqual((estado['estado'], estado['ronda'], estado['misVidas']),
                         ('jugando', 1, salas.VIDAS))

    def test_el_frenesi_solo_existe_en_el_entrenamiento(self):
        respuesta = Navegador().formulario('/online/crear', nombre='Ana', rondas=str(salas.FRENESI))
        self.assertEqual(respuesta.status_code, 400)


class TestEsquema(Base):
    def test_completa_una_base_de_datos_antigua(self):
        with App.app.app_context():
            db.drop_all()
            with db.engine.begin() as conexion:
                conexion.execute(text(
                    'CREATE TABLE jugador_sala (id INTEGER PRIMARY KEY, sala_id INTEGER NOT NULL, '
                    'nombre VARCHAR(12) NOT NULL, anfitrion BOOLEAN NOT NULL, usuario_id INTEGER, '
                    'puntos INTEGER NOT NULL, aciertos INTEGER NOT NULL)'))
                conexion.execute(text(
                    'CREATE TABLE sala (id INTEGER PRIMARY KEY, codigo VARCHAR(4) NOT NULL, '
                    'estado VARCHAR(12) NOT NULL, ronda INTEGER NOT NULL, '
                    'categorias VARCHAR(200) NOT NULL, limite DATETIME, creada DATETIME NOT NULL)'))
                conexion.execute(text(
                    "INSERT INTO sala VALUES (1, 'ABCD', 'espera', 0, '', NULL, '2026-11-01')"))
            actualizar_esquema()
            inspector = inspect(db.engine)
            self.assertTrue({'bot', 'vidas'} <= {c['name'] for c in inspector.get_columns('jugador_sala')})
            self.assertIn('rondas', {c['name'] for c in inspector.get_columns('sala')})
            with db.engine.connect() as conexion:     # las salas que ya había quedan con 4 rondas
                self.assertEqual(conexion.execute(text('SELECT rondas FROM sala')).scalar(), 4)
            actualizar_esquema()    # una segunda vez no debe fallar


if __name__ == '__main__':
    unittest.main()
