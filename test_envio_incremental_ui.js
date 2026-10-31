const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fuente = fs.readFileSync('bandeja/web/panel.js', 'utf8');
const inicio = fuente.indexOf('    function formatearBytes(');
const fin = fuente.indexOf('    let carpetasPendriveData', inicio);
assert.ok(inicio >= 0 && fin > inicio);
const elementos = new Map();
function elemento(id) {
  if (!elementos.has(id)) elementos.set(id, {style: {}, disabled: false, innerHTML: '', botones: [],
    querySelectorAll() {
      this.botones = [...this.innerHTML.matchAll(/data-envio-archivo="([^"]+)" data-envio-accion="([^"]+)"/g)].map(m => ({
        dataset: {envioArchivo: m[1], envioAccion: m[2]}, eventos: {},
        addEventListener(tipo, fn) {this.eventos[tipo] = fn;},
      }));
      return this.botones;
    }});
  return elementos.get(id);
}
let plan;
const llamadas = [];
const ctx = vm.createContext({
  document: {getElementById: elemento},
  escapeHTML: s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
  mostrarError: s => {throw Error(s);},
  programarSiguienteSondeo() {},
  apiFetch: async (ruta, datos) => {llamadas.push({ruta, datos}); return plan;},
});
vm.runInContext(fuente.slice(inicio, fin), ctx);

