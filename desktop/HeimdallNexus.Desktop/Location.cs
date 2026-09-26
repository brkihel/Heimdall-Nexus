using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.AccessControl;
using System.Security.Principal;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// Where to install. By default, the Windows folders on C: (Program Files and
    /// ProgramData). Or everything in one folder on another disk:
    /// &lt;disk&gt;:\HeimdallNexus\program and \data, with a note on what is where.
    ///
    /// The Heimdall services run with high privileges and read their code from this
    /// folder, so nobody but an administrator may change it, nor rename or replace
    /// any folder it sits in: a folder a user can rename is a folder a user can swap.
    /// </summary>
    static class Location
    {
        public const string FolderName = "HeimdallNexus";
        const long MinimumFree = 10L * 1024 * 1024 * 1024;

        static readonly SecurityIdentifier Administrators = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
        static readonly SecurityIdentifier System = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
        static readonly SecurityIdentifier Users = new SecurityIdentifier(WellKnownSidType.BuiltinUsersSid, null);
        static readonly SecurityIdentifier TrustedInstaller =
            new SecurityIdentifier("S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464");

        // What lets someone rename, delete or re-permission a folder.
        const FileSystemRights Takeover = FileSystemRights.Delete | FileSystemRights.DeleteSubdirectoriesAndFiles |
                                         FileSystemRights.ChangePermissions | FileSystemRights.TakeOwnership;
        const int GenericAll = 0x10000000, GenericWrite = 0x40000000;

        public static string SystemDrive => Path.GetPathRoot(Heimdall.ProgramFiles);

        public class Option
        {
            public string id, title, detail, reason;
            public bool ok;
        }

        /// <summary>The disks to offer: the Windows default first, then every fixed disk.</summary>
        public static List<Option> Options()
        {
            var options = new List<Option>();
            foreach (var drive in DriveInfo.GetDrives().Where(d => d.DriveType == DriveType.Fixed && d.IsReady))
            {
                bool system = string.Equals(drive.Name, SystemDrive, StringComparison.OrdinalIgnoreCase);
                var letter = drive.Name.TrimEnd('\\');
                var label = string.IsNullOrEmpty(drive.VolumeLabel) ? T.LocalDisk : drive.VolumeLabel;
                var option = new Option
                {
                    id = system ? "default" : letter,
                    title = system ? T.WindowsDefault(letter) : $"{label} ({letter})",
                    detail = T.FreeSpace(drive.AvailableFreeSpace / (1024L * 1024 * 1024)) + " · " +
                             (system ? Heimdall.DefaultAppDir : Path.Combine(drive.Name, FolderName)),
                };
                option.reason = system ? (drive.AvailableFreeSpace < MinimumFree ? T.NeedsSpaceShort : null)
                                       : Check(Path.Combine(drive.Name, FolderName));
                option.ok = option.reason == null;
                if (system) options.Insert(0, option); else options.Add(option);
            }
            return options;
        }

        /// <summary>The installation folder for a folder the person picked: always named HeimdallNexus.</summary>
        public static string RootFor(string picked)
        {
            var full = Path.GetFullPath(picked.TrimEnd('\\') + "\\");
            return string.Equals(new DirectoryInfo(full).Name, FolderName, StringComparison.OrdinalIgnoreCase)
                ? full.TrimEnd('\\') : Path.Combine(full, FolderName);
        }

        /// <summary>Null when Heimdall may be installed in <paramref name="root"/>; otherwise why not.</summary>
        public static string Check(string root)
        {
            try
            {
                root = Path.GetFullPath(root);
                if (!string.Equals(Path.GetFileName(root), FolderName, StringComparison.OrdinalIgnoreCase))
                    return T.Error(root);
                var drive = new DriveInfo(Path.GetPathRoot(root));
                if (!drive.IsReady || drive.DriveType != DriveType.Fixed) return T.NotFixedDisk;
                if (!string.Equals(drive.DriveFormat, "NTFS", StringComparison.OrdinalIgnoreCase)) return T.NotNtfs(drive.DriveFormat);
                if (drive.AvailableFreeSpace < MinimumFree) return T.NeedsSpaceShort;
                var windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
                foreach (var forbidden in new[] { windows, Heimdall.ProgramFiles, Heimdall.ProgramData,
                                                  Environment.GetFolderPath(Environment.SpecialFolder.UserProfile) })
                    if (!string.IsNullOrEmpty(forbidden) && Inside(root, forbidden)) return T.SystemFolder;
                if (Directory.Exists(root) && Directory.EnumerateFileSystemEntries(root).Any() && !PreviousInstall(root))
                    return T.FolderNotEmpty(root);
                for (var parent = Directory.GetParent(root); parent != null; parent = parent.Parent)
                    if (!Guarded(parent, parent.Parent == null)) return T.UnsafeFolder(parent.FullName);
                return null;
            }
            catch (UnauthorizedAccessException) { return T.UnsafeFolder(root); }
            catch (Exception error) { return T.Error(error.Message); }
        }

        static bool Inside(string path, string folder) =>
            (path.TrimEnd('\\') + "\\").StartsWith(folder.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);

        /// <summary>Kept after an uninstall that saved the worlds: Heimdall picks up where it left off.</summary>
        /// Only administrators can read inside data\, so this looks at what everyone may see.
        public static bool PreviousInstall(string root) =>
            Directory.Exists(Path.Combine(root, "data")) && File.Exists(Path.Combine(root, "LEIA-ME.txt")) &&
            Guarded(new DirectoryInfo(root), false);

        static bool Trusted(IdentityReference id) =>
            id is SecurityIdentifier sid && (sid == Administrators || sid == System || sid == TrustedInstaller);

        /// <summary>Only administrators, SYSTEM or TrustedInstaller may take this folder over.</summary>
        static bool Guarded(DirectoryInfo folder, bool diskRoot)
        {
            var acl = folder.GetAccessControl(AccessControlSections.Access | AccessControlSections.Owner);
            if (!Trusted(acl.GetOwner(typeof(SecurityIdentifier)))) return false;
            // A disk's root cannot be deleted or renamed; its children still could be.
            var takeover = diskRoot ? Takeover & ~FileSystemRights.Delete : Takeover;
            foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            {
                if (rule.AccessControlType != AccessControlType.Allow || Trusted(rule.IdentityReference)) continue;
                if ((rule.PropagationFlags & PropagationFlags.InheritOnly) != 0) continue; // children only
                var rights = (int)rule.FileSystemRights;
                if ((rights & (int)takeover) != 0 || (rights & (GenericAll | GenericWrite)) != 0) return false;
            }
            return true;
        }

        /// <summary>
        /// Elevated, before anything is written: checks again, then creates the folder
        /// owned by Administrators and cut from the disk's permissions.
        /// </summary>
        public static void Prepare(string root)
        {
            var problem = Check(root);
            if (problem != null) throw new SetupError(problem);
            var security = new DirectorySecurity();
            security.SetOwner(Administrators);
            security.SetAccessRuleProtection(true, false);
            const InheritanceFlags all = InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit;
            security.AddAccessRule(new FileSystemAccessRule(System, FileSystemRights.FullControl, all, PropagationFlags.None, AccessControlType.Allow));
            security.AddAccessRule(new FileSystemAccessRule(Administrators, FileSystemRights.FullControl, all, PropagationFlags.None, AccessControlType.Allow));
            security.AddAccessRule(new FileSystemAccessRule(Users, FileSystemRights.ReadAndExecute, all, PropagationFlags.None, AccessControlType.Allow));
            if (Directory.Exists(root)) new DirectoryInfo(root).SetAccessControl(security);
            else Directory.CreateDirectory(root, security);
            if (!Guarded(new DirectoryInfo(root), false)) throw new SetupError(T.UnsafeFolder(root));
        }
    }
}
