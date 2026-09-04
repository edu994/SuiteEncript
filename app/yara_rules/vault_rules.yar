/*
Reglas propias para SuiteEncript — no pretenden ser un antivirus completo
ni cubrir todo el malware conocido (para eso existen sets públicos como
Yara-Rules/rules o Neo23x0/signature-base, con miles de reglas). Esta es
una capa de defensa en profundidad, chica y curada a propósito, además del
check de extensión + magic bytes que ya existe en
app/routes/vault.py::is_content_safe(). El criterio para elegir qué entra
acá es el mismo que ya se usó para ALLOWED_EXTENSIONS/DANGEROUS_MIME_TYPES:
patrones concretos y razonablemente específicos, no reglas tan genéricas
que generen falsos positivos constantes contra archivos legítimos.

Ver app/utils/malware_scan.py para cómo se cargan y usan estas reglas, y
la entrada correspondiente en CLAUDE.md para el detalle de esta decisión
(por qué un set propio y no uno público, y qué queda deliberadamente fuera
de alcance — no se descomprimen .zip/.7z/.tar/.gz para escanear adentro).
*/

rule EICAR_Test_File
{
    meta:
        description = "Archivo de prueba estandar de la industria antivirus (EICAR) -- no es malware real, existe para confirmar que un escaner de verdad esta funcionando."
        severity = "test"
    strings:
        // String oficial EICAR (eicar.org) -- inerte, no hace nada al
        // ejecutarse, es literalmente el archivo que se usa en todo el
        // mundo para probar que un antivirus detecta algo.
        $eicar = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    condition:
        $eicar
}

rule SuiteEncript_Selftest_Marker
{
    meta:
        description = "Marcador inerte e inventado, usado solo por los tests automatizados para verificar de punta a punta que el pipeline de escaneo (detectar -> rechazar -> loggear) funciona. No es una firma real de nada."
        severity = "n/a (solo test)"
        // Por que no usar el string real de EICAR en los tests: al
        // sincronizar este repo por OneDrive, Windows Defender (con
        // proteccion en tiempo real) detecto el patron EICAR dentro del
        // archivo de test -- incluso partido en dos literales o
        // codificado en base64 -- y borro el archivo del disco antes de
        // poder commitearlo. La regla EICAR_Test_File de arriba sigue
        // existiendo para detectar EICAR real en produccion (se verifico
        // manualmente end-to-end, ver CLAUDE.md), pero los tests
        // automatizados usan este marcador propio para no pelear
        // indefinidamente contra el antivirus del propio equipo cada vez
        // que alguien clona o sincroniza el repo.
    strings:
        $marker = "SUITEENCRIPT-MALWARE-SCAN-SELFTEST-7f3a9c"
    condition:
        $marker
}

rule Suspicious_PDF_JavaScript
{
    meta:
        description = "PDF con JavaScript embebido y auto-ejecucion al abrirse (OpenAction/AA) -- patron comun de PDFs maliciosos reales."
        severity = "high"
    strings:
        $pdf_magic = "%PDF-"
        $js1 = "/JavaScript" nocase
        $js2 = "/JS" nocase
        $autoexec1 = "/OpenAction" nocase
        $autoexec2 = "/AA" nocase
    condition:
        $pdf_magic at 0 and any of ($js1, $js2) and any of ($autoexec1, $autoexec2)
}

rule Office_Macro_AutoExec
{
    meta:
        description = "Documento de Office (.docx/.xlsx/.pptx, formato ZIP moderno) con macro VBA que se autoejecuta al abrir el archivo."
        severity = "high"
    strings:
        $vba_marker = "vbaProject.bin"
        $autoopen = "AutoOpen" nocase
        $autoexec = "AutoExec" nocase
        $document_open = "Document_Open" nocase
        $workbook_open = "Workbook_Open" nocase
    condition:
        $vba_marker and any of ($autoopen, $autoexec, $document_open, $workbook_open)
}

rule Obfuscated_PowerShell
{
    meta:
        description = "Patrones tipicos de PowerShell ofuscado usado para descargar o ejecutar payloads en memoria sin tocar el disco."
        severity = "high"
    strings:
        $enc1 = "-EncodedCommand" nocase
        $enc2 = "-enc " nocase
        $iex = "IEX(" nocase
        $iex2 = "Invoke-Expression" nocase
        $b64 = "FromBase64String" nocase
        $download = "DownloadString" nocase
    condition:
        2 of them
}

rule Generic_Webshell
{
    meta:
        description = "Patrones de webshell PHP/ASP genericos -- ejecucion de comandos del sistema a partir de parametros HTTP."
        severity = "high"
    strings:
        $php1 = "eval(base64_decode(" nocase
        $php2 = "eval($_POST" nocase
        $php3 = "eval($_GET" nocase
        $php4 = "passthru($_" nocase
        $php5 = "system($_" nocase
        $php6 = "shell_exec($_" nocase
        $asp1 = "eval request(" nocase
        $asp2 = "Execute(Request" nocase
    condition:
        any of them
}

rule Embedded_Windows_Executable
{
    meta:
        description = "Cabecera MZ/PE de un ejecutable de Windows -- cubre el caso de un contenedor (ej. .tar sin comprimir) que trae un .exe adentro sin ser un ejecutable el archivo completo."
        severity = "critical"
        // Limitacion conocida: dentro de un .zip/.7z/.gz comprimidos, los
        // bytes "MZ"/"PE" del ejecutable interno no aparecen literales en
        // el archivo comprimido -- esta regla no los detecta ahi. Un
        // ejecutable que ES el archivo completo subido ya lo bloquea
        // is_content_safe() por su tipo MIME, antes de llegar a este scan.
    strings:
        $mz = { 4D 5A }
        $pe = "PE\x00\x00"
    condition:
        $mz at 0 and $pe in (0..4096)
}
