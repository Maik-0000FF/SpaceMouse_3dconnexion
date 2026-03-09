#!/usr/bin/env python3
"""
Apply SpaceMouse fixes to FreeCAD source.

Works across FreeCAD versions regardless of directory structure or line numbers.
Finds exact code patterns and applies six fixes:

Performance (PR #28110):
  1. Event coalescing in pollSpacenav()
  2. Batched camera updates in processMotionEvent()
  3. Per-axis deadzone with cached Observer in pollSpacenav()

Button fixes (PR #28181):
  4. Button selection sync in DlgCustomizeSpaceball (#17812)
  5. Checkable action invoke in SpaceBall handlers (#10073)

Stability:
  6. spnav disconnect detection in pollSpacenav() (#17809)

Usage:
    python3 apply-spacemouse-fix.py /path/to/freecad-source
    python3 apply-spacemouse-fix.py --check /path/to/freecad-source
"""
import sys
import os

def find_file(base_dir, filename):
    """Find a file anywhere in the source tree."""
    for root, dirs, files in os.walk(base_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None

# ---------------------------------------------------------------------------
# Fix 1: Event coalescing (PR #28110)
# ---------------------------------------------------------------------------
def patch_poll_spacenav(source_dir):
    """Fix 1: Event coalescing in pollSpacenav().

    Before: Every spnav motion event is posted individually via Qt.
    After:  Only the latest motion state is posted once per poll cycle.
    """
    filepath = find_file(source_dir, "GuiNativeEventLinux.cpp")
    if not filepath:
        print("  SKIP: GuiNativeEventLinux.cpp not found (not a Linux build?)")
        return False

    with open(filepath, "r") as f:
        content = f.read()

    if "hasMotion" in content:
        print(f"  OK:   {os.path.relpath(filepath, source_dir)} (already patched)")
        return True

    # Find and replace the postMotionEvent call inside the while loop
    old = "mainApp->postMotionEvent(motionDataArray);\n                break;"
    new = "hasMotion = true;\n                break;"

    if old not in content:
        print(f"  FAIL: Could not find postMotionEvent pattern in {os.path.relpath(filepath, source_dir)}")
        print(f"        The code may have changed in this FreeCAD version.")
        return False

    content = content.replace(old, new, 1)

    # Add 'bool hasMotion = false;' after 'spnav_event ev;'
    content = content.replace(
        "spnav_event ev;\n",
        "spnav_event ev;\n    bool hasMotion = false;\n",
        1
    )

    # Add the if(hasMotion) block after the while loop closes, before the function ends.
    # Use a specific pattern anchored to the button handler to avoid matching
    # the wrong function (e.g. initSpaceball which also ends with "}\n}").
    old_end = (
        "mainApp->postButtonEvent(ev.button.bnum, ev.button.press);\n"
        "                break;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}"
    )
    new_end = (
        "mainApp->postButtonEvent(ev.button.bnum, ev.button.press);\n"
        "                break;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    if (hasMotion) {\n"
        "        mainApp->postMotionEvent(motionDataArray);\n"
        "    }\n"
        "}"
    )

    if old_end not in content:
        print(f"  FAIL: Could not find pollSpacenav end pattern in {os.path.relpath(filepath, source_dir)}")
        print(f"        (looking for postButtonEvent + closing braces)")
        return False

    content = content.replace(old_end, new_end, 1)

    with open(filepath, "w") as f:
        f.write(content)

    print(f"  DONE: {os.path.relpath(filepath, source_dir)} - Event coalescing applied")
    return True

# ---------------------------------------------------------------------------
# Fix 2: Batched camera updates (PR #28110)
# ---------------------------------------------------------------------------
def patch_process_motion_event(source_dir):
    """Fix 2: Batched camera updates in processMotionEvent().

    Before: camera->orientation and camera->position each trigger a separate redraw.
    After:  Notifications suppressed during update, single touch() at the end.
    """
    filepath = find_file(source_dir, "NavigationStyle.cpp")
    if not filepath:
        print(f"  FAIL: NavigationStyle.cpp not found in {source_dir}")
        return False

    with open(filepath, "r") as f:
        content = f.read()

    if "enableNotify(false)" in content:
        print(f"  OK:   {os.path.relpath(filepath, source_dir)} (already patched)")
        return True

    # Pattern: the three lines at the end of processMotionEvent that set camera properties
    # Works with various whitespace/formatting styles
    patterns = [
        # Style 1: spaces around operators (formatted)
        (
            "    camera->orientation.setValue(newRotation);\n"
            "    camera->orientation.getValue().multVec(dir,dir);\n"
            "    camera->position = newPosition + (dir * translationFactor);",

            "    newRotation.multVec(dir,dir);\n"
            "    SbVec3f finalPosition = newPosition + (dir * translationFactor);\n"
            "\n"
            "    // Batch camera property changes into a single Coin3D redraw\n"
            "    camera->enableNotify(false);\n"
            "    camera->orientation.setValue(newRotation);\n"
            "    camera->position = finalPosition;\n"
            "    camera->enableNotify(true);\n"
            "    camera->touch();"
        ),
        # Style 2: with space in multVec(dir, dir)
        (
            "    camera->orientation.setValue(newRotation);\n"
            "    camera->orientation.getValue().multVec(dir, dir);\n"
            "    camera->position = newPosition + (dir * translationFactor);",

            "    newRotation.multVec(dir, dir);\n"
            "    SbVec3f finalPosition = newPosition + (dir * translationFactor);\n"
            "\n"
            "    // Batch camera property changes into a single Coin3D redraw\n"
            "    camera->enableNotify(false);\n"
            "    camera->orientation.setValue(newRotation);\n"
            "    camera->position = finalPosition;\n"
            "    camera->enableNotify(true);\n"
            "    camera->touch();"
        ),
    ]

    for old, new in patterns:
        if old in content:
            content = content.replace(old, new, 1)
            with open(filepath, "w") as f:
                f.write(content)
            print(f"  DONE: {os.path.relpath(filepath, source_dir)} - Batched camera updates applied")
            return True

    print(f"  FAIL: Could not find processMotionEvent camera update pattern in")
    print(f"        {os.path.relpath(filepath, source_dir)}")
    print(f"        The code may have changed in this FreeCAD version.")
    return False

# ---------------------------------------------------------------------------
# Fix 3: Per-axis deadzone (PR #28110)
# ---------------------------------------------------------------------------
def patch_per_axis_deadzone(source_dir):
    """Fix 3: Per-axis deadzone filtering in pollSpacenav().

    Adds a Gui::DeadzoneCache class (member of GuiNativeEvent) that reads
    per-axis deadzone values from user.cfg (BaseApp/Spaceball/Motion) once
    and auto-updates via ParameterGrp::ObserverType when values change.
    Initialized in initSpaceball(), zeroes out axis values below their
    threshold before posting the motion event.
    Applied on top of the event coalescing patch (requires hasMotion block).
    """
    cpp_path = find_file(source_dir, "GuiNativeEventLinux.cpp")
    h_path = find_file(source_dir, "GuiNativeEventLinux.h")
    if not cpp_path:
        print("  SKIP: GuiNativeEventLinux.cpp not found")
        return False
    if not h_path:
        print("  SKIP: GuiNativeEventLinux.h not found")
        return False

    with open(cpp_path, "r") as f:
        cpp = f.read()
    with open(h_path, "r") as f:
        header = f.read()

    if "DeadzoneCache" in cpp:
        print(f"  OK:   {os.path.relpath(cpp_path, source_dir)} (deadzone already patched)")
        return True

    if "hasMotion" not in cpp:
        print(f"  FAIL: Event coalescing patch must be applied first")
        return False

    # --- Patch header: add forward declaration, include, and member ---

    # Add #include <memory> if missing
    if '#include <memory>' not in header:
        header = header.replace(
            '#include "GuiAbstractNativeEvent.h"',
            '#include "GuiAbstractNativeEvent.h"\n#include <memory>',
            1
        )

    # Add forward declaration of DeadzoneCache
    if 'class DeadzoneCache;' not in header:
        header = header.replace(
            'class GUIApplicationNativeEventAware;',
            'class GUIApplicationNativeEventAware;\nclass DeadzoneCache;',
            1
        )

    # Add unique_ptr<DeadzoneCache> member before "private Q_SLOTS:"
    if 'unique_ptr<DeadzoneCache>' not in header:
        header = header.replace(
            'private Q_SLOTS:',
            '    std::unique_ptr<DeadzoneCache> dzCache;\n\nprivate Q_SLOTS:',
            1
        )

    with open(h_path, "w") as f:
        f.write(header)

    # --- Patch cpp: add includes, class definition, init, and usage ---

    # Add required includes
    for inc in ['<array>', '<cmath>', '<cstring>']:
        if f'#include {inc}' not in cpp:
            cpp = cpp.replace(
                '#include <App/Application.h>',
                f'#include {inc}\n#include <App/Application.h>',
                1
            )
    if '#include <App/Application.h>' not in cpp:
        cpp = cpp.replace(
            '#include <FCConfig.h>\n',
            '#include <FCConfig.h>\n#include <array>\n#include <cmath>\n#include <cstring>\n#include <App/Application.h>\n',
            1
        )
    if '#include <Base/Parameter.h>' not in cpp:
        cpp = cpp.replace(
            '#include <Base/Console.h>',
            '#include <Base/Console.h>\n#include <Base/Parameter.h>',
            1
        )

    # Add Gui::DeadzoneCache class definition before the constructor
    deadzone_cache_class = (
        '\n// Cached per-axis deadzone values, auto-updated via Observer when user.cfg changes.\n'
        'class Gui::DeadzoneCache: public ParameterGrp::ObserverType\n'
        '{\n'
        'public:\n'
        '    static constexpr std::array<const char*, 6> keys = {\n'
        '        "PanLRDeadzone",\n'
        '        "PanUDDeadzone",\n'
        '        "ZoomDeadzone",\n'
        '        "TiltDeadzone",\n'
        '        "RollDeadzone",\n'
        '        "SpinDeadzone",\n'
        '    };\n'
        '\n'
        '    std::array<int, 6> values {};\n'
        '\n'
        '    explicit DeadzoneCache(ParameterGrp::handle hGrp)\n'
        '        : hGrp(std::move(hGrp))\n'
        '    {\n'
        '        loadAll();\n'
        '        this->hGrp->Attach(this);\n'
        '    }\n'
        '\n'
        '    ~DeadzoneCache() override\n'
        '    {\n'
        '        hGrp->Detach(this);\n'
        '    }\n'
        '\n'
        '    void OnChange(ParameterGrp::SubjectType& /*rCaller*/,\n'
        '                  ParameterGrp::MessageType reason) override\n'
        '    {\n'
        '        for (size_t i = 0; i < keys.size(); i++) {\n'
        '            if (std::strcmp(reason, keys[i]) == 0) {\n'
        '                values[i] = static_cast<int>(hGrp->GetInt(keys[i], 0));\n'
        '                return;\n'
        '            }\n'
        '        }\n'
        '    }\n'
        '\n'
        'private:\n'
        '    void loadAll()\n'
        '    {\n'
        '        for (size_t i = 0; i < keys.size(); i++) {\n'
        '            values[i] = static_cast<int>(hGrp->GetInt(keys[i], 0));\n'
        '        }\n'
        '    }\n'
        '\n'
        '    ParameterGrp::handle hGrp;\n'
        '};\n'
    )

    constructor_pattern = 'Gui::GuiNativeEvent::GuiNativeEvent('
    if constructor_pattern not in cpp:
        print(f"  FAIL: Could not find GuiNativeEvent constructor in {os.path.relpath(cpp_path, source_dir)}")
        return False

    cpp = cpp.replace(
        constructor_pattern,
        deadzone_cache_class + '\n' + constructor_pattern,
        1
    )

    # Add dzCache initialization in initSpaceball() after the connect() call
    connect_pattern = 'connect(SpacenavNotifier, SIGNAL(activated(int)), this, SLOT(pollSpacenav()));'
    if connect_pattern not in cpp:
        print(f"  FAIL: Could not find connect() pattern in initSpaceball()")
        return False

    dzCache_init = (
        'connect(SpacenavNotifier, SIGNAL(activated(int)), this, SLOT(pollSpacenav()));\n'
        '        dzCache = std::make_unique<DeadzoneCache>(\n'
        '            App::GetApplication().GetParameterGroupByPath(\n'
        '                "User parameter:BaseApp/Spaceball/Motion"\n'
        '            )\n'
        '        );'
    )
    cpp = cpp.replace(connect_pattern, dzCache_init, 1)

    # Replace the simple "if (hasMotion) { postMotionEvent }" block
    old_motion_block = (
        "    if (hasMotion) {\n"
        "        mainApp->postMotionEvent(motionDataArray);\n"
        "    }"
    )
    new_motion_block = (
        '    if (hasMotion) {\n'
        '        // Per-axis deadzone: zero out axes below their individual threshold.\n'
        '        // Values cached and auto-updated via Observer when user.cfg changes.\n'
        '        if (dzCache) {\n'
        '            for (size_t i = 0; i < dzCache->values.size(); i++) {\n'
        '                int dz = dzCache->values[i];\n'
        '                if (dz > 0 && std::abs(motionDataArray[i]) < dz) {\n'
        '                    motionDataArray[i] = 0;\n'
        '                }\n'
        '            }\n'
        '        }\n'
        '        mainApp->postMotionEvent(motionDataArray);\n'
        '    }'
    )

    if old_motion_block not in cpp:
        print(f"  FAIL: Could not find hasMotion block in {os.path.relpath(cpp_path, source_dir)}")
        return False

    cpp = cpp.replace(old_motion_block, new_motion_block, 1)

    with open(cpp_path, "w") as f:
        f.write(cpp)

    print(f"  DONE: {os.path.relpath(cpp_path, source_dir)} + {os.path.relpath(h_path, source_dir)} - Per-axis deadzone with member Observer cache applied")
    return True

# ---------------------------------------------------------------------------
# Fix 4: Button selection sync (#17812)
# ---------------------------------------------------------------------------
def patch_button_select(source_dir):
    """Fix 4: Sync currentIndex with selection in ButtonView::selectButton().

    Before: selectButton() updates the visual selection but not currentIndex(),
            so goChangedCommand() reads the wrong button when user clicks a row.
    After:  setCurrentIndex() is called to keep both in sync.
    Fixes: https://github.com/FreeCAD/FreeCAD/issues/17812
    """
    filepath = find_file(source_dir, "DlgCustomizeSpaceball.cpp")
    if not filepath:
        print("  SKIP: DlgCustomizeSpaceball.cpp not found")
        return False

    with open(filepath, "r") as f:
        content = f.read()

    if "this->setCurrentIndex(idx)" in content:
        print(f"  OK:   {os.path.relpath(filepath, source_dir)} (already patched)")
        return True

    old = (
        "void ButtonView::selectButton(int number)\n"
        "{\n"
        "    this->selectionModel()->select(this->model()->index(number, 0), QItemSelectionModel::ClearAndSelect);\n"
        "    this->scrollTo(this->model()->index(number, 0), QAbstractItemView::EnsureVisible);\n"
        "}"
    )
    new = (
        "void ButtonView::selectButton(int number)\n"
        "{\n"
        "    QModelIndex idx = this->model()->index(number, 0);\n"
        "    this->selectionModel()->select(idx, QItemSelectionModel::ClearAndSelect);\n"
        "    this->setCurrentIndex(idx);\n"
        "    this->scrollTo(idx, QAbstractItemView::EnsureVisible);\n"
        "}"
    )

    if old not in content:
        print(f"  FAIL: Could not find selectButton pattern in {os.path.relpath(filepath, source_dir)}")
        print(f"        The code may have changed in this FreeCAD version.")
        return False

    content = content.replace(old, new, 1)

    with open(filepath, "w") as f:
        f.write(content)

    print(f"  DONE: {os.path.relpath(filepath, source_dir)} - Button selection sync applied")
    return True

# ---------------------------------------------------------------------------
# Fix 5: Checkable action invoke (#10073)
# ---------------------------------------------------------------------------
def patch_button_invoke(source_dir):
    """Fix 5: Use invoke(1) for SpaceBall button commands.

    Before: runCommandByName() calls invoke(0), which never satisfies
            checkable action guards (if iMsg == 1), so commands like
            Std_OrthographicCamera fail silently.
    After:  getCommandByName() + invoke(1) in the two SpaceBall button
            handlers (MainWindow.cpp for Linux/spnav, NavlibCmds.cpp for
            Windows/macOS NavLib).
    Fixes: https://github.com/FreeCAD/FreeCAD/issues/10073
    """
    ok_main = _patch_button_invoke_mainwindow(source_dir)
    ok_navlib = _patch_button_invoke_navlib(source_dir)
    return ok_main and ok_navlib

def _patch_button_invoke_mainwindow(source_dir):
    """Fix 5a: SpaceBall button handler in MainWindow.cpp (Linux/spnav)."""
    filepath = find_file(source_dir, "MainWindow.cpp")
    if not filepath:
        print("  FAIL: MainWindow.cpp not found")
        return False

    with open(filepath, "r") as f:
        content = f.read()

    # Check if already patched
    if "cmd->invoke(1);" in content and "getCommandByName(\n                    commandName" in content:
        print(f"  OK:   {os.path.relpath(filepath, source_dir)} (already patched)")
        return True

    old = (
        '            if (commandName.empty()) {\n'
        '                return true;\n'
        '            }\n'
        '            else {\n'
        '                Application::Instance->commandManager().runCommandByName(commandName.c_str());\n'
        '            }'
    )
    new = (
        '            if (commandName.empty()) {\n'
        '                return true;\n'
        '            }\n'
        '            else {\n'
        '                Command* cmd = Application::Instance->commandManager().getCommandByName(\n'
        '                    commandName.c_str());\n'
        '                if (cmd) {\n'
        '                    cmd->invoke(1);\n'
        '                }\n'
        '            }'
    )

    if old not in content:
        print(f"  FAIL: Could not find SpaceBall button handler pattern in {os.path.relpath(filepath, source_dir)}")
        print(f"        (looking for runCommandByName near commandName.empty())")
        return False

    content = content.replace(old, new, 1)

    with open(filepath, "w") as f:
        f.write(content)

    print(f"  DONE: {os.path.relpath(filepath, source_dir)} - Button invoke(1) applied")
    return True

def _patch_button_invoke_navlib(source_dir):
    """Fix 5b: SpaceBall button handler in NavlibCmds.cpp (Windows/macOS)."""
    filepath = find_file(source_dir, "NavlibCmds.cpp")
    if not filepath:
        print("  SKIP: NavlibCmds.cpp not found (NavLib not available?)")
        return True  # Not a failure — NavLib may not be present

    with open(filepath, "r") as f:
        content = f.read()

    # Check if already patched
    if "cmd->invoke(1);" in content and "getCommandByName(parsedData.commandName" in content:
        print(f"  OK:   {os.path.relpath(filepath, source_dir)} (already patched)")
        return True

    old = (
        '    else\n'
        '        commandManager.runCommandByName(parsedData.commandName.c_str());'
    )
    new = (
        '    else {\n'
        '        Gui::Command* cmd = commandManager.getCommandByName(parsedData.commandName.c_str());\n'
        '        if (cmd) {\n'
        '            cmd->invoke(1);\n'
        '        }\n'
        '    }'
    )

    if old not in content:
        print(f"  FAIL: Could not find NavLib button handler pattern in {os.path.relpath(filepath, source_dir)}")
        print(f"        (looking for commandManager.runCommandByName(parsedData.commandName))")
        return False

    content = content.replace(old, new, 1)

    with open(filepath, "w") as f:
        f.write(content)

    print(f"  DONE: {os.path.relpath(filepath, source_dir)} - Button invoke(1) applied")
    return True

# ---------------------------------------------------------------------------
# Fix 6: spnav disconnect detection (#17809)
# ---------------------------------------------------------------------------
def patch_spnav_disconnect(source_dir):
    """Fix 6: Detect spacenavd disconnection to prevent 100% CPU usage.

    Before: When spacenavd stops, QSocketNotifier fires continuously on
            the dead socket fd (EOF is always "readable"). pollSpacenav()
            spins in a tight loop pegging one CPU core at 100%.
    After:  After an empty poll cycle, recv(MSG_PEEK) checks for EOF.
            On disconnection, the QSocketNotifier is disabled and the
            spnav connection is closed.
    Requires: Fix 1 (event coalescing) must be applied first.
    Fixes: https://github.com/FreeCAD/FreeCAD/issues/17809
    """
    cpp_path = find_file(source_dir, "GuiNativeEventLinux.cpp")
    h_path = find_file(source_dir, "GuiNativeEventLinux.h")
    if not cpp_path:
        print("  SKIP: GuiNativeEventLinux.cpp not found")
        return False
    if not h_path:
        print("  SKIP: GuiNativeEventLinux.h not found")
        return False

    with open(cpp_path, "r") as f:
        cpp = f.read()
    with open(h_path, "r") as f:
        header = f.read()

    if "spnavNotifier" in cpp:
        print(f"  OK:   {os.path.relpath(cpp_path, source_dir)} (disconnect detection already patched)")
        return True

    if "hasMotion" not in cpp:
        print(f"  FAIL: Event coalescing patch (Fix 1) must be applied first")
        return False

    # --- Patch header ---

    # Add QSocketNotifier forward declaration
    if 'class QSocketNotifier;' not in header:
        header = header.replace(
            'class QMainWindow;',
            'class QMainWindow;\nclass QSocketNotifier;',
            1
        )

    # Add spnavNotifier member
    if 'spnavNotifier' not in header:
        # Insert before "private Q_SLOTS:" or after dzCache if present
        if 'std::unique_ptr<DeadzoneCache> dzCache;' in header:
            header = header.replace(
                '    std::unique_ptr<DeadzoneCache> dzCache;',
                '    std::unique_ptr<DeadzoneCache> dzCache;\n'
                '    QSocketNotifier* spnavNotifier {nullptr};',
                1
            )
        else:
            header = header.replace(
                'private Q_SLOTS:',
                '    QSocketNotifier* spnavNotifier {nullptr};\n\n'
                'private Q_SLOTS:',
                1
            )

    with open(h_path, "w") as f:
        f.write(header)

    # --- Patch cpp ---

    # Add includes for recv/errno
    if '#include <cerrno>' not in cpp:
        cpp = cpp.replace(
            '#include <spnav.h>',
            '#include <cerrno>\n#include <sys/socket.h>\n\n#include <spnav.h>',
            1
        )

    # Rename local SpacenavNotifier to member spnavNotifier
    cpp = cpp.replace(
        'QSocketNotifier* SpacenavNotifier\n'
        '            = new QSocketNotifier(spnav_fd(), QSocketNotifier::Read, this);',
        'spnavNotifier = new QSocketNotifier(spnav_fd(), QSocketNotifier::Read, this);',
        1
    )
    # Also rename in connect() call (may have dzCache init after it)
    cpp = cpp.replace('connect(SpacenavNotifier,', 'connect(spnavNotifier,', 1)

    # Update destructor: only close if connection is active
    old_dtor = (
        'Gui::GuiNativeEvent::~GuiNativeEvent()\n'
        '{\n'
        '    if (spnav_close()) {\n'
        '        Base::Console().log("Couldn\'t disconnect from spacenav daemon\\n");\n'
        '    }\n'
        '    else {\n'
        '        Base::Console().log("Disconnected from spacenav daemon\\n");\n'
        '    }\n'
        '}'
    )
    new_dtor = (
        'Gui::GuiNativeEvent::~GuiNativeEvent()\n'
        '{\n'
        '    if (spnavNotifier) {\n'
        '        if (spnav_close()) {\n'
        '            Base::Console().log("Couldn\'t disconnect from spacenav daemon\\n");\n'
        '        }\n'
        '        else {\n'
        '            Base::Console().log("Disconnected from spacenav daemon\\n");\n'
        '        }\n'
        '    }\n'
        '}'
    )

    if old_dtor not in cpp:
        print(f"  FAIL: Could not find destructor pattern in {os.path.relpath(cpp_path, source_dir)}")
        return False

    cpp = cpp.replace(old_dtor, new_dtor, 1)

    # Add 'bool gotEvent = false;' after 'bool hasMotion = false;'
    if 'bool gotEvent = false;' not in cpp:
        cpp = cpp.replace(
            '    bool hasMotion = false;\n',
            '    bool hasMotion = false;\n    bool gotEvent = false;\n\n',
            1
        )

    # Add 'gotEvent = true;' at the top of the while loop body
    cpp = cpp.replace(
        '    while (spnav_poll_event(&ev)) {\n        switch (ev.type) {',
        '    while (spnav_poll_event(&ev)) {\n        gotEvent = true;\n        switch (ev.type) {',
        1
    )

    # Add EOF detection block after the if(hasMotion) block, before the function-closing brace.
    # Anchor to the moc include to ensure we match the right closing brace.
    eof_block = (
        '\n'
        '    if (!gotEvent) {\n'
        '        // QSocketNotifier fired but no events were available.\n'
        '        // Verify the connection is still alive using a non-consuming peek.\n'
        '        int fd = spnav_fd();\n'
        '        if (fd >= 0) {\n'
        '            char buf;\n'
        '            ssize_t ret = recv(fd, &buf, 1, MSG_PEEK | MSG_DONTWAIT);\n'
        '            if (ret == 0 || (ret < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) {\n'
        '                // EOF or socket error — spacenavd disconnected\n'
        '                Base::Console().warning("Lost connection to spacenav daemon\\n");\n'
        '                spnavNotifier->setEnabled(false);\n'
        '                spnav_close();\n'
        '                spnavNotifier = nullptr;\n'
        '            }\n'
        '        }\n'
        '    }\n'
    )

    old_end = (
        '        mainApp->postMotionEvent(motionDataArray);\n'
        '    }\n'
        '}\n'
        '\n'
        '#include "3Dconnexion/moc_GuiNativeEventLinux.cpp"'
    )
    new_end = (
        '        mainApp->postMotionEvent(motionDataArray);\n'
        '    }\n'
        + eof_block +
        '}\n'
        '\n'
        '#include "3Dconnexion/moc_GuiNativeEventLinux.cpp"'
    )

    if old_end not in cpp:
        print(f"  FAIL: Could not find pollSpacenav end pattern for EOF block in {os.path.relpath(cpp_path, source_dir)}")
        return False

    cpp = cpp.replace(old_end, new_end, 1)

    with open(cpp_path, "w") as f:
        f.write(cpp)

    print(f"  DONE: {os.path.relpath(cpp_path, source_dir)} + {os.path.relpath(h_path, source_dir)} - spnav disconnect detection applied")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    check_only = False
    args = [a for a in sys.argv[1:] if a != "--check"]
    if "--check" in sys.argv:
        check_only = True

    if not args:
        print(f"Usage: {sys.argv[0]} [--check] /path/to/freecad-source")
        print()
        print("Applies SpaceMouse fixes to FreeCAD source code:")
        print("  Fixes 1-3: Performance (event coalescing, camera batching, per-axis deadzone)")
        print("  Fixes 4-5: Button fixes (selection sync, checkable action invoke)")
        print("  Fix 6:     Stability (spnav disconnect detection)")
        print()
        print("Use --check to verify if patches can be applied without modifying files.")
        sys.exit(1)

    source_dir = args[0]

    if not os.path.isdir(source_dir):
        print(f"Error: Directory not found: {source_dir}")
        sys.exit(1)

    # Verify this looks like a FreeCAD source tree
    nav_file = find_file(source_dir, "NavigationStyle.cpp")
    spnav_file = find_file(source_dir, "GuiNativeEventLinux.cpp")

    if not nav_file and not spnav_file:
        print(f"Error: This doesn't look like a FreeCAD source directory.")
        print(f"       Could not find NavigationStyle.cpp or GuiNativeEventLinux.cpp")
        sys.exit(1)

    if check_only:
        print("Checking if SpaceMouse fixes can be applied...")
        ok = True

        if spnav_file:
            rel = os.path.relpath(spnav_file, source_dir)
            with open(spnav_file) as f:
                c = f.read()
            # Fix 1: Event coalescing
            if "hasMotion" in c:
                print(f"  OK: {rel} event coalescing already patched")
            elif "mainApp->postMotionEvent(motionDataArray)" in c:
                print(f"  OK: {rel} event coalescing can be patched")
            else:
                print(f"  WARN: {rel} - event coalescing pattern not found")
                ok = False
            # Fix 3: Per-axis deadzone
            if "DeadzoneCache" in c:
                print(f"  OK: {rel} per-axis deadzone already patched")
            elif "hasMotion" in c or "mainApp->postMotionEvent(motionDataArray)" in c:
                print(f"  OK: {rel} per-axis deadzone can be patched")
            else:
                print(f"  WARN: {rel} - per-axis deadzone requires event coalescing first")
                ok = False
            # Fix 6: Disconnect detection
            if "spnavNotifier" in c:
                print(f"  OK: {rel} disconnect detection already patched")
            elif "hasMotion" in c or "mainApp->postMotionEvent(motionDataArray)" in c:
                print(f"  OK: {rel} disconnect detection can be patched")
            else:
                print(f"  WARN: {rel} - disconnect detection requires event coalescing first")
                ok = False

        if nav_file:
            rel = os.path.relpath(nav_file, source_dir)
            with open(nav_file) as f:
                c = f.read()
            # Fix 2: Batched camera updates
            if "enableNotify(false)" in c:
                print(f"  OK: {rel} batched camera updates already patched")
            elif "camera->orientation.setValue(newRotation)" in c and "camera->orientation.getValue().multVec(dir" in c:
                print(f"  OK: {rel} batched camera updates can be patched")
            else:
                print(f"  WARN: {rel} - batched camera updates pattern not found")
                ok = False

        # Fix 4: Button select
        btn_file = find_file(source_dir, "DlgCustomizeSpaceball.cpp")
        if btn_file:
            rel = os.path.relpath(btn_file, source_dir)
            with open(btn_file) as f:
                c = f.read()
            if "this->setCurrentIndex(idx)" in c:
                print(f"  OK: {rel} button selection sync already patched")
            elif "void ButtonView::selectButton" in c:
                print(f"  OK: {rel} button selection sync can be patched")
            else:
                print(f"  WARN: {rel} - selectButton pattern not found")
                ok = False

        # Fix 5: Button invoke
        mw_file = find_file(source_dir, "MainWindow.cpp")
        if mw_file:
            rel = os.path.relpath(mw_file, source_dir)
            with open(mw_file) as f:
                c = f.read()
            if "cmd->invoke(1);" in c and "getCommandByName" in c:
                print(f"  OK: {rel} button invoke already patched")
            elif "runCommandByName(commandName.c_str())" in c:
                print(f"  OK: {rel} button invoke can be patched")
            else:
                print(f"  WARN: {rel} - button invoke pattern not found")
                ok = False

        nl_file = find_file(source_dir, "NavlibCmds.cpp")
        if nl_file:
            rel = os.path.relpath(nl_file, source_dir)
            with open(nl_file) as f:
                c = f.read()
            if "cmd->invoke(1);" in c and "getCommandByName(parsedData" in c:
                print(f"  OK: {rel} NavLib button invoke already patched")
            elif "runCommandByName(parsedData.commandName.c_str())" in c:
                print(f"  OK: {rel} NavLib button invoke can be patched")
            else:
                print(f"  WARN: {rel} - NavLib button invoke pattern not found")
                ok = False

        sys.exit(0 if ok else 1)

    print("Applying SpaceMouse fixes...")
    print()

    print("--- Performance (PR #28110) ---")
    ok1 = patch_poll_spacenav(source_dir)
    ok2 = patch_process_motion_event(source_dir)
    ok3 = patch_per_axis_deadzone(source_dir)

    print()
    print("--- Button fixes (PR #28181) ---")
    ok4 = patch_button_select(source_dir)
    ok5 = patch_button_invoke(source_dir)

    print()
    print("--- Stability (#17809) ---")
    ok6 = patch_spnav_disconnect(source_dir)

    print()
    results = [ok1, ok2, ok3, ok4, ok5, ok6]
    if all(results):
        print("All patches applied successfully.")
        sys.exit(0)
    else:
        print("Some patches failed. See errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
