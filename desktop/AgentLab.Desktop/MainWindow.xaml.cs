using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Win32;

namespace AgentLab.Desktop
{
    public partial class MainWindow : Window
    {
        private readonly Backend backend;
        private List<AgentSettings> agents;
        private int step;
        private bool initialized, busy, repairing;
        private string cancelFile, runDirectory;
        private static readonly Brush Active = new SolidColorBrush(Color.FromRgb(45, 83, 86));
        private static readonly Brush Inactive = new SolidColorBrush(Color.FromRgb(36, 52, 79));

        public MainWindow(Backend backend, bool headless)
        {
            this.backend = backend;
            InitializeComponent();
            initialized = true;
            Apply(new Settings { agents = new List<AgentSettings> {
                new AgentSettings { slot = "Dars", name = "Builder", role = "Implementación", url = "http://127.0.0.1:8081" },
                new AgentSettings { slot = "Rade", name = "Reviewer", role = "Revisión", url = "http://127.0.0.1:8082" },
                new AgentSettings { slot = "Miso", name = "Tester", role = "Pruebas", url = "http://127.0.0.1:8083" } }, wsl_distro = "AgentLab-Repair", workspace_mode = "folder" });
            SetStep(0);
            Page("setup");
            if (!headless) Loaded += async (s, e) => await LoadSettings();
        }

        private void Apply(Settings settings)
        {
            agents = settings.agents;
            TeamCards.ItemsSource = EndpointCards.ItemsSource = LocalCards.ItemsSource = agents;
            LocalModels.IsChecked = settings.load_on_demand;
            ExistingServers.IsChecked = !settings.load_on_demand;
            LlamaPath.Text = settings.llama_server_path ?? "";
            PreferWsl.IsChecked = RepairWsl.IsChecked = settings.workspace_mode == "wsl";
            PreferFolder.IsChecked = RepairFolder.IsChecked = settings.workspace_mode != "wsl";
            DistroName.Text = RepairDistro.Text = settings.wsl_distro ?? "AgentLab-Repair";
            ConfigLocation.Text = backend.Config;
            Footer.Text = settings.exists ? "Configuración cargada. Puedes ajustar el equipo o comenzar una reparación." : "Bienvenido. Completa los cuatro pasos para guardar tu primera configuración.";
            LoadingChanged(null, null);
        }

        private async Task LoadSettings()
        {
            await Operation(async () => {
                var result = await backend.Run(new[] { "setup", "--snapshot" });
                result.RequireSuccess();
                Apply(Backend.Json.Deserialize<Settings>(result.Output));
            });
        }

        private Settings Draft()
        {
            if (LocalModels.IsChecked == true)
                for (int index = 0; index < agents.Count; index++) agents[index].url = "http://127.0.0.1:" + (8081 + index);
            return new Settings { agents = agents, load_on_demand = LocalModels.IsChecked == true,
                llama_server_path = LlamaPath.Text.Trim(), workspace_mode = PreferWsl.IsChecked == true ? "wsl" : "folder", wsl_distro = DistroName.Text.Trim() };
        }

        private async Task<bool> Operation(Func<Task> action)
        {
            if (busy) return false;
            busy = true; SetupPage.IsEnabled = RepairPage.IsEnabled = false; PythonButton.IsEnabled = false;
            try { await action(); return true; }
            catch (Exception ex) { Footer.Text = ex.Message; CheckReport.Text = ex.Message; StatusBadge.Text = "REQUIERE ATENCIÓN"; return false; }
            finally { busy = false; SetupPage.IsEnabled = RepairPage.IsEnabled = true; PythonButton.IsEnabled = true; }
        }

        private void SetStep(int selected)
        {
            step = Math.Max(0, Math.Min(3, selected));
            var views = new[] { TeamStep, ModelsStep, EnvironmentStep, FinishStep };
            var buttons = new[] { Step0, Step1, Step2, Step3 };
            for (int i = 0; i < 4; i++) { views[i].Visibility = i == step ? Visibility.Visible : Visibility.Collapsed; buttons[i].Background = i == step ? Active : Inactive; }
            BackButton.IsEnabled = step > 0; NextButton.Visibility = step < 3 ? Visibility.Visible : Visibility.Collapsed;
            StepLabel.Text = "PASO " + (step + 1) + " DE 4";
            if (step == 3) SetupSummary.Text = string.Join("\n", agents.Select(a => a.name + " · " + a.role)) + "\n\n" +
                (LocalModels.IsChecked == true ? "Modelos GGUF por turnos" : "Servidores existentes") + "\n" +
                (PreferWsl.IsChecked == true ? "WSL: " + DistroName.Text : "Comenzar con una copia de carpeta");
        }

