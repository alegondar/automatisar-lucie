    const TITULO_BASE = document.title;
    let versionActualToken = null;
    let temporizadorSondeo = null;
    let sondeoEnCurso = false;
    let reintentoEsperaSegundos = REFRESCO_PANEL_SEGUNDOS > 0 ? REFRESCO_PANEL_SEGUNDOS : 4;
    let desconectado = false;
    let lotesNuevosSegundoPlano = 0;
    let temporizadorToast = null;

    let datosEstado = { lotes: [], lotes_anteriores: [], sin_identificar: [], escenas: [], personajes: [], ultimo_personaje: "lucie", capitulo_activo: null, capitulo_foco: null, capitulos_abiertos: [], cantidad_abiertos: 0, alerta_olvidado: false, horas_limite: 12, balance_capitulo: { pendientes: 0, movidos: 0 } };
    let simulacionActiva = null;
    let descarteSimulacionActiva = null;
    let loteActivoId = null;
    let terminarCapituloTrasMover = null;
    let pestanaActual = 'lotes';
    let historialActual = [];
    let operacionAvisoActual = null;

    let bannerPendriveDescartado = false;
    let ultimoTextoBannerPendrive = null;

    function mostrarBannerPendrive(texto) {
      if (texto !== ultimoTextoBannerPendrive) {
        bannerPendriveDescartado = false;
        ultimoTextoBannerPendrive = texto;
      }
      if (bannerPendriveDescartado) return;
      const b = document.getElementById('banner-pendrive-detectado');
      const t = document.getElementById('banner-pendrive-texto');
      if (b && t) {
        t.innerText = texto;
        b.style.display = 'flex';
      }
    }

    function ocultarBannerPendrive() {
      const b = document.getElementById('banner-pendrive-detectado');
      if (b) b.style.display = 'none';
    }

    function cerrarBannerPendrive() {
      ocultarBannerPendrive();
      bannerPendriveDescartado = true;
    }

    function mostrarToastLlegada(mensaje) {
      const toast = document.getElementById('toast-llegada');
      if (!toast) return;
      toast.innerText = mensaje;
      toast.classList.add('visible');
      if (temporizadorToast) clearTimeout(temporizadorToast);
      temporizadorToast = setTimeout(() => {
        toast.classList.remove('visible');
      }, 5000);
    }

    function mostrarAvisoDesconexion() {
      const banner = document.getElementById('banner-desconexion');
      if (banner) banner.style.display = 'flex';
    }

    function ocultarAvisoDesconexion() {
      const banner = document.getElementById('banner-desconexion');
      if (banner) banner.style.display = 'none';
    }

    function hayModalAbierto() {
      if (document.getElementById('dialog-eliminacion')?.open || document.getElementById('dialog-eliminacion-imagen')?.open) return true;
      const idsModales = ['modal-simulacion', 'modal-terminar-capitulo', 'modal-descartar-capitulo', 'modal-plan-envio', 'modal-vincular-pendrive', 'modal-visor-media', 'modal-control-pendrive'];
      return idsModales.some(id => {
        const el = document.getElementById(id);
        return el && el.style.display && el.style.display !== 'none';
      });
    }

    function hayCampoEnEdicion() {
      const activo = document.activeElement;
      if (activo && (activo.tagName === 'INPUT' || activo.tagName === 'SELECT' || activo.tagName === 'TEXTAREA')) {
        return true;
      }
      const inputs = document.querySelectorAll('input[id^="txt-nueva-escena-"]');
      for (const inp of inputs) {
        if (inp.value && inp.value.trim().length > 0 && inp.style.display !== 'none') {
          return true;
        }
      }
      return false;
    }

    function capturarEstadoUI() {
      const snap = {
        archivosChecked: {},
        lotesListosChecked: {},
        lotesAnterioresChecked: {},
        persSeleccionado: {},
        escenaSeleccionada: {},
        nuevaEscenaTexto: {},
        detailsAnterioresAbierto: false,
        scrollY: window.scrollY || document.documentElement.scrollTop || 0,
        pestana: pestanaActual
      };

      document.querySelectorAll('.chk-archivo').forEach(cb => {
        const id = cb.getAttribute('data-id');
        if (id) snap.archivosChecked[id] = cb.checked;
      });

      document.querySelectorAll('.cb-lote-listo').forEach(cb => {
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId) snap.lotesListosChecked[loteId] = cb.checked;
      });

      document.querySelectorAll('.cb-lote-anterior').forEach(cb => {
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId) snap.lotesAnterioresChecked[loteId] = cb.checked;
      });

      document.querySelectorAll('select[id^="sel-pers-"]').forEach(sel => {
        const loteId = sel.id.replace('sel-pers-', '');
        snap.persSeleccionado[loteId] = sel.value;
      });

      document.querySelectorAll('select[id^="sel-escena-"]').forEach(sel => {
        const loteId = sel.id.replace('sel-escena-', '');
        snap.escenaSeleccionada[loteId] = sel.value;
      });

      document.querySelectorAll('input[id^="txt-nueva-escena-"]').forEach(inp => {
        const loteId = inp.id.replace('txt-nueva-escena-', '');
        snap.nuevaEscenaTexto[loteId] = inp.value;
      });

      const detailsAnt = document.getElementById('details-anteriores');
      if (detailsAnt) {
        snap.detailsAnterioresAbierto = detailsAnt.hasAttribute('open');
      }

      return snap;
    }

    function restaurarEstadoUI(snap) {
      if (!snap) return;

      document.querySelectorAll('.chk-archivo').forEach(cb => {
        const id = cb.getAttribute('data-id');
        if (id && Object.prototype.hasOwnProperty.call(snap.archivosChecked, id)) {
          cb.checked = snap.archivosChecked[id];
        }
      });

      document.querySelectorAll('.cb-lote-listo').forEach(cb => {
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId && Object.prototype.hasOwnProperty.call(snap.lotesListosChecked, loteId)) {
          cb.checked = snap.lotesListosChecked[loteId];
        }
      });

      document.querySelectorAll('.cb-lote-anterior').forEach(cb => {
        const loteId = cb.getAttribute('data-lote-id');
        if (loteId && Object.prototype.hasOwnProperty.call(snap.lotesAnterioresChecked, loteId)) {
          cb.checked = snap.lotesAnterioresChecked[loteId];
        }
      });

      for (const loteId in snap.persSeleccionado) {
        const sel = document.getElementById(`sel-pers-${loteId}`);
        if (sel) sel.value = snap.persSeleccionado[loteId];
      }

      for (const loteId in snap.escenaSeleccionada) {
        const sel = document.getElementById(`sel-escena-${loteId}`);
        if (sel) {
          sel.value = snap.escenaSeleccionada[loteId];
          toggleNuevaEscena(loteId, sel.value);
        }
      }

      for (const loteId in snap.nuevaEscenaTexto) {
        const inp = document.getElementById(`txt-nueva-escena-${loteId}`);
        if (inp && snap.nuevaEscenaTexto[loteId] !== undefined) {
          inp.value = snap.nuevaEscenaTexto[loteId];
          validarInputEscena(loteId);
        }
      }

      const detailsAnt = document.getElementById('details-anteriores');
      if (detailsAnt) {
        if (snap.detailsAnterioresAbierto) {
          detailsAnt.setAttribute('open', '');
        } else {
          detailsAnt.removeAttribute('open');
        }
      }

      const todosLotes = (datosEstado.lotes || []).concat(datosEstado.lotes_anteriores || []);
      todosLotes.forEach(l => {
        actualizarSeleccionLote(l.lote_id);
      });

      if (typeof snap.scrollY === 'number') {
        window.scrollTo(0, snap.scrollY);
      }
    }

    function escapeHTML(str) {
      return String(str || '').replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
      }[tag] || tag));
    }

    function mostrarAvisoMover(totalMovidos, personaje, escena, idOperacion) {
      operacionAvisoActual = idOperacion;
      const banner = document.getElementById('banner-aviso');
      const msg = document.getElementById('banner-aviso-msg');
      if (personaje === 'varios') {
        msg.innerText = `Se movieron ${totalMovidos} archivos en ${escena}`;
      } else {
        msg.innerText = `Se movieron ${totalMovidos} archivos a ${personaje}/${escena}`;
      }
      banner.style.display = 'flex';
    }

    function mostrarAvisoDescartar(personaje, escena, idOperacion) {
      operacionAvisoActual = idOperacion;
      const banner = document.getElementById('banner-aviso');
      const msg = document.getElementById('banner-aviso-msg');
      if (msg) {
        msg.innerText = `Se descartó el capítulo ${personaje}/${escena} (movido a _descartados)`;
      }
      if (banner) banner.style.display = 'flex';
    }

    function mostrarAvisoSinIdentificar(nombre, hash, ruta, esProyecto) {
      operacionAvisoActual = {
        tipo: 'sin_identificar',
        hash: hash,
        ruta: ruta,
        nombre: nombre,
        esProyecto: esProyecto
      };
      const banner = document.getElementById('banner-aviso');
      const msg = document.getElementById('banner-aviso-msg');
      if (msg) {
        if (esProyecto) {
          msg.innerHTML = `Agregado a Lotes Detectados: <strong>${escapeHTML(nombre)}</strong>. <a href="#" onclick="mostrarPestana('lotes'); return false;" style="color:#38bdf8; text-decoration:underline; font-weight:600; margin-left:8px;">Ver en Lotes Detectados &rarr;</a>`;
        } else {
          msg.innerHTML = `Archivo <strong>${escapeHTML(nombre)}</strong> marcado como ignorado.`;
        }
      }
      if (banner) banner.style.display = 'flex';
    }

    function cerrarAviso() {
      const banner = document.getElementById('banner-aviso');
      banner.style.display = 'none';
      operacionAvisoActual = null;
    }

    async function deshacerDesdeAviso() {
      if (!operacionAvisoActual) return;
      if (typeof operacionAvisoActual === 'object' && operacionAvisoActual.tipo === 'sin_identificar') {
        const op = operacionAvisoActual;
        try {
          await apiFetch('/api/deshacer-clasificar-sin-identificar', {
            method: 'POST',
            body: JSON.stringify({ hash: op.hash, ruta: op.ruta })
          });
          cerrarAviso();
          await cargarDatos();
          mostrarToastLlegada(`Se restableció "${op.nombre}" en Sin Identificar`);
        } catch (e) {
          mostrarError(`Error al deshacer: ${e.message}`);
        }
        return;
      }
      const idOp = operacionAvisoActual;
      if (!confirm("¿Confirmás deshacer esta operación? Los archivos regresarán a sus rutas originales.")) {
        return;
      }
      try {
        const res = await apiFetch('/api/deshacer', {
          method: 'POST',
          body: JSON.stringify({ id_operacion: idOp })
        });
        cerrarAviso();
        await cargarDatos();
        if (pestanaActual === 'historial') {
          await cargarHistorial();
        } else if (pestanaActual === 'capitulos-cerrados') {
          await cargarCapitulosCerrados();
        } else if (pestanaActual === 'descartados') {
          await cargarCapitulosDescartados();
        }
      } catch (e) {
        mostrarError(e.message);
      }
    }

    let capituloATerminarId = null;

    function mostrarPestana(pestana, ev) {
      pestanaActual = pestana;
      document.body?.classList?.toggle('vista-eliminacion', pestana === 'eliminacion');
      if (pestana !== 'eliminacion') document.querySelectorAll('#sec-eliminacion video, #sec-eliminacion audio').forEach(m => m.pause());
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      if (ev && ev.target) {
        ev.target.classList.add('active');
      } else {
        const btn = document.getElementById(`nav-btn-${pestana}`);
        if (btn) btn.classList.add('active');
      }

      document.getElementById('sec-lotes').style.display = (pestana === 'lotes') ? 'block' : 'none';
      document.getElementById('sec-sin-identificar').style.display = (pestana === 'sin-identificar') ? 'block' : 'none';
      document.getElementById('sec-capitulos-abiertos').style.display = (pestana === 'capitulos-abiertos') ? 'block' : 'none';
      document.getElementById('sec-capitulos-cerrados').style.display = (pestana === 'capitulos-cerrados') ? 'block' : 'none';
      document.getElementById('sec-descartados').style.display = (pestana === 'descartados') ? 'block' : 'none';
      document.getElementById('sec-pendrive').style.display = (pestana === 'pendrive') ? 'block' : 'none';
      document.getElementById('sec-eliminacion').style.display = (pestana === 'eliminacion') ? 'block' : 'none';
      document.getElementById('sec-edicion').style.display = (pestana === 'edicion') ? 'block' : 'none';
      document.getElementById('sec-completados').style.display = (pestana === 'completados') ? 'block' : 'none';
      const publicacion = document.getElementById('sec-publicacion');
      if (publicacion) publicacion.style.display = (pestana === 'publicacion') ? 'block' : 'none';
      document.getElementById('sec-historial').style.display = (pestana === 'historial') ? 'block' : 'none';

      if (pestana === 'publicacion') {
        if (window.cargarPublicacionWifi) window.cargarPublicacionWifi();
      } else if (pestana === 'eliminacion') {
        cargarEliminacion();
      } else if (pestana === 'historial') {
        cargarHistorial();
      } else if (pestana === 'pendrive') {
        cargarVistaPendrive();
      } else if (pestana === 'edicion' || pestana === 'completados') {
        cargarVistaEdicion();
      } else if (pestana === 'capitulos-abiertos') {
        cargarCapitulosAbiertos();
      } else if (pestana === 'capitulos-cerrados') {
        cargarCapitulosCerrados();
      } else if (pestana === 'descartados') {
        cargarCapitulosDescartados();
      }
    }

    async function recargarVistaActual() {
      if (pestanaActual === 'publicacion') {
        if (window.cargarPublicacionWifi) await window.cargarPublicacionWifi();
      } else if (pestanaActual === 'eliminacion') {
        await cargarEliminacion();
      } else if (pestanaActual === 'historial') {
        await cargarHistorial();
      } else if (pestanaActual === 'pendrive') {
        await cargarVistaPendrive();
      } else if (pestanaActual === 'edicion' || pestanaActual === 'completados') {
        await cargarVistaEdicion();
      } else if (pestanaActual === 'capitulos-abiertos') {
        await cargarCapitulosAbiertos();
      } else if (pestanaActual === 'capitulos-cerrados') {
        await cargarCapitulosCerrados();
      } else if (pestanaActual === 'descartados') {
        await cargarCapitulosDescartados();
      } else {
        await cargarDatos();
      }
    }

    function mostrarError(msg) {
      const b = document.getElementById('alert-box');
      b.innerText = msg;
      b.style.display = 'block';
      setTimeout(() => { b.style.display = 'none'; }, 8000);
    }

    async function fetchConCsrf(url, options = {}) {
      if ((options.method || 'GET').toUpperCase() !== 'POST') return fetch(url, options);

      // La bandeja cambia su token al reiniciarse; una pestaña abierta no lo sabe.
      // Renovar antes de actuar evita reenviar una operación de resultado incierto.
      const pagina = await fetch('/panel.html', {
        cache: 'no-store', mode: 'same-origin', credentials: 'same-origin',
        redirect: 'error', signal: options.signal
      });
      if (!pagina.ok) throw new Error('No se pudo actualizar la conexión. Recargá el dashboard y volvé a intentar.');
      const html = new DOMParser().parseFromString(await pagina.text(), 'text/html');
      const token = html.querySelector('meta[name="csrf-token"]')?.content?.trim();
      if (!token || token === '__TOKEN_CSRF__') {
        throw new Error('No se pudo actualizar la conexión. Recargá el dashboard y volvé a intentar.');
      }
      const headers = new Headers(options.headers);
      headers.set('Content-Type', 'application/json');
      headers.set('X-CSRF-Token', token);
      return fetch(url, {...options, headers, mode: 'same-origin', redirect: 'error'});
    }

    async function apiFetch(url, options = {}) {
      const res = await fetchConCsrf(url, options);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        const e = new Error(err.error || 'Error en la petición');
        e.detalles = err;
        throw e;
      }
      return await res.json();
    }

    async function cargarDatos() {
      try {
        const [lotesRes, sinIdRes, escenasRes, persRes, capRes, versionRes] = await Promise.all([
          apiFetch('/api/lotes'),
          apiFetch('/api/sin-identificar'),
          apiFetch('/api/escenas'),
          apiFetch('/api/personajes'),
          apiFetch('/api/capitulos/estado'),
          apiFetch('/api/estado-version').catch(() => null)
        ]);
        if (versionRes && versionRes.version) {
          versionActualToken = versionRes.version;
        }
        datosEstado.lotes = lotesRes.lotes || [];
        datosEstado.lotes_anteriores = lotesRes.lotes_anteriores || [];
        datosEstado.horas_material_reciente = lotesRes.horas_material_reciente || 168;
        datosEstado.sin_identificar = sinIdRes.sin_identificar || [];
        datosEstado.escenas = escenasRes.escenas || [];
        datosEstado.personajes = persRes.personajes || [];
        datosEstado.ultimo_personaje = persRes.ultimo_personaje;
        datosEstado.capitulo_activo = capRes.capitulo_foco || capRes.capitulo;
        datosEstado.capitulo_foco = capRes.capitulo_foco;
        datosEstado.capitulos_abiertos = capRes.capitulos_abiertos || [];
        datosEstado.cantidad_abiertos = capRes.cantidad_abiertos || 0;
        datosEstado.alerta_olvidado = capRes.alerta_olvidado;
        datosEstado.horas_limite = capRes.horas_limite;
        datosEstado.balance_capitulo = capRes.balance;
        renderCapituloActivo();
        renderLotes();
        renderLotesAnteriores();
        renderSinIdentificar();
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function recargarConPreservacion() {
      const snap = capturarEstadoUI();
      const enEdicion = hayCampoEnEdicion();

      try {
        const [lotesRes, sinIdRes, escenasRes, persRes, capRes, versionRes] = await Promise.all([
          apiFetch('/api/lotes'),
          apiFetch('/api/sin-identificar'),
          apiFetch('/api/escenas'),
          apiFetch('/api/personajes'),
          apiFetch('/api/capitulos/estado'),
          apiFetch('/api/estado-version').catch(() => null)
        ]);

        if (versionRes && versionRes.version) {
          versionActualToken = versionRes.version;
        }

        const nuevosLotes = lotesRes.lotes || [];
        const nuevosAnt = lotesRes.lotes_anteriores || [];
        datosEstado.horas_material_reciente = lotesRes.horas_material_reciente || 168;

        const idsLotesPrevios = new Set((datosEstado.lotes || []).map(l => l.lote_id));
        const lotesNuevosEntrantes = nuevosLotes.filter(l => !l.es_anterior && !idsLotesPrevios.has(l.lote_id));

        const idsArchivosPrevios = new Set();
        (datosEstado.lotes || []).forEach(l => (l.archivos || []).forEach(a => idsArchivosPrevios.add(String(a.id_db))));
        (datosEstado.lotes_anteriores || []).forEach(l => (l.archivos || []).forEach(a => idsArchivosPrevios.add(String(a.id_db))));

        let cantArchivosNuevos = 0;
        nuevosLotes.forEach(l => (l.archivos || []).forEach(a => {
          if (!idsArchivosPrevios.has(String(a.id_db))) cantArchivosNuevos++;
        }));
        nuevosAnt.forEach(l => (l.archivos || []).forEach(a => {
          if (!idsArchivosPrevios.has(String(a.id_db))) cantArchivosNuevos++;
        }));

        datosEstado.lotes = nuevosLotes;
        datosEstado.lotes_anteriores = nuevosAnt;
        datosEstado.sin_identificar = sinIdRes.sin_identificar || [];
        datosEstado.escenas = escenasRes.escenas || [];
        datosEstado.personajes = persRes.personajes || [];
        datosEstado.ultimo_personaje = persRes.ultimo_personaje;
        datosEstado.capitulo_activo = capRes.capitulo_foco || capRes.capitulo;
        datosEstado.capitulo_foco = capRes.capitulo_foco;
        datosEstado.capitulos_abiertos = capRes.capitulos_abiertos || [];
        datosEstado.cantidad_abiertos = capRes.cantidad_abiertos || 0;
        datosEstado.alerta_olvidado = capRes.alerta_olvidado;
        datosEstado.horas_limite = capRes.horas_limite;
        datosEstado.balance_capitulo = capRes.balance;

        renderCapituloActivo();
        if (enEdicion) {
          renderLotesIncremental();
          renderLotesAnterioresIncremental();
        } else {
          renderLotes();
          renderLotesAnteriores();
        }
        renderSinIdentificar();
        restaurarEstadoUI(snap);

        if (cantArchivosNuevos > 0) {
          mostrarToastLlegada(`Llegaron ${cantArchivosNuevos} archivo(s) nuevo(s)`);
          if (document.hidden && lotesNuevosEntrantes.length > 0) {
            lotesNuevosSegundoPlano += lotesNuevosEntrantes.length;
            document.title = `(${lotesNuevosSegundoPlano}) ${TITULO_BASE}`;
          }
        }

        if (pestanaActual === 'capitulos-abiertos') {
          await cargarCapitulosAbiertos();
        } else if (pestanaActual === 'capitulos-cerrados') {
          await cargarCapitulosCerrados();
        } else if (pestanaActual === 'descartados') {
          await cargarCapitulosDescartados();
        } else if (pestanaActual === 'pendrive') {
          await cargarVistaPendrive();
        } else if (pestanaActual === 'historial') {
          await cargarHistorial();
        }
      } catch (e) {
        console.error('Error al recargar con preservación:', e);
      }
    }

    function programarSiguienteSondeo(esperaMs) {
      if (temporizadorSondeo) {
        clearTimeout(temporizadorSondeo);
        temporizadorSondeo = null;
      }
      if (REFRESCO_PANEL_SEGUNDOS <= 0) return;

      const ms = (typeof esperaMs === 'number') ? esperaMs : (reintentoEsperaSegundos * 1000);
      temporizadorSondeo = setTimeout(verificarVersionEstado, ms);
    }

    async function verificarVersionEstado() {
      if (REFRESCO_PANEL_SEGUNDOS <= 0) return;
      if (sondeoEnCurso) return;
      if (temporizadorSondeo) {
        clearTimeout(temporizadorSondeo);
        temporizadorSondeo = null;
      }

      if (document.hidden) {
        return;
      }

      if (hayModalAbierto()) {
        programarSiguienteSondeo();
        return;
      }

      sondeoEnCurso = true;
      try {
        const res = await apiFetch('/api/estado-version');
        if (pestanaActual === 'completados' || (pestanaActual === 'edicion' &&
            document.getElementById('contenedor-traslados-pendientes')?.children.length)) await cargarVistaEdicion();

        if (res.banner_pendrive) {
          if (typeof res.banner_pendrive === 'string') {
            mostrarBannerPendrive(res.banner_pendrive);
          } else if (res.banner_pendrive.mensaje) {
            mostrarBannerPendrive(res.banner_pendrive.mensaje);
          }
        } else {
          ocultarBannerPendrive();
        }

        if (desconectado) {
          desconectado = false;
          ocultarAvisoDesconexion();
          reintentoEsperaSegundos = REFRESCO_PANEL_SEGUNDOS > 0 ? REFRESCO_PANEL_SEGUNDOS : 4;
          versionActualToken = res.version;
          await recargarConPreservacion();
          programarSiguienteSondeo();
          return;
        }

        reintentoEsperaSegundos = REFRESCO_PANEL_SEGUNDOS > 0 ? REFRESCO_PANEL_SEGUNDOS : 4;

        if (versionActualToken === null) {
          versionActualToken = res.version;
        } else if (res.version !== versionActualToken) {
          versionActualToken = res.version;
          await recargarConPreservacion();
        }

        programarSiguienteSondeo();
      } catch (e) {
        console.warn('Fallo en sondeo de estado-version:', e);
        desconectado = true;
        mostrarAvisoDesconexion();
        reintentoEsperaSegundos = Math.min(reintentoEsperaSegundos * 2, 30);
        programarSiguienteSondeo(reintentoEsperaSegundos * 1000);
      } finally {
        sondeoEnCurso = false;
      }
    }

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        lotesNuevosSegundoPlano = 0;
        document.title = TITULO_BASE;
        verificarVersionEstado();
      }
    });

    window.addEventListener('focus', () => {
      lotesNuevosSegundoPlano = 0;
      document.title = TITULO_BASE;
    });

    function renderCapituloActivo() {
      const bannerActivo = document.getElementById('banner-capitulo-activo');
      const bannerSinFoco = document.getElementById('banner-sin-foco');
      const cardEmpezar = document.getElementById('card-empezar-capitulo');
      const bannerOlvidado = document.getElementById('banner-capitulo-olvidado');
      const errSpan = document.getElementById('error-capitulo-activo');
      if (errSpan) {
        errSpan.style.display = 'none';
        errSpan.innerText = '';
      }

      const capFoco = datosEstado.capitulo_foco;
      const esFoco = capFoco && capFoco.habilitado && capFoco.nombre;
      const cantAbiertos = datosEstado.cantidad_abiertos || 0;

      const badgeNav = document.getElementById('conteo-nav-abiertos');
      if (badgeNav) badgeNav.innerText = cantAbiertos;

      if (esFoco) {
        if (cardEmpezar) cardEmpezar.style.display = 'none';
        if (bannerSinFoco) bannerSinFoco.style.display = 'none';
        if (bannerActivo) {
          bannerActivo.style.display = 'flex';
          const titulo = document.getElementById('banner-capitulo-titulo');
          const subtitulo = document.getElementById('banner-capitulo-subtitulo');
          const otrosSpan = document.getElementById('banner-otros-abiertos');

          if (titulo) titulo.innerText = `Capítulo en foco: ${capFoco.personaje}/${capFoco.nombre}`;
          if (otrosSpan) {
            if (cantAbiertos > 1) {
              otrosSpan.innerText = `(+${cantAbiertos - 1} abierto(s))`;
              otrosSpan.style.display = 'inline';
            } else {
              otrosSpan.style.display = 'none';
            }
          }
          if (subtitulo) {
            const fechaTxt = capFoco.fecha_inicio ? capFoco.fecha_inicio.replace('T', ' ').slice(0, 19) : '';
            const movidos = (datosEstado.balance_capitulo && datosEstado.balance_capitulo.movidos !== undefined) ? datosEstado.balance_capitulo.movidos : (capFoco.archivos_movidos || 0);
            let textoSub = `Iniciado: ${fechaTxt} | ${movidos} archivo(s) movido(s). Todo archivo nuevo entrante se asigna a esta historia.`;
            if (capFoco.carpeta_info && capFoco.carpeta_info.ya_existia && capFoco.carpeta_info.total_archivos > 0) {
              textoSub += ` • ℹ️ ${capFoco.carpeta_info.mensaje}`;
            } else if (datosEstado.mensaje_carpeta_existente) {
              textoSub += ` • ℹ️ ${datosEstado.mensaje_carpeta_existente}`;
            }
            subtitulo.innerText = textoSub;
          }
        }
        if (bannerOlvidado) {
          bannerOlvidado.style.display = datosEstado.alerta_olvidado ? 'flex' : 'none';
          const txtOlv = document.getElementById('banner-olvidado-texto');
          if (txtOlv) txtOlv.innerText = `⚠️ ¿Sigue activo este capítulo? Lleva más de ${datosEstado.horas_limite || 12} horas abierto.`;
        }
      } else {
        if (bannerActivo) bannerActivo.style.display = 'none';
        if (bannerOlvidado) bannerOlvidado.style.display = 'none';
        if (cantAbiertos > 0) {
          if (bannerSinFoco) bannerSinFoco.style.display = 'flex';
          if (cardEmpezar) cardEmpezar.style.display = 'none';
        } else {
          if (bannerSinFoco) bannerSinFoco.style.display = 'none';
          if (cardEmpezar) {
            cardEmpezar.style.display = 'block';
            const txtNombre = document.getElementById('txt-capitulo-nombre');
            if (txtNombre && (!datosEstado.capitulo_activo || !datosEstado.capitulo_activo.nombre)) txtNombre.value = '';
          }
        }
      }
    }

    async function empezarCapitulo() {
      const selPers = document.getElementById('sel-capitulo-personaje');
      const txtNombre = document.getElementById('txt-capitulo-nombre');
      const errSpan = document.getElementById('error-capitulo-activo');

      const personaje = (selPers ? selPers.value : 'lucie').trim();
      const nombre = (txtNombre ? txtNombre.value : '').trim();

      const err = validarNombreEscena(nombre);
      if (err) {
        if (errSpan) {
          errSpan.innerText = err;
          errSpan.style.display = 'inline-block';
        }
        return;
      }
      if (errSpan) { errSpan.style.display = 'none'; }

      try {
        const res = await apiFetch('/api/capitulos/empezar', {
          method: 'POST',
          body: JSON.stringify({ personaje, nombre })
        });
        if (txtNombre) txtNombre.value = '';
        if (res && res.carpeta_info && res.carpeta_info.ya_existia && res.carpeta_info.total_archivos > 0) {
          datosEstado.mensaje_carpeta_existente = res.carpeta_info.mensaje;
        } else {
          datosEstado.mensaje_carpeta_existente = null;
        }
        await cargarDatos();
      } catch (e) {
        if (errSpan) {
          errSpan.innerText = e.message;
          errSpan.style.display = 'inline-block';
        } else {
          mostrarError(e.message);
        }
      }
    }

    async function empezarCapituloSecundario() {
      const selPers = document.getElementById('sel-nuevo-capitulo-pers');
      const txtNombre = document.getElementById('txt-nuevo-capitulo-nom');
      const errSpan = document.getElementById('error-nuevo-capitulo');

      const personaje = (selPers ? selPers.value : 'lucie').trim();
      const nombre = (txtNombre ? txtNombre.value : '').trim();

      const err = validarNombreEscena(nombre);
      if (err) {
        if (errSpan) {
          errSpan.innerText = err;
          errSpan.style.display = 'inline-block';
        }
        return;
      }
      if (errSpan) { errSpan.style.display = 'none'; }

      try {
        await apiFetch('/api/capitulos/empezar', {
          method: 'POST',
          body: JSON.stringify({ personaje, nombre })
        });
        if (txtNombre) txtNombre.value = '';
        await cargarDatos();
        await cargarCapitulosAbiertos();
      } catch (e) {
        if (errSpan) {
          errSpan.innerText = e.message;
          errSpan.style.display = 'inline-block';
        } else {
          mostrarError(e.message);
        }
      }
    }

    async function cargarCapitulosAbiertos() {
      const cont = document.getElementById('contenedor-capitulos-abiertos');
      if (!cont) return;
      try {
        const res = await apiFetch('/api/capitulos/abiertos');
        const abiertos = res.abiertos || [];
        const badgeNav = document.getElementById('conteo-nav-abiertos');
        if (badgeNav) badgeNav.innerText = abiertos.length;

        if (!abiertos.length) {
          cont.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay capítulos abiertos actualmente.</p>';
          return;
        }

        cont.innerHTML = `
          <table class="tabla-historial">
            <thead>
              <tr>
                <th style="width:12%;">Personaje</th>
                <th style="width:22%;">Capítulo</th>
                <th style="width:14%; text-align:center;">Foco</th>
                <th style="width:16%;">Fecha Inicio</th>
                <th style="width:8%; text-align:center;">Movidos</th>
                <th style="width:8%; text-align:center;">Pendientes</th>
                <th style="width:20%; text-align:center;">Acciones</th>
              </tr>
            </thead>
            <tbody>
              ${abiertos.map(c => {
                const bal = c.balance || { pendientes: 0, movidos: 0 };
                const mov = bal.movidos !== undefined ? bal.movidos : (c.archivos_movidos || 0);
                const fechaTxt = (c.fecha_inicio || '').replace('T', ' ').slice(0, 19);
                const badgeFoco = c.en_foco 
                  ? '<span class="badge" style="background:#f59e0b; color:#000; font-weight:700;">⭐ En foco</span>'
                  : '<span style="color:var(--text-muted); font-size:0.85rem;">Secundario</span>';
                
                const btnFoco = !c.en_foco
                  ? `<button class="btn-sm" onclick="ponerEnFoco(${c.id})" style="background:var(--accent); color:#000; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;" title="Poner en foco para recibir descargas nuevas">Poner en foco</button>`
                  : '';
                
                return `
                  <tr style="${c.en_foco ? 'background:rgba(99, 102, 241, 0.1);' : ''}">
                    <td><code>${escapeHTML(c.personaje)}</code></td>
                    <td><strong>${escapeHTML(c.nombre)}</strong></td>
                    <td style="text-align:center;">${badgeFoco}</td>
                    <td style="color:var(--text-muted);">${fechaTxt}</td>
                    <td style="text-align:center;"><strong>${mov}</strong></td>
                    <td style="text-align:center;">${bal.pendientes}</td>
                    <td style="text-align:center;">
                      <div style="display:flex; gap:6px; justify-content:center; align-items:center; flex-wrap:wrap;">
                        ${btnFoco}
                        <button class="btn-sm" onclick="abrirModalPlanEnvio('${escapeHTML(c.personaje)}/${escapeHTML(c.nombre)}')" style="background:#10b981; color:#000; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;" title="Enviar material al pendrive">
                          Enviar al pendrive
                        </button>
                        <button class="btn-sm" onclick="abrirModalTerminarCapitulo(${c.id})" style="background:#ef4444; color:#fff; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;">
                          Terminar
                        </button>
                        <button class="btn-sm" onclick="abrirModalDescartarCapitulo(${c.id}, '${escapeHTML(c.nombre)}', '${escapeHTML(c.personaje)}')" style="background:#4b5563; color:#fff; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;">
                          Descartar
                        </button>
                      </div>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        `;
      } catch (e) {
        cont.innerHTML = `<p style="color:var(--error); padding:16px;">Error al cargar capítulos abiertos: ${escapeHTML(e.message)}</p>`;
      }
    }

    async function ponerEnFoco(id) {
      try {
        await apiFetch('/api/capitulos/en-foco', {
          method: 'POST',
          body: JSON.stringify({ id: id })
        });
        await cargarDatos();
        await cargarCapitulosAbiertos();
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function abrirModalTerminarCapitulo(idCap) {
      try {
        capituloATerminarId = (idCap !== undefined && idCap !== null) ? idCap : ((datosEstado.capitulo_foco && datosEstado.capitulo_foco.id) || null);
        const res = await apiFetch('/api/capitulos/estado');
        const cap = (res.capitulos_abiertos || []).find(c => c.id === capituloATerminarId)
          || (res.capitulo_foco?.id === capituloATerminarId ? res.capitulo_foco : null);
        const bal = cap?.balance || res.balance || { pendientes: 0, movidos: 0 };

        if (!cap || !cap.id) {
          throw new Error('No hay un capítulo abierto para terminar. Actualizá el panel.');
        }
        capituloATerminarId = cap.id;
        datosEstado.capitulos_abiertos = res.capitulos_abiertos || [];
        if (bal.pendientes === 0) {
          await ejecutarTerminarCapitulo(false);
          return;
        }

        const cont = document.getElementById('modal-terminar-resumen');
        if (cont && cap) {
          cont.innerHTML = `
            <p style="margin-bottom:8px;">Capítulo a terminar: <strong>${escapeHTML(cap.personaje)} / ${escapeHTML(cap.nombre)}</strong></p>
            <div style="background:var(--card-alt); padding:12px; border-radius:6px; margin:12px 0;">
              <div style="margin-bottom:6px;">📁 <strong>${bal.pendientes}</strong> archivo(s) pendiente(s) en Descargas</div>
              <div>📦 <strong>${bal.movidos}</strong> archivo(s) ya movido(s) al destino</div>
            </div>
            <p style="color:var(--text-muted); font-size:0.85rem;">
              Al terminar, el capítulo queda cerrado: no se le asignará ningún archivo nuevo y lo que llegue después seguirá el circuito sin capítulo en foco.
            </p>
          `;
        }
        document.getElementById('modal-terminar-capitulo').style.display = 'flex';
      } catch (e) {
        mostrarError(e.message);
      }
    }

    function cerrarModalTerminarCapitulo() {
      document.getElementById('modal-terminar-capitulo').style.display = 'none';
      capituloATerminarId = null;
      programarSiguienteSondeo(500);
    }

    async function ejecutarTerminarCapitulo(trasMover, idCap = capituloATerminarId) {
      try {
        const payload = {
          accion: trasMover ? 'mover_pendientes' : 'sin_mover'
        };
        if (idCap === null) throw new Error('Elegí el capítulo que querés terminar.');
        payload.id = idCap;
        await apiFetch('/api/capitulos/terminar', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        cerrarModalTerminarCapitulo();
        datosEstado.capitulos_abiertos = (datosEstado.capitulos_abiertos || []).filter(c => c.id !== idCap);
        datosEstado.cantidad_abiertos = datosEstado.capitulos_abiertos.length;
        if (datosEstado.capitulo_foco?.id === idCap) {
          datosEstado.capitulo_foco = null;
          datosEstado.capitulo_activo = null;
          datosEstado.balance_capitulo = {pendientes: 0, movidos: 0};
          datosEstado.alerta_olvidado = false;
        }
        datosEstado.mensaje_carpeta_existente = null;
        renderCapituloActivo();
        await cargarDatos();
        mostrarToastLlegada('Capítulo terminado. Ya podés crear otro; su carpeta y archivos se conservan.');
        if (pestanaActual === 'capitulos-abiertos') {
          await cargarCapitulosAbiertos();
        } else if (pestanaActual === 'capitulos-cerrados') {
          await cargarCapitulosCerrados();
        }
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function posponerAlertaCapitulo() {
      try {
        await apiFetch('/api/capitulos/posponer_alerta', {
          method: 'POST',
          body: JSON.stringify({})
        });
        await cargarDatos();
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function ejecutarMoverYTerminar() {
      const cap = (datosEstado.capitulos_abiertos || []).find(c => c.id === capituloATerminarId)
        || (datosEstado.capitulo_foco?.id === capituloATerminarId ? datosEstado.capitulo_foco : null);
      if (!cap) return mostrarError('Actualizá el panel y elegí el capítulo que querés terminar.');
      const lotesCapitulo = (datosEstado.lotes || []).filter(l =>
        !l.es_anterior && l.personaje_sugerido === cap.personaje &&
        (l.escena_sugerida === cap.nombre || l.raiz_escena === `${cap.personaje}::${cap.nombre}`)
      );
      if (!lotesCapitulo.length) {
        await ejecutarTerminarCapitulo(true, cap.id);
        return;
      }
      const lotes = lotesCapitulo.map(l => {
        const seleccionados = new Set(Array.from(document.querySelectorAll(`.chk-lote-${l.lote_id}:checked`))
          .map(cb => cb.getAttribute('data-id')));
        return {lote_id: l.lote_id, personaje: cap.personaje, escena: cap.nombre,
          archivos: l.archivos.filter(a => seleccionados.has(String(a.id_db))), es_existente_descargas: false};
      }).filter(l => l.archivos.length);
      if (!lotes.length) {
        return mostrarError('No hay pendientes seleccionados de este capítulo. Podés terminar sin mover.');
      }
      try {
        const sim = await apiFetch('/api/simular-mover', {
          method: 'POST', body: JSON.stringify({lotes})
        });
        cerrarModalTerminarCapitulo();
        simulacionActiva = sim;
        loteActivoId = null;
        terminarCapituloTrasMover = {id: cap.id};
        mostrarModalSimulacion(sim);
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function cargarCapitulosCerrados() {
      const cont = document.getElementById('contenedor-capitulos-cerrados');
      if (!cont) return;
      try {
        const res = await apiFetch('/api/capitulos/cerrados');
        const cerrados = res.cerrados || [];
        if (!cerrados.length) {
          cont.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay capítulos cerrados en el historial.</p>';
          return;
        }
        cont.innerHTML = `
          <table class="tabla-historial">
            <thead>
              <tr>
                <th style="width:12%;">Personaje</th>
                <th style="width:25%;">Capítulo</th>
                <th style="width:18%;">Fecha Inicio</th>
                <th style="width:18%;">Fecha Fin</th>
                <th style="width:9%; text-align:center;">Movidos</th>
                <th style="width:18%; text-align:center;">Acción</th>
              </tr>
            </thead>
            <tbody>
              ${cerrados.map(c => `
                <tr>
                  <td><code>${escapeHTML(c.personaje)}</code></td>
                  <td><strong>${escapeHTML(c.nombre)}</strong></td>
                  <td style="color:var(--text-muted);">${(c.fecha_inicio || '').replace('T', ' ').slice(0, 19)}</td>
                  <td style="color:var(--text-muted);">${(c.fecha_fin || '').replace('T', ' ').slice(0, 19)}</td>
                  <td style="text-align:center;"><strong>${c.archivos_movidos || 0}</strong></td>
                  <td style="text-align:center;">
                    <button class="btn-sm" onclick="abrirModalPlanEnvio('${escapeHTML(c.personaje)}/${escapeHTML(c.nombre)}')" style="background:#10b981; color:#000; font-weight:600; padding:4px 8px; border-radius:4px; border:none; cursor:pointer;" title="Enviar material al pendrive">
                      Enviar al pendrive
                    </button>
                    <button class="btn-sm" onclick="reabrirCapitulo(${c.id})" style="background:var(--teal); color:#000; font-weight:600; padding:4px 10px; border-radius:4px; border:none; cursor:pointer; margin-left:6px;">
                      Reabrir
                    </button>
                    <button class="btn-sm" onclick="abrirModalDescartarCapitulo(${c.id}, '${escapeHTML(c.nombre)}', '${escapeHTML(c.personaje)}')" style="background:#4b5563; color:#fff; font-weight:600; padding:4px 10px; border-radius:4px; border:none; cursor:pointer; margin-left:6px;">
                      Descartar
                    </button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      } catch (e) {
        cont.innerHTML = `<p style="color:var(--error); padding:16px;">Error al cargar capítulos: ${escapeHTML(e.message)}</p>`;
      }
    }

    async function reabrirCapitulo(id) {
      try {
        await apiFetch('/api/capitulos/reabrir', {
          method: 'POST',
          body: JSON.stringify({ id: id })
        });
        await cargarDatos();
        mostrarPestana('lotes');
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function cargarCapitulosDescartados() {
      const cont = document.getElementById('contenedor-capitulos-descartados');
      if (!cont) return;
      try {
        const res = await apiFetch('/api/capitulos/descartados');
        const descartados = res.descartados || [];
        if (!descartados.length) {
          cont.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay capítulos descartados en cuarentena.</p>';
          return;
        }
        cont.innerHTML = `
          <table class="tabla-historial">
            <thead>
              <tr>
                <th style="width:12%;">Personaje</th>
                <th style="width:25%;">Capítulo</th>
                <th style="width:22%;">Fecha Inicio</th>
                <th style="width:22%;">Fecha Descarte</th>
                <th style="width:19%; text-align:center;">Estado</th>
              </tr>
            </thead>
            <tbody>
              ${descartados.map(c => `
                <tr>
                  <td><code>${escapeHTML(c.personaje)}</code></td>
                  <td><strong>${escapeHTML(c.nombre)}</strong></td>
                  <td style="color:var(--text-muted);">${(c.fecha_inicio || '').replace('T', ' ').slice(0, 19)}</td>
                  <td style="color:var(--text-muted);">${(c.fecha_descartado || c.fecha_fin || '').replace('T', ' ').slice(0, 19)}</td>
                  <td style="text-align:center;">
                    <span class="badge-descartado">Descartado</span>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      } catch (e) {
        cont.innerHTML = `<p style="color:var(--error); padding:16px;">Error al cargar descartados: ${escapeHTML(e.message)}</p>`;
      }
    }

    function descartarCapituloActivo() {
      const cap = datosEstado.capitulo_activo;
      if (!cap || !cap.id) {
        mostrarError("No hay capítulo activo para descartar.");
        return;
      }
      abrirModalDescartarCapitulo(cap.id, cap.nombre, cap.personaje);
    }

    async function abrirModalDescartarCapitulo(idCapitulo, nombreCapitulo, personaje) {
      try {
        const modal = document.getElementById('modal-descartar-capitulo');
        const detalles = document.getElementById('modal-descartar-detalles');
        const txtConfirm = document.getElementById('txt-confirmar-descartar');
        const lblEsperado = document.getElementById('nombre-capitulo-esperado');
        const btnConfirm = document.getElementById('btn-confirmar-descartar');
        const errSpan = document.getElementById('error-confirmar-descartar');

        txtConfirm.value = '';
        btnConfirm.disabled = true;
        btnConfirm.style.cursor = 'not-allowed';
        btnConfirm.style.opacity = '0.5';
        if (errSpan) {
          errSpan.style.display = 'none';
          errSpan.innerText = '';
        }
        if (lblEsperado) lblEsperado.innerText = nombreCapitulo || '';

        detalles.innerHTML = '<p style="color:var(--text-muted)">Calculando simulación de descarte...</p>';
        modal.style.display = 'flex';

        const sim = await apiFetch('/api/capitulos/descartar-simular', {
          method: 'POST',
          body: JSON.stringify({ id: idCapitulo })
        });
        descarteSimulacionActiva = sim;

        let notaVacio = '';
        if (!sim.carpeta_existe || sim.carpeta_vacia) {
          notaVacio = '<p style="color:#f59e0b; margin-top:8px;"><em>Nota: La carpeta no existe o está vacía. Se descartará el registro en la base de datos sin mover archivos.</em></p>';
        }

        detalles.innerHTML = `
          <p style="margin-bottom:8px;">Capítulo: <strong>${escapeHTML(sim.escena)}</strong> (${escapeHTML(sim.personaje)})</p>
          <div style="background:var(--card-alt); padding:12px; border-radius:6px; margin:12px 0; font-size:0.9rem;">
            <div>📁 <strong>Origen:</strong> <code style="word-break:break-all;">${escapeHTML(sim.origen_carpeta)}</code></div>
            <div style="margin-top:6px;">📦 <strong>Destino en cuarentena:</strong> <code style="word-break:break-all; color:var(--teal);">${escapeHTML(sim.destino_carpeta)}</code></div>
            <div style="margin-top:6px;">📊 <strong>Total archivos:</strong> ${sim.total_archivos} &bull; <strong>Peso:</strong> ${escapeHTML(sim.peso_total_fmt || '0 B')}</div>
          </div>
          ${notaVacio}
        `;
      } catch (e) {
        mostrarError(e.message);
        cerrarModalDescartarCapitulo();
      }
    }

    function validarConfirmacionDescartar() {
      const txtConfirm = document.getElementById('txt-confirmar-descartar');
      const btnConfirm = document.getElementById('btn-confirmar-descartar');
      const errSpan = document.getElementById('error-confirmar-descartar');
      if (!descarteSimulacionActiva || !txtConfirm || !btnConfirm) return;

      const esperado = (descarteSimulacionActiva.escena || '').trim();
      const ingresado = txtConfirm.value.trim();

      if (ingresado === esperado) {
        btnConfirm.disabled = false;
        btnConfirm.style.cursor = 'pointer';
        btnConfirm.style.opacity = '1';
        if (errSpan) errSpan.style.display = 'none';
      } else {
        btnConfirm.disabled = true;
        btnConfirm.style.cursor = 'not-allowed';
        btnConfirm.style.opacity = '0.5';
      }
    }

    async function ejecutarDescarteCapitulo() {
      if (!descarteSimulacionActiva) return;
      const txtConfirm = document.getElementById('txt-confirmar-descartar');
      const nombreConfirmacion = (txtConfirm ? txtConfirm.value : '').trim();
      const escena = descarteSimulacionActiva.escena;
      const pers = descarteSimulacionActiva.personaje;

      try {
        const res = await apiFetch('/api/capitulos/descartar', {
          method: 'POST',
          body: JSON.stringify({
            simulacion: descarteSimulacionActiva,
            nombre_confirmacion: nombreConfirmacion
          })
        });
        cerrarModalDescartarCapitulo();
        mostrarAvisoDescartar(pers, escena, res.id_operacion);
        await cargarDatos();
        if (pestanaActual === 'capitulos-cerrados') {
          await cargarCapitulosCerrados();
        } else if (pestanaActual === 'descartados') {
          await cargarCapitulosDescartados();
        } else if (pestanaActual === 'historial') {
          await cargarHistorial();
        }
      } catch (e) {
        const errSpan = document.getElementById('error-confirmar-descartar');
        if (errSpan) {
          errSpan.innerText = e.message;
          errSpan.style.display = 'block';
        } else {
          mostrarError(e.message);
        }
      }
    }

    function cerrarModalDescartarCapitulo() {
      const modal = document.getElementById('modal-descartar-capitulo');
      if (modal) modal.style.display = 'none';
      descarteSimulacionActiva = null;
      programarSiguienteSondeo(500);
    }

    async function guardarCapituloActivo(habilitar) {
      const selPers = document.getElementById('sel-capitulo-personaje');
      const txtNombre = document.getElementById('txt-capitulo-nombre');
      const errSpan = document.getElementById('error-capitulo-activo');

      const personaje = (selPers ? selPers.value : 'lucie').trim();
      const nombre = (txtNombre ? txtNombre.value : '').trim();

      if (habilitar) {
        const err = validarNombreEscena(nombre);
        if (err) {
          if (errSpan) {
            errSpan.innerText = err;
            errSpan.style.display = 'inline-block';
          }
          return;
        }
      }
      if (errSpan) {
        errSpan.style.display = 'none';
        errSpan.innerText = '';
      }

      try {
        await apiFetch('/api/capitulo-activo', {
          method: 'POST',
          body: JSON.stringify({ personaje, nombre, habilitado })
        });
        await cargarDatos();
      } catch (e) {
        if (errSpan) {
          errSpan.innerText = e.message;
          errSpan.style.display = 'inline-block';
        } else {
          mostrarError(e.message);
        }
      }
    }

    function esArchivoVideo(nombre) {
      if (!nombre) return false;
      const idx = nombre.lastIndexOf('.');
      if (idx === -1) return false;
      const ext = nombre.slice(idx).toLowerCase();
      return ['.mp4', '.mov', '.webm', '.m4v'].includes(ext);
    }

    function esArchivoFoto(nombre) {
      if (!nombre) return false;
      const idx = nombre.lastIndexOf('.');
      if (idx === -1) return false;
      const ext = nombre.slice(idx).toLowerCase();
      return ['.jpg', '.jpeg', '.png', '.webp'].includes(ext);
    }

    const MAX_CONCURRENT_VIDEO_LOADS = 3;
    const colaCargaVideos = [];
    let videosCargandoActivos = 0;
    let observerVideos = null;

    function inicializarLazyLoaderVideos() {
      if (typeof window === 'undefined' || typeof document === 'undefined') return;
      if (typeof IntersectionObserver === 'undefined') {
        document.querySelectorAll('video.video-thumb-lazy').forEach(v => {
          const src = v.getAttribute('data-src');
          if (src && !v.src) {
            v.preload = 'metadata';
            v.src = src;
          }
        });
        return;
      }

      if (observerVideos) {
        observerVideos.disconnect();
      }

      observerVideos = new IntersectionObserver((entries, obs) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            obs.unobserve(entry.target);
            encolarCargaVideo(entry.target);
          }
        });
      }, {
        rootMargin: '200px 0px'
      });

      document.querySelectorAll('video.video-thumb-lazy').forEach(v => {
        if (!v.src) {
          observerVideos.observe(v);
        }
      });
    }

    function encolarCargaVideo(videoEl) {
      colaCargaVideos.push(videoEl);
      procesarColaVideos();
    }

    function procesarColaVideos() {
      while (videosCargandoActivos < MAX_CONCURRENT_VIDEO_LOADS && colaCargaVideos.length > 0) {
        const v = colaCargaVideos.shift();
        if (!v) continue;
        const dataSrc = v.getAttribute('data-src');
        if (!dataSrc || v.src) continue;

        videosCargandoActivos++;

        let finalizado = false;
        const finalizar = () => {
          if (finalizado) return;
          finalizado = true;
          videosCargandoActivos--;
          v.removeEventListener('loadeddata', finalizar);
          v.removeEventListener('seeked', finalizar);
          v.removeEventListener('error', manejarError);
          procesarColaVideos();
        };

        const manejarError = () => {
          if (finalizado) return;
          v.style.display = 'none';
          const fallback = v.parentElement ? v.parentElement.querySelector('.video-thumb-fallback') : null;
          if (fallback) fallback.style.display = 'block';
          finalizar();
        };

        v.addEventListener('loadeddata', finalizar, { once: true });
        v.addEventListener('seeked', finalizar, { once: true });
        v.addEventListener('error', manejarError, { once: true });

        setTimeout(() => {
          if (!finalizado) finalizar();
        }, 5000);

        v.preload = 'metadata';
        v.src = dataSrc;
      }
    }

    function generarHtmlMiniatura(loteId, a) {
      if (a.nombre && a.nombre.toLowerCase().endsWith('.mp3')) {
        const src = a.id_media ? `/api/media?id=${encodeURIComponent(a.id_media)}` : '';
        return `<div class="audio-thumb"><span>🎵 ${escapeHTML(a.nombre)}</span><audio controls preload="none" src="${src}"></audio></div>`;
      }
      const esVid = esArchivoVideo(a.nombre);
      const mediaId = a.id_media || '';
      const fallbackSvg = `data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect width=%22100%%22 height=%22100%%22 fill=%22%23222%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23888%22 text-anchor=%22middle%22 dy=%22.3em%22>Media</text></svg>`;

      if (esVid) {
        const srcVideo = mediaId ? `/api/media?id=${mediaId}#t=0.1` : '';
        return `
          <div class="miniatura-wrap miniatura-clickable" onclick="abrirVisorMedia('${loteId}', '${mediaId}')" title="Clic para ver vista previa">
            <video class="video-thumb-lazy" data-src="${srcVideo}" muted playsinline preload="none"></video>
            <img class="video-thumb-fallback" src="${fallbackSvg}" alt="Media" style="display:none;">
          </div>
        `;
      } else {
        const srcFoto = mediaId ? `/api/media?id=${mediaId}` : (a.id_db ? `/api/miniatura?id=${a.id_db}` : fallbackSvg);
        return `
          <div class="miniatura-wrap miniatura-clickable" onclick="abrirVisorMedia('${loteId}', '${mediaId}')" title="Clic para ver vista previa">
            <img class="foto-thumb" src="${srcFoto}" loading="lazy" alt="${escapeHTML(a.nombre)}" onerror="this.onerror=null;this.src='${fallbackSvg}';">
          </div>
        `;
      }
    }

    let visorLoteIdActual = null;
    let visorListaActual = [];
    let visorIndiceActual = -1;
    let visorArchivoActual = null;

    function abrirVisorMedia(loteId, idMedia) {
      let listaArchivos = [];
      if (loteId === 'sin_identificar') {
        listaArchivos = datosEstado.sin_identificar || [];
      } else if (loteId === 'edicion_sin_editar') {
        listaArchivos = clipsParaEditar || [];
      } else if (loteId && loteId.startsWith('pendrive:')) {
        const cKey = loteId.slice(9);
        const cObj = (carpetasPendriveData || []).find(c => `${c.personaje}/${c.carpeta}` === cKey);
        if (cObj) {
          listaArchivos = (cObj.archivos || []).filter(a => a.tipo === 'video' || a.tipo === 'foto' || a.tipo === 'audio');
        }
      } else {
        const todosLotes = (datosEstado.lotes || []).concat(datosEstado.lotes_anteriores || []);
        const lote = todosLotes.find(l => l.lote_id === loteId);
        if (lote) {
          listaArchivos = lote.archivos || [];
        }
      }

      if (!listaArchivos.length) return;

      const idx = listaArchivos.findIndex(a => 
        (a.id_media && a.id_media === idMedia) || 
        (a.identificador && a.identificador === idMedia) || 
        (a.ruta_relativa && a.ruta_relativa === idMedia) || 
        (a.nombre && a.nombre === idMedia)
      );
      if (idx === -1) return;

      visorLoteIdActual = loteId;
      visorListaActual = listaArchivos;
      visorIndiceActual = idx;

      mostrarArchivoEnVisor();

      const modal = document.getElementById('modal-visor-media');
      if (modal) {
        modal.style.display = 'flex';
        modal.focus();
      }
    }

    async function mostrarErrorMedia(elemento, errBox) {
      const fuente = elemento.src;
      const mensaje = document.getElementById('visor-error-mensaje');
      let texto = 'No se pudo cargar el video. Volvé a intentarlo.';
      try {
        const respuesta = await fetch(fuente, { method: 'HEAD' });
        if (respuesta.status === 404) texto = 'El video ya no está disponible. Actualizá el listado y verificá que el pendrive siga conectado.';
        else if (respuesta.status === 403) texto = 'No se puede acceder al video. Verificá que el pendrive esté conectado y vinculado.';
        else if (!respuesta.ok) texto = `No se pudo cargar el video (HTTP ${respuesta.status}). Volvé a intentarlo.`;
        else if (elemento.error && elemento.error.code === 2) texto = 'Se interrumpió la carga del video. Verificá la conexión del pendrive y volvé a intentarlo.';
        else texto = 'El archivo está disponible, pero el navegador no pudo decodificarlo. Podés copiar la ruta y abrirlo en otro reproductor.';
      } catch (err) {
        texto = 'No se pudo conectar con la bandeja. Verificá que siga abierta y volvé a intentarlo.';
      }
      if (elemento.src !== fuente) return;
      elemento.style.display = 'none';
      if (mensaje) mensaje.innerText = texto;
      if (errBox) errBox.style.display = 'block';
    }

    function mostrarArchivoEnVisor() {
      if (visorIndiceActual < 0 || visorIndiceActual >= visorListaActual.length) return;
      const archivo = visorListaActual[visorIndiceActual];
      visorArchivoActual = archivo;
      if (!archivo.ruta) {
        archivo.ruta = archivo.ruta_relativa || archivo.identificador || archivo.nombre || '';
      }

      const hNombre = document.getElementById('visor-nombre');
      const divMeta = document.getElementById('visor-meta');
      const chk = document.getElementById('visor-chk-seleccion');
      const lblChk = document.getElementById('visor-lbl-seleccion');
      const img = document.getElementById('visor-img');
      const vid = document.getElementById('visor-video');
      const errBox = document.getElementById('visor-error-formato');
      const feedback = document.getElementById('visor-copiar-feedback');
      const navPrev = document.querySelector('.visor-nav-prev');
      const navNext = document.querySelector('.visor-nav-next');

      if (feedback) feedback.style.display = 'none';
      if (errBox) errBox.style.display = 'none';

      if (navPrev) navPrev.style.display = visorListaActual.length > 1 ? 'flex' : 'none';
      if (navNext) navNext.style.display = visorListaActual.length > 1 ? 'flex' : 'none';

      if (hNombre) hNombre.innerText = archivo.nombre || '';
      if (divMeta) {
        let loteDesc = '';
        if (visorLoteIdActual === 'sin_identificar') {
          loteDesc = 'Sin identificar';
        } else if (visorLoteIdActual === 'edicion_sin_editar') {
          loteDesc = `Para editar: ${archivo.personaje || ''} / ${archivo.capitulo || ''}`;
        } else if (visorLoteIdActual && visorLoteIdActual.startsWith('pendrive:')) {
          const cKey = visorLoteIdActual.slice(9);
          loteDesc = `Sala de espera: ${cKey}`;
        } else {
          const todosLotes = (datosEstado.lotes || []).concat(datosEstado.lotes_anteriores || []);
          const l = todosLotes.find(lot => lot.lote_id === visorLoteIdActual);
          loteDesc = l ? (l.es_anterior ? `Lote #${l.numero} (Anteriores)` : `Lote #${l.numero}`) : 'Lote';
        }
        const pesoFmt = archivo.tamanio_fmt || formatearBytes(archivo.tamanio || archivo.tamanio_bytes || archivo.tamano || 0);
        const fechaTxt = archivo.fecha_modificacion || archivo.fecha_llegada || archivo.fecha || '';
        divMeta.innerText = `${loteDesc} • ${pesoFmt}${fechaTxt ? ' • 🕒 ' + fechaTxt : ''}`;
      }

      if (chk) {
        if (visorLoteIdActual === 'sin_identificar' || visorLoteIdActual === 'edicion_sin_editar' || (visorLoteIdActual && visorLoteIdActual.startsWith('pendrive:'))) {
          if (lblChk) lblChk.style.display = 'none';
        } else {
          if (lblChk) lblChk.style.display = 'flex';
          const cbTarjeta = document.querySelector(`.chk-lote-${visorLoteIdActual}[data-id="${archivo.id_db}"]`);
          chk.checked = cbTarjeta ? cbTarjeta.checked : false;
        }
      }

      if (img) {
        img.style.display = 'none';
        img.removeAttribute('src');
      }
      if (vid) {
        vid.pause();
        vid.removeAttribute('src');
        vid.load();
        vid.style.display = 'none';
      }

      const mediaId = archivo.id_media || archivo.ruta_relativa || archivo.identificador || '';
      const srcUrl = `/api/media?id=${encodeURIComponent(mediaId)}`;

      if (esArchivoVideo(archivo.nombre) || archivo.nombre.toLowerCase().endsWith('.mp3')) {
        if (vid) {
          vid.onerror = () => mostrarErrorMedia(vid, errBox);
          vid.src = srcUrl;
          vid.style.display = 'block';
          vid.play().catch(() => {});
        }
      } else {
        if (img) {
          img.onerror = () => {
            img.style.display = 'none';
            const mensaje = document.getElementById('visor-error-mensaje');
            if (mensaje) mensaje.innerText = 'No se pudo cargar la imagen. Verificá que el archivo siga disponible.';
            if (errBox) errBox.style.display = 'block';
          };
          img.src = srcUrl;
          img.style.display = 'block';
        }
      }
    }

    function toggleSeleccionVisor(marcado) {
      if (!visorArchivoActual || !visorLoteIdActual || visorLoteIdActual === 'sin_identificar' || visorLoteIdActual.startsWith('pendrive:')) return;
      const cbTarjeta = document.querySelector(`.chk-lote-${visorLoteIdActual}[data-id="${visorArchivoActual.id_db}"]`);
      if (cbTarjeta) {
        cbTarjeta.checked = marcado;
        actualizarSeleccionLote(visorLoteIdActual);
      }
    }

    function navegarVisorMedia(delta) {
      if (!visorListaActual.length) return;
      const nuevoIdx = visorIndiceActual + delta;
      if (nuevoIdx >= 0 && nuevoIdx < visorListaActual.length) {
        visorIndiceActual = nuevoIdx;
        mostrarArchivoEnVisor();
      }
    }

    function cerrarVisorMedia() {
      const modal = document.getElementById('modal-visor-media');
      if (modal) modal.style.display = 'none';
      const vid = document.getElementById('visor-video');
      if (vid) {
        vid.pause();
        vid.removeAttribute('src');
        vid.load();
        vid.style.display = 'none';
      }
      const img = document.getElementById('visor-img');
      if (img) {
        img.removeAttribute('src');
        img.style.display = 'none';
      }
      const errBox = document.getElementById('visor-error-formato');
      if (errBox) errBox.style.display = 'none';

      visorArchivoActual = null;
      visorListaActual = [];
      visorIndiceActual = -1;
      visorLoteIdActual = null;

      programarSiguienteSondeo(500);
    }

    function copiarRutaVisor() {
      if (!visorArchivoActual || !visorArchivoActual.ruta) return;
      const ruta = visorArchivoActual.ruta;
      const fb = document.getElementById('visor-copiar-feedback');
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(ruta).then(() => {
          if (fb) {
            fb.style.display = 'inline';
            setTimeout(() => { if (fb) fb.style.display = 'none'; }, 3000);
          }
        }).catch(() => {
          if (typeof prompt !== 'undefined') prompt("Ruta del archivo:", ruta);
        });
      } else {
        if (typeof prompt !== 'undefined') prompt("Ruta del archivo:", ruta);
      }
    }

    if (typeof document !== 'undefined') {
      document.addEventListener('keydown', (e) => {
        const modal = document.getElementById('modal-visor-media');
        if (!modal || modal.style.display === 'none') return;

        if (e.key === 'Escape') {
          e.preventDefault();
          cerrarVisorMedia();
        } else if (e.key === 'ArrowLeft') {
          e.preventDefault();
          navegarVisorMedia(-1);
        } else if (e.key === 'ArrowRight') {
          e.preventDefault();
          navegarVisorMedia(1);
        }
      });
    }

    function generarHtmlCardLote(lote) {
      const esLoteAdoptado = Boolean(lote.adoptado_a_mano || (lote.archivos || []).some(a => a.adoptado_a_mano));

      const capFoco = (datosEstado.capitulo_foco && datosEstado.capitulo_foco.habilitado) ? datosEstado.capitulo_foco : 
                      ((datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado) ? datosEstado.capitulo_activo : null);
      const capsAbiertos = datosEstado.capitulos_abiertos || [];
      const nombresAbiertos = new Set(capsAbiertos.map(c => c.nombre));

      const persPre = capFoco ? capFoco.personaje : (lote.personaje_sugerido || datosEstado.ultimo_personaje || 'lucie');
      const escenaPre = esLoteAdoptado ? '' : (capFoco ? capFoco.nombre : (lote.escena_sugerida || ''));

      const persOptions = datosEstado.personajes.map(p => 
        `<option value="${p.id}" ${p.id === persPre ? 'selected' : ''}>${p.nombre}</option>`
      ).join('');

      let optFoco = '';
      if (capFoco) {
        const isSelectedFoco = (!esLoteAdoptado);
        optFoco = `<option value="${escapeHTML(capFoco.nombre)}" data-tipo="capitulo_foco" data-personaje="${escapeHTML(capFoco.personaje)}" ${isSelectedFoco ? 'selected' : ''}>[Capítulo en foco] ${escapeHTML(capFoco.nombre)}</option>`;
      }

      const optsAbiertosSecundarios = capsAbiertos
        .filter(c => !capFoco || c.id !== capFoco.id)
        .map(c => {
          const isSelected = (!esLoteAdoptado && !capFoco && c.nombre === escenaPre);
          return `<option value="${escapeHTML(c.nombre)}" data-tipo="capitulo_abierto" data-personaje="${escapeHTML(c.personaje)}" ${isSelected ? 'selected' : ''}>[Capítulo abierto] ${escapeHTML(c.personaje)}/${escapeHTML(c.nombre)}</option>`;
        })
        .join('');

      const matchAbiertoSecundario = !esLoteAdoptado && !capFoco && capsAbiertos.some(c => c.nombre === escenaPre);
      const matchOtraEscena = !esLoteAdoptado && !capFoco && (datosEstado.escenas || []).some(e => !nombresAbiertos.has(e.nombre) && e.nombre === escenaPre);
      const esNueva = !esLoteAdoptado && !capFoco && !matchAbiertoSecundario && !matchOtraEscena;

      const optElegir = esLoteAdoptado ? `<option value="" selected disabled>-- Elegir escena o capítulo --</option>` : '';
      const optNueva = `<option value="__nueva__" ${esNueva ? 'selected' : ''}>+ Crear nueva escena...</option>`;

      const otrasEscenas = (datosEstado.escenas || [])
        .filter(e => !nombresAbiertos.has(e.nombre))
        .map(e => `<option value="${escapeHTML(e.nombre)}" data-tipo="${e.tipo}" data-personaje="${escapeHTML(e.personaje || "")}" ${(matchOtraEscena && e.nombre === escenaPre) ? 'selected' : ''}>[${e.tipo === 'en_edicion' ? 'En edici?n: ' + e.personaje : e.tipo === 'descargas_alias' ? 'En Descargas' : 'Destino'}] ${escapeHTML(e.nombre)}</option>`)
        .join('');

      const escenasOptions = optElegir + optFoco + optsAbiertosSecundarios + optNueva + otrasEscenas;
      const totalArchivosLote = (lote.archivos || []).length;
      const archivosSeleccionadosIniciales = (lote.archivos || []).filter(a => !(a.duplicado && a.duplicado.es_duplicado)).length;
      const todosTildados = totalArchivosLote > 0 && archivosSeleccionadosIniciales === totalArchivosLote;
      const listoParaMover = todosTildados && !esLoteAdoptado;
      const badgeAdoptadoHeader = esLoteAdoptado ? `<span class="badge" style="background:#7c3aed; color:#fff; font-weight:600; margin-left:8px; font-size:0.75rem;">Adoptado a mano</span>` : '';

      return `
        <div class="card" id="card-${lote.lote_id}">
          <div class="card-header">
            <div style="display:flex; align-items:center; gap:10px;">
              <input type="checkbox" class="cb-lote-listo" data-lote-id="${lote.lote_id}" ${listoParaMover ? 'checked' : ''} title="Tildar para mover con 'Mover lotes listos'" onchange="seleccionarTodosLote('${lote.lote_id}', this.checked)">
              <h3>Lote #${lote.numero} (${lote.total_archivos} archivos &bull; ${formatearBytes(lote.total_bytes)})${badgeAdoptadoHeader}</h3>
            </div>
            <span style="color:var(--text-muted);font-size:0.85rem">${lote.fecha}</span>
          </div>
          <div class="lote-toolbar">
            <span id="lbl-sel-${lote.lote_id}" style="font-size:0.85rem; color:var(--text-muted);">${archivosSeleccionadosIniciales} seleccionados</span>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${lote.lote_id}', true)">Seleccionar todos</button>
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${lote.lote_id}', false)">Ninguno</button>
            </div>
          </div>
          <div class="archivos-grid">
            ${lote.archivos.map(a => {
              const esDup = Boolean(a.duplicado && a.duplicado.es_duplicado);
              const isChecked = !esDup;
              const badgeDup = esDup ? `<span class="badge-duplicado" title="${escapeHTML(a.duplicado.mensaje || 'Archivo duplicado')}">Duplicado</span>` : '';
              const badgeAdop = a.adoptado_a_mano ? `<span class="badge" style="background:#7c3aed; color:#fff; font-size:0.7rem; padding:1px 5px; border-radius:3px; margin-left:4px; font-weight:600;" title="Adoptado a mano desde Sin Identificar">Adoptado a mano</span>` : '';
              const detalleDup = esDup ? `<div class="archivo-duplicado-info" style="font-size:0.72rem; color:#ef4444; margin-top:2px;" title="${escapeHTML(a.duplicado.mensaje || '')}">${escapeHTML(a.duplicado.mensaje || 'Duplicado')}</div>` : '';
              return `
              <div class="archivo-item" title="Archivo: ${a.nombre}&#10;Fecha llegada: ${a.fecha_llegada || a.fecha || ''}&#10;Fecha modificación: ${a.fecha || ''}&#10;Tamaño: ${formatearBytes(a.tamanio)}">
                <div class="chk-container">
                  <input type="checkbox" class="chk-archivo chk-lote-${lote.lote_id}" data-id="${a.id_db}" ${isChecked ? 'checked' : ''} onchange="actualizarSeleccionLote('${lote.lote_id}')">
                </div>
                ${generarHtmlMiniatura(lote.lote_id, a)}
                <div class="archivo-meta">
                  <div class="archivo-nombre" title="${a.nombre}">${escapeHTML(a.nombre)} ${badgeDup} ${badgeAdop}</div>
                  <div class="archivo-peso">${formatearBytes(a.tamanio)}</div>
                  ${detalleDup}
                  <div class="archivo-llegada" style="font-size:0.75rem; color:var(--text-muted);" title="Fecha de llegada: ${a.fecha_llegada || a.fecha || ''}">🕒 ${a.fecha_llegada || a.fecha || ''}</div>
                </div>
              </div>
            `;}).join('')}
          </div>
          <div class="form-row">
            <label>Personaje: <select id="sel-pers-${lote.lote_id}">${persOptions}</select></label>
            <label>Escena:
              <select id="sel-escena-${lote.lote_id}" onchange="toggleNuevaEscena('${lote.lote_id}', this.value)">
                ${escenasOptions}
              </select>
            </label>
            <div class="campo-escena-wrap">
              <input type="text" id="txt-nueva-escena-${lote.lote_id}" value="${esNueva ? escapeHTML(escenaPre) : ''}" placeholder="Nombre de escena nueva" style="max-width:200px; display:${esNueva ? 'inline-block' : 'none'};" oninput="validarInputEscena('${lote.lote_id}', false)" onblur="validarInputEscena('${lote.lote_id}', true)">
              <span id="error-escena-${lote.lote_id}" class="error-inline" style="display:none;"></span>
            </div>
            <button class="btn-accion" id="btn-mover-${lote.lote_id}" onclick="iniciarMover('${lote.lote_id}')" ${archivosSeleccionadosIniciales === 0 ? 'disabled' : ''}>Mover seleccionados (${archivosSeleccionadosIniciales})</button>
          </div>
        </div>
      `;
    }

    function generarHtmlCardLoteAnterior(lote) {
      const persPre = lote.personaje_sugerido || datosEstado.ultimo_personaje || 'lucie';
      const persOptions = datosEstado.personajes.map(p => 
        `<option value="${p.id}" ${p.id === persPre ? 'selected' : ''}>${p.nombre}</option>`
      ).join('');

      const capFocoAnt = (datosEstado.capitulo_foco && datosEstado.capitulo_foco.habilitado) ? datosEstado.capitulo_foco : 
                         ((datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado) ? datosEstado.capitulo_activo : null);
      const capsAbiertosAnt = datosEstado.capitulos_abiertos || [];
      const nombresAbiertosAnt = new Set(capsAbiertosAnt.map(c => c.nombre));

      let optFocoAnt = '';
      if (capFocoAnt) {
        optFocoAnt = `<option value="${escapeHTML(capFocoAnt.nombre)}" data-tipo="capitulo_foco" data-personaje="${escapeHTML(capFocoAnt.personaje)}">[Capítulo en foco] ${escapeHTML(capFocoAnt.nombre)}</option>`;
      }

      const optsAbiertosSecundariosAnt = capsAbiertosAnt
        .filter(c => !capFocoAnt || c.id !== capFocoAnt.id)
        .map(c => `<option value="${escapeHTML(c.nombre)}" data-tipo="capitulo_abierto" data-personaje="${escapeHTML(c.personaje)}">[Capítulo abierto] ${escapeHTML(c.personaje)}/${escapeHTML(c.nombre)}</option>`)
        .join('');

      const otrasEscenasAnt = (datosEstado.escenas || [])
        .filter(e => !nombresAbiertosAnt.has(e.nombre))
        .map(e => `<option value="${escapeHTML(e.nombre)}" data-tipo="${e.tipo}" data-personaje="${escapeHTML(e.personaje || "")}">[${e.tipo === 'en_edicion' ? 'En edici?n: ' + e.personaje : e.tipo === 'descargas_alias' ? 'En Descargas' : 'Destino'}] ${escapeHTML(e.nombre)}</option>`)
        .join('');

      const escenasOptions = optFocoAnt + optsAbiertosSecundariosAnt + otrasEscenasAnt;

      return `
        <div class="card" id="card-${lote.lote_id}" style="border:1px solid #333; margin-bottom:12px;">
          <div class="card-header">
            <div style="display:flex; align-items:center; gap:10px;">
              <input type="checkbox" class="cb-lote-anterior" data-lote-id="${lote.lote_id}" title="Lote anterior al capítulo" onchange="seleccionarTodosLote('${lote.lote_id}', this.checked)">
              <h3>Lote #${lote.numero} (${lote.total_archivos} archivos &bull; ${formatearBytes(lote.total_bytes)})</h3>
            </div>
            <span style="color:var(--text-muted);font-size:0.85rem">${lote.fecha}</span>
          </div>
          <div class="lote-toolbar">
            <span id="lbl-sel-${lote.lote_id}" style="font-size:0.85rem; color:var(--text-muted);">0 seleccionados</span>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${lote.lote_id}', true)">Seleccionar todos</button>
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${lote.lote_id}', false)">Ninguno</button>
            </div>
          </div>
          <div class="archivos-grid">
            ${lote.archivos.map(a => {
              const esDup = Boolean(a.duplicado && a.duplicado.es_duplicado);
              const badgeDup = esDup ? `<span class="badge-duplicado" title="${escapeHTML(a.duplicado.mensaje || 'Archivo duplicado')}">Duplicado</span>` : '';
              const detalleDup = esDup ? `<div class="archivo-duplicado-info" style="font-size:0.72rem; color:#ef4444; margin-top:2px;" title="${escapeHTML(a.duplicado.mensaje || '')}">${escapeHTML(a.duplicado.mensaje || 'Duplicado')}</div>` : '';
              return `
              <div class="archivo-item" title="Archivo: ${a.nombre}&#10;Fecha llegada: ${a.fecha_llegada || a.fecha || ''}&#10;Fecha modificación: ${a.fecha || ''}&#10;Tamaño: ${formatearBytes(a.tamanio)}">
                <div class="chk-container">
                  <input type="checkbox" class="chk-archivo chk-lote-${lote.lote_id}" data-id="${a.id_db}" onchange="actualizarSeleccionLote('${lote.lote_id}')">
                </div>
                ${generarHtmlMiniatura(lote.lote_id, a)}
                <div class="archivo-meta">
                  <div class="archivo-nombre" title="${a.nombre}">${escapeHTML(a.nombre)} ${badgeDup}</div>
                  <div class="archivo-peso">${formatearBytes(a.tamanio)}</div>
                  ${detalleDup}
                  <div class="archivo-llegada" style="font-size:0.75rem; color:var(--text-muted);" title="Fecha de llegada: ${a.fecha_llegada || a.fecha || ''}">🕒 ${a.fecha_llegada || a.fecha || ''}</div>
                </div>
              </div>
            `;}).join('')}
          </div>
          <div class="form-row">
            <label>Personaje: <select id="sel-pers-${lote.lote_id}">${persOptions}</select></label>
            <label>Escena:
              <select id="sel-escena-${lote.lote_id}" onchange="toggleNuevaEscena('${lote.lote_id}', this.value)">
                <option value="__nueva__" selected>+ Crear nueva escena...</option>
                ${escenasOptions}
              </select>
            </label>
            <div class="campo-escena-wrap">
              <input type="text" id="txt-nueva-escena-${lote.lote_id}" value="" placeholder="Nombre de escena nueva" style="max-width:200px; display:inline-block;" oninput="validarInputEscena('${lote.lote_id}', false)" onblur="validarInputEscena('${lote.lote_id}', true)">
              <span id="error-escena-${lote.lote_id}" class="error-inline" style="display:none;"></span>
            </div>
            <button class="btn-accion" id="btn-mover-${lote.lote_id}" onclick="iniciarMover('${lote.lote_id}')" disabled>Mover seleccionados (0)</button>
          </div>
        </div>
      `;
    }

    function renderLotes() {
      const cont = document.getElementById('contenedor-lotes');
      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      if (!lotesActivos.length) {
        cont.innerHTML = '<div class="card"><p style="color:var(--text-muted)">No hay nuevos lotes de candidatos en ~/Descargas.</p></div>';
        actualizarConteoGlobalSeleccion();
        return;
      }
      cont.innerHTML = lotesActivos.map(lote => generarHtmlCardLote(lote)).join('');
      actualizarConteoGlobalSeleccion();
      inicializarLazyLoaderVideos();
    }

    function renderLotesIncremental() {
      const cont = document.getElementById('contenedor-lotes');
      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      if (!lotesActivos.length) {
        cont.innerHTML = '<div class="card"><p style="color:var(--text-muted)">No hay nuevos lotes de candidatos en ~/Descargas.</p></div>';
        actualizarConteoGlobalSeleccion();
        return;
      }
      const pVacio = cont.querySelector('p');
      if (pVacio && pVacio.innerText.includes('No hay nuevos lotes')) {
        cont.innerHTML = '';
      }

      const idsActivos = new Set(lotesActivos.map(l => l.lote_id));
      const cardsExistentes = cont.querySelectorAll('[id^="card-"]');
      cardsExistentes.forEach(card => {
        const id = card.id.replace('card-', '');
        if (!idsActivos.has(id)) {
          card.remove();
        }
      });

      lotesActivos.forEach(lote => {
        const cardExistente = document.getElementById(`card-${lote.lote_id}`);
        if (!cardExistente) {
          const divTemp = document.createElement('div');
          divTemp.innerHTML = generarHtmlCardLote(lote).trim();
          const nuevaCard = divTemp.firstElementChild;
          cont.appendChild(nuevaCard);
        }
      });
      actualizarConteoGlobalSeleccion();
      inicializarLazyLoaderVideos();
    }

    function renderLotesAnteriores() {
      const sec = document.getElementById('sec-lotes-anteriores');
      const cont = document.getElementById('contenedor-lotes-anteriores');
      const conteo = document.getElementById('conteo-lotes-anteriores');
      const titulo = document.getElementById('titulo-lotes-anteriores');
      const subtitulo = document.getElementById('subtitulo-lotes-anteriores');
      if (!sec || !cont) return;

      const capActivo = datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado ? datosEstado.capitulo_activo : null;
      const lotesAnt = datosEstado.lotes_anteriores || [];

      if (!lotesAnt.length) {
        sec.style.display = 'none';
        cont.innerHTML = '';
        if (conteo) conteo.innerText = '0';
        return;
      }

      sec.style.display = 'block';
      if (conteo) conteo.innerText = String(lotesAnt.length);

      const horasReciente = datosEstado.horas_material_reciente || 168;
      if (capActivo) {
        if (titulo) titulo.innerText = "Anteriores al capítulo";
        if (subtitulo) subtitulo.innerText = "Material descargado antes del inicio del capítulo activo. No está preasignado ni seleccionado.";
      } else {
        if (titulo) titulo.innerText = "Anteriores";
        if (subtitulo) subtitulo.innerText = `Material de más de ${horasReciente} horas: revisá antes de mover.`;
      }

      cont.innerHTML = lotesAnt.map(lote => generarHtmlCardLoteAnterior(lote)).join('');
      inicializarLazyLoaderVideos();
    }

    function renderLotesAnterioresIncremental() {
      const sec = document.getElementById('sec-lotes-anteriores');
      const cont = document.getElementById('contenedor-lotes-anteriores');
      const conteo = document.getElementById('conteo-lotes-anteriores');
      const titulo = document.getElementById('titulo-lotes-anteriores');
      const subtitulo = document.getElementById('subtitulo-lotes-anteriores');
      if (!sec || !cont) return;

      const capActivo = datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado ? datosEstado.capitulo_activo : null;
      const lotesAnt = datosEstado.lotes_anteriores || [];

      if (!lotesAnt.length) {
        sec.style.display = 'none';
        cont.innerHTML = '';
        if (conteo) conteo.innerText = '0';
        return;
      }

      sec.style.display = 'block';
      if (conteo) conteo.innerText = String(lotesAnt.length);

      const horasReciente = datosEstado.horas_material_reciente || 168;
      if (capActivo) {
        if (titulo) titulo.innerText = "Anteriores al capítulo";
        if (subtitulo) subtitulo.innerText = "Material descargado antes del inicio del capítulo activo. No está preasignado ni seleccionado.";
      } else {
        if (titulo) titulo.innerText = "Anteriores";
        if (subtitulo) subtitulo.innerText = `Material de más de ${horasReciente} horas: revisá antes de mover.`;
      }

      const idsAnt = new Set(lotesAnt.map(l => l.lote_id));
      const cardsExistentes = cont.querySelectorAll('[id^="card-"]');
      cardsExistentes.forEach(card => {
        const id = card.id.replace('card-', '');
        if (!idsAnt.has(id)) {
          card.remove();
        }
      });

      lotesAnt.forEach(lote => {
        const cardExistente = document.getElementById(`card-${lote.lote_id}`);
        if (!cardExistente) {
          const divTemp = document.createElement('div');
          divTemp.innerHTML = generarHtmlCardLoteAnterior(lote).trim();
          const nuevaCard = divTemp.firstElementChild;
          cont.appendChild(nuevaCard);
        }
      });
      inicializarLazyLoaderVideos();
    }

    function actualizarConteoGlobalSeleccion() {
      const spanConteo = document.getElementById('conteo-global-seleccion');
      if (!spanConteo) return;

      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      let totalArchivos = 0;
      let totalSeleccionados = 0;

      lotesActivos.forEach(lote => {
        totalArchivos += (lote.archivos || []).length;
        const marcados = document.querySelectorAll(`.chk-lote-${lote.lote_id}:checked`).length;
        totalSeleccionados += marcados;
      });

      spanConteo.innerText = `${totalSeleccionados} archivos seleccionados de ${totalArchivos}`;
    }

    function seleccionarTodoGlobal(marcar) {
      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      lotesActivos.forEach(lote => {
        const checkboxes = document.querySelectorAll(`.chk-lote-${lote.lote_id}`);
        checkboxes.forEach(cb => { cb.checked = marcar; });
        const cbMaestro = document.querySelector(`.cb-lote-listo[data-lote-id="${lote.lote_id}"]`);
        if (cbMaestro) cbMaestro.checked = marcar;
        actualizarSeleccionLote(lote.lote_id, false);
      });
      actualizarConteoGlobalSeleccion();
    }

    function seleccionarTodosLote(loteId, marcar) {
      const checkboxes = document.querySelectorAll(`.chk-lote-${loteId}`);
      checkboxes.forEach(cb => { cb.checked = marcar; });
      actualizarSeleccionLote(loteId);
    }

    function actualizarSeleccionLote(loteId, actualizarGlobal = true) {
      const checkboxes = document.querySelectorAll(`.chk-lote-${loteId}`);
      let marcados = 0;
      checkboxes.forEach(cb => { if (cb.checked) marcados++; });

      const lbl = document.getElementById(`lbl-sel-${loteId}`);
      if (lbl) {
        lbl.innerText = `${marcados} seleccionados`;
      }

      const btn = document.getElementById(`btn-mover-${loteId}`);
      if (btn) {
        btn.innerText = `Mover seleccionados (${marcados})`;
        btn.disabled = (marcados === 0);
      }

      const cbMaestro = document.querySelector(`.cb-lote-listo[data-lote-id="${loteId}"]`) ||
                        document.querySelector(`.cb-lote-anterior[data-lote-id="${loteId}"]`);
      if (cbMaestro) {
        cbMaestro.checked = (checkboxes.length > 0 && marcados === checkboxes.length);
      }

      if (actualizarGlobal) {
        actualizarConteoGlobalSeleccion();
      }
    }

    function validarNombreEscena(nombre) {
      if (!nombre || !nombre.trim()) {
        return "El nombre de la escena no puede estar vacío.";
      }
      const trim = nombre.trim();
      if (trim.length > 100) {
        return "El nombre no puede exceder 100 caracteres.";
      }
      if (trim.endsWith('.') || trim.endsWith(' ')) {
        return "El nombre no puede terminar en punto ni en espacio.";
      }
      if (trim.includes('..') || trim.includes('/') || trim.includes('\\\\')) {
        return "El nombre no puede contener '/', '\\\\' ni '..'.";
      }
      if (/[<>:"|?*\\x00-\\x1F]/.test(trim)) {
        return "Contiene caracteres inválidos (< > : \\\" | ? * o de control).";
      }
      const reservados = ["CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"];
      const baseNombre = trim.split('.')[0].toUpperCase();
      if (reservados.includes(trim.toUpperCase()) || reservados.includes(baseNombre)) {
        return `\\"${trim}\\" es un nombre reservado del sistema.`;
      }
      return null;
    }

    function validarInputEscena(loteId, forzarMostrarVacio = false) {
      const input = document.getElementById(`txt-nueva-escena-${loteId}`);
      const errSpan = document.getElementById(`error-escena-${loteId}`);
      if (!input || !errSpan) return true;

      const selEscena = document.getElementById(`sel-escena-${loteId}`).value;
      if (selEscena !== '__nueva__') {
        errSpan.style.display = 'none';
        errSpan.innerText = '';
        return true;
      }

      const val = input.value;
      if (!val || !val.trim()) {
        if (forzarMostrarVacio) {
          errSpan.innerText = "El nombre de la escena no puede estar vacío.";
          errSpan.style.display = 'block';
          return false;
        } else {
          errSpan.style.display = 'none';
          errSpan.innerText = '';
          return false;
        }
      }

      const error = validarNombreEscena(val);
      if (error) {
        errSpan.innerText = error;
        errSpan.style.display = 'block';
        return false;
      } else {
        errSpan.style.display = 'none';
        errSpan.innerText = '';
        return true;
      }
    }

    function toggleNuevaEscena(loteId, valor) {
      const txt = document.getElementById(`txt-nueva-escena-${loteId}`);
      const errSpan = document.getElementById(`error-escena-${loteId}`);
      const selEscena = document.getElementById(`sel-escena-${loteId}`);
      const selPers = document.getElementById(`sel-pers-${loteId}`);

      if (selEscena && selPers && selEscena.selectedIndex >= 0) {
        const opt = selEscena.options[selEscena.selectedIndex];
        const persOpt = opt ? opt.getAttribute('data-personaje') : null;
        if (persOpt) {
          selPers.value = persOpt;
        }
      }

      if (valor === '__nueva__') {
        txt.style.display = 'inline-block';
        validarInputEscena(loteId, false);
      } else {
        txt.style.display = 'none';
        if (errSpan) {
          errSpan.style.display = 'none';
          errSpan.innerText = '';
        }
      }
    }

    function renderSinIdentificar() {
      const cont = document.getElementById('contenedor-sin-identificar');
      if (!datosEstado.sin_identificar.length) {
        cont.innerHTML = '<p style="color:var(--text-muted)">No hay archivos multimedia sin clasificar.</p>';
        return;
      }
      cont.innerHTML = `
        <table>
          <thead>
            <tr><th style="width:70px;">Vista</th><th>Archivo</th><th>Tamaño</th><th>Acción</th></tr>
          </thead>
          <tbody>
            ${datosEstado.sin_identificar.map(a => `
              <tr id="row-sin-id-${a.hash}">
                <td style="padding:6px;">
                  <div style="width:60px; height:45px; border-radius:4px; overflow:hidden;">
                    ${generarHtmlMiniatura('sin_identificar', a)}
                  </div>
                </td>
                <td><span style="cursor:pointer; font-weight:500;" onclick="abrirVisorMedia('sin_identificar', '${a.id_media}')" title="Clic para vista previa">${escapeHTML(a.nombre)}</span></td>
                <td>${formatearBytes(a.tamanio)}</td>
                <td>
                  <button class="btn-accion btn-sin-id-proyecto" style="padding:4px 8px;font-size:0.75rem;" onclick="clasificarSinId('${a.hash}', true)">Del Proyecto</button>
                  <button class="btn-cancelar btn-sin-id-ignorar" style="padding:4px 8px;font-size:0.75rem;" onclick="clasificarSinId('${a.hash}', false)">Ignorar</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      inicializarLazyLoaderVideos();
    }

    async function clasificarSinId(hash, esProyecto) {
      const arch = (datosEstado.sin_identificar || []).find(x => x.hash === hash);
      const ruta = arch ? arch.ruta : '';
      const nombre = arch ? arch.nombre : 'Archivo';

      // Salida visual inmediata de la fila
      const fila = document.getElementById(`row-sin-id-${hash}`);
      if (fila) {
        fila.remove();
        const tbody = document.querySelector('#contenedor-sin-identificar tbody');
        if (tbody && !tbody.children.length) {
          document.getElementById('contenedor-sin-identificar').innerHTML = '<p style="color:var(--text-muted)">No hay archivos multimedia sin clasificar.</p>';
        }
      }

      // Remover del estado local en memoria
      datosEstado.sin_identificar = (datosEstado.sin_identificar || []).filter(x => x.hash !== hash);

      // Aviso con enlace y Deshacer
      mostrarAvisoSinIdentificar(nombre, hash, ruta, esProyecto);

      try {
        await apiFetch('/api/clasificar-sin-identificar', {
          method: 'POST',
          body: JSON.stringify({ hash, ruta, es_proyecto: esProyecto })
        });
        await cargarDatos();
      } catch (e) {
        mostrarError(`Error al clasificar: ${e.message}`);
        await cargarDatos();
      }
    }

    async function cargarHistorial() {
      const cont = document.getElementById('contenedor-historial');
      cont.innerHTML = '<p style="color:var(--text-muted)">Cargando historial...</p>';
      try {
        const res = await apiFetch('/api/historial');
        historialActual = res.historial || [];
        renderHistorial();
      } catch (e) {
        cont.innerHTML = '<p style="color:var(--danger)">Error al cargar historial.</p>';
        mostrarError(e.message);
      }
    }

    function renderHistorial() {
      const cont = document.getElementById('contenedor-historial');
      const btnUltimo = document.getElementById('btn-deshacer-ultimo-lote');

      if (!historialActual.length) {
        cont.innerHTML = '<p style="color:var(--text-muted)">No hay movimientos registrados en la bitácora aún.</p>';
        if (btnUltimo) btnUltimo.disabled = true;
        return;
      }

      const primerReversible = historialActual.find(m => m.estado === 'movido' || m.estado === 'descartado');
      if (btnUltimo) {
        btnUltimo.disabled = !primerReversible;
      }

      cont.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Archivo</th>
              <th>Origen</th>
              <th>Destino</th>
              <th>Estado</th>
              <th>Acción</th>
            </tr>
          </thead>
          <tbody>
            ${historialActual.map(m => `
              <tr>
                <td><small>${m.fecha}</small></td>
                <td><strong>${m.archivo}</strong></td>
                <td><small title="${m.origen}">${m.origen}</small></td>
                <td><small style="color:var(--teal)" title="${m.destino}">${m.destino}</small></td>
                <td>
                  <span class="${m.estado === 'deshecho' ? 'badge-deshecho' : (m.estado === 'descartado' ? 'badge-descartado' : 'badge-movido')}">
                    ${m.estado}
                  </span>
                </td>
                <td>
                  ${(m.estado === 'movido' || m.estado === 'descartado') ? `
                    <button class="btn-sm" onclick="deshacerMovimiento('${m.id_operacion}')">
                      Deshacer
                    </button>
                  ` : `
                    <span style="color:var(--text-muted)">-</span>
                  `}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }

    async function deshacerMovimiento(idOperacion) {
      if (!idOperacion) return;
      if (!confirm("¿Confirmás deshacer esta operación? Los archivos serán restaurados a su ubicación original.")) {
        return;
      }
      try {
        const res = await apiFetch('/api/deshacer', {
          method: 'POST',
          body: JSON.stringify({ id_operacion: idOperacion })
        });
        if (operacionAvisoActual === idOperacion) {
          cerrarAviso();
        }
        await cargarHistorial();
        await cargarDatos();
        if (pestanaActual === 'descartados') {
          await cargarCapitulosDescartados();
        } else if (pestanaActual === 'capitulos-cerrados') {
          await cargarCapitulosCerrados();
        }
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function deshacerUltimoLote() {
      const primerReversible = historialActual.find(m => m.estado === 'movido' || m.estado === 'descartado');
      if (!primerReversible) {
        mostrarError("No hay operaciones pendientes de deshacer en el historial.");
        return;
      }
      await deshacerMovimiento(primerReversible.id_operacion);
    }

    async function iniciarMover(loteId) {
      const lote = datosEstado.lotes.find(l => l.lote_id === loteId) ||
                   (datosEstado.lotes_anteriores && datosEstado.lotes_anteriores.find(l => l.lote_id === loteId));
      if (!lote) return;

      const checkboxes = document.querySelectorAll(`.chk-lote-${loteId}:checked`);
      const idsSeleccionados = new Set(Array.from(checkboxes).map(cb => cb.getAttribute('data-id')));
      const archivosSeleccionados = lote.archivos.filter(a => idsSeleccionados.has(String(a.id_db)));

      if (!archivosSeleccionados.length) {
        mostrarError("Debés seleccionar al menos un archivo para mover.");
        return;
      }

      const selPers = document.getElementById(`sel-pers-${loteId}`).value;
      const selEscena = document.getElementById(`sel-escena-${loteId}`).value;
      let nombreEscena = selEscena;
      let esExistenteDescargas = false;

      if (!selEscena || selEscena.trim() === '') {
        mostrarError("Debés elegir o escribir una escena o capítulo para el lote.");
        const sel = document.getElementById(`sel-escena-${loteId}`);
        if (sel) sel.focus();
        return;
      }

      if (selEscena === '__nueva__') {
        if (!validarInputEscena(loteId, true)) {
          const txt = document.getElementById(`txt-nueva-escena-${loteId}`);
          if (txt) txt.focus();
          return;
        }
        nombreEscena = document.getElementById(`txt-nueva-escena-${loteId}`).value.trim();
      } else {
        const opt = document.querySelector(`#sel-escena-${loteId} option[value="${selEscena}"]`);
        if (opt && opt.getAttribute('data-tipo') === 'descargas_alias') {
          esExistenteDescargas = true;
        }
      }

      try {
        const sim = await apiFetch('/api/simular-mover', {
          method: 'POST',
          body: JSON.stringify({
            archivos: archivosSeleccionados,
            personaje: selPers,
            escena: nombreEscena,
            es_existente_descargas: esExistenteDescargas
          })
        });

        simulacionActiva = sim;
        loteActivoId = loteId;
        mostrarModalSimulacion(sim);
      } catch (e) {
        mostrarError(e.message);
      }
    }

    async function simularMoverLotesListos() {
      const cbs = document.querySelectorAll('#contenedor-lotes .cb-lote-listo:checked');
      if (!cbs.length) {
        mostrarError("No hay ningún lote seleccionado para mover.");
        return;
      }

      const lotesPayload = [];
      for (const cb of cbs) {
        const loteId = cb.getAttribute('data-lote-id');
        const lote = datosEstado.lotes.find(l => l.lote_id === loteId);
        if (!lote || lote.es_anterior) continue;

        const chkArchivos = document.querySelectorAll(`.chk-lote-${loteId}:checked`);
        const idsSel = new Set(Array.from(chkArchivos).map(c => c.getAttribute('data-id')));
        const archivosSel = lote.archivos.filter(a => idsSel.has(String(a.id_db)));
        if (!archivosSel.length) {
          continue;
        }

        const selPers = document.getElementById(`sel-pers-${loteId}`).value;
        const selEscena = document.getElementById(`sel-escena-${loteId}`).value;
        let nombreEscena = selEscena;
        let esExistenteDescargas = false;

        if (!selEscena || selEscena.trim() === '') {
          mostrarError("Debés elegir o escribir una escena o capítulo para todos los lotes seleccionados.");
          const sel = document.getElementById(`sel-escena-${loteId}`);
          if (sel) sel.focus();
          return;
        }

        if (selEscena === '__nueva__') {
          if (!validarInputEscena(loteId, true)) {
            const txt = document.getElementById(`txt-nueva-escena-${loteId}`);
            if (txt) txt.focus();
            return;
          }
          nombreEscena = document.getElementById(`txt-nueva-escena-${loteId}`).value.trim();
        } else {
          const opt = document.querySelector(`#sel-escena-${loteId} option[value="${selEscena}"]`);
          if (opt && opt.getAttribute('data-tipo') === 'descargas_alias') {
            esExistenteDescargas = true;
          }
        }

        lotesPayload.push({
          lote_id: loteId,
          archivos: archivosSel,
          personaje: selPers,
          escena: nombreEscena,
          es_existente_descargas: esExistenteDescargas
        });
      }

      if (!lotesPayload.length) {
        mostrarError("No hay archivos seleccionados en los lotes tildados.");
        return;
      }

      try {
        const sim = await apiFetch('/api/simular-mover', {
          method: 'POST',
          body: JSON.stringify({ lotes: lotesPayload })
        });
        simulacionActiva = sim;
        loteActivoId = null;
        mostrarModalSimulacion(sim);
      } catch (e) {
        mostrarError(e.message);
      }
    }

    function formatearDestinoCliente(m) {
      const rel = (m.destino_relativo || m.destino || '').replace(/\\\\/g, '/');
      return escapeHTML(rel);
    }

    function mostrarModalSimulacion(sim) {
      const cont = document.getElementById('simulacion-contenido');
      if (sim.html) {
        cont.innerHTML = sim.html;
      } else {
        const alertaOtro = sim.hay_otro_tipo ? `
          <div style="margin:8px 0 14px 0; padding:10px 14px; background:rgba(234, 179, 8, 0.15); border:1px solid #eab308; border-radius:6px; color:#fde047; font-size:0.9rem;">
            <strong>⚠️ Archivo no multimedia detectado:</strong> Contiene archivos con extensión distinta a fotos o videos. Se moverán a la raíz de la escena conservando su nombre original sin sobreescritura.
          </div>
        ` : '';
        cont.innerHTML = `
          ${alertaOtro}
          <p><strong>Personaje:</strong> ${escapeHTML(sim.personaje || '')} | <strong>Escena:</strong> ${escapeHTML(sim.escena || '')} ${sim.es_existente_descargas ? '(En Descargas)' : ''}</p>
          <table class="modal-tabla">
            <thead>
              <tr>
                <th style="width:35%;">Archivo (Renombrado)</th>
                <th style="width:30%;">Origen</th>
                <th style="width:35%;">Destino</th>
              </tr>
            </thead>
            <tbody>
              ${sim.movimientos.map(m => `
                <tr>
                  <td><strong>${escapeHTML(m.nombre_original || m.origen.split('/').pop())}</strong> &rarr; <span class="badge-renombrado" style="color:${m.es_otro_tipo ? 'var(--text-warning, #f59e0b)' : 'var(--accent-primary, #60a5fa)'}; font-weight:600;">${escapeHTML(m.nombre_nuevo || m.destino.split('/').pop())}${m.es_otro_tipo ? ' (sin renombrar)' : ''}</span></td>
                  <td class="ruta-celda" title="${escapeHTML(m.origen)}"><small style="color:var(--text-muted)">${escapeHTML(m.origen)}</small></td>
                  <td class="ruta-celda destino-celda" title="${escapeHTML(m.destino)}" data-destino="${escapeHTML(m.destino)}">${formatearDestinoCliente(m)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      }
      document.getElementById('modal-simulacion').style.display = 'flex';
      document.getElementById('btn-ejecutar-mover').onclick = ejecutarMoverLote;
    }

    function cerrarModal() {
      document.getElementById('modal-simulacion').style.display = 'none';
      simulacionActiva = null;
      loteActivoId = null;
      terminarCapituloTrasMover = null;
      programarSiguienteSondeo(500);
    }

    async function ejecutarMoverLote() {
      if (!simulacionActiva) return;
      const simulacion = simulacionActiva;
      const capituloTrasMover = terminarCapituloTrasMover;
      try {
        let bodyReq;
        if (simulacionActiva.es_multilote) {
          bodyReq = { simulacion: simulacionActiva };
        } else {
          if (!loteActivoId) return;
          bodyReq = { simulacion: simulacionActiva, lote_id: loteActivoId };
        }

        const res = await apiFetch('/api/mover-lote', {
          method: 'POST',
          body: JSON.stringify(bodyReq)
        });
        cerrarModal();

        if (capituloTrasMover) {
          await ejecutarTerminarCapitulo(true, capituloTrasMover.id);
        }

        if (res.es_multilote) {
          const primerRes = (res.resultados && res.resultados.length > 0) ? res.resultados[0] : null;
          mostrarAvisoMover(
            res.total_movidos,
            primerRes ? primerRes.personaje : 'varios',
            primerRes ? (res.resultados.length > 1 ? `${primerRes.escena} y otros` : primerRes.escena) : 'lotes',
            res.id_operacion || res.ultimo_id_operacion
          );
        } else {
          mostrarAvisoMover(
            res.total_movidos,
            res.personaje || simulacion.personaje,
            res.escena || simulacion.escena,
            res.id_operacion
          );
        }

        await cargarDatos();
        if (pestanaActual === 'historial') {
          await cargarHistorial();
        }
      } catch (e) {
        mostrarError(e.message);
      }
    }

    function formatearBytes(b) {
      if (b < 1024) return b + ' B';
      if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
      if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
      return (b / 1073741824).toFixed(1) + ' GB';
    }

    function iniciarEnvioCapituloActivo() {
      const cap = datosEstado.capitulo_foco || datosEstado.capitulo_activo;
      if (!cap || !cap.nombre) {
        mostrarError("No hay un capítulo activo en foco para enviar.");
        return;
      }
      abrirModalPlanEnvio(`${cap.personaje}/${cap.nombre}`);
    }

    let planEnvioActivo = null;
    let revisionPlanEnvio = 0;

    function opcionesArchivoExistente(archivo) {
      if (!archivo.id_archivo) return '';
      return `<div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:6px;">
        <button type="button" class="btn-sm" data-envio-archivo="${escapeHTML(archivo.id_archivo)}" data-envio-accion="renombrar">Renombrar y agregar</button>
        <button type="button" class="btn-sm" data-envio-archivo="${escapeHTML(archivo.id_archivo)}" data-envio-accion="omitir">No agregar</button>
      </div>`;
    }

    async function resolverColisionPendrive(id, accion) {
      if (!planEnvioActivo) return;
      const seleccion = planEnvioActivo.carpetas_seleccionadas;
      const resoluciones = {...(planEnvioActivo.resoluciones_colisiones || {}), [id]: accion};
      await abrirModalPlanEnvio(seleccion, resoluciones);
    }

    async function abrirModalPlanEnvio(capitulo = null, resoluciones = {}) {
      const revision = ++revisionPlanEnvio;
      try {
        const modal = document.getElementById('modal-plan-envio');
        const cont = document.getElementById('contenido-plan-envio');
        const btnConfirm = document.getElementById('btn-confirmar-envio-pendrive');

        planEnvioActivo = null;
        btnConfirm.disabled = true;
        btnConfirm.style.cursor = 'not-allowed';
        btnConfirm.style.opacity = '0.5';

        cont.innerHTML = '<p style="color:var(--text-muted); padding:20px 0;">Calculando simulación de envío y verificando pendrive...</p>';
        modal.style.display = 'flex';

        let body = {};
        if (Array.isArray(capitulo)) {
          body = { carpetas: capitulo };
        } else if (typeof capitulo === 'string' && capitulo.trim()) {
          body = { carpetas: [capitulo.trim()] };
        }
        if (Object.keys(resoluciones).length) body.resoluciones_colisiones = resoluciones;
        const sim = await apiFetch('/api/pendrive/envio-simular', {
          method: 'POST',
          body: JSON.stringify(body)
        });

        if (revision !== revisionPlanEnvio) return;
        planEnvioActivo = sim;

        const pendientes = sim.archivos_a_copiar || sim.archivos || [];
        const archivos = [...pendientes, ...(sim.archivos_conflictos || []), ...(sim.archivos_bloqueados || [])];
        const pen = sim.pendrive || sim;
        let alertasHtml = '';
        if ((sim.archivos_conflictos || []).length || (sim.archivos_omitidos || []).some(a => a.estado === 'ya_enviado')) {
          alertasHtml += '<div role="alert" style="padding:12px; border:1px solid var(--teal); margin-bottom:12px;"><strong>Estos archivos ya existen en el pendrive.</strong> Elegí «Renombrar y agregar» para conservar ambas versiones o «No agregar». El plan mostrará el nombre nuevo antes de confirmar.</div>';
        }
        if (sim.motivo_bloqueo || sim.error) {
          alertasHtml += `<p role="status" style="color:var(--danger)">${escapeHTML(sim.motivo_bloqueo || sim.error)}</p>`;
        }
        if (sim.capitulo_abierto) {
          alertasHtml += `
            <div style="background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; color:#fef3c7; padding:10px 14px; border-radius:6px; margin-bottom:12px; font-weight:500;">
              ⚠️ <strong>Atención:</strong> Uno o más capítulos seleccionados siguen abiertos en el panel; podrían recibirse más archivos luego.
            </div>
          `;
        }

        if (sim.advertencias && sim.advertencias.length > 0) {
          alertasHtml += `
            <div style="background:rgba(207, 102, 121, 0.15); border:1px solid var(--danger); color:var(--danger); padding:10px 14px; border-radius:6px; margin-bottom:12px; font-size:0.9rem;">
              <strong>Advertencias del sistema:</strong>
              <ul style="margin:6px 0 0 18px;">
                ${sim.advertencias.map(a => `<li>${escapeHTML(a)}</li>`).join('')}
              </ul>
            </div>
          `;
        }

        if (sim.archivos_omitidos && sim.archivos_omitidos.length > 0) {
          alertasHtml += `
            <div style="background:rgba(14, 165, 233, 0.15); border:1px solid #0ea5e9; color:#bae6fd; padding:10px 14px; border-radius:6px; margin-bottom:12px; font-size:0.9rem;">
              <strong>ℹ️ Archivos que no se agregarán:</strong>
              <ul style="margin:6px 0 0 18px;">
                ${sim.archivos_omitidos.map(o => `<li><code>${escapeHTML(o.nombre)}</code>: ${escapeHTML(o.aviso || o.motivo || o.estado || "Ya enviado")}${["ya_enviado", "omitido_usuario"].includes(o.estado) ? opcionesArchivoExistente(o) : ""}</li>`).join('')}
              </ul>
            </div>
          `;
        }

        const infoPendrive = `
          <div style="display:flex; flex-wrap:wrap; gap:16px; background:var(--card-alt); padding:12px 16px; border-radius:6px; margin-bottom:14px; font-size:0.85rem;">
            <div><strong>Pendrive ID:</strong> <code>${escapeHTML((sim.pendrive_id || '').slice(0, 8))}...</code></div>
            <div><strong>Punto montaje:</strong> <code>${escapeHTML(sim.punto_montaje || '')}</code></div>
            <div><strong>Filesystem:</strong> <code>${escapeHTML(pen.sistema_archivos || '')}</code></div>
            <div><strong>Espacio libre:</strong> ${escapeHTML(sim.espacio_libre_fmt || (pen.espacio_libre_bytes == null ? 'No disponible' : formatearBytes(pen.espacio_libre_bytes)))} (Margen: ${escapeHTML(sim.margen_libre_fmt || (pen.margen_libre_bytes == null ? 'No disponible' : formatearBytes(pen.margen_libre_bytes)))})</div>
            <div><strong>Total a enviar:</strong> <strong>${sim.total_archivos_a_enviar ?? pendientes.length} archivo(s)</strong> (${escapeHTML(sim.bytes_a_enviar_fmt || '0 B')})</div>
          </div>
        `;

        let tablaArchivos = '';
        if (archivos.length > 0) {
          tablaArchivos = `
            <table class="modal-tabla">
              <thead>
                <tr>
                  <th style="width:25%;">Archivo</th>
                  <th style="width:12%;">Tipo</th>
                  <th style="width:13%;">Tamaño</th>
                  <th style="width:35%;">Destino relativo en pendrive</th>
                  <th style="width:15%;">Estado</th>
                </tr>
              </thead>
              <tbody>
                ${archivos.map(a => {
                  const tagTipo = a.tipo === 'audio' ? '<span class="tag-tipo">AUDIO</span>' : ['video', 'crudo'].includes(a.tipo) ? '<span class="tag-tipo tag-video">VIDEO</span>' : '<span class="tag-tipo tag-imagen">IMAGEN</span>';
                  const bloqueado = a.conflicto || ['conflicto', 'bloqueado_fat32'].includes(a.estado);
                  const badgeEstado = bloqueado
                    ? `<span style="color:var(--danger); font-weight:bold;">${escapeHTML(a.aviso || 'Conflicto (hash distinto)')}</span>`
                    : '<span style="color:var(--teal); font-weight:600;">Listo para enviar</span>';
                  return `
                    <tr style="${bloqueado ? 'background:rgba(207, 102, 121, 0.1);' : ''}">
                      <td><strong>${escapeHTML(a.nombre)}</strong>${bloqueado || a.nombre_destino ? opcionesArchivoExistente(a) : ""}</td>
                      <td>${tagTipo}</td>
                      <td>${escapeHTML(a.tamanio_fmt || formatearBytes(a.tamanio_bytes))}</td>
                      <td class="ruta-celda"><code style="color:var(--teal)">${escapeHTML(a.ruta_relativa_pendrive || a.destino_relativo)}</code></td>
                      <td>${badgeEstado}</td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          `;
        } else {
          tablaArchivos = '<p style="color:var(--text-muted); padding:16px 0;">No hay archivos pendientes de transferir en los capítulos seleccionados.</p>';
        }

        cont.innerHTML = alertasHtml + infoPendrive + tablaArchivos;
        cont.querySelectorAll('[data-envio-archivo]').forEach(boton => {
          boton.addEventListener('click', () => resolverColisionPendrive(boton.dataset.envioArchivo, boton.dataset.envioAccion));
        });

        if (sim.puede_enviar && sim.total_archivos_a_enviar > 0) {
          btnConfirm.disabled = false;
          btnConfirm.style.cursor = 'pointer';
          btnConfirm.style.opacity = '1';
        } else {
          btnConfirm.disabled = true;
          btnConfirm.style.cursor = 'not-allowed';
          btnConfirm.style.opacity = '0.5';
        }
      } catch (e) {
        if (revision !== revisionPlanEnvio) return;
        mostrarError(e.message);
        cerrarModalPlanEnvio();
      }
    }

    function cerrarModalPlanEnvio() {
      revisionPlanEnvio += 1;
      const modal = document.getElementById('modal-plan-envio');
      if (modal) modal.style.display = 'none';
      planEnvioActivo = null;
      programarSiguienteSondeo(500);
    }

    async function confirmarEnvioPendrive() {
      if (!planEnvioActivo || !planEnvioActivo.puede_enviar) return;
      const btn = document.getElementById('btn-confirmar-envio-pendrive');
      if (btn) {
        btn.disabled = true;
        btn.innerText = 'Enviando...';
      }
      try {
        const res = await apiFetch('/api/pendrive/envio', {
          method: 'POST',
          body: JSON.stringify({ simulacion: planEnvioActivo })
        });
        cerrarModalPlanEnvio();
        mostrarToastLlegada(`Envío exitoso: ${res.total_archivos_enviados} archivo(s) transferidos al pendrive`);
        await cargarDatos();
        if (pestanaActual === 'pendrive') {
          await cargarVistaPendrive();
        } else if (pestanaActual === 'historial') {
          await cargarHistorial();
        }
      } catch (e) {
        mostrarError(`Error al enviar material al pendrive: ${e.message}`);
        if (btn) {
          btn.disabled = false;
          btn.innerText = 'Confirmar y enviar';
        }
      }
    }

    let carpetasPendriveData = [];
    let estadoPendriveActual = null;
    window.carpetasPendriveSeleccionadas = window.carpetasPendriveSeleccionadas || new Set();
    window.carpetasPendriveInicializadas = window.carpetasPendriveInicializadas || false;
    window.carpetasPendriveDesplegadas = window.carpetasPendriveDesplegadas || new Set();

    function seleccionarTodasCarpetasPendrive() {
      if (!window.carpetasPendriveSeleccionadas) window.carpetasPendriveSeleccionadas = new Set();
      carpetasPendriveData.forEach(c => {
        window.carpetasPendriveSeleccionadas.add(`${c.personaje}/${c.carpeta}`);
      });
      actualizarEstadoCheckboxesPendrive();
    }

    function seleccionarNingunaCarpetasPendrive() {
      if (window.carpetasPendriveSeleccionadas) {
        window.carpetasPendriveSeleccionadas.clear();
      }
      actualizarEstadoCheckboxesPendrive();
    }

    function toggleSeleccionCarpetaPendrive(carpetaKey, marcado) {
      if (!window.carpetasPendriveSeleccionadas) window.carpetasPendriveSeleccionadas = new Set();
      if (marcado) {
        window.carpetasPendriveSeleccionadas.add(carpetaKey);
      } else {
        window.carpetasPendriveSeleccionadas.delete(carpetaKey);
      }
      actualizarEstadoCheckboxesPendrive();
    }

    function toggleSeleccionarTodasCarpetasCheckbox(marcado) {
      if (marcado) {
        seleccionarTodasCarpetasPendrive();
      } else {
        seleccionarNingunaCarpetasPendrive();
      }
    }

    function toggleVerArchivosCarpeta(safeKey) {
      const fila = document.getElementById(`fila-archivos-${safeKey}`);
      const btn = document.getElementById(`btn-toggle-archivos-${safeKey}`);
      if (!fila) return;
      const estaVisible = (fila.style.display !== 'none');
      if (estaVisible) {
        fila.style.display = 'none';
        if (window.carpetasPendriveDesplegadas) window.carpetasPendriveDesplegadas.delete(safeKey);
        if (btn) btn.innerText = btn.innerText.replace('Ocultar archivos', 'Ver archivos');
      } else {
        fila.style.display = 'table-row';
        if (window.carpetasPendriveDesplegadas) window.carpetasPendriveDesplegadas.add(safeKey);
        if (btn) btn.innerText = btn.innerText.replace('Ver archivos', 'Ocultar archivos');
      }
    }

    function enviarCarpetasSeleccionadasPendrive() {
      if (!window.carpetasPendriveSeleccionadas || window.carpetasPendriveSeleccionadas.size === 0) {
        mostrarError("No seleccionaste ninguna carpeta para enviar.");
        return;
      }
      abrirModalPlanEnvio(Array.from(window.carpetasPendriveSeleccionadas));
    }

    function actualizarEstadoCheckboxesPendrive() {
      const cbs = document.querySelectorAll('.chk-carpeta-pendrive');
      let cantMarcadas = 0;
      cbs.forEach(cb => {
        const k = cb.getAttribute('data-carpeta-key');
        if (window.carpetasPendriveSeleccionadas && window.carpetasPendriveSeleccionadas.has(k)) {
          cb.checked = true;
          cantMarcadas++;
        } else {
          cb.checked = false;
        }
      });

      const chkMaestro = document.getElementById('chk-maestro-carpetas-pendrive');
      if (chkMaestro) {
        if (cbs.length > 0 && cantMarcadas === cbs.length) {
          chkMaestro.checked = true;
          chkMaestro.indeterminate = false;
        } else if (cantMarcadas > 0 && cantMarcadas < cbs.length) {
          chkMaestro.checked = false;
          chkMaestro.indeterminate = true;
        } else {
          chkMaestro.checked = false;
          chkMaestro.indeterminate = false;
        }
      }

      const btnEnviar = document.getElementById('btn-enviar-seleccionadas-pendrive');
      if (btnEnviar) {
        btnEnviar.innerText = `Enviar seleccionadas (${cantMarcadas})`;
        const puedeEnviar = estadoPendriveActual && estadoPendriveActual.conectado && !estadoPendriveActual.sin_respuesta;
        if (!puedeEnviar) {
          btnEnviar.disabled = true;
          btnEnviar.style.opacity = '0.5';
          btnEnviar.style.cursor = 'not-allowed';
          if (estadoPendriveActual && estadoPendriveActual.sin_respuesta) {
            btnEnviar.title = "El pendrive no responde a las lecturas.";
          } else if (estadoPendriveActual && estadoPendriveActual.estado_unidad === 'detectada_sin_montar') {
            btnEnviar.title = "Unidad removible detectada sin montar. Hacé clic en 'Montar unidad' para acceder a ella.";
          } else if (estadoPendriveActual && estadoPendriveActual.unidad_candidata) {
            btnEnviar.title = "Unidad candidata detectada sin vincular. Hacé clic en 'Vincular pendrive' para configurarla.";
          } else {
            btnEnviar.title = "No hay ningún pendrive vinculado conectado.";
          }
        } else if (cantMarcadas === 0) {
          btnEnviar.disabled = true;
          btnEnviar.style.opacity = '0.5';
          btnEnviar.style.cursor = 'not-allowed';
          btnEnviar.title = "Seleccioná al menos una carpeta para enviar";
        } else {
          btnEnviar.disabled = false;
          btnEnviar.style.opacity = '1';
          btnEnviar.style.cursor = 'pointer';
          btnEnviar.title = `Enviar ${cantMarcadas} carpeta(s) al pendrive`;
        }
      }
    }

    async function cargarVistaPendrive() {
      const contEstado = document.getElementById('contenedor-estado-pendrive');
      const contCaps = document.getElementById('contenedor-capitulos-pendrive');
      const cardPart = document.getElementById('card-part-pendrive');
      const contPart = document.getElementById('contenedor-part-pendrive');
      const contHist = document.getElementById('contenedor-historial-pendrive');
      const btnVincular = document.getElementById('btn-vincular-pendrive');

      if (!contEstado) return;

      try {
        const [carpetasRes, estadoPen, histRes] = await Promise.all([
          apiFetch('/api/pendrive/carpetas').catch(e => ({ carpetas: [], error: e.message })),
          apiFetch('/api/pendrive/estado').catch(e => ({ sin_respuesta: true, error: e.message })),
          apiFetch('/api/historial').catch(() => ({ historial: [] }))
        ]);

        estadoPendriveActual = estadoPen;
        carpetasPendriveData = carpetasRes.carpetas || [];

        // Inicialización o poda de selecciones
        if (!window.carpetasPendriveInicializadas) {
          window.carpetasPendriveSeleccionadas = new Set();
          carpetasPendriveData.forEach(c => {
            if (!c.es_heredada && (c.pendientes_conteo > 0 || c.total_archivos > 0)) {
              window.carpetasPendriveSeleccionadas.add(`${c.personaje}/${c.carpeta}`);
            }
          });
          window.carpetasPendriveInicializadas = true;
        } else {
          const keysActuales = new Set(carpetasPendriveData.map(c => `${c.personaje}/${c.carpeta}`));
          for (const k of Array.from(window.carpetasPendriveSeleccionadas)) {
            if (!keysActuales.has(k)) {
              window.carpetasPendriveSeleccionadas.delete(k);
            }
          }
        }

        const contSelector = document.getElementById('contenedor-selector-unidades');
        const contDiag = document.getElementById('contenedor-diag-pendrive');
        const todasRem = estadoPen.todas_unidades_removibles || [];

        // Selector multi-unidad si hay más de 1 unidad removible
        if (todasRem.length > 1) {
          if (contSelector) {
            contSelector.style.display = 'flex';
            if (!unidadRemovibleSeleccionada || !todasRem.some(u => u.dispositivo === unidadRemovibleSeleccionada)) {
              unidadRemovibleSeleccionada = (estadoPen.dispositivo && todasRem.some(u => u.dispositivo === estadoPen.dispositivo))
                ? estadoPen.dispositivo
                : todasRem[0].dispositivo;
            }
            contSelector.innerHTML = `
              <label for="sel-unidad-removible" style="font-size:0.9rem; font-weight:600; color:var(--text); white-space:nowrap;">
                Unidad removible (${todasRem.length}):
              </label>
              <select id="sel-unidad-removible" onchange="seleccionarUnidadRemovible(this.value)" style="flex:1; padding:6px 12px; background:var(--bg); border:1px solid var(--border); color:var(--text); border-radius:4px; font-size:0.9rem;">
                ${todasRem.map(u => `
                  <option value="${escapeHTML(u.dispositivo)}" ${u.dispositivo === unidadRemovibleSeleccionada ? 'selected' : ''}>
                    ${escapeHTML(u.dispositivo)} ${u.etiqueta ? '("' + escapeHTML(u.etiqueta) + '")' : ''} &mdash; ${escapeHTML(u.tamanio_fmt)} [${escapeHTML(u.sistema_archivos || 'desconocido')}] &mdash; ${u.montado ? '● Montada' : '○ Sin montar'}
                  </option>
                `).join('')}
              </select>
            `;
          }
        } else {
          if (contSelector) {
            contSelector.style.display = 'none';
            contSelector.innerHTML = '';
          }
          if (todasRem.length === 1) {
            unidadRemovibleSeleccionada = todasRem[0].dispositivo;
          } else {
            unidadRemovibleSeleccionada = null;
          }
        }

        // Unidad activa seleccionada
        let unidadActiva = null;
        if (todasRem.length > 0) {
          unidadActiva = todasRem.find(u => u.dispositivo === unidadRemovibleSeleccionada) || todasRem[0];
        }

        // 1. Tarjeta Estado Físico del Pendrive (5 estados)
        let puedeEnviarPendrive = false;
        let motivoDeshabilitado = "";

        if (estadoPen.sin_respuesta) {
          // (e) Sin respuesta
          puedeEnviarPendrive = false;
          motivoDeshabilitado = "El pendrive no responde a las lecturas dentro del tiempo límite de 3 segundos.";
          contEstado.innerHTML = `
            <div style="background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; padding:16px; border-radius:6px; color:#fef3c7;">
              <h3 style="display:flex; align-items:center; gap:8px;">⚠️ Pendrive sin respuesta</h3>
              <p style="margin-top:6px; font-size:0.9rem;">El dispositivo montado no responde a las solicitudes de lectura dentro del tiempo límite de 3 segundos.</p>
            </div>
          `;
          if (btnVincular) btnVincular.style.display = 'none';
        } else if (!unidadActiva && !estadoPen.conectado && !estadoPen.unidad_candidata) {
          // (a) Sin ninguna unidad removible
          puedeEnviarPendrive = false;
          motivoDeshabilitado = "No hay ningún pendrive vinculado conectado.";
          contEstado.innerHTML = `
            <div style="background:var(--card-alt); padding:16px; border-radius:6px; color:var(--text-muted);">
              <p>🔌 Ningún pendrive detectado en el sistema.</p>
              <small>Conectá tu pendrive para transferir el material o vincularlo por primera vez.</small>
            </div>
          `;
          if (btnVincular) btnVincular.style.display = 'none';
        } else {
          // Tenemos unidad para mostrar
          const esWindows = !!estadoPen.es_windows;
          const disp = (unidadActiva && unidadActiva.dispositivo) || estadoPen.dispositivo || "";
          const nodo = (unidadActiva && unidadActiva.nodo) || estadoPen.nodo || "";
          const padre = (unidadActiva && unidadActiva.disco_padre) || estadoPen.disco_padre || "";
          const etiq = (unidadActiva && unidadActiva.etiqueta) || estadoPen.etiqueta || "";
          const fs = (unidadActiva && unidadActiva.sistema_archivos) || estadoPen.sistema_archivos || "desconocido";
          const estaMontada = unidadActiva ? !!unidadActiva.montado : (estadoPen.conectado || !!estadoPen.unidad_candidata);
          const ptoMontaje = (unidadActiva && unidadActiva.punto_montaje) || estadoPen.punto_montaje || "";

          if (!estaMontada) {
            // (b) Unidad detectada SIN MONTAR
            puedeEnviarPendrive = false;
            motivoDeshabilitado = "Unidad removible detectada sin montar. Montala para acceder a ella.";
            if (btnVincular) btnVincular.style.display = 'none';

            const btnMontarHtml = !esWindows ? `
              <button class="btn-sm" onclick="abrirModalControlPendrive('montar', '${escapeHTML(disp)}', '${escapeHTML(nodo)}', '${escapeHTML(padre)}', '')" style="background:var(--accent); color:#000; font-weight:700; padding:8px 18px; border:none; border-radius:4px; cursor:pointer;" title="Montar partición usando udisksctl">
                Montar unidad
              </button>
            ` : '';

            contEstado.innerHTML = `
              <div style="background:rgba(245, 158, 11, 0.08); border:1px solid #f59e0b; padding:16px; border-radius:6px;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:12px;">
                  <div>
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Estado</div>
                    <div style="font-size:1.1rem; font-weight:700; color:#f59e0b; margin-top:4px;">
                      ○ Unidad detectada (sin montar)
                    </div>
                  </div>
                  ${btnMontarHtml}
                </div>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px;">
                  <div style="background:var(--card-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Dispositivo</div>
                    <div style="font-size:0.95rem; font-family:monospace; margin-top:2px;">${escapeHTML(disp)}</div>
                  </div>
                  <div style="background:var(--card-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Etiqueta</div>
                    <div style="font-size:0.95rem; font-weight:600; margin-top:2px;">${escapeHTML(etiq || '(sin etiqueta)')}</div>
                  </div>
                  <div style="background:var(--card-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Tamaño</div>
                    <div style="font-size:0.95rem; font-weight:600; margin-top:2px;">${escapeHTML(unidadActiva ? unidadActiva.tamanio_fmt : estadoPen.espacio_total_fmt)}</div>
                  </div>
                  <div style="background:var(--card-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Sistema de archivos</div>
                    <div style="font-size:0.95rem; font-family:monospace; margin-top:2px;">${escapeHTML(fs)}</div>
                  </div>
                </div>
              </div>
            `;
          } else {
            // Unidad MONTADA: ¿Vinculada o sin vincular?
            const esEstaVinculada = estadoPen.conectado && (!unidadActiva || unidadActiva.punto_montaje === estadoPen.punto_montaje);

            const btnsDesmontarHtml = !esWindows ? `
              <div style="display:flex; gap:8px; align-items:center;">
                <button class="btn-sm" onclick="abrirModalControlPendrive('desmontar', '${escapeHTML(disp)}', '${escapeHTML(nodo)}', '${escapeHTML(padre)}', '${escapeHTML(ptoMontaje)}')" style="background:var(--card-alt); border:1px solid var(--border); color:var(--text); padding:6px 12px; font-weight:600; border-radius:4px; cursor:pointer;" title="Desmontar partición con udisksctl">
                  Desmontar
                </button>
                <button class="btn-sm" onclick="abrirModalControlPendrive('expulsar', '${escapeHTML(disp)}', '${escapeHTML(nodo)}', '${escapeHTML(padre)}', '${escapeHTML(ptoMontaje)}')" style="background:rgba(239, 68, 68, 0.2); border:1px solid #ef4444; color:#fca5a5; padding:6px 12px; font-weight:600; border-radius:4px; cursor:pointer;" title="Desmontar y apagar disco para retirar con seguridad">
                  Desmontar y expulsar
                </button>
              </div>
            ` : '';

            if (!esEstaVinculada) {
              // (c) Montada SIN VINCULAR
              puedeEnviarPendrive = false;
              motivoDeshabilitado = "Unidad candidata montada sin vincular. Hacé clic en 'Vincular pendrive' para configurarla.";
              if (btnVincular) btnVincular.style.display = 'none';

              contEstado.innerHTML = `
                <div style="background:rgba(99, 102, 241, 0.1); border:1px solid #6366f1; padding:16px; border-radius:6px;">
                  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:12px;">
                    <div>
                      <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Estado</div>
                      <div style="font-size:1.1rem; font-weight:700; color:#818cf8; margin-top:4px;">
                        🔍 Unidad candidata montada (sin vincular)
                      </div>
                    </div>
                    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                      <button class="btn-sm" onclick="abrirModalVincularPendrive('${escapeHTML(ptoMontaje)}')" style="background:var(--accent); color:#000; font-weight:700; padding:8px 18px; border:none; border-radius:4px; cursor:pointer;">
                        Vincular pendrive
                      </button>
                      ${btnsDesmontarHtml}
                    </div>
                  </div>
                  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px;">
                    <div style="background:var(--card-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
                      <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Punto de montaje</div>
                      <div style="font-size:0.85rem; font-family:monospace; margin-top:2px; word-break:break-all;" title="${escapeHTML(ptoMontaje)}">${escapeHTML(ptoMontaje)}</div>
                    </div>
                    <div style="background:var(--card-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
                      <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Sistema de archivos</div>
                      <div style="font-size:0.95rem; font-family:monospace; margin-top:2px;">${escapeHTML(fs)}</div>
                    </div>
                    <div style="background:var(--card-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
                      <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Espacio libre</div>
                      <div style="font-size:0.95rem; font-weight:600; margin-top:2px;">${escapeHTML(estadoPen.espacio_libre_fmt)} de ${escapeHTML(estadoPen.espacio_total_fmt)}</div>
                    </div>
                  </div>
                </div>
              `;
            } else {
              // (d) Vinculada y lista
              puedeEnviarPendrive = true;
              motivoDeshabilitado = "";
              if (btnVincular) btnVincular.style.display = 'none';

              contEstado.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:12px;">
                  <div>
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Estado</div>
                    <div style="font-size:1.1rem; font-weight:700; color:var(--teal); margin-top:4px;">● Conectado y Vinculado</div>
                  </div>
                  ${btnsDesmontarHtml}
                </div>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px;">
                  <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">ID Marcador</div>
                    <div style="font-size:0.95rem; font-family:monospace; margin-top:4px;" title="${escapeHTML(estadoPen.id)}">${escapeHTML((estadoPen.id || '').slice(0, 13))}...</div>
                  </div>
                  <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Punto de Montaje</div>
                    <div style="font-size:0.85rem; font-family:monospace; margin-top:4px; word-break:break-all;" title="${escapeHTML(estadoPen.punto_montaje)}">${escapeHTML(estadoPen.punto_montaje)}</div>
                  </div>
                  <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Sistema de Archivos</div>
                    <div style="font-size:1rem; font-weight:600; margin-top:4px;">${escapeHTML(estadoPen.sistema_archivos || 'N/D')}</div>
                  </div>
                  <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                    <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Espacio Disponible</div>
                    <div style="font-size:1rem; font-weight:600; color:#38bdf8; margin-top:4px;">
                      ${escapeHTML(estadoPen.espacio_libre_fmt)} <span style="font-size:0.8rem; color:var(--text-muted); font-weight:normal;">/ ${escapeHTML(estadoPen.espacio_total_fmt)}</span>
                    </div>
                  </div>
                </div>
              `;
            }
          }
        }

        // 2. Tabla de Carpetas de Sala de Espera
        if (!carpetasPendriveData.length) {
          contCaps.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay carpetas con archivos en la sala de espera (~/Descargas/_lucie/).</p>';
        } else {
          contCaps.innerHTML = `
            <table class="tabla-historial">
              <thead>
                <tr>
                  <th style="width:5%; text-align:center;">
                    <input type="checkbox" id="chk-maestro-carpetas-pendrive" onchange="toggleSeleccionarTodasCarpetasCheckbox(this.checked)" title="Seleccionar o deseleccionar todas">
                  </th>
                  <th style="width:12%;">Personaje</th>
                  <th style="width:23%;">Carpeta</th>
                  <th style="width:15%;">Tipo</th>
                  <th style="width:17%;">Archivos y peso</th>
                  <th style="width:13%;">Transferencia</th>
                  <th style="width:15%; text-align:center;">Acciones</th>
                </tr>
              </thead>
              <tbody>
                ${carpetasPendriveData.map(c => {
                  const cKey = `${c.personaje}/${c.carpeta}`;
                  const safeKey = `${c.personaje}__${c.carpeta}`.replace(/[^a-zA-Z0-9_-]/g, '_');
                  const estaMarcada = window.carpetasPendriveSeleccionadas.has(cKey);
                  const estaDesplegada = window.carpetasPendriveDesplegadas.has(safeKey);

                  let badgeTipo = '';
                  if (c.tipo === 'Capítulo en foco') {
                    badgeTipo = '<span class="badge-tipo-foco">Capítulo en foco</span>';
                  } else if (c.tipo === 'Capítulo abierto') {
                    badgeTipo = '<span class="badge-tipo-abierto">Capítulo abierto</span>';
                  } else if (c.tipo === 'Capítulo cerrado') {
                    badgeTipo = '<span class="badge-tipo-cerrado">Capítulo cerrado</span>';
                  } else if (c.es_heredada || c.tipo === 'Carpeta heredada') {
                    badgeTipo = '<span class="badge-tipo-heredada" title="Carpeta preexistente sin estructura estándar de capítulo">⚠️ Carpeta heredada</span>';
                  } else {
                    badgeTipo = '<span class="badge-tipo-escena">Escena suelta</span>';
                  }

                  let transferInfo = '';
                  if (estadoPen.conectado) {
                    transferInfo = `<div><strong style="color:var(--teal)">${c.enviados_conteo}</strong> enviados</div><div style="color:var(--text-muted); font-size:0.8rem;">${c.pendientes_conteo} pendientes</div>`;
                  } else {
                    transferInfo = `<span style="color:var(--text-muted); font-size:0.85rem;">${c.total_archivos} pendientes</span>`;
                  }

                  const tagsMedia = `
                    <div style="display:flex; gap:4px; flex-wrap:wrap; align-items:center;">
                      <span class="tag-tipo tag-video">${c.videos} vid</span>
                      <span class="tag-tipo tag-imagen">${c.fotos} fot</span>
                      ${c.audios ? `<span class="tag-tipo">${c.audios} aud</span>` : ''}
                      ${c.no_multimedia > 0 ? `<span class="tag-no-media" title="${c.no_multimedia} archivo(s) no multimedia (no se envían)">${c.no_multimedia} otros</span>` : ''}
                    </div>
                    <div style="font-size:0.8rem; color:var(--text-muted); margin-top:2px;">${escapeHTML(c.bytes_totales_fmt)}</div>
                  `;

                  const filaEnvioInhabilitada = !puedeEnviarPendrive || (estadoPen.conectado && c.pendientes_conteo === 0);
                  const motivoFila = !puedeEnviarPendrive ? motivoDeshabilitado : 'Todos los archivos ya fueron transferidos';

                  return `
                    <tr>
                      <td style="text-align:center;">
                        <input type="checkbox" class="chk-carpeta-pendrive" data-carpeta-key="${escapeHTML(cKey)}" onchange="toggleSeleccionCarpetaPendrive('${escapeHTML(cKey)}', this.checked)" ${estaMarcada ? 'checked' : ''}>
                      </td>
                      <td><code>${escapeHTML(c.personaje)}</code></td>
                      <td>
                        <strong>${escapeHTML(c.carpeta)}</strong>
                        <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">Último: ${escapeHTML(c.fecha_ultimo_archivo)}</div>
                      </td>
                      <td>${badgeTipo}</td>
                      <td>${tagsMedia}</td>
                      <td>${transferInfo}</td>
                      <td style="text-align:center;">
                        <div style="display:flex; flex-direction:column; gap:6px; align-items:center;">
                          <button class="btn-sm" id="btn-toggle-archivos-${safeKey}" onclick="toggleVerArchivosCarpeta('${safeKey}')" style="background:var(--card-alt); border:1px solid var(--border); color:var(--text); padding:4px 8px; font-size:0.8rem; border-radius:4px; cursor:pointer; width:100%;">
                            ${estaDesplegada ? 'Ocultar archivos' : `Ver archivos (${c.total_archivos})`}
                          </button>
                          <button class="btn-sm btn-enviar-fila-pendrive" onclick="abrirModalPlanEnvio(['${escapeHTML(cKey)}'])" ${filaEnvioInhabilitada ? `disabled title="${escapeHTML(motivoFila)}" style="background:#555; opacity:0.5; cursor:not-allowed; padding:4px 8px; font-size:0.8rem; width:100%;"` : 'style="background:#10b981; color:#000; font-weight:600; padding:4px 8px; font-size:0.8rem; border:none; border-radius:4px; cursor:pointer; width:100%;" title="Enviar esta carpeta al pendrive"'}>
                            Enviar esta carpeta
                          </button>
                        </div>
                      </td>
                    </tr>
                    <tr id="fila-archivos-${safeKey}" class="desplegable-archivos-fila" style="display:${estaDesplegada ? 'table-row' : 'none'};">
                      <td colspan="7">
                        <div class="desplegable-archivos-box">
                          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <strong>Contenido de <code>${escapeHTML(c.personaje)}/${escapeHTML(c.carpeta)}</code>:</strong>
                            <small style="color:var(--text-muted)">${c.total_archivos} archivo(s) &bull; ${escapeHTML(c.bytes_totales_fmt)}</small>
                          </div>
                          ${c.es_heredada ? `
                            <div style="background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; color:#fef3c7; padding:8px 12px; border-radius:6px; margin-bottom:8px; font-size:0.85rem;">
                              ⚠️ <strong>Carpeta heredada:</strong> No tiene estructura canónica de capítulo. Revisá el contenido antes de decidir su envío.
                            </div>
                          ` : ''}
                          ${c.no_multimedia > 0 ? `
                            <div style="background:rgba(239, 68, 68, 0.15); border:1px solid #ef4444; color:#fca5a5; padding:8px 12px; border-radius:6px; margin-bottom:8px; font-size:0.85rem;">
                              ⚠️ <strong>Archivos no multimedia (${c.no_multimedia}):</strong> Se omitirán en la transferencia hacia el pendrive y permanecerán intactos en la sala de espera sin borrarse.
                            </div>
                          ` : ''}
                          <table class="tabla-archivos-carpeta">
                            <thead>
                              <tr>
                                <th style="width:30%;">Archivo</th>
                                <th style="width:25%;">Ubicación relativa</th>
                                <th style="width:10%;">Tipo</th>
                                <th style="width:12%;">Tamaño</th>
                                <th style="width:13%;">Estado</th>
                                <th style="width:10%; text-align:center;">Vista previa</th>
                              </tr>
                            </thead>
                            <tbody>
                              ${(c.archivos || []).map(a => {
                                const esMedia = (a.tipo === 'video' || a.tipo === 'foto' || a.tipo === 'audio');
                                const onclickVisor = esMedia ? `onclick="abrirVisorMedia('pendrive:${escapeHTML(cKey)}', '${escapeHTML(a.id_media)}')"` : '';
                                const cursorStyle = esMedia ? 'cursor:pointer; text-decoration:underline;' : '';
                                return `
                                  <tr>
                                    <td>
                                      <span ${onclickVisor} style="${cursorStyle} font-weight:500;" title="${esMedia ? 'Clic para ver en el visor' : ''}">
                                        ${esMedia ? (a.tipo === 'video' ? '🎬 ' : '🖼️ ') : '📄 '}${escapeHTML(a.nombre)}
                                      </span>
                                    </td>
                                    <td><code>${escapeHTML(a.ruta_relativa)}</code></td>
                                    <td><span class="tag-tipo ${a.tipo === 'video' ? 'tag-video' : (a.tipo === 'foto' ? 'tag-imagen' : 'tag-no-media')}">${escapeHTML(a.tipo)}</span></td>
                                    <td>${escapeHTML(a.tamanio_fmt)}</td>
                                    <td>${a.ya_enviado ? '<span class="badge-enviado">Ya en pendrive</span>' : '<span class="badge-pendiente">Pendiente</span>'}</td>
                                    <td style="text-align:center;">
                                      ${esMedia ? `
                                        <button class="btn-sm" onclick="abrirVisorMedia('pendrive:${escapeHTML(cKey)}', '${escapeHTML(a.id_media)}')" style="background:transparent; border:1px solid var(--border); color:var(--text); padding:2px 8px; font-size:0.8rem; border-radius:4px; cursor:pointer;" title="Abrir visor">
                                          👁️ Ver
                                        </button>
                                      ` : '<span style="color:var(--text-muted); font-size:0.8rem;">-</span>'}
                                    </td>
                                  </tr>
                                `;
                              }).join('')}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          `;
        }

        actualizarEstadoCheckboxesPendrive();

        // 3. Archivos .part huérfanos
        const parts = estadoPen.archivos_part_huerfanos || [];
        if (parts.length > 0) {
          cardPart.style.display = 'block';
          contPart.innerHTML = `
            <table class="tabla-historial">
              <thead>
                <tr>
                  <th>Archivo .part</th>
                  <th>Ubicación relativa</th>
                  <th>Tamaño</th>
                  <th>Modificado</th>
                </tr>
              </thead>
              <tbody>
                ${parts.map(p => `
                  <tr>
                    <td><strong style="color:var(--danger)">${escapeHTML(p.nombre)}</strong></td>
                    <td class="ruta-celda"><code>${escapeHTML(p.ruta_relativa)}</code></td>
                    <td>${escapeHTML(p.tamanio_fmt)}</td>
                    <td><small style="color:var(--text-muted)">${escapeHTML((p.fecha_modificacion || '').replace('T', ' ').slice(0, 19))}</small></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          `;
        } else {
          cardPart.style.display = 'none';
          contPart.innerHTML = '';
        }

        // 4. Historial de envíos
        const hist = histRes.historial || [];
        const enviosPendrive = hist.filter(h => h.evento === 'envio_pendrive');
        if (!enviosPendrive.length) {
          contHist.innerHTML = '<p style="color:var(--text-muted); padding:16px;">Aún no se registraron transferencias al pendrive en la bitácora.</p>';
        } else {
          contHist.innerHTML = `
            <table class="tabla-historial">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Capítulo</th>
                  <th>Archivos</th>
                  <th>Bytes</th>
                  <th>Estado</th>
                  <th style="text-align:center;">Acción</th>
                </tr>
              </thead>
              <tbody>
                ${enviosPendrive.map(e => `
                  <tr>
                    <td><small>${escapeHTML(e.fecha)}</small></td>
                    <td><strong>${escapeHTML(e.personaje || '')}/${escapeHTML(e.capitulo || '')}</strong></td>
                    <td>${e.total_archivos || (e.archivos ? e.archivos.length : 1)} archivo(s)</td>
                    <td>${formatearBytes(e.total_bytes || 0)}</td>
                    <td><span class="${e.estado === 'deshecho' ? 'badge-deshecho' : 'badge-movido'}">${escapeHTML(e.estado)}</span></td>
                    <td style="text-align:center;">
                      ${e.estado !== 'deshecho' ? `
                        <button class="btn-sm" onclick="deshacerEnvio('${escapeHTML(e.id_operacion)}')" style="background:var(--card-alt); border:1px solid var(--border); color:var(--text); padding:4px 10px; border-radius:4px; cursor:pointer;">
                          Deshacer envío
                        </button>
                      ` : '<span style="color:var(--text-muted)">Revertido</span>'}
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          `;
        }

        // 5. Diagnóstico de particiones ("¿Por qué no veo mi pendrive?")
        if (contDiag) {
          const diagParts = estadoPen.diagnostico_particiones || [];
          if (!diagParts.length) {
            contDiag.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem; padding:8px 0;">No se encontraron particiones de almacenamiento para diagnosticar.</p>';
          } else {
            contDiag.innerHTML = `
              <table class="tabla-diag">
                <thead>
                  <tr>
                    <th>Dispositivo</th>
                    <th>Tamaño</th>
                    <th>Removible</th>
                    <th>Montada</th>
                    <th>Sistema de archivos</th>
                    <th>Estado / Diagnóstico</th>
                  </tr>
                </thead>
                <tbody>
                  ${diagParts.map(p => `
                    <tr>
                      <td><code>${escapeHTML(p.dispositivo)}</code>${p.etiqueta ? ' <small style="color:var(--text-muted)">(' + escapeHTML(p.etiqueta) + ')</small>' : ''}</td>
                      <td>${escapeHTML(p.tamanio_fmt || '-')}</td>
                      <td>${p.es_removible ? '<span style="color:var(--teal)">Sí</span>' : '<span style="color:var(--text-muted)">No</span>'}</td>
                      <td>${p.montado ? `<span style="color:#60a5fa" title="${escapeHTML(p.punto_montaje || '')}">Sí (<code>${escapeHTML(p.punto_montaje || '')}</code>)</span>` : '<span style="color:var(--text-muted)">No</span>'}</td>
                      <td><code>${escapeHTML(p.sistema_archivos || '-')}</code></td>
                      <td style="color:var(--text-muted); font-size:0.8rem;">${escapeHTML(p.motivo || '')}</td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            `;
          }
        }
      } catch (e) {
        contEstado.innerHTML = `<p style="color:var(--danger)">Error al cargar vista de pendrive: ${escapeHTML(e.message)}</p>`;
      }
    }

    async function deshacerEnvio(idOperacion) {
      if (!confirm("¿Confirmás deshacer este envío al pendrive? La copia en el pendrive se moverá a _revertidos/ y los archivos originales regresarán a la sala de espera si sus ubicaciones siguen libres.")) {
        return;
      }
      try {
        await apiFetch('/api/deshacer', {
          method: 'POST',
          body: JSON.stringify({ id_operacion: idOperacion })
        });
        mostrarToastLlegada("Envío revertido con éxito.");
        await cargarVistaPendrive();
        await cargarDatos();
      } catch (e) {
        mostrarError(`Error al deshacer envío: ${e.message}`);
      }
    }

    let puntoMontajeVincular = null;

    async function abrirModalVincularPendrive(punto = null) {
      try {
        puntoMontajeVincular = punto;
        const modal = document.getElementById('modal-vincular-pendrive');
        const cont = document.getElementById('contenido-vincular-pendrive');
        cont.innerHTML = '<p style="color:var(--text-muted)">Inspeccionando unidad...</p>';
        modal.style.display = 'flex';

        const body = punto ? { punto_montaje: punto } : {};
        const sim = await apiFetch('/api/pendrive/vincular-simular', {
          method: 'POST',
          body: JSON.stringify(body)
        });

        puntoMontajeVincular = sim.punto_montaje;
        cont.innerHTML = `
          <div style="background:var(--card-alt); padding:16px; border-radius:6px; margin-bottom:12px;">
            <p><strong>Punto de montaje:</strong> <code>${escapeHTML(sim.punto_montaje)}</code></p>
            <p style="margin-top:6px;"><strong>Sistema de archivos:</strong> <code>${escapeHTML(sim.sistema_archivos || 'desconocido')}</code></p>
            <p style="margin-top:6px;"><strong>Espacio libre:</strong> ${escapeHTML(sim.espacio_libre_fmt)} de ${escapeHTML(sim.espacio_total_fmt)}</p>
          </div>
          <p style="font-size:0.9rem; color:var(--text-muted);">
            Al vincular, se creará el marcador de identidad <code>.lucie_pendrive.json</code> en la raíz y la estructura base <code>LucieSinReglas/</code> con sus subcarpetas.
            <strong>Nada de lo que ya exista en el pendrive será modificado ni tocado.</strong>
          </p>
        `;
      } catch (e) {
        mostrarError(e.message);
        cerrarModalVincularPendrive();
      }
    }

    function cerrarModalVincularPendrive() {
      const modal = document.getElementById('modal-vincular-pendrive');
      if (modal) modal.style.display = 'none';
      puntoMontajeVincular = null;
      programarSiguienteSondeo(500);
    }

    async function confirmarVincularPendrive() {
      try {
        const body = puntoMontajeVincular ? { punto_montaje: puntoMontajeVincular } : {};
        await apiFetch('/api/pendrive/vincular', {
          method: 'POST',
          body: JSON.stringify(body)
        });
        cerrarModalVincularPendrive();
        mostrarToastLlegada("Pendrive vinculado exitosamente.");
        await cargarVistaPendrive();
      } catch (e) {
        mostrarError(`Error al vincular pendrive: ${e.message}`);
      }
    }

    let accionPendriveModal = null;
    let dispPendriveModal = null;
    let nodoPendriveModal = null;
    let padrePendriveModal = null;
    let puntoPendriveModal = null;
    let comandoPendriveModal = '';
    let comandoManualFallback = '';
    let unidadRemovibleSeleccionada = null;

    function abrirModalControlPendrive(accion, dispositivo, nodo, discoPadre, puntoMontaje) {
      accionPendriveModal = accion;
      dispPendriveModal = dispositivo;
      nodoPendriveModal = nodo;
      padrePendriveModal = discoPadre || (dispositivo ? dispositivo.replace(/\d+$/, '') : '');
      puntoPendriveModal = puntoMontaje;

      const modal = document.getElementById('modal-control-pendrive');
      const tit = document.getElementById('modal-control-titulo');
      const desc = document.getElementById('modal-control-desc');
      const cmd = document.getElementById('modal-control-comando');
      const errBox = document.getElementById('modal-control-error-box');
      const exitoBox = document.getElementById('modal-control-exito-box');
      const actBox = document.getElementById('modal-control-actions');
      const btnConf = document.getElementById('btn-confirmar-control-pendrive');
      const btnCanc = document.getElementById('btn-cancelar-control-pendrive');
      const fbCopy = document.getElementById('feedback-copiar-comando');

      if (errBox) errBox.style.display = 'none';
      if (exitoBox) exitoBox.style.display = 'none';
      if (fbCopy) fbCopy.style.display = 'none';
      if (actBox) actBox.style.display = 'flex';
      if (btnCanc) btnCanc.innerText = 'Cancelar';
      if (btnConf) {
        btnConf.style.display = 'inline-block';
        btnConf.disabled = false;
        btnConf.style.opacity = '1';
        btnConf.style.cursor = 'pointer';
      }

      if (accion === 'montar') {
        if (tit) tit.innerText = 'Montar unidad pendrive';
        if (desc) desc.innerHTML = `Montar la partición <code>${escapeHTML(dispositivo)}</code> para permitir el acceso al almacenamiento.`;
        comandoPendriveModal = `udisksctl mount -b ${dispositivo}`;
        comandoManualFallback = `sudo mount ${dispositivo} /media/pendrive`;
        if (btnConf) btnConf.innerText = 'Confirmar montaje';
      } else if (accion === 'desmontar') {
        if (tit) tit.innerText = 'Desmontar unidad pendrive';
        if (desc) desc.innerHTML = `Sincronizar buffers de disco y desmontar la partición <code>${escapeHTML(dispositivo)}</code> de forma segura.`;
        comandoPendriveModal = `udisksctl unmount -b ${dispositivo}`;
        comandoManualFallback = `sudo umount ${dispositivo}`;
        if (btnConf) btnConf.innerText = 'Confirmar desmontaje';
      } else if (accion === 'expulsar') {
        if (tit) tit.innerText = 'Desmontar y expulsar pendrive';
        if (desc) desc.innerHTML = `Sincronizar buffers, desmontar la partición <code>${escapeHTML(dispositivo)}</code> y apagar la energía del disco <code>${escapeHTML(padrePendriveModal)}</code> para su extracción física.`;
        comandoPendriveModal = `udisksctl unmount -b ${dispositivo} && udisksctl power-off -b ${padrePendriveModal}`;
        comandoManualFallback = `sudo umount ${dispositivo} && sudo udisksctl power-off -b ${padrePendriveModal}`;
        if (btnConf) btnConf.innerText = 'Confirmar y expulsar';
      }

      if (cmd) cmd.innerText = comandoPendriveModal;
      if (modal) modal.style.display = 'flex';
    }

    function cerrarModalControlPendrive() {
      const modal = document.getElementById('modal-control-pendrive');
      if (modal) modal.style.display = 'none';
      accionPendriveModal = null;
      dispPendriveModal = null;
      nodoPendriveModal = null;
      padrePendriveModal = null;
      puntoPendriveModal = null;
      comandoPendriveModal = '';
      comandoManualFallback = '';
    }

    function copiarComandoControlPendrive() {
      if (!comandoPendriveModal) return;
      navigator.clipboard.writeText(comandoPendriveModal).then(() => {
        const fb = document.getElementById('feedback-copiar-comando');
        if (fb) {
          fb.style.display = 'block';
          setTimeout(() => { fb.style.display = 'none'; }, 3000);
        }
      }).catch(() => {
        prompt("Copiá este comando:", comandoPendriveModal);
      });
    }

    function copiarComandoManualPendrive() {
      if (!comandoManualFallback) return;
      navigator.clipboard.writeText(comandoManualFallback).then(() => {
        mostrarToastLlegada("Comando manual copiado.");
      }).catch(() => {
        prompt("Copiá este comando manual:", comandoManualFallback);
      });
    }

    async function confirmarControlPendrive() {
      const btnConf = document.getElementById('btn-confirmar-control-pendrive');
      const btnCanc = document.getElementById('btn-cancelar-control-pendrive');
      const errBox = document.getElementById('modal-control-error-box');
      const errMsg = document.getElementById('modal-control-error-msg');
      const procBox = document.getElementById('modal-control-procesos-box');
      const procLista = document.getElementById('modal-control-procesos-lista');
      const fallBox = document.getElementById('modal-control-fallback-box');
      const fallCmd = document.getElementById('modal-control-fallback-cmd');
      const exitoBox = document.getElementById('modal-control-exito-box');
      const exitoMsg = document.getElementById('modal-control-exito-msg');

      if (errBox) errBox.style.display = 'none';
      if (btnConf) {
        btnConf.disabled = true;
        btnConf.style.opacity = '0.5';
        btnConf.innerText = 'Ejecutando...';
      }

      let endpoint = '/api/pendrive/montar';
      if (accionPendriveModal === 'desmontar') endpoint = '/api/pendrive/desmontar';
      if (accionPendriveModal === 'expulsar') endpoint = '/api/pendrive/expulsar';

      try {
        const res = await apiFetch(endpoint, {
          method: 'POST',
          body: JSON.stringify({ dispositivo: dispPendriveModal })
        });

        if (accionPendriveModal === 'expulsar') {
          cerrarBannerPendrive();
          if (exitoBox && exitoMsg) {
            exitoMsg.innerText = res.mensaje || 'Ya podés retirar el pendrive con seguridad.';
            exitoBox.style.display = 'block';
          }
          if (btnConf) btnConf.style.display = 'none';
          if (btnCanc) btnCanc.innerText = 'Cerrar';
          await cargarVistaPendrive();
        } else if (accionPendriveModal === 'desmontar') {
          cerrarBannerPendrive();
          cerrarModalControlPendrive();
          mostrarToastLlegada(res.mensaje || 'Unidad desmontada exitosamente.');
          await cargarVistaPendrive();
        } else {
          cerrarModalControlPendrive();
          mostrarToastLlegada(res.mensaje || 'Unidad montada exitosamente.');
          await cargarVistaPendrive();
        }
      } catch (err) {
        if (btnConf) {
          btnConf.disabled = false;
          btnConf.style.opacity = '1';
          btnConf.innerText = 'Reintentar';
        }
        const det = err.detalles || {};
        if (errBox && errMsg) {
          errMsg.innerText = err.message || 'Error al ejecutar la acción.';
          errBox.style.display = 'block';

          // Procesos ocupando montaje
          if (det.procesos_ocupando && det.procesos_ocupando.length > 0 && procBox && procLista) {
            procBox.style.display = 'block';
            procLista.innerHTML = `
              <ul style="margin:4px 0 0 16px; padding:0; font-size:0.85rem; color:#fef3c7;">
                ${det.procesos_ocupando.map(p => `
                  <li>PID <strong>${escapeHTML(p.pid)}</strong> (<em>${escapeHTML(p.comando || p.cmd)}</em>) &mdash; ${escapeHTML(p.detalle)}</li>
                `).join('')}
              </ul>
            `;
          } else if (procBox) {
            procBox.style.display = 'none';
          }

          // Comando manual sugerido
          if (det.comando_manual || comandoManualFallback) {
            if (det.comando_manual) comandoManualFallback = det.comando_manual;
            if (fallCmd) fallCmd.innerText = comandoManualFallback;
            if (fallBox) fallBox.style.display = 'block';
          }
        }
      }
    }

    function seleccionarUnidadRemovible(disp) {
      unidadRemovibleSeleccionada = disp;
      cargarVistaPendrive();
    }

    // =========================================================================
    // Modo Edición con CapCut (Tramo 3)
    // =========================================================================

    let clipsParaEditar = [];
    let clipsSeleccionadosParaEditar = new Set();
    let sesionModalClips = [];

    function mostrarAvisoEdicion(mensajeHtml, accionesHtml = '') {
      const aviso = document.getElementById('aviso-edicion');
      const texto = document.getElementById('aviso-edicion-texto');
      const acciones = document.getElementById('aviso-edicion-acciones');
      if (!aviso || !texto) return;
      texto.innerHTML = mensajeHtml;
      if (acciones) acciones.innerHTML = accionesHtml;
      aviso.style.display = 'flex';
    }

    function ocultarAvisoEdicion() {
      const aviso = document.getElementById('aviso-edicion');
      if (aviso) aviso.style.display = 'none';
    }

    async function cargarVistaEdicion() {
      const contParaEditar = document.getElementById('contenedor-para-editar');
      const contEnEdicion = document.getElementById('contenedor-en-edicion');
      const contEditados = document.getElementById('contenedor-editados-completos');
      const contExports = document.getElementById('contenedor-exports-capcut');

      try {
        const res = await fetch('/api/edicion/secciones');
        const data = await res.json();

        if (!data.conectado) {
          if (contParaEditar) {
            contParaEditar.innerHTML = `
              <div style="padding:16px; background:var(--card-alt); border-radius:6px; color:var(--text-muted); text-align:center;">
                <p style="font-size:1.05rem; font-weight:600; color:var(--text);">Pendrive no conectado o no vinculado</p>
                <p style="margin-top:6px;">Conectá y vinculá tu pendrive para explorar los clips crudos y gestionar sesiones de edición.</p>
                <button class="btn-sm" onclick="mostrarPestana('pendrive')" style="margin-top:12px; background:var(--accent); color:#000; font-weight:600;">Ir a pestaña Pendrive</button>
              </div>
            `;
          }
          if (contEnEdicion) contEnEdicion.innerHTML = '<p style="color:var(--text-muted);">Sin sesiones disponibles.</p>';
          const esperando = document.getElementById('contenedor-esperando-export');
          if (esperando) esperando.replaceChildren();
          renderizarTrasladosPendientes([]);
          if (contEditados) contEditados.innerHTML = '<p style="color:var(--text-muted);">Sin datos de capítulos.</p>';
          if (contExports) renderizarExportsCapCut(data.videos_completados || [], data.sesiones_para_export || []);
          return;
        }

        // 1. Para editar
        clipsParaEditar = data.para_editar || [];
        renderizarClipsParaEditar(clipsParaEditar);

        // 2. En edición
        renderizarSesionesEnEdicion(data.en_edicion || []);
        renderizarTrasladosPendientes(data.traslados_pendientes || []);
        renderizarSesionesEsperandoExport(data.sesiones_esperando_export || [], data.videos_completados || []);

        // 3. Editados y completos
        renderizarEditadosYCompletos(data.conteos_capitulo || {});

        // 4. Exports de CapCut
        renderizarExportsCapCut(data.videos_completados || [], data.sesiones_para_export || []);

      } catch (err) {
        console.error("Error al cargar vista de edición:", err);
        if (contParaEditar) contParaEditar.innerHTML = `<div class="error-box">Error al cargar datos de edición: ${escapeHTML(String(err))}</div>`;
      }
    }

    function renderizarClipsParaEditar(clips) {
      const cont = document.getElementById('contenedor-para-editar');
      if (!cont) return;

      if (!clips || clips.length === 0) {
        cont.innerHTML = '<p style="color:var(--text-muted); padding:10px;">No hay clips crudos pendientes de editar en el pendrive.</p>';
        actualizarBotonCrearSesion();
        return;
      }

      let html = `
        <table class="tabla-archivos" style="width:100%; border-collapse:collapse; margin-top:8px;">
          <thead>
            <tr style="border-bottom:1px solid var(--border); text-align:left;">
              <th style="width:36px; padding:8px;"></th>
              <th style="padding:8px;">Clip</th>
              <th style="padding:8px;">Personaje</th>
              <th style="padding:8px;">Capítulo</th>
              <th style="padding:8px;">Tamaño</th>
              <th style="padding:8px; text-align:right;">Acción</th>
            </tr>
          </thead>
          <tbody>
      `;

      const grupos = new Map();
      clips.forEach(c => {
        const clave = JSON.stringify([c.personaje, c.capitulo]);
        if (!grupos.has(clave)) grupos.set(clave, []);
        grupos.get(clave).push(c);
      });
      let indiceGrupo = 0;
      grupos.forEach(grupo => {
        const primero = grupo[0];
        const indice = indiceGrupo++;
        const todoCapitulo = clipsParaEditar.filter(c => c.personaje === primero.personaje && c.capitulo === primero.capitulo);
        const completo = todoCapitulo.every(c => clipsSeleccionadosParaEditar.has(c.identificador));
        html += `<tr><td colspan="6" style="padding:12px; background:var(--card-alt);">
          <label><input type="checkbox" data-grupo-edicion="${indice}" ${completo ? 'checked' : ''}>
          Seleccionar capítulo: <strong>${escapeHTML(primero.personaje)} / ${escapeHTML(primero.capitulo)}</strong>
          (${todoCapitulo.length} archivos)</label></td></tr>`;
      grupo.forEach(c => {
        const sel = clipsSeleccionadosParaEditar.has(c.identificador) ? 'checked' : '';
        const tamStr = c.tamano ? (c.tamano / (1024 * 1024)).toFixed(1) + ' MB' : '-';
        html += `
          <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
            <td style="padding:8px;">
              <input type="checkbox" onchange="toggleSeleccionClipParaEditar('${escapeHTML(c.identificador)}')" ${sel}>
            </td>
            <td style="padding:8px; font-weight:500;">
              <span style="cursor:pointer;" onclick="previsualizarClipPendrive('${escapeHTML(c.id_media || c.ruta_relativa || c.identificador)}', '${escapeHTML(c.nombre)}')" title="${escapeHTML(c.ruta_relativa)}">${c.tipo === 'audio' ? '🎵 ' : ''}${escapeHTML(c.nombre)}</span>
            </td>
            <td style="padding:8px; color:var(--text-muted);">${escapeHTML(c.personaje)}</td>
            <td style="padding:8px; color:var(--text-muted);"><span class="badge" style="background:#1e1b4b; color:#a5b4fc;">${escapeHTML(c.capitulo)}</span></td>
            <td style="padding:8px; color:var(--text-muted); font-size:0.85rem;">${tamStr}</td>
            <td style="padding:8px; text-align:right;">
              <button class="btn-sm" onclick="previsualizarClipPendrive('${escapeHTML(c.id_media || c.ruta_relativa || c.identificador)}', '${escapeHTML(c.nombre)}')" style="padding:3px 8px; font-size:0.8rem; background:var(--card-alt); border:1px solid var(--border); color:var(--text); cursor:pointer;">▶ Ver</button>
            </td>
          </tr>
        `;
      });
      });

      html += '</tbody></table>';
      cont.innerHTML = html;
      cont.querySelectorAll('[data-grupo-edicion]').forEach((checkbox, indice) => {
        const grupo = Array.from(grupos.values())[indice];
        checkbox.indeterminate = !checkbox.checked && clipsParaEditar.some(c => c.personaje === grupo[0].personaje && c.capitulo === grupo[0].capitulo && clipsSeleccionadosParaEditar.has(c.identificador));
        checkbox.addEventListener('change', () => {
          // Incluye todo el capítulo, incluso archivos ocultos por la búsqueda.
          clipsParaEditar.filter(c => c.personaje === grupo[0].personaje && c.capitulo === grupo[0].capitulo)
            .forEach(c => checkbox.checked ? clipsSeleccionadosParaEditar.add(c.identificador) : clipsSeleccionadosParaEditar.delete(c.identificador));
          filtrarClipsParaEditar();
        });
      });
      actualizarBotonCrearSesion();
    }

    function toggleSeleccionClipParaEditar(identificador) {
      if (clipsSeleccionadosParaEditar.has(identificador)) {
        clipsSeleccionadosParaEditar.delete(identificador);
      } else {
        clipsSeleccionadosParaEditar.add(identificador);
      }
      filtrarClipsParaEditar();
    }

    function seleccionarTodosParaEditar() {
      clipsParaEditar.forEach(c => clipsSeleccionadosParaEditar.add(c.identificador));
      renderizarClipsParaEditar(clipsParaEditar);
    }

    function deseleccionarTodosParaEditar() {
      clipsSeleccionadosParaEditar.clear();
      renderizarClipsParaEditar(clipsParaEditar);
    }

    function actualizarBotonCrearSesion() {
      const btn = document.getElementById('btn-crear-sesion');
      if (!btn) return;
      const count = clipsSeleccionadosParaEditar.size;
      btn.innerText = `Crear nueva sesión (${count})`;
      btn.disabled = (count === 0);
      const sumar = document.getElementById('btn-sumar-seleccionados');
      if (sumar) {
        sumar.innerText = `Sumar video (${count})`;
        sumar.disabled = (count === 0);
      }
    }

    function filtrarClipsParaEditar() {
      const input = document.getElementById('filtro-para-editar');
      const q = input ? input.value.trim().toLowerCase() : '';
      if (!q) {
        renderizarClipsParaEditar(clipsParaEditar);
        return;
      }
      const filtrados = clipsParaEditar.filter(c =>
        c.nombre.toLowerCase().includes(q) ||
        c.capitulo.toLowerCase().includes(q) ||
        c.personaje.toLowerCase().includes(q)
      );
      renderizarClipsParaEditar(filtrados);
    }

    function abrirModalCrearSesion() {
      if (clipsSeleccionadosParaEditar.size === 0) return;

      sesionModalClips = clipsParaEditar.filter(c => clipsSeleccionadosParaEditar.has(c.identificador));
      if (sesionModalClips.length === 0) return;
      if (sesionModalClips.some(c => c.personaje !== sesionModalClips[0].personaje || c.capitulo !== sesionModalClips[0].capitulo)) {
        mostrarAvisoEdicion('Para crear una sesión, seleccioná archivos de un solo personaje y capítulo. Usá el tilde del capítulo deseado.');
        return;
      }

      const primerClip = sesionModalClips[0];
      const capitulo = primerClip.capitulo;

      // El servidor comparte el mismo título legible con carpetas y exports.
      const sugerencia = sesionModalClips.length === 1
        ? (primerClip.nombre_sesion_sugerido ?? primerClip.nombre.replace(/\.[^/.]+$/, ''))
        : (primerClip.nombre_capitulo_sugerido ?? capitulo);

      document.getElementById('input-nombre-sesion').value = sugerencia;
      document.getElementById('conteo-clips-modal').innerText = String(sesionModalClips.length);

      const listaDiv = document.getElementById('lista-clips-modal');
      listaDiv.innerHTML = sesionModalClips.map(c => `<div>🎬 <strong>${escapeHTML(c.nombre)}</strong> (${escapeHTML(c.capitulo)})</div>`).join('');

      document.getElementById('modal-crear-sesion').style.display = 'flex';
    }

    function cerrarModalCrearSesion() {
      document.getElementById('modal-crear-sesion').style.display = 'none';
    }

    async function confirmarCrearSesion() {
      const nombreInput = document.getElementById('input-nombre-sesion').value.trim();
      if (!nombreInput) {
        alert("Por favor ingresá un nombre para la sesión.");
        return;
      }

      const primerClip = sesionModalClips[0];
      const payload = {
        clips: sesionModalClips.map(c => c.ruta_relativa),
        personaje: primerClip.personaje,
        capitulo: primerClip.capitulo,
        nombre_sesion: nombreInput,
        abrir_carpeta: true
      };

      try {
        const res = await fetchConCsrf('/api/edicion/crear-sesion', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.exito) {
          cerrarModalCrearSesion();
          clipsSeleccionadosParaEditar.clear();
          mostrarAvisoEdicion(`✅ Sesión iniciada: <strong>${escapeHTML(nombreInput)}</strong> con ${sesionModalClips.length} clip(s).`);
          if (data.error_abrir_carpeta) {
            mostrarAvisoEdicion(`Sesión iniciada. No se pudo abrir la carpeta: ${escapeHTML(data.error_abrir_carpeta)}`);
          }
          await cargarVistaEdicion();
        } else {
          alert("Error al crear sesión: " + (data.error || "Desconocido"));
        }
      } catch (err) {
        alert("Error de comunicación: " + String(err));
      }
    }

    function renderizarTrasladosPendientes(sesiones) {
      const cont = document.getElementById('contenedor-traslados-pendientes');
      if (!cont) return;
      cont.replaceChildren();
      const aviso = document.getElementById('aviso-traslados-edicion');
      if (aviso) {
        aviso.style.display = sesiones.length ? 'block' : 'none';
        aviso.textContent = sesiones.length ? sesiones.map(s => `${s.nombre}: ${s.archivos.length} clip(s) con copia en Ya editados y original pendiente de retiro.`).join(' ') +
          (sesiones.every(s => s.archivos.every(a => a.automatico))
            ? ' Al quedar libres se retirarán automáticamente de Sin editar.'
            : ' Las ediciones anteriores requieren Completar traslado y confirmar su plan.') +
          ' Revisá los detalles de traslado debajo.' : '';
      }
      for (const sesion of sesiones) {
        const fila = document.createElement('div');
        fila.className = 'edicion-pendiente-fila';
        const texto = document.createElement('p');
        const esAuto = sesion.archivos.every(a => a.automatico);
        texto.textContent = esAuto
          ? `${sesion.nombre}: los clips ya están copiados en Videos ya editados. ${sesion.archivos.length} original(es) siguen en Sin editar. ${sesion.archivos.some(a => a.en_uso) ? 'Windows los mantiene en uso por CapCut u otra aplicación. ' : ''}El retiro se completará automáticamente cuando queden libres, sin forzar el bloqueo.`
          : `${sesion.nombre}: ${sesion.archivos.length} original(es) de esta edición anterior siguen en Sin editar (su video editado ya fue guardado). Confirmá el retiro para archivarlos en resguardo.`;
        const boton = document.createElement('button');
        boton.className = 'btn-sm'; boton.textContent = 'Completar traslado';
        boton.addEventListener('click', async () => {
          const detalle = sesion.archivos.map(a => `Origen: ${a.origen}\nCopia editada: ${a.destino}\nResguardo del original: ${a.resguardo}`).join('\n\n');
          if (!confirm(`¿Completar el traslado de «${sesion.nombre}»?\n${detalle}\nSe verificará SHA-256. Los originales retenidos pasarán al resguardo sin borrar ni sobrescribir; se retirarán solo sus carpetas vacías. Si siguen en uso, quedará pendiente y se reintentará automáticamente.`)) return;
          boton.disabled = true;
          try { await terminarEdicionSesion(sesion.id, true); }
          finally { boton.disabled = false; }
        });
        fila.append(texto, boton); cont.append(fila);
      }
      const panel = document.getElementById('card-pendientes-edicion');
      const esp = document.getElementById('contenedor-esperando-export');
      const total = cont.children.length + (esp?.children ? esp.children.length : 0);
      if (panel && panel !== cont) {
        panel.style.display = total > 0 ? 'block' : 'none';
      }
      const badge = document.getElementById('conteo-pendientes-edicion');
      if (badge && badge !== cont) badge.textContent = String(total);
    }

    function renderizarSesionesEsperandoExport(sesiones, exports) {
      const cont = document.getElementById('contenedor-esperando-export');
      if (!cont) return;
      cont.replaceChildren();
      for (const sesion of sesiones) {
        const fila = document.createElement('div');
        fila.className = 'edicion-pendiente-fila';
        const asociado = exports.find(e => e.sesion_id === sesion.id);
        const texto = document.createElement('p');
        texto.textContent = `${sesion.nombre} (${sesion.personaje} / ${sesion.capitulo}): edición terminada; ${asociado?.error ? asociado.error : 'el video final todavía no está copiado a Sin publicar.'}`;
        const revisar = document.createElement('button');
        revisar.className = 'btn-sm btn-secundario';
        revisar.textContent = 'Revisar video final';
        revisar.addEventListener('click', async () => {
          revisar.disabled = true;
          try {
            const resultado = await apiFetch('/api/edicion/revisar-export', {
              method: 'POST', body: JSON.stringify({sesion_id: sesion.id})
            });
            const estado = resultado.export_final || {};
            mostrarAvisoEdicion(escapeHTML(`${estado.mensaje || 'Revisión terminada.'} ${estado.destino || ''}`));
            await cargarVistaEdicion();
          } catch (error) { mostrarAvisoEdicion(escapeHTML(error.message)); }
          finally { revisar.disabled = false; }
        });
        fila.append(texto, revisar); cont.append(fila);
      }
      const panel = document.getElementById('card-pendientes-edicion');
      const tras = document.getElementById('contenedor-traslados-pendientes');
      const total = cont.children.length + (tras?.children ? tras.children.length : 0);
      if (panel && panel !== cont) panel.style.display = total > 0 ? 'block' : 'none';
      const badge = document.getElementById('conteo-pendientes-edicion');
      if (badge && badge !== cont) badge.textContent = String(total);
    }

    function renderizarSesionesEnEdicion(sesiones) {
      const destino = document.getElementById('sesion-destino-sumar');
      if (destino) {
        const anterior = destino.value;
        destino.innerHTML = '<option value="">Elegí una sesión en curso</option>' +
          (sesiones || []).filter(s => !s.video_completo_ruta).map(s =>
            `<option value="${s.id}">${escapeHTML(s.nombre)} (${escapeHTML(s.personaje)} / ${escapeHTML(s.capitulo)})</option>`).join('');
        if (Array.from(destino.options).some(o => o.value === anterior)) destino.value = anterior;
      }
      const cont = document.getElementById('contenedor-en-edicion');
      if (!cont) return;

      if (!sesiones || sesiones.length === 0) {
        cont.innerHTML = '<p style="color:var(--text-muted); padding:10px;">No hay sesiones activas en este momento.</p>';
        return;
      }

      let html = '<div style="display:flex; flex-direction:column; gap:12px; margin-top:8px;">';
      sesiones.forEach(s => {
        const clips = s.clips || [];
        html += `
          <div style="background:var(--card-alt); border:1px solid var(--border); border-radius:6px; padding:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
              <div>
                <span class="badge" style="background:#0284c7; color:#fff; font-weight:600; margin-right:8px;">${s.video_completo_ruta ? 'EXPORT ENVIADO · CRUDOS PENDIENTES' : 'EN EDICIÓN'}</span>
                <strong style="font-size:1.05rem;">${escapeHTML(s.nombre)}</strong>
                <span style="color:var(--text-muted); font-size:0.85rem; margin-left:8px;">(${escapeHTML(s.personaje)} / ${escapeHTML(s.capitulo)})</span>
              </div>
              <div style="display:flex; gap:8px;">
                ${!s.video_completo_ruta ? `<button class="btn-sm btn-secundario" onclick="sumarVideosSesion(${s.id})">Sumar video</button>` : ''}
                <button class="btn-sm" onclick="terminarEdicionSesion(${s.id})" style="background:#10b981; color:#000; font-weight:600; padding:6px 14px;">Terminé de editar</button>
                ${!s.video_completo_ruta ? `<button class="btn-sm btn-secundario" onclick="cancelarSesionEdicion(${s.id})" style="color:var(--danger);">Cancelar</button>` : ''}
              </div>
            </div>
            <div style="margin-top:10px; font-size:0.85rem; color:var(--text-muted);">
              <strong>Clips agrupados (${clips.length}):</strong>
              <div style="margin-top:4px; display:flex; flex-wrap:wrap; gap:6px;">
                ${clips.map(c => `<span style="background:rgba(255,255,255,0.06); padding:2px 8px; border-radius:4px;">🎬 ${escapeHTML(c.split('/').pop())}</span>`).join('')}
              </div>
            </div>
          </div>
        `;
      });
      html += '</div>';
      cont.innerHTML = html;
    }

    function sumarVideosSesionElegida() {
      const selector = document.getElementById('sesion-destino-sumar');
      if (!selector || !selector.value) {
        mostrarAvisoEdicion('Elegí la sesión que ya estás editando en «Sumar seleccionados a».');
        return;
      }
      return sumarVideosSesion(Number(selector.value));
    }

    async function sumarVideosSesion(sesionId) {
      const seleccion = clipsParaEditar.filter(c => clipsSeleccionadosParaEditar.has(c.identificador));
      if (!seleccion.length) {
        mostrarAvisoEdicion('Seleccioná los videos en «Para editar» y luego pulsá «Sumar video» en la sesión deseada.');
        return;
      }
      const selector = document.getElementById('sesion-destino-sumar');
      const opcion = selector ? Array.from(selector.options).find(o => Number(o.value) === sesionId) : null;
      const nombre = opcion ? opcion.textContent : `sesión ${sesionId}`;
      if (!confirm(`¿Sumar estos ${seleccion.length} video(s) a «${nombre}»?\n${seleccion.map(c => c.nombre).join('\n')}\nLos archivos conservarán su ubicación.`)) return;
      try {
        const resultado = await apiFetch('/api/edicion/sumar-videos', {
          method: 'POST', body: JSON.stringify({ sesion_id: sesionId, clips: seleccion.map(c => c.ruta_relativa) })
        });
        clipsSeleccionadosParaEditar.clear();
        mostrarAvisoEdicion(`Se sumaron ${resultado.agregados.length} video(s) a la sesión.`);
        await cargarVistaEdicion();
      } catch (e) { mostrarAvisoEdicion(escapeHTML(e.message)); }
    }

    async function terminarEdicionSesion(sesionId, confirmacionPrevia = false) {
      if (!confirmacionPrevia && !confirm("¿Confirmás que terminaste de editar? Los clips quedarán organizados en 'videos ya editados'. Si CapCut los mantiene abiertos, se copiarán de forma segura y el retiro de los originales se completará en segundo plano (no es necesario cerrar CapCut). Se revisará el video final exportado para copiarlo automáticamente a 'videos completos/videos sin publicar'. Los exports originales de CapCut se conservan.")) return;

      try {
        const res = await fetchConCsrf('/api/edicion/terminar', {
          method: 'POST',
          body: JSON.stringify({ sesion_id: sesionId })
        });
        const data = await res.json();
        if (data.exito) {
          const movidosCount = (data.movidos || []).length;
          const pendientes = (data.retiro_originales?.pendientes || []).length;
          const motivos = [...new Set((data.retiro_originales?.pendientes || []).map(p => p.error).filter(Boolean))].join(' ');
          mostrarAvisoEdicion(
            `✅ ${movidosCount} clip(s) organizados en 'videos ya editados'. ${pendientes ? `${pendientes} original(es) siguen en Sin editar en uso por CapCut; se retirarán automáticamente en segundo plano (no es necesario cerrar CapCut).` : 'Traslado completado.'} ${escapeHTML(data.export_final?.mensaje || '')} ${data.export_final?.destino ? escapeHTML(data.export_final.destino) : ''}`,
            `<button class="btn-sm" onclick="deshacerTerminarEdicion(${sesionId})" style="background:#f59e0b; color:#000; font-weight:600;">Deshacer</button>`
          );
          await cargarVistaEdicion();
        } else {
          const detalle = (data.conflictos || []).map(c => `${c.clip}: ${c.error}`).join('\n');
          const estado = data.fase === 'validacion_previa'
            ? 'No se trasladó ningún archivo: la comprobación previa encontró un problema.'
            : `Se trasladaron ${(data.movidos || []).length} clips; la sesión sigue abierta.`;
          alert(`${estado}\n${detalle || data.error || 'No se pudo completar la edición.'}\nLos archivos anteriores se conservan. Revisá el problema indicado y reintentá; no hace falta restaurar archivos si el aviso indica que están en uso.`);
          await cargarVistaEdicion();
        }
      } catch (err) {
        alert("Error de comunicación: " + String(err));
      }
    }

    async function deshacerTerminarEdicion(sesionId) {
      try {
        const res = await fetchConCsrf('/api/edicion/deshacer-terminar', {
          method: 'POST',
          body: JSON.stringify({ sesion_id: sesionId })
        });
        const data = await res.json();
        if (data.exito) {
          mostrarAvisoEdicion("⏪ Deshacer completado: clips devueltos a 'videos sin editar'.");
          await cargarVistaEdicion();
        } else {
          alert("Error al deshacer: " + (data.error || "Ruta de retorno ocupada"));
        }
      } catch (err) {
        alert("Error de comunicación: " + String(err));
      }
    }

    async function cancelarSesionEdicion(sesionId) {
      if (!confirm("¿Deseas cancelar esta sesión? Ningún archivo físico será modificado.")) return;
      try {
        const res = await fetchConCsrf('/api/edicion/cancelar-sesion', {
          method: 'POST',
          body: JSON.stringify({ sesion_id: sesionId })
        });
        const data = await res.json();
        if (data.exito) {
          mostrarAvisoEdicion("Sesión cancelada. Los clips volvieron a 'Para editar'.");
          await cargarVistaEdicion();
        }
      } catch (err) {
        alert("Error: " + String(err));
      }
    }

    function renderizarEditadosYCompletos(conteos) {
      const cont = document.getElementById('contenedor-editados-completos');
      if (!cont) return;

      const capitulos = Object.keys(conteos);
      if (capitulos.length === 0) {
        cont.innerHTML = '<p style="color:var(--text-muted); padding:10px;">No se registraron capítulos en el pendrive.</p>';
        return;
      }

      let html = `
        <table class="tabla-archivos" style="width:100%; border-collapse:collapse; margin-top:8px;">
          <thead>
            <tr style="border-bottom:1px solid var(--border); text-align:left;">
              <th style="padding:8px;">Capítulo</th>
              <th style="padding:8px; text-align:center;">Sin editar</th>
              <th style="padding:8px; text-align:center;">En edición</th>
              <th style="padding:8px; text-align:center;">Ya editados</th>
              <th style="padding:8px; text-align:center;">Completos</th>
            </tr>
          </thead>
          <tbody>
      `;

      capitulos.forEach(cap => {
        const c = conteos[cap];
        html += `
          <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
            <td style="padding:8px; font-weight:600;">${escapeHTML(cap)}</td>
            <td style="padding:8px; text-align:center; color:var(--text-muted);">${c.sin_editar}</td>
            <td style="padding:8px; text-align:center; color:#38bdf8; font-weight:600;">${c.en_edicion}</td>
            <td style="padding:8px; text-align:center; color:#10b981; font-weight:600;">${c.ya_editados}</td>
            <td style="padding:8px; text-align:center; color:#a855f7; font-weight:700;">${c.completos}</td>
          </tr>
        `;
      });

      html += '</tbody></table>';
      cont.innerHTML = html;
    }

    function renderizarExportsCapCut(exports, sesionesActivas) {
      const cont = document.getElementById('contenedor-exports-capcut');
      if (!cont) return;
      const firma = JSON.stringify([exports, sesionesActivas]);
      if (cont.dataset.firma === firma) return;
      if (Array.from(cont.querySelectorAll('video')).some(video => !video.paused)) return;
      cont.dataset.firma = firma;

      if (!exports || exports.length === 0) {
        cont.innerHTML = '<p style="color:var(--text-muted); padding:10px;">Los nuevos videos exportados por CapCut aparecerán aquí cuando termine la exportación.</p>';
        return;
      }

      let html = '<div style="display:flex; flex-direction:column; gap:10px; margin-top:8px;">';
      exports.forEach(exp => {
        const tamStr = (exp.tamano / (1024 * 1024)).toFixed(1) + ' MB';
        const selectId = `sel-sesion-export-${exp.id}`;
        const copiado = exp.estado === 'copiado';
        const estado = copiado ? 'ENVIADO AL PENDRIVE' : exp.archivo_reemplazado ? 'EXPORT REEMPLAZADO EN CAPCUT' : exp.error ? 'ERROR DE ENVÍO' : exp.sesion_id ? 'PENDIENTE DE ENVÍO' : 'ELEGIR EDICIÓN';
        html += `
          <div style="background:var(--card-alt); border:1px solid var(--border); border-radius:6px; padding:12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div>
              <span class="badge" style="background:${copiado ? '#4ade80' : '#f59e0b'}; color:#000; font-weight:600; margin-right:6px;">${estado}</span>
              <strong>${escapeHTML(exp.nombre_video || exp.nombre)}</strong>
              <span style="color:var(--text-muted); font-size:0.85rem; margin-left:6px;">(${tamStr})</span>
              <p style="color:var(--text-muted);">Export de CapCut: ${escapeHTML(exp.nombre)}</p>
              ${exp.archivo_reemplazado ? '<p>CapCut reemplazó el archivo original. Elegí el nuevo export de la lista.</p>' : `<video controls preload="none" style="width:280px; max-width:100%; max-height:220px;" src="/api/media?id=capcut%3A${exp.id}"></video>`}
              ${exp.ruta_destino ? `<p style="overflow-wrap:anywhere;">Destino: ${escapeHTML(exp.ruta_destino)}</p>` : ''}
              ${exp.error ? `<p class="error-box">${escapeHTML(exp.error)}</p>` : ''}
            </div>
            <div style="display:flex; gap:8px; align-items:center;">
              ${!copiado && !exp.archivo_reemplazado && !exp.sesion_id ? `<select id="${selectId}" style="padding:4px 8px; border:1px solid var(--border); border-radius:4px; background:var(--bg); color:var(--text); font-size:0.85rem;">
                <option value="">Seleccionar sesión...</option>
                ${sesionesActivas.map(s => `<option value="${s.id}">${escapeHTML(s.nombre)} (${escapeHTML(s.capitulo)})</option>`).join('')}
              </select>` : ''}
              ${!copiado ? `<button class="btn-sm" ${exp.archivo_reemplazado ? 'disabled' : ''} onclick="asignarExportASesion(${exp.id}, '${selectId}', ${exp.sesion_id || 'null'})" style="background:var(--accent); color:#000; font-weight:600;">Enviar al pendrive</button>
              <button class="btn-sm btn-secundario" onclick="descartarExportCapCut(${exp.id})">Descartar de la lista</button>` : ''}
              ${copiado && exp.ruta_destino ? `<button class="btn-sm btn-secundario" data-ruta="${escapeHTML(exp.ruta_destino)}" onclick="deshacerCopiaCompleto(this.dataset.ruta)">Deshacer envío</button>` : ''}
            </div>
            ${!copiado && !exp.sesion_id && !exp.archivo_reemplazado ? `<div class="export-sin-sesion">
              <p>Si este export no corresponde a una sesión pendiente, indicá su título y personaje. La copia usará ese título; el original de CapCut se conserva.</p>
              <label>Título del video <input id="titulo-export-${exp.id}" maxlength="160" placeholder="Por ejemplo: Lucie pedo" autocomplete="off"></label>
              <label>Personaje <select id="personaje-export-${exp.id}"><option value="">Elegí el personaje</option><option value="lucie">Lucie</option><option value="roli">Roli</option><option value="mailen">Mailen</option></select></label>
              <button class="btn-sm" onclick="guardarExportSinPublicar(${exp.id})">Revisar título y guardar en Sin publicar</button>
            </div>` : ''}
          </div>
        `;
      });
      html += '</div>';
      cont.innerHTML = html;
    }

    async function guardarExportSinPublicar(exportId) {
      try {
        const campoTitulo = document.getElementById('titulo-export-' + exportId);
        const campoPersonaje = document.getElementById('personaje-export-' + exportId);
        const titulo = campoTitulo?.value.trim();
        const personaje = campoPersonaje?.value;
        if (!titulo || !personaje) {
          mostrarAvisoEdicion('Escribí el título y elegí el personaje del export, o asignalo a su sesión de edición.');
          (!titulo ? campoTitulo : campoPersonaje)?.focus();
          return;
        }
        const plan = await apiFetch('/api/publicacion/resguardar-simular', {method: 'POST', body: JSON.stringify({export_id: exportId, titulo, personaje})});
        if (!confirm(`¿Guardar esta copia en Sin publicar?\nOrigen: ${plan.origen}\nDestino: ${plan.destino}\nTamaño: ${plan.tamano} bytes\nEl original de CapCut se conserva.`)) return;
        // Una edición de los campos durante la revisión exige un plan nuevo.
        if (document.getElementById('titulo-export-' + exportId) !== campoTitulo ||
            document.getElementById('personaje-export-' + exportId) !== campoPersonaje ||
            campoTitulo.value.trim() !== titulo || campoPersonaje.value !== personaje) {
          mostrarAvisoEdicion('Cambiaste el título o personaje. Revisá nuevamente el destino.');
          return;
        }
        const datos = await apiFetch('/api/publicacion/resguardar', {method: 'POST', body: JSON.stringify({token: plan.token, confirmacion: true})});
        mostrarAvisoEdicion('Video guardado en Sin publicar: ' + escapeHTML(datos.destino));
        await cargarVistaEdicion();
      } catch (error) { mostrarAvisoEdicion(escapeHTML(error.message)); }
    }

    async function asignarExportASesion(exportId, selectElemId, sesionAsociada = null) {
      const select = document.getElementById(selectElemId);
      const sesionId = sesionAsociada || (select ? select.value : '');
      if (!sesionId) {
        alert("Por favor seleccioná una sesión a la cual asociar este export.");
        return;
      }

      try {
        const res = await fetchConCsrf('/api/capcut/asignar-export', {
          method: 'POST',
          body: JSON.stringify({ export_id: exportId, sesion_id: parseInt(sesionId) })
        });
        const data = await res.json();
        if (data.exito) {
          if (data.resultado_copia && data.resultado_copia.destino) {
            const dest = data.resultado_copia.destino;
            mostrarAvisoEdicion(
              `🎬 Video copiado a 'videos completos'.`,
              `<button class="btn-sm" onclick="deshacerCopiaCompleto('${escapeHTML(dest)}')" style="background:#f59e0b; color:#000; font-weight:600;">Deshacer</button>`
            );
          } else {
            mostrarAvisoEdicion("Export asociado. Se copiará en cuanto el pendrive esté conectado.");
          }
          await cargarVistaEdicion();
        } else {
          alert("Error al asignar export: " + (data.error || "Desconocido"));
        }
      } catch (err) {
        alert("Error de comunicación: " + String(err));
      }
    }

    async function descartarExportCapCut(exportId) {
      if (!confirm("¿Deseas descartar este export de la bandeja? (No se borrará ningún archivo del disco).")) return;
      try {
        const res = await fetchConCsrf('/api/capcut/descartar-export', {
          method: 'POST',
          body: JSON.stringify({ export_id: exportId })
        });
        const data = await res.json();
        if (data.exito) {
          await cargarVistaEdicion();
        }
      } catch (err) {
        alert("Error: " + String(err));
      }
    }

    async function deshacerCopiaCompleto(videoCompletoRuta) {
      try {
        const res = await fetchConCsrf('/api/capcut/deshacer-completo', {
          method: 'POST',
          body: JSON.stringify({ video_completo_ruta: videoCompletoRuta })
        });
        const data = await res.json();
        if (data.exito) {
          mostrarAvisoEdicion("⏪ Deshacer completado: el video fue trasladado a '_revertidos' sin borrarlo.");
          await cargarVistaEdicion();
        } else {
          alert("Error al deshacer: " + (data.error || "Desconocido"));
        }
      } catch (err) {
        alert("Error de comunicación: " + String(err));
      }
    }

    async function escanearCapCutManual() {
      try {
        const res = await fetchConCsrf('/api/capcut/escanear', {
          method: 'POST',
          body: JSON.stringify({})
        });
        const data = await res.json();
        if (data.exito) {
          const nuevosCount = (data.nuevos || []).length;
          mostrarAvisoEdicion(`🔍 Escaneo de CapCut finalizado. ${nuevosCount} nuevo(s) export(s) estabilizado(s).`);
          await cargarVistaEdicion();
        }
      } catch (err) {
        alert("Error: " + String(err));
      }
    }

    function previsualizarClipPendrive(rutaRelativaOId, nombre) {
      if (clipsParaEditar && clipsParaEditar.length) {
        const idx = clipsParaEditar.findIndex(c => 
          (c.id_media && c.id_media === rutaRelativaOId) || 
          c.ruta_relativa === rutaRelativaOId || 
          c.identificador === rutaRelativaOId || 
          c.nombre === nombre
        );
        if (idx !== -1) {
          abrirVisorMedia('edicion_sin_editar', rutaRelativaOId);
          return;
        }
      }

      const visor = document.getElementById('modal-visor-media');
      const video = document.getElementById('visor-video');
      const img = document.getElementById('visor-img');
      const nombreEl = document.getElementById('visor-nombre');
      const metaEl = document.getElementById('visor-meta');
      const errBox = document.getElementById('visor-error-formato');
      const feedback = document.getElementById('visor-copiar-feedback');
      const lblChk = document.getElementById('visor-lbl-seleccion');
      const navPrev = document.querySelector('.visor-nav-prev');
      const navNext = document.querySelector('.visor-nav-next');
      if (!visor || !video) return;

      if (img) {
        img.removeAttribute('src');
        img.style.display = 'none';
      }
      if (errBox) errBox.style.display = 'none';
      if (feedback) feedback.style.display = 'none';
      if (lblChk) lblChk.style.display = 'none';
      if (navPrev) navPrev.style.display = 'none';
      if (navNext) navNext.style.display = 'none';

      if (nombreEl) nombreEl.innerText = nombre || '';
      if (metaEl) metaEl.innerText = `Para editar • ${rutaRelativaOId || ''}`;

      visorArchivoActual = {
        nombre: nombre,
        ruta: rutaRelativaOId
      };
      visorLoteIdActual = 'edicion_sin_editar';
      visorListaActual = [];
      visorIndiceActual = -1;

      video.pause();
      video.removeAttribute('src');
      video.load();

      video.onerror = () => mostrarErrorMedia(video, errBox);

      video.src = `/api/media?id=${encodeURIComponent(rutaRelativaOId)}`;
      video.style.display = 'block';
      visor.style.display = 'flex';
      visor.focus();
      video.play().catch(() => {});
    }

    cargarDatos().then(() => {
      programarSiguienteSondeo();
    });

    let planEliminacion = null;
    let eliminacionEnCurso = false;

    let carpetaEliminacionActual = '';
    let carpetasEliminacion = [];
    const seleccionEliminacion = new Set();
    let cargaEliminacionEnCurso = false;

    function actualizarSeleccionEliminacion() {
      const cantidad = seleccionEliminacion.size;
      document.getElementById('eliminacion-conteo').textContent = cantidad
        ? `${cantidad} elemento${cantidad === 1 ? '' : 's'} seleccionado${cantidad === 1 ? '' : 's'}`
        : 'Ningún elemento seleccionado';
      const boton = document.getElementById('eliminacion-simular');
      boton.disabled = !cantidad || eliminacionEnCurso || cargaEliminacionEnCurso;
      boton.textContent = cantidad ? `Eliminar seleccionados (${cantidad})` : 'Eliminar seleccionados';
      document.getElementById('eliminacion-limpiar').disabled = !cantidad || eliminacionEnCurso;
      const resumen = document.getElementById('eliminacion-seleccion');
      resumen.replaceChildren();
      seleccionEliminacion.forEach(ruta => {
        const chip = document.createElement('span');
        chip.textContent = ruta;
        resumen.append(chip);
      });
    }

    let observadorMediosEliminacion = null;

    function crearVistaPreviaEliminacion(entrada) {
      const src = `/api/media?id=${encodeURIComponent(entrada.id_media)}`;
      if (entrada.formato === 'imagen') {
        const boton = document.createElement('button');
        boton.type = 'button';
        boton.className = 'eliminacion-miniatura';
        boton.setAttribute('aria-label', `Ver imagen ${entrada.ruta}`);
        const imagen = document.createElement('img');
        imagen.src = src;
        imagen.alt = entrada.ruta.split('/').at(-1);
        imagen.loading = 'lazy';
        imagen.width = 320;
        imagen.height = 180;
        imagen.addEventListener('error', () => { imagen.hidden = true; boton.textContent = 'Vista previa no disponible'; });
        boton.append(imagen);
        boton.addEventListener('click', () => {
          const grande = document.getElementById('eliminacion-imagen-grande');
          grande.src = src;
          grande.alt = imagen.alt;
          document.getElementById('eliminacion-imagen-titulo').textContent = imagen.alt;
          document.getElementById('dialog-eliminacion-imagen').showModal();
        });
        return boton;
      }
      const contenedor = document.createElement('div');
      contenedor.className = 'eliminacion-media';
      const medio = document.createElement(entrada.formato === 'audio' ? 'audio' : 'video');
      medio.controls = true;
      medio.preload = 'none';
      medio.setAttribute('aria-label', `Reproducir ${entrada.ruta}`);
      if (entrada.formato === 'audio') {
        const icono = document.createElement('span');
        icono.className = 'eliminacion-audio-icono';
        icono.textContent = '♫';
        icono.setAttribute('aria-hidden', 'true');
        contenedor.append(icono);
        medio.src = src;
      } else {
        medio.width = 320;
        medio.height = 180;
        medio.playsInline = true;
        medio.dataset.src = src;
        medio.addEventListener('loadedmetadata', () => { if (medio.duration > .1) medio.currentTime = .1; }, {once: true});
      }
      const aviso = document.createElement('span');
      aviso.className = 'eliminacion-previa-error';
      aviso.hidden = true;
      aviso.textContent = 'El navegador no puede reproducir este formato.';
      medio.addEventListener('error', () => { aviso.hidden = false; });
      contenedor.append(medio, aviso);
      return contenedor;
    }

    function activarPreviaMediosEliminacion() {
      const videos = document.querySelectorAll('#eliminacion-lista video[data-src]');
      function cargar(video) {
        video.preload = 'metadata';
        video.src = video.dataset.src;
        delete video.dataset.src;
      }
      if (typeof IntersectionObserver === 'undefined') { videos.forEach(cargar); return; }
      observadorMediosEliminacion = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) { cargar(entry.target); observadorMediosEliminacion.unobserve(entry.target); }
        });
      }, {rootMargin: '150px'});
      videos.forEach(v => observadorMediosEliminacion.observe(v));
    }

    function mostrarCarpetasEliminacion(carpeta = '') {
      document.querySelectorAll('#eliminacion-lista video, #eliminacion-lista audio').forEach(m => m.pause());
      observadorMediosEliminacion?.disconnect();
      carpetaEliminacionActual = carpeta;
      const ubicacion = document.getElementById('eliminacion-ruta');
      ubicacion.replaceChildren();
      const partes = carpeta ? carpeta.split('/') : [];
      ['LucieSinReglas', ...partes].forEach((nombre, index) => {
        const boton = document.createElement('button');
        boton.type = 'button';
        boton.textContent = nombre;
        boton.setAttribute('aria-label', nombre);
        if (index === partes.length) boton.setAttribute('aria-current', 'location');
        boton.addEventListener('click', () => mostrarCarpetasEliminacion(partes.slice(0, index).join('/')));
        ubicacion.append(boton);
      });
      const lista = document.getElementById('eliminacion-lista');
      lista.replaceChildren();
      const leyenda = document.createElement('legend');
      leyenda.textContent = carpeta ? `Contenido de ${partes.at(-1)}` : 'Carpetas y multimedia del proyecto';
      lista.append(leyenda);
      const visibles = carpetasEliminacion.filter(entrada => {
        const idx = entrada.ruta.lastIndexOf('/');
        return (idx < 0 ? '' : entrada.ruta.slice(0, idx)) === carpeta;
      });
      visibles.forEach(entrada => {
        const tarjeta = document.createElement('div');
        tarjeta.className = 'eliminacion-carpeta';
        const etiqueta = document.createElement('label');
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.value = entrada.ruta;
        check.checked = seleccionEliminacion.has(entrada.ruta);
        check.setAttribute('aria-label', `Seleccionar ${entrada.ruta}`);
        check.addEventListener('change', () => {
          if (check.checked) seleccionEliminacion.add(entrada.ruta);
          else seleccionEliminacion.delete(entrada.ruta);
          actualizarSeleccionEliminacion();
        });
        const nombre = document.createElement('span');
        nombre.textContent = entrada.ruta.split('/').at(-1);
        const icono = document.createElement('span');
        icono.className = 'eliminacion-icono';
        icono.textContent = entrada.tipo === 'carpeta' ? '📁' : (entrada.formato === 'audio' ? '🎵' : (entrada.formato === 'video' ? '🎬' : '🖼️'));
        icono.setAttribute('aria-hidden', 'true');
        etiqueta.append(check, icono, nombre);
        tarjeta.append(etiqueta);
        if (entrada.tipo === 'carpeta') {
          const abrir = document.createElement('button');
          abrir.type = 'button';
          abrir.className = 'eliminacion-abrir';
          abrir.textContent = 'Abrir →';
          abrir.setAttribute('aria-label', `Abrir ${entrada.ruta}`);
          abrir.addEventListener('click', () => mostrarCarpetasEliminacion(entrada.ruta));
          tarjeta.append(abrir);
        } else {
          tarjeta.classList.add('eliminacion-archivo');
          tarjeta.append(crearVistaPreviaEliminacion(entrada));
          const info = document.createElement('small');
          info.textContent = `${entrada.formato.toUpperCase()} · ${(entrada.tamano / 1024 / 1024).toFixed(2)} MB`;
          tarjeta.append(info);
        }
        lista.append(tarjeta);
      });
      if (!visibles.length) {
        const vacio = document.createElement('p');
        vacio.className = 'eliminacion-vacio';
        vacio.textContent = carpeta ? 'No hay subcarpetas, videos, imágenes ni MP3 en esta carpeta.' : 'No hay carpetas ni multimedia disponibles en el proyecto.';
        lista.append(vacio);
      }
      activarPreviaMediosEliminacion();
      actualizarSeleccionEliminacion();
    }

    async function cargarEliminacion(forzar = false) {
      if (!document.getElementById('eliminacion-lista') || eliminacionEnCurso || cargaEliminacionEnCurso || (!forzar && seleccionEliminacion.size)) return;
      const estado = document.getElementById('eliminacion-estado');
      cargaEliminacionEnCurso = true;
      actualizarSeleccionEliminacion();
      estado.textContent = 'Cargando carpetas del proyecto…';
      try {
        const datos = await apiFetch('/api/pendrive/eliminacion');
        carpetasEliminacion = datos.entradas;
        document.getElementById('eliminacion-raiz').textContent = datos.ruta_proyecto;
        const disponibles = new Set(carpetasEliminacion.map(e => e.ruta));
        seleccionEliminacion.forEach(ruta => { if (!disponibles.has(ruta)) seleccionEliminacion.delete(ruta); });
        if (carpetaEliminacionActual && !carpetasEliminacion.some(e => e.ruta === carpetaEliminacionActual && e.tipo === 'carpeta')) carpetaEliminacionActual = '';
        mostrarCarpetasEliminacion(carpetaEliminacionActual);
        estado.textContent = 'Marcá los elementos que quieras eliminar y presioná Eliminar seleccionados.';
      } catch (e) {
        carpetasEliminacion = [];
        seleccionEliminacion.clear();
        mostrarCarpetasEliminacion();
        document.getElementById('eliminacion-raiz').textContent = 'Pendrive no disponible';
        estado.textContent = e.message;
      } finally {
        cargaEliminacionEnCurso = false;
        actualizarSeleccionEliminacion();
      }
    }

    async function simularEliminacion() {
      const seleccion = Array.from(seleccionEliminacion);
      const boton = document.getElementById('eliminacion-simular');
      boton.disabled = true;
      document.getElementById('eliminacion-estado').textContent = 'Preparando la revisión de los elementos seleccionados…';
      try {
        planEliminacion = await apiFetch('/api/pendrive/eliminacion-simular', {
          method: 'POST', body: JSON.stringify({seleccion})
        });
        const detalle = document.getElementById('eliminacion-detalle');
        detalle.replaceChildren();
        planEliminacion.entradas.forEach(e => {
          const li = document.createElement('li');
          li.textContent = `${e.tipo}: ${e.ruta} (${e.tamano} bytes)`;
          detalle.append(li);
        });
        document.getElementById('eliminacion-resumen').textContent = `${planEliminacion.entradas.length} elementos · ${planEliminacion.total_bytes} bytes · Pendrive ${planEliminacion.pendrive_id}`;
        document.getElementById('eliminacion-confirmacion').value = '';
        document.getElementById('eliminacion-ejecutar').disabled = true;
        document.getElementById('dialog-eliminacion').showModal();
      } catch (e) { document.getElementById('eliminacion-estado').textContent = e.message; }
      finally { boton.disabled = seleccion.length === 0; }
    }

    async function ejecutarEliminacionManual() {
      const confirmacion = document.getElementById('eliminacion-confirmacion').value;
      if (!planEliminacion || confirmacion !== 'ELIMINAR' || eliminacionEnCurso) return;
      eliminacionEnCurso = true;
      const boton = document.getElementById('eliminacion-ejecutar');
      const cancelar = document.getElementById('eliminacion-cancelar');
      boton.disabled = cancelar.disabled = true;
      const estado = document.getElementById('eliminacion-estado');
      estado.textContent = 'Eliminando los elementos confirmados…';
      try {
        const resultado = await apiFetch('/api/pendrive/eliminar', {
          method: 'POST', body: JSON.stringify({token: planEliminacion.token, confirmacion})
        });
        document.getElementById('dialog-eliminacion').close();
        eliminacionEnCurso = false;
        seleccionEliminacion.clear();
        await cargarEliminacion(true);
        estado.textContent = `Eliminados: ${resultado.eliminados.length}. ` +
          (resultado.errores.length ? `Se detuvo: ${resultado.errores.map(e => `${e.ruta}: ${e.error}`).join('; ')}` : 'Borrado manual completado.');
      } catch (e) {
        document.getElementById('dialog-eliminacion').close();
        estado.textContent = `${e.message} Revisá el estado del pendrive antes de volver a simular.`;
      } finally {
        planEliminacion = null;
        eliminacionEnCurso = false;
        cancelar.disabled = false;
      }
    }

    function conectarEliminacionManual() {
      const eventos = [
        ['nav-btn-eliminacion', 'click', () => mostrarPestana('eliminacion')],
        ['eliminacion-refrescar', 'click', () => cargarEliminacion(true)],
        ['eliminacion-limpiar', 'click', () => {
          seleccionEliminacion.clear();
          mostrarCarpetasEliminacion(carpetaEliminacionActual);
        }],
        ['eliminacion-simular', 'click', simularEliminacion],
        ['eliminacion-ejecutar', 'click', ejecutarEliminacionManual],
        ['eliminacion-confirmacion', 'input', e => {
          document.getElementById('eliminacion-ejecutar').disabled = eliminacionEnCurso || e.target.value !== 'ELIMINAR';
        }],
        ['eliminacion-cancelar', 'click', () => document.getElementById('dialog-eliminacion').close()],
        ['dialog-eliminacion', 'cancel', e => { if (eliminacionEnCurso) e.preventDefault(); }],
        ['dialog-eliminacion', 'close', () => { planEliminacion = null; }]
      ];
      eventos.forEach(([id, tipo, fn]) => {
        const el = document.getElementById(id);
        if (el && typeof el.addEventListener === 'function') el.addEventListener(tipo, fn);
      });
    }
    conectarEliminacionManual();
