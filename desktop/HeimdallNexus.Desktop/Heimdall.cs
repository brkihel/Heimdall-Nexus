using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography.X509Certificates;
using System.Security.Principal;
using System.ServiceProcess;
using System.Web.Script.Serialization;

namespace HeimdallNexus.Desktop
{
    /// <summary>Paths, services and preferences of the Heimdall Nexus installed on this PC.</summary>
    static class Heimdall
    {
        public static readonly string ProgramData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
        public static readonly string ProgramFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        public static readonly string DataDir = Path.Combine(ProgramData, "HeimdallNexus");
        public static readonly string AppDir = Path.Combine(ProgramFiles, "HeimdallNexus");
        public static readonly string InstalledExe = Path.Combine(AppDir, "HeimdallNexus.exe");
        static readonly string DesktopInfo = Path.Combine(AppDir, "desktop.json");
        static readonly string PrefsFile = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "HeimdallNexus", "desktop-app.json");

        // The panel and website, in start order; the game is separate.
        public static readonly string[] Core =
            { "heimdall-executor", "heimdall-panel", "heimdall-web", "heimdall-jobs", "heimdall-sagas-jobs" };
        public const string Game = "heimdall-valheim";

        public static bool Installed =>
            File.Exists(DesktopInfo) && ServiceController.GetServices().Any(s => s.ServiceName == "heimdall-panel");

