$ErrorActionPreference = 'SilentlyContinue'

[Windows.Devices.Bluetooth.Advertisement.BluetoothLEAdvertisementWatcher, Windows.Devices.Bluetooth.Advertisement, ContentType=WindowsRuntime] | Out-Null

$watcher = [Windows.Devices.Bluetooth.Advertisement.BluetoothLEAdvertisementWatcher]::new()
$watcher.ScanningMode = [Windows.Devices.Bluetooth.Advertisement.BluetoothLEScanningMode]::Active

$sub = Register-ObjectEvent -InputObject $watcher -EventName Received -Action {
    $e = $Event.SourceEventArgs
    $name = $e.Advertisement.LocalName
    if ([string]::IsNullOrEmpty($name)) { $name = '(no-name)' }
    $addr = ('{0:X12}' -f $e.BluetoothAddress)
    $rssi = $e.RawSignalStrengthInDBm
    $uuids = ($e.Advertisement.ServiceUuids | ForEach-Object { $_.ToString() }) -join ' | '
    Write-Host ("FOUND: name=[{0}] MAC={1} RSSI={2}dBm UUID=[{3}]" -f $name, $addr, $rssi, $uuids)
}

$watcher.Start()
Write-Host "Scanning 20 seconds..."
Start-Sleep -Seconds 20
$watcher.Stop()
Unregister-Event -SubscriptionId $sub.Id
Write-Host "Scan done."
