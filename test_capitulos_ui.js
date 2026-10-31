/* Regresión del cierre real del panel, con DOM y servidor simulados. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fuente = fs.readFileSync(process.env.LUCIE_PANEL_PRUEBA || 'bandeja/web/panel.js', 'utf8');
function funcion(nombre) {
  const inicio = fuente.search(new RegExp('    (?:async )?function ' + nombre + '\\('));
  assert(inicio >= 0, 'Función no encontrada: ' + nombre);
  const siguiente = fuente.slice(inicio + 1).search(/\n    (?:async )?function /);
  return fuente.slice(inicio, siguiente < 0 ? undefined : inicio + 1 + siguiente);
}
function panel({pendientes = 0, secundario = false, lotes = []} = {}) {
  const principal = {id: 2, personaje: 'roli', nombre: 'roliferne', habilitado: true,
    balance: {pendientes: secundario ? 0 : pendientes, movidos: 3},
    carpeta_info: {ya_existia: true, total_archivos: 3, mensaje: 'La carpeta ya existía y tiene 3 archivos'}};
  const otro = {id: 1, personaje: 'lucie', nombre: 'otra historia', habilitado: true,
    balance: {pendientes, movidos: 0}};
  let abiertos = secundario ? [otro, principal] : [principal];
  let foco = principal;
  const llamadas = [], errores = [], avisos = [], selecciones = {};
  const elementos = {};
  const el = id => elementos[id] ||= {style: {}, value: '', innerText: '', innerHTML: ''};
  const estado = () => ({capitulo_foco: foco, capitulo: foco || {habilitado: false},
    capitulos_abiertos: abiertos, cantidad_abiertos: abiertos.length, balance: foco?.balance});
  const contexto = vm.createContext({
    capituloATerminarId: null, terminarCapituloTrasMover: null, simulacionActiva: null,
    loteActivoId: null, pestanaActual: 'lotes', versionActualToken: null,
    datosEstado: {...estado(), capitulo_activo: foco, lotes},
    document: {getElementById: el, querySelectorAll: selector => selecciones[selector] || []},
    programarSiguienteSondeo: () => {}, mostrarError: msg => errores.push(msg),
    mostrarToastLlegada: msg => avisos.push(msg), escapeHTML: String,
    renderLotes: () => {}, renderLotesAnteriores: () => {}, renderSinIdentificar: () => {},
    mostrarAvisoMover: () => {}, cargarCapitulosAbiertos: async () => {},
    cargarCapitulosCerrados: async () => {}, cargarHistorial: async () => {},
    mostrarModalSimulacion: () => {el('modal-simulacion').style.display = 'flex';},
    apiFetch: async (url, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : null;
      llamadas.push({url, body});
      if (contexto.fallar === url) throw new Error('Fallo simulado');
      if (url === '/api/capitulos/estado') return estado();
      if (url === '/api/capitulos/terminar') {
        assert(abiertos.some(c => c.id === body.id), 'Cerrar solo un ID abierto explícito');
        abiertos = abiertos.filter(c => c.id !== body.id);
        if (foco?.id === body.id) foco = null;
        return {exito: true};
      }
      if (url === '/api/simular-mover') return {es_multilote: true, simulaciones_lotes: body.lotes};
      if (url === '/api/mover-lote') return {es_multilote: true, total_movidos: 2, resultados: []};
      if (url === '/api/lotes') return {lotes};
      return {};
    }
  });
  for (const nombre of ['abrirModalTerminarCapitulo', 'cerrarModalTerminarCapitulo',
    'ejecutarTerminarCapitulo', 'ejecutarMoverYTerminar', 'cerrarModal', 'ejecutarMoverLote',
    'cargarDatos', 'renderCapituloActivo']) vm.runInContext(funcion(nombre), contexto);
  return {contexto, elementos, llamadas, errores, avisos, selecciones, principal, otro, estado};
}
const lote = (id, personaje = 'roli', escena = 'roliferne') => ({lote_id: id,
  personaje_sugerido: personaje, escena_sugerida: escena, archivos: [{id_db: id + '-1'}]});
function seleccionar(p, id) {
  p.selecciones[`.chk-lote-${id}:checked`] = [{getAttribute: () => id + '-1'}];
}
async function probar() {
  // Carpeta ya existente y material organizado: un clic libera el foco y muestra crear.
  let p = panel();
  await p.contexto.abrirModalTerminarCapitulo();
  assert.equal(p.estado().cantidad_abiertos, 0);
  assert.equal(p.elementos['banner-capitulo-activo'].style.display, 'none');
  assert.equal(p.elementos['card-empezar-capitulo'].style.display, 'block');
  assert(p.avisos.some(m => m.includes('Capítulo terminado')));
  assert.equal(p.llamadas.filter(c => c.body).length, 1, 'No mover ni recrear la carpeta existente');

  // Una consulta auxiliar fallida no debe dejar pegado un foco que ya se cerró.
  p = panel(); p.contexto.fallar = '/api/escenas';
  await p.contexto.abrirModalTerminarCapitulo();
  assert.equal(p.estado().cantidad_abiertos, 0);
  assert.equal(p.elementos['banner-capitulo-activo'].style.display, 'none');
  assert.equal(p.elementos['card-empezar-capitulo'].style.display, 'block');
  assert.deepEqual(p.errores, ['Fallo simulado']);

  // Con pendientes se muestra el resumen, sin cerrar ni mover antes de decidir.
  p = panel({pendientes: 1});
  await p.contexto.abrirModalTerminarCapitulo();
  assert.equal(p.elementos['modal-terminar-capitulo'].style.display, 'flex');
  assert.equal(p.estado().cantidad_abiertos, 1);

  // Una selección vacía o una simulación fallida no pierde el ID ni cierra el modal.
  p = panel({pendientes: 1, lotes: [lote('a')]});
  await p.contexto.abrirModalTerminarCapitulo();
  await p.contexto.ejecutarMoverYTerminar();
  assert.equal(p.estado().cantidad_abiertos, 1);
  assert.equal(p.contexto.capituloATerminarId, 2);
  assert.equal(p.elementos['modal-terminar-capitulo'].style.display, 'flex');
  seleccionar(p, 'a'); p.contexto.fallar = '/api/simular-mover';
  await p.contexto.ejecutarMoverYTerminar();
  assert.equal(p.estado().cantidad_abiertos, 1);
  assert.equal(p.contexto.capituloATerminarId, 2);
  assert.equal(p.elementos['modal-terminar-capitulo'].style.display, 'flex');
  await p.contexto.ejecutarTerminarCapitulo(false);
  assert.equal(p.estado().cantidad_abiertos, 0);
  assert(!p.llamadas.some(c => c.url === '/api/mover-lote'));

  // Uno o varios lotes: solo el capítulo elegido, con simulación y confirmación.
  for (const cantidad of [1, 2]) {
    p = panel({pendientes: cantidad, lotes: [lote('a'), ...(cantidad === 2 ? [lote('b')] : []),
      lote('ajeno', 'lucie', 'roliferne'), lote('otra', 'roli', 'otra historia')]});
    for (const id of ['a', 'b', 'ajeno', 'otra']) seleccionar(p, id);
    await p.contexto.abrirModalTerminarCapitulo();
    await p.contexto.ejecutarMoverYTerminar();
    assert.deepEqual(p.errores, []);
    const sim = p.llamadas.find(c => c.url === '/api/simular-mover');
    assert.equal(sim.body.lotes.length, cantidad);
    assert(sim.body.lotes.every(l => l.personaje === 'roli' && l.escena === 'roliferne'));
    assert.equal(p.estado().cantidad_abiertos, 1, 'La simulación no termina el capítulo');
    await p.contexto.ejecutarMoverLote();
    assert.equal(p.estado().cantidad_abiertos, 0, 'Confirmar movimiento debe terminar el capítulo');
    assert.deepEqual(p.llamadas.filter(c => ['/api/mover-lote', '/api/capitulos/terminar'].includes(c.url))
      .map(c => c.url), ['/api/mover-lote', '/api/capitulos/terminar']);
    assert.deepEqual(p.errores, []);
  }

  // Cancelar una simulación no cierra ahora ni después de otro movimiento normal.
  p = panel({pendientes: 1, lotes: [lote('a')]}); seleccionar(p, 'a');
  await p.contexto.abrirModalTerminarCapitulo();
  await p.contexto.ejecutarMoverYTerminar();
  p.contexto.cerrarModal();
  p.contexto.simulacionActiva = {es_multilote: true};
  await p.contexto.ejecutarMoverLote();
  assert.equal(p.estado().cantidad_abiertos, 1);

  // Un secundario no debe terminar el foco; tampoco si cambia mientras se mueve.
  p = panel({pendientes: 1, secundario: true, lotes: [lote('s', 'lucie', 'otra historia')]});
  seleccionar(p, 's');
  await p.contexto.abrirModalTerminarCapitulo(1);
  await p.contexto.ejecutarMoverYTerminar();
  await p.contexto.ejecutarMoverLote();
  assert.equal(p.estado().capitulo_foco.id, 2);
  assert.equal(p.estado().cantidad_abiertos, 1);
  assert.deepEqual(p.errores, []);

  // Un fallo de movimiento conserva el capítulo abierto y permite cancelar/reintentar.
  p = panel({pendientes: 1, lotes: [lote('a')]}); seleccionar(p, 'a');
  await p.contexto.abrirModalTerminarCapitulo(); await p.contexto.ejecutarMoverYTerminar();
  p.contexto.fallar = '/api/mover-lote';
  await p.contexto.ejecutarMoverLote();
  assert.equal(p.estado().cantidad_abiertos, 1);
  assert.equal(p.elementos['modal-simulacion'].style.display, 'flex');
  assert.deepEqual(p.errores, ['Fallo simulado']);
  p.contexto.fallar = null; await p.contexto.ejecutarMoverLote();
  assert.equal(p.estado().cantidad_abiertos, 0);

  // Un error al cerrar se informa al usuario, aunque el movimiento ya haya terminado.
  p = panel(); p.contexto.fallar = '/api/capitulos/terminar';
  await p.contexto.abrirModalTerminarCapitulo();
  assert.equal(p.estado().cantidad_abiertos, 1);
  assert.deepEqual(p.errores, ['Fallo simulado']);
  assert.equal(p.avisos.length, 0);

  // Una tarjeta obsoleta no puede cerrar otro capítulo por accidente.
  p = panel({secundario: true});
  await p.contexto.abrirModalTerminarCapitulo(999);
  assert.equal(p.estado().cantidad_abiertos, 2);
  assert.equal(p.errores.length, 1);
  console.log('OK: cierre directo, pendientes, lotes acotados, cancelación, ID y errores.');
}
probar().then(probarTitulos).catch(error => {console.error(error); process.exitCode = 1;});

async function probarTitulos() {
  const nodos = new Map();
  const nodo = id => {
    if (!nodos.has(id)) nodos.set(id, {value: '', style: {}, innerText: ''});
    return nodos.get(id);
  };
  const llamadas = [];
  const ctx = vm.createContext({
    document: {getElementById: nodo},
    apiFetch: async (ruta, opciones) => {llamadas.push({ruta, datos: JSON.parse(opciones.body)}); return {};},
    cargarDatos: async () => {},
    datosEstado: {},
    mostrarError: msg => {throw Error(msg);},
  });
  vm.runInContext(funcion('validarNombreEscena') + funcion('empezarCapitulo'), ctx);
  for (const titulo of ['Luna de paseo', 'LUCIE 2026', 'Roli y Mailén', 'Café con Luna', 'Mix X1F 09',
                         'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz', '0123456789']) {
    assert.equal(ctx.validarNombreEscena(titulo), null, titulo);
    nodo('sel-capitulo-personaje').value = 'luna';
    nodo('txt-capitulo-nombre').value = titulo;
    await ctx.empezarCapitulo();
    assert.deepEqual(llamadas.at(-1), {ruta: '/api/capitulos/empezar', datos: {personaje: 'luna', nombre: titulo}},
      'El título debe enviarse conservando mayúsculas, acentos y números');
  }
  const cantidad = llamadas.length;
  const invalidos = ['', '   ', 'Luna/otra', 'Luna\\otra', 'Luna..otra', 'Luna.', 'CON', 'con.mp4', 'NUL', 'LPT9.txt',
    'a'.repeat(101), ...Array.from('<>:"|?*', c => 'Luna' + c + 'otra'),
    ...Array.from({length: 32}, (_, n) => 'Luna' + String.fromCharCode(n) + 'otra')];
  for (const titulo of invalidos) {
    assert(ctx.validarNombreEscena(titulo), 'Debe rechazar ' + JSON.stringify(titulo));
    nodo('txt-capitulo-nombre').value = titulo;
    await ctx.empezarCapitulo();
    assert.equal(llamadas.length, cantidad, 'Los nombres inválidos no deben llamar a la API');
  }
  console.log('Títulos UI OK: mayúsculas, acentos y números intactos; rutas, reservados y controles bloqueados.');
}