        private void Page(string page)
        {
            SetupPage.Visibility = page == "setup" ? Visibility.Visible : Visibility.Collapsed;
            RepairPage.Visibility = page == "repair" ? Visibility.Visible : Visibility.Collapsed;
            ActivityPage.Visibility = page == "activity" ? Visibility.Visible : Visibility.Collapsed;
            SetupNav.Background = page == "setup" ? Active : Inactive;
            RepairNav.Background = page == "repair" ? Active : Inactive;
            ActivityNav.Background = page == "activity" ? Active : Inactive;
            PageTitle.Text = page == "setup" ? "Prepara tu equipo" : page == "repair" ? "Un objetivo compartido" : "El equipo en acción";
            PageSubtitle.Text = page == "setup" ? "De la primera conexión al primer arreglo, paso a paso." : page == "repair" ? "Define el problema y cómo comprobar que está resuelto." : "Propuestas, acuerdos y pruebas reales en un mismo lugar.";
        }

        private void ShowSetup(object sender, RoutedEventArgs e) { Page("setup"); }
        private void ShowRepair(object sender, RoutedEventArgs e) { Page("repair"); }
        private void ShowActivity(object sender, RoutedEventArgs e) { Page("activity"); }
        private void GoStep(object sender, RoutedEventArgs e) { SetStep(int.Parse((string)((Button)sender).Tag)); }
        private void PreviousStep(object sender, RoutedEventArgs e) { SetStep(step - 1); }
        private void NextStep(object sender, RoutedEventArgs e)
        {
            if (step == 0 && (agents.Any(a => string.IsNullOrWhiteSpace(a.name)) || agents.Select(a => a.name.Trim()).Distinct(StringComparer.OrdinalIgnoreCase).Count() != 3))
            { Footer.Text = "Escribe tres nombres distintos antes de continuar."; return; }
            SetStep(step + 1);
        }

        private void LoadingChanged(object sender, RoutedEventArgs e)
        {
            if (!initialized) return;
            bool local = LocalModels.IsChecked == true;
            LlamaPathPanel.Visibility = LocalCards.Visibility = local ? Visibility.Visible : Visibility.Collapsed;
            EndpointCards.Visibility = local ? Visibility.Collapsed : Visibility.Visible;
        }

        private static string SelectFile(string filter)
        {
            var dialog = new OpenFileDialog { Filter = filter, CheckFileExists = true };
            return dialog.ShowDialog() == true ? dialog.FileName : null;
        }
        private void BrowseLlama(object sender, RoutedEventArgs e) { string path = SelectFile("llama-server.exe|llama-server.exe|Ejecutables|*.exe"); if (path != null) LlamaPath.Text = path; }
        private void BrowseModel(object sender, RoutedEventArgs e) { string path = SelectFile("Modelos GGUF|*.gguf"); if (path != null) ((AgentSettings)((Button)sender).Tag).model = path; }
        private async void ChoosePython(object sender, RoutedEventArgs e)
        {
            string path = SelectFile("Python|python.exe;py.exe|Ejecutables|*.exe");
            if (path != null) { backend.SetPython(path); await LoadSettings(); }
        }
        private void BrowseFolder(object sender, RoutedEventArgs e)
        {
            using (var dialog = new System.Windows.Forms.FolderBrowserDialog { Description = "Carpeta original del proyecto", ShowNewFolderButton = false })
                if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK) TargetPath.Text = dialog.SelectedPath;
        }

        private async void SaveSettings(object sender, RoutedEventArgs e)
        {
            await Operation(async () => {
                var result = await backend.Run(new[] { "setup", "--save-json" }, Backend.Json.Serialize(Draft()));
                result.RequireSuccess();
                RepairDistro.Text = DistroName.Text.Trim(); RepairWsl.IsChecked = PreferWsl.IsChecked; RepairFolder.IsChecked = PreferFolder.IsChecked;
                Footer.Text = "Configuración guardada con respaldo. Ahora comprueba las conexiones o crea una reparación.";
                CheckReport.Text = "Guardado en " + backend.Config + "\nLa conexión aún no se ha comprobado."; StatusBadge.Text = "GUARDADO";
            });
        }