async function probar() {
  // Contrato actual de simular_envio_capitulos, incluidos los campos anidados.
  plan = {
    puede_enviar: true, total_archivos_a_enviar: 3, bytes_a_enviar_fmt: '300 B',
    carpetas_seleccionadas: ['lucie/proyecto'],
    pendrive_id: 'temporal', punto_montaje: '/tmp/pendrive',
    pendrive: {sistema_archivos: 'exfat', espacio_libre_bytes: 100 * 1073741824, margen_libre_bytes: 1073741824},
    archivos_a_copiar: [9, 10, 11].map(n => ({nombre: `foto${n}.jpg`, tipo: 'imagen',
      tamanio_bytes: 100, ruta_relativa_pendrive: `imagenes/lucie/proyecto/foto${n}.jpg`, estado: 'nuevo'})),
    archivos_omitidos: [{nombre: '<video>.mp4', aviso: 'Mismo destino y SHA-256'}],
  };
  await ctx.abrirModalPlanEnvio('lucie/proyecto');
  const boton = elemento('btn-confirmar-envio-pendrive');
  const contenido = elemento('contenido-plan-envio');
  assert.equal(boton.disabled, false);
  assert.match(contenido.innerHTML, /imagenes\/lucie\/proyecto\/foto11.jpg/);
  assert.match(contenido.innerHTML, /100.0 GB/);
  assert.match(contenido.innerHTML, /exfat/);
  assert.match(contenido.innerHTML, /Mismo destino y SHA-256/);
  assert.match(contenido.innerHTML, /&lt;video&gt;/);
  assert.ok(!contenido.innerHTML.includes('<video>'));
  assert.deepEqual(JSON.parse(llamadas[0].datos.body), {carpetas: ['lucie/proyecto']});

  plan = {...plan, puede_enviar: false, total_archivos_a_enviar: 0, archivos_a_copiar: [],
    motivo_bloqueo: 'Todos los archivos ya están en este destino.'};
  await ctx.abrirModalPlanEnvio('lucie/proyecto');
  assert.equal(boton.disabled, true);
  assert.match(contenido.innerHTML, /Todos los archivos ya están en este destino/);
  await ctx.confirmarEnvioPendrive();
  assert.ok(llamadas.every(c => c.ruta.endsWith('envio-simular')));

  plan = {...plan, archivos_conflictos: [{id_archivo: 'id-foto', nombre: 'foto.jpg', tipo: 'imagen',
    ruta_relativa_pendrive: 'imagenes/lucie/proyecto/foto.jpg',
    estado: 'conflicto', aviso: 'Destino ocupado con otro contenido', tamanio_bytes: 100}]};
  await ctx.abrirModalPlanEnvio('lucie/proyecto');
  assert.equal(boton.disabled, true);
  assert.match(contenido.innerHTML, /Destino ocupado con otro contenido/);
  assert.match(contenido.innerHTML, /imagenes\/lucie\/proyecto\/foto.jpg/);
  assert.match(contenido.innerHTML, /Estos archivos ya existen/);
  const renombrar = contenido.botones.find(b => b.dataset.envioAccion === 'renombrar');
  assert.ok(renombrar);
  plan = {...plan, puede_enviar: true, total_archivos_a_enviar: 1, archivos_omitidos: [],
    motivo_bloqueo: null, resoluciones_colisiones: {'id-foto': 'renombrar'}, archivos_conflictos: [],
    archivos_a_copiar: [{id_archivo: 'id-foto', nombre: 'foto.jpg', nombre_destino: 'foto_1.jpg',
      ruta_relativa_pendrive: 'imagenes/lucie/proyecto/foto_1.jpg', tamanio_bytes: 100, estado: 'nuevo'}]};
  await renombrar.eventos.click();
  assert.equal(JSON.parse(llamadas.at(-1).datos.body).resoluciones_colisiones['id-foto'], 'renombrar');
  assert.deepEqual(JSON.parse(llamadas.at(-1).datos.body).carpetas, ['lucie/proyecto']);
  assert.match(contenido.innerHTML, /imagenes\/lucie\/proyecto\/foto_1.jpg/);
  assert.equal(boton.disabled, false);
  const omitir = contenido.botones.find(b => b.dataset.envioAccion === 'omitir');
  plan = {...plan, puede_enviar: false, total_archivos_a_enviar: 0, archivos_a_copiar: [],
    resoluciones_colisiones: {'id-foto': 'omitir'},
    archivos_omitidos: [{id_archivo: 'id-foto', nombre: 'foto.jpg', estado: 'omitido_usuario', aviso: 'No se agrega'}]};
  await omitir.eventos.click();
  assert.equal(JSON.parse(llamadas.at(-1).datos.body).resoluciones_colisiones['id-foto'], 'omitir');
  assert.equal(boton.disabled, true);
  assert.ok(llamadas.every(c => c.ruta.endsWith('envio-simular')), 'Elegir no debe enviar archivos');

  // Una simulación tardía nunca reemplaza la elección más reciente.
  const pendientes = [];
  ctx.apiFetch = () => new Promise(resolve => pendientes.push(resolve));
  const vieja = ctx.abrirModalPlanEnvio('lucie/proyecto');
  const reciente = ctx.abrirModalPlanEnvio('lucie/proyecto');
  pendientes[1]({...plan, puede_enviar: true, total_archivos_a_enviar: 1});
  await reciente;
  pendientes[0](plan);
  await vieja;
  assert.equal(boton.disabled, false);
  console.log('Envío incremental UI OK: pendientes, espacio, cartel, renombrar/no agregar, revisión tardía y ausencia de envíos automáticos.');
}
probar().then(probarSeleccionVacias).catch(error => {console.error(error); process.exitCode = 1;});

