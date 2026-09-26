using System;
using System.Drawing;
using System.ServiceProcess;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>After installing: turn Heimdall and the Valheim server on and off, and choose when they start.</summary>
    class CenterForm : Form
    {
        readonly Heimdall.Prefs prefs = Heimdall.LoadPrefs();
        readonly Dot heimdallDot = new Dot(), serverDot = new Dot();
        readonly Label heimdallState, serverState, busyLabel;
        readonly Button heimdallButton, serverButton, panelButton, siteButton;
        readonly Switch onOpen, withWindows, serverWithHeimdall;
        readonly Timer refresh = new Timer { Interval = 2000 };
        bool busy;

        public CenterForm()
        {
            Theme.Style(this, "Heimdall Nexus");
            ClientSize = new Size(640, 700);
            var body = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false,
                Padding = new Padding(28, 24, 28, 16), AutoScroll = true,
            };
            Controls.Add(body);
            body.Controls.Add(Theme.Header("Heimdall Nexus"));

            heimdallState = Theme.Label("", Theme.Body, Theme.Muted, 360);
            heimdallButton = Theme.Button(T.TurnOn);
            heimdallButton.Click += (s, e) => ToggleHeimdall();
            body.Controls.Add(StatusCard(T.Heimdall, heimdallDot, heimdallState, heimdallButton));

            serverState = Theme.Label("", Theme.Body, Theme.Muted, 360);
            serverButton = Theme.Button(T.TurnOn);
            serverButton.Click += (s, e) => ToggleServer();
            body.Controls.Add(StatusCard(T.Server, serverDot, serverState, serverButton));

            var links = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 0, 0, 10) };
            panelButton = Theme.Button(T.OpenPanel, false);
            panelButton.Click += (s, e) => Heimdall.OpenAsUser(Heimdall.PanelUrl);
            siteButton = Theme.Button(T.OpenSite, false);
            siteButton.Click += (s, e) => Heimdall.OpenAsUser(Heimdall.SiteUrl);
            links.Controls.Add(panelButton);
            links.Controls.Add(siteButton);
            body.Controls.Add(links);

            busyLabel = Theme.Label("", Theme.Heading, Theme.Busy);
            busyLabel.Visible = false;
            body.Controls.Add(busyLabel);

            body.Controls.Add(Theme.Label(T.WhenTitle, Theme.Heading, Theme.GoldLight));
            var choices = new Card();
            onOpen = Choice(choices, T.OnOpen, T.OnOpenHint);
            withWindows = Choice(choices, T.WithWindows, T.WithWindowsHint);
            serverWithHeimdall = Choice(choices, T.ServerWithHeimdall, T.ServerWithHeimdallHint);
            body.Controls.Add(choices);

            onOpen.Checked = prefs.on_open;
            serverWithHeimdall.Checked = prefs.server_with_heimdall;
            withWindows.Checked = Heimdall.StartsWithWindows;
            onOpen.CheckedChanged += (s, e) => { prefs.on_open = onOpen.Checked; Heimdall.SavePrefs(prefs); };
            withWindows.CheckedChanged += (s, e) => ApplyBoot();
            serverWithHeimdall.CheckedChanged += (s, e) =>
            {
                prefs.server_with_heimdall = serverWithHeimdall.Checked;
                Heimdall.SavePrefs(prefs);
                if (withWindows.Checked) ApplyBoot();
            };

            body.Controls.Add(Theme.Label(T.ClosingNote, Theme.Small, Theme.Muted));
            var uninstall = new LinkLabel
            {
                Text = T.Uninstall, AutoSize = true, LinkColor = Theme.Muted, ActiveLinkColor = Theme.GoldLight,
                Margin = new Padding(0, 4, 0, 0),
            };
            uninstall.LinkClicked += (s, e) => Uninstaller.Start();
            body.Controls.Add(uninstall);
            var version = Heimdall.InstalledVersion;
            if (!string.IsNullOrEmpty(version))
                body.Controls.Add(Theme.Label("Heimdall Nexus " + version, Theme.Small, Theme.Line));

            refresh.Tick += (s, e) => UpdateState();
            Shown += (s, e) =>
            {
                UpdateState();
                refresh.Start();
                if (prefs.on_open && !Heimdall.HeimdallOn)
                    Run(r => Heimdall.TurnOn(prefs.server_with_heimdall, r));
            };
        }

        static Card StatusCard(string title, Dot dot, Label state, Button button)
        {
            var card = new Card { FlowDirection = FlowDirection.LeftToRight, Width = 584 };
            var text = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, Width = 400, WrapContents = false };
            var line = new FlowLayoutPanel { AutoSize = true, WrapContents = false };
            line.Controls.Add(dot);
            line.Controls.Add(Theme.Label(title, Theme.Heading));
            text.Controls.Add(line);
            state.Margin = new Padding(22, 0, 0, 0);
            text.Controls.Add(state);
            card.Controls.Add(text);
            button.Margin = new Padding(20, 8, 0, 0);
            card.Controls.Add(button);
            return card;
        }

        static Switch Choice(Card card, string title, string hint)
        {
            var row = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 4, 0, 10) };
            var toggle = new Switch();
            var text = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, WrapContents = false };
            var label = Theme.Label(title, Theme.Heading, Theme.Text, 470);
            label.Cursor = Cursors.Hand;
            label.Click += (s, e) => toggle.Checked = !toggle.Checked;
            text.Controls.Add(label);
            text.Controls.Add(Theme.Label(hint, Theme.Small, Theme.Muted, 470));
            row.Controls.Add(toggle);
            row.Controls.Add(text);
            card.Controls.Add(row);
            return toggle;
        }

        void UpdateState()
        {
            if (busy) return;
            bool heimdall = Heimdall.HeimdallOn;
            var game = Heimdall.Status(Heimdall.Game);
            heimdallDot.Color = heimdall ? Theme.Good : Theme.Bad;
            heimdallState.Text = heimdall ? T.On : T.Off;
            heimdallButton.Text = heimdall ? T.TurnOff : T.TurnOn;
            panelButton.Enabled = siteButton.Enabled = heimdall;

            bool running = game == ServiceControllerStatus.Running;
            bool pending = game == ServiceControllerStatus.StartPending || game == ServiceControllerStatus.StopPending;
            serverDot.Color = running ? Theme.Good : pending ? Theme.Busy : Theme.Bad;
            var players = running ? Heimdall.PlayersOnline() : null;
            serverState.Text = pending ? (game == ServiceControllerStatus.StartPending ? T.Starting : T.Stopping)
                             : running ? T.On + (players.HasValue ? " · " + T.Players(players.Value) : "") : T.Off;
            serverButton.Text = running ? T.TurnOff : T.TurnOn;
            serverButton.Enabled = !pending;
        }

        void ToggleHeimdall()
        {
            if (Heimdall.HeimdallOn) Run(Heimdall.TurnOff);
            else Run(r => Heimdall.TurnOn(prefs.server_with_heimdall, r));
        }

        void ToggleServer()
        {
            if (Heimdall.ServerOn) Run(Heimdall.StopServer);
            else Run(r => { r(T.Starting); Heimdall.StartServer(); });
        }

        void ApplyBoot()
        {
            try { Heimdall.SetStartWithWindows(withWindows.Checked, serverWithHeimdall.Checked); }
            catch (Exception error)
            {
                MessageBox.Show(Heimdall.AccessDenied(error) ? T.NoPermission : T.Error(error.Message), "Heimdall Nexus",
                                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            withWindows.Checked = Heimdall.StartsWithWindows; // show what Windows really has
        }

        /// <summary>Runs a slow action off the window, showing what is happening.</summary>
        void Run(Action<Action<string>> action)
        {
            if (busy) return;
            busy = true;
            heimdallButton.Enabled = serverButton.Enabled = false;
            busyLabel.Visible = true;
            void Report(string text) => BeginInvoke(new Action(() => busyLabel.Text = text));
            Task.Run(() =>
            {
                string problem = null;
                try { action(Report); }
                catch (System.ServiceProcess.TimeoutException) { problem = T.SaveSlow; }
                catch (Exception error) { problem = Heimdall.AccessDenied(error) ? T.NoPermission : T.Error(error.Message); }
                BeginInvoke(new Action(() =>
                {
                    busy = false;
                    busyLabel.Visible = false;
                    heimdallButton.Enabled = serverButton.Enabled = true;
                    UpdateState();
                    if (problem != null)
                        MessageBox.Show(problem, "Heimdall Nexus", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }));
            });
        }
    }
}
