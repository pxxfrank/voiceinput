Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = New-Object System.Drawing.Bitmap 32, 32
$g = [System.Drawing.Graphics]::FromImage($b)
$g.Clear([System.Drawing.Color]::Red)
[System.Windows.Forms.Clipboard]::SetImage($b)
Write-Output ("image=" + [System.Windows.Forms.Clipboard]::ContainsImage())
