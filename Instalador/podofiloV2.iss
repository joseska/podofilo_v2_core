#define MyAppName "PodofiloV2Core"
#define MyAppPublisher "Joseska"
#define MyAppExeName "PodofiloV2.exe"

; Versión de la app definida por el build script (build_exe_y_compilar.bat)
; mediante:  iscc /DMyAppVersion=1.0.0  podofiloV2.iss
; El bat lee el contenido de VERSION.txt (raíz del repo) y lo pasa a ISCC.
; Si se compila el .iss directamente sin /D, cae en el fallback "V2_unknown".
#ifndef MyAppVersion
  #define MyAppVersion "V2_unknown"
#endif




[Setup]

; ============================================================
; INFORMACIÓN DE LA APLICACIÓN
; ============================================================

; AppId DISTINTO del de la build con OVE (Instalador/podofiloV2.iss de
; podofilo_dev) para que el instalador del core y el de la build OVE
; puedan coexistir instalados en la misma máquina.
AppId={{C4F0A2E7-52B8-4A1F-9D63-83A7B5E2D901}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

; Instalación solamente para el usuario actual.
; No requiere permisos de administrador.
PrivilegesRequired=lowest

; ============================================================
; CARPETA DE INSTALACIÓN
; ============================================================

DefaultDirName={localappdata}\{#MyAppName}

; No mostrar pantalla para elegir carpeta
DisableDirPage=yes

; ============================================================
; MENÚ INICIO
; ============================================================

DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; ============================================================
; INSTALADOR
; ============================================================

WizardStyle=modern

; Ocultar pantallas innecesarias
DisableWelcomePage=yes
DisableStartupPrompt=yes

; No mostrar página de "Listo para instalar".
; El icono del escritorio se crea siempre, sin preguntar.
DisableReadyPage=yes

; No mostrar página final
; El instalador simplemente termina.
DisableFinishedPage=yes

; ============================================================
; COMPRESIÓN
; ============================================================

Compression=lzma
SolidCompression=yes

; ============================================================
; SALIDA
; ============================================================

OutputDir=installer
OutputBaseFilename=PodofiloV2_Setup

; ============================================================
; DESINSTALACIÓN
; ============================================================

Uninstallable=yes
UninstallDisplayName={#MyAppName}

; Cerrar forzosamente cualquier instancia en marcha de PodofiloV2Core que
; pudiera quedar bloqueada tras el cierre abrupto (os._exit) del updater.
CloseApplications=force
RestartApplications=no


[Files]

; Ejecutable principal
Source: "PodofiloV2.exe"; \
    DestDir: "{app}"; \
    Flags: ignoreversion

; Carpeta completa _internal
Source: "_internal\*"; \
    DestDir: "{app}\_internal"; \
    Flags: ignoreversion recursesubdirs createallsubdirs


[Icons]

; Acceso directo en el menú Inicio del usuario
Name: "{userprograms}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"

; Acceso directo en el escritorio del usuario.
Name: "{userdesktop}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"


[Run]

; Tras instalar (silencioso o no), reabrir PodofiloV2 automáticamente.
; nowait: el instalador no espera a que la app termine (no bloquea).
; postinstall: en modo interactivo muestra opción "Iniciar PodofiloV2".
;
; IMPORTANTE: NO usamos `skipifsilent`.  El updater lanza el setup con
; `/SILENT` (muestra barra de progreso); con `skipifsilent` el relanzamiento
; se saltaría y la app no se reabriría. Sin esa flag, la entrada [Run] se
; ejecuta tanto en modo silencioso como interactivo -> la nueva versión
; se abre sola al terminar la instalación.
Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; \
    Flags: nowait postinstall


[UninstallDelete]

; Al desinstalar, eliminar absolutamente toda
; la carpeta de PodofiloV2.
Type: filesandordirs; Name: "{app}"


[Code]

function IsPodofiloRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;

  Exec(
    ExpandConstant('{cmd}'),
    '/C tasklist /FI "IMAGENAME eq PodofiloV2.exe" /NH | find /I "PodofiloV2.exe"',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );

  if ResultCode = 0 then
    Result := True;
end;


function InitializeSetup(): Boolean;
begin
  Result := True;

  { Comprobar si PodofiloV2 (el ejecutable que hay en esta carpeta de
    instalación, core u OVE según cuál se instale) está abierto }
  if IsPodofiloRunning() then
  begin
    MsgBox(
      'PodofiloV2 está actualmente en ejecución.' + #13#10 + #13#10 +
      'Cierra PodofiloV2 antes de instalar o actualizar la aplicación.',
      mbError,
      MB_OK
    );

    Result := False;
  end;
end;


procedure CurStepChanged(CurStep: TSetupStep);
begin

  { Antes de instalar los archivos nuevos,
    eliminar completamente la instalación anterior. }

  if CurStep = ssInstall then
  begin

    if DirExists(ExpandConstant('{app}')) then
    begin
      DelTree(
        ExpandConstant('{app}'),
        True,
        True,
        True
      );
    end;

  end;

end;
