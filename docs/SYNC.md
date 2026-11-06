# Política de sincronización podofilo_dev → podofilo_v2_core

> `podofilo_dev` es el **programa principal** (activa, con la extensión OVE
> privada, versionado ~`1.0.5`). `podofilo_v2_core` es la versión
> **pública open-core** sin la extensión, publicada como releases en este
> repositorio: `https://github.com/joseska/podofilo_v2_core/releases`.
>
> Sincronizar = llevar al core las mejoras de dev **sin** el código OVE.

## Resumen del modelo open-core

- `src/core/extension_loader.py` intenta importar `src/extensions/ove/*` y,
  si no existe, devuelve `None` (la app corre en modo *Open Core*).
- Todo punto de contacto de la UI con la extensión está guardado con
  `if self.extensions:` / `if self.shipment_manager:`. Por eso **copiar el
  `src/` completo de dev funciona sin OVE**.
- El `.gitignore` de este repo excluye `src/extensions/ove/` (privado); los
  tests del core son públicos.

## Qué se copia "tal cual" (wholesale) en cada sync

| Fichero / carpeta | Acción |
|---|---|
| `src/**` | Copia espejo (`robocopy /MIR`) **excluyendo** `src\extensions\ove` |
| `main.py` | Copiar tal cual (trae `--version`, `--debug`, check de updates, protocolo extendido de instancia única) |
| `src/core/single_instance.py` | SIEMPRE junto a `main.py` (protocolo: payload dict `{files, actions, debug}` — cambiar uno sin el otro lo rompe) |
| `tests/**` | Copiar tal cual, **excluyendo** `test_ove_payload_classification.py` (es OVE) |
| `resources/**` | Copiar tal cual (nuevos iconos, tema) |

## Qué se mantiene DIFERENTE entre repos (no copiar a ciegas)

| Fichero | En dev | En core |
|---|---|---|
| `requirements.txt` | incluye deps OVE activas | solo deps core (`httpx` para el updater) + comentario apuntando a `requirements_ove.txt` |
| `PodofiloV2.spec` | hiddenimports de playwright/greenlet/keyring/pypac/lxml + datas del driver de Playwright + empaqueta OVE si está | sin nada de OVE; SIEMPRE: `httpx` en hiddenimports y `VERSION.txt` en datas |
| `Instalador/podofiloV2.iss` | `MyAppName PodofiloV2`, AppId del build OVE | `MyAppName PodofiloV2Core`, AppId propio `{{C4F0A2E7-52B8-4A1F-9D63-83A7B5E2D901}` |
| `VERSION.txt` | línea de versiones de dev | línea de versiones del core (semver, empezó en `1.0.0`) |
| `src/core/updater.py` | `GITHUB_REPO = "PodofiloV2-releases"` | `GITHUB_REPO = "podofilo_v2_core"` |
| `.gitignore` | — | excluye `src/extensions/ove/` y `V1/`; **no** excluye `tests/` |
| `environment.yml`, `setup_conda.ps1` | env `podofilo_v2` | env `podofilo_v2_core` (solo deps core en pip) |
| `README.md`, `QUICKSTART.md`, este fichero | referenciado OVE como feature | explica modo open-core, releases y extensiones opcionales |

## Checklist de sincronización (procedimiento)

1. En `podofilo_v2_core`, crear rama `sync-dev-<fecha>` y commit snapshot del estado actual.
2. Copiar `src/**` (con `robocopy /MIR` excluyendo `src\extensions\ove`), `main.py`, `tests/**` (menos el test OVE).
   - Borrar después `tests/test_ove_payload_classification.py` si robocopy lo arrastró.
   - Borrar `__pycache__` arrastrados.
3. Si cambió el updater en dev, **re-aplicar** `GITHUB_OWNER/GITHUB_REPO` del core y re-verificar:
   - `GITHUB_REPO = "podofilo_v2_core"` (releases de este repo).
   - Nombres de assets fijos: `PodofiloV2_Setup.exe` + `PodofiloV2_Setup.exe.sha256`.
4. Re-asegurar las diferencias de la tabla anterior: `requirements.txt`, `PodofiloV2.spec`, `Instalador/podofiloV2.iss`, `environment.yml`, `setup_conda.ps1`, `.gitignore`.
5. Verificar imports: solo `extension_loader.py` y el `try/except` de `ShipmentState` en `main_window` pueden importar `src.extensions.ove`.
6. `python -m unittest discover -s tests -v` en el env del core.
7. `python main.py --version` (imprime la versión de `VERSION.txt`) y arranque normal con el log
   `"Extension OVE not found. Running in Open Core mode."`.
8. Build: `build_exe_y_compilar.bat` (fases PyInstaller → copia a Instalador → ISCC con `/DMyAppVersion` desde `VERSION.txt` → `certutil` SHA256). Confirmar que el build NO arrastra `playwright/`, `keyring/`, `pypac/`, `lxml/`, `greenlet/`, `dukpy/`.
9. Merge a `main`, tag `v<X.Y.Z>` igual a `VERSION.txt` y crear la **release de GitHub** con los dos assets (`PodofiloV2_Setup.exe` + `.sha256`).
10. Forzar el check manual de actualizaciones desde Configuración para validar el flujo updater.

## Probar localmente con la extensión OVE (opcional, privado)

```
pip install -r requirements_ove.txt
xcopy /E /I "<ruta>\podofilo_dev\src\extensions\ove" src\extensions\ove
python main.py
```
La carpeta copiada queda ignorada por git (no se filtra al repo público).

## Limitaciones conocidas

- **Puerto de instancia única compartido (13013)**: si tienes abierta la build
  con OVE (dev) y la build core a la vez, solo una poseerá el puerto; la otra
  enviará sus archivos a la primera. Abrirlas una a una o cambiar el puerto
  del core (mejora pendiente).
- `~/podofilo/config_v2.json` es compartida por ambas builds: los ajustes se
  sobrescriben entre sí. Documentado; no bloquea el uso normal.
- El instador del core (`PodofiloV2Core`) y el de dev (`PodofiloV2`) pueden
  estar instalados a la vez (AppId distinto), pero comparten los archivos
  temporales (`%TEMP%\PodofiloV2_update` del updater es común).
