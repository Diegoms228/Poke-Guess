"""Partidas online: cada jugador en su móvil, unidos por el código de la sala.

Todos responden a la vez. La ronda se cierra cuando han contestado todos o
cuando se acaba el tiempo, lo que ocurra antes.

No hay ningún proceso vigilando el reloj: cada vez que un móvil pregunta
"¿cómo va la sala?" (lo hace cada segundo y medio) se llama a `avanzar`, que
comprueba si toca cambiar de fase. Es más sencillo que mantener conexiones
abiertas y funciona en cualquier hosting.

Las salas de entrenamiento son salas normales con bots dentro. Los bots
"contestan" en esa misma revisión periódica: cuando les toca, se guarda su
respuesta como si la hubiera enviado un móvil.
"""

import math
import random
from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from database import JugadorSala, Respuesta, Sala, Usuario, ahora, db
from game_mode import bots, motor

SEGUNDOS_RONDA = 30
SEGUNDOS_RESULTADOS = 12
# Margen para que una respuesta enviada en el último instante llegue a tiempo
MARGEN = timedelta(seconds=1.5)
HORAS_DE_VIDA = 3
LONGITUD_NOMBRE = 12
# Sin I ni O, que se confunden con 1 y 0 al dictar el código
LETRAS_CODIGO = 'ABCDEFGHJKLMNPQRSTUVWXYZ'


class ErrorSala(Exception):
    """Algo que el jugador ha pedido y no se puede hacer. El mensaje se le enseña."""


def limpiar_nombre(nombre):
    return ' '.join((nombre or '').split())[:LONGITUD_NOMBRE]


def buscar(codigo):
    return Sala.query.filter_by(codigo=(codigo or '').strip().upper()).first()


def _borrar_antiguas():
    caducidad = ahora() - timedelta(hours=HORAS_DE_VIDA)
    for sala in Sala.query.filter(Sala.creada < caducidad).all():
        db.session.delete(sala)


def _usuario_id(usuario):
    return usuario.id if usuario is not None and usuario.is_authenticated else None


def crear(nombre, usuario=None):
    """Crea una sala y mete en ella a quien la crea, que será el anfitrión."""
    nombre = limpiar_nombre(nombre)
    if not nombre:
        raise ErrorSala('Escribe tu nombre')

    _borrar_antiguas()
    for _ in range(20):
        codigo = ''.join(random.choices(LETRAS_CODIGO, k=4))
        if buscar(codigo) is None:
            break
    else:
        raise ErrorSala('No se pudo crear la sala, inténtalo otra vez')

    sala = Sala(codigo=codigo)
    jugador = JugadorSala(sala=sala, nombre=nombre, anfitrion=True,
                          usuario_id=_usuario_id(usuario))
    db.session.add_all([sala, jugador])
    db.session.commit()
    return jugador


def unirse(codigo, nombre, usuario=None):
    nombre = limpiar_nombre(nombre)
    if not nombre:
        raise ErrorSala('Escribe tu nombre')

    sala = buscar(codigo)
    if sala is None:
        raise ErrorSala('No existe ninguna sala con ese código')
    if es_entrenamiento(sala):
        raise ErrorSala('Esa sala es de entrenamiento')
    if sala.estado != 'espera':
        raise ErrorSala('Esa partida ya ha empezado')
    if len(sala.jugadores) >= motor.MAX_JUGADORES:
        raise ErrorSala('La sala está llena')
    if any(j.nombre.lower() == nombre.lower() for j in sala.jugadores):
        raise ErrorSala('Ya hay alguien con ese nombre en la sala')

    jugador = JugadorSala(sala=sala, nombre=nombre, usuario_id=_usuario_id(usuario))
    db.session.add(jugador)
    db.session.commit()
    return jugador


def es_entrenamiento(sala):
    return any(j.bot for j in sala.jugadores)


def crear_entrenamiento(nombre, usuario, cantidad, dificultad):
    """Sala con una persona y de 1 a 3 bots. Empieza al momento."""
    if dificultad not in bots.DIFICULTADES:
        raise ErrorSala('Elige una dificultad')
    if not 1 <= cantidad <= bots.MAX_BOTS:
        raise ErrorSala(f'Elige entre 1 y {bots.MAX_BOTS} bots')

    jugador = crear(nombre, usuario)
    sala = jugador.sala
    for nombre_bot in bots.nombres(dificultad, cantidad, ocupados=[jugador.nombre]):
        db.session.add(JugadorSala(sala=sala, nombre=nombre_bot, bot=dificultad))
    db.session.commit()

    empezar(sala, jugador)
    return jugador


