<#
.SYNOPSIS
Report the calling Windows session's lock state once per second.
.DESCRIPTION
Embedded in the host executable. Reads WTS session flags, including initial
state, without opening the display device or modifying Windows settings.
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

    /// <summary>Query WTSSessionInfoEx for WTS_CURRENT_SESSION on this machine.</summary>
    public static bool IsLocked() {
        IntPtr buffer;
        int bytes;
        if (!WTSQuerySessionInformationW(IntPtr.Zero, -1, 25, out buffer, out bytes))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            if (buffer == IntPtr.Zero || bytes < Marshal.SizeOf(typeof(Info)))
                throw new InvalidOperationException("Incomplete WTS session information");
            Info info = (Info)Marshal.PtrToStructure(buffer, typeof(Info));
            if (info.Level != 1 || (info.Data.SessionFlags != 0 && info.Data.SessionFlags != 1))
                throw new InvalidOperationException("Unknown WTS session lock state");
            return info.Data.SessionFlags == 0;
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
