<#
.SYNOPSIS
Report whether the calling Windows session requires display sleep once per second.
.DESCRIPTION
Embedded in the host executable. Requires an active, unlocked physical-console
session to allow the display, without modifying Windows settings.
#>
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

/// <summary>Read the current session through the Windows WTS API.</summary>
public static class InfoTvSession {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Level1 {
        public uint SessionId;
        public int SessionState;
        public int SessionFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 33)] public string WinStationName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 21)] public string UserName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 18)] public string DomainName;
        public long LogonTime, ConnectTime, DisconnectTime, LastInputTime, CurrentTime;
        public uint IncomingBytes, OutgoingBytes, IncomingFrames, OutgoingFrames;
        public uint IncomingCompressedBytes, OutgoingCompressedBytes;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Info {
        public uint Level;
        public Level1 Data;
    }

    [DllImport("wtsapi32.dll", SetLastError = true)]
    private static extern bool WTSQuerySessionInformationW(
        IntPtr server, int session, int infoClass, out IntPtr buffer, out int bytes);

    [DllImport("wtsapi32.dll")]
    private static extern void WTSFreeMemory(IntPtr buffer);

    [DllImport("kernel32.dll")]
    private static extern uint WTSGetActiveConsoleSessionId();

    /// <summary>Apply lock policy unless this is the active, unlocked console session.</summary>
    public static bool RequiresLock(uint sessionId, int sessionState, int sessionFlags,
                                    uint consoleSessionId) {
        if (sessionFlags != 0 && sessionFlags != 1)
            throw new InvalidOperationException("Unknown WTS session lock state");
        // WTSActive = 0; no attached console is reported as 0xFFFFFFFF.
        return sessionFlags == 0 || sessionState != 0 ||
               consoleSessionId == uint.MaxValue || sessionId != consoleSessionId;
    }

    /// <summary>Query current-session WTS state and its physical-console attachment.</summary>
    public static bool IsLocked() {
        IntPtr buffer;
        int bytes;
        if (!WTSQuerySessionInformationW(IntPtr.Zero, -1, 25, out buffer, out bytes))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            if (buffer == IntPtr.Zero || bytes < Marshal.SizeOf(typeof(Info)))
                throw new InvalidOperationException("Incomplete WTS session information");
            Info info = (Info)Marshal.PtrToStructure(buffer, typeof(Info));
            if (info.Level != 1)
                throw new InvalidOperationException("Unknown WTS session lock state");
            return RequiresLock(info.Data.SessionId, info.Data.SessionState,
                                info.Data.SessionFlags, WTSGetActiveConsoleSessionId());
        } finally {
            WTSFreeMemory(buffer);
        }
    }
}
'@
$hostProcess = [System.Diagnostics.Process]::GetProcessById([int]$env:INFO_TV_HOST_PID)
while (-not $hostProcess.HasExited) {
    if ([InfoTvSession]::IsLocked()) {
        [Console]::WriteLine('locked')
    } else {
        [Console]::WriteLine('unlocked')
    }
    [Console]::Out.Flush()
    Start-Sleep -Seconds 1
}
