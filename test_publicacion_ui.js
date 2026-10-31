/* Prueba hermética del selector: ningún archivo oculto se incluye en un envío.
 * Ejecutar: node test_publicacion_ui.js. Sin navegador, red ni material real. */
'use strict';
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

class Elemento {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.events = {};
    this.value = '';
    this.textContent = '';
    this.disabled = false;
  }
  append(...items) { this.children.push(...items); }
  add(item) { this.append(item); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(evento, funcion) { this.events[evento] = funcion; }
  setAttribute(nombre, valor) { this[nombre] = valor; }
  async emitir(evento) { await (this.events[evento] || this['on' + evento])?.(); }
  set innerHTML(_) { throw Error('Los nombres de archivos deben usar textContent.'); }
}

async function probar(personajeAlternativo = 'mailen') {
  const html = fs.readFileSync('bandeja/web/panel.html', 'utf8');
  const elementos = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], new Elemento()]));
  const el = id => { assert(elementos.has(id), 'ID inexistente: ' + id); return elementos.get(id); };
  const documento = {getElementById: el, createElement: tag => new Elemento(tag)};
  const ventana = {};
  const almacen = new Map();
  el('wifi-personaje').value = 'todos';
  const datos = [
    ['lucie', 'Cafe.mp4', 'video', 'lucie/Cafe'],
    ['lucie', '<archivo especial>.mp4', 'video', 'lucie/Cafe'],
    ['roli', 'Roli.mp4', 'video', 'roli/Cancion'],
    [personajeAlternativo, 'Foto.png', 'imagen', personajeAlternativo + '/Plaza'],
    ['sin_asignar', '1010(5).mp4', 'video', 'Sin publicar (raíz)']
  ].map(([personaje, nombre, tipo, carpeta_relativa], indice) => ({id: 'archivo-' + indice,
    nombre, personaje, tipo, carpeta_relativa, tamano: 5000, mtime: 1,
    id_media: 'publicacion:archivo-' + indice, ruta: 'videos completos/videos sin publicar/' + nombre}));
  const receptor = {id: 'celular-temporal', alias: 'Celular temporal', ip: '192.168.1.20', port: 53318, receptor: 'lucie'};
  const oficial = {...receptor, id: 'localsend-temporal', alias: 'Mi teléfono', port: 53317, receptor: 'localsend'};
  let conexionRespuesta = receptor;
  let retenerPlan = false;
  let liberarPlan;
  let ultimoTokenPlan;
  let cantidadPlanes = 0;
  let esperados = [];
  let enviados = [];
  let archivados = new Set();
  let deshechos = 0;
  let organizados = 0;
  let retenerLista = false;
  const listasPendientes = [];
  let respuestaEstado = null;
  const sondeos = [];
  const llamadas = [];
  const evento = {id_operacion: 'operacion-temporal', ruta_destino: 'videos completos/videosPublicados/' + personajeAlternativo + '/Foto.png',
    dispositivo: receptor.alias, fecha: '2026-10-12'};
  async function apiFetch(url, opciones) {
    const cuerpo = opciones ? JSON.parse(opciones.body) : null;
    llamadas.push({url, cuerpo});
    if (url.endsWith('/lista')) {
      const respuesta = {conectado: true, carpeta: 'Pendrive temporal',
      archivos: datos.filter(a => !archivados.has(a.id)), historial: archivados.size ? [evento] : [],
      organizacion_pendiente: [{id: 'carpeta-antigua', ruta: 'videos completos/roli', tipo: 'carpeta_pendiente', personaje: 'roli'}]};
      if (retenerLista) return new Promise(resolve => listasPendientes.push(() => resolve(respuesta)));
      return respuesta;
    }
    if (url.endsWith('/buscar')) {
      assert.strictEqual(cuerpo.receptor, el('wifi-app').value || 'lucie');
      return {dispositivos: [receptor, oficial]};
    }
    if (url.endsWith('/conectar')) return {dispositivo: conexionRespuesta};
    if (url.endsWith('/simular')) {
      assert.deepStrictEqual(cuerpo.seleccion, esperados, 'Se incluyeron archivos ajenos al filtro.');
      assert.strictEqual(cuerpo.dispositivo_id, receptor.id);
      assert.strictEqual(cuerpo.receptor, 'lucie');
      assert.deepStrictEqual(cuerpo.personajes, esperados.includes('archivo-4') ? {'archivo-4': 'roli'} : {});
      ultimoTokenPlan = 'plan-temporal-' + (++cantidadPlanes);
      const respuesta = {token: ultimoTokenPlan, dispositivo: receptor, total_bytes: 5000,
        archivos: datos.filter(a => esperados.includes(a.id)).map(a => ({...a, destino_rel: 'videos completos/videosPublicados/' + a.personaje + '/' + a.nombre})),
        aviso: 'La recepción es señal de publicación.'};
      if (retenerPlan) return new Promise(resolve => { liberarPlan = () => resolve(respuesta); });
      return respuesta;
    }
    if (url.endsWith('/enviar')) {
      assert.strictEqual(cuerpo.token, ultimoTokenPlan);
      assert.strictEqual(cuerpo.confirmacion, true);
      enviados = [...esperados];
      return {id: 'envio-temporal'};
    }
    if (url.includes('/estado?id=')) {
      if (respuestaEstado) return respuestaEstado();
      archivados = new Set(enviados);
      return {estado: 'completado', mensaje: 'Recibido', bytes_enviados: 5000, total_bytes: 5000,
        recibidos: ['Foto.png'], publicados: [evento], dispositivo: receptor};
    }
    if (url.endsWith('/deshacer')) {
      assert.strictEqual(cuerpo.id_operacion, evento.id_operacion);
      archivados.clear();
      deshechos++;
      return {exito: true};
    }
    if (url.endsWith('/organizar-simular')) {
      assert.deepStrictEqual(cuerpo.seleccion, [{id: 'carpeta-antigua', personaje: 'roli'}]);
      return {token: 'organizacion-temporal', acciones: [{ruta: 'videos completos/roli', destino: 'videos completos/videos sin publicar/roli', archivos: 2, bytes: 1234}]};
    }
    if (url.endsWith('/organizar')) {
      assert.strictEqual(cuerpo.token, 'organizacion-temporal');
      assert.strictEqual(cuerpo.confirmacion, true); organizados++;
      return {exito: true};
    }
    throw Error('API inesperada: ' + url);
  }
  vm.runInNewContext(fs.readFileSync('bandeja/web/wifi.js', 'utf8'), {
    document: documento, window: ventana, apiFetch,
    Option: function(texto, valor) { const opcion = new Elemento('option'); opcion.textContent = texto; opcion.value = valor; return opcion; },
    confirm: () => true,
    sessionStorage: {getItem: k => almacen.get(k), setItem: (k, v) => almacen.set(k, v), removeItem: k => almacen.delete(k)},
    setTimeout: funcion => { sondeos.push(funcion); return sondeos.length; }
  });
  function tarjetas() {
    return el('wifi-videos').children.flatMap(grupo => grupo.children.filter(c => c.className === 'wifi-archivos-grid')
      .flatMap(rejilla => rejilla.children));
  }
  const tilde = tarjeta => tarjeta.children[0].children[0];
  const preview = tarjeta => tarjeta.children[1].children[0];
  await ventana.cargarPublicacionWifi();
  assert.strictEqual(el('wifi-videos').children.length, 4, 'Deben mostrarse grupos separados.');
  assert.strictEqual(tarjetas().length, 5);
  assert.strictEqual(tarjetas()[1].children[0].children[1].textContent, '<archivo especial>.mp4');
  assert(preview(tarjetas()[0]).src.startsWith('/api/media?id=publicacion%3A'));
  assert(preview(tarjetas()[0]).src.endsWith('#t=0.1'));
  await el('wifi-todos').emitir('click');
  assert(tarjetas().every(t => tilde(t).checked));
  el('wifi-personaje').value = 'roli';
  await el('wifi-personaje').emitir('change');
  assert.strictEqual(tarjetas().length, 1);
  assert.strictEqual(tilde(tarjetas()[0]).checked, false);
  await el('wifi-todos').emitir('click');
  await el('wifi-buscar').emitir('click');
  assert.strictEqual(el('wifi-dispositivo').value, '', 'Buscar no elige un receptor automáticamente.');
  assert.strictEqual(el('wifi-dispositivo').children.length, 2, 'Lucie no mezcla la app LocalSend de la misma IP.');
  assert(el('wifi-dispositivo').children[1].textContent.includes(':53318'));
  el('wifi-dispositivo').value = receptor.id;
  await el('wifi-dispositivo').emitir('change');
  assert.strictEqual(el('wifi-conexion').open, false, 'Elegir celular deja visible el destino y pliega los controles.');
  assert.strictEqual(el('wifi-conexion-resumen').textContent, 'Cambiar celular o app');
  esperados = ['archivo-2'];
  await el('wifi-preparar').emitir('click');
  const confirmacionAnterior = el('wifi-plan').children[3];
  el('wifi-personaje').value = personajeAlternativo;
  await el('wifi-personaje').emitir('change');
  assert.strictEqual(el('wifi-plan').style.display, 'none');
  await confirmacionAnterior.emitir('click');
  assert.strictEqual(enviados.length, 0, 'No debe usarse el plan anterior después de cambiar el filtro.');
  assert.strictEqual(preview(tarjetas()[0]).tag, 'img');
  assert.strictEqual(preview(tarjetas()[0]).alt, 'Vista previa de Foto.png');
  await preview(tarjetas()[0]).emitir('error');
  assert.strictEqual(tarjetas()[0].children[1].children[1].hidden, false);
  el('wifi-filtro').value = 'no coincide';
  await el('wifi-filtro').emitir('input');
  assert.strictEqual(tarjetas().length, 0);
  el('wifi-filtro').value = 'plaza';
  await el('wifi-filtro').emitir('input');
  assert.strictEqual(tarjetas().length, 1, 'La búsqueda debe encontrar carpetas.');
  await el('wifi-todos').emitir('click');
  esperados = ['archivo-3'];
  await el('wifi-preparar').emitir('click');
  await confirmacionAnterior.emitir('click');
  assert.strictEqual(enviados.length, 0, 'Un botón viejo no puede enviar la revisión nueva.');
  await el('wifi-plan').children[3].emitir('click');
  assert.deepStrictEqual(enviados, ['archivo-3']);
  assert.strictEqual(almacen.size, 0);
  assert.strictEqual(sondeos.length, 0, 'Un envío completado no sigue sondeando.');
  assert.strictEqual(tarjetas().length, 0, 'El archivo recibido y archivado desaparece del panel pendiente.');
  assert.strictEqual(el('wifi-cancelar').style.display, 'none');
  assert.strictEqual(el('wifi-historial').children[0].children[0].children[0].textContent, 'Foto.png');
  assert.strictEqual(el('wifi-historial').children[0].children[0].children[2].children[1].textContent, evento.ruta_destino);
  el('wifi-historial-filtro').value = 'no existe'; await el('wifi-historial-filtro').emitir('input');
  assert.strictEqual(el('wifi-historial').children.length, 0);
  el('wifi-historial-filtro').value = 'Foto'; await el('wifi-historial-filtro').emitir('input');
  assert.strictEqual(el('wifi-historial').children.length, 1);
  await el('wifi-historial').children[0].children[1].emitir('click');
  assert.strictEqual(deshechos, 1);
  assert.strictEqual(tarjetas().length, 1);
  el('wifi-personaje').value = 'sin_asignar'; el('wifi-filtro').value = '';
  await el('wifi-personaje').emitir('change');
  await el('wifi-todos').emitir('click'); esperados = ['archivo-4'];
  assert.strictEqual(el('wifi-preparar').disabled, true);
  assert(el('wifi-siguiente').textContent.includes('1010(5).mp4'), 'Se indica qué archivo necesita personaje antes de revisar.');
  assert.strictEqual(el('wifi-seleccion-detalle').children[0].children[0].textContent, '1010(5).mp4');
  const antes = llamadas.filter(l => l.url.endsWith('/simular')).length;
  await el('wifi-preparar').emitir('click');
  assert.strictEqual(llamadas.filter(l => l.url.endsWith('/simular')).length, antes, 'Sin personaje no se prepara ni envía.');
  const asignacion = tarjetas()[0].children.find(c => c.tag === 'label' && c.children.some(e => e.tag === 'select')).children[0];
  const asignacionLateral = el('wifi-seleccion-detalle').children[0].children.find(c => c.tag === 'label').children[0];
  asignacionLateral.value = 'roli'; await asignacionLateral.emitir('change');
  assert.strictEqual(el('wifi-preparar').disabled, false, 'Elegir personaje junto al nombre habilita la revisión.');
  assert.strictEqual(tarjetas()[0].children.find(c => c.tag === 'label' && c.children.some(e => e.tag === 'select')).children[0].value, 'roli', 'La tarjeta refleja la elección del panel lateral.');
  await el('wifi-preparar').emitir('click');
  assert.strictEqual(llamadas.at(-1).cuerpo.personajes['archivo-4'], 'roli');
  const vieja = el('wifi-plan').children[3];
  asignacion.value = 'lucie'; await asignacion.emitir('change');
  await vieja.emitir('click');
  assert.deepStrictEqual(enviados, ['archivo-3'], 'Cambiar personaje invalida la confirmación anterior.');
  const marcar = el('wifi-organizacion-lista').children[0].children[0].children[0];
  assert(!marcar.checked, 'La organización no preselecciona carpetas.');
  marcar.checked = true; await marcar.emitir('change');
  await el('wifi-organizacion-revisar').emitir('click');
  assert.strictEqual(organizados, 0, 'La simulación no mueve material.');
  await el('wifi-organizacion-plan').children[1].emitir('click');
  assert.strictEqual(organizados, 1);
  await el('wifi-tab-historial').emitir('click');
  assert.strictEqual(el('wifi-vista-historial').style.display, 'block');
  assert.strictEqual(el('wifi-vista-envio').style.display, 'none');
  await el('wifi-tab-envio').emitir('click');
  assert.strictEqual(el('wifi-vista-envio').style.display, 'grid');
  el('wifi-app').value = 'localsend'; await el('wifi-app').emitir('change');
  assert.strictEqual(el('wifi-conexion').open, true, 'Cambiar la app permite buscar un nuevo receptor.');
  assert.strictEqual(el('wifi-dispositivo').value, '');
  assert.strictEqual(el('wifi-puerto').value, '53317');
  await el('wifi-buscar').emitir('click');
  assert.strictEqual(el('wifi-dispositivo').children.length, 2);
  assert(el('wifi-dispositivo').children[1].textContent.includes(':53317'));
  el('wifi-app').value = 'lucie'; await el('wifi-app').emitir('change');
  assert.strictEqual(el('wifi-puerto').value, '53318');
  conexionRespuesta = oficial; await el('wifi-conectar').emitir('click');
  assert.strictEqual(el('wifi-dispositivo').value, '', 'Conectar a otra app no selecciona ni sustituye el destino.');
  assert(el('wifi-busqueda-estado').textContent.includes('LocalSend'));
  conexionRespuesta = receptor; await el('wifi-conectar').emitir('click');
  assert.strictEqual(el('wifi-dispositivo').value, receptor.id);
  assert(el('wifi-destino').textContent.includes('Lucie Recibir'));
  el('wifi-personaje').value = personajeAlternativo; await el('wifi-personaje').emitir('change');
  await el('wifi-todos').emitir('click'); esperados = ['archivo-3'];
  retenerPlan = true;
  const pendiente = el('wifi-preparar').emitir('click');
  el('wifi-app').value = 'localsend'; await el('wifi-app').emitir('change');
  liberarPlan(); await pendiente;
  assert.strictEqual(el('wifi-plan').style.display, 'none', 'Una revisión tardía no reaparece después de cambiar la app.');
  assert.deepStrictEqual(enviados, ['archivo-3'], 'Buscar, conectar o cambiar de app nunca inicia un envío.');

  // La selección sobrevive a una actualización sin cambios; una versión nueva
  // del archivo o una respuesta vieja nunca habilita una confirmación anterior.
  retenerPlan = false;
  el('wifi-app').value = 'lucie'; await el('wifi-app').emitir('change');
  await el('wifi-conectar').emitir('click');
  await el('wifi-preparar').emitir('click');
  const confirmarArchivoViejo = el('wifi-plan').children[3];
  await ventana.cargarPublicacionWifi();
  assert.strictEqual(el('wifi-plan').style.display, 'block', 'La misma versión conserva su revisión.');
  datos[3] = {...datos[3], mtime: 2};
  await ventana.cargarPublicacionWifi();
  assert.strictEqual(el('wifi-plan').style.display, 'none', 'Cambiar el archivo en la misma ruta invalida la revisión.');
  const enviosAntes = llamadas.filter(l => l.url.endsWith('/enviar')).length;
  await confirmarArchivoViejo.emitir('click');
  assert.strictEqual(llamadas.filter(l => l.url.endsWith('/enviar')).length, enviosAntes);
  retenerLista = true;
  const listaVieja = ventana.cargarPublicacionWifi();
  archivados.add('archivo-3');
  const listaNueva = ventana.cargarPublicacionWifi();
  listasPendientes[1](); await listaNueva;
  listasPendientes[0](); await listaVieja;
  assert.strictEqual(tarjetas().length, 0, 'Una lista tardía no vuelve a mostrar el archivo archivado.');
  assert.strictEqual(el('wifi-preparar').disabled, true);
  retenerLista = false; archivados.clear(); await ventana.cargarPublicacionWifi();

  // Cada recepción archivada sale de la selección aunque otro archivo del
  // mismo envío siga pendiente o termine fallando; no se vuelve a enviar.
  el('wifi-personaje').value = 'lucie'; await el('wifi-personaje').emitir('change');
  await el('wifi-todos').emitir('click'); esperados = ['archivo-0', 'archivo-1'];
  const parcial = {...evento, ruta_origen: datos[0].ruta};
  respuestaEstado = () => {
    archivados.add('archivo-0');
    return {estado: 'en_curso', mensaje: 'Enviando segundo archivo', bytes_enviados: 5000, total_bytes: 10000,
      recibidos: [datos[0].nombre], publicados: [parcial], dispositivo: receptor};
  };
  await el('wifi-preparar').emitir('click');
  await el('wifi-plan').children[3].emitir('click');
  assert.strictEqual(tarjetas().length, 1, 'El primero desaparece sin esperar al final del envío.');
  assert.strictEqual(tarjetas()[0].children[0].children[1].textContent, datos[1].nombre);
  assert(el('wifi-resumen-seleccion').textContent.startsWith('1 archivo'));
  respuestaEstado = () => ({estado: 'error', mensaje: 'Envío parcial', error: 'Rechazado segundo archivo',
    bytes_enviados: 5000, total_bytes: 10000, recibidos: [datos[0].nombre], publicados: [parcial], dispositivo: receptor});
  await sondeos.shift()();
  assert.strictEqual(tarjetas().length, 1, 'Un fallo posterior conserva solo el video no recibido en pendientes.');
  assert.strictEqual(almacen.size, 0);
  assert.strictEqual(el('wifi-preparar').disabled, false, 'El pendiente se puede revisar para un nuevo envío explícito.');
  await el('wifi-seleccion-detalle').children[0].children[1].emitir('click');
  assert.strictEqual(tilde(tarjetas()[0]).checked, false, 'Quitar del resumen desmarca la tarjeta.');
  assert.strictEqual(el('wifi-preparar').disabled, true);
  const recarga = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], new Elemento()]));
  recarga.get('wifi-app').value = 'lucie';
  vm.runInNewContext(fs.readFileSync('bandeja/web/wifi.js', 'utf8'), {
    document: {getElementById: id => recarga.get(id), createElement: tag => new Elemento(tag)}, window: {},
    apiFetch: async () => ({estado: 'en_curso', mensaje: 'Enviando', total_bytes: 10, bytes_enviados: 1,
      recibidos: [], publicados: [], dispositivo: oficial}),
    Option: function(t, v) { const o = new Elemento('option'); o.textContent = t; o.value = v; return o; },
    sessionStorage: {getItem: () => 'envio-pendiente'}, setTimeout: () => 0
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(recarga.get('wifi-app').value, 'localsend', 'Recargar muestra la app real del envío en curso.');
  assert.strictEqual(recarga.get('wifi-dispositivo').value, oficial.id);
  assert(recarga.get('wifi-destino').textContent.includes('LocalSend'));
  assert.strictEqual(recarga.get('wifi-app').disabled, true);
  console.log('UI OK: grupos, imágenes/video, rutas, filtros, selección visible, invalidación, envío e historial. ' + llamadas.length + ' llamadas simuladas.');
}

probar().then(() => probar('luna')).catch(error => { console.error(error); process.exitCode = 1; });