        public static Dictionary<string, object> Info()
        {
            try { return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(DesktopInfo)); }
            catch (Exception) { return new Dictionary<string, object>(); }
        }

        public static string PanelUrl => Info().TryGetValue("panel", out var v) ? v as string : "http://localhost/jarl/";
        public static string SiteUrl => Info().TryGetValue("site", out var v) ? v as string : "http://localhost/";
        public static string InstalledVersion => Info().TryGetValue("version", out var v) ? v as string : "";

        // ---------------------------------------------------------------- state
        public static ServiceControllerStatus? Status(string name)
        {
            try { using (var s = new ServiceController(name)) return s.Status; }
            catch (InvalidOperationException) { return null; }
        }

        public static bool HeimdallOn => Core.Take(3).All(n => Status(n) == ServiceControllerStatus.Running);
        public static bool ServerOn => Status(Game) == ServiceControllerStatus.Running;

        /// <summary>Players online, from the public status feed the website shows; null if unknown.</summary>
        public static int? PlayersOnline()
        {
            try
            {
                var path = Info().TryGetValue("status", out var v) ? v as string : null;
                if (string.IsNullOrEmpty(path) || !File.Exists(path)) return null;
                var feed = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
                if (!(feed.TryGetValue("online", out var up) && up is bool online && online)) return null;
                if (feed.TryGetValue("jogadores", out var p) && p is Dictionary<string, object> players &&
                    players.TryGetValue("online", out var count) && count is int n)
                    return n;
            }
            catch (Exception) { }
            return null;
        }

        // ---------------------------------------------------------------- actions
        public static void TurnOn(bool withServer, Action<string> report)
        {
            report(T.Starting);
            foreach (var name in Core)
                Start(name, TimeSpan.FromSeconds(90));
            if (withServer)
                Start(Game, TimeSpan.FromSeconds(60));
        }

        public static void StartServer() => Start(Game, TimeSpan.FromSeconds(60));

        /// <summary>Stops the game first: Valheim saves the world when its service stops.</summary>
        public static void StopServer(Action<string> report)
        {
            report(T.Saving);
            Stop(Game, TimeSpan.FromSeconds(180));
        }

        public static void TurnOff(Action<string> report)
        {
            StopServer(report);
            report(T.Stopping);
            foreach (var name in new[] { "heimdall-web", "heimdall-panel", "heimdall-sagas-jobs", "heimdall-jobs", "heimdall-executor" })
                Stop(name, TimeSpan.FromSeconds(60));
        }

        static void Start(string name, TimeSpan wait)
        {
            using (var s = new ServiceController(name))
            {
                if (s.Status == ServiceControllerStatus.Running) return;
                if (s.Status != ServiceControllerStatus.StartPending) s.Start();
                s.WaitForStatus(ServiceControllerStatus.Running, wait);
            }
        }

        static void Stop(string name, TimeSpan wait)
        {
            using (var s = new ServiceController(name))
            {
                if (s.Status == ServiceControllerStatus.Stopped) return;
                if (s.Status != ServiceControllerStatus.StopPending) s.Stop();
                s.WaitForStatus(ServiceControllerStatus.Stopped, wait);
            }
        }

        // ---------------------------------------------------------------- start with Windows
        public static bool StartsWithWindows => StartType("heimdall-panel") == ServiceStartMode.Automatic;

        static ServiceStartMode? StartType(string name)
        {
            try { using (var s = new ServiceController(name)) return s.StartType; }
            catch (InvalidOperationException) { return null; }
        }

        /// <summary>Panel, website and jobs start at boot; the game too when it should follow Heimdall.</summary>
        public static void SetStartWithWindows(bool boot, bool withServer)
        {
            foreach (var name in Core)
                SetStartType(name, boot);
            SetStartType(Game, boot && withServer);
        }

        const uint SC_MANAGER_CONNECT = 0x0001, SERVICE_CHANGE_CONFIG = 0x0002, SERVICE_NO_CHANGE = 0xFFFFFFFF;
        const uint SERVICE_AUTO_START = 2, SERVICE_DEMAND_START = 3;

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern IntPtr OpenSCManager(string machine, string database, uint access);
        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern IntPtr OpenService(IntPtr manager, string name, uint access);
        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern bool ChangeServiceConfig(IntPtr service, uint type, uint start, uint error, string path,
                                               string group, IntPtr tag, string dependencies, string user,
                                               string password, string display);
        [DllImport("advapi32.dll", SetLastError = true)]
        static extern bool CloseServiceHandle(IntPtr handle);

        static void SetStartType(string name, bool automatic)
        {
            IntPtr manager = OpenSCManager(null, null, SC_MANAGER_CONNECT);
            if (manager == IntPtr.Zero) throw new Win32Exception();
            try
            {
                IntPtr service = OpenService(manager, name, SERVICE_CHANGE_CONFIG);
                if (service == IntPtr.Zero) throw new Win32Exception();
                try
                {
                    if (!ChangeServiceConfig(service, SERVICE_NO_CHANGE, automatic ? SERVICE_AUTO_START : SERVICE_DEMAND_START,
                                             SERVICE_NO_CHANGE, null, null, IntPtr.Zero, null, null, null, null))
                        throw new Win32Exception();
                }
                finally { CloseServiceHandle(service); }
            }
            finally { CloseServiceHandle(manager); }
        }

        // ---------------------------------------------------------------- preferences (per Windows account)
        public class Prefs
        {
            public bool on_open { get; set; }
            public bool server_with_heimdall { get; set; }
        }

        public static Prefs LoadPrefs()
        {
            try { return new JavaScriptSerializer().Deserialize<Prefs>(File.ReadAllText(PrefsFile)) ?? new Prefs(); }
            catch (Exception) { return new Prefs(); }
        }

        public static void SavePrefs(Prefs prefs)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(PrefsFile));
            File.WriteAllText(PrefsFile, new JavaScriptSerializer().Serialize(prefs));
        }

        // ---------------------------------------------------------------- Windows helpers
        public static bool IsAdmin => new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
        public static string UserSid => WindowsIdentity.GetCurrent().User?.Value ?? "";

        /// <summary>Opens a web page or program as the signed-in user, never elevated.</summary>
        public static void OpenAsUser(string target)
        {
            Process.Start(new ProcessStartInfo("explorer.exe", "\"" + target + "\"") { UseShellExecute = true });
        }

        public static bool RunElevated(string exe, string arguments)
        {
            try
            {
                Process.Start(new ProcessStartInfo(exe, arguments) { UseShellExecute = true, Verb = "runas" });
                return true;
            }
            catch (Win32Exception) { return false; } // the person said no to the Windows prompt
        }

        public static bool AccessDenied(Exception error)
        {
            for (var e = error; e != null; e = e.InnerException)
                if (e is Win32Exception w && w.NativeErrorCode == 5) return true;
            return false;
        }

        // ---------------------------------------------------------------- signatures
        [DllImport("wintrust.dll", CharSet = CharSet.Unicode)]
        static extern int WinVerifyTrust(IntPtr window, ref Guid action, ref WinTrustData data);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct WinTrustFileInfo
        {
            public uint cbStruct; public string pcwszFilePath; public IntPtr hFile; public IntPtr pgKnownSubject;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct WinTrustData
        {
            public uint cbStruct; public IntPtr pPolicyCallbackData; public IntPtr pSIPClientData; public uint dwUIChoice;
            public uint fdwRevocationChecks; public uint dwUnionChoice; public IntPtr pFile; public uint dwStateAction;
            public IntPtr hWVTStateData; public string pwszURLReference; public uint dwProvFlags; public uint dwUIContext;
            public IntPtr pSignatureSettings;
        }

        /// <summary>True when Windows trusts the file's signature and it was signed by `organization`.</summary>
        public static bool SignedBy(string path, string organization)
        {
            var file = new WinTrustFileInfo { cbStruct = (uint)Marshal.SizeOf(typeof(WinTrustFileInfo)), pcwszFilePath = path };
            IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf(file));
            try
            {
                Marshal.StructureToPtr(file, pointer, false);
                var data = new WinTrustData
                {
                    cbStruct = (uint)Marshal.SizeOf(typeof(WinTrustData)), dwUIChoice = 2 /* none */,
                    fdwRevocationChecks = 0, dwUnionChoice = 1 /* file */, pFile = pointer, dwStateAction = 0,
                };
                var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE"); // WINTRUST_ACTION_GENERIC_VERIFY_V2
                if (WinVerifyTrust(IntPtr.Zero, ref action, ref data) != 0) return false;
            }
            finally { Marshal.FreeHGlobal(pointer); }
            var subject = X509Certificate.CreateFromSignedFile(path).Subject;
            return subject.Contains("O=" + organization);
        }
    }
}
