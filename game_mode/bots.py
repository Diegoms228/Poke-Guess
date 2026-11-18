"""Jugadores controlados por el servidor para las partidas de entrenamiento.

Un bot es un jugador más de la sala (JugadorSala con el campo `bot` relleno con
su dificultad). Aquí solo se decide QUÉ contesta y CUÁNDO; quien lo mete en la
partida es game_mode/salas.py.

Todo se calcula a partir de la sala, la ronda y el jugador, así que el mismo
bot en la misma ronda siempre tarda lo mismo y contesta lo mismo, aunque el
servidor se reinicie o atiendan la web varios procesos a la vez.
"""

import random

from game_mode import motor

MAX_BOTS = 3

DIFICULTADES = {
    'facil': {
        'nombre': 'Fácil',
        'descripcion': 'Falla a menudo y elige Pokémon muy conocidos.',
        'fallo': 0.35,        # probabilidad de equivocarse de tipo
        'conocidos': 12,      # elige entre los N primeros Pokémon del tipo
        'espera': (8, 22),    # segundos que tarda en contestar
    },
    'normal': {
        'nombre': 'Normal',
        'descripcion': 'Falla de vez en cuando y conoce bastantes Pokémon.',
        'fallo': 0.15,
        'conocidos': 50,
        'espera': (6, 18),
    },
    'dificil': {
        'nombre': 'Difícil',
        'descripcion': 'Casi nunca falla y elige Pokémon que nadie recuerda.',
        'fallo': 0.05,
        'conocidos': None,    # todos
        'espera': (4, 14),
    },
}

NOMBRES = {
    'facil': ['Novato', 'Aprendiz', 'Pupilo'],
    'normal': ['Rival', 'Retador', 'Entrenador'],
    'dificil': ['Campeón', 'Maestro', 'Alto Mando'],
}


def _azar(*partes):
    """Generador aleatorio que siempre da lo mismo para los mismos datos."""
    return random.Random('-'.join(str(p) for p in partes))


def nombres(dificultad, cantidad, ocupados=()):
    """Nombres para los bots que no choquen con los de la sala."""
    usados = {n.lower() for n in ocupados}
    elegidos = []
    for base in NOMBRES[dificultad][:cantidad]:
        nombre, numero = base, 2
        while nombre.lower() in usados:
            nombre = f'{base} {numero}'
            numero += 1
        usados.add(nombre.lower())
        elegidos.append(nombre)
    return elegidos


def segundos_para_responder(dificultad, sala_id, ronda, jugador_id):
    minimo, maximo = DIFICULTADES[dificultad]['espera']
    return _azar('espera', sala_id, ronda, jugador_id).uniform(minimo, maximo)


def elegir_respuesta(dificultad, tipo, sala_id, ronda, jugador_id):
    """El Pokémon que escribe el bot. A veces, según la dificultad, se equivoca."""
    datos = DIFICULTADES[dificultad]
    azar = _azar('respuesta', sala_id, ronda, jugador_id)

    if azar.random() < datos['fallo']:
        # Se equivoca como lo haría una persona: un Pokémon famoso de otro tipo
        otros = [p for p in motor.LISTA if tipo not in p['tipos']][:30]
        return azar.choice(otros)['nombre']

    opciones = motor.POR_TIPO[tipo]
    if datos['conocidos']:
        opciones = opciones[:datos['conocidos']]
    return azar.choice(opciones)['nombre']
