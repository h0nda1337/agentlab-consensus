using System;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace AgentLab.Desktop
{
    public partial class App : Application
    {
        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);
            string report = Option(e.Args, "--report");
            try
            {
                string root = Option(e.Args, "--root") ?? FindRoot();
                var backend = new Backend(root, Option(e.Args, "--config"));
                bool headless = e.Args.Contains("--self-test") || e.Args.Contains("--render-preview");
                var window = new MainWindow(backend, headless);
                MainWindow = window;
                if (headless)
                {
                    // An offscreen WPF tree: no Show(), focus, desktop capture or input.
                    window.VerifyViews();
                    var result = backend.Run(new[] { "setup", "--snapshot" }).GetAwaiter().GetResult();
                    result.RequireSuccess();
                    var loaded = Backend.Json.Deserialize<Settings>(result.Output);
                    if (loaded.agents == null || loaded.agents.Count != 3) throw new InvalidDataException("El backend no devolvió tres agentes.");
                    string scratch = Path.Combine(Path.GetTempPath(), "AgentLab test equipo á " + Guid.NewGuid().ToString("N"));
                    try
                    {
                        var testBackend = new Backend(root, Path.Combine(scratch, "config.json"));
                        loaded.load_on_demand = false; loaded.workspace_mode = "folder";
                        loaded.agents[0].name = "Atenea α";
                        var saved = testBackend.Run(new[] { "setup", "--save-json" }, Backend.Json.Serialize(loaded)).GetAwaiter().GetResult();
                        saved.RequireSuccess();
                        var readback = testBackend.Run(new[] { "setup", "--snapshot" }).GetAwaiter().GetResult();
                        readback.RequireSuccess();
                        if (Backend.Json.Deserialize<Settings>(readback.Output).agents[0].name != "Atenea α") throw new InvalidDataException("No se conservó el nombre Unicode.");
                    }
                    finally
                    {
                        if (Directory.Exists(scratch)) { File.Delete(Path.Combine(scratch, "config.json")); Directory.Delete(scratch); }
                    }
                    if (Backend.Quote("a\\") != "\"a\\\\\"" || Backend.Quote("a\"b") != "\"a\\\"b\"") throw new InvalidDataException("Argumentos de proceso incorrectos.");
                    string imagePath = Option(e.Args, "--render-preview");
                    if (imagePath != null)
                    {
                        var visual = (FrameworkElement)window.Content;
                        window.Content = null;
                        visual.Measure(new Size(1180, 840)); visual.Arrange(new Rect(0, 0, 1180, 840)); visual.UpdateLayout();
                        var bitmap = new RenderTargetBitmap(1180, 840, 96, 96, PixelFormats.Pbgra32);
                        bitmap.Render(visual);
                        var png = new PngBitmapEncoder(); png.Frames.Add(BitmapFrame.Create(bitmap));
                        using (var stream = File.Create(imagePath)) png.Save(stream);
                    }
                    if (report != null) File.WriteAllText(report, "OK: vistas WPF, argumentos, guardado JSON y nombres Unicode mediante Python. No se abrió ninguna ventana.");
                    Shutdown(0); return;
                }
                ShutdownMode = ShutdownMode.OnMainWindowClose;
                window.Show();
            }
            catch (Exception ex)
            {
                if (report != null) File.WriteAllText(report, ex.ToString());
                if (!e.Args.Contains("--self-test") && !e.Args.Contains("--render-preview"))
                    MessageBox.Show(ex.Message, "AgentLab · No se pudo iniciar", MessageBoxButton.OK, MessageBoxImage.Error);
                Shutdown(2);
            }
        }

        private static string Option(string[] args, string key)
        {
            int index = Array.IndexOf(args, key);
            if (index < 0) return null;
            if (index + 1 >= args.Length || args[index + 1].StartsWith("--")) throw new ArgumentException("Falta el valor de " + key);
            return args[index + 1];
        }

        private static string FindRoot()
        {
            foreach (string start in new[] { AppDomain.CurrentDomain.BaseDirectory, Environment.CurrentDirectory })
                for (var path = new DirectoryInfo(start); path != null; path = path.Parent)
                    if (File.Exists(Path.Combine(path.FullName, "agentlab.py"))) return path.FullName;
            throw new DirectoryNotFoundException("Conserva la aplicación dentro del repositorio o ejecútala con --root C:\\ruta\\agentlab-consensus.");
        }
    }
}
