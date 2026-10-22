using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace AgentLab.Desktop
{
    public class AgentSettings : INotifyPropertyChanged
    {
        private string agentName, modelPath, familyName = "native", endpoint, deviceName = "Vulkan0";
        public string slot { get; set; }
        public string role { get; set; }
        public string role_hint { get { return role == "Implementación" ? "Propone cambios concretos para resolver el fallo." : role == "Revisión" ? "Revisa corrección, alcance y compatibilidad." : "Comprueba pruebas y busca casos límite."; } }
        public string name { get { return agentName; } set { agentName = value; Changed("name"); } }
        public string model { get { return modelPath; } set { modelPath = value; Changed("model"); } }
        public string family { get { return familyName; } set { familyName = value; Changed("family"); } }
        public string url { get { return endpoint; } set { endpoint = value; Changed("url"); } }
        public string device { get { return deviceName; } set { deviceName = value; Changed("device"); } }
        public event PropertyChangedEventHandler PropertyChanged;
        private void Changed(string property) { PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(property)); }
    }

    public class Settings
    {
        public bool exists { get; set; }
        public string config_path { get; set; }
        public List<AgentSettings> agents { get; set; }
        public bool load_on_demand { get; set; }
        public string llama_server_path { get; set; }
        public string workspace_mode { get; set; }
        public string wsl_distro { get; set; }
    }

    public class Check { public string name { get; set; } public bool ok { get; set; } public string detail { get; set; } }
    public class Report { public bool ready { get; set; } public List<Check> checks { get; set; } }
    public class ProcessResult
    {
        public int Code;
        public string Output, Error;
        public void RequireSuccess()
        {
            if (Code != 0) throw new InvalidOperationException(string.IsNullOrWhiteSpace(Error) ? Output : Error);
        }
    }

    public sealed class Backend
    {
        public readonly string Root, Config;
        public string Python { get; private set; }
        public static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 };

        public Backend(string root, string config = null)
        {
            Root = Path.GetFullPath(root);
            Config = Path.GetFullPath(config ?? Path.Combine(Root, "config.json"));
            string preference = Path.Combine(Root, "work", "desktop-python.txt");
            Python = File.Exists(preference) ? File.ReadAllText(preference).Trim() : FindPython();
        }

        public void SetPython(string executable)
        {
            Python = Path.GetFullPath(executable);
            string directory = Path.Combine(Root, "work");
            Directory.CreateDirectory(directory);
            File.WriteAllText(Path.Combine(directory, "desktop-python.txt"), Python);
        }

        private static string FindPython()
        {
            foreach (string command in new[] { "python.exe", "py.exe" })
                foreach (string directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
                    try { string path = Path.Combine(directory.Trim('"'), command); if (File.Exists(path) && !path.Contains("WindowsApps")) return path; }
                    catch (ArgumentException) { }
            string installed = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Python");
            if (Directory.Exists(installed))
                foreach (string directory in Directory.GetDirectories(installed).OrderByDescending(p => p))
                    if (File.Exists(Path.Combine(directory, "python.exe"))) return Path.Combine(directory, "python.exe");
            return "python.exe";
        }

        // ProcessStartInfo on .NET Framework needs the Windows argv quoting rules.
        public static string Quote(string value)
        {
            var result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') result.Append('\\', slashes * 2 + 1);
                else result.Append('\\', slashes);
                slashes = 0;
                result.Append(c);
            }
            result.Append('\\', slashes * 2);
            return result.Append('"').ToString();
        }

        public Task<ProcessResult> Run(string[] arguments, string input = null, Action<string> onLine = null)
        {
            var all = new List<string>();
            all.AddRange(new[] { "-u", Path.Combine(Root, "agentlab.py"), "--config", Config });
            all.AddRange(arguments);
            string launcher = string.Equals(Path.GetFileName(Python), "py.exe", StringComparison.OrdinalIgnoreCase) ? "-3 " : "";
            var info = new ProcessStartInfo(Python, launcher + string.Join(" ", all.Select(Quote)))
            {
                WorkingDirectory = Root, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            return Task.Run(() =>
            {
                var output = new StringBuilder(); var error = new StringBuilder();
                using (var process = new Process { StartInfo = info })
                {
                    process.OutputDataReceived += (s, e) => { if (e.Data == null) return; lock (output) { if (output.Length < 2 * 1024 * 1024) output.AppendLine(e.Data); } onLine?.Invoke(e.Data); };
                    process.ErrorDataReceived += (s, e) => { if (e.Data == null) return; lock (error) { if (error.Length < 2 * 1024 * 1024) error.AppendLine(e.Data); } onLine?.Invoke(e.Data); };
                    try { process.Start(); }
                    catch (Win32Exception) { throw new InvalidOperationException("No se encontró Python. Instala Python 3.11 o posterior, o usa «Elegir Python»."); }
                    process.BeginOutputReadLine(); process.BeginErrorReadLine();
                    if (input != null) { byte[] bytes = Encoding.UTF8.GetBytes(input); process.StandardInput.BaseStream.Write(bytes, 0, bytes.Length); }
                    process.StandardInput.Close();
                    process.WaitForExit(); // Also drains both asynchronous readers.
                    return new ProcessResult { Code = process.ExitCode, Output = output.ToString(), Error = error.ToString() };
                }
            });
        }
    }
}
