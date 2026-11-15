// Partida online. Este archivo no decide nada del juego: cada segundo y medio
// pregunta al servidor cómo está la sala y pinta la pantalla que corresponda.
// Las reglas, el reloj y la puntuación viven en game_mode/salas.py.

const datos = JSON.parse(document.getElementById('datos-sala').textContent);
const tokenCsrf = document.querySelector('meta[name="csrf-token"]').content;

const MS_ENTRE_CONSULTAS = 1500;

let ultimo = null;          // último estado recibido del servidor
let rondaPintada = null;    // para saber cuándo empieza una ronda nueva
let finReloj = 0;           // momento local en que se acaba la fase actual
let fallosSeguidos = 0;

const $ = (id) => document.getElementById(id);

function mostrar(idPantalla) {
    document.querySelectorAll('.pantalla').forEach((pantalla) => {
        pantalla.hidden = pantalla.id !== idPantalla;
    });
}

function avisar(texto) {
    $('aviso').textContent = texto || '';
    $('aviso').hidden = !texto;
}

function celda(fila, texto, clase) {
    const td = document.createElement('td');
    td.textContent = texto;
    if (clase) td.className = clase;
    fila.appendChild(td);
    return td;
}

// COMUNICACIÓN CON EL SERVIDOR

async function pedir(url, cuerpo) {
    const opciones = cuerpo === undefined ? {} : {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tokenCsrf },
        body: JSON.stringify(cuerpo),
    };
    const respuesta = await fetch(url, opciones);
    if (respuesta.status === 403 || respuesta.status === 404) {
        // La sala ha caducado o este navegador ya no pertenece a ella
        window.location.href = '/online';
        return null;
    }
    if (!respuesta.ok) throw new Error(`Error ${respuesta.status}`);
    return respuesta.json();
}

async function accion(url, cuerpo) {
    try {
        const estado = await pedir(url, cuerpo);
        if (estado) pintar(estado);
    } catch (error) {
        avisar('No se pudo conectar. Inténtalo otra vez.');
    }
}

async function consultar() {
    try {
        const estado = await pedir(datos.urlEstado);
        if (estado) pintar(estado);
        fallosSeguidos = 0;
    } catch (error) {
        fallosSeguidos += 1;
        if (fallosSeguidos >= 3) avisar('Sin conexión. Reintentando...');
    }
    setTimeout(consultar, MS_ENTRE_CONSULTAS);
}

// PINTAR LA PANTALLA

function pintar(estado) {
    ultimo = estado;
    avisar(estado.aviso);
    finReloj = Date.now() + estado.segundos * 1000;

    if (estado.estado === 'espera') {
        rondaPintada = null;
        pintarEspera(estado);
    } else if (estado.estado === 'jugando') {
        pintarJugando(estado);
    } else {
        pintarResultados(estado);
    }
    pintarReloj();
}

function listaJugadores(lista, estado, conEstado) {
    lista.replaceChildren();
    estado.jugadores.forEach((jugador) => {
        const elemento = document.createElement('li');
        let texto = jugador.nombre;
        if (jugador.yo) texto += ' (tú)';
        if (jugador.anfitrion && !conEstado) texto += ' ★';
        if (conEstado) texto += jugador.respondio ? ' ✔' : ' ...';
        elemento.textContent = texto;
        if (jugador.yo) elemento.className = 'destacado';
        lista.appendChild(elemento);
    });
}

function pintarEspera(estado) {
    listaJugadores($('espera-jugadores'), estado, false);
    const suficientes = estado.jugadores.length >= estado.minJugadores;
    $('btn-empezar').hidden = !(estado.soyAnfitrion && suficientes);
    if (!suficientes) {
        $('espera-nota').textContent = `Hacen falta al menos ${estado.minJugadores} jugadores.`;
    } else if (estado.soyAnfitrion) {
        $('espera-nota').textContent = 'Cuando estéis todos, empieza la partida.';
    } else {
        $('espera-nota').textContent = 'Esperando a que el anfitrión (★) empiece la partida...';
    }
    mostrar('pantalla-espera');
}

