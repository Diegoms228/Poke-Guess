"""Pruebas de los bots de entrenamiento. No necesitan base de datos.

    python -m unittest discover pruebas
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game_mode import bots, motor


def respuestas(dificultad, tipo, veces=300):
    return [bots.elegir_respuesta(dificultad, tipo, sala, 0, 1) for sala in range(veces)]


def aciertos(dificultad, tipo, veces=300):
    lista = respuestas(dificultad, tipo, veces)
    return sum(tipo in motor.buscar_pokemon(r)['tipos'] for r in lista) / veces


class TestRespuestas(unittest.TestCase):
    def test_siempre_escriben_un_pokemon_que_existe(self):
        for dificultad in bots.DIFICULTADES:
            for tipo in motor.TIPOS:
                for texto in respuestas(dificultad, tipo, 40):
                    self.assertIsNotNone(motor.buscar_pokemon(texto), (dificultad, tipo, texto))

    def test_cuanto_mas_dificil_menos_fallan(self):
        facil, normal, dificil = (aciertos(d, 'agua') for d in ('facil', 'normal', 'dificil'))
        self.assertLess(facil, normal)
        self.assertLess(normal, dificil)
        self.assertGreater(dificil, 0.85)
        self.assertLess(facil, 0.8)

    def test_el_facil_solo_conoce_pokemon_famosos(self):
        famosos = {p['nombre'] for p in motor.POR_TIPO['fuego'][:bots.DIFICULTADES['facil']['conocidos']]}
        validas = [r for r in respuestas('facil', 'fuego') if 'fuego' in motor.buscar_pokemon(r)['tipos']]
        self.assertTrue(set(validas) <= famosos)

    def test_el_dificil_usa_pokemon_poco_conocidos(self):
        numeros = [motor.buscar_pokemon(r)['id'] for r in respuestas('dificil', 'agua')]
        self.assertGreater(sum(n > 151 for n in numeros), len(numeros) / 2)

    def test_misma_sala_y_ronda_misma_respuesta(self):
        self.assertEqual(bots.elegir_respuesta('normal', 'roca', 7, 2, 3),
                         bots.elegir_respuesta('normal', 'roca', 7, 2, 3))
        self.assertEqual(bots.segundos_para_responder('normal', 7, 2, 3),
                         bots.segundos_para_responder('normal', 7, 2, 3))

    def test_tardan_lo_que_marca_su_dificultad(self):
        for dificultad, datos in bots.DIFICULTADES.items():
            minimo, maximo = datos['espera']
            for sala in range(50):
                self.assertTrue(minimo <= bots.segundos_para_responder(dificultad, sala, 0, 1) <= maximo)


class TestNombres(unittest.TestCase):
    def test_nombres_por_dificultad(self):
        self.assertEqual(bots.nombres('dificil', 3), ['Campeón', 'Maestro', 'Alto Mando'])
        self.assertEqual(bots.nombres('facil', 1), ['Novato'])

    def test_no_repiten_el_nombre_de_una_persona(self):
        self.assertEqual(bots.nombres('facil', 2, ocupados=['NOVATO']), ['Novato 2', 'Aprendiz'])

    def test_caben_en_el_limite_de_12_letras(self):
        for dificultad in bots.DIFICULTADES:
            for nombre in bots.nombres(dificultad, bots.MAX_BOTS, ocupados=bots.NOMBRES[dificultad]):
                self.assertLessEqual(len(nombre), 12, nombre)


class TestPokedex(unittest.TestCase):
    def test_lista_sin_repetidos_y_ordenada(self):
        numeros = [p['id'] for p in motor.LISTA]
        self.assertEqual(numeros, sorted(set(numeros)))
        self.assertEqual(len(numeros), 1025)

    def test_cada_tipo_tiene_pokemon_suficientes(self):
        for tipo in motor.TIPOS:
            self.assertGreaterEqual(len(motor.POR_TIPO[tipo]), bots.DIFICULTADES['facil']['conocidos'])


if __name__ == '__main__':
    unittest.main()
