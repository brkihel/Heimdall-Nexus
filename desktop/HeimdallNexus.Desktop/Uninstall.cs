using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// Removes Heimdall with confirmation windows. It runs from a temporary copy of
    /// this app, because the installed copy lives in the folder being removed.
    /// </summary>
    static class Uninstaller
    {
        /// <summary>From the app or from Windows' installed apps list.</summary>
        public static void Start()
        {
            var copy = Path.Combine(Path.GetTempPath(), "HeimdallNexus-uninstall.exe");
            File.Copy(Application.ExecutablePath, copy, true);
            if (Heimdall.RunElevated(copy, "--uninstall-now"))
                Application.Exit();
        }

        public static void Run()
        {
            if (MessageBox.Show(T.UninstallConfirm, T.UninstallTitle, MessageBoxButtons.YesNo, MessageBoxIcon.Question,
                                MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                return;
            bool keep = MessageBox.Show(T.UninstallKeep, T.UninstallTitle, MessageBoxButtons.YesNo,
                                        MessageBoxIcon.Question, MessageBoxDefaultButton.Button1) == DialogResult.Yes;
            var form = new Form();
            Theme.Style(form, T.UninstallTitle);
            form.ClientSize = new Size(520, 150);
            form.ControlBox = false;
            var label = Theme.Label(T.Removing, Theme.Heading, Theme.GoldLight, 460);
            label.Location = new Point(28, 28);
            var bar = new ProgressBar { Style = ProgressBarStyle.Marquee, Location = new Point(28, 90), Width = 460, Height = 16 };
            form.Controls.Add(label);
            form.Controls.Add(bar);
            string problem = null;
            form.Shown += (s, e) => Task.Run(() =>
            {
                try { Remove(keep); }
                catch (Exception error) { problem = error.Message; }
                form.BeginInvoke(new Action(form.Close));
            });
            Application.Run(form);
            if (problem != null)
                MessageBox.Show(T.Error(problem), T.UninstallTitle, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            else
                MessageBox.Show(T.Removed + (keep ? "\n\n" + T.RemovedKept : ""), T.UninstallTitle,
                                MessageBoxButtons.OK, MessageBoxIcon.Information);
            SelfDelete();
        }

        static void Remove(bool keep)
        {
            var source = Path.Combine(Heimdall.AppDir, "app", "deploy", "windows", "uninstall.ps1");
            if (!File.Exists(source)) throw new Exception(source);
            var script = Path.Combine(Path.GetTempPath(), "heimdall-uninstall.ps1");
            File.Copy(source, script, true);
            var arguments = $"-NoProfile -ExecutionPolicy Bypass -File \"{script}\" -Yes -RemovePython" + (keep ? "" : " -RemoveData");
            using (var process = Process.Start(new ProcessStartInfo("powershell.exe", arguments)
                   { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true }))
            {
                var errors = process.StandardError.ReadToEndAsync();
                process.StandardOutput.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode != 0) throw new Exception(errors.Result.Trim());
            }
            File.Delete(script);
        }

        /// <summary>The temporary copy removes itself once it has closed.</summary>
        static void SelfDelete()
        {
            var me = Application.ExecutablePath;
            Process.Start(new ProcessStartInfo("cmd.exe", $"/c ping -n 3 127.0.0.1 >nul & del /f /q \"{me}\"")
                          { CreateNoWindow = true, UseShellExecute = false });
        }
    }
}
