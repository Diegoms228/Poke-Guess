"""Descarga de PokeAPI los nombres y tipos de todos los Pokémon y los guarda
en data/pokemon.json. Solo hay que ejecutarlo una vez (o cuando salga una
generación nueva):

    python herramientas/descargar_pokemon.py

El juego no usa internet: lee siempre el JSON local.
"""

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = 'https://pokeapi.co/api/v2'
TOTAL_POKEMON = 1025
SALIDA = Path(__file__).resolve().parent.parent / 'data' / 'pokemon.json'

# PokeAPI da los tipos en inglés; el juego los muestra en español.
TIPOS = {
    'normal': 'normal', 'fire': 'fuego', 'water': 'agua', 'grass': 'planta',
    'electric': 'eléctrico', 'ice': 'hielo', 'fighting': 'lucha',
    'poison': 'veneno', 'ground': 'tierra', 'flying': 'volador',
    'psychic': 'psíquico', 'bug': 'bicho', 'rock': 'roca', 'ghost': 'fantasma',
    'dragon': 'dragón', 'dark': 'siniestro', 'steel': 'acero', 'fairy': 'hada',
}


def pedir(ruta):
    peticion = urllib.request.Request(f'{API}/{ruta}', headers={'User-Agent': 'poke-guess'})
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        return json.load(respuesta)


def id_de_url(url):
    return int(url.rstrip('/').split('/')[-1])


def descargar_tipos():
    """Devuelve {id_pokemon: [tipos en español]} usando una petición por tipo."""
    tipos_por_id = {}
    for ingles, espanol in TIPOS.items():
        datos = pedir(f'type/{ingles}')
        for entrada in datos['pokemon']:
            numero = id_de_url(entrada['pokemon']['url'])
            # Los id por encima de 10000 son formas alternativas (megas, regionales...).
            if numero <= TOTAL_POKEMON:
                tipos_por_id.setdefault(numero, []).append((entrada['slot'], espanol))
    return {n: [t for _, t in sorted(lista)] for n, lista in tipos_por_id.items()}


def descargar_nombres(numero):
    """Devuelve (id, nombre en español, nombre en inglés)."""
    datos = pedir(f'pokemon-species/{numero}')
    nombres = {n['language']['name']: n['name'] for n in datos['names']}
    ingles = nombres.get('en', datos['name'])
    return numero, nombres.get('es', ingles), ingles


def main():
    print('Descargando tipos...')
    tipos_por_id = descargar_tipos()

    print(f'Descargando nombres de {TOTAL_POKEMON} Pokémon...')
    with ThreadPoolExecutor(max_workers=8) as grupo:
        nombres = list(grupo.map(descargar_nombres, range(1, TOTAL_POKEMON + 1)))

    pokemon = []
    for numero, espanol, ingles in sorted(nombres):
        entrada = {'id': numero, 'nombre': espanol, 'tipos': tipos_por_id[numero]}
        if ingles != espanol:
            entrada['nombre_en'] = ingles
        pokemon.append(entrada)

    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps(pokemon, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'Guardados {len(pokemon)} Pokémon en {SALIDA}')


if __name__ == '__main__':
    main()
