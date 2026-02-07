# FreeCAD SpaceMouse Patch — Entwicklungsstand

## Ziel
SpaceMouse soll in FreeCAD smooth Viewport-Navigation machen (Orbit, Pan, Zoom)
wie auf Windows/macOS — nicht sprunghaft und mit korrektem Rotationszentrum (wie bei Maus-Navigation).

## Kernproblem
- **Windows/macOS**: FreeCAD nutzt 3Dconnexion **NavLib SDK** — professionelles Smoothing, Object-Center-Rotation, Velocity-Curves
- **Linux**: FreeCAD nutzt **Legacy spacenavd** mit 31 Zeilen `processMotionEvent()` in `NavigationStyle.cpp` — rohe Werte direkt auf Kamera, kein Smoothing, Rotation um Viewport-Mitte
- **NavLib ist für Linux in CMake blockiert** (`FREECAD_3DCONNEXION_SUPPORT` nur Windows/macOS)

## Was bereits getestet wurde

### 1. user.cfg Konfiguration (funktioniert, reicht aber nicht)
- `LegacySpaceMouseDevices = 1` ← muss AN sein, sonst kein SpaceMouse-Input
- `NavigationStyle = Gui::BlenderNavigationStyle`
- `OrbitStyle = 1` (Trackball)
- `RotationMode = 2` (Object center — hat aber keinen Effekt auf Spaceball-Events! Issue #9543)
- `FlipYZ = 1` (Push/Pull = Zoom)
- Alle Achsen enabled (PanLR, PanUD, Zoom, Tilt, Roll, Spin)
- `GlobalSensitivity = -15` (dämpft die hohe spnavrc)
- Spaceball/Buttons: 0=Std_ViewFitAll, 1=Std_ViewHome
- **Ergebnis**: Navigation immer noch sprunghaft, Rotation nicht um Objekt

### 2. Shell-Script `scripts/freecad-spacemouse-patch.sh` (funktioniert)
- Patcht user.cfg automatisch via Python XML-Manipulation
- Findet richtige XML-Hierarchie: `FCParameters > Root > BaseApp > ...`
- Backup + Restore (`--restore`)
- Idempotent (kann mehrfach ausgeführt werden)
- **Bug v1 behoben**: Erste Version erzeugte doppelten `<BaseApp>` Block

### 3. FreeCAD Macro `scripts/freecad-spacemouse-setup.FCMacro` (erstellt, nicht getestet)
- Setzt dieselben Settings via `FreeCAD.ParamGet()`
- Nutzt korrekten Parameter-Namen `LegacySpaceMouseDevices` (nicht `LegacySpaceMouse`)

### 4. Python-Addon Ansatz 1: Eigene spnav-Verbindung (GESCHEITERT)
Datei: `scripts/freecad_spacenav.py` + `~/.local/share/FreeCAD/Mod/SpaceNav/`

**Idee**: LegacySpaceMouseDevices=0, eigene libspnav-Verbindung, eigene Kamera-Steuerung

**Probleme durchlaufen**:
- ❌ `PySide2` Import → FreeCAD 1.0.2 nutzt **PySide6** (gefixt mit try/except)
- ❌ `from SpaceNav import freecad_spacenav` → FreeCAD Mod-System anders (gefixt)
- ❌ `__file__` nicht definiert in InitGui.py → FreeCAD setzt das nicht (gefixt)
- ❌ `exec()` ohne globals → ctypes nicht im Scope (gefixt mit globals dict)
- ❌ `_script` Variable nicht im QTimer-Callback-Scope (gefixt mit Closure)
- ❌ **spnav_open() = -1 innerhalb FreeCAD** ← SHOWSTOPPER
  - Von externem Python: `spnav_open()` gibt 0 zurück (funktioniert)
  - Innerhalb FreeCAD: gibt -1 zurück
  - **Ursache**: libspnav erlaubt NUR EINE Verbindung pro Prozess.
    FreeCAD öffnet die Verbindung bereits bei Start (auch mit LegacySpaceMouseDevices=0!
    PR #19226 "Disable legacy spnav code when legacy is false" ist vermutlich
    nicht in FreeCAD 1.0.2 enthalten).
  - Eigene spnav-Verbindung ist damit UNMÖGLICH innerhalb von FreeCAD.

### 5. Python-Addon Ansatz 2: reorientCamera-Logik (Code geschrieben, nicht getestet)
- `_reorient_camera()` = 1:1 Python-Port von FreeCADs C++ `NavigationStyle::reorientCamera()`
- Rotation um **Camera Focal Point** (= exakt wie Maus-Navigation)
- Smoothing, Dead Zone, Velocity Curve eingebaut
- **Konnte nicht getestet werden** wegen spnav_open() Problem

## Nächster Ansatz: Event-Filter (NOCH NICHT IMPLEMENTIERT)

### Idee
FreeCAD empfängt bereits SpaceMouse-Events über seine eigene spnav-Verbindung.
Diese Events werden als Qt-Events (`Spaceball::MotionEvent`, Type ~QEvent::User+1)
durch `GuiApplicationNativeEventAware` gepostet und landen bei `MainWindow::event()`,
das sie an `View3DInventorViewer` weiterleitet, der `processMotionEvent()` aufruft.

**Plan**:
1. `LegacySpaceMouseDevices = 1` (FreeCAD hält spnav-Verbindung)
2. QEventFilter auf FreeCADs MainWindow installieren
3. Spaceball::MotionEvent abfangen (6 Achswerte auslesen)
4. Event NICHT an FreeCADs Default-Handler weiterleiten (return True)
5. Stattdessen eigene Kamera-Manipulation mit:
   - `_reorient_camera()` (schon geschrieben)
   - Smoothing + Velocity Curve (schon geschrieben)
   - `_pan_camera()` und `_zoom_camera()` (schon geschrieben)

### Offene Fragen
- Wie ist der Qt Event Type für Spaceball::MotionEvent? (custom QEvent subclass)
- Wie liest man die 6 Achswerte aus dem Event in Python?
- FreeCAD definiert diese in `SpaceballEvent.h` — sind die per Python/PySide6 zugreifbar?
- Alternative: `coin.SoMotion3Event` über SoEventCallback im Scenegraph abfangen

### Alternative: SoEventCallback
Statt Qt Event-Filter könnte man einen **Coin3D SoEventCallback** Node
im Scenegraph registrieren der `SoMotion3Event` abfängt:
```python
cb = coin.SoEventCallback()
cb.addEventCallback(coin.SoMotion3Event.getClassTypeId(), my_handler)
view.getSceneGraph().insertChild(cb, 0)  # Vor allem anderen
```
Das könnte einfacher sein weil `SoMotion3Event` die Achswerte direkt enthält
(`getTranslation()`, `getRotation()`).

## Dateien im Repo

```
scripts/
  freecad-spacemouse-patch.sh    # user.cfg Patcher (funktioniert)
  freecad-spacemouse-setup.FCMacro  # FreeCAD Macro (erstellt)
  freecad_spacenav.py            # Python Addon (reorientCamera-Logik, braucht Event-Quelle)

~/.local/share/FreeCAD/Mod/SpaceNav/
  InitGui.py                     # Auto-Loader (funktioniert nach Fixes)
  freecad_spacenav.py            # Kopie des Addons
  __init__.py                    # Package marker
```

## System-Umgebung
- Arch Linux, KDE Plasma (Wayland), Kernel 6.18.7-arch1-1
- FreeCAD 1.0.2
- Python 3.14, PySide6 6.10.2
- spacenavd (AUR), libspnav
- Hardware: 3Dconnexion SpaceNavigator (046d:c626)
- spnavrc: sensitivity=1.5, dead-zone=5

## Quellen
- FreeCAD `NavigationStyle::reorientCamera()`: Rotation um Focal Point, Position nachführen
- FreeCAD `NavigationStyle::panCamera()`: Projektion auf Kamera-Ebene
- PR #12929: NavLib Integration (Windows/macOS only)
- PR #17000: NavLib macOS
- PR #18098: Spaceball Events im Placement Dialog (eventFilter Beispiel)
- PR #19226: Disable legacy spnav when unchecked
- Issue #9543: SpaceMouse Rotation Center
- Issue #12644: Default Axis Mapping mismatch
- `processMotionEvent()` in NavigationStyle.cpp: 31 Zeilen, kein Smoothing
