using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// Before installing, the window shows what will happen and a Start button. Start asks
    /// Windows for permission once and runs <see cref="InstallWorker"/> elevated, with no
    /// window of its own; this window shows its progress until the end.
    /// </summary>
    sealed class SetupFlow
    {
        readonly WebWindow window = new WebWindow();
        Channel worker;
        bool installing, finished;

        public static void Run() => Application.Run(new SetupFlow().window);

        SetupFlow()
        {
            window.Command += OnCommand;
            window.FormClosing += (s, e) =>
            {
                if (!installing || finished) return;
                e.Cancel = true;
                window.Post(new { type = "confirmCancel" });
            };
        }

        void OnCommand(Dictionary<string, object> message)
        {
            switch ((string)message["cmd"])
            {
                case "ready":
                    window.Post(new { type = "screen", name = "welcome" });
                    break;
                case "install":
                    Start(message.TryGetValue("desktopShortcut", out var s) && s is bool shortcut && shortcut);
                    break;
                case "reopenBrowser":
                    worker?.Send(new { cmd = "reopenBrowser" });
                    break;
                case "cancelInstall":
                    worker?.Send(new { cmd = "cancel" });
                    finished = true;
                    window.Close();
                    break;
                case "openCenter":
                    Heimdall.OpenAsUser(File.Exists(Heimdall.InstalledExe) ? Heimdall.InstalledExe : Application.ExecutablePath);
                    window.Close();
                    break;
                case "close":
                    finished = true;
                    window.Close();
                    break;
            }
        }

        void Start(bool desktopShortcut)
        {
            if (installing) return;
            if (string.IsNullOrEmpty(BuildInfo.SourceUrl))
            {
                window.Post(new { type = "welcomeError", text = T.DevBuild });
                return;
            }
            var name = Channel.NewName();
            worker = Channel.Serve(name);
            var arguments = $"--install-worker --for {Heimdall.UserSid} --pipe {name}" + (desktopShortcut ? " --desktop-shortcut" : "");
            if (!Heimdall.RunElevated(Application.ExecutablePath, arguments))
            {
                worker.Dispose();
                worker = null;
                window.Post(new { type = "welcomeError", text = T.NeedsPermission });
                return;
            }
            installing = true;
            window.Post(new { type = "install", percent = 0, stage = 0, title = T.StepCheck });
            worker.Accept(message =>
            {
                if (message.TryGetValue("done", out var d) && d is bool done && done) finished = true;
                if (message.TryGetValue("fatal", out var f) && f is bool fatal && fatal) finished = true;
                window.Post(message);
            }, () =>
            {
                if (finished) return;
                finished = true;
                window.Post(new { type = "install", stage = (object)null, title = T.Failed, error = T.WorkerStopped, fatal = true });
            });
        }
    }

    /// <summary>
    /// The elevated side of the installation: downloads Heimdall and its Python, starts the
    /// setup assistant, opens it in the person's browser and follows it to the end.
    /// </summary>
    sealed class InstallWorker
    {
        const string PythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe";
        const int WizardPort = 8765;

        // The stages the window lists, in order.
        const int StageCheck = 0, StageDownload = 1, StagePython = 2, StageWizard = 3, StageBrowser = 4,
                  StageValheim = 5, StageFinish = 6, StageDone = 7;

        readonly Channel window;
        readonly string controllerSid;
        readonly bool desktopShortcut;
        Process wizard;
        string claimLink;
        volatile bool finished;

        public static void Run(string pipe, string controllerSid, bool desktopShortcut)
        {
            Channel channel;
            try { channel = Channel.Connect(pipe); }
            catch (Exception) { return; } // the window is gone
            new InstallWorker(channel, controllerSid, desktopShortcut).Install();
        }

        InstallWorker(Channel window, string controllerSid, bool desktopShortcut)
        {
            this.window = window;
            this.controllerSid = controllerSid;
            this.desktopShortcut = desktopShortcut;
            window.Listen(message =>
            {
                var cmd = message.TryGetValue("cmd", out var c) ? c as string : null;
                if (cmd == "reopenBrowser" && claimLink != null) Heimdall.OpenAsUser(claimLink);
                if (cmd == "cancel") Stop();
            }, Stop); // closing the window stops the installation, as it always did
        }

        void Stop()
        {
            if (finished) return;
            finished = true;
            StopWizard();
            Environment.Exit(1);
        }

        void Show(int stage, string title, string detail = "", int progress = -1, bool browser = false) =>
            window.Send(new Dictionary<string, object>
            {
                ["type"] = "install", ["stage"] = stage, ["title"] = title, ["detail"] = detail,
                ["percent"] = progress < 0 ? (object)null : progress / 10.0, ["browser"] = browser,
            });

        void Fail(string message, int stage)
        {
            finished = true;
            window.Send(new { type = "install", stage, title = T.Failed, error = message, fatal = true });
        }

        int stage = StageCheck;

        void Install()
        {
            try
            {
                Show(stage = StageCheck, T.StepCheck, "", 10);
                var os = Environment.OSVersion.Version;
                if (!Environment.Is64BitOperatingSystem || os.Major < 10 || (os.Major == 10 && os.Build < 17763))
                    throw new SetupError(T.NeedsWindows);
                var drive = new DriveInfo(Path.GetPathRoot(Heimdall.ProgramData));
                long freeGb = drive.AvailableFreeSpace / (1024L * 1024 * 1024);
                if (freeGb < 10) throw new SetupError(T.NeedsSpace(freeGb));
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;

                stage = StageDownload;
                var setup = Path.Combine(Heimdall.DataDir, "setup", BuildInfo.Version);
                var package = setup + ".zip";
                Directory.CreateDirectory(Path.GetDirectoryName(package));
                if (!File.Exists(package) || Sha256(package) != BuildInfo.SourceSha256)
                    Download(BuildInfo.SourceUrl, package, T.StepDownload, 20, 180);
                Show(stage, T.StepVerify, "", 185);
                if (Sha256(package) != BuildInfo.SourceSha256)
                {
                    File.Delete(package);
                    throw new SetupError(T.BadDownload);
                }
                if (Directory.Exists(setup)) Directory.Delete(setup, true);
                ZipFile.ExtractToDirectory(package, setup);
                var root = Directory.GetDirectories(setup).FirstOrDefault(d => File.Exists(Path.Combine(d, "deploy", "setup_server.py")))
                           ?? setup;

                stage = StagePython;
                var python = Path.Combine(Heimdall.AppDir, "python", "python.exe");
                if (!File.Exists(python)) InstallPython(python);

                Show(stage = StageWizard, T.StepWizard, "", 420);
                StartWizard(python, root);
                Follow();
            }
            catch (SetupError error) { Fail(error.Message, stage); }
            catch (Exception error) { Fail(T.Error(error.Message), stage); }
        }

        void InstallPython(string python)
        {
            var setup = Path.Combine(Path.GetTempPath(), "heimdall-python-3.12.10-amd64.exe");
            Download(PythonUrl, setup, T.StepPython, 200, 330);
            Show(stage, T.StepPython, T.StepPythonHint, 340);
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
                    Show(stage, label, $"{e.BytesReceived / 1048576} MB / {Math.Max(1, total / 1048576)} MB",
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
            Get(claimLink, cookies); // the one-time link also signs this worker in
            stage = StageBrowser;
            Show(stage, T.ContinueInBrowser, T.ContinueInBrowserHint, 430, true);
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
                if (state.TryGetValue("done", out var d) && d is bool done && done)
                {
                    Finish();
                    return;
                }
                var known = StepProgress.TryGetValue(stepName ?? "", out var progress);
                stage = !known ? StageBrowser : progress <= StepProgress["valheim"] ? StageValheim : StageFinish;
                var title = stage == StageBrowser ? T.ContinueInBrowser : stage == StageValheim ? T.StepValheim : T.StepFinish;
                var detail = stage == StageBrowser && string.IsNullOrEmpty(lastText) ? T.ContinueInBrowserHint : lastText ?? "";
                if (state.TryGetValue("error", out var e) && e is string error && error.Length > 0)
                    window.Send(new { type = "install", stage, title = T.StepFailed, detail = T.WizardFailed, error, browser = true });
                else
                    Show(stage, title, detail, Progress(stepName, lastText), true);
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
            Thread.Sleep(4000); // let the browser show its own "ready" screen first
            finished = true;
            StopWizard();
            window.Send(new { type = "install", percent = 100, stage = StageDone, done = true });
            window.Dispose();
        }

        void StopWizard()
        {
            try { if (wizard != null && !wizard.HasExited) wizard.Kill(); }
            catch (Exception) { }
        }
    }

    class SetupError : Exception
    {
        public SetupError(string message) : base(message) { }
    }
}
