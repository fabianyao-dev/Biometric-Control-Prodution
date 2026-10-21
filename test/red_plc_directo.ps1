<#
    red_plc_directo.ps1 - Red de la PC para el PLC Zelio (SR3NET01BD).

    El PLC va CABLEADO DIRECTO a la PC (dev y planta). Este script deja la
    NIC "del PLC" de la PC en la misma subred que el PLC, SIN tocar la red
    de planta (192.168.1.0/24).

    DOS topologias:

      A) DIRECTA (por defecto, recomendada)
         PC:  192.158.1.241/24   (sin gateway, sin DNS)
         PLC: 192.158.1.80
         El subred 192.158.1.0/24 NO existe en la red de planta, asi que no
         hay ambiguedad de rutas ni riesgo de que el trafico de la LAN se
         meta por el cable del PLC.
         Requiere que el PLC tenga la IP 192.158.1.80 (en Zelio Soft 2:
         Edit > Program configuration > Ethernet extension > Static address).

      B) ALIAS (-Alias): el PLC se queda en 192.168.1.80 (dentro del subred
         de planta) y no hay que tocar la programacion del PLC.
         La NIC del PLC conserva su IP y se le anade un alias /32
         (192.168.1.250/32) + una ruta host persistente hacia 192.168.1.80
         por esa NIC. El /32 evita duplicar 192.168.1.0/24 en dos NICs
         (que es lo que rompe la red de planta).

    USO (PowerShell como ADMINISTRADOR):

        .\red_plc_directo.ps1                        # prueba el enlace
        .\red_plc_directo.ps1 -Accion Apply          # topologia A
        .\red_plc_directo.ps1 -Accion Apply -Alias   # topologia B
        .\red_plc_directo.ps1 -Accion Undo           # deja la NIC como estaba

    OPCIONES:

        -Adaptador "Ethernet 2"    fuerza la NIC del PLC (si hay varias)
        -IpPlc  192.158.1.80        IP del PLC
        -IpPc   192.158.1.241       IP de la PC en la NIC del PLC
        -Prefijo 24
        -Alias                       usa la topologia B
        -IpPlcAlterno 192.168.1.80  IP del PLC en la topologia B
#>
param(
    [ValidateSet('Test', 'Apply', 'Undo')]
    [string]$Accion = 'Test',
    [string]$Adaptador = '',
    [string]$IpPlc = '192.158.1.80',
    [string]$IpPc = '192.158.1.241',
    [int]$Prefijo = 24,
    [switch]$Alias,
    [string]$IpPlcAlterno = '192.168.1.80'
)

$ErrorActionPreference = 'Stop'
$Respaldo = Join-Path $PSScriptRoot 'red_plc_backup.json'

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-IfIndexDefault {
    $r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Sort-Object -Property RouteMetric, InterfaceMetric |
        Select-Object -First 1
    if ($r) { return $r.InterfaceIndex }
    return $null
}

function Get-NicPlc {
    param([string]$Nombre)

    if ($Nombre) {
        $a = Get-NetAdapter -Name $Nombre -ErrorAction SilentlyContinue
        if (-not $a) { throw "No existe el adaptador '$Nombre'." }
        return $a
    }

    $idxDef = Get-IfIndexDefault
    $cand = @(Get-NetAdapter | Where-Object {
            $_.Status -eq 'Up' -and
            $_.ifIndex -ne $idxDef -and
            $_.InterfaceDescription -notmatch 'Loopback|Tunnel|WireGuard|VPN'
        })
    if ($cand.Count -eq 0) {
        throw ("No hay ninguna NIC candidata para el PLC (conectada y que " +
               "no sea la de la ruta por defecto). Conectala por cable o " +
               "usa -Adaptador.")
    }
    if ($cand.Count -gt 1) {
        Write-Host "NICs candidatas (elige una con -Adaptador):"
        foreach ($c in $cand) {
            Write-Host ("  - {0}  (ifIndex {1}, {2})" -f
                $c.Name, $c.ifIndex, $c.InterfaceDescription)
        }
        throw "Hay varias NICs candidatas: especifica -Adaptador."
    }
    return $cand[0]
}

