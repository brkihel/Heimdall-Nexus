/* Heimdall Nexus desktop app: the page inside the window. The C# host sends the
   state and runs the actions; this page only shows them. Opened in a plain
   browser, it runs a demo host so the screens can be seen and tried. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);

  // ---------------------------------------------------------------- texts
  const TEXTS = {
    pt: {
      eyebrow: 'Servidor de Valheim · painel · site',
      lead: 'O guardião do seu servidor. Tudo o que o seu mundo precisa, instalado com um clique e cuidado de um só lugar.',
      giftServer: 'Servidor dedicado', giftServerHint: 'O servidor oficial de Valheim, com seus mods se quiser.',
      giftPanel: 'Painel Jarl', giftPanelHint: 'Ligue, desligue, faça backups e instale mods pelo navegador.',
      giftSite: 'Site do servidor', giftSiteHint: 'Status ao vivo e a lista de mods, para seus amigos.',
      howTitle: 'Como funciona',
      how1: 'Clique em Iniciar instalação e permita quando o Windows perguntar.',
      how2: 'Esta janela baixa o que é preciso e abre o assistente no seu navegador.',
      how3: 'No navegador, você escolhe o nome do servidor, o mundo e as senhas.',
      factTime: '20 a 40 minutos', factTimeHint: 'quase tudo é o download do jogo',
      factSpace: '10 GB livres', factSpaceHint: 'para o jogo, os mundos e os backups',
      promise: 'Nada do Heimdall liga sozinho com o Windows. Depois de instalar, você escolhe isso aqui mesmo.',
      shortcut: 'Criar um atalho na área de trabalho',
      whereTitle: 'Onde instalar', whereChange: 'Alterar',
      whereChooseTitle: 'Onde instalar o Heimdall?',
      whereChooseText: 'Em outro disco, tudo fica numa pasta só, HeimdallNexus: o programa, o jogo, os mundos e os backups. No padrão do Windows, o programa vai para Arquivos de Programas e os dados para ProgramData, no disco C:.',
      whereFolder: 'Outra pasta…', whereFolderHint: 'Escolha uma pasta; o Heimdall cria a HeimdallNexus dentro dela.',
      startInstall: 'Iniciar instalação', uac: 'O Windows vai pedir permissão uma única vez.',
      installingWord: 'instalando', doneWord: 'concluído', stoppedWord: 'parou',
      stageCheck: 'Conferir o computador', stageDownload: 'Baixar o Heimdall Nexus', stagePython: 'Preparar o Python do Heimdall',
      stageWizard: 'Abrir o assistente no navegador', stageBrowser: 'Suas escolhas no navegador',
      stageValheim: 'Baixar o servidor de Valheim', stageFinish: 'Deixar tudo pronto',
      reopenBrowser: 'O navegador não abriu? Clique aqui.',
      doneTitle: 'O Heimdall Nexus está pronto', doneDetail: 'Daqui em diante, você liga, desliga e abre tudo por este aplicativo.',
      openCenter: 'Abrir o Heimdall Nexus',
      closingNote: 'Fechar esta janela não desliga o Heimdall.',
      heimdall: 'Heimdall · painel e site', server: 'Servidor de Valheim',
      on: 'Ligado', off: 'Desligado', starting: 'Ligando…', stopping: 'Desligando…', saving: 'Salvando o mundo…',
      heimdallHint: 'O painel para administrar e o site para os jogadores.',
      serverOff: 'Ninguém consegue entrar enquanto estiver desligado.', serverOnNoPlayers: 'Ninguém jogando agora.',
      players: n => n === 1 ? '1 viking jogando agora' : `${n} vikings jogando agora`,
      world: w => `Mundo ${w}`,
      openPanel: 'Abrir o painel', openSite: 'Abrir o site',
      whenTitle: 'Quando ligar',
      onOpen: 'Ligar o Heimdall quando eu abrir este aplicativo',
      onOpenHint: 'Ao abrir este aplicativo, o painel e o site ligam sozinhos. Desligado: você liga pelo botão acima.',
      withWindows: 'Ligar o Heimdall junto com o Windows',
      withWindowsHint: 'O painel e o site ligam quando o computador liga, mesmo sem abrir este aplicativo e sem ninguém entrar no Windows. Desligado: nada do Heimdall roda até você mandar.',
      serverWith: 'Ligar o servidor de Valheim sempre que o Heimdall ligar',
      serverWithHint: 'Quando o Heimdall liga (pelo botão, ao abrir este aplicativo ou junto com o Windows), o servidor liga também. Desligado: você liga o servidor pelo botão acima ou pelo painel.',
      uninstall: 'Desinstalar o Heimdall Nexus…',
      offTitle: 'Desligar o Heimdall?', offText: 'O painel e o site saem do ar. Se o servidor de Valheim estiver ligado, ele salva o mundo e desliga junto.',
      offYes: 'Desligar tudo', cancel: 'Cancelar',
      serverOffTitle: 'Desligar o servidor?', serverOffText: 'Quem estiver jogando é desconectado. O mundo é salvo antes de desligar.',
      serverOffYes: 'Salvar e desligar',
      uninstallTitle: 'Desinstalar o Heimdall Nexus?', uninstallText: 'O servidor, o painel, o site e os serviços do Heimdall são desligados e removidos deste computador.',
      uninstallNext: 'Continuar',
      keepTitle: 'E os seus mundos?', keepText: 'Guardar: mundos, backups e o site ficam em C:\\ProgramData\\HeimdallNexus, e uma nova instalação continua de onde parou.\nApagar: tudo some de vez, inclusive os mundos.',
      keepYes: 'Guardar meus mundos', keepNo: 'Apagar tudo',
      removing: 'Removendo o Heimdall Nexus…', removingText: 'Se o servidor estiver ligado, o mundo é salvo antes.',
      removedTitle: 'Até a próxima, viking', removed: 'O Heimdall Nexus foi removido deste computador.', farewellFailed: 'A desinstalação não terminou',
      cancelTitle: 'Parar a instalação?', cancelText: 'Você pode instalar de novo depois; o que já foi baixado é aproveitado.',
      cancelYes: 'Parar a instalação', cancelNo: 'Continuar instalando',
      close: 'Fechar',
    },
    en: {
      eyebrow: 'Valheim server · panel · website',
      lead: "Your server's guardian. Everything your world needs, installed with one click and run from one place.",
      giftServer: 'Dedicated server', giftServerHint: 'The official Valheim server, with your mods if you want them.',
      giftPanel: 'Jarl panel', giftPanelHint: 'Start, stop, back up and install mods from your browser.',
      giftSite: 'Server website', giftSiteHint: 'Live status and the mod list, for your friends.',
      howTitle: 'How it works',
      how1: 'Click Start installation and allow it when Windows asks.',
      how2: 'This window downloads what is needed and opens the assistant in your browser.',
      how3: 'In the browser, you choose the server name, the world and the passwords.',
      factTime: '20 to 40 minutes', factTimeHint: 'mostly downloading the game',
      factSpace: '10 GB free', factSpaceHint: 'for the game, worlds and backups',
      promise: 'Nothing from Heimdall starts with Windows by itself. After installing, you choose that right here.',
      shortcut: 'Create a desktop shortcut',
      whereTitle: 'Where to install', whereChange: 'Change',
      whereChooseTitle: 'Where to install Heimdall?',
      whereChooseText: "On another disk, everything goes in one folder, HeimdallNexus: the program, the game, the worlds and the backups. With the Windows default, the program goes to Program Files and the data to ProgramData, on drive C:.",
      whereFolder: 'Another folder…', whereFolderHint: 'Pick a folder; Heimdall creates HeimdallNexus inside it.',
      startInstall: 'Start installation', uac: 'Windows will ask for permission just once.',
      installingWord: 'installing', doneWord: 'done', stoppedWord: 'stopped',
      stageCheck: 'Check the computer', stageDownload: 'Download Heimdall Nexus', stagePython: "Prepare Heimdall's Python",
      stageWizard: 'Open the assistant in the browser', stageBrowser: 'Your choices in the browser',
      stageValheim: 'Download the Valheim server', stageFinish: 'Get everything ready',
      reopenBrowser: 'The browser did not open? Click here.',
      doneTitle: 'Heimdall Nexus is ready', doneDetail: 'From now on, you turn everything on and off and open it from this app.',
      openCenter: 'Open Heimdall Nexus',
      closingNote: 'Closing this window does not turn Heimdall off.',
      heimdall: 'Heimdall · panel and website', server: 'Valheim server',
      on: 'On', off: 'Off', starting: 'Starting…', stopping: 'Stopping…', saving: 'Saving the world…',
      heimdallHint: 'The panel to manage it and the website for players.',
      serverOff: 'Nobody can join while it is off.', serverOnNoPlayers: 'Nobody playing right now.',
      players: n => n === 1 ? '1 viking playing now' : `${n} vikings playing now`,
      world: w => `World ${w}`,
      openPanel: 'Open the panel', openSite: 'Open the website',
      whenTitle: 'When to turn on',
      onOpen: 'Turn Heimdall on when I open this app',
      onOpenHint: 'When you open this app, the panel and the website start by themselves. Off: you turn them on with the button above.',
      withWindows: 'Turn Heimdall on with Windows',
      withWindowsHint: 'The panel and the website start when the computer starts, even without opening this app and before anyone signs in. Off: nothing from Heimdall runs until you say so.',
      serverWith: 'Start the Valheim server whenever Heimdall turns on',
      serverWithHint: 'When Heimdall turns on (with the button, when opening this app or with Windows), the server starts too. Off: you start the server with the button above or from the panel.',
      uninstall: 'Uninstall Heimdall Nexus…',
      offTitle: 'Turn Heimdall off?', offText: 'The panel and the website go offline. If the Valheim server is on, it saves the world and stops too.',
      offYes: 'Turn everything off', cancel: 'Cancel',
      serverOffTitle: 'Stop the server?', serverOffText: 'Whoever is playing is disconnected. The world is saved first.',
      serverOffYes: 'Save and stop',
      uninstallTitle: 'Uninstall Heimdall Nexus?', uninstallText: "The server, the panel, the website and Heimdall's services are stopped and removed from this computer.",
      uninstallNext: 'Continue',
      keepTitle: 'What about your worlds?', keepText: 'Keep: worlds, backups and the website stay in C:\\ProgramData\\HeimdallNexus, and a new installation picks up where you left off.\nErase: everything is gone for good, worlds included.',
      keepYes: 'Keep my worlds', keepNo: 'Erase everything',
      removing: 'Removing Heimdall Nexus…', removingText: 'If the server is on, the world is saved first.',
      removedTitle: 'Until next time, viking', removed: 'Heimdall Nexus was removed from this computer.', farewellFailed: 'The removal did not finish',
      cancelTitle: 'Stop the installation?', cancelText: 'You can install again later; what was downloaded is reused.',
      cancelYes: 'Stop the installation', cancelNo: 'Keep installing',
      close: 'Close',
    },
  };
  let lang = (navigator.language || 'pt').toLowerCase().startsWith('pt') ? 'pt' : 'en';
  const t = key => TEXTS[lang][key];
  function translate() {
    document.documentElement.lang = lang === 'pt' ? 'pt-BR' : 'en';
    document.querySelectorAll('[data-t]').forEach(el => { el.textContent = t(el.dataset.t); });
    renderStages();
  }

  // ---------------------------------------------------------------- the host (C#) or a demo host
  const webview = window.chrome && window.chrome.webview;
  const host = webview
    ? { send: msg => webview.postMessage(msg), listen: fn => webview.addEventListener('message', e => fn(e.data)) }
    : demoHost();

  // ---------------------------------------------------------------- screens
  let current = null;
  function show(id) {
    if (current === id) return;
    const next = $(id), previous = current && $(current);
    current = id;
    if (previous) {
      previous.classList.add('leaving');
      setTimeout(() => { previous.hidden = true; previous.classList.remove('leaving'); next.hidden = false; }, 260);
    } else {
      next.hidden = false;
    }
  }

  // ---------------------------------------------------------------- installing
  const STAGES = ['stageCheck', 'stageDownload', 'stagePython', 'stageWizard', 'stageBrowser', 'stageValheim', 'stageFinish'];
  let stage = 0, stageFailed = false, shownPercent = 0;
  function renderStages() {
    const list = $('stages');
    list.replaceChildren(...STAGES.map((key, index) => {
      const li = document.createElement('li');
      li.textContent = t(key);
      li.className = index < stage ? 'done' : index === stage ? (stageFailed ? 'failed' : 'current') : '';
      return li;
    }));
  }
  function install(data) {
    show('installing');
    const circle = document.querySelector('.ring .fill');
    if (data.percent != null) shownPercent = Math.max(0, Math.min(100, data.percent));
    const percent = shownPercent;
    circle.style.strokeDashoffset = String(326.7 * (1 - percent / 100));
    $('percent').textContent = `${Math.round(percent)}%`;
    stage = data.stage ?? stage;
    stageFailed = !!data.error;
    $('step-title').textContent = data.done ? t('doneTitle') : (data.title || '');
    $('step-detail').textContent = data.done ? t('doneDetail') : (data.detail || '');
    $('step-error').textContent = data.error || '';
    $('step-error').hidden = !data.error;
    $('reopen-browser').hidden = !data.browser || data.done || data.fatal;
    $('ring').classList.toggle('done', !!data.done);
    $('ring').classList.toggle('failed', !!data.fatal);
    $('ring-word').textContent = t(data.done ? 'doneWord' : data.fatal ? 'stoppedWord' : 'installingWord');
    if (data.done) stage = STAGES.length;
    if ((data.done || data.fatal) && !$('install-end')) {
      const button = document.createElement('button');
      button.className = 'cta'; button.id = 'install-end';
      button.dataset.t = data.done ? 'openCenter' : 'close'; button.textContent = t(button.dataset.t);
      button.onclick = () => host.send({ cmd: data.done ? 'openCenter' : 'close' });
      $('stages').after(button);
    }
    renderStages();
  }

  // ---------------------------------------------------------------- control center
  let state = null;
  function center(data) {
    state = data;
    show('center');
    $('version').textContent = data.version ? `v${data.version}` : '';
    paintPower('power-heimdall', data.heimdall, $('heimdall-state'));
    paintPower('power-server', data.server, $('server-state'));
    const players = data.players;
    $('server-sub').textContent = data.server === 'on'
      ? [data.world ? t('world')(data.world) : '', players > 0 ? t('players')(players) : players === 0 ? t('serverOnNoPlayers') : ''].filter(Boolean).join(' · ')
      : data.server === 'off' ? t('serverOff') : '';
    document.querySelectorAll('[data-open]').forEach(button => { button.disabled = data.heimdall !== 'on'; });
    $('on-open').checked = !!data.prefs.onOpen;
    $('with-windows').checked = !!data.prefs.withWindows;
    $('server-with').checked = !!data.prefs.serverWith;
  }
  function paintPower(id, value, label) {
    const card = $(id);
    card.classList.toggle('on', value === 'on');
    card.classList.toggle('off', value === 'off');
    card.classList.toggle('busy', value !== 'on' && value !== 'off');
    card.querySelector('.orb').disabled = value !== 'on' && value !== 'off';
    label.textContent = value === 'on' ? t('on') : value === 'off' ? t('off') : t(value) || t('starting');
  }

  document.querySelector('[data-action=heimdall]').onclick = () => {
    if (state.heimdall === 'on')
      ask(t('offTitle'), t('offText'), [[t('cancel'), 'ghost'], [t('offYes'), 'cta danger', () => host.send({ cmd: 'heimdall', on: false })]]);
    else host.send({ cmd: 'heimdall', on: true });
  };
  document.querySelector('[data-action=server]').onclick = () => {
    if (state.server === 'on')
      ask(t('serverOffTitle'), t('serverOffText'), [[t('cancel'), 'ghost'], [t('serverOffYes'), 'cta danger', () => host.send({ cmd: 'server', on: false })]]);
    else host.send({ cmd: 'server', on: true });
  };
  document.querySelectorAll('[data-open]').forEach(button => { button.onclick = () => host.send({ cmd: 'open', target: button.dataset.open }); });
  for (const [id, key] of [['on-open', 'onOpen'], ['with-windows', 'withWindows'], ['server-with', 'serverWith']])
    $(id).onchange = () => host.send({ cmd: 'prefs', [key]: $(id).checked });
  $('uninstall').onclick = () => askUninstall(keep => host.send({ cmd: 'uninstall', keep }));
  $('start-install').onclick = () => { $('start-install').disabled = true; host.send({ cmd: 'install', desktopShortcut: $('desktop-shortcut').checked }); };
  $('reopen-browser').onclick = () => host.send({ cmd: 'reopenBrowser' });

  // ---------------------------------------------------------------- where to install
  let where = null;
  function showWhere(data) {
    where = data;
    $('where-path').textContent = data.path;
    $('where-note').textContent = data.note || '';
    $('where-note').hidden = !data.note;
  }
  function option(title, detail, reason, current, disabled, pick) {
    const button = document.createElement('button');
    button.className = 'option' + (current ? ' current' : '');
    button.disabled = disabled;
    const name = document.createElement('b'); name.textContent = title;
    const more = document.createElement('small'); more.textContent = detail;
    button.append(name, more);
    if (reason) { const why = document.createElement('small'); why.className = 'reason'; why.textContent = reason; button.append(why); }
    button.onclick = () => { $('modal').hidden = true; pick(); };
    return button;
  }
  $('where-change').onclick = () => {
    if (!where) return;
    ask(t('whereChooseTitle'), t('whereChooseText'), [[t('cancel'), 'ghost']]);
    const list = document.createElement('div');
    list.className = 'options';
    for (const o of where.options) {
      const current = o.id === 'default' ? !where.custom : where.custom && where.path.toUpperCase().startsWith(o.id.toUpperCase() + '\\');
      list.append(option(o.title, o.detail, o.ok ? '' : o.reason, current, !o.ok, () => host.send({ cmd: 'where', id: o.id })));
    }
    list.append(option(t('whereFolder'), t('whereFolderHint'), '', false, false, () => host.send({ cmd: 'where', id: 'folder' })));
    $('modal-extra').replaceChildren(list);
  };

  // ---------------------------------------------------------------- modal and toast
  let onEscape = null;
  function ask(title, text, choices, escape) {
    onEscape = escape || null;
    $('modal-title').textContent = title;
    $('modal-text').textContent = text;
    $('modal-extra').replaceChildren();
    $('modal-choices').replaceChildren(...choices.map(([label, style, action]) => {
      const button = document.createElement('button');
      button.className = style; button.textContent = label;
      button.onclick = () => { $('modal').hidden = true; if (action) action(); };
      return button;
    }));
    $('modal').hidden = false;
    $('modal-choices').lastChild.focus();
  }
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || $('modal').hidden) return;
    $('modal').hidden = true;
    if (onEscape) onEscape();
  });
  let toastTimer = null;
  function toast(text) {
    $('toast').textContent = text; $('toast').hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3800);
  }

  // ---------------------------------------------------------------- uninstalling
  function askUninstall(then, cancel) {
    ask(t('uninstallTitle'), t('uninstallText'), [[t('cancel'), 'ghost', cancel], [t('uninstallNext'), 'cta', () =>
      ask(t('keepTitle'), t('keepText'), [[t('keepNo'), 'ghost', () => then(false)], [t('keepYes'), 'cta', () => then(true)]], cancel)]], cancel);
  }
  function farewell(title, text, state) {
    show('farewell');
    $('farewell-title').textContent = title;
    $('farewell-text').textContent = text;
    $('farewell-ring').classList.toggle('done', state === 'removed');
    $('farewell-ring').classList.toggle('failed', state === 'failed');
    $('farewell-close').hidden = state === 'working' || state === 'asking';
    $('farewell').classList.toggle('asking', state === 'asking');
  }
  $('farewell-close').onclick = () => host.send({ cmd: 'close' });

  host.listen(msg => {
    if (msg.type === 'init') { lang = msg.lang || lang; translate(); }
    else if (msg.type === 'screen' && msg.name === 'welcome') show('welcome');
    else if (msg.type === 'screen' && msg.name === 'farewell' && msg.ask) {
      farewell(t('uninstallTitle'), '', 'asking');
      askUninstall(keep => host.send({ cmd: 'uninstall', keep }), () => host.send({ cmd: 'close' }));
    }
    else if (msg.type === 'screen' && msg.name === 'farewell') farewell(t('removing'), t('removingText'), 'working');
    else if (msg.type === 'removed') farewell(t('removedTitle'), msg.text || t('removed'), 'removed');
    else if (msg.type === 'farewellError') farewell(t('farewellFailed'), msg.text, 'failed');
    else if (msg.type === 'install') install(msg);
    else if (msg.type === 'confirmCancel')
      ask(t('cancelTitle'), t('cancelText'), [[t('cancelNo'), 'ghost'], [t('cancelYes'), 'cta danger', () => host.send({ cmd: 'cancelInstall' })]]);
    else if (msg.type === 'welcomeError') { $('start-install').disabled = false; ask('Heimdall Nexus', msg.text, [[t('close'), 'cta']]); }
    else if (msg.type === 'where') showWhere(msg);
    else if (msg.type === 'state') center(msg);
    else if (msg.type === 'toast') toast(msg.text);
    else if (msg.type === 'error') ask('Heimdall Nexus', msg.text, [[t('close'), 'cta']]);
  });
  translate();
  host.send({ cmd: 'ready' });

  // ---------------------------------------------------------------- embers
  (function embers() {
    const canvas = $('embers'), ctx = canvas.getContext('2d');
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let sparks = [];
    function size() { canvas.width = innerWidth * devicePixelRatio; canvas.height = innerHeight * devicePixelRatio; }
    size(); addEventListener('resize', size);
    function spawn() {
      return { x: Math.random() * canvas.width, y: canvas.height + 10, r: (Math.random() * 1.6 + .6) * devicePixelRatio,
               v: (Math.random() * .35 + .15) * devicePixelRatio, drift: Math.random() * 2 * Math.PI, life: 0 };
    }
    for (let i = 0; i < 26; i++) { const s = spawn(); s.y = Math.random() * canvas.height; sparks.push(s); }
    (function frame() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const s of sparks) {
        s.life += 1; s.y -= s.v; s.x += Math.sin((s.life / 90) + s.drift) * .25 * devicePixelRatio;
        const fade = Math.min(1, s.life / 120) * Math.max(0, s.y / canvas.height);
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(236, 170, 90, ${.55 * fade})`; ctx.shadowColor = 'rgba(236, 150, 60, .8)'; ctx.shadowBlur = 8 * devicePixelRatio;
        ctx.fill();
        if (s.y < -10) Object.assign(s, spawn());
      }
      requestAnimationFrame(frame);
    })();
  })();

  // ---------------------------------------------------------------- demo host (browser preview only)
  function demoHost() {
    let listener = () => {};
    const prefs = { onOpen: false, withWindows: false, serverWith: false };
    const live = { heimdall: 'off', server: 'off', players: 0, world: 'Midgard', version: '1.2.0', prefs };
    const emit = msg => setTimeout(() => listener(msg), 0);
    const push = () => emit({ type: 'state', ...live, prefs: { ...prefs } });
    const bar = document.createElement('div');
    bar.className = 'preview';
    for (const [label, action] of [['Boas-vindas', () => emit({ type: 'screen', name: 'welcome' })],
                                   ['Instalando', () => runInstall()], ['Central', () => push()],
                                   ['Desinstalar', () => emit({ type: 'screen', name: 'farewell', ask: true })],
                                   ['PT/EN', () => { lang = lang === 'pt' ? 'en' : 'pt'; translate(); if (current === 'center') push(); }]]) {
      const button = document.createElement('button'); button.textContent = label; button.onclick = action; bar.append(button);
    }
    document.body.append(bar);
    function runInstall() {
      const steps = [[3, 0, 'Conferindo o computador…', ''], [12, 1, 'Baixando o Heimdall Nexus…', '1 MB / 4 MB'],
                     [24, 1, 'Baixando o Heimdall Nexus…', '4 MB / 4 MB'], [32, 2, 'Instalando o Python do Heimdall…', '18 MB / 26 MB'],
                     [42, 3, 'Abrindo o assistente no navegador…', ''], [48, 4, 'Continue no navegador: preencha as cinco telas.', 'Esta janela acompanha a instalação.', true],
                     [60, 5, 'Baixando o servidor de Valheim…', 'progress: 34.20 (722 MB / 2112 MB)', true],
                     [86, 5, 'Baixando o servidor de Valheim…', 'progress: 97.80 (2066 MB / 2112 MB)', true],
                     [95, 6, 'Deixando tudo pronto…', 'Registrando os serviços do Windows', true]];
      steps.forEach(([percent, stage, title, detail, browser], index) =>
        setTimeout(() => listener({ type: 'install', percent, stage, title, detail, browser }), index * 1100));
      setTimeout(() => listener({ type: 'install', percent: 100, stage: 7, done: true }), steps.length * 1100);
    }
    let demoRoot = null;
    function demoWhere() {
      return { type: 'where', path: demoRoot || 'C:\\Program Files\\HeimdallNexus', custom: !!demoRoot, note: null, options: [
        { id: 'default', title: 'Padrão do Windows (C:)', detail: '38 GB livres · C:\\Program Files\\HeimdallNexus', ok: true },
        { id: 'D:', title: 'Jogos (D:)', detail: '812 GB livres · D:\\HeimdallNexus', ok: true },
        { id: 'E:', title: 'Backup (E:)', detail: '4 GB livres · E:\\HeimdallNexus', ok: false, reason: 'Menos de 10 GB livres' }] };
    }
    function busy(key, word, then) { live[key] = word; push(); setTimeout(() => { then(); push(); }, 2200); }
    return {
      listen: fn => { listener = fn; },
      send: msg => {
        if (msg.cmd === 'ready') { emit({ type: 'screen', name: 'welcome' }); emit(demoWhere()); }
        if (msg.cmd === 'where') {
          demoRoot = msg.id === 'default' ? null : msg.id === 'folder' ? 'E:\\Jogos\\HeimdallNexus' : msg.id + '\\HeimdallNexus';
          emit(demoWhere());
        }
        if (msg.cmd === 'close') emit({ type: 'toast', text: 'Aqui a janela fecharia.' });
        if (msg.cmd === 'install') runInstall();
        if (msg.cmd === 'openCenter') push();
        if (msg.cmd === 'heimdall') busy('heimdall', msg.on ? 'starting' : 'stopping', () => {
          live.heimdall = msg.on ? 'on' : 'off';
          if (!msg.on) live.server = 'off';
          if (msg.on && prefs.serverWith) { live.server = 'on'; live.players = 3; }
        });
        if (msg.cmd === 'server') busy('server', msg.on ? 'starting' : 'saving', () => { live.server = msg.on ? 'on' : 'off'; live.players = msg.on ? 3 : 0; });
        if (msg.cmd === 'prefs') Object.assign(prefs, Object.fromEntries(Object.entries(msg).filter(([k]) => k !== 'cmd')));
        if (msg.cmd === 'open') emit({ type: 'toast', text: msg.target === 'panel' ? 'Abrindo o painel no navegador…' : 'Abrindo o site no navegador…' });
        if (msg.cmd === 'uninstall') {
          emit({ type: 'screen', name: 'farewell' });
          setTimeout(() => listener({ type: 'removed', text: 'O Heimdall Nexus foi removido deste computador. Seus mundos e backups continuam em C:\\ProgramData\\HeimdallNexus.' }), 2600);
        }
      },
    };
  }
})();
