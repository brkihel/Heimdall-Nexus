using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// The WebView2 libraries travel inside this exe. The managed ones load from memory;
    /// the native loader is written to the user's own folder, since only the user's
    /// (never elevated) window uses it. The browser engine itself is Windows' own
    /// WebView2 Runtime, installed here only if this PC lacks it and the person agrees.
    /// </summary>
    static class Runtime
    {
        public static readonly string Folder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HeimdallNexus", "desktop");
        public static string UserDataFolder => Path.Combine(Folder, Heimdall.IsAdmin ? "webview-admin" : "webview");

        const string BootstrapperUrl = "https://go.microsoft.com/fwlink/p/?LinkId=2124703";

        public static Stream Resource(string name) => Assembly.GetExecutingAssembly().GetManifestResourceStream(name);

        static byte[] Bytes(string name)
        {
            using (var stream = Resource(name))
            using (var memory = new MemoryStream())
            {
                if (stream == null) return null;
                stream.CopyTo(memory);
                return memory.ToArray();
            }
        }

        /// <summary>Must run before any WebView2 type is touched.</summary>
        public static void LoadEmbeddedAssemblies()
        {
            var loaded = new Dictionary<string, Assembly>();
            AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
            {
                var name = new AssemblyName(e.Name).Name;
                lock (loaded)
                {
                    // Once per name: a second copy of the same library would not share its types.
                    if (loaded.TryGetValue(name, out var known)) return known;
                    var bytes = Bytes("lib/" + name + ".dll");
                    return loaded[name] = bytes == null ? null : Assembly.Load(bytes);
                }
            };
        }

        /// <summary>True when the window can be shown; offers to install the WebView2 Runtime if missing.</summary>
        public static bool Prepare()
        {
            var arch = RuntimeInformation.ProcessArchitecture == Architecture.Arm64 ? "arm64"
                     : Environment.Is64BitProcess ? "x64" : "x86";
            var loader = Bytes($"native/{arch}/WebView2Loader.dll");
            // Opened with "Run as administrator", the loader goes where only administrators can write.
            var folder = Path.Combine(Heimdall.IsAdmin ? Path.Combine(Heimdall.AppDir, "desktop") : Folder,
                                      "loader-" + Hash(loader).Substring(0, 16) + "-" + arch);
            var path = Path.Combine(folder, "WebView2Loader.dll");
            if (!File.Exists(path) || Hash(File.ReadAllBytes(path)) != Hash(loader))
            {
                Directory.CreateDirectory(folder);
                File.WriteAllBytes(path, loader);
            }
            CoreWebView2Environment.SetLoaderDllFolderPath(folder);
            if (Available()) return true;
            if (MessageBox.Show(T.NeedsWebView, "Heimdall Nexus", MessageBoxButtons.YesNo, MessageBoxIcon.Information)
                != DialogResult.Yes)
                return false;
            string problem = InstallWebView();
            if (problem == null && Available()) return true;
            MessageBox.Show(problem ?? T.WebViewFailed, "Heimdall Nexus", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }

        static bool Available()
        {
            try { return !string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString()); }
            catch (WebView2RuntimeNotFoundException) { return false; }
        }

        /// <summary>Microsoft's own small installer, checked for Microsoft's signature, with a waiting window.</summary>
        static string InstallWebView()
        {
            var wait = new Form
            {
                Text = "Heimdall Nexus", FormBorderStyle = FormBorderStyle.FixedDialog, ControlBox = false,
                StartPosition = FormStartPosition.CenterScreen, ClientSize = new Size(460, 110),
                BackColor = Color.FromArgb(13, 21, 29), ForeColor = Color.FromArgb(238, 221, 176),
            };
            wait.Controls.Add(new Label { Text = T.InstallingWebView, AutoSize = false, Bounds = new Rectangle(24, 20, 412, 44) });
            wait.Controls.Add(new ProgressBar { Style = ProgressBarStyle.Marquee, Bounds = new Rectangle(24, 72, 412, 12) });
            string problem = null;
            wait.Shown += (s, e) => Task.Run(() =>
            {
                try
                {
                    ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
                    var setup = Path.Combine(Path.GetTempPath(), "heimdall-webview2-setup.exe");
                    using (var client = new WebClient()) client.DownloadFile(BootstrapperUrl, setup);
                    if (!Heimdall.SignedBy(setup, "Microsoft Corporation"))
                    {
                        File.Delete(setup);
                        problem = T.BadWebView;
                        return;
                    }
                    using (var process = Process.Start(new ProcessStartInfo(setup, "/silent /install") { UseShellExecute = false }))
                        process.WaitForExit();
                    File.Delete(setup);
                }
                catch (Exception error) { problem = T.Error(error.Message); }
                finally { wait.BeginInvoke(new Action(wait.Close)); }
            });
            wait.ShowDialog();
            return problem;
        }

        static string Hash(byte[] data)
        {
            using (var sha = SHA256.Create())
                return string.Concat(sha.ComputeHash(data).Select(b => b.ToString("x2")));
        }
    }
}
