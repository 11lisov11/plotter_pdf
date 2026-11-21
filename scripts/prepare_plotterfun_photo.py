"""Prepare local Plotterfun photo styles for the small A4 plotter. Never connects."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys
import tempfile

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import plotter_pdf_drawer as backend
from src.plotter_backend.photo_to_plotter import WorkArea
from src.plotter_backend.plotterfun import STYLES, generate_plotterfun
from src.plotter_backend.geometry.unique_strokes import unique_strokes
from scripts.prepare_photo_plot_package import gcode_draw_polylines, write_svg_polylines

MM = 72 / 25.4


def _write_photo_xy(path, paths, feed_travel, feed_draw):
    """Preserve artistic curves: no technical collinearity/closed-loop cleanup."""
    lines = ["G21", "G90", "G17", "G91.1", f"G0 Z{backend.Z_UP:.4f}"]
    for poly in unique_strokes(paths, precision=4):
        if len(poly) < 2:
            continue
        lines.append(f"G0 X{poly[0][0]:.4f} Y{poly[0][1]:.4f} F{feed_travel:.1f}")
        for i, (x, y) in enumerate(poly[1:]):
            suffix = f" F{feed_draw:.1f}" if i == 0 else ""
            lines.append(f"G1 X{x:.4f} Y{y:.4f}{suffix}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _page(doc, paths, area, title):
    page = doc.new_page(width=210 * MM, height=297 * MM)
    shape = page.new_shape()
    left = (210 - (area.max_x - area.min_x)) / 2
    top = (297 - (area.max_y - area.min_y)) / 2
    for poly in paths:
        if len(poly) >= 2:
            shape.draw_polyline([fitz.Point((left + x - area.min_x) * MM, (top + area.max_y - y) * MM) for x, y in poly])
    shape.finish(color=(0.08, 0.08, 0.08), width=0.20 * MM, closePath=False)
    shape.commit()
    # The title is preview-only, outside the plotted work area.
    page.insert_text((15 * MM, 4.5 * MM), title, fontsize=6, color=(0.3, 0.3, 0.3))
    return page


def prepare(args) -> int:
    if not args.image or not args.image.is_file():
        raise ValueError("Provide an existing source image")
    selected = list(STYLES) if args.styles == "all" else [s.strip() for s in args.styles.split(",") if s.strip()]
    if not selected or len(set(selected)) != len(selected) or any(s not in STYLES for s in selected):
        raise ValueError("Invalid or repeated style; use --list-styles")
    if getattr(backend, "MACHINE_PROFILE_NAME", "a4_desktop") != "a4_desktop":
        raise ValueError("This entry point is only for the small a4_desktop plotter")
    if args.feed_draw <= 0 or args.feed_travel <= 0:
        raise ValueError("Feed rates must be positive")
    out = (args.out_dir or ROOT / "_plotter_jobs" / (args.image.stem + "_plotterfun_A4")).resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("Output directory is not empty; choose a new directory to preserve prepared jobs")
    out.mkdir(parents=True, exist_ok=True)
    source = out / ("source" + args.image.suffix.lower())
    shutil.copyfile(args.image, source)
    area = WorkArea(*map(float, backend.work_area_bounds()))
    if abs(area.max_x - area.min_x - 180) > 0.01 or abs(area.max_y - area.min_y - 280) > 0.01:
        raise ValueError("Expected the confirmed small-plotter 180 x 280 mm field")
    user_controls = json.loads(args.controls.read_text(encoding="utf-8-sig")) if args.controls else {}
    if not isinstance(user_controls, dict):
        raise ValueError("Controls JSON must be an object")
    combined = fitz.open()
    queue, failures, thumbs = [], [], []
    for index, style in enumerate(selected, 1):
        print(f"PREPARE {index}/{len(selected)} {style}", flush=True)
        try:
            controls = {**user_controls.get("*", {}), **user_controls.get(style, {})}
            result = generate_plotterfun(
                source, style, work_area=area, quality=args.quality, fit=args.fit,
                margin_mm=args.margin_mm, max_side_px=args.max_side_px,
                contrast=args.contrast, gamma=args.gamma, seed=args.seed,
                local_contrast_blend=args.local_contrast_blend,
                controls=controls, node=args.node, timeout_seconds=args.timeout_seconds,
            )
            if not result.polylines:
                raise ValueError("No drawable paths for this image and style")
            folder = out / f"{index:02d}_{style}"
            folder.mkdir()
            nc = folder / "photo_plot.nc"
            # Reuse the production lift/finalization pipeline, without a sender.
            saved = {name: getattr(backend, name) for name in ("EMIT_ARCS", "LINE_FIT_TOL_MM", "RDP_SIMPLIFY_EPS_MM", "DIRECT_PDF_VECTOR_SOURCE_ACTIVE")}
            try:
                backend.EMIT_ARCS = False
                backend.LINE_FIT_TOL_MM = 0.0
                backend.RDP_SIMPLIFY_EPS_MM = 0.0
                # Shared exact deduplication is already applied by our writer.
                # Do not run legacy technical-drawing cleanup over art loops.
                backend.DIRECT_PDF_VECTOR_SOURCE_ACTIVE = True
                with tempfile.TemporaryDirectory(prefix="plotterfun_") as temp:
                    temp = Path(temp)
                    xy, pen, final = temp / "xy.gcode", temp / "pen.gcode", temp / "final.gcode"
                    _write_photo_xy(xy, result.polylines, args.feed_travel, args.feed_draw)
                    backend.apply_penlift(xy, pen, handwriting_mode=False, force_full_lift=True)
                    backend.make_final_with_preamble(pen, final, feed_travel=args.feed_travel)
                    text = final.read_text(encoding="utf-8")
                    text = text.replace("\n$1=0", "\nG4 P0.10\n$1=0")
                    nc.write_text(text, encoding="utf-8", newline="\n")
            finally:
                for name, value in saved.items():
                    setattr(backend, name, value)
            # All visible output below comes from the FINAL NC, not the source.
            paths = gcode_draw_polylines(nc)
            if not paths:
                raise ValueError("Final G-code has no visible pen-down strokes")
            for poly in paths:
                for x, y in poly:
                    if not (area.min_x - 0.01 <= x <= area.max_x + 0.01 and area.min_y - 0.01 <= y <= area.max_y + 0.01):
                        raise ValueError("Final pen-down path leaves the confirmed field")
            pdf = folder / "A4_from_Gcode.pdf"
            single = fitz.open()
            page = _page(single, paths, area, STYLES[style])
            page.get_pixmap(matrix=fitz.Matrix(1.15, 1.15), alpha=False).save(folder / "A4_from_Gcode.png")
            single.save(pdf, deflate=True)
            combined.insert_pdf(single)
            single.close()
            write_svg_polylines(folder / "from_Gcode.svg", paths, area)
            metadata = {
                "style": style, "title": STYLES[style], "machine_profile": "a4_desktop", "sheet_format": "A4",
                "work_area_mm": [area.min_x, area.max_x, area.min_y, area.max_y],
                "source_size_px": result.source_size_px, "processed_size_px": result.processed_size_px,
                "target_size_mm": result.target_size_mm, "placement_bounds": result.placement_bounds,
                "feed_draw": args.feed_draw, "feed_travel": args.feed_travel,
                "stats": result.stats, "nc_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "preview_source": "final_nc_pen_down_paths", "hardware_started": False,
            }
            (folder / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            queue.append({"number": index, "style": style, "file": nc.relative_to(out).as_posix(),
                          "sha256": metadata["nc_sha256"], "preview": pdf.relative_to(out).as_posix()})
            thumbs.append((style, folder / "A4_from_Gcode.png"))
            print(f"READY {style}: {len(paths)} strokes", flush=True)
        except Exception as error:
            failures.append({"style": style, "error": str(error)})
            print(f"FAILED {style}: {error}", flush=True)
    if combined.page_count:
        combined.save(out / "All_styles_from_Gcode.pdf", deflate=True)
    combined.close()
    contacts = []
    for offset in range(0, len(thumbs), 4):
        canvas = Image.new("RGB", (1000, 1480), "#e8e5df")
        draw = ImageDraw.Draw(canvas)
        for slot, (name, image_path) in enumerate(thumbs[offset:offset + 4]):
            with Image.open(image_path) as image:
                image = image.convert("RGB")
                image.thumbnail((470, 675))
                x, y = 15 + (slot % 2) * 500, 30 + (slot // 2) * 740
                canvas.paste(image, (x + (470 - image.width) // 2, y))
                draw.text((x + 8, y + 685), STYLES[name], fill="#222222")
        contact = out / f"contact_{offset // 4 + 1:02d}.png"
        canvas.save(contact)
        contacts.append(contact.name)
    (out / "photo_queue.json").write_text(json.dumps({"machine_profile": "a4_desktop", "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "files": queue, "failures": failures,
        "hardware_started": False}, indent=2) + "\n", encoding="utf-8")
    cards = ''.join(f'<figure><a href="{html.escape(record["preview"])}"><img loading="lazy" src="{html.escape(record["preview"].replace(".pdf", ".png"))}"></a><figcaption>{html.escape(STYLES[record["style"]])}</figcaption></figure>' for record in queue)
    (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Plotterfun A4 - final G-code</title><style>body{margin:32px;background:#e8e5df;color:#292824;font:18px Georgia,serif}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px}figure{margin:0}img{width:100%;height:auto}figcaption{padding:10px 0}</style><h1>Plotterfun A4</h1><p>Reconstructed from final G-code. No plotting started.</p><main>'+cards+'</main>', encoding="utf-8")
    print(json.dumps({"out_dir": str(out), "prepared": len(queue), "failed": failures, "contacts": contacts}), flush=True)
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, nargs="?")
    parser.add_argument("--list-styles", action="store_true")
    parser.add_argument("--styles", default="all", help="all, or comma-separated style IDs")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--quality", choices=["fast", "normal", "detailed"], default="normal")
    parser.add_argument("--fit", choices=["cover", "contain"], default="cover")
    parser.add_argument("--margin-mm", type=float, default=0.0)
    parser.add_argument("--max-side-px", type=int)
    parser.add_argument("--contrast", type=float, default=1.0)
    parser.add_argument("--gamma", type=float, default=1.0)
    parser.add_argument("--local-contrast-blend", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--controls", type=Path, help='JSON: {"*": {...}, "style-id": {...}}')
    parser.add_argument("--node", help="Path to node.exe; otherwise PATH or PLOTTERFUN_NODE")
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--feed-draw", type=float, default=2200)
    parser.add_argument("--feed-travel", type=float, default=15000)
    args = parser.parse_args(argv)
    if args.list_styles:
        print(json.dumps(STYLES, indent=2))
        return 0
    return prepare(args)


if __name__ == "__main__":
    raise SystemExit(main())
