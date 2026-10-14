/* Regresión del transporte real del panel; DOM mínimo y red simulada por defecto. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const fuente = fs.readFileSync('bandeja/web/panel.js', 'utf8');
function funcion(nombre) {
  const inicio = fuente.indexOf('    async function ' + nombre + '(') >= 0
    ? fuente.indexOf('    async function ' + nombre + '(')
    : fuente.indexOf('    function ' + nombre + '(');
  assert(inicio >= 0, 'Función del panel no encontrada: ' + nombre);
  const resto = fuente.slice(inicio + 1);
  const siguiente = resto.search(/\n    (?:async )?function /);
  return fuente.slice(inicio, siguiente < 0 ? undefined : inicio + 1 + siguiente);
}

// Solo se sustituye el DOM de navegador; se ejecutan las funciones del proyecto.
class ParserDOM {
  parseFromString(texto, tipo) {
    assert.equal(tipo, 'text/html');
    const meta = texto.match(/<meta name="csrf-token" content="([^"]*)">/);
    return {querySelector: () => meta ? {content: meta[1]} : null};
  }
}
function panel(fetch) {
  const elementos = {
    'sel-capitulo-personaje': {value: 'roli'},
    'txt-capitulo-nombre': {value: 'capitulo prueba'},
    'error-capitulo-activo': {innerText: '', style: {}}
  };
  const contexto = vm.createContext({
    fetch, Headers, DOMParser: ParserDOM, CSRF_TOKEN: 'token_de_pestana_anterior',
    document: {getElementById: id => elementos[id]},
    datosEstado: {}, cargarDatos: async () => {}, mostrarError: mensaje => {throw Error(mensaje);}
  });
  for (const nombre of ['fetchConCsrf', 'apiFetch', 'validarNombreEscena', 'empezarCapitulo']) {
    vm.runInContext(funcion(nombre), contexto);
  }
  return {contexto, elementos};
}
const respuestaHtml = token => new Response('<html><head><meta name="csrf-token" content="' + token + '"></head></html>',
  {headers: {'Content-Type': 'text/html'}});
const respuestaJson = (datos, status = 200) => new Response(JSON.stringify(datos), {status});

async function probar() {
  let token = 'token_vigente_uno';
  const llamadas = [];
  const {contexto, elementos} = panel(async (url, opciones = {}) => {
    llamadas.push({url, opciones});
    if (url === '/panel.html') return respuestaHtml(token);
    assert.equal(opciones.headers.get('X-CSRF-Token'), token);
    assert.equal(opciones.headers.get('Content-Type'), 'application/json');
    assert.equal(opciones.mode, 'same-origin');
    assert.equal(opciones.redirect, 'error');
    return respuestaJson({exito: true});
  });
  await contexto.empezarCapitulo();
  assert.deepEqual(llamadas.map(c => c.url), ['/panel.html', '/api/capitulos/empezar']);
  assert.deepEqual(JSON.parse(llamadas[1].opciones.body), {personaje: 'roli', nombre: 'capitulo prueba'});
  assert.equal(elementos['txt-capitulo-nombre'].value, '');
  assert.equal(llamadas[0].opciones.cache, 'no-store');
  assert.equal(llamadas[0].opciones.mode, 'same-origin');
  assert.equal(llamadas[0].opciones.redirect, 'error');

  // Un segundo reinicio sin recargar la pestaña también obtiene el token actual.
  token = 'token_vigente_dos';
  elementos['txt-capitulo-nombre'].value = 'segundo capitulo';
  await contexto.empezarCapitulo();
  assert.equal(llamadas.filter(c => c.url === '/api/capitulos/empezar').length, 2);
  const headers = new Headers({'x-csrf-token': 'anterior', 'X-Prueba': 'conservar'});
  await contexto.fetchConCsrf('/api/edicion/cancelar-sesion', {method: 'post', headers, body: '{}'});
  assert.equal(llamadas.at(-1).opciones.headers.get('X-Prueba'), 'conservar');
  assert.equal(headers.get('X-CSRF-Token'), 'anterior', 'No modificar opciones del llamador.');

  let lecturas = 0;
  const lectura = panel(async url => {lecturas++; assert.equal(url, '/api/lotes'); return respuestaJson({lotes: []});});
  await lectura.contexto.apiFetch('/api/lotes');
  assert.equal(lecturas, 1, 'Las consultas GET no necesitan renovar el token.');

  for (const fallo of ['sin-meta', 'vacio', 'plantilla', 'http', 'red']) {
    let posts = 0;
    const prueba = panel(async (url, opciones = {}) => {
      if (opciones.method) posts++;
      assert.equal(url, '/panel.html');
      if (fallo === 'red') throw Error('sin conexión');
      if (fallo === 'http') return respuestaJson({error: 'no disponible'}, 503);
      if (fallo === 'sin-meta') return new Response('<html></html>');
      return respuestaHtml(fallo === 'plantilla' ? '__TOKEN_CSRF__' : '');
    });
    await prueba.contexto.empezarCapitulo();
    assert.equal(posts, 0, fallo + ': no enviar sin renovar.');
    assert.equal(prueba.elementos['txt-capitulo-nombre'].value, 'capitulo prueba');
    assert(prueba.elementos['error-capitulo-activo'].innerText);
  }

  // Un resultado rechazado o incierto nunca reenvía una mutación.
  for (const fallo of [403, 409, 500, 'red']) {
    let posts = 0;
    const prueba = panel(async url => {
      if (url === '/panel.html') return respuestaHtml('actual');
      posts++;
      if (fallo === 'red') throw Error('respuesta perdida');
      return respuestaJson({error: 'error esperado', detalle: 'conservar'}, fallo);
    });
    await prueba.contexto.empezarCapitulo();
    assert.equal(posts, 1, 'No repetir POST: ' + fallo);
    assert.equal(prueba.elementos['txt-capitulo-nombre'].value, 'capitulo prueba');
    assert(prueba.elementos['error-capitulo-activo'].innerText);
  }
  console.log('CSRF UI OK: reinicios, capítulo, cabeceras, GET, fallos y ausencia de reenvíos.');
}

async function integrar(base) {
  const destino = new URL(base);
  assert.equal(destino.hostname, '127.0.0.1');
  assert.equal(destino.protocol, 'http:');
  assert.notEqual(destino.port, '8766', 'La integración solo admite un servidor de prueba aislado.');
  let posts = 0;
  const {contexto, elementos} = panel((ruta, opciones = {}) => {
    if (opciones.method) posts++;
    return fetch(new URL(ruta, destino), opciones);
  });
  await contexto.empezarCapitulo();
  assert.equal(elementos['error-capitulo-activo'].innerText, '');
  assert.equal(elementos['txt-capitulo-nombre'].value, '');
  assert.equal(posts, 1);
  console.log('CSRF HTTP OK: capítulo creado una vez en el servidor temporal.');
}

(async () => {
  await probar();
  if (process.argv[2]) await integrar(process.argv[2]);
})().catch(error => {console.error(error); process.exitCode = 1;});