function Guardar-Respaldo {
    param($Nic)

    $dirs = @(Get-NetIPAddress -InterfaceIndex $Nic.ifIndex -AddressFamily IPv4 `
            -ErrorAction SilentlyContinue | ForEach-Object {
            @{ ip = $_.IPAddress; prefijo = $_.PrefixLength }
        })
    $rutas = @(Get-NetRoute -InterfaceIndex $Nic.ifIndex -AddressFamily IPv4 `
            -ErrorAction SilentlyContinue |
            Where-Object { $_.DestinationPrefix -ne '255.255.255.255/32' } |
            ForEach-Object {
            @{ destino = $_.DestinationPrefix; siguiente = $_.NextHop
                metrica = $_.RouteMetric }
            })
    @{ nombre = $Nic.Name; ifIndex = $Nic.ifIndex
        direcciones = $dirs; rutas = $rutas
    } | ConvertTo-Json -Depth 5 | Set-Content -Path $Respaldo -Encoding UTF8
    Write-Host "Respaldo de la NIC guardado en $Respaldo"
}

function Set-DireccionDirecta {
    param($Nic, [string]$Ip, [int]$Pref)

    Write-Host "Quitando las IPv4 actuales de '$($Nic.Name)'..."
    Get-NetIPAddress -InterfaceIndex $Nic.ifIndex -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-NetIPAddress -InterfaceIndex $Nic.ifIndex -IPAddress $_.IPAddress `
            -Confirm:$false -ErrorAction SilentlyContinue
    }
    Get-NetRoute -InterfaceIndex $Nic.ifIndex -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.DestinationPrefix -eq '0.0.0.0/0' } | ForEach-Object {
        Remove-NetRoute -InterfaceIndex $Nic.ifIndex `
            -DestinationPrefix '0.0.0.0/0' -Confirm:$false `
            -ErrorAction SilentlyContinue
    }
    Set-DnsClientServerAddress -InterfaceIndex $Nic.ifIndex `
        -ResetServerAddresses -ErrorAction SilentlyContinue

    New-NetIPAddress -InterfaceIndex $Nic.ifIndex -IPAddress $Ip `
        -PrefixLength $Pref | Out-Null
    Write-Host "OK: '$($Nic.Name)' ahora es $Ip/$Pref (sin gateway ni DNS)."
}

function Set-Alias {
    param($Nic, [string]$IpAlias, [string]$IpDestino)

    $existe = Get-NetIPAddress -InterfaceIndex $Nic.ifIndex -IPAddress $IpAlias `
        -ErrorAction SilentlyContinue
    if (-not $existe) {
        New-NetIPAddress -InterfaceIndex $Nic.ifIndex -IPAddress $IpAlias `
            -PrefixLength 32 | Out-Null
    }
    $ruta = Get-NetRoute -DestinationPrefix "$IpDestino/32" `
        -InterfaceIndex $Nic.ifIndex -ErrorAction SilentlyContinue
    if (-not $ruta) {
        New-NetRoute -DestinationPrefix "$IpDestino/32" `
            -InterfaceIndex $Nic.ifIndex -NextHop '0.0.0.0' -RouteMetric 1 `
            -PolicyStore PersistentStore | Out-Null
    }
    Write-Host ("OK: alias $IpAlias/32 en '$($Nic.Name)' + ruta host " +
                "$IpDestino/32 por esa NIC.")
}

function Quitar-Alias {
    param($Nic, [string]$IpAlias)

    Get-NetIPAddress -InterfaceIndex $Nic.ifIndex -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.PrefixLength -eq 32 } | ForEach-Object {
        Remove-NetIPAddress -InterfaceIndex $Nic.ifIndex `
            -IPAddress $_.IPAddress -Confirm:$false -ErrorAction SilentlyContinue
    }
    Get-NetRoute -InterfaceIndex $Nic.ifIndex -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.DestinationPrefix -match '/32$' -and
                       $_.NextHop -eq '0.0.0.0' } | ForEach-Object {
        Remove-NetRoute -InterfaceIndex $Nic.ifIndex `
            -DestinationPrefix $_.DestinationPrefix -Confirm:$false `
            -ErrorAction SilentlyContinue
    }
    Write-Host "Alias y rutas /32 quitados de '$($Nic.Name)'."
}

function Restaurar-Respaldo {
    if (-not (Test-Path $Respaldo)) {
        Write-Host "No hay respaldo ($Respaldo): nada que restaurar."
        return
    }
    $d = Get-Content -Path $Respaldo -Raw | ConvertFrom-Json
    $idx = $d.ifIndex
    Write-Host "Restaurando la configuracion previa de '$($d.nombre)'..."
    foreach ($r in $d.rutas) {
        try {
            New-NetRoute -DestinationPrefix $r.destino -InterfaceIndex $idx `
                -NextHop $r.siguiente -RouteMetric $r.metrica `
                -PolicyStore ActiveStore -ErrorAction Stop | Out-Null
        } catch {
            Write-Host "  (ruta $($r.destino) no restaurada: $($_.Exception.Message))"
        }
    }
    foreach ($a in $d.direcciones) {
        try {
            New-NetIPAddress -InterfaceIndex $idx -IPAddress $a.ip `
                -PrefixLength $a.prefijo -ErrorAction Stop | Out-Null
        } catch {
            Write-Host "  (IP $($a.ip) no restaurada: $($_.Exception.Message))"
        }
    }
    Remove-Item $Respaldo -Force
    Write-Host "Configuracion previa restaurada."
}