function pintarJugando(estado) {
    $('jugando-ronda').textContent = `Ronda ${estado.ronda} de ${estado.rondas}`;
    $('jugando-tipo').textContent = estado.tipo;
    $('form-respuesta').hidden = estado.heRespondido;
    $('jugando-enviada').hidden = !estado.heRespondido;
    listaJugadores($('jugando-jugadores'), estado, true);
    mostrar('pantalla-jugando');

    if (rondaPintada !== estado.ronda) {     // acaba de empezar una ronda
        rondaPintada = estado.ronda;
        $('respuesta').value = '';
        if (!estado.heRespondido) $('respuesta').focus();
    }
}

function pintarResultados(estado) {
    const final = estado.estado === 'final';
    $('resultados-titulo').textContent = final
        ? 'Resultado final'
        : `Ronda ${estado.ronda}: tipo ${estado.tipo}`;

    const filas = [...estado.resultados];
    if (final) filas.sort((a, b) => b.total - a.total);

    const cuerpo = $('resultados-tabla');
    cuerpo.replaceChildren();
    filas.forEach((resultado) => {
        const fila = document.createElement('tr');
        if (resultado.yo) fila.className = 'destacado';
        celda(fila, resultado.nombre);
        const respuesta = celda(fila, resultado.respuesta || '—');
        const motivo = document.createElement('small');
        motivo.textContent = resultado.motivo;
        respuesta.appendChild(motivo);
        celda(fila, `+${resultado.puntos}`, resultado.valida ? 'acierto' : 'fallo');
        celda(fila, resultado.total);
        cuerpo.appendChild(fila);
    });

    const ganador = $('resultados-ganador');
    ganador.hidden = !final;
    if (final) {
        const maximo = Math.max(...estado.jugadores.map((j) => j.puntos));
        if (maximo === 0) {
            ganador.textContent = 'Nadie ha puntuado';
        } else if (estado.ganadores.length === 1) {
            ganador.textContent = `¡Gana ${estado.ganadores[0]}!`;
        } else {
            ganador.textContent = `¡Empate: ${estado.ganadores.join(' y ')}!`;
        }
    }

    $('btn-reiniciar').hidden = !(final && estado.soyAnfitrion);
    $('btn-salir').hidden = !final;
    mostrar('pantalla-resultados');
}

// El servidor manda los segundos que quedan; entre consulta y consulta el
// reloj baja solo para que no vaya a saltos.
function pintarReloj() {
    if (!ultimo) return;
    const segundos = Math.max(0, Math.ceil((finReloj - Date.now()) / 1000));

    if (ultimo.estado === 'jugando') {
        const reloj = $('jugando-reloj');
        reloj.textContent = segundos;
        reloj.classList.toggle('reloj-urgente', segundos <= 5);
    } else if (ultimo.estado === 'resultados') {
        $('resultados-nota').textContent = `Siguiente ronda en ${segundos}...`;
    } else if (ultimo.estado === 'final') {
        if (ultimo.guardado) {
            $('resultados-nota').textContent = 'Partida guardada en tu cuenta.';
        } else {
            $('resultados-nota').textContent = 'Inicia sesión antes de jugar para aparecer en el ranking.';
        }
    }
}

// BOTONES

$('btn-empezar').addEventListener('click', () => accion(datos.urlEmpezar, {}));
$('btn-reiniciar').addEventListener('click', () => accion(datos.urlReiniciar, {}));

$('form-respuesta').addEventListener('submit', (evento) => {
    evento.preventDefault();
    const texto = $('respuesta').value.trim();
    if (!texto) return;
    $('form-respuesta').hidden = true;      // evita envíos dobles
    accion(datos.urlResponder, { texto: texto });
});

setInterval(pintarReloj, 250);
consultar();