async function probarSeleccionVacias() {
  const nodos = new Map();
  const nodo = id => {
    if (!nodos.has(id)) nodos.set(id, {style: {}, innerHTML: '', innerText: '', disabled: false});
    return nodos.get(id);
  };
  let carpetas = [];
  let conectado = true;
  const planes = [], errores = [], consultas = [];
  const contexto = vm.createContext({
    window: {},
    document: {
      getElementById: nodo,
      querySelectorAll() {
        return [...nodo('contenedor-capitulos-pendrive').innerHTML.matchAll(/<input type="checkbox" class="chk-carpeta-pendrive"[^>]+>/g)].map(m => ({
          disabled: /\sdisabled(?:\s|>)/.test(m[0]), checked: false,
          getAttribute: () => m[0].match(/data-carpeta-key="([^"]+)"/)[1],
        }));
      },
    },
    escapeHTML: s => String(s ?? ''),
    apiFetch: async ruta => {
      consultas.push(ruta);
      if (ruta === '/api/pendrive/carpetas') return {carpetas};
      if (ruta === '/api/pendrive/estado') return {conectado};
      if (ruta === '/api/historial') return {historial: []};
      throw Error('Consulta inesperada: ' + ruta);
    },
    mostrarError: mensaje => errores.push(mensaje),
    abrirModalPlanEnvio: seleccion => planes.push(Array.from(seleccion)),
  });
  const inicioSeleccion = fuente.indexOf('    let carpetasPendriveData');
  const finSeleccion = fuente.indexOf('    async function deshacerEnvio', inicioSeleccion);
  vm.runInContext(fuente.slice(inicioSeleccion, finSeleccion), contexto);
  const vacia = {personaje: 'lucie', carpeta: 'publicidad', total_archivos: 0,
    pendientes_conteo: 0, archivos: [], videos: 0, fotos: 0, bytes_totales_fmt: '0 B'};
  const conArchivos = {...vacia, carpeta: 'otro', total_archivos: 1, pendientes_conteo: 1, videos: 1};
  carpetas = [vacia];
  await contexto.cargarVistaPendrive();
  assert.doesNotMatch(nodo('contenedor-estado-pendrive').innerHTML, /Error al cargar/);
  assert.match(nodo('contenedor-capitulos-pendrive').innerHTML, /Carpeta vacía\. No hay archivos para enviar\./);
  assert.match(nodo('contenedor-capitulos-pendrive').innerHTML, /data-carpeta-key="lucie\/publicidad"[^>]*disabled/);
  contexto.seleccionarTodasCarpetasPendrive();
  contexto.toggleSeleccionCarpetaPendrive('lucie/publicidad', true);
  assert.equal(contexto.window.carpetasPendriveSeleccionadas.size, 0);
  assert.equal(nodo('btn-enviar-seleccionadas-pendrive').disabled, true);
  assert.equal(nodo('chk-maestro-carpetas-pendrive').disabled, true);
  contexto.enviarCarpetasSeleccionadasPendrive();
  assert.equal(planes.length, 0);
  assert.equal(errores.length, 1);

  carpetas = [vacia, conArchivos];
  await contexto.cargarVistaPendrive();
  contexto.seleccionarTodasCarpetasPendrive();
  assert.deepEqual(Array.from(contexto.window.carpetasPendriveSeleccionadas), ['lucie/otro']);
  assert.equal(nodo('chk-maestro-carpetas-pendrive').checked, true);
  assert.equal(nodo('chk-maestro-carpetas-pendrive').indeterminate, false);
  assert.equal(nodo('btn-enviar-seleccionadas-pendrive').disabled, false);
  contexto.enviarCarpetasSeleccionadasPendrive();
  assert.deepEqual(planes, [['lucie/otro']]);

  // La carpeta permanece listada pero pierde sus archivos durante el refresco.
  carpetas = [vacia, {...conArchivos, total_archivos: 0, pendientes_conteo: 0}];
  await contexto.cargarVistaPendrive();
  assert.equal(contexto.window.carpetasPendriveSeleccionadas.size, 0);
  assert.equal(nodo('btn-enviar-seleccionadas-pendrive').disabled, true);
  contexto.enviarCarpetasSeleccionadasPendrive();
  assert.equal(planes.length, 1);
  conectado = false;
  await contexto.cargarVistaPendrive();
  assert.match(nodo('contenedor-capitulos-pendrive').innerHTML, /Carpeta vacía/);
  assert.equal(nodo('btn-enviar-seleccionadas-pendrive').disabled, true);
  assert.ok(consultas.every(ruta => ['/api/pendrive/carpetas', '/api/pendrive/estado', '/api/historial'].includes(ruta)));
  console.log('Selección Pendrive UI OK: vacías, selección mixta, refresco, contador, plan acotado y ausencia de envío.');
}
