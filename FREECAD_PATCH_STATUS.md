# FreeCAD SpaceMouse Patch — Entwicklungsstand

## Status: NICHT FUNKTIONSFÄHIG (Stand 2026-02-08)

Die SpaceMouse-Navigation in FreeCAD auf Linux funktioniert noch nicht zufriedenstellend.
Rotation um Objektmittelpunkt, Sensitivity-Kontrolle und Smoothing sind ungelöst.

## Kernproblem

- **Windows/macOS**: FreeCAD nutzt 3Dconnexion **NavLib SDK** — professionelles Smoothing, Object-Center-Rotation, Velocity-Curves, Pivot-Visualisierung
- **Linux**: FreeCAD nutzt **Legacy spacenavd** mit `processMotionEvent()` in `NavigationStyle.cpp` — rohe Werte direkt auf Kamera, kein Smoothing, kein Pivot, kein Deadzone
- **NavLib ist für Linux in CMake blockiert** (`FREECAD_3DCONNEXION_SUPPORT` nur Windows/macOS)
- **Issue #9543 ist seit 2,5 Jahren OFFEN** — kein Fix für das Rotationszentrum gemerged
- **FreeCADs Linux SpaceMouse-Code (`GuiNativeEventLinux.cpp`) ist seit 2018 unverändert**

## Getestete Ansätze (alle gescheitert)

