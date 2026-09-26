using System.Globalization;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// What the C# side says, in Portuguese or English (follows Windows' language). The
    /// window's own texts live in ../ui/app.js, which gets the same language from here.
    /// </summary>
    static class T
    {
        public static readonly bool Pt = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "pt";

        static string P(string pt, string en) => Pt ? pt : en;

        // ---------------------------------------------------------------- the WebView2 Runtime
        public static string NeedsWebView => P(
            "Para mostrar esta janela, o Heimdall Nexus usa o WebView2, um componente gratuito da Microsoft que já vem " +
            "no Windows 11 e na maioria dos Windows 10. Este computador ainda não tem.\n\nBaixar e instalar agora? " +
            "Leva um ou dois minutos.",
            "To show its window, Heimdall Nexus uses WebView2, a free Microsoft component that comes with Windows 11 " +
            "and most of Windows 10. This computer does not have it yet.\n\nDownload and install it now? " +
            "It takes a minute or two.");
        public static string InstallingWebView => P("Instalando o WebView2 da Microsoft…", "Installing Microsoft WebView2…");
        public static string BadWebView => P(
            "O instalador do WebView2 não está assinado pela Microsoft. A instalação foi interrompida por segurança.",
            "The WebView2 installer is not signed by Microsoft. The installation stopped for safety.");
        public static string WebViewFailed => P(
            "O WebView2 não ficou disponível. Reinicie o computador e abra o Heimdall Nexus de novo.",
            "WebView2 did not become available. Restart the computer and open Heimdall Nexus again.");

        // ---------------------------------------------------------------- installing
        public static string NeedsPermission => P(
            "A instalação precisa da permissão do Windows. Clique em Iniciar instalação de novo e escolha Sim quando o Windows perguntar.",
            "The installation needs Windows' permission. Click Start installation again and choose Yes when Windows asks.");
        public static string WorkerStopped => P(
            "A parte da instalação que roda com permissão de administrador parou sem avisar. Feche esta janela e tente de novo.",
            "The part of the installation that runs with administrator permission stopped without a word. Close this window and try again.");
        public static string StepCheck => P("Conferindo o computador…", "Checking the computer…");
        public static string StepDownload => P("Baixando o Heimdall Nexus…", "Downloading Heimdall Nexus…");
        public static string StepVerify => P("Conferindo o pacote baixado…", "Checking the downloaded package…");
        public static string StepPython => P("Instalando o Python do Heimdall…", "Installing Heimdall's Python…");
        public static string StepPythonHint => P("Ele fica escondido e não atrapalha outros programas.",
                                                 "It stays out of the way and does not disturb other programs.");
        public static string StepWizard => P("Abrindo o assistente no navegador…", "Opening the assistant in the browser…");
        public static string ContinueInBrowser => P("Continue no navegador", "Continue in the browser");
        public static string ContinueInBrowserHint => P(
            "Preencha as cinco telas do assistente. Esta janela acompanha a instalação; não feche.",
            "Fill in the assistant's five screens. This window follows the installation; do not close it.");
        public static string StepValheim => P("Baixando o servidor de Valheim…", "Downloading the Valheim server…");
        public static string StepFinish => P("Deixando tudo pronto…", "Getting everything ready…");
        public static string StepFailed => P("Uma etapa falhou", "A step failed");
        public static string WizardFailed => P(
            "Veja a mensagem no navegador, corrija a causa e clique em Tentar de novo lá.",
            "See the message in the browser, fix the cause and click Try again there.");
        public static string Failed => P("A instalação não terminou", "The installation did not finish");
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
        public static string Starting => P("Ligando…", "Starting…");
        public static string Stopping => P("Desligando…", "Stopping…");
        public static string Saving => P("Salvando o mundo e desligando…", "Saving the world and stopping…");
        public static string OpeningPanel => P("Abrindo o painel no navegador…", "Opening the panel in the browser…");
        public static string OpeningSite => P("Abrindo o site no navegador…", "Opening the website in the browser…");
        public static string NoPermission => P(
            "Esta conta do Windows não tem permissão para ligar ou desligar o Heimdall Nexus. " +
            "Use a conta que fez a instalação, ou abra este aplicativo com o botão direito → Executar como administrador.",
            "This Windows account may not turn Heimdall Nexus on or off. " +
            "Use the account that installed it, or right-click this app → Run as administrator.");
        public static string SaveSlow => P(
            "O Valheim demorou demais para salvar e desligar. Tente de novo em um minuto.",
            "Valheim took too long to save and stop. Try again in a minute.");
        public static string Error(string reason) => P($"Algo deu errado: {reason}", $"Something went wrong: {reason}");

        // ---------------------------------------------------------------- uninstalling
        public static string NeedsPermissionUninstall => P(
            "A desinstalação precisa da permissão do Windows. Nada foi removido.",
            "Uninstalling needs Windows' permission. Nothing was removed.");
        public static string Removed => P("O Heimdall Nexus foi removido deste computador.", "Heimdall Nexus was removed from this computer.");
        public static string RemovedKept => P("Seus mundos e backups continuam em C:\\ProgramData\\HeimdallNexus.",
                                              "Your worlds and backups are still in C:\\ProgramData\\HeimdallNexus.");
    }
}
