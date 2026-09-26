using System;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// One exe for everything a Windows user does outside the browser:
    ///   (no arguments)       installs Heimdall, or turns it on and off once installed
    ///   --uninstall          from Windows' installed apps list
    /// and, started by the app itself:
    ///   --install-worker     the elevated installation, reporting to the window
    ///   --uninstall-ui       the removal window, from a temporary copy
    ///   --uninstall-worker   the elevated removal, reporting to that window
    /// </summary>
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Runtime.LoadEmbeddedAssemblies();
            Route(args);
        }

        // Separate from Main so that no WebView2 type is resolved before the embedded libraries can load.
        [MethodImpl(MethodImplOptions.NoInlining)]
        static void Route(string[] args)
        {
            string Value(string name)
            {
                int index = Array.IndexOf(args, name);
                return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
            }
            bool? Keep() => args.Contains("--keep") ? true : args.Contains("--erase") ? false : (bool?)null;

            if (args.Contains("--install-worker"))
            {
                if (Heimdall.IsAdmin && Value("--pipe") != null)
                    InstallWorker.Run(Value("--pipe"), Value("--for") ?? Heimdall.UserSid, args.Contains("--desktop-shortcut"));
                return;
            }
            if (args.Contains("--uninstall-worker"))
            {
                if (Heimdall.IsAdmin && Value("--pipe") != null && Keep() != null)
                    UninstallWorker.Run(Value("--pipe"), Keep().Value);
                return;
            }
            if (args.Contains("--uninstall"))
            {
                Uninstaller.Start(null);
                return;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            if (!Runtime.Prepare()) return;
            if (args.Contains("--uninstall-ui")) UninstallFlow.Run(Keep());
            else if (Heimdall.Installed) CenterFlow.Run();
            else SetupFlow.Run();
        }
    }
}
