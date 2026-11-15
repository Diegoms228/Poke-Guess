"""Pruebas de la web: seguridad y partidas online con varios jugadores simulados.

    python -m unittest discover pruebas

Usan una base de datos temporal; no tocan las cuentas reales.
"""

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

import App
from database import Sala, Usuario, db
from game_mode import motor, salas

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
                     '/login', '/registro', '/jugar/2', '/jugar/5']:
            self.assertEqual(navegador.get(ruta).status_code, 200, ruta)
        self.assertEqual(navegador.get('/jugar/1').status_code, 404)
        self.assertEqual(navegador.get('/no-existe').status_code, 404)

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


if __name__ == '__main__':
    unittest.main()
