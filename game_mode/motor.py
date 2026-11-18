"""Motor del juego: categorías, validación de respuestas y puntuación.

No sabe nada de Flask ni de HTML: recibe datos y devuelve datos. Así sirve
igual para 2 jugadores que para 8 y se puede probar sin arrancar la web.
"""

import difflib
import json
import random
import unicodedata
from pathlib import Path

RUTA_DATOS = Path(__file__).resolve().parent.parent / 'data' / 'pokemon.json'

TIPOS = [
    'agua', 'fuego', 'planta', 'acero', 'bicho', 'dragón', 'eléctrico',
    'fantasma', 'hada', 'hielo', 'lucha', 'normal', 'psíquico', 'roca',
    'siniestro', 'tierra', 'veneno', 'volador',
]

RONDAS = 4
SEGUNDOS_POR_TURNO = 20
MIN_JUGADORES = 2
MAX_JUGADORES = 8

# Puntos por respuesta válida, según cuánta gente la haya repetido.
PUNTOS_UNICA = 100        # nadie más la ha escrito
PUNTOS_REPETIDA = 50      # coincide con algún otro jugador
PUNTOS_TODOS_IGUAL = 25   # todos han escrito lo mismo


def normalizar(texto):
    """Deja el texto en minúsculas, sin tildes, espacios ni símbolos.

    'Mr. Mime', 'mr mime' y 'MRMIME' acaban siendo 'mrmime'.
    """
    sin_tildes = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in sin_tildes.lower() if c.isalnum())


# Cada Pokémon una sola vez, por número de Pokédex. Los primeros números son
# los más conocidos, así que el orden sirve de medida de "fama".
LISTA = sorted(json.loads(RUTA_DATOS.read_text(encoding='utf-8')), key=lambda p: p['id'])


def _cargar_pokedex():
    """Devuelve {nombre normalizado: datos del Pokémon} para buscar respuestas.

    Si dos nombres quedan iguales al normalizarlos (Nidoran♀ y Nidoran♂ son
    los dos "nidoran"), se queda el primero; los dos son del mismo tipo, así
    que para corregir da igual cuál sea.
    """
    indice = {}
    for entrada in LISTA:
        for nombre in (entrada['nombre'], entrada.get('nombre_en')):
            if nombre:
                indice.setdefault(normalizar(nombre), entrada)
    return indice


POKEDEX = _cargar_pokedex()
POR_TIPO = {tipo: [p for p in LISTA if tipo in p['tipos']] for tipo in TIPOS}


def buscar_pokemon(texto):
    """Devuelve los datos del Pokémon escrito, o None si no existe.

    Perdona pequeñas erratas ('charizar', 'bulbasur') porque en el móvil es
    fácil equivocarse de tecla con el tiempo corriendo.
    """
    clave = normalizar(texto)
    if clave in POKEDEX:
        return POKEDEX[clave]
    if len(clave) >= 5:
        parecidos = difflib.get_close_matches(clave, POKEDEX.keys(), n=1, cutoff=0.85)
        if parecidos:
            return POKEDEX[parecidos[0]]
    return None


def elegir_categorias(cantidad=RONDAS):
    """Sortea los tipos de la partida, sin repetir ninguno."""
    return random.sample(TIPOS, cantidad)


def puntuar_ronda(tipo, respuestas):
    """Corrige una ronda. `respuestas` es una lista con un texto por jugador.

    Devuelve una lista en el mismo orden, con un diccionario por jugador:
    respuesta, pokemon (nombre oficial o None), valida, motivo y puntos.
    """
    resultados = []
    for texto in respuestas:
        texto = (texto or '').strip()
        resultado = {'respuesta': texto, 'pokemon': None, 'valida': False,
                     'motivo': '', 'puntos': 0}
        if not texto:
            resultado['motivo'] = 'Sin respuesta'
        else:
            pokemon = buscar_pokemon(texto)
            if pokemon is None:
                resultado['motivo'] = 'Ese Pokémon no existe'
            else:
                resultado['pokemon'] = pokemon['nombre']
                if tipo in pokemon['tipos']:
                    resultado['valida'] = True
                else:
                    resultado['motivo'] = 'Es de tipo ' + ' / '.join(pokemon['tipos'])
        resultados.append(resultado)

    # Cuántas veces aparece cada Pokémon válido en esta ronda.
    veces = {}
    for resultado in resultados:
        if resultado['valida']:
            veces[resultado['pokemon']] = veces.get(resultado['pokemon'], 0) + 1

    for resultado in resultados:
        if not resultado['valida']:
            continue
        repeticiones = veces[resultado['pokemon']]
        if repeticiones == 1:
            resultado['puntos'] = PUNTOS_UNICA
            resultado['motivo'] = 'Respuesta única'
        elif repeticiones == len(respuestas):
            resultado['puntos'] = PUNTOS_TODOS_IGUAL
            resultado['motivo'] = 'Todos habéis puesto lo mismo'
        else:
            resultado['puntos'] = PUNTOS_REPETIDA
            resultado['motivo'] = 'Repetida'
    return resultados


def ganadores(totales):
    """Devuelve las posiciones de quienes tienen más puntos (varias si hay empate)."""
    maximo = max(totales)
    return [i for i, puntos in enumerate(totales) if puntos == maximo]
