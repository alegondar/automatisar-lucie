/* Cola de publicación y emisor LocalSend integrado al dashboard local. */
(() => {
  'use strict';
  if (typeof document === 'undefined' || !document.getElementById('sec-publicacion')) return;
  let archivos = [];
  let pendriveConectado = false;
  const personajesElegidos = new Map();
  let organizacionPlan = null;
  let seleccion = new Set();
  let plan = null;
  let revision = 0;
  let revisando = false;
  let buscando = false;
  let conectando = false;
  let enviando = false;
  let historialEnvios = [];
  let trabajo = null;
  try { trabajo = sessionStorage.getItem('lucie-envio-wifi') || null; } catch (_) { /* Sin almacenamiento disponible. */ }
  let timer = null;
  let observadorPreviews = null;
  let consultaLista = 0;
  const etiquetasPersonaje = {lucie: 'Lucie', roli: 'Roli', mailen: 'Mailen', luna: 'Luna', sin_asignar: 'Sin asignar'};
  const dispositivos = new Map();
  const el = id => document.getElementById(id);
  const texto = (id, mensaje) => { el(id).textContent = mensaje; };
  const bytes = n => n < 1024 ? n + ' B' : n < 1024 * 1024 ? (n / 1024).toFixed(1) + ' KB' : (n / (1024 * 1024)).toFixed(1) + ' MB';
  const peticion = (accion, datos) => apiFetch('/api/publicacion/' + accion, {
    method: 'POST', body: JSON.stringify(datos || {})
  });
  const estado = mensaje => texto('wifi-estado', mensaje);
  const appElegida = () => el('wifi-app').value || 'lucie';
  const nombreApp = receptor => receptor === 'localsend' ? 'LocalSend' : 'Lucie Recibir';
  const tipoDispositivo = d => d.receptor || (d.port === 53318 && d.alias.startsWith('Lucie Recibir') ? 'lucie' : 'localsend');
  const aliasDispositivo = d => tipoDispositivo(d) === 'lucie' ? d.alias.replace(/^Lucie Recibir\s*[·-]\s*/, '') : d.alias;

  function invalidarPlan() {
    revision++;
    plan = null;
    el('wifi-plan').replaceChildren();
    el('wifi-plan').style.display = 'none';
    estado('');
    dibujarConteo();
  }

  function selectorPersonaje(archivo) {
    const selector = document.createElement('select');
    selector.setAttribute('aria-label', 'Personaje de ' + archivo.nombre);
    selector.add(new Option('Elegí el personaje', ''));
    for (const p of ['lucie', 'roli', 'mailen', 'luna']) selector.add(new Option(etiquetasPersonaje[p], p));
    selector.value = personajesElegidos.get(archivo.id) || '';
    selector.disabled = Boolean(trabajo) || enviando;
    selector.addEventListener('change', () => {
      personajesElegidos.set(archivo.id, selector.value);
      invalidarPlan();
      dibujarArchivos();
    });
    return selector;
  }

  function dibujarSeleccion() {
    const lista = el('wifi-seleccion-detalle');
    lista.replaceChildren();
    for (const archivo of archivos.filter(a => seleccion.has(a.id))) {
      const fila = document.createElement('div');
      fila.className = 'wifi-seleccion-fila';
      const nombre = document.createElement('strong'); nombre.textContent = archivo.nombre;
      const quitar = document.createElement('button');
      quitar.className = 'wifi-quitar'; quitar.textContent = 'Quitar';
      quitar.setAttribute('aria-label', 'Quitar ' + archivo.nombre + ' del envío');
      quitar.disabled = Boolean(trabajo) || enviando;
      quitar.addEventListener('click', () => { seleccion.delete(archivo.id); invalidarPlan(); dibujarArchivos(); });
      fila.append(nombre, quitar);
      if (archivo.personaje === 'sin_asignar') {
        const etiqueta = document.createElement('label');
        etiqueta.className = 'wifi-asignacion';
        etiqueta.textContent = '¿De qué personaje es?';
        etiqueta.append(selectorPersonaje(archivo)); fila.append(etiqueta);
      } else {
        const personaje = document.createElement('span');
        personaje.textContent = etiquetasPersonaje[archivo.personaje] + ' · ' + bytes(archivo.tamano);
        fila.append(personaje);
      }
      lista.append(fila);
    }
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
    const elegidos = archivos.filter(a => seleccion.has(a.id));
    texto('wifi-resumen-seleccion', elegidos.length ? elegidos.length + (elegidos.length === 1 ? ' archivo' : ' archivos') +
      ' · ' + bytes(elegidos.reduce((s, a) => s + a.tamano, 0)) : 'Ningún archivo seleccionado. Marcá los que quieras enviar.');
    const celular = dispositivos.get(el('wifi-dispositivo').value);
    texto('wifi-destino', celular ? 'Recibe: ' + nombreApp(celular.receptor || appElegida()) + ' · ' +
      aliasDispositivo(celular) + ' · ' + celular.ip + ':' + celular.port : trabajo ? 'Envío en curso. El receptor se conserva hasta que termine.' : 'Todavía no elegiste un celular.');
    const ocupado = Boolean(trabajo) || enviando;
    const sinPersonaje = elegidos.filter(a => a.personaje === 'sin_asignar' && !personajesElegidos.get(a.id));
    const listo = !ocupado && !revisando && !buscando && !conectando && elegidos.length > 0 && !sinPersonaje.length && Boolean(celular);
    el('wifi-preparar').disabled = !listo || Boolean(plan);
    el('wifi-preparar').textContent = revisando ? 'Revisando archivos…' : plan ? 'Revisión lista abajo' : 'Revisar envío';
    texto('wifi-siguiente', ocupado ? 'Esperá a que termine este envío.' : revisando ? 'Comprobando archivos y destinos…' :
      !elegidos.length ? '1. Marcá el video que querés enviar.' : sinPersonaje.length ? 'Elegí el personaje de ' + sinPersonaje.map(a => a.nombre).join(', ') + ' aquí arriba.' :
      buscando || conectando ? 'Buscando conexión con el celular…' : !celular ? '2. Buscá tu celular y elegilo en la lista.' :
      plan ? '3. Revisá el detalle y pulsá Confirmar y enviar.' : 'Todo listo. Revisá el envío para continuar.');
    el('wifi-siguiente').dataset.estado = listo || plan ? 'listo' : sinPersonaje.length ? 'pendiente' : 'esperando';
    el('wifi-paso-celular').dataset.estado = celular ? 'listo' : 'pendiente';
    texto('wifi-conexion-resumen', celular ? 'Cambiar celular o app' : 'Buscar o elegir celular');
    for (const id of ['wifi-app', 'wifi-dispositivo', 'wifi-ip', 'wifi-puerto', 'wifi-todos', 'wifi-ninguno', 'wifi-actualizar', 'wifi-tab-historial', 'wifi-tab-organizacion']) el(id).disabled = ocupado;
    el('wifi-buscar').disabled = ocupado || buscando;
    el('wifi-conectar').disabled = ocupado || conectando;
    dibujarSeleccion();
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
      lista.textContent = pendriveConectado ? 'No hay videos ni fotos pendientes en Sin publicar. Los nuevos exports aparecerán aquí después de copiarse al pendrive.' : 'Conectá el pendrive para ver los archivos listos para enviar.';
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
          asignacion.className = 'wifi-asignacion';
          asignacion.textContent = 'Personaje para publicar';
          asignacion.append(selectorPersonaje(archivo));
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
    selector.replaceChildren(new Option('Elegí el celular', ''));
    for (const dispositivo of dispositivos.values()) {
      selector.add(new Option(aliasDispositivo(dispositivo) +
        ' · ' + dispositivo.ip + ':' + dispositivo.port, dispositivo.id));
    }
    selector.value = '';
    dibujarConteo();
  }

  async function cargar() {
    const consulta = ++consultaLista;
    try {
      const datos = await apiFetch('/api/publicacion/lista');
      if (consulta !== consultaLista) return;
      pendriveConectado = Boolean(datos.conectado);
      texto('wifi-fuente-estado', datos.conectado ? 'Pendrive conectado · Archivos de Sin publicar' : datos.mensaje || 'Conectá el pendrive vinculado.');
      const nuevos = datos.archivos || [];
      // Una revisión solo vale para la versión exacta de sus archivos.
      // La misma ruta puede reaparecer con contenido nuevo entre sondeos.
      const firma = a => JSON.stringify([a.ruta, a.tamano, a.mtime, a.personaje]);
      if ([...seleccion].some(id => firma(archivos.find(a => a.id === id) || {}) !== firma(nuevos.find(a => a.id === id) || {}))) invalidarPlan();
      archivos = nuevos;
      for (const id of personajesElegidos.keys()) if (!archivos.some(a => a.id === id)) personajesElegidos.delete(id);
      dibujarOrganizacion(datos);
      const disponibles = new Set(archivosVisibles().map(a => a.id));
      seleccion = new Set([...seleccion].filter(id => disponibles.has(id)));
      texto('wifi-carpeta', datos.conectado ? datos.carpeta : datos.mensaje);
      dibujarArchivos();
      historialEnvios = datos.historial || [];
      dibujarHistorial();
    } catch (error) { if (consulta === consultaLista) estado(error.message); }
  }

  function dibujarHistorial() {
      const historial = el('wifi-historial');
      historial.replaceChildren();
      texto('wifi-historial-conteo', String(historialEnvios.length));
      const busqueda = el('wifi-historial-filtro').value.trim().toLocaleLowerCase();
      const visibles = historialEnvios.filter(e => (e.ruta_destino + ' ' + e.dispositivo + ' ' + e.fecha).toLocaleLowerCase().includes(busqueda));
      if (!visibles.length) historial.textContent = historialEnvios.length ? 'No hay envíos que coincidan con tu búsqueda.' : 'Todavía no enviaste archivos desde esta sección.';
      for (const envio of visibles) {
        const fila = document.createElement('article');
        fila.className = 'wifi-historial-fila';
        const etiqueta = document.createElement('div');
        const titulo = document.createElement('strong');
        titulo.className = 'wifi-historial-titulo';
        titulo.textContent = envio.ruta_destino.split('/').at(-1);
        const meta = document.createElement('p'); meta.className = 'wifi-historial-meta';
        const fecha = new Date(envio.fecha);
        const fechaLegible = Number.isNaN(fecha.getTime()) ? envio.fecha : fecha.toLocaleString('es-AR', {dateStyle: 'medium', timeStyle: 'short'});
        const personaje = envio.personaje || envio.ruta_destino.split('/')[2];
        meta.textContent = (etiquetasPersonaje[personaje] || 'Sin asignar') + ' · ' + fechaLegible + ' · Recibido en ' + envio.dispositivo;
        const detalles = document.createElement('details'); detalles.className = 'wifi-detalles';
        const resumen = document.createElement('summary'); resumen.textContent = 'Ver ubicación del archivo';
        const ruta = document.createElement('p'); ruta.textContent = envio.ruta_destino;
        detalles.append(resumen, ruta); etiqueta.append(titulo, meta, detalles);
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
  }

  function mostrarVista(vista) {
    if ((trabajo || enviando) && vista !== 'envio') return;
    for (const nombre of ['envio', 'historial', 'organizacion']) {
      el('wifi-vista-' + nombre).style.display = nombre === vista ? (nombre === 'envio' ? 'grid' : 'block') : 'none';
      el('wifi-tab-' + nombre).setAttribute('aria-pressed', String(nombre === vista));
    }
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
        for (const p of ['lucie', 'roli', 'mailen', 'luna']) personaje.add(new Option(etiquetasPersonaje[p], p));
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
    if (trabajo || enviando || buscando) return;
    buscando = true;
    invalidarPlan();
    const receptor = appElegida();
    dispositivos.clear(); dibujarDispositivos();
    el('wifi-buscar').disabled = true;
    texto('wifi-busqueda-estado', 'Buscando ' + nombreApp(receptor) + ' en la Wi-Fi actual… Puede tardar unos segundos.');
    try {
      const datos = await peticion('buscar', {receptor});
      if (appElegida() !== receptor) return;
      dispositivos.clear();
      for (const d of datos.dispositivos || []) if (tipoDispositivo(d) === receptor) dispositivos.set(d.id, d);
      dibujarDispositivos();
      texto('wifi-busqueda-estado', dispositivos.size ? 'Encontramos ' + dispositivos.size + '. Elegí tu celular en la lista.' :
        'No encontramos ' + nombreApp(receptor) + '. Abrí esa app en el celular y buscá de nuevo. También podés usar la conexión manual.');
    } catch (error) { texto('wifi-busqueda-estado', error.message); }
    finally { buscando = false; dibujarConteo(); }
  }

  async function conectar() {
    if (trabajo || enviando || conectando) return;
    conectando = true;
    invalidarPlan();
    const receptor = appElegida();
    el('wifi-conectar').disabled = true;
    texto('wifi-busqueda-estado', 'Comprobando ' + nombreApp(receptor) + '…');
    try {
      const datos = await peticion('conectar', {ip: el('wifi-ip').value.trim(), puerto: Number(el('wifi-puerto').value), receptor});
      if (appElegida() !== receptor) return;
      if (tipoDispositivo(datos.dispositivo) !== receptor) throw new Error('En esa dirección responde ' + nombreApp(tipoDispositivo(datos.dispositivo)) + '. Cambiá la app elegida o revisá el puerto.');
      dispositivos.set(datos.dispositivo.id, datos.dispositivo);
      dibujarDispositivos();
      el('wifi-dispositivo').value = datos.dispositivo.id;
      el('wifi-conexion').open = false;
      invalidarPlan();
      texto('wifi-busqueda-estado', 'Conectado con ' + nombreApp(receptor) + '. El destino está listo para revisar.');
    } catch (error) { texto('wifi-busqueda-estado', error.message); }
    finally { conectando = false; dibujarConteo(); }
  }

  async function preparar() {
    if (trabajo || enviando || revisando || buscando || conectando) return;
    if (!seleccion.size || !el('wifi-dispositivo').value) {
      estado('Seleccioná al menos un video y elegí el celular receptor.');
      return;
    }
    el('wifi-preparar').disabled = true;
    estado('Calculando integridad y revisando los destinos…');
    invalidarPlan();
    const version = revision;
    revisando = true;
    dibujarConteo();
    try {
      const personajes = {};
      for (const id of seleccion) {
        const archivo = archivos.find(a => a.id === id);
        if (archivo && archivo.personaje === 'sin_asignar') {
          if (!personajesElegidos.get(id)) throw new Error('Elegí el personaje de ' + archivo.nombre + ' antes de enviar.');
          personajes[id] = personajesElegidos.get(id);
        }
      }
      const resultado = await peticion('simular', {seleccion: [...seleccion], dispositivo_id: el('wifi-dispositivo').value, personajes, receptor: appElegida()});
      if (revision !== version || trabajo) return;
      if (tipoDispositivo(resultado.dispositivo) !== appElegida()) throw new Error('La app receptora cambió. Buscá y elegí nuevamente el celular.');
      plan = resultado;
      const cont = el('wifi-plan');
      cont.style.display = 'block';
      const titulo = document.createElement('h3');
      titulo.textContent = nombreApp(plan.dispositivo.receptor || appElegida()) + ' · ' + aliasDispositivo(plan.dispositivo) + ' · ' + bytes(plan.total_bytes);
      const detalle = document.createElement('ul');
      for (const archivo of plan.archivos) {
        const item = document.createElement('li');
        item.textContent = archivo.nombre + ' · ' + bytes(archivo.tamano);
        const destino = document.createElement('details'); destino.className = 'wifi-detalles';
        const resumen = document.createElement('summary'); resumen.textContent = 'Ubicación después de recibir';
        const ruta = document.createElement('p'); ruta.textContent = archivo.destino_rel;
        destino.append(resumen, ruta); item.append(destino);
        detalle.append(item);
      }
      const aviso = document.createElement('div'); aviso.className = 'wifi-ayuda';
      aviso.textContent = plan.aviso;
      if (plan.dispositivo.protocol === 'https' && plan.dispositivo.fingerprint) {
        const identidad = document.createElement('details'); identidad.className = 'wifi-detalles';
        const tituloIdentidad = document.createElement('summary'); tituloIdentidad.textContent = 'Comparar identidad HTTPS del celular';
        const huella = document.createElement('p'); huella.textContent = plan.dispositivo.fingerprint;
        identidad.append(tituloIdentidad, huella); aviso.append(identidad);
      }
      const confirmar = document.createElement('button');
      confirmar.className = 'btn-sm wifi-principal';
      confirmar.textContent = 'Confirmar y enviar al celular';
      const token = plan.token;
      confirmar.addEventListener('click', () => iniciar(token));
      const cancelar = document.createElement('button');
      cancelar.className = 'btn-sm btn-secundario';
      cancelar.textContent = 'Cancelar revisión';
      cancelar.addEventListener('click', invalidarPlan);
      cont.replaceChildren(titulo, detalle, aviso, confirmar, cancelar);
      cont.scrollIntoView?.({behavior: 'smooth', block: 'nearest'});
      estado('Revisá los archivos y destinos. Todavía no se envió ni movió ningún video.');
    } catch (error) { estado(error.message); }
    finally { revisando = false; dibujarConteo(); }
  }

  async function iniciar(tokenEsperado) {
    if (!plan || plan.token !== tokenEsperado || trabajo || enviando) return;
    const token = plan.token;
    enviando = true;
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
      estado('Aceptá la recepción en ' + nombreApp(appElegida()) + ' en el celular.');
      await seguir();
    } catch (error) { estado(error.message); }
    finally { enviando = false; dibujarConteo(); }
  }

  async function seguir() {
    if (!trabajo) return;
    try {
      const datos = await apiFetch('/api/publicacion/estado?id=' + encodeURIComponent(trabajo));
      // Retirar de la galería cada archivo ya archivado, también en envíos
      // de varios videos o si el siguiente archivo falla.
      const publicados = new Set((datos.publicados || []).map(a => a.ruta_origen));
      if (archivos.some(a => publicados.has(a.ruta))) {
        consultaLista++; // Descartar listados previos al archivado confirmado.
        archivos = archivos.filter(a => !publicados.has(a.ruta));
        const pendientes = new Set(archivos.map(a => a.id));
        seleccion = new Set([...seleccion].filter(id => pendientes.has(id)));
        dibujarArchivos();
      }
      if (datos.dispositivo) {
        const d = datos.dispositivo;
        dispositivos.set(d.id, d);
        el('wifi-app').value = tipoDispositivo(d);
        el('wifi-puerto').value = String(d.port);
        dibujarDispositivos();
        el('wifi-dispositivo').value = d.id;
        el('wifi-conexion').open = false;
        dibujarConteo();
      }
      el('wifi-progreso').value = Math.min(100, datos.total_bytes ? datos.bytes_enviados * 100 / datos.total_bytes : 0);
      let diagnostico = datos.etapa ? ' · Etapa: ' + datos.etapa : '';
      if (datos.codigo_http) diagnostico += ' · HTTP ' + datos.codigo_http;
      if (datos.cancelacion_confirmada === false) diagnostico += ' · El celular no confirmó la cancelación: revisá su recepción antes de reintentar.';
      if (datos.codigo_http === 409 && datos.etapa === 'preparacion') diagnostico += ' · Revisá o cancelá la recepción pendiente desde el celular; no se cancelará una sesión ajena.';
      texto('wifi-diagnostico-texto', diagnostico);
      el('wifi-diagnostico').style.display = diagnostico ? 'block' : 'none';
      estado(datos.mensaje + (datos.error ? ': ' + datos.error : '') +
        ' · Recibidos: ' + (datos.recibidos || []).length + ' · Archivados: ' + (datos.publicados || []).length +
        (datos.cancelacion_confirmada === false ? ' · Verificá la recepción en el celular antes de reintentar.' : ''));
      if (datos.estado === 'en_curso') {
        timer = setTimeout(seguir, 1000);
      } else {
        trabajo = null;
        if (!el('wifi-app').value) el('wifi-app').value = 'lucie';
        try { sessionStorage.removeItem('lucie-envio-wifi'); } catch (_) { /* Sin almacenamiento disponible. */ }
        el('wifi-preparar').disabled = false;
        el('wifi-cancelar').style.display = 'none';
        if (datos.estado === 'completado') seleccion.clear();
        await cargar();
      }
    } catch (error) {
      if (error.message === 'Envío no encontrado.') {
        trabajo = null;
        if (!el('wifi-app').value) el('wifi-app').value = 'lucie';
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
  for (const vista of ['envio', 'historial', 'organizacion']) el('wifi-tab-' + vista).addEventListener('click', () => mostrarVista(vista));
  el('wifi-historial-filtro').addEventListener('input', dibujarHistorial);
  el('wifi-app').addEventListener('change', () => {
    if (trabajo) return;
    dispositivos.clear(); dibujarDispositivos(); invalidarPlan();
    el('wifi-conexion').open = true;
    el('wifi-puerto').value = appElegida() === 'lucie' ? '53318' : '53317';
    texto('wifi-busqueda-estado', 'Abrí ' + nombreApp(appElegida()) + ' en el celular y buscá nuevamente.');
  });
  el('wifi-actualizar').addEventListener('click', cargar);
  el('wifi-personaje').addEventListener('change', cambiarFiltro);
  el('wifi-filtro').addEventListener('input', cambiarFiltro);
  el('wifi-todos').addEventListener('click', () => { if (trabajo) return; seleccion = new Set(archivosVisibles().map(a => a.id)); invalidarPlan(); dibujarArchivos(); });
  el('wifi-ninguno').addEventListener('click', () => { if (trabajo) return; seleccion.clear(); invalidarPlan(); dibujarArchivos(); });
  el('wifi-dispositivo').addEventListener('change', () => {
    el('wifi-conexion').open = !dispositivos.has(el('wifi-dispositivo').value);
    invalidarPlan();
  });
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
    // Hasta recibir el estado del servidor no se adivina qué app tiene el envío.
    el('wifi-app').value = '';
    dibujarConteo();
    el('wifi-preparar').disabled = true;
    el('wifi-cancelar').style.display = 'inline-block';
    el('wifi-progreso').style.display = 'block';
    seguir();
  }
})();
