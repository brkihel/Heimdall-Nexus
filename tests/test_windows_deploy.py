"""Windows deployment pieces that can be checked on any system."""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / 'deploy' / 'windows'
sys.path.insert(0, str(WINDOWS))
sys.path.insert(0, str(ROOT / 'deploy'))
import jobs  # noqa: E402
import services  # noqa: E402
import web  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, WINDOWS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_services_run_with_the_smallest_account():
    by_name = {service.name: service for service in services.definitions()}
    assert services.account_of(by_name['heimdall-executor']) == 'LocalSystem'
    assert services.account_of(by_name['heimdall-jobs']) == 'LocalSystem'
    for name in ('heimdall-panel', 'heimdall-valheim', 'heimdall-sagas-jobs'):
        assert services.account_of(by_name[name]) == f'NT SERVICE\\{name}'
    assert by_name['heimdall-panel'].depends == ('heimdall-executor',)
    # Nothing starts with Windows unless the person turns it on in the desktop app.
    assert {service.start for service in services.definitions()} == {'Manual'}
    assert {service.start for service in services.definitions(game_autostart=True)} == {'Manual'}
    booted = {service.name: service.start for service in services.definitions(boot=True)}
    assert booted['heimdall-panel'] == 'Automatic' and booted['heimdall-valheim'] == 'Manual'
    assert {s.name: s.start for s in services.definitions(boot=True, game_autostart=True)}['heimdall-valheim'] == 'Automatic'


def test_service_definition_quotes_paths_and_keeps_logs_apart():
    game = next(s for s in services.definitions() if s.name == 'heimdall-valheim')
    text = services.xml(game, python=Path('C:/Program Files/HeimdallNexus/venv/Scripts/python.exe'),
                        root=Path('C:/Program Files/HeimdallNexus/app'), logs=Path('C:/ProgramData/HeimdallNexus/logs'),
                        valheim=Path('C:/ProgramData/HeimdallNexus/valheim'))
    assert '"C:/Program Files/HeimdallNexus/app/deploy/windows/run.py"' in text.replace('\\', '/')
    assert '<logpath>C:/ProgramData/HeimdallNexus/logs/heimdall-valheim</logpath>' in text.replace('\\', '/')
    assert '<log mode="none"/>' in text          # the launcher keeps its own log
    assert '<stoptimeout>150 sec</stoptimeout>' in text  # time for the world to save
    assert 'valheim/logs' in text.replace('\\', '/')


def test_winsw_is_pinned():
    assert re.fullmatch(r'[0-9a-f]{64}', services.WINSW_SHA256)
    assert services.WINSW_URL.startswith('https://github.com/winsw/winsw/releases/download/')


def test_caddy_serves_the_same_routes_as_nginx():
    text = web.caddyfile('play.example.org', Path('C:/ProgramData/HeimdallNexus/web'), tls=False)
    assert ':80 {' in text and 'auto_https off' in text and 'admin off' in text
    assert '/api/sagas/v1/overview /api/sagas/v1/vikings/* /api/sagas/v1/atlas/*' in text
    assert 'respond @write 403' in text and 'handle /jarl/*' in text and 'redir /jarl /jarl/ 301' in text
    nginx = (ROOT / 'deploy/nginx/heimdall-nexus.conf.template').read_text(encoding='utf-8')
    for route in ('/api/sagas/v1/overview', '/api/sagas/v1/vikings/', '/api/sagas/v1/atlas/', '/jarl/'):
        assert route in nginx and route.rstrip('/') in text
    secure = web.caddyfile('play.example.org', Path('C:/web'), tls=True, email='a@b.org')
    assert 'play.example.org {' in secure and 'email a@b.org' in secure and 'auto_https off' not in secure


def test_jobs_keep_the_linux_timer_intervals():
    systemd = ROOT / 'deploy' / 'systemd'
    for name, (_, script, first, interval, _) in jobs.JOBS.items():
        timer = (systemd / f'{name}.timer').read_text(encoding='utf-8')
        assert (ROOT / script).is_file()
        if interval == 'minute':
            assert 'OnCalendar=*-*-* *:*:00' in timer
            continue
        every = re.search(r'OnUnitActiveSec=(\d+)(s|min)?', timer)
        seconds = int(every.group(1)) * (60 if every.group(2) == 'min' else 1)
        assert seconds == interval, name


def test_run_loads_heimdall_env(tmp_path):
    run = load('run_windows', 'run.py')
    env = tmp_path / 'heimdall.env'
    env.write_text('# x\nHEIMDALL_ROOT="C:\\\\Program Files\\\\HeimdallNexus\\\\app"\nPAINEL_RAIZ=/jarl\n', encoding='utf-8')
    assert run.load_env(env) == {'HEIMDALL_ROOT': r'C:\Program Files\HeimdallNexus\app', 'PAINEL_RAIZ': '/jarl'}
    assert run.load_env(tmp_path / 'missing.env') == {}


