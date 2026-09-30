using System;
using System.Diagnostics;
using System.IO;

namespace AciesLauncher
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            string defaultDir = @"C:\Users\JacobH\Documents\dev\ACIES-Tools\apps\ProjectManagement";
            string baseDir = defaultDir;

            string exeDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            if (File.Exists(Path.Combine(exeDir, "main.py")))
            {
                baseDir = exeDir;
            }

            string venvPythonW = Path.Combine(baseDir, ".venv", "Scripts", "pythonw.exe");
            string venvPython = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");
            // launch.py imports main so Python can cache its bytecode; running main.py
            // directly recompiles all of it on every start. Fall back for older checkouts.
            string launchPy = Path.Combine(baseDir, "launch.py");
            string entryPy = File.Exists(launchPy) ? launchPy : Path.Combine(baseDir, "main.py");

            string pythonExe = "pythonw.exe";
            if (File.Exists(venvPythonW))
            {
                pythonExe = venvPythonW;
            }
            else if (File.Exists(venvPython))
            {
                pythonExe = venvPython;
            }

            string arguments = "\"" + entryPy + "\"";
            if (args != null && args.Length > 0)
            {
                arguments += " " + string.Join(" ", args);
            }

            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = pythonExe,
                Arguments = arguments,
                WorkingDirectory = baseDir,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };

            try
            {
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                System.Windows.Forms.MessageBox.Show(
                    "Failed to start ACIES Project Management:\n\n" + ex.Message,
                    "ACIES Launcher Error",
                    System.Windows.Forms.MessageBoxButtons.OK,
                    System.Windows.Forms.MessageBoxIcon.Error
                );
            }
        }
    }
}
