using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// Removes Heimdall. The window runs from a temporary copy of this app, because the
    /// installed copy lives in the folder being removed; the removal itself runs in an
    /// elevated worker with no window, which reports back to it.
    /// </summary>
    static class Uninstaller
    {
        /// <summary>From the app (the person already chose) or from Windows' installed apps list (keep: null).</summary>
        public static void Start(bool? keep)
        {
            var copy = Path.Combine(Path.GetTempPath(), "HeimdallNexus-uninstall.exe");
            try { File.Copy(Application.ExecutablePath, copy, true); }
            catch (IOException)
            {
                copy = Path.Combine(Path.GetTempPath(), $"HeimdallNexus-uninstall-{Guid.NewGuid():N}.exe");
                File.Copy(Application.ExecutablePath, copy, true);
            }
            var choice = keep == null ? "" : keep.Value ? " --keep" : " --erase";
            Process.Start(new ProcessStartInfo(copy, "--uninstall-ui" + choice) { UseShellExecute = false });
        }
    }

    sealed class UninstallFlow
    {
        readonly WebWindow window = new WebWindow();
        readonly bool? keep;
        Channel worker;
        bool removing, removed, kept;

        public static void Run(bool? keep) => Application.Run(new UninstallFlow(keep).window);

        UninstallFlow(bool? keep)
        {
            this.keep = keep;
            window.Command += OnCommand;
            window.FormClosing += (s, e) => { if (removing) e.Cancel = true; }; // it cannot stop halfway
            window.FormClosed += (s, e) => SelfDelete();
        }

        void OnCommand(Dictionary<string, object> message)
        {
            switch ((string)message["cmd"])
            {
                case "ready":
                    if (keep == null) window.Post(new { type = "screen", name = "farewell", ask = true });
                    else Begin(keep.Value);
                    break;
                case "uninstall":
                    Begin(message.TryGetValue("keep", out var k) && k is bool b && b);
                    break;
                case "close":
                    window.Close();
                    break;
            }
        }

        void Begin(bool keepData)
        {
            if (removing || removed) return;
            kept = keepData;
            window.Post(new { type = "screen", name = "farewell" });
            var name = Channel.NewName();
            worker = Channel.Serve(name);
            if (!Heimdall.RunElevated(Application.ExecutablePath, $"--uninstall-worker {(keepData ? "--keep" : "--erase")} --pipe {name}"))
            {
                worker.Dispose();
                window.Post(new { type = "farewellError", text = T.NeedsPermissionUninstall });
                return;
            }
            removing = true;
            bool answered = false;
            worker.Accept(message =>
            {
                answered = true;
                window.OnUi(() =>
                {
                    removing = false;
                    removed = message.TryGetValue("type", out var type) && (type as string) == "removed";
                    var text = message.TryGetValue("text", out var t) ? t as string : null;
                    window.Post(removed ? new { type = "removed", text }
                                        : (object)new { type = "farewellError", text = text ?? T.WorkerStopped });
                });
            }, () =>
            {
                if (answered) return;
                window.OnUi(() =>
                {
                    removing = false;
                    window.Post(new { type = "farewellError", text = T.WorkerStopped });
                });
            });
        }

        /// <summary>The temporary copy removes itself once closed; after a removal, also this app's own folders.</summary>
        void SelfDelete()
        {
            var command = $"ping -n 4 127.0.0.1 >nul & del /f /q \"{Application.ExecutablePath}\"";
            if (removed)
            {
                command += $" & rmdir /s /q \"{Path.GetDirectoryName(Runtime.Folder)}\"";
                if (!kept) command += $" & rmdir /s /q \"{Path.GetDirectoryName(Heimdall.PrefsFile)}\"";
            }
            Process.Start(new ProcessStartInfo("cmd.exe", "/c " + command) { CreateNoWindow = true, UseShellExecute = false });
        }
    }

    static class UninstallWorker
    {
        public static void Run(string pipe, bool keep)
        {
            Channel window;
            try { window = Channel.Connect(pipe); }
            catch (Exception) { return; }
            try
            {
                Remove(keep);
                window.Send(new { type = "removed", text = T.Removed + (keep ? " " + T.RemovedKept : "") });
            }
            catch (Exception error) { window.Send(new { type = "error", text = T.Error(error.Message) }); }
            window.Dispose();
        }

        static void Remove(bool keep)
        {
            // Run in place: only administrators can change Program Files, and PowerShell reads the
            // whole script before it starts removing that folder.
            var script = Path.Combine(Heimdall.AppDir, "app", "deploy", "windows", "uninstall.ps1");
            if (!File.Exists(script)) throw new Exception(script);
            var arguments = $"-NoProfile -ExecutionPolicy Bypass -File \"{script}\" -Yes -RemovePython" + (keep ? "" : " -RemoveData");
            using (var process = Process.Start(new ProcessStartInfo("powershell.exe", arguments)
                   { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true }))
            {
                var errors = process.StandardError.ReadToEndAsync();
                process.StandardOutput.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode != 0) throw new Exception(errors.Result.Trim());
            }
        }
    }
}