        private async void CheckSettings(object sender, RoutedEventArgs e)
        {
            await Operation(async () => {
                CheckReport.Text = "Comprobando la configuración guardada…";
                var result = await backend.Run(new[] { "setup", "--check" });
                if (result.Code > 1) result.RequireSuccess();
                var report = Backend.Json.Deserialize<Report>(result.Output);
                CheckReport.Text = string.Join("\n\n", report.checks.Select(c => (c.ok ? "OK · " : "PENDIENTE · ") + c.name + "\n" + c.detail));
                StatusBadge.Text = report.ready ? "COMPROBADO" : "PENDIENTES";
                Footer.Text = report.ready ? "Requisitos comprobados. El chat con GBNF se verifica durante la sesión." : "La configuración está disponible; resuelve los puntos pendientes antes de reparar.";
            });
        }

        private async void PrepareWsl(object sender, RoutedEventArgs e)
        {
            Page("activity"); ActivityLog.Clear(); SessionTitle.Text = "Preparando Linux dedicado";
            SessionDescription.Text = "Puede descargar Debian y herramientas. Espera a que termine antes de cerrar.";
            StatusBadge.Text = "PREPARANDO";
            bool ok = await Operation(async () => {
                var result = await backend.Run(new[] { "setup", "--prepare-wsl", DistroName.Text.Trim() }, onLine: AppendLog);
                result.RequireSuccess();
            });
            SessionTitle.Text = ok ? "WSL preparado" : "WSL requiere atención";
            SessionDescription.Text = ok ? "Vuelve al asistente para guardar y comprobar tu configuración." : "Consulta la salida y el mensaje inferior antes de volver a intentar.";
            StatusBadge.Text = ok ? "PREPARADO" : "REQUIERE ATENCIÓN";
        }

        private void RepairModeChanged(object sender, RoutedEventArgs e)
        {
            if (!initialized) return;
            bool wsl = RepairWsl.IsChecked == true;
            ApplyChanges.Visibility = FolderBrowseButton.Visibility = wsl ? Visibility.Collapsed : Visibility.Visible;
            RepairDistroPanel.Visibility = wsl ? Visibility.Visible : Visibility.Collapsed;
            TargetPath.Text = wsl ? "/workspace/mi-proyecto" : "";
            TargetHint.Text = wsl ? "Cambios directos, con acceso root a todo este WSL. La ruta elige el directorio de trabajo; no limita los permisos." : "El equipo reparará una copia. El original solo cambia si marcas aplicar y la sesión termina verificada.";
            TestCommand.Text = wsl ? "python3 -m unittest discover -s tests -v" : "python -m unittest discover -s tests -v";
        }

