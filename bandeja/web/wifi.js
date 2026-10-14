/* Cola de publicación y emisor LocalSend integrado al dashboard local. */
(() => {
  'use strict';
  if (typeof document === 'undefined' || !document.getElementById('sec-publicacion')) return;
  let archivos = [];
  const personajesElegidos = new Map();
  let organizacionPlan = null;
  let seleccion = new Set();
  let plan = null;
  let trabajo = null;
  try { trabajo = sessionStorage.getItem('lucie-envio-wifi') || null; } catch (_) { /* Sin almacenamiento disponible. */ }
  let timer = null;
  let observadorPreviews = null;
  const etiquetasPersonaje = {lucie: 'Lucie', roli: 'Roli', mailen: 'Mailen', sin_asignar: 'Sin asignar'};
  const dispositivos = new Map();
  const el = id => document.getElementById(id);
  const texto = (id, mensaje) => { el(id).textContent = mensaje; };
  const bytes = n => n < 1024 ? n + ' B' : n < 1024 * 1024 ? (n / 1024).toFixed(1) + ' KB' : (n / (1024 * 1024)).toFixed(1) + ' MB';
  const peticion = (accion, datos) => apiFetch('/api/publicacion/' + accion, {
    method: 'POST', body: JSON.stringify(datos || {})
  });
  const estado = mensaje => texto('wifi-estado', mensaje);

  function invalidarPlan() {
    plan = null;
    el('wifi-plan').replaceChildren();
    el('wifi-plan').style.display = 'none';
  }

  function archivosVisibles() {
    const personaje = el('wifi-personaje').value || 'todos';
    const busqueda = el('wifi-filtro').value.trim().toLocaleLowerCase();
    return archivos.filter(a => (personaje === 'todos' || a.personaje === personaje) &&
      (!busqueda || (a.nombre + ' ' + a.carpeta_relativa).toLocaleLowerCase().includes(busqueda)));
  }

  function dibujarConteo() {
    const cantidad = archivosVisibles().length;
    texto('wifi-conteo', cantidad + (cantidad === 1 ? ' archivo visible de ' : ' archivos visibles de ') + archivos.length +
      ' · ' + seleccion.size + (seleccion.size === 1 ? ' seleccionado para enviar' : ' seleccionados para enviar'));
  }

  function dibujarArchivos() {
    const lista = el('wifi-videos');
    if (observadorPreviews) observadorPreviews.disconnect();
    observadorPreviews = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entradas => {
      for (const entrada of entradas) {
        if (entrada.isIntersecting) {
          entrada.target.src = entrada.target.dataset.src;
          observadorPreviews.unobserve(entrada.target);
        }
      }
    }, {rootMargin: '200px'}) : null;
    lista.replaceChildren();
    el('wifi-personaje').disabled = Boolean(trabajo);
    el('wifi-filtro').disabled = Boolean(trabajo);
    dibujarConteo();
    if (!archivos.length) {
      lista.textContent = 'No hay videos ni fotos pendientes en Sin publicar. Los nuevos exports aparecerán aquí después de copiarse al pendrive.';
      return;
    }
    const visibles = archivosVisibles();
    if (!visibles.length) {
      lista.textContent = 'No hay archivos de este personaje que coincidan con la búsqueda. Podés elegir otro personaje o revisar Sin asignar.';
      return;
    }
    for (const [personaje, etiqueta] of Object.entries(etiquetasPersonaje)) {
      const grupo = visibles.filter(a => a.personaje === personaje);
      if (!grupo.length) continue;
      const seccion = document.createElement('section');
      seccion.className = 'wifi-grupo';
      const titulo = document.createElement('h3');
      titulo.textContent = etiqueta + ' · ' + grupo.length + (grupo.length === 1 ? ' archivo' : ' archivos');
      seccion.append(titulo);
      if (personaje === 'sin_asignar') {
        const ayuda = document.createElement('p');
        ayuda.className = 'wifi-ayuda';
        ayuda.textContent = 'No se conoce el personaje de estos archivos. Elegí su personaje en cada tarjeta antes de enviarlos.';
        seccion.append(ayuda);
      }
      const rejilla = document.createElement('div');
      rejilla.className = 'wifi-archivos-grid';
      rejilla.setAttribute('role', 'list');
      seccion.append(rejilla);
      lista.append(seccion);
      for (const archivo of grupo) {
        const fila = document.createElement('article');
        fila.className = 'wifi-archivo';
        fila.setAttribute('role', 'listitem');
        const cabecera = document.createElement('label');
        cabecera.className = 'wifi-archivo-titulo';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = seleccion.has(archivo.id);
        checkbox.disabled = Boolean(trabajo);
        checkbox.addEventListener('change', () => {
          checkbox.checked ? seleccion.add(archivo.id) : seleccion.delete(archivo.id);
          invalidarPlan();
          dibujarConteo();
        });
        const nombre = document.createElement('strong');
        nombre.textContent = archivo.nombre;
        cabecera.append(checkbox, nombre);
        const marco = document.createElement('div');
        marco.className = 'wifi-preview';
        const preview = document.createElement(archivo.tipo === 'imagen' ? 'img' : 'video');
        const url = '/api/media?id=' + encodeURIComponent(archivo.id_media) + '&v=' + encodeURIComponent(archivo.mtime + '-' + archivo.tamano);
        if (archivo.tipo === 'imagen') {
          preview.alt = 'Vista previa de ' + archivo.nombre;
          preview.loading = 'lazy';
        } else {
          preview.controls = true;
          preview.muted = true;
          preview.playsInline = true;
          preview.preload = 'metadata';
          preview.setAttribute('aria-label', 'Vista previa de ' + archivo.nombre);
        }
        const fallback = document.createElement('p');
        fallback.className = 'wifi-preview-error';
        fallback.textContent = 'No se pudo mostrar la vista previa. Podés abrir el archivo con el enlace de abajo.';
        fallback.hidden = true;
        preview.addEventListener('error', () => { fallback.hidden = false; });
        marco.append(preview, fallback);
        const detalle = document.createElement('p');
        detalle.className = 'wifi-archivo-detalle';
        detalle.textContent = etiqueta + ' · ' + (archivo.tipo === 'imagen' ? 'Foto' : 'Video') + ' · ' + bytes(archivo.tamano);
        if (archivo.personaje_origen === 'nombre') detalle.textContent += ' · personaje indicado por el nombre';
        const carpeta = document.createElement('p');
        carpeta.className = 'wifi-archivo-carpeta';
        carpeta.textContent = 'Carpeta: ' + archivo.carpeta_relativa;
        carpeta.title = archivo.ruta;
        const abrir = document.createElement('a');
        abrir.href = url;
        abrir.target = '_blank';
        abrir.rel = 'noopener';
        abrir.textContent = 'Abrir vista previa';
        fila.append(cabecera, marco, detalle, carpeta, abrir);
        if (archivo.personaje === 'sin_asignar') {
          const asignacion = document.createElement('label');
          asignacion.textContent = 'Personaje para publicar ';
          const selector = document.createElement('select');
          selector.setAttribute('aria-label', 'Personaje de ' + archivo.nombre);
          selector.add(new Option('Elegí el personaje', ''));
          for (const p of ['lucie', 'roli', 'mailen']) selector.add(new Option(etiquetasPersonaje[p], p));
          selector.value = personajesElegidos.get(archivo.id) || '';
          selector.disabled = Boolean(trabajo);
          selector.addEventListener('change', () => {
            personajesElegidos.set(archivo.id, selector.value);
            invalidarPlan();
          });
          asignacion.append(selector);
          fila.append(asignacion);
        }
        rejilla.append(fila);
        preview.dataset.src = url + (archivo.tipo === 'imagen' ? '' : '#t=0.1');
        if (observadorPreviews) observadorPreviews.observe(preview);
        else preview.src = preview.dataset.src;
      }
    }
  }

  function cambiarFiltro() {
    if (trabajo) return;
    // El nuevo grupo empieza sin selección; no se envían archivos ocultos
    // que el usuario hubiera tildado antes de cambiar de personaje.
    seleccion.clear();
    invalidarPlan();
    dibujarArchivos();
  }

  function dibujarDispositivos() {
    const selector = el('wifi-dispositivo');
    const anterior = selector.value;
    selector.replaceChildren(new Option('Elegí el celular', ''));
    for (const dispositivo of dispositivos.values()) {
      selector.add(new Option(dispositivo.alias + ' · ' + dispositivo.ip, dispositivo.id));
    }
    if (dispositivos.has(anterior)) selector.value = anterior;
  }

  async function cargar() {
    try {
      const datos = await apiFetch('/api/publicacion/lista');
      archivos = datos.archivos || [];
      for (const id of personajesElegidos.keys()) if (!archivos.some(a => a.id === id)) personajesElegidos.delete(id);
      dibujarOrganizacion(datos);
      const disponibles = new Set(archivosVisibles().map(a => a.id));
      seleccion = new Set([...seleccion].filter(id => disponibles.has(id)));
      texto('wifi-carpeta', datos.conectado ? datos.carpeta : datos.mensaje);
      dibujarArchivos();
      const historial = el('wifi-historial');
      historial.replaceChildren();
      if (!(datos.historial || []).length) historial.textContent = 'Todavía no hubo envíos confirmados desde esta sección.';
      for (const envio of datos.historial || []) {
        const fila = document.createElement('div');
        fila.style.cssText = 'padding:12px;border-bottom:1px solid var(--border);';
        const etiqueta = document.createElement('span');
        etiqueta.textContent = envio.ruta_destino + ' · recibido en ' + envio.dispositivo + ' · ' + envio.fecha + ' ';
        const boton = document.createElement('button');
        boton.className = 'btn-sm btn-secundario';
        boton.textContent = 'Volver a Sin publicar';
        boton.disabled = Boolean(trabajo);
        boton.addEventListener('click', async () => {
          if (!confirm('¿Volver a colocar este video en Videos sin publicar? Se conservará el archivo y no se quitará la copia del celular.')) return;
          boton.disabled = true;
          try {
            await peticion('deshacer', {id_operacion: envio.id_operacion});
            estado('El video volvió a Videos sin publicar. La copia recibida en el celular se conserva.');
            await cargar();
          } catch (error) { estado(error.message); boton.disabled = false; }
        });
        fila.append(etiqueta, boton);
        historial.append(fila);
      }
    } catch (error) { estado(error.message); }
  }

  function dibujarOrganizacion(datos) {
    const lista = el('wifi-organizacion-lista');
    const candidatos = datos.organizacion_pendiente || [];
    const historial = datos.organizaciones || [];
    el('wifi-organizacion').style.display = candidatos.length || historial.length ? 'block' : 'none';
    lista.replaceChildren();
    el('wifi-organizacion-plan').replaceChildren();
    organizacionPlan = null;
    const opciones = [];
    for (const candidato of candidatos) {
      const fila = document.createElement('div');
      const etiqueta = document.createElement('label');
      const tilde = document.createElement('input'); tilde.type = 'checkbox'; tilde.disabled = Boolean(trabajo);
      const nombre = document.createElement('span');
      nombre.textContent = candidato.ruta + (candidato.tipo === 'publicado' ? ' · publicado confirmado' : ' · carpeta pendiente');
      etiqueta.append(tilde, nombre); fila.append(etiqueta);
      let personaje = null;
      if (!candidato.personaje) {
        personaje = document.createElement('select');
        personaje.setAttribute('aria-label', 'Personaje de ' + candidato.ruta);
        personaje.add(new Option('Elegí el personaje', ''));
        for (const p of ['lucie', 'roli', 'mailen']) personaje.add(new Option(etiquetasPersonaje[p], p));
        fila.append(personaje);
      }
      const invalidar = () => { organizacionPlan = null; el('wifi-organizacion-plan').replaceChildren(); };
      tilde.addEventListener('change', invalidar);
      if (personaje) personaje.addEventListener('change', invalidar);
      lista.append(fila); opciones.push({candidato, tilde, personaje});
    }
    el('wifi-organizacion-revisar').disabled = Boolean(trabajo) || !candidatos.length;
    el('wifi-organizacion-revisar').onclick = async () => {
      const elegidos = opciones.filter(o => o.tilde.checked).map(o => ({id: o.candidato.id, personaje: o.personaje ? o.personaje.value : o.candidato.personaje}));
      if (!elegidos.length) { estado('Marcá las carpetas o publicados que quieras organizar.'); return; }
      try {
        organizacionPlan = await peticion('organizar-simular', {seleccion: elegidos});
        const detalle = document.createElement('ul');
        for (const a of organizacionPlan.acciones) {
          const item = document.createElement('li');
          item.textContent = a.ruta + ' → ' + a.destino + ' · ' + a.archivos + ' archivos · ' + bytes(a.bytes);
          detalle.append(item);
        }
        const confirmar = document.createElement('button');
        confirmar.className = 'btn-sm'; confirmar.textContent = 'Confirmar organización';
        confirmar.addEventListener('click', async () => {
          if (!organizacionPlan || trabajo) return;
          const token = organizacionPlan.token; organizacionPlan = null; confirmar.disabled = true;
          try {
            const resultado = await peticion('organizar', {token, confirmacion: true});
            estado(resultado.exito ? 'Organización completada. Podés deshacer cada traslado.' : 'Organización parcial: ' + resultado.error);
            await cargar();
          } catch (error) { estado(error.message); }
        });
        el('wifi-organizacion-plan').replaceChildren(detalle, confirmar);
        estado('Revisá la organización. Todavía no se movió ningún archivo.');
      } catch (error) { estado(error.message); }
    };
    const movimientos = el('wifi-organizacion-historial'); movimientos.replaceChildren();
    for (const movimiento of historial) {
      const fila = document.createElement('div');
      const etiqueta = document.createElement('span'); etiqueta.textContent = movimiento.accion.ruta + ' → ' + movimiento.accion.destino + ' ';
      const deshacer = document.createElement('button'); deshacer.className = 'btn-sm btn-secundario';
      deshacer.textContent = 'Deshacer organización'; deshacer.disabled = Boolean(trabajo);
      deshacer.addEventListener('click', async () => {
        if (!confirm('¿Devolver este contenido a su ubicación anterior? No se borrará ni sobrescribirá material.')) return;
        try { await peticion('deshacer-organizacion', {id_organizacion: movimiento.id_organizacion}); await cargar(); }
        catch (error) { estado(error.message); }
      });
      fila.append(etiqueta, deshacer); movimientos.append(fila);
    }
  }

  async function buscar() {
    invalidarPlan();
    el('wifi-buscar').disabled = true;
    estado('Buscando Lucie Recibir o LocalSend en la red Wi-Fi. Mantené la app abierta en el celular…');
    try {
      const datos = await peticion('buscar');
      dispositivos.clear();
      for (const d of datos.dispositivos || []) dispositivos.set(d.id, d);
      dibujarDispositivos();
      estado(datos.dispositivos.length ? 'Elegí tu celular en la lista.' : 'No apareció ningún celular. Podés conectarlo por su IP local en «No aparece mi celular».');
    } catch (error) { estado(error.message); }
    finally { el('wifi-buscar').disabled = false; }
  }

  async function conectar() {
    el('wifi-conectar').disabled = true;
    estado('Comprobando el receptor…');
    try {
      const datos = await peticion('conectar', {ip: el('wifi-ip').value.trim(), puerto: Number(el('wifi-puerto').value)});
      dispositivos.set(datos.dispositivo.id, datos.dispositivo);
      dibujarDispositivos();
      el('wifi-dispositivo').value = datos.dispositivo.id;
      invalidarPlan();
      estado('Conectado a ' + datos.dispositivo.alias + '. Podés revisar el envío.');
    } catch (error) { estado(error.message); }
    finally { el('wifi-conectar').disabled = false; }
  }

  async function preparar() {
    if (trabajo) return;
    if (!seleccion.size || !el('wifi-dispositivo').value) {
      estado('Seleccioná al menos un video y elegí el celular receptor.');
      return;
    }
    el('wifi-preparar').disabled = true;
    estado('Calculando integridad y revisando los destinos…');
    invalidarPlan();
    try {
      const personajes = {};
      for (const id of seleccion) {
        const archivo = archivos.find(a => a.id === id);
        if (archivo && archivo.personaje === 'sin_asignar') {
          if (!personajesElegidos.get(id)) throw new Error('Elegí el personaje de ' + archivo.nombre + ' antes de enviar.');
          personajes[id] = personajesElegidos.get(id);
        }
      }
      plan = await peticion('simular', {seleccion: [...seleccion], dispositivo_id: el('wifi-dispositivo').value, personajes});
      const cont = el('wifi-plan');
      cont.style.display = 'block';
      const titulo = document.createElement('h3');
      titulo.textContent = 'Revisar envío a ' + plan.dispositivo.alias + ' (' + plan.dispositivo.ip + ') · ' + bytes(plan.total_bytes);
      const detalle = document.createElement('ul');
      for (const archivo of plan.archivos) {
        const item = document.createElement('li');
        item.textContent = archivo.nombre + ' · ' + bytes(archivo.tamano) + ' · después de recibir: ' + archivo.destino_rel;
        detalle.append(item);
      }
      const aviso = document.createElement('p');
      aviso.textContent = plan.aviso;
      if (plan.dispositivo.protocol === 'https' && plan.dispositivo.fingerprint) {
        aviso.textContent += ' · Huella HTTPS del receptor: ' + plan.dispositivo.fingerprint + '. Comparala con Lucie Recibir antes del primer envío.';
        aviso.style.overflowWrap = 'anywhere';
      }
      const confirmar = document.createElement('button');
      confirmar.className = 'btn-sm';
      confirmar.textContent = 'Confirmar y enviar al celular';
      confirmar.addEventListener('click', iniciar);
      const cancelar = document.createElement('button');
      cancelar.className = 'btn-sm btn-secundario';
      cancelar.textContent = 'Cancelar revisión';
      cancelar.addEventListener('click', invalidarPlan);
      cont.replaceChildren(titulo, detalle, aviso, confirmar, cancelar);
      estado('Revisá los archivos y destinos. Todavía no se envió ni movió ningún video.');
    } catch (error) { estado(error.message); }
    finally { el('wifi-preparar').disabled = false; }
  }

  async function iniciar() {
    if (!plan || trabajo) return;
    const token = plan.token;
    invalidarPlan();
    el('wifi-preparar').disabled = true;
    try {
      const datos = await peticion('enviar', {token, confirmacion: true, pin: el('wifi-pin').value});
      el('wifi-pin').value = '';
      trabajo = datos.id;
      try { sessionStorage.setItem('lucie-envio-wifi', trabajo); } catch (_) { /* El envío sigue disponible en esta vista. */ }
      el('wifi-cancelar').style.display = 'inline-block';
      el('wifi-progreso').style.display = 'block';
      dibujarArchivos();
      estado('Aceptá la recepción en Lucie Recibir o LocalSend en el celular.');
      await seguir();
    } catch (error) { estado(error.message); el('wifi-preparar').disabled = false; }
  }

  async function seguir() {
    if (!trabajo) return;
    try {
      const datos = await apiFetch('/api/publicacion/estado?id=' + encodeURIComponent(trabajo));
      el('wifi-progreso').value = Math.min(100, datos.total_bytes ? datos.bytes_enviados * 100 / datos.total_bytes : 0);
      let diagnostico = datos.etapa ? ' · Etapa: ' + datos.etapa : '';
      if (datos.codigo_http) diagnostico += ' · HTTP ' + datos.codigo_http;
      if (datos.cancelacion_confirmada === false) diagnostico += ' · El celular no confirmó la cancelación: revisá su recepción antes de reintentar.';
      if (datos.codigo_http === 409 && datos.etapa === 'preparacion') diagnostico += ' · Revisá o cancelá la recepción pendiente desde el celular; no se cancelará una sesión ajena.';
      estado(datos.mensaje + (datos.error ? ': ' + datos.error : '') +
        ' · Recibidos: ' + (datos.recibidos || []).length + ' · Archivados: ' + datos.publicados.length + diagnostico);
      if (datos.estado === 'en_curso') {
        timer = setTimeout(seguir, 1000);
      } else {
        trabajo = null;
        try { sessionStorage.removeItem('lucie-envio-wifi'); } catch (_) { /* Sin almacenamiento disponible. */ }
        el('wifi-preparar').disabled = false;
        el('wifi-cancelar').style.display = 'none';
        if (datos.estado === 'completado') seleccion.clear();
        await cargar();
      }
    } catch (error) {
      if (error.message === 'Envío no encontrado.') {
        trabajo = null;
        try { sessionStorage.removeItem('lucie-envio-wifi'); } catch (_) { /* Sin almacenamiento disponible. */ }
        el('wifi-preparar').disabled = false;
        el('wifi-cancelar').style.display = 'none';
        estado('La bandeja se reinició. Revisá el historial y los videos que siguen sin publicar antes de repetir el envío.');
        await cargar();
        return;
      }
      estado('No se pudo consultar el envío: ' + error.message + '. No inicies otro envío mientras verificás la conexión.');
      timer = setTimeout(seguir, 3000);
    }
  }

  window.cargarPublicacionWifi = cargar;
  el('wifi-actualizar').addEventListener('click', cargar);
  el('wifi-personaje').addEventListener('change', cambiarFiltro);
  el('wifi-filtro').addEventListener('input', cambiarFiltro);
  el('wifi-todos').addEventListener('click', () => { if (trabajo) return; seleccion = new Set(archivosVisibles().map(a => a.id)); invalidarPlan(); dibujarArchivos(); });
  el('wifi-ninguno').addEventListener('click', () => { if (trabajo) return; seleccion.clear(); invalidarPlan(); dibujarArchivos(); });
  el('wifi-dispositivo').addEventListener('change', invalidarPlan);
  el('wifi-buscar').addEventListener('click', buscar);
  el('wifi-conectar').addEventListener('click', conectar);
  el('wifi-preparar').addEventListener('click', preparar);
  el('wifi-cancelar').addEventListener('click', async () => {
    if (!trabajo) return;
    el('wifi-cancelar').disabled = true;
    try { await peticion('cancelar', {id: trabajo}); estado('Cancelando. Los videos no recibidos permanecerán en Sin publicar.'); }
    catch (error) { estado(error.message); }
    finally { el('wifi-cancelar').disabled = false; }
  });
  if (trabajo) {
    el('wifi-preparar').disabled = true;
    el('wifi-cancelar').style.display = 'inline-block';
    el('wifi-progreso').style.display = 'block';
    seguir();
  }
})();
