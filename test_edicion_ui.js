const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fuente = fs.readFileSync('bandeja/web/panel.js', 'utf8');
function extraer(nombre, siguiente) {
  const inicio = fuente.indexOf(`    ${nombre.startsWith('terminar') ? 'async ' : ''}function ${nombre}(`);
  const fin = fuente.indexOf(`    ${siguiente.startsWith('deshacer') ? 'async ' : ''}function ${siguiente}(`, inicio);
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
  const ctx = vm.createContext({
    document: {getElementById: () => cont, createElement: elemento},
    confirm: () => true, alert: mensaje => { throw Error(mensaje); },
    escapeHTML: s => String(s).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    mostrarAvisoEdicion: mensaje => avisos.push(mensaje), cargarVistaEdicion: async () => {},
    apiFetch: async (ruta, datos) => { llamadas.push({ruta, datos}); return {export_final: {modo, mensaje: 'Esperando export'}}; },
    fetchConCsrf: async (ruta, datos) => {
      llamadas.push({ruta, datos}); return {json: async () => ({exito: true, movidos: [{}],
        export_final: {modo, mensaje: modo === 'copiado' ? 'Video final copiado' : 'Falta copiar: sin espacio',
          destino: modo === 'copiado' ? 'videos completos/videos sin publicar/lucie/Cafe.mp4' : undefined}})};
    }
  });
  vm.runInContext(extraer('renderizarSesionesEsperandoExport', 'renderizarSesionesEnEdicion'), ctx);
  vm.runInContext(extraer('terminarEdicionSesion', 'deshacerTerminarEdicion'), ctx);
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
  ctx.renderizarSesionesEsperandoExport([], []);
  assert.equal(cont.children.length, 0);
  console.log('Edición UI OK: pendientes visibles, revisión explícita, destino y errores de copia.');
}
probar().catch(error => {console.error(error); process.exitCode = 1;});
