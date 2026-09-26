using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// The app's window: the page in ../ui, served from inside this exe and never from
    /// the network. The page shows state and asks for actions; C# does the work.
    /// </summary>
    sealed class WebWindow : Form
    {
        const string Origin = "https://app.heimdall-nexus.example/";
        const string Csp = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'none'";
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        static readonly Color Night = Color.FromArgb(7, 12, 18);

        readonly WebView2 view = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Night };
        readonly List<string> waiting = new List<string>();
        CoreWebView2Environment environment;
        bool ready;

        /// <summary>A message from the page: {cmd: ...}. "ready" arrives once the page can listen.</summary>
        public event Action<Dictionary<string, object>> Command;

        public WebWindow()
        {
            Text = "Heimdall Nexus";
            BackColor = Night;
            StartPosition = FormStartPosition.CenterScreen;
            using (var icon = Runtime.Resource("heimdall.ico")) Icon = new Icon(icon);
            Controls.Add(view);
            Load += (s, e) =>
            {
                float scale = DeviceDpi / 96f;
                var area = Screen.FromControl(this).WorkingArea;
                ClientSize = new Size(Math.Min((int)(1040 * scale), area.Width - 40), Math.Min((int)(740 * scale), area.Height - 40));
                MinimumSize = new Size((int)(760 * scale), (int)(560 * scale));
                CenterToScreen();
                _ = Start();
            };
        }

        async Task Start()
        {
            try
            {
                environment = await CoreWebView2Environment.CreateAsync(null, Runtime.UserDataFolder);
                await view.EnsureCoreWebView2Async(environment);
            }
            catch (Exception error)
            {
                MessageBox.Show(T.Error(error.Message), "Heimdall Nexus", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                Close();
                return;
            }
            var core = view.CoreWebView2;
            var settings = core.Settings;
#if DEBUG
            settings.AreDevToolsEnabled = true;
#else
            settings.AreDevToolsEnabled = false;
            settings.AreDefaultContextMenusEnabled = false;
            settings.AreBrowserAcceleratorKeysEnabled = false;
#endif
            settings.AreDefaultScriptDialogsEnabled = false;
            settings.IsStatusBarEnabled = false;
            settings.IsZoomControlEnabled = false;
            settings.IsGeneralAutofillEnabled = false;
            settings.IsPasswordAutosaveEnabled = false;
            core.AddWebResourceRequestedFilter(Origin + "*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += Serve;
            core.NavigationStarting += (s, e) => { if (!e.Uri.StartsWith(Origin, StringComparison.Ordinal)) e.Cancel = true; };
            core.NewWindowRequested += (s, e) => e.Handled = true;
            core.WebMessageReceived += Receive;
            core.Navigate(Origin + "index.html");
        }

        void Serve(object sender, CoreWebView2WebResourceRequestedEventArgs e)
        {
            var path = new Uri(e.Request.Uri).AbsolutePath.TrimStart('/');
            var stream = path.Contains("..") ? null : Runtime.Resource("ui/" + path);
            e.Response = stream == null
                ? environment.CreateWebResourceResponse(null, 404, "Not Found", "")
                : environment.CreateWebResourceResponse(stream, 200, "OK",
                    $"Content-Type: {Mime(path)}\r\nContent-Security-Policy: {Csp}\r\nCache-Control: no-store");
        }

        static string Mime(string path)
        {
            switch (Path.GetExtension(path).ToLowerInvariant())
            {
                case ".html": return "text/html; charset=utf-8";
                case ".css": return "text/css; charset=utf-8";
                case ".js": return "text/javascript; charset=utf-8";
                case ".svg": return "image/svg+xml";
                case ".webp": return "image/webp";
                case ".woff2": return "font/woff2";
                default: return "application/octet-stream";
            }
        }

        void Receive(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            if (!e.Source.StartsWith(Origin, StringComparison.Ordinal)) return;
            Dictionary<string, object> message;
            try { message = Json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson); }
            catch (Exception) { return; }
            if (message == null || !(message.TryGetValue("cmd", out var cmd) && cmd is string)) return;
            if ((string)cmd == "ready" && !ready)
            {
                ready = true;
                Post(new { type = "init", lang = T.Pt ? "pt" : "en" });
                foreach (var json in waiting) view.CoreWebView2.PostWebMessageAsJson(json);
                waiting.Clear();
            }
            Command?.Invoke(message);
        }

        /// <summary>Sends a message to the page, from any thread.</summary>
        public void Post(object message)
        {
            if (IsDisposed) return;
            if (InvokeRequired)
            {
                try { BeginInvoke(new Action(() => Post(message))); } catch (InvalidOperationException) { }
                return;
            }
            var json = Json.Serialize(message);
            if (ready) view.CoreWebView2.PostWebMessageAsJson(json);
            else waiting.Add(json);
        }

        /// <summary>Runs on the window's thread, from any thread.</summary>
        public void OnUi(Action action)
        {
            if (IsDisposed) return;
            try { BeginInvoke(action); } catch (InvalidOperationException) { }
        }
    }
}
