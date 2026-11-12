using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

/// <summary>Report the launch environment of a real console-subsystem child.</summary>
internal static class StartupProbe {
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();

    /// <summary>Persist console, directory, and argument observations before a distinct exit.</summary>
    private static int Main(string[] args) {
        string report = Environment.GetEnvironmentVariable("INFO_TV_STARTUP_PROBE");
        var lines = new List<string>();
        lines.Add(GetConsoleWindow().ToInt64().ToString());
        lines.Add(Environment.CurrentDirectory);
        lines.AddRange(args);
        File.WriteAllLines(report, lines, new UTF8Encoding(false));
        File.WriteAllText(Path.ChangeExtension(report, "pid"), Process.GetCurrentProcess().Id.ToString());
        if (Environment.GetEnvironmentVariable("INFO_TV_STARTUP_PROBE_WAIT") == "1") {
            Thread.Sleep(15000);
        }
        Thread.Sleep(150);
        return 37;
    }
}
