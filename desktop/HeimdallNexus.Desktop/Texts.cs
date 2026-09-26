using System.Globalization;

namespace HeimdallNexus.Desktop
{
    /// <summary>Everything the app says, in Portuguese or English (follows Windows' language).</summary>
    static class T
    {
        public static readonly bool Pt = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "pt";

        static string P(string pt, string en) => Pt ? pt : en;

        // ---------------------------------------------------------------- installing
        public static string SetupTitle => P("Instalar o Heimdall Nexus", "Install Heimdall Nexus");
        public static string SetupIntro => P(
            "Este assistente coloca no seu computador:",
            "This assistant puts on your computer:");
        public static string SetupWhat => P(
            "•  o servidor dedicado de Valheim, o oficial da Iron Gate;\n" +
            "•  o painel do Heimdall, para cuidar do servidor pelo navegador;\n" +
            "•  o site do seu servidor, para mostrar aos amigos.",
            "•  the Valheim dedicated server, Iron Gate's official one;\n" +
            "•  the Heimdall panel, to run the server from your browser;\n" +
            "•  your server's website, to show your friends.");
        public static string SetupHowTitle => P("Como funciona", "How it works");
        public static string SetupHow => P(
            "1.  Clique em Iniciar instalação e permita quando o Windows perguntar.\n" +
            "2.  Esta janela baixa o que é preciso e abre o assistente no seu navegador.\n" +
            "3.  No navegador, você escolhe o nome do servidor, o mundo e as senhas.\n" +
            "     O Valheim é baixado nessa hora (cerca de 2 GB).",
            "1.  Click Start installation and allow it when Windows asks.\n" +
            "2.  This window downloads what is needed and opens the assistant in your browser.\n" +
            "3.  In the browser, you choose the server name, the world and the passwords.\n" +
            "     Valheim is downloaded at that point (about 2 GB).");
        public static string SetupNotes => P(
            "Leva de 20 a 40 minutos. Precisa de 10 GB livres e de internet.\n" +
            "Nada do Heimdall liga sozinho com o Windows: depois da instalação, você escolhe isso neste mesmo aplicativo.",
            "It takes 20 to 40 minutes and needs 10 GB free and internet.\n" +
            "Nothing from Heimdall starts with Windows by itself: after installing, you choose that in this same app.");
        public static string DesktopShortcut => P("Criar um atalho na área de trabalho", "Create a desktop shortcut");
        public static string StartInstall => P("Iniciar instalação", "Start installation");
        public static string Cancel => P("Cancelar", "Cancel");
        public static string Close => P("Fechar", "Close");

        public static string StepCheck => P("Conferindo o computador…", "Checking the computer…");
        public static string StepDownload => P("Baixando o Heimdall Nexus…", "Downloading Heimdall Nexus…");
        public static string StepVerify => P("Conferindo o pacote baixado…", "Checking the downloaded package…");
        public static string StepPython => P("Instalando o Python do Heimdall (ele fica escondido e não atrapalha outros programas)…",
                                             "Installing Heimdall's Python (it stays hidden and does not disturb other programs)…");
        public static string StepWizard => P("Abrindo o assistente no navegador…", "Opening the assistant in the browser…");
        public static string ContinueInBrowser => P(
            "Continue no navegador: preencha as cinco telas do assistente.\nEsta janela acompanha a instalação. Não feche.",
            "Continue in the browser: fill in the assistant's five screens.\nThis window follows the installation. Do not close it.");
        public static string OpenBrowserAgain => P("O navegador não abriu? Clique aqui.", "The browser did not open? Click here.");
        public static string WizardFailed => P(
            "Uma etapa falhou. Veja a mensagem no navegador, corrija a causa e clique em Tentar de novo lá.",
            "A step failed. See the message in the browser, fix the cause and click Try again there.");
        public static string Done => P("Pronto! O Heimdall Nexus está instalado.", "Done! Heimdall Nexus is installed.");
        public static string DoneHint => P(
            "Agora você liga, desliga e abre o Heimdall por este aplicativo, que fica no menu Iniciar.",
            "From now on you turn Heimdall on and off and open it from this app, found in the Start menu.");
        public static string OpenCenter => P("Abrir o Heimdall Nexus", "Open Heimdall Nexus");
        public static string Failed => P("A instalação não terminou", "The installation did not finish");
        public static string ConfirmCancel => P(
            "Parar a instalação agora? Você pode instalar de novo depois; o que já foi baixado é aproveitado.",
            "Stop the installation now? You can install again later; what was downloaded is reused.");
        public static string NeedsWindows => P(
            "O Heimdall Nexus precisa do Windows 10 (versão 1809 ou mais nova), Windows 11 ou Windows Server 2019, de 64 bits.",
            "Heimdall Nexus needs 64-bit Windows 10 (version 1809 or newer), Windows 11 or Windows Server 2019.");
        public static string NeedsSpace(long gb) => P(
            $"São precisos pelo menos 10 GB livres no disco C:. Agora há {gb} GB.",
            $"At least 10 GB must be free on drive C:. There are {gb} GB now.");
        public static string BadDownload => P(
            "O arquivo baixado não confere com o original. Pode ter sido um problema de internet: tente de novo.",
            "The downloaded file does not match the original. It may have been a network problem: try again.");
        public static string BadPython => P(
            "O instalador do Python não está assinado pela Python Software Foundation. A instalação foi interrompida por segurança.",
            "The Python installer is not signed by the Python Software Foundation. The installation stopped for safety.");
        public static string DevBuild => P(
            "Esta é uma versão de desenvolvimento do aplicativo, sem pacote de instalação. Baixe o aplicativo na página de versões do Heimdall Nexus.",
            "This is a development build of the app, without an installation package. Download the app from the Heimdall Nexus releases page.");

