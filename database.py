from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def ahora():
    """Hora actual en UTC, sin zona, que es como la guarda SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Usuario(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    # Progreso del jugador
    partidas      = db.Column(db.Integer, default=0)
    aciertos      = db.Column(db.Integer, default=0)
    fallos        = db.Column(db.Integer, default=0)
    puntuacion    = db.Column(db.Integer, default=0)


# PARTIDAS ONLINE
# El estado de cada sala vive en la base de datos y no en la memoria del
# servidor: así da igual cuántos procesos atiendan la web o si se reinicia.

class Sala(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    codigo     = db.Column(db.String(4), unique=True, nullable=False, index=True)
    # espera -> jugando -> resultados -> (jugando ...) -> final
    estado     = db.Column(db.String(12), nullable=False, default='espera')
    ronda      = db.Column(db.Integer, nullable=False, default=0)
    categorias = db.Column(db.String(200), nullable=False, default='')
    # Momento en que termina la fase actual (la ronda o la pausa de resultados)
    limite     = db.Column(db.DateTime)
    creada     = db.Column(db.DateTime, nullable=False, default=ahora)

    jugadores  = db.relationship('JugadorSala', backref='sala', order_by='JugadorSala.id',
                                 cascade='all, delete-orphan')
    respuestas = db.relationship('Respuesta', backref='sala', cascade='all, delete-orphan')


class JugadorSala(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    sala_id    = db.Column(db.Integer, db.ForeignKey('sala.id'), nullable=False, index=True)
    nombre     = db.Column(db.String(12), nullable=False)
    anfitrion  = db.Column(db.Boolean, nullable=False, default=False)
    # Cuenta a la que se guarda el progreso (vacío si juega sin cuenta)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    puntos     = db.Column(db.Integer, nullable=False, default=0)
    aciertos   = db.Column(db.Integer, nullable=False, default=0)


class Respuesta(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    sala_id    = db.Column(db.Integer, db.ForeignKey('sala.id'), nullable=False, index=True)
    jugador_id = db.Column(db.Integer, db.ForeignKey('jugador_sala.id'), nullable=False)
    ronda      = db.Column(db.Integer, nullable=False)
    texto      = db.Column(db.String(40), nullable=False, default='')
    # Lo siguiente se rellena al corregir la ronda
    pokemon    = db.Column(db.String(40))
    valida     = db.Column(db.Boolean, nullable=False, default=False)
    motivo     = db.Column(db.String(80), nullable=False, default='')
    puntos     = db.Column(db.Integer, nullable=False, default=0)

    # Cada jugador solo puede responder una vez por ronda
    __table_args__ = (db.UniqueConstraint('jugador_id', 'ronda'),)
