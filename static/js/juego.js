// Lleva el desarrollo de la partida en el navegador: turnos, reloj y pantallas.
// La corrección de las respuestas la hace el servidor (game_mode/motor.py).

const datos = JSON.parse(document.getElementById('datos-partida').textContent);
const tokenCsrf = document.querySelector('meta[name="csrf-token"]').content;

const partida = {
    nombres: [],
    totales: [],      // puntos acumulados de cada jugador
    ronda: 0,        // índice de la ronda actual
    turno: 0,         // índice del jugador que está escribiendo
    respuestas: [],   // respuestas de la ronda actual
};

let intervaloReloj = null;

const $ = (id) => document.getElementById(id);

function mostrar(idPantalla) {
    document.querySelectorAll('.pantalla').forEach((pantalla) => {
        pantalla.hidden = pantalla.id !== idPantalla;
    });
    window.scrollTo(0, 0);
}

function celda(fila, texto, clase) {
    const td = document.createElement('td');
    td.textContent = texto;
    if (clase) td.className = clase;
    fila.appendChild(td);
    return td;
}

// 1. NOMBRES

function prepararNombres() {
    const lista = $('lista-nombres');
    for (let i = 0; i < datos.jugadores; i++) {
        const etiqueta = document.createElement('label');
        etiqueta.textContent = `Jugador ${i + 1}`;
        etiqueta.htmlFor = `nombre-${i}`;

        const campo = document.createElement('input');
        campo.type = 'text';
        campo.id = `nombre-${i}`;
        campo.maxLength = 12;
        campo.placeholder = `Jugador ${i + 1}`;
        campo.autocomplete = 'off';

        lista.append(etiqueta, campo);
    }
}

$('form-nombres').addEventListener('submit', (evento) => {
    evento.preventDefault();
    for (let i = 0; i < datos.jugadores; i++) {
        const escrito = $(`nombre-${i}`).value.trim();
        partida.nombres.push(escrito || `Jugador ${i + 1}`);
        partida.totales.push(0);
    }
    empezarRonda();
});

// 2. PASE DEL MÓVIL

function empezarRonda() {
    partida.turno = 0;
    partida.respuestas = [];
    mostrarPase();
}

function mostrarPase() {
    $('pase-ronda').textContent = `Ronda ${partida.ronda + 1} de ${datos.categorias.length}`;
    $('pase-jugador').textContent = `Turno de ${partida.nombres[partida.turno]}`;
    mostrar('pantalla-pase');
}

$('btn-listo').addEventListener('click', empezarTurno);

// 3. TURNO

function empezarTurno() {
    $('turno-jugador').textContent = partida.nombres[partida.turno];
    $('turno-tipo').textContent = datos.categorias[partida.ronda];
    $('turno-respuesta').value = '';
    mostrar('pantalla-turno');
    $('turno-respuesta').focus();

    let restante = datos.segundos;
    pintarReloj(restante);
    intervaloReloj = setInterval(() => {
        restante -= 1;
        pintarReloj(restante);
        if (restante <= 0) terminarTurno();   // se envía lo que haya escrito
    }, 1000);
}

function pintarReloj(segundos) {
    const reloj = $('turno-reloj');
    reloj.textContent = segundos;
    reloj.classList.toggle('reloj-urgente', segundos <= 5);
}

function terminarTurno() {
    clearInterval(intervaloReloj);
    partida.respuestas.push($('turno-respuesta').value.trim());
    $('turno-respuesta').value = '';
    $('turno-respuesta').blur();

    partida.turno += 1;
    if (partida.turno < datos.jugadores) {
        mostrarPase();
    } else {
        corregirRonda();
    }
}

$('form-turno').addEventListener('submit', (evento) => {
    evento.preventDefault();
    terminarTurno();
});

// 4. CORRECCIÓN DE LA RONDA

async function corregirRonda() {
    const tipo = datos.categorias[partida.ronda];
    $('ronda-titulo').textContent = `Ronda ${partida.ronda + 1}: tipo ${tipo}`;
    $('ronda-estado').textContent = 'Corrigiendo...';
    $('ronda-estado').hidden = false;
    $('ronda-tabla').hidden = true;
    $('btn-siguiente').hidden = true;
    $('btn-reintentar').hidden = true;
    mostrar('pantalla-ronda');

    let resultados;
    try {
        const respuesta = await fetch(datos.urlRonda, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tokenCsrf },
            body: JSON.stringify({ tipo: tipo, respuestas: partida.respuestas }),
        });
        if (!respuesta.ok) throw new Error(`Error ${respuesta.status}`);
        resultados = (await respuesta.json()).resultados;
    } catch (error) {
        $('ronda-estado').textContent = 'No se pudo conectar con el servidor.';
        $('btn-reintentar').hidden = false;
        return;
    }

    const cuerpo = $('ronda-tabla').querySelector('tbody');
    cuerpo.replaceChildren();
    resultados.forEach((resultado, i) => {
        partida.totales[i] += resultado.puntos;

        const fila = document.createElement('tr');
        celda(fila, partida.nombres[i]);

        const respuesta = celda(fila, resultado.pokemon || resultado.respuesta || '—');
        const motivo = document.createElement('small');
        motivo.textContent = resultado.motivo;
        respuesta.appendChild(motivo);

        celda(fila, `+${resultado.puntos}`, resultado.valida ? 'acierto' : 'fallo');
        celda(fila, partida.totales[i]);
        cuerpo.appendChild(fila);
    });

    const ultima = partida.ronda === datos.categorias.length - 1;
    $('btn-siguiente').textContent = ultima ? '▶ Ver resultado final' : '▶ Siguiente ronda';
    $('ronda-estado').hidden = true;
    $('ronda-tabla').hidden = false;
    $('btn-siguiente').hidden = false;
}

$('btn-reintentar').addEventListener('click', corregirRonda);

$('btn-siguiente').addEventListener('click', () => {
    partida.ronda += 1;
    if (partida.ronda < datos.categorias.length) {
        empezarRonda();
    } else {
        mostrarFinal();
    }
});

// 5. RESULTADO FINAL

function mostrarFinal() {
    const maximo = Math.max(...partida.totales);
    const ganadores = partida.nombres.filter((_, i) => partida.totales[i] === maximo);

    if (maximo === 0) {
        $('final-ganador').textContent = 'Nadie ha puntuado';
    } else if (ganadores.length === 1) {
        $('final-ganador').textContent = `¡Gana ${ganadores[0]}!`;
    } else {
        $('final-ganador').textContent = `¡Empate: ${ganadores.join(' y ')}!`;
    }

    const orden = partida.nombres
        .map((nombre, i) => ({ nombre: nombre, puntos: partida.totales[i] }))
        .sort((a, b) => b.puntos - a.puntos);

    const cuerpo = $('final-tabla');
    cuerpo.replaceChildren();
    orden.forEach((jugador, i) => {
        const fila = document.createElement('tr');
        // Los empatados comparten puesto.
        const puesto = i > 0 && orden[i - 1].puntos === jugador.puntos ? '=' : i + 1;
        celda(fila, puesto);
        celda(fila, jugador.nombre);
        celda(fila, jugador.puntos);
        if (jugador.puntos === maximo && maximo > 0) fila.className = 'destacado';
        cuerpo.appendChild(fila);
    });

    mostrar('pantalla-final');
}

prepararNombres();
