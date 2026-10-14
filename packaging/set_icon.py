"""Give a file, folder or mounted volume a custom Finder icon. Usage: python set_icon.py <icon.icns> <path>"""

import sys

import AppKit


def main(icon_path: str, target: str) -> None:
    image = AppKit.NSImage.alloc().initWithContentsOfFile_(icon_path)
    if image is None:
        sys.exit(f"Could not read icon {icon_path}")
    if not AppKit.NSWorkspace.sharedWorkspace().setIcon_forFile_options_(image, target, 0):
        sys.exit(f"Could not set icon on {target}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