def test_windows_installer_imports_and_lays_out_paths(tmp_path):
    installer_windows = load('installer_windows', 'installer_windows.py')
    layout = installer_windows.Layout(base=tmp_path / 'data', app_base=tmp_path / 'app')
    assert layout.service_files.parent == tmp_path / 'app'       # readable by service accounts
    assert layout.executor_key.parent == tmp_path / 'data' / 'etc'
    assert installer_windows.CADDY_URL.endswith('windows_amd64.zip')
    assert re.fullmatch(r'[0-9a-f]{64}', installer_windows.CADDY_SHA256)


def test_update_and_sagas_scripts_compile_and_keep_update_markers():
    for name in ('update.py', 'install-sagas.py', 'uninstall.ps1', 'install.ps1'):
        assert (WINDOWS / name).is_file()
    source = (WINDOWS / 'update.py').read_text(encoding='utf-8')
    compile(source, 'update.py', 'exec')
    compile((WINDOWS / 'install-sagas.py').read_text(encoding='utf-8'), 'install-sagas.py', 'exec')
    linux = (ROOT / 'deploy' / 'update.sh').read_text(encoding='utf-8')
    for code in re.findall(r'step \d+ [\w-]+ (HN-UPD-\d{3})', linux):
        assert code in source, code
    for script in ('install.ps1', 'uninstall.ps1'):  # Windows PowerShell 5 reads BOM-less files as ANSI
        (WINDOWS / script).read_text(encoding='ascii')


def test_launcher_hands_server_env_to_the_game():
    source = (WINDOWS / 'launcher-windows.py').read_text(encoding='utf-8')
    assert "environment = {**os.environ, **settings, 'SteamAppId': '892970'}" in source


def test_installing_never_turns_anything_on_by_itself():
    installer_windows = load('installer_windows', 'installer_windows.py')
    source = (WINDOWS / 'installer_windows.py').read_text(encoding='utf-8')
    assert "definitions = services.definitions()" in source
    assert "(), start='Manual', stop_seconds=20)" in source          # the web server too
    assert "heimdall-valheim.exe'), 'start'" not in source           # the installer never starts the game
    assert installer_windows.CONTROLLER_RIGHTS == 'CCLCSWRPWPLORCDC'  # query, start, stop, start type
    assert set(installer_windows.CORE_SERVICES) >= {'heimdall-panel', 'heimdall-valheim', 'heimdall-web'}
    for sid in ('S-1-5-21-111-222-333-1001', 'S-1-5-18'):
        assert installer_windows.SID.fullmatch(sid)
    for bad in ('S-1-1-0', 'S-1-5-21-1;(A;;GA;;;WD)', ''):
        assert not installer_windows.SID.fullmatch(bad)
    assert re.fullmatch(r'[0-9a-f]{64}', installer_windows.MINGIT_SHA256)


def test_the_wizard_can_leave_the_browser_to_the_desktop_app():
    source = (ROOT / 'deploy' / 'setup_server.py').read_text(encoding='utf-8')
    assert "'--no-browser'" in source and 'if not args.no_browser:' in source


def test_release_packages_carry_their_commit():
    attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
    assert 'deploy/COMMIT export-subst' in attributes
    assert (ROOT / 'deploy' / 'COMMIT').read_text(encoding='ascii').strip() == '$Format:%H$'


def test_desktop_app_is_complete():
    app = ROOT / 'desktop' / 'HeimdallNexus.Desktop'
    for name in ('Program.cs', 'Setup.cs', 'Center.cs', 'Uninstall.cs', 'WebWindow.cs', 'Channel.cs', 'Runtime.cs',
                 'Heimdall.cs', 'Texts.cs', 'app.manifest', 'heimdall.ico', 'HeimdallNexus.Desktop.csproj'):
        assert (app / name).is_file(), name
    ui = ROOT / 'desktop' / 'ui'
    for name in ('index.html', 'app.css', 'app.js', 'heimdall.svg', 'fundo.webp',
                 'fontes/OFL-cinzel.txt', 'fontes/OFL-spectral.txt'):
        assert (ui / name).is_file(), name
    assert (ROOT / 'desktop' / 'licenses' / 'WebView2-SDK-LICENSE.txt').is_file()
    manifest = (app / 'app.manifest').read_text(encoding='utf-8')
    assert 'level="asInvoker"' in manifest   # daily use without the administrator prompt
    page = (ui / 'app.js').read_text(encoding='utf-8')
    for option in ('onOpenHint', 'withWindowsHint', 'serverWithHint'):
        assert page.count(option + ':') == 2     # every switch explains what it does, in both languages


def test_desktop_page_is_served_only_from_the_exe():
    window = (ROOT / 'desktop' / 'HeimdallNexus.Desktop' / 'WebWindow.cs').read_text(encoding='utf-8')
    assert "connect-src 'none'" in window and "default-src 'none'" in window
    assert 'e.Cancel = true' in window            # no navigating away from the app's own page
    assert 'AreDevToolsEnabled = false' in window
    page = (ROOT / 'desktop' / 'ui' / 'index.html').read_text(encoding='utf-8')
    assert 'http' not in page.replace('http-equiv', '')  # nothing loaded from the network


