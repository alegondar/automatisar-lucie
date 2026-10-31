const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fuente = fs.readFileSync('bandeja/web/panel.js', 'utf8');
function extraer(nombre, siguiente) {
  const inicio = fuente.search(new RegExp(`    (?:async )?function ${nombre}\\(`));
  const resto = fuente.slice(inicio).search(new RegExp(`    (?:async )?function ${siguiente}\\(`));
  const fin = resto < 0 ? -1 : inicio + resto;
  assert.ok(inicio >= 0 && fin > inicio);
  return fuente.slice(inicio, fin);
}
function elemento() {
  return {textContent: '', children: [], style: {}, disabled: false, eventos: {},
    replaceChildren() { this.children = []; }, append(...hijos) { this.children.push(...hijos); },
    addEventListener(tipo, fn) { this.eventos[tipo] = fn; }};
}
async function probar() {
  const cont = elemento(); const avisos = []; const llamadas = [];
  let modo = 'copiado';
  let pendientes = [];
  const confirmaciones = [];
  const ctx = vm.createContext({
    document: {getElementById: () => cont, createElement: elemento},
    confirm: mensaje => {confirmaciones.push(mensaje); return true;}, alert: mensaje => { throw Error(mensaje); },
    escapeHTML: s => String(s).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    mostrarAvisoEdicion: mensaje => avisos.push(mensaje), cargarVistaEdicion: async () => {},
    apiFetch: async (ruta, datos) => { llamadas.push({ruta, datos}); return {export_final: {modo, mensaje: 'Esperando export'}}; },
    fetchConCsrf: async (ruta, datos) => {
      llamadas.push({ruta, datos}); return {json: async () => ({exito: true, movidos: [{}], retiro_originales: {pendientes},
        export_final: {modo, mensaje: modo === 'copiado' ? 'Video final copiado' : 'Falta copiar: sin espacio',
          destino: modo === 'copiado' ? 'videos completos/videos sin publicar/lucie/Cafe.mp4' : undefined}})};
    }
  });
  vm.runInContext(extraer('renderizarSesionesEsperandoExport', 'renderizarSesionesEnEdicion'), ctx);
  vm.runInContext(extraer('terminarEdicionSesion', 'deshacerTerminarEdicion'), ctx);
  vm.runInContext(extraer('renderizarTrasladosPendientes', 'renderizarSesionesEsperandoExport'), ctx);
  ctx.renderizarSesionesEsperandoExport([{id: 7, nombre: '<img>', personaje: 'lucie', capitulo: 'Cafe'}], []);
  assert.equal(cont.children.length, 1);
  assert.ok(cont.children[0].children[0].textContent.includes('<img>'));
  const boton = cont.children[0].children[1];
  assert.equal(boton.textContent, 'Revisar video final');
  await boton.eventos.click();
  assert.equal(llamadas[0].ruta, '/api/edicion/revisar-export');
  assert.deepEqual(JSON.parse(llamadas[0].datos.body), {sesion_id: 7});
  await ctx.terminarEdicionSesion(7);
  assert.ok(avisos.at(-1).includes('Video final copiado'));
  assert.ok(avisos.at(-1).includes('videos completos/videos sin publicar'));
  modo = 'error'; await ctx.terminarEdicionSesion(7);
  assert.ok(avisos.at(-1).includes('sin espacio'));
  assert.ok(!avisos.at(-1).includes('Video final copiado'));
  assert.equal(llamadas.filter(c => c.ruta === '/api/edicion/terminar').length, 2);
  pendientes = [{clip: 'clip.mp4'}];
  await ctx.terminarEdicionSesion(7);
  assert.ok(avisos.at(-1).includes('siguen en Sin editar'));
  assert.ok(avisos.at(-1).includes('automáticamente'));
  assert.ok(!avisos.at(-1).includes('Traslado completado'));
  const historico = {id: 7, nombre: '<Cafe>', archivos: [{origen: 'sin editar/clip.mp4', destino: 'ya editados/clip.mp4', resguardo: '_enviados/edicion/clip.mp4', automatico: false}]};
  const antes = llamadas.length;
  ctx.renderizarTrasladosPendientes([historico]);
  assert.equal(llamadas.length, antes, 'Mostrar pendientes no debe mover archivos');
  assert.ok(cont.children[0].children[0].textContent.includes('edición anterior'));
  assert.ok(!cont.children[0].children[0].textContent.includes('Cerrá el proyecto de CapCut'));
  const completar = cont.children[0].children[1];
  assert.equal(completar.textContent, 'Completar traslado');
  ctx.confirm = () => false;
  await completar.eventos.click();
  assert.equal(llamadas.length, antes);
  ctx.confirm = mensaje => {confirmaciones.push(mensaje); return true;};
  await completar.eventos.click();
  assert.equal(llamadas.length, antes + 1);
  assert.ok(confirmaciones.at(-1).includes(historico.archivos[0].origen));
  assert.ok(confirmaciones.at(-1).includes(historico.archivos[0].destino));
  assert.ok(confirmaciones.at(-1).includes(historico.archivos[0].resguardo));
  ctx.renderizarTrasladosPendientes([]);
  assert.equal(cont.children.length, 0);
  ctx.renderizarSesionesEsperandoExport([], []);
  assert.equal(cont.children.length, 0);
  const campos = new Map();
  const titulo = 'Caballero lo estamos llamando';
  const capitulo = titulo + ' - jueves - semana 3 - octubre - 2026';
  const clips = [1, 2].map(n => ({identificador: String(n), personaje: 'lucie', capitulo,
    nombre: `Toma ${n}.mp4`, nombre_sesion_sugerido: `Toma ${n}`, nombre_capitulo_sugerido: titulo}));
  ctx.document.getElementById = id => {
    if (!campos.has(id)) campos.set(id, {style: {}, value: '', innerHTML: '', innerText: ''});
    return campos.get(id);
  };
  ctx.clipsParaEditar = clips;
  ctx.clipsSeleccionadosParaEditar = new Set(['1', '2']);
  vm.runInContext('let sesionModalClips = [];', ctx);
  vm.runInContext(extraer('abrirModalCrearSesion', 'cerrarModalCrearSesion'), ctx);
  ctx.abrirModalCrearSesion();
  assert.equal(campos.get('input-nombre-sesion').value, titulo);
  assert.equal(campos.get('conteo-clips-modal').innerText, '2');
  assert.equal(campos.get('modal-crear-sesion').style.display, 'flex');
  ctx.clipsSeleccionadosParaEditar = new Set(['1']);
  ctx.abrirModalCrearSesion();
  assert.equal(campos.get('input-nombre-sesion').value, 'Toma 1');
  assert.equal(campos.get('conteo-clips-modal').innerText, '1');
  clips[0].nombre_sesion_sugerido = 'Café y canción 🎬';
  ctx.abrirModalCrearSesion();
  assert.equal(campos.get('input-nombre-sesion').value, 'Café y canción 🎬');
  const resumen = elemento();
  const lista = elemento();
  campos.set('aviso-traslados-edicion', resumen);
  campos.set('contenedor-traslados-pendientes', lista);
  ctx.renderizarTrasladosPendientes([{id: 32, nombre: 'Lucie pedo', archivos: [{automatico: true, en_uso: true}]}]);
  assert.equal(resumen.style.display, 'block');
  assert(resumen.textContent.includes('Ya editados'));
  assert(resumen.textContent.includes('automáticamente'));
  assert(lista.children[0].children[0].textContent.includes('Windows los mantiene en uso'));
  ctx.renderizarTrasladosPendientes([historico]);
  assert(resumen.textContent.includes('requieren Completar traslado'));
  ctx.renderizarTrasladosPendientes([]);
  assert.equal(resumen.style.display, 'none');

  vm.runInContext(extraer('guardarExportSinPublicar', 'asignarExportASesion'), ctx);
  const campoTitulo = {value: '', focus() {this.enfocado = true;}};
  const campoPersonaje = {value: 'lucie'};
  campos.set('titulo-export-41', campoTitulo);
  campos.set('personaje-export-41', campoPersonaje);
  const resguardos = [];
  const plan = {token: 'plan-nombre', origen: 'CapCut/1005.mp4', destino: 'Sin publicar/lucie/Café y canción.mp4', tamano: 100};
  ctx.apiFetch = async (ruta, datos) => {
    const cuerpo = JSON.parse(datos.body); resguardos.push({ruta, cuerpo});
    return ruta.endsWith('resguardar-simular') ? plan : {destino: plan.destino};
  };
  await ctx.guardarExportSinPublicar(41);
  assert.equal(resguardos.length, 0, 'Sin título no se copia ni se simula con el número de CapCut.');
  assert(campoTitulo.enfocado);
  campoTitulo.value = 'Café y canción';
  ctx.confirm = () => false;
  await ctx.guardarExportSinPublicar(41);
  assert.equal(resguardos.length, 1, 'Cancelar el plan no ejecuta el resguardo.');
  ctx.confirm = mensaje => {confirmaciones.push(mensaje); return true;};
  await ctx.guardarExportSinPublicar(41);
  assert.deepEqual(resguardos.at(-2).cuerpo, {export_id: 41, titulo: 'Café y canción', personaje: 'lucie'});
  assert.deepEqual(resguardos.at(-1).cuerpo, {token: plan.token, confirmacion: true});
  assert(confirmaciones.at(-1).includes(plan.origen));
  assert(confirmaciones.at(-1).includes(plan.destino));
  ctx.confirm = () => {campoTitulo.value = 'Otro título'; return true;};
  const antesCambio = resguardos.length;
  await ctx.guardarExportSinPublicar(41);
  assert.equal(resguardos.length, antesCambio + 1, 'Cambiar el título invalida el plan mostrado.');
  console.log('Edición UI OK: pendientes visibles, revisión explícita, destino y errores de copia.');
}
probar().catch(error => {console.error(error); process.exitCode = 1;});