def _responden_bots(sala):
    """Guarda la respuesta de cada bot al que ya le toque contestar.

    Un bot contesta cuando han pasado sus segundos de "pensar" o, para no
    hacer esperar a nadie, en cuanto todas las personas han respondido.
    """
    robots = [j for j in sala.jugadores if j.bot]
    if not robots:
        return

    ya = {r.jugador_id for r in Respuesta.query.filter_by(sala_id=sala.id, ronda=sala.ronda)}
    personas_listas = all(j.id in ya for j in sala.jugadores if not j.bot)
    inicio = sala.limite - timedelta(seconds=SEGUNDOS_RONDA)
    transcurrido = (ahora() - inicio).total_seconds()
    tipo = sala.categorias.split(',')[sala.ronda]
    ronda, sala_id = sala.ronda, sala.id

    for bot in robots:
        if bot.id in ya:
            continue
        espera = bots.segundos_para_responder(bot.bot, sala_id, ronda, bot.id)
        if personas_listas or transcurrido >= espera:
            texto = bots.elegir_respuesta(bot.bot, tipo, sala_id, ronda, bot.id)
            db.session.add(Respuesta(sala_id=sala_id, jugador_id=bot.id, ronda=ronda, texto=texto))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()   # otra petición lo guardó a la vez


def _cambiar_fase(sala, desde, hacia, **valores):
    """Pasa la sala de una fase a otra solo si sigue en la fase y ronda esperadas.

    Devuelve True si el cambio lo ha hecho esta petición. Si dos móviles
    preguntan a la vez, solo uno gana y el otro no repite la corrección.
    """
    hecho = db.session.execute(
        update(Sala)
        .where(Sala.id == sala.id, Sala.estado == desde, Sala.ronda == sala.ronda)
        .values(estado=hacia, **valores)
    ).rowcount == 1
    if not hecho:
        db.session.rollback()
    return hecho


def empezar(sala, jugador):
    if not jugador.anfitrion:
        raise ErrorSala('Solo el anfitrión puede empezar la partida')
    if len(sala.jugadores) < motor.MIN_JUGADORES:
        raise ErrorSala(f'Hacen falta al menos {motor.MIN_JUGADORES} jugadores')

    _cambiar_fase(sala, 'espera', 'jugando', ronda=0,
                  categorias=','.join(motor.elegir_categorias()),
                  limite=ahora() + timedelta(seconds=SEGUNDOS_RONDA))
    db.session.commit()


def responder(sala, jugador, texto):
    if sala.estado != 'jugando' or ahora() > sala.limite + MARGEN:
        raise ErrorSala('Se acabó el tiempo')

    db.session.add(Respuesta(sala_id=sala.id, jugador_id=jugador.id, ronda=sala.ronda,
                             texto=(texto or '').strip()[:40]))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()   # ya había respondido: se queda la primera
    avanzar(sala)


def avanzar(sala):
    """Cambia de fase si toca. Se puede llamar todas las veces que se quiera."""
    db.session.refresh(sala)
    if sala.estado == 'jugando':
        _responden_bots(sala)
        contestadas = Respuesta.query.filter_by(sala_id=sala.id, ronda=sala.ronda).count()
        if contestadas >= len(sala.jugadores) or ahora() >= sala.limite + MARGEN:
            _cerrar_ronda(sala)
    elif sala.estado == 'resultados' and ahora() >= sala.limite:
        _cambiar_fase(sala, 'resultados', 'jugando', ronda=sala.ronda + 1,
                      limite=ahora() + timedelta(seconds=SEGUNDOS_RONDA))
        db.session.commit()
    db.session.refresh(sala)


