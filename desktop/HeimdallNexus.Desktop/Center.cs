using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>After installing: turn Heimdall and the Valheim server on and off, and choose when they start.</summary>
    sealed class CenterFlow
    {
        readonly WebWindow window = new WebWindow();
        readonly Heimdall.Prefs prefs = Heimdall.LoadPrefs();
        readonly Timer refresh = new Timer { Interval = 2000 };
        // While an action runs, what the window shows instead of the services' own state.
        volatile string heimdallBusy, serverBusy;
        volatile bool busy;

        public static void Run() => Application.Run(new CenterFlow().window);

        CenterFlow()
        {
            window.Command += OnCommand;
            refresh.Tick += (s, e) => Push();
            window.FormClosed += (s, e) => refresh.Stop();
        }

        void OnCommand(Dictionary<string, object> message)
        {
            bool Flag(string key) => message.TryGetValue(key, out var v) && v is bool b && b;
            switch ((string)message["cmd"])
            {
                case "ready":
                    Push();
                    refresh.Start();
                    if (prefs.on_open && !Heimdall.HeimdallOn) TurnOn();
                    break;
                case "heimdall":
                    if (Flag("on")) TurnOn();
                    else Act(() => { heimdallBusy = "stopping"; if (Heimdall.ServerOn) serverBusy = "saving"; },
                             () => Heimdall.TurnOff(stage => { if (stage == T.Stopping) { serverBusy = null; heimdallBusy = "stopping"; } }));
                    break;
                case "server":
                    if (Flag("on")) Act(() => serverBusy = "starting", Heimdall.StartServer);
                    else Act(() => serverBusy = "saving", () => Heimdall.StopServer(_ => { }));
                    break;
                case "open":
                    var panel = message.TryGetValue("target", out var t) && (t as string) == "panel";
                    Heimdall.OpenAsUser(panel ? Heimdall.PanelUrl : Heimdall.SiteUrl);
                    window.Post(new { type = "toast", text = panel ? T.OpeningPanel : T.OpeningSite });
                    break;
                case "prefs":
                    if (message.ContainsKey("onOpen")) { prefs.on_open = Flag("onOpen"); Heimdall.SavePrefs(prefs); }
                    if (message.ContainsKey("serverWith"))
                    {
                        prefs.server_with_heimdall = Flag("serverWith");
                        Heimdall.SavePrefs(prefs);
                        if (Heimdall.StartsWithWindows) ApplyBoot(true);
                    }
                    if (message.ContainsKey("withWindows")) ApplyBoot(Flag("withWindows"));
                    Push();
                    break;
                case "uninstall":
                    Uninstaller.Start(Flag("keep"));
                    window.Close();
                    break;
            }
        }

        void TurnOn()
        {
            bool withServer = prefs.server_with_heimdall;
            Act(() => { heimdallBusy = "starting"; if (withServer) serverBusy = "starting"; },
                () => Heimdall.TurnOn(withServer, _ => { }));
        }

        void ApplyBoot(bool boot)
        {
            try { Heimdall.SetStartWithWindows(boot, prefs.server_with_heimdall); }
            catch (Exception error) { window.Post(new { type = "error", text = Problem(error) }); }
        }

        /// <summary>Runs a slow action off the window's thread; the page shows what is happening meanwhile.</summary>
        void Act(Action before, Action action)
        {
            if (busy) return;
            busy = true;
            before();
            Push();
            Task.Run(() =>
            {
                string problem = null;
                try { action(); }
                catch (System.ServiceProcess.TimeoutException) { problem = T.SaveSlow; }
                catch (Exception error) { problem = Problem(error); }
                heimdallBusy = serverBusy = null;
                busy = false;
                window.OnUi(() =>
                {
                    Push();
                    if (problem != null) window.Post(new { type = "error", text = problem });
                });
            });
        }

        static string Problem(Exception error) => Heimdall.AccessDenied(error) ? T.NoPermission : T.Error(error.Message);

        void Push()
        {
            var game = Heimdall.Status(Heimdall.Game);
            string server = serverBusy
                ?? (game == ServiceControllerStatus.Running ? "on"
                  : game == ServiceControllerStatus.StartPending ? "starting"
                  : game == ServiceControllerStatus.StopPending ? "stopping" : "off");
            var feed = server == "on" ? Heimdall.Feed() : null;
            window.Post(new Dictionary<string, object>
            {
                ["type"] = "state",
                ["version"] = Heimdall.InstalledVersion,
                ["heimdall"] = heimdallBusy ?? (Heimdall.HeimdallOn ? "on" : "off"),
                ["server"] = server,
                ["players"] = feed?.Players,
                ["world"] = feed?.World,
                ["prefs"] = new Dictionary<string, object>
                {
                    ["onOpen"] = prefs.on_open,
                    ["withWindows"] = Heimdall.StartsWithWindows,
                    ["serverWith"] = prefs.server_with_heimdall,
                },
            });
        }
    }
}
