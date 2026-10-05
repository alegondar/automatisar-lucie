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
    let terminarCapituloTrasMover = false;
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
      const idsModales = ['modal-simulacion', 'modal-terminar-capitulo', 'modal-descartar-capitulo', 'modal-plan-envio', 'modal-vincular-pendrive'];
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

    function cerrarAviso() {
      const banner = document.getElementById('banner-aviso');
      banner.style.display = 'none';
      operacionAvisoActual = null;
    }

    async function deshacerDesdeAviso() {
      if (!operacionAvisoActual) return;
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
      document.getElementById('sec-historial').style.display = (pestana === 'historial') ? 'block' : 'none';

      if (pestana === 'historial') {
        cargarHistorial();
      } else if (pestana === 'pendrive') {
        cargarVistaPendrive();
      } else if (pestana === 'capitulos-abiertos') {
        cargarCapitulosAbiertos();
      } else if (pestana === 'capitulos-cerrados') {
        cargarCapitulosCerrados();
      } else if (pestana === 'descartados') {
        cargarCapitulosDescartados();
      }
    }

    async function recargarVistaActual() {
      if (pestanaActual === 'historial') {
        await cargarHistorial();
      } else if (pestanaActual === 'pendrive') {
        await cargarVistaPendrive();
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

    async function apiFetch(url, options = {}) {
      options.headers = options.headers || {};
      if (options.method && options.method.toUpperCase() === 'POST') {
        options.headers['Content-Type'] = 'application/json';
        options.headers['X-CSRF-Token'] = CSRF_TOKEN;
      }
      const res = await fetch(url, options);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(err.error || 'Error en la petición');
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
        let cap = res.capitulo_foco || res.capitulo;
        let bal = res.balance || { pendientes: 0, movidos: 0 };

        if (idCap && datosEstado.capitulos_abiertos) {
          const capObj = datosEstado.capitulos_abiertos.find(c => c.id === idCap);
          if (capObj) {
            cap = capObj;
            bal = capObj.balance || bal;
          }
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

    async function ejecutarTerminarCapitulo(trasMover) {
      try {
        const payload = {
          accion: trasMover ? 'mover_pendientes' : 'sin_mover'
        };
        if (capituloATerminarId !== null) {
          payload.id = capituloATerminarId;
        }
        await apiFetch('/api/capitulos/terminar', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        cerrarModalTerminarCapitulo();
        await cargarDatos();
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
      cerrarModalTerminarCapitulo();
      const cap = datosEstado.capitulo_activo;
      if (!cap || !cap.habilitado) {
        await ejecutarTerminarCapitulo(false);
        return;
      }
      const lotesCapitulo = datosEstado.lotes.filter(l =>
        (l.personaje_sugerido === cap.personaje || cap.personaje) &&
        (l.escena_sugerida === cap.nombre || l.raiz_escena === `${cap.personaje}::${cap.nombre}`)
      );
      if (!lotesCapitulo.length) {
        await ejecutarTerminarCapitulo(true);
        return;
      }
      terminarCapituloTrasMover = true;
      if (lotesCapitulo.length === 1) {
        await simularMoverLote(lotesCapitulo[0].lote_id);
      } else {
        await simularMoverLotesListos();
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

    function generarHtmlCardLote(lote) {
      const capFoco = (datosEstado.capitulo_foco && datosEstado.capitulo_foco.habilitado) ? datosEstado.capitulo_foco : 
                      ((datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado) ? datosEstado.capitulo_activo : null);
      const capsAbiertos = datosEstado.capitulos_abiertos || [];
      const nombresAbiertos = new Set(capsAbiertos.map(c => c.nombre));

      const persPre = capFoco ? capFoco.personaje : (lote.personaje_sugerido || datosEstado.ultimo_personaje || 'lucie');
      const escenaPre = capFoco ? capFoco.nombre : (lote.escena_sugerida || '');

      const persOptions = datosEstado.personajes.map(p => 
        `<option value="${p.id}" ${p.id === persPre ? 'selected' : ''}>${p.nombre}</option>`
      ).join('');

      let optFoco = '';
      if (capFoco) {
        optFoco = `<option value="${escapeHTML(capFoco.nombre)}" data-tipo="capitulo_foco" data-personaje="${escapeHTML(capFoco.personaje)}" selected>[Capítulo en foco] ${escapeHTML(capFoco.nombre)}</option>`;
      }

      const optsAbiertosSecundarios = capsAbiertos
        .filter(c => !capFoco || c.id !== capFoco.id)
        .map(c => {
          const isSelected = (!capFoco && c.nombre === escenaPre);
          return `<option value="${escapeHTML(c.nombre)}" data-tipo="capitulo_abierto" data-personaje="${escapeHTML(c.personaje)}" ${isSelected ? 'selected' : ''}>[Capítulo abierto] ${escapeHTML(c.personaje)}/${escapeHTML(c.nombre)}</option>`;
        })
        .join('');

      const matchAbiertoSecundario = !capFoco && capsAbiertos.some(c => c.nombre === escenaPre);
      const matchOtraEscena = !capFoco && (datosEstado.escenas || []).some(e => !nombresAbiertos.has(e.nombre) && e.nombre === escenaPre);
      const esNueva = !capFoco && !matchAbiertoSecundario && !matchOtraEscena;

      const optNueva = `<option value="__nueva__" ${esNueva ? 'selected' : ''}>+ Crear nueva escena...</option>`;

      const otrasEscenas = (datosEstado.escenas || [])
        .filter(e => !nombresAbiertos.has(e.nombre))
        .map(e => `<option value="${escapeHTML(e.nombre)}" data-tipo="${e.tipo}" ${(matchOtraEscena && e.nombre === escenaPre) ? 'selected' : ''}>[${e.tipo === 'descargas_alias' ? 'En Descargas' : 'Destino'}] ${escapeHTML(e.nombre)}</option>`)
        .join('');

      const escenasOptions = optFoco + optsAbiertosSecundarios + optNueva + otrasEscenas;

      return `
        <div class="card" id="card-${lote.lote_id}">
          <div class="card-header">
            <div style="display:flex; align-items:center; gap:10px;">
              <input type="checkbox" class="cb-lote-listo" data-lote-id="${lote.lote_id}" checked title="Tildar para mover con 'Mover lotes listos'">
              <h3>Lote #${lote.numero} (${lote.total_archivos} archivos &bull; ${formatearBytes(lote.total_bytes)})</h3>
            </div>
            <span style="color:var(--text-muted);font-size:0.85rem">${lote.fecha}</span>
          </div>
          <div class="lote-toolbar">
            <span id="lbl-sel-${lote.lote_id}" style="font-size:0.85rem; color:var(--text-muted);">${lote.archivos.length} seleccionados</span>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${lote.lote_id}', true)">Seleccionar todos</button>
              <button type="button" class="btn-sm" onclick="seleccionarTodosLote('${lote.lote_id}', false)">Ninguno</button>
            </div>
          </div>
          <div class="archivos-grid">
            ${lote.archivos.map(a => `
              <div class="archivo-item" title="Archivo: ${a.nombre}&#10;Fecha llegada: ${a.fecha_llegada || a.fecha || ''}&#10;Fecha modificación: ${a.fecha || ''}&#10;Tamaño: ${formatearBytes(a.tamanio)}">
                <div class="chk-container">
                  <input type="checkbox" class="chk-archivo chk-lote-${lote.lote_id}" data-id="${a.id_db}" checked onchange="actualizarSeleccionLote('${lote.lote_id}')">
                </div>
                <div class="miniatura-wrap">
                  <img src="/api/miniatura?id=${a.id_db}" alt="${a.nombre}" onerror="this.onerror=null;this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect width=%22100%%22 height=%22100%%22 fill=%22%23222%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23888%22 text-anchor=%22middle%22 dy=%22.3em%22>Media</text></svg>';">
                </div>
                <div class="archivo-meta">
                  <div class="archivo-nombre" title="${a.nombre}">${a.nombre}</div>
                  <div class="archivo-peso">${formatearBytes(a.tamanio)}</div>
                  <div class="archivo-llegada" style="font-size:0.75rem; color:var(--text-muted);" title="Fecha de llegada: ${a.fecha_llegada || a.fecha || ''}">🕒 ${a.fecha_llegada || a.fecha || ''}</div>
                </div>
              </div>
            `).join('')}
          </div>
          <div class="form-row">
            <label>Personaje: <select id="sel-pers-${lote.lote_id}">${persOptions}</select></label>
            <label>Escena:
              <select id="sel-escena-${lote.lote_id}" onchange="toggleNuevaEscena('${lote.lote_id}', this.value)">
                ${escenasOptions}
              </select>
            </label>
            <div class="campo-escena-wrap">
              <input type="text" id="txt-nueva-escena-${lote.lote_id}" value="${esNueva ? escapeHTML(escenaPre) : ''}" placeholder="Nombre de escena nueva" style="max-width:200px; display:${esNueva ? 'inline-block' : 'none'};" oninput="validarInputEscena('${lote.lote_id}')">
              <span id="error-escena-${lote.lote_id}" class="error-inline" style="display:none;"></span>
            </div>
            <button class="btn-accion" id="btn-mover-${lote.lote_id}" onclick="iniciarMover('${lote.lote_id}')">Mover seleccionados (${lote.archivos.length})</button>
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
        .map(e => `<option value="${escapeHTML(e.nombre)}" data-tipo="${e.tipo}">[${e.tipo === 'descargas_alias' ? 'En Descargas' : 'Destino'}] ${escapeHTML(e.nombre)}</option>`)
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
            ${lote.archivos.map(a => `
              <div class="archivo-item" title="Archivo: ${a.nombre}&#10;Fecha llegada: ${a.fecha_llegada || a.fecha || ''}&#10;Fecha modificación: ${a.fecha || ''}&#10;Tamaño: ${formatearBytes(a.tamanio)}">
                <div class="chk-container">
                  <input type="checkbox" class="chk-archivo chk-lote-${lote.lote_id}" data-id="${a.id_db}" onchange="actualizarSeleccionLote('${lote.lote_id}')">
                </div>
                <div class="miniatura-wrap">
                  <img src="/api/miniatura?id=${a.id_db}" alt="${a.nombre}" onerror="this.onerror=null;this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect width=%22100%%22 height=%22100%%22 fill=%22%23222%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23888%22 text-anchor=%22middle%22 dy=%22.3em%22>Media</text></svg>';">
                </div>
                <div class="archivo-meta">
                  <div class="archivo-nombre" title="${a.nombre}">${a.nombre}</div>
                  <div class="archivo-peso">${formatearBytes(a.tamanio)}</div>
                  <div class="archivo-llegada" style="font-size:0.75rem; color:var(--text-muted);" title="Fecha de llegada: ${a.fecha_llegada || a.fecha || ''}">🕒 ${a.fecha_llegada || a.fecha || ''}</div>
                </div>
              </div>
            `).join('')}
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
              <input type="text" id="txt-nueva-escena-${lote.lote_id}" value="" placeholder="Nombre de escena nueva" style="max-width:200px; display:inline-block;" oninput="validarInputEscena('${lote.lote_id}')">
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
        return;
      }
      cont.innerHTML = lotesActivos.map(lote => generarHtmlCardLote(lote)).join('');
    }

    function renderLotesIncremental() {
      const cont = document.getElementById('contenedor-lotes');
      const lotesActivos = (datosEstado.lotes || []).filter(l => !l.es_anterior);
      if (!lotesActivos.length) {
        cont.innerHTML = '<div class="card"><p style="color:var(--text-muted)">No hay nuevos lotes de candidatos en ~/Descargas.</p></div>';
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
    }

    function renderLotesAnteriores() {
      const sec = document.getElementById('sec-lotes-anteriores');
      const cont = document.getElementById('contenedor-lotes-anteriores');
      const conteo = document.getElementById('conteo-lotes-anteriores');
      if (!sec || !cont) return;

      const capActivo = datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado ? datosEstado.capitulo_activo : null;
      const lotesAnt = datosEstado.lotes_anteriores || [];

      if (!capActivo || !lotesAnt.length) {
        sec.style.display = 'none';
        cont.innerHTML = '';
        if (conteo) conteo.innerText = '0';
        return;
      }

      sec.style.display = 'block';
      if (conteo) conteo.innerText = String(lotesAnt.length);
      cont.innerHTML = lotesAnt.map(lote => generarHtmlCardLoteAnterior(lote)).join('');
    }

    function renderLotesAnterioresIncremental() {
      const sec = document.getElementById('sec-lotes-anteriores');
      const cont = document.getElementById('contenedor-lotes-anteriores');
      const conteo = document.getElementById('conteo-lotes-anteriores');
      if (!sec || !cont) return;

      const capActivo = datosEstado.capitulo_activo && datosEstado.capitulo_activo.habilitado ? datosEstado.capitulo_activo : null;
      const lotesAnt = datosEstado.lotes_anteriores || [];

      if (!capActivo || !lotesAnt.length) {
        sec.style.display = 'none';
        cont.innerHTML = '';
        if (conteo) conteo.innerText = '0';
        return;
      }

      sec.style.display = 'block';
      if (conteo) conteo.innerText = String(lotesAnt.length);

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
    }

    function seleccionarTodosLote(loteId, marcar) {
      const checkboxes = document.querySelectorAll(`.chk-lote-${loteId}`);
      checkboxes.forEach(cb => { cb.checked = marcar; });
      actualizarSeleccionLote(loteId);
    }

    function actualizarSeleccionLote(loteId) {
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

    function validarInputEscena(loteId) {
      const input = document.getElementById(`txt-nueva-escena-${loteId}`);
      const errSpan = document.getElementById(`error-escena-${loteId}`);
      if (!input || !errSpan) return true;

      const selEscena = document.getElementById(`sel-escena-${loteId}`).value;
      if (selEscena !== '__nueva__') {
        errSpan.style.display = 'none';
        errSpan.innerText = '';
        return true;
      }

      const error = validarNombreEscena(input.value);
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
        validarInputEscena(loteId);
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
            <tr><th>Archivo</th><th>Tamaño</th><th>Acción</th></tr>
          </thead>
          <tbody>
            ${datosEstado.sin_identificar.map(a => `
              <tr>
                <td>${a.nombre}</td>
                <td>${formatearBytes(a.tamanio)}</td>
                <td>
                  <button class="btn-accion" style="padding:4px 8px;font-size:0.75rem;" onclick="clasificarSinId('${a.hash}', '${a.ruta.replace(/'/g, "\\\\\\'")}', true)">Del Proyecto</button>
                  <button class="btn-cancelar" style="padding:4px 8px;font-size:0.75rem;" onclick="clasificarSinId('${a.hash}', '${a.ruta.replace(/'/g, "\\\\\\'")}', false)">Ignorar</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }

    async function clasificarSinId(hash, ruta, esProyecto) {
      try {
        await apiFetch('/api/clasificar-sin-identificar', {
          method: 'POST',
          body: JSON.stringify({ hash, ruta, es_proyecto: esProyecto })
        });
        await cargarDatos();
      } catch (e) {
        mostrarError(e.message);
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

      if (selEscena === '__nueva__') {
        if (!validarInputEscena(loteId)) {
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

        if (selEscena === '__nueva__') {
          if (!validarInputEscena(loteId)) {
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
      terminarCapituloTrasMover = false;
      programarSiguienteSondeo(500);
    }

    async function ejecutarMoverLote() {
      if (!simulacionActiva) return;
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

        if (terminarCapituloTrasMover) {
          terminarCapituloTrasMover = false;
          try {
            await apiFetch('/api/capitulos/terminar', {
              method: 'POST',
              body: JSON.stringify({ accion: 'mover_pendientes' })
            });
          } catch (errTerminar) {
            console.error('Error al terminar capítulo tras mover:', errTerminar);
          }
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
            res.personaje || simulacionActiva.personaje,
            res.escena || simulacionActiva.escena,
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
      return (b / 1048576).toFixed(1) + ' MB';
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

    async function abrirModalPlanEnvio(capitulo = null) {
      try {
        const modal = document.getElementById('modal-plan-envio');
        const cont = document.getElementById('contenido-plan-envio');
        const btnConfirm = document.getElementById('btn-confirmar-envio-pendrive');

        btnConfirm.disabled = true;
        btnConfirm.style.cursor = 'not-allowed';
        btnConfirm.style.opacity = '0.5';

        cont.innerHTML = '<p style="color:var(--text-muted); padding:20px 0;">Calculando simulación de envío y verificando pendrive...</p>';
        modal.style.display = 'flex';

        const body = capitulo ? { capitulos: [capitulo] } : {};
        const sim = await apiFetch('/api/pendrive/envio-simular', {
          method: 'POST',
          body: JSON.stringify(body)
        });

        planEnvioActivo = sim;

        let alertasHtml = '';
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
              <strong>ℹ️ Archivos omitidos (ya enviados anteriormente o no multimedia):</strong>
              <ul style="margin:6px 0 0 18px;">
                ${sim.archivos_omitidos.map(o => `<li><code>${escapeHTML(o.nombre)}</code>: ${escapeHTML(o.motivo)}</li>`).join('')}
              </ul>
            </div>
          `;
        }

        const infoPendrive = `
          <div style="display:flex; flex-wrap:wrap; gap:16px; background:var(--card-alt); padding:12px 16px; border-radius:6px; margin-bottom:14px; font-size:0.85rem;">
            <div><strong>Pendrive ID:</strong> <code>${escapeHTML((sim.pendrive_id || '').slice(0, 8))}...</code></div>
            <div><strong>Punto montaje:</strong> <code>${escapeHTML(sim.punto_montaje || '')}</code></div>
            <div><strong>Filesystem:</strong> <code>${escapeHTML(sim.sistema_archivos || '')}</code></div>
            <div><strong>Espacio libre:</strong> ${escapeHTML(sim.espacio_libre_fmt || '0 B')} (Margen: ${escapeHTML(sim.margen_libre_fmt || '1 GiB')})</div>
            <div><strong>Total a enviar:</strong> <strong>${sim.total_archivos_a_enviar} archivo(s)</strong> (${escapeHTML(sim.bytes_a_enviar_fmt || '0 B')})</div>
          </div>
        `;

        let tablaArchivos = '';
        if (sim.archivos && sim.archivos.length > 0) {
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
                ${sim.archivos.map(a => {
                  const tagTipo = a.tipo === 'video' ? '<span class="tag-tipo tag-video">VIDEO</span>' : '<span class="tag-tipo tag-imagen">IMAGEN</span>';
                  const badgeEstado = a.conflicto
                    ? '<span style="color:var(--danger); font-weight:bold;">⚠️ Conflicto (hash distinto)</span>'
                    : '<span style="color:var(--teal); font-weight:600;">Listo para enviar</span>';
                  return `
                    <tr style="${a.conflicto ? 'background:rgba(207, 102, 121, 0.1);' : ''}">
                      <td><strong>${escapeHTML(a.nombre)}</strong></td>
                      <td>${tagTipo}</td>
                      <td>${escapeHTML(a.tamanio_fmt || formatearBytes(a.tamanio_bytes))}</td>
                      <td class="ruta-celda"><code style="color:var(--teal)">${escapeHTML(a.destino_relativo)}</code></td>
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
        mostrarError(e.message);
        cerrarModalPlanEnvio();
      }
    }

    function cerrarModalPlanEnvio() {
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

    async function cargarVistaPendrive() {
      const contEstado = document.getElementById('contenedor-estado-pendrive');
      const contCaps = document.getElementById('contenedor-capitulos-pendrive');
      const cardPart = document.getElementById('card-part-pendrive');
      const contPart = document.getElementById('contenedor-part-pendrive');
      const contHist = document.getElementById('contenedor-historial-pendrive');
      const btnVincular = document.getElementById('btn-vincular-pendrive');
      const btnEnviarTodos = document.getElementById('btn-enviar-todos-pendrive');

      if (!contEstado) return;

      try {
        const [estadoPen, histRes] = await Promise.all([
          apiFetch('/api/pendrive/estado'),
          apiFetch('/api/historial').catch(() => ({ historial: [] }))
        ]);

        // 1. Tarjeta Estado Físico
        if (estadoPen.sin_respuesta) {
          contEstado.innerHTML = `
            <div style="background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; padding:16px; border-radius:6px; color:#fef3c7;">
              <h3 style="display:flex; align-items:center; gap:8px;">⚠️ Pendrive sin respuesta</h3>
              <p style="margin-top:6px; font-size:0.9rem;">El dispositivo montado no responde a las solicitudes de lectura dentro del tiempo límite de 3 segundos.</p>
            </div>
          `;
          if (btnVincular) btnVincular.style.display = 'none';
          if (btnEnviarTodos) btnEnviarTodos.disabled = true;
        } else if (!estadoPen.conectado) {
          const cand = estadoPen.unidad_candidata;
          if (cand) {
            contEstado.innerHTML = `
              <div style="background:rgba(99, 102, 241, 0.1); border:1px solid #6366f1; padding:16px; border-radius:6px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <div>
                    <h3 style="color:#e0e7ff;">Unidad candidata detectada (sin vincular)</h3>
                    <p style="color:var(--text-muted); font-size:0.85rem; margin-top:4px;">
                      Punto de montaje: <code>${escapeHTML(cand.punto_montaje)}</code> &bull; Filesystem: <code>${escapeHTML(cand.sistema_archivos || 'desconocido')}</code> &bull; Libre: ${escapeHTML(cand.espacio_libre_fmt)}
                    </p>
                  </div>
                  <button class="btn-sm" onclick="abrirModalVincularPendrive('${escapeHTML(cand.punto_montaje)}')" style="background:var(--accent); color:#000; font-weight:700; padding:8px 18px; border:none; border-radius:4px; cursor:pointer;">
                    Vincular pendrive
                  </button>
                </div>
              </div>
            `;
            if (btnVincular) btnVincular.style.display = 'none';
          } else {
            contEstado.innerHTML = `
              <div style="background:var(--card-alt); padding:16px; border-radius:6px; color:var(--text-muted);">
                <p>🔌 Ningún pendrive vinculado detectado en el sistema.</p>
                <small>Conectá tu pendrive para transferir el material o vincularlo por primera vez.</small>
              </div>
            `;
            if (btnVincular) btnVincular.style.display = 'inline-block';
          }
          if (btnEnviarTodos) btnEnviarTodos.disabled = true;
        } else {
          // Pendrive Conectado y Vinculado
          if (btnVincular) btnVincular.style.display = 'none';
          if (btnEnviarTodos) btnEnviarTodos.disabled = (estadoPen.archivos_pendientes_conteo === 0);

          contEstado.innerHTML = `
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px;">
              <div style="background:var(--card-alt); padding:12px; border-radius:6px; border:1px solid var(--border);">
                <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase;">Estado</div>
                <div style="font-size:1.1rem; font-weight:700; color:var(--teal); margin-top:4px;">● Conectado y Vinculado</div>
              </div>
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

        // 2. Capítulos Pendientes
        const capsPendientes = estadoPen.capitulos_pendientes || [];
        if (!capsPendientes.length) {
          contCaps.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No hay archivos en la sala de espera listos para transferir.</p>';
        } else {
          contCaps.innerHTML = `
            <table class="tabla-historial">
              <thead>
                <tr>
                  <th style="width:15%;">Personaje</th>
                  <th style="width:25%;">Capítulo</th>
                  <th style="width:12%; text-align:center;">Videos</th>
                  <th style="width:12%; text-align:center;">Fotos</th>
                  <th style="width:16%;">Tamaño</th>
                  <th style="width:20%; text-align:center;">Acción</th>
                </tr>
              </thead>
              <tbody>
                ${capsPendientes.map(c => `
                  <tr>
                    <td><code>${escapeHTML(c.personaje)}</code></td>
                    <td><strong>${escapeHTML(c.capitulo)}</strong></td>
                    <td style="text-align:center;"><span class="tag-tipo tag-video">${c.videos}</span></td>
                    <td style="text-align:center;"><span class="tag-tipo tag-imagen">${c.fotos}</span></td>
                    <td>${escapeHTML(c.bytes_totales_fmt)}</td>
                    <td style="text-align:center;">
                      <button class="btn-sm" onclick="abrirModalPlanEnvio('${escapeHTML(c.personaje)}/${escapeHTML(c.capitulo)}')" style="background:#10b981; color:#000; font-weight:600; padding:6px 14px; border:none; border-radius:4px; cursor:pointer;" title="Enviar este capítulo">
                        Enviar al pendrive
                      </button>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          `;
        }

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

    cargarDatos().then(() => {
      programarSiguienteSondeo();
    });