def _cerrar_ronda(sala):
    ronda = sala.ronda
    tipo = sala.categorias.split(',')[ronda]
    ultima = ronda == motor.RONDAS - 1

    siguiente = 'final' if ultima else 'resultados'
    if not _cambiar_fase(sala, 'jugando', siguiente,
                         limite=ahora() + timedelta(seconds=SEGUNDOS_RESULTADOS)):
        return

    # Quien no haya contestado a tiempo se queda con una respuesta vacía.
    respuestas = {r.jugador_id: r for r in
                  Respuesta.query.filter_by(sala_id=sala.id, ronda=ronda)}
    for jugador in sala.jugadores:
        if jugador.id not in respuestas:
            respuestas[jugador.id] = Respuesta(sala_id=sala.id, jugador_id=jugador.id,
                                               ronda=ronda, texto='')
            db.session.add(respuestas[jugador.id])

    correccion = motor.puntuar_ronda(tipo, [respuestas[j.id].texto for j in sala.jugadores])
    for jugador, resultado in zip(sala.jugadores, correccion):
        respuesta = respuestas[jugador.id]
        respuesta.pokemon = resultado['pokemon']
        respuesta.valida = resultado['valida']
        respuesta.motivo = resultado['motivo']
        respuesta.puntos = resultado['puntos']
        jugador.puntos += resultado['puntos']
        jugador.aciertos += 1 if resultado['valida'] else 0

    if ultima:
        _guardar_progreso(sala)
    db.session.commit()


def _guardar_progreso(sala):
    """Suma la partida a las cuentas de los jugadores que tengan sesión iniciada.

    Lo hace el servidor con sus propios datos: el navegador no puede inventarse
    una puntuación. Las partidas de entrenamiento no cuentan.
    """
    if es_entrenamiento(sala):
        return
    for jugador in sala.jugadores:
        usuario = db.session.get(Usuario, jugador.usuario_id) if jugador.usuario_id else None
        if usuario is not None:
            usuario.partidas += 1
            usuario.aciertos += jugador.aciertos
            usuario.fallos += motor.RONDAS - jugador.aciertos
            usuario.puntuacion += jugador.puntos


def reiniciar(sala, jugador):
    """Revancha: misma sala y mismos jugadores, marcadores a cero."""
    if not jugador.anfitrion:
        raise ErrorSala('Solo el anfitrión puede empezar otra partida')
    if not _cambiar_fase(sala, 'final', 'espera', ronda=0, categorias='', limite=None):
        return
    Respuesta.query.filter_by(sala_id=sala.id).delete()
    JugadorSala.query.filter_by(sala_id=sala.id).update({'puntos': 0, 'aciertos': 0})
    db.session.commit()

    if es_entrenamiento(sala):
        db.session.refresh(sala)
        empezar(sala, jugador)    # contra bots no hay nadie a quien esperar


def estado_para(sala, yo):
    """Lo que el móvil de un jugador necesita saber para pintar la pantalla.

    Mientras se juega la ronda no se envían las respuestas de los demás.
    """
    entrenamiento = es_entrenamiento(sala)
    en_partida = sala.estado != 'espera'
    respuestas = {}
    if en_partida:
        respuestas = {r.jugador_id: r for r in
                      Respuesta.query.filter_by(sala_id=sala.id, ronda=sala.ronda)}
    corregida = sala.estado in ('resultados', 'final')

    segundos = 0
    if sala.limite is not None and sala.estado in ('jugando', 'resultados'):
        segundos = max(0, math.ceil((sala.limite - ahora()).total_seconds()))

    estado = {
        'codigo': sala.codigo,
        'estado': sala.estado,
        'ronda': sala.ronda + 1,
        'rondas': motor.RONDAS,
        'tipo': sala.categorias.split(',')[sala.ronda] if en_partida else None,
        'segundos': segundos,
        'soyAnfitrion': yo.anfitrion,
        'entrenamiento': entrenamiento,
        'heRespondido': yo.id in respuestas,
        'minJugadores': motor.MIN_JUGADORES,
        'jugadores': [{
            'nombre': j.nombre,
            'puntos': j.puntos,
            'anfitrion': j.anfitrion,
            'bot': bool(j.bot),
            'yo': j.id == yo.id,
            'respondio': j.id in respuestas,
        } for j in sala.jugadores],
    }

    if corregida:
        estado['resultados'] = [{
            'nombre': j.nombre,
            'yo': j.id == yo.id,
            'respuesta': respuestas[j.id].pokemon or respuestas[j.id].texto,
            'motivo': respuestas[j.id].motivo,
            'valida': respuestas[j.id].valida,
            'puntos': respuestas[j.id].puntos,
            'total': j.puntos,
        } for j in sala.jugadores if j.id in respuestas]

    if sala.estado == 'final':
        mejores = motor.ganadores([j.puntos for j in sala.jugadores])
        estado['ganadores'] = [sala.jugadores[i].nombre for i in mejores]
        estado['guardado'] = yo.usuario_id is not None and not entrenamiento

    return estado
