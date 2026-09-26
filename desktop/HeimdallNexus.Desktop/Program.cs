using System;
using System.Linq;
using System.Windows.Forms;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// One exe for everything a Windows user does outside the browser:
    ///   (no arguments)    installs Heimdall, or turns it on and off once installed
    ///   --install         the elevated installation, started by the Install button
    ///   --uninstall       from Windows' installed apps list
    /// </summary>
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string Value(string name)
            {
                int index = Array.IndexOf(args, name);
                return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
            }

            if (args.Contains("--uninstall-now"))
            {
                Uninstaller.Run();
                return;
            }
            if (args.Contains("--uninstall"))
            {
                Uninstaller.Start();
                return;
            }
            if (args.Contains("--install"))
            {
                if (!Heimdall.IsAdmin) return;
                Application.Run(new SetupForm(true, Value("--for") ?? Heimdall.UserSid, args.Contains("--desktop-shortcut")));
                return;
            }
            Application.Run(Heimdall.Installed ? (Form)new CenterForm() : new SetupForm(false, Heimdall.UserSid, true));
        }
    }
}
