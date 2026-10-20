Add-Type -AssemblyName System.Windows.Forms
Write-Output ("image_after=" + [System.Windows.Forms.Clipboard]::ContainsImage())
