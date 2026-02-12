#!/usr/bin/env python3
"""
Apply SpaceMouse smooth navigation fix to FreeCAD source.

Works across FreeCAD versions regardless of directory structure or line numbers.
Finds the exact code patterns and applies the two fixes:
  1. Event coalescing in pollSpacenav()
  2. Batched camera updates in processMotionEvent()

Usage:
    python3 apply-spacemouse-fix.py /path/to/freecad-source
    python3 apply-spacemouse-fix.py --check /path/to/freecad-source
"""
import sys
import os
import glob

def find_file(base_dir, filename):
    """Find a file anywhere in the source tree."""
    for root, dirs, files in os.walk(base_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None

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

def patch_per_axis_deadzone(source_dir):
    """Fix 3: Per-axis deadzone filtering in pollSpacenav().

    Reads per-axis deadzone values from FreeCAD user.cfg (BaseApp/Spaceball/Motion)
    and zeroes out axis values below their threshold before posting the motion event.
    Applied on top of the event coalescing patch (requires hasMotion block).
    """
    filepath = find_file(source_dir, "GuiNativeEventLinux.cpp")
    if not filepath:
        print("  SKIP: GuiNativeEventLinux.cpp not found")
        return False

    with open(filepath, "r") as f:
        content = f.read()

    if "axisDeadzone" in content:
        print(f"  OK:   {os.path.relpath(filepath, source_dir)} (deadzone already patched)")
        return True

    if "hasMotion" not in content:
        print(f"  FAIL: Event coalescing patch must be applied first")
        return False

    # Add #include for ParameterGrp (FreeCAD's config API) at top of file
    # Find the last #include line and add after it
    include_line = '#include "GuiNativeEvent.h"'
    if include_line not in content:
        # Try alternative include pattern
        include_line = '#include <App/Application.h>'
    if include_line in content:
        if '#include <App/Application.h>' not in content:
            content = content.replace(
                include_line,
                include_line + '\n#include <App/Application.h>',
                1
            )
    else:
        # Fallback: add after first include
        first_include = content.find('#include')
        eol = content.find('\n', first_include)
        content = content[:eol+1] + '#include <App/Application.h>\n' + content[eol+1:]

    # Replace the simple "if (hasMotion) { postMotionEvent }" block with
    # one that reads deadzone values and filters axes before posting
    old_motion_block = (
        "    if (hasMotion) {\n"
        "        mainApp->postMotionEvent(motionDataArray);\n"
        "    }"
    )
    new_motion_block = (
        '    if (hasMotion) {\n'
        '        // Per-axis deadzone filtering (reads from user.cfg)\n'
        '        static const char *axisDeadzoneKeys[] = {\n'
        '            "PanLRDeadzone", "PanUDDeadzone", "ZoomDeadzone",\n'
        '            "TiltDeadzone", "RollDeadzone", "SpinDeadzone"\n'
        '        };\n'
        '        auto hGrp = App::GetApplication().GetParameterGroupByPath(\n'
        '            "User parameter:BaseApp/Spaceball/Motion");\n'
        '        for (int i = 0; i < 6; i++) {\n'
        '            int dz = (int)hGrp->GetInt(axisDeadzoneKeys[i], 0);\n'
        '            if (dz > 0 && motionDataArray[i] > -dz && motionDataArray[i] < dz) {\n'
        '                motionDataArray[i] = 0;\n'
        '            }\n'
        '        }\n'
        '        mainApp->postMotionEvent(motionDataArray);\n'
        '    }'
    )

    if old_motion_block not in content:
        print(f"  FAIL: Could not find hasMotion block in {os.path.relpath(filepath, source_dir)}")
        return False

    content = content.replace(old_motion_block, new_motion_block, 1)

    with open(filepath, "w") as f:
        f.write(content)

    print(f"  DONE: {os.path.relpath(filepath, source_dir)} - Per-axis deadzone applied")
    return True


def main():
    check_only = False
    args = [a for a in sys.argv[1:] if a != "--check"]
    if "--check" in sys.argv:
        check_only = True

    if not args:
        print(f"Usage: {sys.argv[0]} [--check] /path/to/freecad-source")
        print()
        print("Applies SpaceMouse smooth navigation fix to FreeCAD source code.")
        print("Use --check to verify if the patch can be applied without modifying files.")
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
        print("Checking if SpaceMouse fix can be applied...")
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
            if "axisDeadzone" in c:
                print(f"  OK: {rel} per-axis deadzone already patched")
            elif "hasMotion" in c or "mainApp->postMotionEvent(motionDataArray)" in c:
                print(f"  OK: {rel} per-axis deadzone can be patched")
            else:
                print(f"  WARN: {rel} - per-axis deadzone requires event coalescing first")
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

        sys.exit(0 if ok else 1)

    print("Applying SpaceMouse smooth navigation fix...")
    print()

    ok1 = patch_poll_spacenav(source_dir)
    ok2 = patch_process_motion_event(source_dir)
    ok3 = patch_per_axis_deadzone(source_dir)

    print()
    if ok1 and ok2 and ok3:
        print("All patches applied successfully.")
        sys.exit(0)
    else:
        print("Some patches failed. See errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
