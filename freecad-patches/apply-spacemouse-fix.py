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

    # Add the if(hasMotion) block before the closing brace of pollSpacenav
    # Find the closing "}\n}" pattern (inner loop closing + function closing)
    # We need to add it after the while loop ends, before the function closes
    old_end = "    }\n}"
    new_end = "    }\n    if (hasMotion) {\n        mainApp->postMotionEvent(motionDataArray);\n    }\n}"

    if old_end not in content:
        # Try alternate brace style
        old_end = "    }\n}\n"
        new_end = "    }\n    if (hasMotion) {\n        mainApp->postMotionEvent(motionDataArray);\n    }\n}\n"

    if old_end not in content:
        print(f"  FAIL: Could not find end-of-function pattern in {os.path.relpath(filepath, source_dir)}")
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
            with open(spnav_file) as f:
                c = f.read()
            if "hasMotion" in c:
                print(f"  OK: {os.path.relpath(spnav_file, source_dir)} already patched")
            elif "mainApp->postMotionEvent(motionDataArray)" in c:
                print(f"  OK: {os.path.relpath(spnav_file, source_dir)} can be patched")
            else:
                print(f"  WARN: {os.path.relpath(spnav_file, source_dir)} - pattern not found")
                ok = False

        if nav_file:
            with open(nav_file) as f:
                c = f.read()
            if "enableNotify(false)" in c:
                print(f"  OK: {os.path.relpath(nav_file, source_dir)} already patched")
            elif "camera->orientation.setValue(newRotation)" in c and "camera->orientation.getValue().multVec(dir" in c:
                print(f"  OK: {os.path.relpath(nav_file, source_dir)} can be patched")
            else:
                print(f"  WARN: {os.path.relpath(nav_file, source_dir)} - pattern not found")
                ok = False

        sys.exit(0 if ok else 1)

    print("Applying SpaceMouse smooth navigation fix...")
    print()

    ok1 = patch_poll_spacenav(source_dir)
    ok2 = patch_process_motion_event(source_dir)

    print()
    if ok1 and ok2:
        print("All patches applied successfully.")
        sys.exit(0)
    else:
        print("Some patches failed. See errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
