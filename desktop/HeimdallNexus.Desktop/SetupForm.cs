using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// Before installing: what will happen and a Start button. Started elevated
    /// (--install), the same window downloads Heimdall and its Python, opens the
    /// setup assistant in the browser and follows it to the end.
    /// </summary>
    class SetupForm : Form
    {
        const string PythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe";
        const int WizardPort = 8765;

        readonly bool installing;
        readonly string controllerSid;
        readonly bool desktopShortcut;
        readonly FlowLayoutPanel body;
        readonly CheckBox shortcut;
        readonly Button start;
        readonly ProgressBar bar;
        readonly Label step;
        readonly Label detail;
        readonly LinkLabel browserLink;
        Process wizard;
        string claimLink;
        volatile bool finished;

        public SetupForm(bool installing, string controllerSid, bool desktopShortcut)
        {
            this.installing = installing;
            this.controllerSid = controllerSid;
            this.desktopShortcut = desktopShortcut;
            Theme.Style(this, T.SetupTitle);
            ClientSize = new Size(640, 560);
            body = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false,
                Padding = new Padding(28, 24, 28, 20), AutoScroll = true,
            };
            Controls.Add(body);
            body.Controls.Add(Theme.Header(T.SetupTitle));
            body.Controls.Add(Theme.Label(T.SetupIntro, Theme.Heading));
            body.Controls.Add(Theme.Label(T.SetupWhat));
            body.Controls.Add(Theme.Label(T.SetupHowTitle, Theme.Heading, Theme.GoldLight));
            body.Controls.Add(Theme.Label(T.SetupHow));
            body.Controls.Add(Theme.Label(T.SetupNotes, Theme.Small, Theme.Muted));

            shortcut = new CheckBox
            {
                Text = T.DesktopShortcut, Checked = true, AutoSize = true, ForeColor = Theme.Text,
                Margin = new Padding(0, 6, 0, 10), Visible = !installing,
            };
            body.Controls.Add(shortcut);

            start = Theme.Button(T.StartInstall);
            start.Visible = !installing;
            start.Click += (s, e) => AskForAdmin();
            body.Controls.Add(start);

            bar = new ProgressBar { Width = 580, Height = 18, Maximum = 1000, Visible = installing, Margin = new Padding(0, 10, 0, 8) };
            step = Theme.Label("", Theme.Heading, Theme.GoldLight, 580);
            detail = Theme.Label("", Theme.Small, Theme.Muted, 580);
            browserLink = new LinkLabel
            {
                Text = T.OpenBrowserAgain, AutoSize = true, Visible = false, LinkColor = Theme.Gold,
                ActiveLinkColor = Theme.GoldLight, Margin = new Padding(0, 4, 0, 0),
            };
            browserLink.LinkClicked += (s, e) => { if (claimLink != null) Heimdall.OpenAsUser(claimLink); };
            body.Controls.AddRange(new Control[] { bar, step, detail, browserLink });

            if (installing)
                Shown += (s, e) => Task.Run(Install);
            FormClosing += OnClosing;
        }

        // ---------------------------------------------------------------- before: ask Windows for permission
        void AskForAdmin()
        {
            if (string.IsNullOrEmpty(BuildInfo.SourceUrl))
            {
                MessageBox.Show(T.DevBuild, "Heimdall Nexus", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            var arguments = $"--install --for {Heimdall.UserSid}" + (shortcut.Checked ? " --desktop-shortcut" : "");
            if (Heimdall.RunElevated(Application.ExecutablePath, arguments))
                Close(); // the elevated window takes over
        }

        // ---------------------------------------------------------------- during: elevated
        void Show(string text, string more = "", int? progress = null)
        {
            if (IsDisposed) return;
            BeginInvoke(new Action(() =>
            {
                step.Text = text;
                detail.Text = more;
                if (progress.HasValue) bar.Value = Math.Max(0, Math.Min(bar.Maximum, progress.Value));
            }));
        }

        void Fail(string message)
        {
            if (IsDisposed) return;
            BeginInvoke(new Action(() =>
            {
                step.Text = T.Failed;
                step.ForeColor = Theme.Bad;
                detail.Text = message;
                detail.ForeColor = Theme.Text;
                var close = Theme.Button(T.Close, false);
                close.Click += (s, e) => Close();
                body.Controls.Add(close);
            }));
        }

        void Install()
        {
            try
            {
                Show(T.StepCheck, "", 10);
                var os = Environment.OSVersion.Version;
                if (!Environment.Is64BitOperatingSystem || os.Major < 10 || (os.Major == 10 && os.Build < 17763))
                    throw new SetupError(T.NeedsWindows);
                var drive = new DriveInfo(Path.GetPathRoot(Heimdall.ProgramData));
                long freeGb = drive.AvailableFreeSpace / (1024L * 1024 * 1024);
                if (freeGb < 10) throw new SetupError(T.NeedsSpace(freeGb));
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;

                var setup = Path.Combine(Heimdall.DataDir, "setup", BuildInfo.Version);
                var package = setup + ".zip";
                Directory.CreateDirectory(Path.GetDirectoryName(package));
                if (!File.Exists(package) || Sha256(package) != BuildInfo.SourceSha256)
                    Download(BuildInfo.SourceUrl, package, T.StepDownload, 20, 180);
                Show(T.StepVerify, "", 185);
                if (Sha256(package) != BuildInfo.SourceSha256)
                {
                    File.Delete(package);
                    throw new SetupError(T.BadDownload);
                }
                if (Directory.Exists(setup)) Directory.Delete(setup, true);
                ZipFile.ExtractToDirectory(package, setup);
                var root = Directory.GetDirectories(setup).FirstOrDefault(d => File.Exists(Path.Combine(d, "deploy", "setup_server.py")))
                           ?? setup;

                var python = Path.Combine(Heimdall.AppDir, "python", "python.exe");
                if (!File.Exists(python)) InstallPython(python);

                Show(T.StepWizard, "", 420);
                StartWizard(python, root);
                Follow();
            }
            catch (SetupError error) { Fail(error.Message); }
            catch (Exception error) { Fail(T.Error(error.Message)); }
        }

        void InstallPython(string python)
        {
            var setup = Path.Combine(Path.GetTempPath(), "heimdall-python-3.12.10-amd64.exe");
            Download(PythonUrl, setup, T.StepPython, 200, 330);
            Show(T.StepPython, "", 340);
            if (!Heimdall.SignedBy(setup, "Python Software Foundation"))
            {
                File.Delete(setup);
                throw new SetupError(T.BadPython);
            }
            // TargetDir quoted: unquoted, a path with a space installs to C:\Program.
            var target = Path.GetDirectoryName(python);
            var arguments = $"/quiet InstallAllUsers=1 \"TargetDir={target}\" Include_launcher=0 PrependPath=0 " +
                            "Include_test=0 Include_doc=0 Include_tcltk=0 AssociateFiles=0 Shortcuts=0 CompileAll=1";
            using (var process = Process.Start(new ProcessStartInfo(setup, arguments) { UseShellExecute = false }))
            {
                process.WaitForExit();
                if (process.ExitCode != 0 || !File.Exists(python))
                    throw new SetupError(T.Error($"Python ({process.ExitCode})"));
            }
            File.Delete(setup);
        }

        void Download(string url, string target, string label, int from, int to)
        {
            var partial = target + ".partial";
            using (var client = new WebClient())
            {
                var done = new ManualResetEventSlim();
                Exception failure = null;
                client.DownloadProgressChanged += (s, e) =>
                {
                    var total = e.TotalBytesToReceive > 0 ? e.TotalBytesToReceive : 1;
                    Show(label, $"{e.BytesReceived / 1048576} MB / {Math.Max(1, total / 1048576)} MB",
                         from + (int)((to - from) * (double)e.BytesReceived / total));
                };
                client.DownloadFileCompleted += (s, e) => { failure = e.Error; done.Set(); };
                client.DownloadFileAsync(new Uri(url), partial);
                done.Wait();
                if (failure != null) throw new SetupError(T.Error(failure.Message));
            }
            if (File.Exists(target)) File.Delete(target);
            File.Move(partial, target);
        }

        static string Sha256(string path)
        {
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(path))
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }

        void StartWizard(string python, string root)
        {
            var info = new ProcessStartInfo(python,
                $"-X utf8 \"{Path.Combine(root, "deploy", "setup_server.py")}\" --port {WizardPort} --no-browser")
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true,
                RedirectStandardError = true, WorkingDirectory = root,
            };
            info.EnvironmentVariables["HEIMDALL_CONTROLLER_SID"] = controllerSid;
            info.EnvironmentVariables["HEIMDALL_DESKTOP_EXE"] = Application.ExecutablePath;
            info.EnvironmentVariables["HEIMDALL_DESKTOP_SHORTCUT"] = desktopShortcut ? "1" : "0";
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            wizard = Process.Start(info);
            var linkFound = new ManualResetEventSlim();
            var output = new StringBuilder();
            void Read(string line)
            {
                if (line == null) return;
                lock (output) output.AppendLine(line);
                var match = Regex.Match(line, @"http://127\.0\.0\.1:\d+/claim\?token=[A-Za-z0-9_-]+");
                if (match.Success && claimLink == null) { claimLink = match.Value; linkFound.Set(); }
            }
            wizard.OutputDataReceived += (s, e) => Read(e.Data);
            wizard.ErrorDataReceived += (s, e) => Read(e.Data);
            wizard.BeginOutputReadLine();
            wizard.BeginErrorReadLine();
            if (!linkFound.Wait(TimeSpan.FromSeconds(60)))
            {
                string text;
                lock (output) text = output.ToString();
                throw new SetupError(T.Error(text.Trim().Split('\n').LastOrDefault() ?? "setup_server"));
            }
            Heimdall.OpenAsUser(claimLink);
        }

        /// <summary>Mirrors the assistant's progress, read from the same setup server.</summary>
        void Follow()
        {
            var cookies = new CookieContainer();
            Get(claimLink, cookies); // the one-time link also signs this window in
            BeginInvoke(new Action(() => browserLink.Visible = true));
            var serializer = new JavaScriptSerializer();
            while (!finished)
            {
                Thread.Sleep(1500);
                Dictionary<string, object> state;
                try { state = serializer.Deserialize<Dictionary<string, object>>(Get($"http://127.0.0.1:{WizardPort}/api/state", cookies)); }
                catch (Exception) { if (wizard.HasExited) throw new SetupError(T.Error("setup_server")); continue; }
                var messages = state.TryGetValue("messages", out var m) ? (m as System.Collections.ArrayList) : null;
                var last = messages != null && messages.Count > 0 ? messages[messages.Count - 1] as Dictionary<string, object> : null;
                var lastText = last != null && last.TryGetValue("message", out var t) ? t as string : "";
                var stepName = state.TryGetValue("step", out var s) ? s as string : "";
                if (state.TryGetValue("error", out var e) && e is string error && error.Length > 0)
                {
                    Show(T.WizardFailed, error);
                    continue;
                }
                if (state.TryGetValue("done", out var d) && d is bool done && done)
                {
                    Finish();
                    return;
                }
                Show(T.ContinueInBrowser, lastText ?? "", Progress(stepName, lastText));
            }
        }

        static readonly Dictionary<string, int> StepProgress = new Dictionary<string, int>
        {
            ["starting"] = 440, ["folders"] = 450, ["permissions"] = 455, ["runtime"] = 460, ["python"] = 480,
            ["steamcmd"] = 500, ["valheim"] = 520, ["bepinex"] = 880, ["modpack"] = 900, ["game-service"] = 910,
            ["website"] = 920, ["panel"] = 940, ["services"] = 950, ["desktop"] = 970, ["firewall"] = 980,
            ["game-start"] = 990, ["complete"] = 1000,
        };

        static int Progress(string stepName, string message)
        {
            int value = StepProgress.TryGetValue(stepName ?? "", out var known) ? known : 430;
            // Valheim's download is the long part: follow SteamCMD's own percentage.
            var match = Regex.Match(message ?? "", @"progress: (\d+(?:\.\d+)?)");
            if (stepName == "valheim" && match.Success &&
                double.TryParse(match.Groups[1].Value, System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out var percent))
                value = 520 + (int)(3.5 * percent);
            return value;
        }

        static string Get(string url, CookieContainer cookies)
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.CookieContainer = cookies;
            request.Timeout = 10000;
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                return reader.ReadToEnd();
        }

        void Finish()
        {
            finished = true;
            Thread.Sleep(4000); // let the browser show its own "ready" screen first
            StopWizard();
            BeginInvoke(new Action(() =>
            {
                bar.Value = bar.Maximum;
                step.Text = T.Done;
                step.ForeColor = Theme.Good;
                detail.Text = T.DoneHint;
                detail.ForeColor = Theme.Text;
                browserLink.Visible = false;
                var open = Theme.Button(T.OpenCenter);
                open.Click += (s, e) =>
                {
                    Heimdall.OpenAsUser(File.Exists(Heimdall.InstalledExe) ? Heimdall.InstalledExe : Application.ExecutablePath);
                    Close();
                };
                body.Controls.Add(open);
            }));
        }

        void StopWizard()
        {
            try { if (wizard != null && !wizard.HasExited) wizard.Kill(); }
            catch (Exception) { }
        }

        void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (installing && !finished && wizard != null && !wizard.HasExited)
            {
                if (MessageBox.Show(T.ConfirmCancel, "Heimdall Nexus", MessageBoxButtons.YesNo, MessageBoxIcon.Question)
                    != DialogResult.Yes)
                {
                    e.Cancel = true;
                    return;
                }
            }
            finished = true;
            StopWizard();
        }
    }

    class SetupError : Exception
    {
        public SetupError(string message) : base(message) { }
    }
}
