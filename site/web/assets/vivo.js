/* Live data for the site's pages.
 *
 * Any element carrying data-vivo="<key>" is filled from the server's public
 * status (/api/status.json, every minute) and the character ranking
 * (/api/saga.json, every five minutes); values that run on their own (uptime,
 * time to restart, the world clock) tick every second in between.
 *
 * No ids: the same value can appear any number of times, in any block, and a
 * block can be copied or removed without breaking anything. The in-page editor
 * reads CATALOG to offer these values for dragging.
 *
 * Extra hooks: data-vivo-pulso gets the class "ligado"/"desligado"; an element
 * showing the world clock gets "parado" while nobody is online.
 */
(function () {
  'use strict';
  if (window.HeimdallVivo) return;

  var status = null, anchor = 0, saga = null, enabledFeatures = null;

  function period(h) {
    if (h < 5) return 'madrugada';
    if (h < 7) return 'amanhecer';
    if (h < 12) return 'manhã';
    if (h < 14) return 'meio-dia';
    if (h < 18) return 'tarde';
    if (h < 20) return 'entardecer';
    return 'noite';
  }
  function duration(s) {
    if (s == null || s < 0) return '—';
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    if (d > 0) return d + (d === 1 ? ' dia' : ' dias') + (h ? ' e ' + h + 'h' : '');
    if (h > 0) return h + 'h' + (m ? ' ' + String(m).padStart(2, '0') + 'min' : '');
    return m + ' min';
  }
  function remaining(s) {
    if (s == null || s < 0) return '—';
    var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
    if (h > 0) return 'em ' + h + 'h ' + String(m).padStart(2, '0') + 'min';
    if (m > 0) return 'em ' + m + ' min';
    return 'a qualquer momento';
  }
  var elapsed = function () { return Math.floor((Date.now() - anchor) / 1000); };
  var on = function () { return !!(status && status.online); };

  // Same arithmetic as the game (EnvMan.RescaleDayFraction): the light band
  // [dawn, dusk] maps to [0.25, 0.75], which on a 24h dial is 06:00 to 18:00.
  // The world clock only runs with someone online; it is frozen otherwise.
  function worldClock() {
    var tj = status && status.tempo_de_jogo;
    if (!tj || !on()) return null;
    var running = tj.correndo !== false;
    var sec = (tj.segundos_mundo || 0) + (running ? elapsed() : 0), day = tj.duracao_dia_seg || 1800;
    var fm = tj.fracao_manha != null ? tj.fracao_manha : 0.15;
    var low = Math.min(Math.max(fm, 0.001), 0.499), high = 1 - low;
    var n = Math.floor(sec / day), fr = (sec % day) / day, r;
    if (fr < low) r = fr / low * 0.25;
    else if (fr > high) r = 0.75 + (fr - high) / low * 0.25;
    else r = 0.25 + (fr - low) / (high - low) * 0.5;
    var h24 = (r * 24) % 24, hh = Math.floor(h24), mm = Math.floor((h24 % 1) * 60);
    return {text: String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0'),
            day: n, hour: hh, running: running, hours: tj.horas_de_mundo};
  }
  function currentSeason() {
    var e = status && status.estacoes;
    if (!e || !e.lista) return null;
    for (var i = 0; i < e.lista.length; i++) if (e.lista[i].atual) return e.lista[i];
    return null;
  }
  function split(address) {
    var i = (address || '').lastIndexOf(':');
    return i > 0 ? [address.slice(0, i), address.slice(i)] : [address || '', ''];
  }
  var s = function () { return (status && status.servidor) || {}; };
  var j = function () { return (status && status.jogadores) || {}; };

  // key -> {rotulo, descricao, grupo, valor(), classe?}
  var CATALOG = {
    estado: {rotulo: 'Estado do servidor', grupo: 'Servidor', descricao: '"no ar" ou "fora do ar".',
      valor: function () { return status ? (on() ? 'no ar' : 'fora do ar') : 'verificando…'; }},
    mundo: {rotulo: 'Nome do mundo', grupo: 'Servidor', descricao: 'O mundo que o servidor está rodando.',
      valor: function () { return s().mundo || '—'; }},
    endereco: {rotulo: 'Endereço completo', grupo: 'Servidor', descricao: 'Endereço para entrar (host:porta).',
      valor: function () { return s().endereco || '—'; }},
    endereco_host: {rotulo: 'Endereço sem porta', grupo: 'Servidor', descricao: 'Só o nome do servidor.',
      valor: function () { return split(s().endereco)[0] || '—'; }},
    endereco_porta: {rotulo: 'Porta', grupo: 'Servidor', descricao: 'Só a porta, com os dois-pontos.',
      valor: function () { return split(s().endereco)[1]; }},
    endereco_ip: {rotulo: 'Endereço por IP', grupo: 'Servidor', descricao: 'O IP direto, para quando o nome falha.',
      valor: function () { return s().endereco_ip || '—'; }},
    online: {rotulo: 'Vikings online', grupo: 'Jogadores', descricao: 'Quantos estão no mundo agora.',
      valor: function () { var n = j().online; return on() && n != null ? String(n) : '—'; }},
    vagas: {rotulo: 'Lugares no salão', grupo: 'Jogadores', descricao: 'Capacidade máxima de jogadores.',
      valor: function () { return String(j().maximo || 10); }},
    vagas_texto: {rotulo: '"de N lugares"', grupo: 'Jogadores', descricao: 'A capacidade já por extenso.',
      valor: function () { return 'de ' + (j().maximo || 10) + ' lugares'; }},
    uptime: {rotulo: 'No ar há', grupo: 'Servidor', descricao: 'Tempo desde o último reinício; corre sozinho.',
      valor: function () { var u = status && status.uptime && status.uptime.segundos;
        return on() && u != null ? duration(u + elapsed()) : '—'; }},
    reinicio: {rotulo: 'Próximo reinício', grupo: 'Servidor', descricao: 'Quanto falta, em contagem regressiva.',
      valor: function () { var p = (status && status.proximo_reinicio) || {};
        return p.segundos_restantes != null ? remaining(p.segundos_restantes - elapsed()) : '—'; }},
    reinicio_horarios: {rotulo: 'Horários de reinício', grupo: 'Servidor', descricao: 'Ex.: "todo dia às 00:00 e 12:00".',
      valor: function () { var p = (status && status.proximo_reinicio) || {};
        return p.horarios_diarios && p.horarios_diarios.length ? 'todo dia às ' + p.horarios_diarios.join(' e ') : '—'; }},
    hora: {rotulo: 'Hora do mundo', grupo: 'Mundo', descricao: 'O relógio do jogo; para quando não há ninguém online.',
      valor: function () { var c = worldClock(); return c ? c.text : '—'; },
      classe: function (el) { var c = worldClock(); el.classList.toggle('parado', !!c && !c.running); }},
    dia: {rotulo: 'Dia do mundo', grupo: 'Mundo', descricao: 'Número do dia no jogo.',
      valor: function () { var c = worldClock(); return c ? 'dia ' + c.day : '—'; }},
    dia_detalhe: {rotulo: 'Dia e horas de mundo', grupo: 'Mundo', descricao: 'Ex.: "dia 12 · 30h de mundo".',
      valor: function () { var c = worldClock(); if (!c) return '—';
        if (!c.running) return 'dia ' + c.day + (status.status_consulta !== 'a2s'
          ? ' · último save' : ' · parado, ninguém online');
        return 'dia ' + c.day + (c.hours != null ? ' · ' + (c.hours >= 10 ? Math.round(c.hours) : c.hours) + 'h de mundo'
                                                 : ' · ' + period(c.hour)); }},
    periodo: {rotulo: 'Período do dia', grupo: 'Mundo', descricao: 'Madrugada, manhã, tarde, noite…',
      valor: function () { var c = worldClock(); return c ? period(c.hour) : '—'; }},
    estacao: {rotulo: 'Estação atual', grupo: 'Mundo', descricao: 'Primavera, verão, outono ou inverno.',
      feature: 'estacoes',
      valor: function () { var e = currentSeason(); return e ? e.nome : '—'; }},
    estacao_duracao: {rotulo: 'Duração da estação', grupo: 'Mundo', descricao: 'Ex.: "6 dias de jogo".',
      feature: 'estacoes',
      valor: function () { var e = status && status.estacoes, n = e && e.duracao_dias_de_jogo;
        return n ? n + (n === 1 ? ' dia' : ' dias') + ' de jogo' : '—'; }},
    recursos: {rotulo: 'Taxa de recursos', grupo: 'Mundo', descricao: 'Multiplicador de coleta (ex.: 2x).',
      feature: 'recursos',
      valor: function () { var t = status && status.taxas; return t && t.recursos ? t.recursos : '—'; }},
    atualizado: {rotulo: 'Hora da atualização', grupo: 'Servidor', descricao: 'Quando o status foi gerado.',
      valor: function () {
        if (!status || !status.gerado_em) return '—';
        try { return new Date(status.gerado_em).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'}); }
        catch (e) { return '—'; } }},
    saga_total: {rotulo: 'Vikings na saga', grupo: 'Saga', descricao: 'Quantos personagens já jogaram.',
      valor: function () { return saga && saga.total_vikings != null ? String(saga.total_vikings) : '—'; }},
    saga_lider: {rotulo: 'Viking mais experiente', grupo: 'Saga', descricao: 'O primeiro do ranking.',
      valor: function () { var l = saga && saga.jogadores && saga.jogadores[0]; return l ? l.nome : '—'; }},
  };

  var FEATURE_GROUP = {Servidor: 'servidor', Jogadores: 'jogadores', Mundo: 'mundo', Saga: 'saga'};
  Object.keys(CATALOG).forEach(function (key) {
    CATALOG[key].feature = CATALOG[key].feature || FEATURE_GROUP[CATALOG[key].grupo] || 'servidor';
  });
  function visibleCatalog() {
    if (!enabledFeatures) return CATALOG; // older installs without features.json
    var visible = {};
    Object.keys(CATALOG).forEach(function (key) {
      if (enabledFeatures.indexOf(CATALOG[key].feature) !== -1) visible[key] = CATALOG[key];
    });
    return visible;
  }

  function paint() {
    var nodes = document.querySelectorAll('[data-vivo]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i], item = CATALOG[el.getAttribute('data-vivo')];
      if (!item || (enabledFeatures && enabledFeatures.indexOf(item.feature) === -1)) continue;
      var text = item.valor();
      if (el.textContent !== text) el.textContent = text;
      if (item.classe) item.classe(el);
    }
    var pulses = document.querySelectorAll('[data-vivo-pulso]');
    for (var k = 0; k < pulses.length; k++) {
      pulses[k].classList.toggle('ligado', !!status && on());
      pulses[k].classList.toggle('desligado', !status || !on());
    }
  }
  function fetchStatus() {
    fetch('/api/status.json', {cache: 'no-store'})
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) { status = d; anchor = Date.now(); paint(); })
      .catch(function () { paint(); });
  }
  function fetchSaga() {
    if (!document.querySelector('[data-vivo^="saga_"]')) return;
    fetch('/api/saga.json', {cache: 'no-store'})
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) { saga = d; paint(); })
      .catch(function () {});
  }

  window.HeimdallVivo = {
    CATALOG: visibleCatalog(),
    allCatalog: CATALOG,
    paint: paint,
    status: function () { return status; },
    refreshSaga: fetchSaga,
  };
  fetch('/api/features.json', {cache: 'no-store'})
    .then(function (r) { if (!r.ok) throw 0; return r.json(); })
    .then(function (d) {
      if (Array.isArray(d.enabled)) {
        enabledFeatures = d.enabled;
        window.HeimdallVivo.CATALOG = visibleCatalog();
        document.querySelectorAll('[data-feature]').forEach(function (el) {
          if (d.enabled.indexOf(el.dataset.feature) === -1) el.classList.add('feature-disabled');
        });
        if (window.parent && window.parent.jarlLiveFeaturesChanged) window.parent.jarlLiveFeaturesChanged();
      }
    }).catch(function () {});
  fetchStatus(); fetchSaga();
  setInterval(fetchStatus, 60000);
  setInterval(fetchSaga, 300000);
  setInterval(paint, 1000);
})();