        // ---------------------------------------------------------------- control center
        public static string Heimdall => P("Heimdall (painel e site)", "Heimdall (panel and website)");
        public static string Server => P("Servidor de Valheim", "Valheim server");
        public static string On => P("Ligado", "On");
        public static string Off => P("Desligado", "Off");
        public static string Starting => P("Ligando…", "Starting…");
        public static string Stopping => P("Desligando…", "Stopping…");
        public static string Saving => P("Salvando o mundo e desligando…", "Saving the world and stopping…");
        public static string Players(int count) => count == 1 ? P("1 jogador online", "1 player online")
                                                             : P($"{count} jogadores online", $"{count} players online");
        public static string TurnOn => P("Ligar", "Turn on");
        public static string TurnOff => P("Desligar", "Turn off");
        public static string OpenPanel => P("Abrir o painel", "Open the panel");
        public static string OpenSite => P("Abrir o site", "Open the website");
        public static string WhenTitle => P("Quando ligar", "When to turn on");

        public static string OnOpen => P("Ligar o Heimdall quando eu abrir este aplicativo",
                                         "Turn Heimdall on when I open this app");
        public static string OnOpenHint => P(
            "Ao abrir este aplicativo, o painel e o site ligam sozinhos. Desligado: você liga pelo botão acima.",
            "When you open this app, the panel and the website start by themselves. Off: you turn them on with the button above.");
        public static string WithWindows => P("Ligar o Heimdall junto com o Windows",
                                              "Turn Heimdall on with Windows");
        public static string WithWindowsHint => P(
            "O painel e o site ligam quando o computador liga, mesmo sem abrir este aplicativo e sem ninguém entrar no Windows. " +
            "Desligado: nada do Heimdall roda até você mandar.",
            "The panel and the website start when the computer starts, even without opening this app and before anyone signs in. " +
            "Off: nothing from Heimdall runs until you say so.");
        public static string ServerWithHeimdall => P("Ligar o servidor de Valheim sempre que o Heimdall ligar",
                                                     "Start the Valheim server whenever Heimdall turns on");
        public static string ServerWithHeimdallHint => P(
            "Quando o Heimdall liga (pelo botão, ao abrir este aplicativo ou junto com o Windows), o servidor liga também. " +
            "Desligado: você liga o servidor pelo botão acima ou pelo painel.",
            "When Heimdall turns on (with the button, when opening this app or with Windows), the server starts too. " +
            "Off: you start the server with the button above or from the panel.");
        public static string ClosingNote => P("Fechar este aplicativo não desliga o Heimdall.",
                                              "Closing this app does not turn Heimdall off.");
        public static string Uninstall => P("Desinstalar o Heimdall Nexus…", "Uninstall Heimdall Nexus…");
        public static string NoPermission => P(
            "Esta conta do Windows não tem permissão para ligar ou desligar o Heimdall Nexus. " +
            "Use a conta que fez a instalação, ou abra este aplicativo com o botão direito → Executar como administrador.",
            "This Windows account may not turn Heimdall Nexus on or off. " +
            "Use the account that installed it, or right-click this app → Run as administrator.");
        public static string PanelSlow => P(
            "O painel demorou para responder. Espere um minuto e tente abrir de novo.",
            "The panel took long to answer. Wait a minute and try opening it again.");
        public static string SaveSlow => P(
            "O Valheim demorou demais para salvar e desligar. Tente de novo em um minuto.",
            "Valheim took too long to save and stop. Try again in a minute.");
        public static string Error(string reason) => P($"Algo deu errado: {reason}", $"Something went wrong: {reason}");

        // ---------------------------------------------------------------- uninstalling
        public static string UninstallTitle => P("Desinstalar o Heimdall Nexus", "Uninstall Heimdall Nexus");
        public static string UninstallConfirm => P(
            "Remover o Heimdall Nexus deste computador?\n\nO servidor, o painel, o site e os serviços do Heimdall serão desligados e removidos.",
            "Remove Heimdall Nexus from this computer?\n\nThe server, the panel, the website and Heimdall's services will be stopped and removed.");
        public static string UninstallKeep => P(
            "Guardar seus mundos, backups e o site?\n\nSim: ficam guardados em C:\\ProgramData\\HeimdallNexus, e uma nova instalação continua de onde parou.\n" +
            "Não: tudo é apagado de vez, inclusive os mundos.",
            "Keep your worlds, backups and website?\n\nYes: they stay in C:\\ProgramData\\HeimdallNexus, and a new installation picks up where you left off.\n" +
            "No: everything is erased for good, worlds included.");
        public static string Removing => P("Removendo o Heimdall Nexus… o mundo é salvo antes, se o servidor estiver ligado.",
                                           "Removing Heimdall Nexus… the world is saved first if the server is on.");
        public static string Removed => P("O Heimdall Nexus foi removido.", "Heimdall Nexus was removed.");
        public static string RemovedKept => P("Seus mundos e backups continuam em C:\\ProgramData\\HeimdallNexus.",
                                              "Your worlds and backups are still in C:\\ProgramData\\HeimdallNexus.");
    }
}
