"""Pruebas del motor de juego. Se ejecutan con:

    python -m unittest discover pruebas
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game_mode import motor


class TestBuscar(unittest.TestCase):
    def test_ignora_mayusculas_tildes_y_simbolos(self):
        self.assertEqual(motor.buscar_pokemon('  CHARIZARD ')['nombre'], 'Charizard')
        self.assertEqual(motor.buscar_pokemon('mr mime')['nombre'], 'Mr. Mime')
        self.assertEqual(motor.buscar_pokemon('flabebe')['nombre'], 'Flabébé')

    def test_acepta_nombre_en_espanol_y_en_ingles(self):
        self.assertEqual(motor.buscar_pokemon('Código Cero')['id'], 772)
        self.assertEqual(motor.buscar_pokemon('type null')['id'], 772)

    def test_perdona_erratas_pequenas(self):
        self.assertEqual(motor.buscar_pokemon('charizar')['nombre'], 'Charizard')
        self.assertEqual(motor.buscar_pokemon('bulbasur')['nombre'], 'Bulbasaur')

    def test_no_inventa_pokemon(self):
        self.assertIsNone(motor.buscar_pokemon('agumon'))
        self.assertIsNone(motor.buscar_pokemon(''))
        self.assertIsNone(motor.buscar_pokemon('pika'))


class TestPuntuar(unittest.TestCase):
    def puntos(self, tipo, respuestas):
        return [r['puntos'] for r in motor.puntuar_ronda(tipo, respuestas)]

    def test_todas_distintas(self):
        self.assertEqual(self.puntos('agua', ['squirtle', 'psyduck', 'magikarp']), [100, 100, 100])

    def test_solo_pierden_puntos_los_que_coinciden(self):
        self.assertEqual(self.puntos('agua', ['squirtle', 'Squirtle', 'psyduck']), [50, 50, 100])

    def test_todos_iguales(self):
        self.assertEqual(self.puntos('fuego', ['charmander'] * 4), [25, 25, 25, 25])

    def test_fallos_no_puntuan(self):
        ronda = motor.puntuar_ronda('fuego', ['squirtle', '', 'agumon', 'vulpix'])
        self.assertEqual([r['puntos'] for r in ronda], [0, 0, 0, 100])
        self.assertEqual(ronda[0]['motivo'], 'Es de tipo agua')
        self.assertEqual(ronda[1]['motivo'], 'Sin respuesta')
        self.assertEqual(ronda[2]['motivo'], 'Ese Pokémon no existe')

    def test_una_invalida_repetida_no_afecta_a_los_demas(self):
        self.assertEqual(self.puntos('fuego', ['squirtle', 'squirtle', 'vulpix']), [0, 0, 100])

    def test_vale_el_segundo_tipo(self):
        self.assertEqual(self.puntos('volador', ['charizard', 'pidgey']), [100, 100])


class TestPartida(unittest.TestCase):
    def test_categorias_sin_repetir(self):
        for _ in range(50):
            categorias = motor.elegir_categorias()
            self.assertEqual(len(categorias), motor.RONDAS)
            self.assertEqual(len(set(categorias)), motor.RONDAS)
            self.assertTrue(set(categorias) <= set(motor.TIPOS))

    def test_todos_los_tipos_tienen_pokemon(self):
        tipos_con_datos = {t for p in motor.POKEDEX.values() for t in p['tipos']}
        self.assertEqual(tipos_con_datos, set(motor.TIPOS))

    def test_ganadores(self):
        self.assertEqual(motor.ganadores([100, 300, 200]), [1])
        self.assertEqual(motor.ganadores([300, 300, 200]), [0, 1])


if __name__ == '__main__':
    unittest.main()
