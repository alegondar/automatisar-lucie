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
  async emitir(evento) { await this.events[evento]?.(); }
  set innerHTML(_) { throw Error('Los nombres de archivos deben usar textContent.'); }
}

async function probar() {
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
    ['mailen', 'Foto.png', 'imagen', 'mailen/Plaza'],
    ['sin_asignar', '1010(6).mp4', 'video', 'Sin publicar (raíz)']
  ].map(([personaje, nombre, tipo, carpeta_relativa], indice) => ({id: 'archivo-' + indice,
    nombre, personaje, tipo, carpeta_relativa, tamano: 5000, mtime: 1,
    id_media: 'publicacion:archivo-' + indice, ruta: 'videos completos/videos sin publicar/' + nombre}));
  const receptor = {id: 'celular-temporal', alias: 'Celular temporal', ip: '192.168.1.20'};
  let esperados = [];
  let enviados = [];
  let archivados = new Set();
  let deshechos = 0;
  const llamadas = [];
  const evento = {id_operacion: 'operacion-temporal', ruta_destino: 'videos completos/Foto.png',
    dispositivo: receptor.alias, fecha: '2026-10-12'};
  async function apiFetch(url, opciones) {
    const cuerpo = opciones ? JSON.parse(opciones.body) : null;
    llamadas.push({url, cuerpo});
    if (url.endsWith('/lista')) return {conectado: true, carpeta: 'Pendrive temporal',
      archivos: datos.filter(a => !archivados.has(a.id)), historial: archivados.size ? [evento] : []};
    if (url.endsWith('/buscar')) return {dispositivos: [receptor]};
    if (url.endsWith('/simular')) {
      assert.deepStrictEqual(cuerpo.seleccion, esperados, 'Se incluyeron archivos ajenos al filtro.');
      assert.strictEqual(cuerpo.dispositivo_id, receptor.id);
      return {token: 'plan-temporal', dispositivo: receptor, total_bytes: 5000,
        archivos: datos.filter(a => esperados.includes(a.id)).map(a => ({...a, destino_rel: 'videos completos/' + a.nombre})),
        aviso: 'La recepción es señal de publicación.'};
    }
    if (url.endsWith('/enviar')) {
      assert.strictEqual(cuerpo.token, 'plan-temporal');
      assert.strictEqual(cuerpo.confirmacion, true);
      enviados = [...esperados];
      return {id: 'envio-temporal'};
    }
    if (url.includes('/estado?id=')) {
      archivados = new Set(enviados);
      return {estado: 'completado', mensaje: 'Recibido', bytes_enviados: 5000, total_bytes: 5000,
        recibidos: ['Foto.png'], publicados: [evento]};
    }
    if (url.endsWith('/deshacer')) {
      assert.strictEqual(cuerpo.id_operacion, evento.id_operacion);
      archivados.clear();
      deshechos++;
      return {exito: true};
    }
    throw Error('API inesperada: ' + url);
  }
  vm.runInNewContext(fs.readFileSync('bandeja/web/wifi.js', 'utf8'), {
    document: documento, window: ventana, apiFetch,
    Option: function(texto, valor) { const opcion = new Elemento('option'); opcion.textContent = texto; opcion.value = valor; return opcion; },
    confirm: () => true,
    sessionStorage: {getItem: k => almacen.get(k), setItem: (k, v) => almacen.set(k, v), removeItem: k => almacen.delete(k)},
    setTimeout: () => { throw Error('No se espera más sondeo tras un envío completado.'); }
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
  el('wifi-dispositivo').value = receptor.id;
  esperados = ['archivo-2'];
  await el('wifi-preparar').emitir('click');
  const confirmacionAnterior = el('wifi-plan').children[3];
  el('wifi-personaje').value = 'mailen';
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
  await el('wifi-plan').children[3].emitir('click');
  assert.deepStrictEqual(enviados, ['archivo-3']);
  assert.strictEqual(almacen.size, 0);
  assert.strictEqual(el('wifi-cancelar').style.display, 'none');
  await el('wifi-historial').children[0].children[1].emitir('click');
  assert.strictEqual(deshechos, 1);
  assert.strictEqual(tarjetas().length, 1);
  console.log('UI OK: grupos, imágenes/video, rutas, filtros, selección visible, invalidación, envío e historial. ' + llamadas.length + ' llamadas simuladas.');
}

probar().catch(error => { console.error(error); process.exitCode = 1; });