function Test-Puerto {
    # Test TCP puro (.NET): no depende de Test-NetConnection ni de los
    # modulos de CIM. Devuelve el codigo y la IP local usada.
    param([string]$Servidor, [int]$Puerto, [int]$TimeoutMs = 2500)

    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $tarea = $cliente.ConnectAsync($Servidor, $Puerto)
        if (-not $tarea.Wait($TimeoutMs)) {
            return @{ ok = $false; local = ''; motivo = 'timeout' }
        }
        if (-not $cliente.Connected) {
            return @{ ok = $false; local = ''; motivo = 'sin conexion' }
        }
        $local = $cliente.Client.LocalEndPoint.ToString()
        return @{ ok = $true; local = $local; motivo = '' }
    } catch {
        return @{ ok = $false; local = ''; motivo = $_.Exception.Message }
    } finally {
        $cliente.Close()
    }
}

function Mostrar-Estado {
    param($Nic, [string]$Ip)

    Write-Host ""
    Write-Host "=== Estado de '$($Nic.Name)' (ifIndex $($Nic.ifIndex)) ==="
    Get-NetIPAddress -InterfaceIndex $Nic.ifIndex -AddressFamily IPv4 |
        Select-Object IPAddress, PrefixLength, PrefixOrigin |
        Format-Table -AutoSize
    Write-Host "=== Ruta que se usaria hacia $Ip ==="
    Find-NetRoute -RemoteIPAddress $Ip -ErrorAction SilentlyContinue |
        Select-Object IPAddress, InterfaceAlias, NextHop, RouteMetric |
        Format-Table -AutoSize
    Write-Host "=== Ping a $Ip ==="
    ping -n 2 $Ip
    Write-Host "=== Modbus TCP (puerto 502) ==="
    $t = Test-Puerto -Servidor $Ip -Puerto 502
    Write-Host ("TcpTestSucceeded : {0}" -f $t.ok)
    if ($t.local) {
        Write-Host ("IP local usada  : {0}" -f $t.local)
    }
    if (-not $t.ok -and $t.motivo) {
        Write-Host ("Motivo           : {0}" -f $t.motivo)
    }
    Write-Host "=== ARP ==="
    arp -a | Select-String -Pattern ([regex]::Escape($Ip))
    Write-Host ""
}

# ----------------------------------------------------------------------
# Ejecucion
# ----------------------------------------------------------------------

if ($Accion -ne 'Test' -and -not (Test-Admin)) {
    throw ("La accion '$Accion' necesita PowerShell como ADMINISTRADOR " +
           "(click derecho > Ejecutar como administrador).")
}

$nic = Get-NicPlc -Nombre $Adaptador
Write-Host "NIC del PLC: '$($nic.Name)' (ifIndex $($nic.ifIndex), $($nic.InterfaceDescription))"

switch ($Accion) {
    'Test' {
        Mostrar-Estado -Nic $nic -Ip $IpPlc
    }
    'Apply' {
        Guardar-Respaldo -Nic $nic
        if ($Alias) {
            Set-Alias -Nic $nic -IpAlias $IpPc -IpDestino $IpPlcAlterno
        } else {
            Set-DireccionDirecta -Nic $nic -Ip $IpPc -Pref $Prefijo
        }
        Write-Host ""
        Mostrar-Estado -Nic $nic -Ip $(if ($Alias) { $IpPlcAlterno } else { $IpPlc })
    }
    'Undo' {
        Quitar-Alias -Nic $nic -IpAlias $IpPc
        Restaurar-Respaldo
    }
}