def test_browser_engine_never_runs_as_administrator():
    program = (ROOT / 'desktop' / 'HeimdallNexus.Desktop' / 'Program.cs').read_text(encoding='utf-8')
    workers = program.index('args.Contains("--install-worker")'), program.index('args.Contains("--uninstall-worker")')
    assert all(index < program.index('Runtime.Prepare()') for index in workers)


def test_desktop_screens_start_hidden():
    # The app opens on any of them (welcome, control center, uninstall); one left visible shows through.
    page = (ROOT / 'desktop' / 'ui' / 'index.html').read_text(encoding='utf-8')
    screens = re.findall(r'<section class="screen"[^>]*>', page)
    assert len(screens) == 4 and all(' hidden' in tag for tag in screens), screens


def test_locations_prefer_the_environment_then_the_windows_defaults(monkeypatch):
    locations = load('locations_test', 'locations.py')
    monkeypatch.setenv('ProgramData', r'C:\ProgramData')
    monkeypatch.setenv('ProgramFiles', r'C:\Program Files')
    monkeypatch.delenv('HEIMDALL_BASE_DIR', raising=False)
    monkeypatch.delenv('HEIMDALL_APP_BASE', raising=False)
    assert locations.recorded('DataDir') == ''  # no registry here
    assert str(locations.data_dir()).endswith('HeimdallNexus')
    monkeypatch.setenv('HEIMDALL_BASE_DIR', r'D:\HeimdallNexus\data')
    monkeypatch.setenv('HEIMDALL_APP_BASE', r'D:\HeimdallNexus\program')
    assert locations.data_dir() == Path(r'D:\HeimdallNexus\data')
    assert locations.app_base() == Path(r'D:\HeimdallNexus\program')
    # Every script finds the installation the same way.
    for script in ('jobs.py', 'launcher-windows.py', 'update.py', 'run.py', 'install-sagas.py', 'installer_windows.py'):
        text = (WINDOWS / script).read_text(encoding='utf-8')
        assert 'locations.data_dir()' in text or 'locations.app_base()' in text, script
        assert "'ProgramData'" not in text.replace("os.environ.get('ProgramData', r'C:\\ProgramData')", ''), script


def test_one_folder_install_is_locked_and_explained(tmp_path):
    installer_windows = load('installer_windows_folder', 'installer_windows.py')
    root = tmp_path / 'HeimdallNexus'
    layout = installer_windows.Layout(base=root / 'data', app_base=root / 'program', root=str(root))
    (root / 'program').mkdir(parents=True)
    calls = []
    engine = installer_windows.WindowsInstaller.__new__(installer_windows.WindowsInstaller)
    engine.paths, engine.report = layout, lambda *a: None
    engine.icacls = lambda path, *arguments: calls.append((Path(path), arguments))
    engine.own_folder(root)
    owner, locked = calls[0], calls[1]
    assert owner == (root, ('/setowner', '*S-1-5-32-544'))
    assert locked[1][0] == '/inheritance:r' and '*S-1-5-32-545:(OI)(CI)RX' in locked[1]
    assert not any('(M)' in a or ':(OI)(CI)F' in a for a in locked[1] if a.startswith('*S-1-5-32-545'))
    for note in ('LEIA-ME.txt', 'README.txt'):
        text = (root / note).read_text(encoding='utf-8-sig')
        assert 'program\\' in text and 'valheim\\saves' in text
    # Nothing but <root>\program and <root>\data, in a folder named HeimdallNexus.
    wrong = installer_windows.Layout(base=tmp_path / 'elsewhere', app_base=root / 'program', root=str(root))
    engine.paths = wrong
    try:
        engine.own_folder(root)
    except installer_windows.InstallError:
        pass
    else:
        raise AssertionError('a data folder outside the installation folder was accepted')


def test_uninstall_only_removes_heimdall_folders():
    script = (WINDOWS / 'uninstall.ps1').read_text(encoding='utf-8')
    assert "HKLM:\\SOFTWARE\\HeimdallNexus" in script
    assert 'Refusing to remove' in script
    assert script.index('Refusing to remove') < script.index("'Stopping and removing the services...'")


def test_the_app_checks_the_folder_before_writing_to_it():
    app = ROOT / 'desktop' / 'HeimdallNexus.Desktop'
    location = (app / 'Location.cs').read_text(encoding='utf-8')
    setup = (app / 'Setup.cs').read_text(encoding='utf-8')
    assert 'SetAccessRuleProtection(true, false)' in location and 'SetOwner(Administrators)' in location
    assert 'DriveFormat' in location and 'NTFS' in location
    # The elevated worker checks again and locks the folder before the first download.
    install = setup[setup.index('void Install()'):]
    assert install.index('Location.Prepare(root)') < install.index('Download(')
    assert 'HEIMDALL_INSTALL_ROOT' in setup