        private async void StartRepair(object sender, RoutedEventArgs e)
        {
            if (busy) return;
            int steps, timeout;
            if (string.IsNullOrWhiteSpace(TargetPath.Text) || string.IsNullOrWhiteSpace(Objective.Text) || string.IsNullOrWhiteSpace(TestCommand.Text) ||
                !int.TryParse(MaxSteps.Text, out steps) || steps < 1 || steps > 500 || !int.TryParse(CommandTimeout.Text, out timeout) || timeout < 1 || timeout > 3600)
            { Footer.Text = "Completa destino, objetivo y pruebas. Propuestas: 1–500; segundos: 1–3600."; return; }
            if (!File.Exists(backend.Config)) { Footer.Text = "Guarda primero la configuración del equipo en el asistente."; Page("setup"); return; }
            bool wsl = RepairWsl.IsChecked == true;
            string runtime = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AgentLab", "desktop");
            try { Directory.CreateDirectory(runtime); }
            catch (Exception ex) { Footer.Text = ex.Message; return; }
            cancelFile = Path.Combine(runtime, Guid.NewGuid().ToString("N") + ".cancel");
            runDirectory = null; OpenResultsButton.IsEnabled = false;
            var args = new List<string> { wsl ? "wsl" : "folder" };
            if (wsl) args.AddRange(new[] { "--distro", RepairDistro.Text.Trim(), "--path", TargetPath.Text.Trim() });
            else { args.Add(TargetPath.Text.Trim()); if (ApplyChanges.IsChecked == true) args.Add("--apply"); }
            args.AddRange(new[] { "--task", Objective.Text.Trim(), "--test", TestCommand.Text.Trim(), "--max-steps", steps.ToString(), "--timeout", timeout.ToString(), "--cancel-file", cancelFile });
            Page("activity"); ActivityLog.Clear(); SessionTitle.Text = "El equipo está trabajando"; StatusBadge.Text = "EN CURSO";
            SessionDescription.Text = "Cada edición necesita tres votos. Las pruebas se ejecutan después de cada cambio aprobado.";
            repairing = true; StopButton.IsEnabled = true;
            int exitCode = 2;
            bool completed = await Operation(async () => { var result = await backend.Run(args.ToArray(), onLine: AppendLog); exitCode = result.Code; });
            repairing = false; StopButton.IsEnabled = false;
            try { File.Delete(cancelFile); } catch (IOException) { }
            bool verified = completed && exitCode == 0;
            SessionTitle.Text = verified ? "Reparación verificada por el equipo" : "La sesión terminó sin verificación completa";
            SessionDescription.Text = verified ? "Las pruebas pasaron y los tres agentes aprobaron el resultado. Consulta los artefactos para revisar los cambios." : "Consulta el registro y result.json. Se conserva el trabajo realizado; un cierre sin verificar no es un arreglo aprobado.";
            StatusBadge.Text = verified ? "VERIFICADO" : "SIN VERIFICAR";
            OpenResultsButton.IsEnabled = runDirectory != null && Directory.Exists(runDirectory);
            Footer.Text = runDirectory == null ? "Consulta el registro para resolver los requisitos pendientes." : "Resultados: " + runDirectory;
        }

        private void AppendLog(string line)
        {
            Dispatcher.BeginInvoke(new Action(() => {
                if (line.StartsWith("Sesión: ") || line.StartsWith("Resultados: ")) runDirectory = line.Substring(line.IndexOf(':') + 1).Trim();
                if (ActivityLog.Text.Length > 180000) ActivityLog.Text = ActivityLog.Text.Substring(ActivityLog.Text.Length - 120000);
                ActivityLog.AppendText(line + Environment.NewLine); ActivityLog.ScrollToEnd();
            }));
        }
        private void StopRepair(object sender, RoutedEventArgs e)
        {
            if (!repairing || cancelFile == null) return;
            try { File.WriteAllText(cancelFile, "stop"); StopButton.IsEnabled = false; SessionDescription.Text = "Parada solicitada. Se conserva la sesión y se liberan los modelos propios al terminar la operación actual; puede tardar varios minutos."; }
            catch (IOException ex) { Footer.Text = ex.Message; }
        }
        private void OpenResults(object sender, RoutedEventArgs e)
        {
            if (runDirectory == null || !Directory.Exists(runDirectory)) return;
            try { Process.Start(new ProcessStartInfo(runDirectory) { UseShellExecute = true }); }
            catch (Win32Exception ex) { Footer.Text = ex.Message; }
        }
        private void OnClosing(object sender, CancelEventArgs e)
        {
            if (!busy) return;
            e.Cancel = true;
            if (repairing) StopRepair(null, null);
            Footer.Text = "Espera a que termine la operación actual. La reparación conserva sus resultados al detenerse.";
        }

        public void VerifyViews()
        {
            for (int i = 0; i < 4; i++) { SetStep(i); Measure(new Size(1180, 840)); Arrange(new Rect(0, 0, 1180, 840)); UpdateLayout(); }
            LocalModels.IsChecked = true; LoadingChanged(null, null); UpdateLayout();
            if (LocalCards.Visibility != Visibility.Visible) throw new InvalidOperationException("No se muestra la configuración GGUF.");
            ExistingServers.IsChecked = true; LoadingChanged(null, null);
            RepairWsl.IsChecked = true; RepairModeChanged(null, null);
            if (ApplyChanges.Visibility != Visibility.Collapsed || RepairDistroPanel.Visibility != Visibility.Visible) throw new InvalidOperationException("Controles WSL incorrectos.");
            RepairFolder.IsChecked = true; RepairModeChanged(null, null);
            foreach (string page in new[] { "repair", "activity", "setup" }) Page(page);
            SetStep(0);
            if (agents.Count != 3 || agents.Any(a => a.family != "native" && a.family != "gemma2"))
                throw new InvalidOperationException("Los selectores de plantilla no conservaron sus valores.");
        }
    }
}