### 1. user.cfg Konfiguration (funktioniert teilweise)
- `LegacySpaceMouseDevices = 1` ← muss AN sein, sonst kein SpaceMouse-Input
- `NavigationStyle = Gui::BlenderNavigationStyle`, `OrbitStyle = 1` (Trackball)
- `RotationMode = 2` — hat keinen Effekt auf Spaceball-Events (Issue #9543)
- `FlipYZ = 1`, alle Achsen enabled, Buttons konfiguriert
- **Ergebnis**: SpaceMouse Input funktioniert, aber Navigation sprunghaft, kein Objektzentrum

### 2. Shell-Script `scripts/freecad-spacemouse-patch.sh` (funktioniert)
- Patcht user.cfg automatisch inkl. Button-Mappings
- Backup + Restore (`--restore`), idempotent

### 3. Focal-Distance-Fix per QTimer (nicht ausreichend)
- **Idee**: `camera.focalDistance` kontinuierlich auf BoundingBox-Center setzen
- `processMotionEvent()` nutzt `focalDistance` als Rotationspivot
- **Problem**: Timer ist asynchron zu SpaceMouse-Events → stale focalDistance
  zwischen Updates, Rotation "wobbelt", Translation-Feedback-Loop → Fly-Away
- Getestete Timer-Raten: 50ms (20fps), 16ms (60fps) — kein spürbarer Unterschied

### 4. SoMotion3Event Interception per SoEventCallback (aktueller Stand)
- **Idee**: Coin3D SoEventCallback fängt SoMotion3Event im Scenegraph ab,
  `event_cb.setHandled()` verhindert dass FreeCADs processMotionEvent läuft,
  eigene Kamera-Steuerung mit Rotation um Szenen-/Selektionsmittelpunkt
- **Implementiert**: Rotation um Pivot, Deadzone, Smoothing, Dominant-Mode,
  Pan in Kameraebene, Zoom mit absolutem Clamp
- **Problem**: Kamera-Distanz konvergiert gegen Null beim Drehen.
  Eventuell sind die SoMotion3Event-Werte (getTranslation/getRotation) anders
  skaliert als erwartet. Debug-Logging ist eingebaut aber noch nicht ausgewertet.
- **Offene Frage**: Werden SoMotion3Events überhaupt durch den Scenegraph
  dispatched? Oder verarbeitet FreeCAD sie auf Qt-Ebene bevor Quarter
  sie in Coin3D-Events konvertiert?

### 5. Eigene spnav-Verbindung (GESCHEITERT — Sackgasse)
- `spnav_open() = -1` innerhalb FreeCAD — libspnav erlaubt nur EINE Verbindung
  pro Prozess, FreeCAD hält sie bereits

## Offene Probleme

1. **Rotation nicht um Objektmittelpunkt** — Kernproblem, bisher kein Fix funktioniert
2. **Navigation sprunghaft/hakelig** — kein Smoothing, kein Velocity-Curve
3. **Kamera fliegt weg** (Focal-Distance-Ansatz) oder **Distanz geht auf Null**
   (Event-Interception-Ansatz)
4. **Buttons** — unklar ob FreeCADs native Handler oder unser Coin3D-Callback funktioniert
5. **Werteskalierung** — die genauen Wertebereiche von SoMotion3Event.getTranslation()
   und getRotation() in FreeCADs Kontext sind nicht dokumentiert

## Nächste Schritte

1. **Debug-Output auswerten**: Das aktuelle Addon loggt Roh-Werte alle 60 Frames
   in die Report-View. Diese Werte müssen analysiert werden um die Skalierung
   und Achszuordnung zu verstehen.
2. **MCP für FreeCAD**: Es gibt MCP-Server für FreeCAD
   (z.B. neka-nat/freecad-mcp, bonninr/freecad_mcp) die direkten Python-Zugriff
   auf FreeCADs Laufzeitumgebung ermöglichen → ermöglicht Live-Debugging
3. **SoFieldSensor statt Timer**: Sensor auf camera.position/orientation
   der synchron nach jedem processMotionEvent feuert
4. **processMotionEvent C++ patchen**: Als letzter Ausweg direkt FreeCADs
   C++ Code patchen und eigenes Build erstellen

## Installierte Dateien

```
~/.local/share/FreeCAD/Mod/SpaceNavFix/    # Auto-Loading Addon
  __init__.py
  InitGui.py          # QTimer-basierter Auto-Starter (pollt alle 2s auf 3D View)
  freecad_spacenav.py # SoMotion3Event Interceptor (aktueller Ansatz)

~/.local/share/FreeCAD/Macro/
  freecad_spacenav.py # Standalone-Version (exec() in Konsole)
```

## Repo-Dateien

```
freecad-addon/SpaceNavFix/       # Addon-Quellcode (identisch mit installierter Version)
scripts/
  freecad-spacemouse-patch.sh    # user.cfg Patcher
  freecad-spacemouse-setup.FCMacro
  freecad_spacenav.py            # Standalone-Version
```

## Konfiguration

### user.cfg (aktuell gesetzt)
- LegacySpaceMouseDevices = 1
- NavigationStyle = Gui::BlenderNavigationStyle
- OrbitStyle = 1 (Trackball), RotationMode = 2
- FlipYZ = 1, alle 6 Achsen enabled
- GlobalSensitivity = -15
- Buttons: 0=Std_ViewFitAll, 1=Std_ViewHome

### spacemouse-desktop Daemon (config.json)
- FreeCAD-Profil: alle Achsen + Buttons = "none" (kein Doppel-Input)

### spnavrc
- sensitivity=1.5, dead-zone=5

## System-Umgebung
- Arch Linux, KDE Plasma (Wayland), Kernel 6.18.7-arch1-1
- FreeCAD 1.0.2 (1.1 hat Regressionen bei SpaceMouse — Issue #27132)
- Python 3.14, PySide6 6.10.2
- spacenavd (AUR), libspnav
- Hardware: 3Dconnexion SpaceNavigator (046d:c626)

## Quellen
- FreeCAD `processMotionEvent()` in NavigationStyle.cpp
- FreeCAD `GuiNativeEventLinux.cpp` — negiert alle Achsen, kein Pivot
- FreeCAD `NavlibPivot.cpp` — Pivot nur für Win/Mac
- Issue #9543: SpaceMouse Rotation Center (OFFEN seit Mai 2023)
- Issue #27132: SpaceMouse broken in FreeCAD 1.1/1.2
- Discussion #25449: Driverless HID Support (Vorschlag ohne Resonanz)
- PR #12929: NavLib Integration (Windows/macOS only)
- PR #18244: Runtime-Auswahl Legacy/NavLib
- MCP-Server: neka-nat/freecad-mcp, bonninr/freecad_mcp
