"""Generate the same 50% platform marks and full-square Testnet4 cone as the suite."""

from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


def mark(name):
    if name in {"apple", "tux"}:
        artwork = ET.parse(ROOT / "assets/icon-overlays" / (name + ".svg")).getroot()
        if "viewBox" not in artwork.attrib:
            artwork.set("viewBox", f"0 0 {artwork.get('width')} {artwork.get('height')}")
        if name == "apple":
            artwork.set("fill", "#fff")
        return artwork
    if name == "windows":
        paths = '<path fill="#3daeff" d="M2 2h21v21H2zm23 0h21v21H25zM2 25h21v21H2zm23 0h21v21H25z"/>'
    else:
        paths = ('<path fill="#0eab52" stroke="#0b4f2b" stroke-width="2" d="M22 3h4l12 35H10L22 3Z"/>'
                 '<path fill="#dbffd7" d="M18.7 13h10.6l2.5 7H16.2zm-5 14h20.6l2.5 7H11.2z"/>'
                 '<path fill="#32dc70" stroke="#0b4f2b" stroke-width="2" d="M10 37h28l8 6v3H2v-3z"/>')
    return ET.fromstring(f'<svg xmlns="{SVG}" viewBox="0 0 48 48">{paths}</svg>')


def generate():
    destination = ROOT / "assets/platform-icons"
    destination.mkdir(exist_ok=True)
    text = (ROOT / "icon.svg").read_text()
    for platform in ("macos", "windows", "linux", "umbrel"):
        for testnet in (False, True):
            overlays = []
            if testnet:
                cone = mark("cone")
                cone.attrib.update(x="0", y="0", width="1024", height=str(1024 * (0.67 + 0.28 * 47 / 48)),
                                   opacity="0.5", viewBox="1 2 46 45", preserveAspectRatio="none", **{"data-mark": "testnet4"})
                overlays.append(ET.tostring(cone, encoding="unicode"))
            if platform != "umbrel":
                artwork = mark({"macos": "apple", "windows": "windows", "linux": "tux"}[platform])
                artwork.attrib.update(x="696.32", y="51.2", width="286.72", height="286.72", opacity="0.5", **{"data-mark": platform})
                overlays.append(ET.tostring(artwork, encoding="unicode"))
            name = platform + ("-testnet4" if testnet else "")
            svg = destination / (name + ".svg")
            svg.write_text(text[:text.rfind("</svg>")] + "".join(overlays) + "</svg>\n")
            subprocess.run(["rsvg-convert", "-w", "512", "-h", "512", "-o", destination / (name + ".png"), svg], check=True)
    (ROOT / "q20/static/icon.svg").write_text(text)


if __name__ == "__main__":
    generate()
