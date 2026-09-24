/* Heimdall Nexus first-run wizard. No third-party code runs in this session. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('setup-form');
  const pages = [...document.querySelectorAll('.page')];
  let step = 0;
  let language = localStorage.getItem('heimdall_setup_language') === 'en' ? 'en' : 'pt';
  let polling = null;
  const en = {
    wizard:'SETUP WIZARD', hero:'Your server, site and panel in one place.', heroText:'This wizard installs SteamCMD, Valheim Dedicated Server, the panel and the site. Choose which features to enable.',
    stepSite:'Site', stepSiteHint:'Address and HTTPS', stepGame:'Server', stepGameHint:'World and access', stepOptions:'Features', stepOptionsHint:'Mods and live data', stepAdmin:'Administrator', stepAdminHint:'Linux account and panel login', stepReview:'Review', stepReviewHint:'Install and monitor', localOnly:'Temporary wizard · private HTTPS link',
    siteTitle:'Where will the site live?', siteIntro:'Enter the domain pointing to this machine. You may also use an IP address and configure HTTPS later.', domain:'Site domain or IP', domainHint:'The wizard configures Nginx for this address.', gameAddress:'Game connection address', gameAddressHint:'Leave blank to use the site domain.', https:'Configure HTTPS automatically', httpsHint:'DNS must point to this server and TCP port 80 must be reachable. Certbot will request a Let’s Encrypt certificate.', email:'Certificate email', emailHint:'Used by Let’s Encrypt for renewal notices.', siteNoteTitle:'Before continuing', siteNote:'The temporary link uses Cloudflare and closes with the installer. Keep the token URL private. To avoid this external service, run install.sh with --local-only and use SSH.',
    gameTitle:'Your Valheim world', gameIntro:'SteamCMD downloads the official dedicated server. Your world is saved in /srv/valheim/saves, separate from game files.', serverName:'Server name', world:'World name', gamePort:'UDP port', portHint:'Valheim uses this port and the next.', gamePassword:'Game password', passwordHint:'Leave empty for a server without a password.', public:'Appear in server listings', publicHint:'Players can also join through the direct address.', crossplay:'Enable crossplay', crossplayHint:'Allows players from other platforms; uses the PlayFab backend.', portsTitle:'Network', portsNote:'With the Steam backend, forward the selected UDP port and the next through your firewall and router. With crossplay, Valheim uses a relay.',
    optionsTitle:'Choose the features', optionsIntro:'Install what makes sense for your server. Edit pages and layouts later in the panel.', bepinexHint:'Installs the Valheim pack for server mods. Unchecked means a vanilla server.', modpack:'Modpack', modpackHint:'Optional. Paste the modpack page link from Thunderstore or Hexium. Author/Modpack or the full path of a .zip uploaded to the server (with private mods) also work. A published modpack also fills the site mod list.', installModpack:'Install the modpack on the server', installModpackHint:'Downloads dependencies in one batch. If required versions conflict, uses the highest. Explicit client-only packages are skipped.', liveTitle:'Live data in the editor', liveHint:'These groups appear as draggable elements. Mod-dependent features require their matching configuration.', featureServer:'Server status', featurePlayers:'Online players', featureWorld:'World and day', featureSeasons:'Seasons (mod)', featureResources:'Resource rate', featureSaga:'Character saga (mod)',
    adminTitle:'Secure the panel', adminIntro:'Choose a Linux account for the panel service and a separate login for its website. The panel password is stored as a hash.', systemUser:'Linux service account', systemUserHint:'Created on the VM to run the panel; separate from the browser login below. The game uses another account.', adminUser:'Administrator username', adminPassword:'Panel password', adminPasswordAgain:'Repeat password', adminNoteTitle:'Access', adminNote:'After installation, open /jarl/entrar. The visual page editor is available after sign-in.',
    reviewTitle:'Ready to install', reviewIntro:'Review your choices. Downloading Valheim may take several minutes; follow each step here.', startGame:'Start Valheim after installation and at boot', startGameHint:'Leave unchecked to start it manually from the panel.', reviewNoteTitle:'What will be installed', reviewNote:'SteamCMD, Valheim Dedicated Server, a systemd service, Nginx, the site and panel. BepInEx is included if selected.', back:'Back', next:'Continue', install:'Install everything', progressNumber:'INSTALLATION', progressTitle:'Preparing your server…', progressHint:'Keep the terminal and this page open. Follow the steps below.', successTitle:'Heimdall Nexus is ready', successHint:'Use the panel to edit the site and control the server.', footer:'Heimdall Nexus · created by BRKiHeL', officialGuide:'Official Valheim guide ↗'
  };
  const words = {
    pt: {systemAccount:'Conta Linux', panelLogin:'Login do painel', yes:'Sim', no:'Não', vanilla:'Vanilla', site:'Site', address:'Jogo', server:'Servidor', world:'Mundo', port:'Porta UDP', mods:'Mods', serverMods:'mods no servidor', siteOnly:'lista no site', live:'Dados ao vivo', https:'HTTPS', gameStart:'Iniciar jogo', passwordMismatch:'As senhas do painel não conferem.', ipHttps:'HTTPS automático exige um domínio público, não um IP. Desmarque HTTPS para usar IP.', started:'Instalação em andamento…', failed:'A instalação parou. Corrija o problema e execute novamente no mesmo assistente.', panel:'Abrir painel', openSite:'Abrir site', retry:'Tentar novamente', installFailed:'Falha na instalação', modpackRead:'Modpack identificado:', modpackUnknown:'Não reconheci esse link. Cole o endereço da página do modpack na Thunderstore ou no Hexium.'},
    en: {systemAccount:'Linux account', panelLogin:'Panel login', yes:'Yes', no:'No', vanilla:'Vanilla', site:'Site', address:'Game address', server:'Server', world:'World', port:'UDP port', mods:'Mods', serverMods:'server mods', siteOnly:'site list only', live:'Live data', https:'HTTPS', gameStart:'Start game', passwordMismatch:'The panel passwords do not match.', ipHttps:'Automatic HTTPS requires a public domain, not an IP. Disable HTTPS to use an IP.', started:'Installation is in progress…', failed:'Installation stopped. Fix the problem and retry in this wizard.', panel:'Open panel', openSite:'Open site', retry:'Retry', installFailed:'Installation failed', modpackRead:'Modpack found:', modpackUnknown:'This link was not recognized. Paste the modpack page address from Thunderstore or Hexium.'}
  };
  const t = key => words[language][key] || key;

  function translate() {
    document.documentElement.lang = language === 'pt' ? 'pt-BR' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(el => {
      if (language === 'en' && en[el.dataset.i18n]) el.textContent = en[el.dataset.i18n];
      else if (language === 'pt' && el.dataset.pt) el.textContent = el.dataset.pt;
    });
    document.querySelectorAll('[data-lang]').forEach(button => button.classList.toggle('active', button.dataset.lang === language));
    $('server_address').placeholder = language === 'pt' ? 'Igual ao domínio do site' : 'Same as site domain';
    $('game_password').placeholder = language === 'pt' ? 'Opcional' : 'Optional';
    if (step === 4) review();
  }
  document.querySelectorAll('[data-i18n]').forEach(el => el.dataset.pt = el.textContent);
  document.querySelectorAll('[data-lang]').forEach(button => button.addEventListener('click', () => {
    language = button.dataset.lang;
    localStorage.setItem('heimdall_setup_language', language);
    translate();
  }));

  function showStep(number) {
    step = Math.max(0, Math.min(4, number));
    pages.forEach((page, i) => { page.hidden = i !== step; });
    document.querySelectorAll('[data-step-label]').forEach((item, i) => {
      item.classList.toggle('current', i === step);
      item.classList.toggle('complete', i < step);
    });
    $('back').hidden = step === 0;
    $('next').hidden = step === 4;
    $('install').hidden = step !== 4;
    $('form-error').hidden = true;
    if (step === 4) review();
    window.scrollTo({top:0, behavior:'smooth'});
  }
  function error(message) { $('form-error').textContent = message; $('form-error').hidden = false; }
  function validStep() {
    $('form-error').hidden = true;
    const controls = [...pages[step].querySelectorAll('input:not([type=checkbox])')].filter(el => !el.closest('[hidden]'));
    for (const control of controls) {
      if (!control.checkValidity()) { control.reportValidity(); return false; }
    }
    if (step === 0 && $('tls').checked && /^(?:\d{1,3}\.){3}\d{1,3}$|:/.test($('domain').value.trim())) {
      error(t('ipHttps')); return false;
    }
    if (step === 3 && $('panel_password').value !== $('panel_password_confirm').value) {
      error(t('passwordMismatch')); return false;
    }
    return true;
  }
  $('next').addEventListener('click', () => { if (validStep()) showStep(step + 1); });
  $('back').addEventListener('click', () => showStep(step - 1));
  form.addEventListener('submit', event => event.preventDefault());
  $('tls').addEventListener('change', () => {
    $('email-field').hidden = !$('tls').checked;
    $('email').required = $('tls').checked;
  });
  // Mirrors deploy/modpack.py normalize_package; the server re-validates.
  function modpackName(raw) {
    const text = raw.trim(), part = /^[A-Za-z0-9_.-]{1,80}$/;
    if (!text || text.startsWith('/')) return text;
    if (/^https?:\/\//i.test(text)) {
      let url; try { url = new URL(text); } catch { return text; }
      const host = url.hostname.toLowerCase();
      if (!['thunderstore.io', 'hexium.gg'].some(h => host === h || host.endsWith('.' + h))) return text;
      const parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent);
      for (const marker of ['p', 'mods', 'package', 'packages']) {
        const i = parts.indexOf(marker); if (i < 0) continue;
        let rest = parts.slice(i + 1); if (rest[0] === 'download') rest = rest.slice(1);
        if (rest.length >= 2 && part.test(rest[0]) && part.test(rest[1])) return `${rest[0]}/${rest[1]}`;
      }
      return text;
    }
    if (!text.includes('/') && text.includes('-')) {
      const [owner, ...restParts] = text.split('-');
      let rest = restParts;
      if (rest.length > 1 && /^\d+(\.\d+){1,3}$/.test(rest[rest.length - 1])) rest = rest.slice(0, -1);
      if (rest.length === 1 && part.test(owner) && part.test(rest[0])) return `${owner}/${rest[0]}`;
    }
    return text;
  }
  function showModpackName() {
    const raw = $('modpack').value.trim(), name = modpackName(raw), note = $('modpack-lido');
    if (!raw || raw.startsWith('/') || name === raw) {
      note.hidden = !/^https?:\/\//i.test(raw);
      note.textContent = t('modpackUnknown');
      note.classList.add('erro');
      return;
    }
    note.hidden = false; note.classList.remove('erro');
    note.textContent = `${t('modpackRead')} ${name}`;
  }
  $('modpack').addEventListener('input', showModpackName);
  $('bepinex').addEventListener('change', () => {
    $('modpack-field').hidden = !$('bepinex').checked;
    if (!$('bepinex').checked) $('modpack').value = '';
  });
  $('email').required = true;

  function collect() {
    const value = id => $(id).value.trim();
    return {domain:value('domain'), server_address:value('server_address'), server_name:value('server_name'),
      world:value('world'), port:Number(value('port')), game_password:$('game_password').value,
      public:$('public').checked, crossplay:$('crossplay').checked, bepinex:$('bepinex').checked,
      modpack:modpackName(value('modpack')), install_modpack:$('bepinex').checked && !!value('modpack') && $('install_modpack').checked,
      features:[...document.querySelectorAll('[name=features]:checked')].map(el => el.value),
      system_user:value('system_user'), panel_user:value('panel_user'), panel_password:$('panel_password').value,
      tls:$('tls').checked, email:value('email'), start_game:$('start_game').checked};
  }
  function review() {
    const c = collect(), list = $('summary');
    const rows = [[t('site'),c.domain],[t('address'),c.server_address || c.domain],[t('server'),c.server_name],
      [t('world'),c.world],[t('port'),String(c.port)],[t('mods'),c.bepinex ? 'BepInEx' + (c.modpack ? ` · ${c.modpack} · ${c.install_modpack ? t('serverMods') : t('siteOnly')}` : '') : t('vanilla')],
      [t('live'),c.features.join(', ') || '—'],[t('systemAccount'),c.system_user],[t('panelLogin'),c.panel_user],[t('https'),c.tls ? t('yes') : t('no')],
      [t('gameStart'),c.start_game ? t('yes') : t('no')]];
    list.replaceChildren();
    rows.forEach(([label,value]) => { const dt=document.createElement('dt'),dd=document.createElement('dd'); dt.textContent=label; dd.textContent=value; list.append(dt,dd); });
  }
  $('start_game').addEventListener('change', review);

  async function state() {
    const response = await fetch('/api/state', {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  function renderStatus(data) {
    $('setup-form').hidden = true; $('progress').hidden = false;
    $('phase').textContent = data.step || t('started');
    const log = $('log');
    log.replaceChildren();
    (data.messages || []).forEach(entry => {
      const row=document.createElement('div'), tag=document.createElement('span');
      tag.textContent=entry.step || ''; row.append(tag,document.createTextNode(entry.message || '')); log.append(row);
    });
    log.scrollTop = log.scrollHeight;
    $('spinner').hidden = !data.running;
    if (data.done) {
      clearInterval(polling); polling=null;
      $('progress-title').textContent = language === 'pt' ? 'Instalação concluída' : 'Installation complete';
      $('success').hidden = false;
      const links=$('success-links'); links.replaceChildren();
      [[t('openSite'),data.result.site],[t('panel'),data.result.panel]].forEach(([label,url]) => {
        if (!url) return; const link=document.createElement('a'); link.href=url; link.target='_blank'; link.rel='noopener noreferrer'; link.textContent=label; links.append(link);
      });
    } else if (data.error) {
      clearInterval(polling); polling=null;
      $('progress-title').textContent=t('installFailed');
      $('progress-error').textContent=`${t('failed')} ${data.error}`; $('progress-error').hidden=false;
      if (!$('retry-button')) { const button=document.createElement('button'); button.id='retry-button'; button.className='button secondary'; button.textContent=t('retry'); button.addEventListener('click',()=>{ $('progress').hidden=true; $('setup-form').hidden=false; $('progress-error').hidden=true; showStep(4); }); $('progress').append(button); }
    }
  }
  async function poll() {
    try { renderStatus(await state()); }
    catch (failure) { $('phase-detail').textContent=String(failure); }
  }
  $('install').addEventListener('click', async () => {
    if (!validStep()) return;
    $('install').disabled=true; $('form-error').hidden=true;
    try {
      const response=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collect())});
      const data=await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      $('setup-form').hidden=true; $('progress').hidden=false;
      await poll(); polling=setInterval(poll,1500);
    } catch (failure) { error(String(failure.message || failure)); }
    finally { $('install').disabled=false; }
  });
  translate(); showStep(0);
  state().then(data=>{ if(data.running||data.done||data.error){ renderStatus(data); if(data.running) polling=setInterval(poll,1500); } }).catch(()=>{});
})();
