from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional, Tuple


SUPPORTED_INPUT_EXTENSIONS = {".pdf", ".svg", ".frw", ".cdw", ".doc", ".docx"}


def optional_path_arg(value: Optional[str]) -> Optional[Path]:
    raw = str(value or "").strip()
    if not raw:
        return None
    return Path(raw)


def should_exit_after_pencil_maintenance(args, *, did_pencil_command: bool) -> bool:
    return bool(
        did_pencil_command
        and not args.frame
        and not args.calibrate_corners
        and not args.pencil_wear_test
        and not args.input
        and not args.plan_sheet
    )


def has_cli_action(args) -> bool:
    return bool(
        args.frame
        or args.calibrate_corners
        or args.pencil_wear_test
        or args.draw_ready
        or args.input
        or args.plan_sheet
        or args.pencil_sharpened
        or args.pencil_status
        or args.pencil_calibrate_from_last_test_stage is not None
    )


def ready_line_has_unsafe_coordinate_reset(line: str) -> bool:
    code = line.upper().split(";", 1)[0].strip()
    if "G92" not in code:
        return False
    tokens = code.replace("\t", " ").split()
    has_g92 = any(token == "G92" or token.startswith("G92.") for token in tokens)
    if not has_g92:
        return False
    axes = {token[0] for token in tokens if token[:1] in {"X", "Y", "Z", "A", "B", "C"}}
    return not axes or bool(axes - {"Z"})


def build_cli_parser(backend: Any) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PDF/SVG/FRW/CDW/DOC/DOCX -> Plotter converter")
    parser.add_argument("input", nargs="?", help="Path to PDF, SVG, FRW, CDW, DOC or DOCX file")
    parser.add_argument("--draw-ready", default=None, help="Draw an already prepared ready-to-plot variant/package root.")
    parser.add_argument("--kind", default="a4", help="Ready package kind for --draw-ready: a4, a3, a3_two_pass.")
    parser.add_argument("--item", default=None, help="Ready package item for --draw-ready, e.g. page_01 or pass_02.")
    parser.add_argument(
        "--ready-sleep",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Send $SLP after --draw-ready sender completes.",
    )
    parser.add_argument("--frame", action="store_true", help="Draw work area frame")
    parser.add_argument("--calibrate-corners", action="store_true", help="Draw 4 corner marks for calibration")
    parser.add_argument("--com", default=None, help="COM port (default detect)")
    parser.add_argument("--baud", default=backend.DEFAULT_BAUD, help="Baud rate")
    parser.add_argument("--dry-run", action="store_true", help="Generate G-code and save file without sending to plotter")
    parser.add_argument("--preview", action="store_true", help="Generate G-code and do not send to plotter")
    parser.add_argument("--open-preview", action="store_true", help="Open prepared G-code in default viewer")
    parser.add_argument("--output", default=None, help="Output file when --dry-run is set")
    parser.add_argument(
        "--feed-travel",
        type=float,
        default=backend.FEED_TRAVEL,
        help=f"Feed for rapid moves (default {backend.FEED_TRAVEL})",
    )
    parser.add_argument(
        "--feed-draw",
        type=float,
        default=backend.FEED_DRAW,
        help=f"Feed for drawing moves (default {backend.FEED_DRAW})",
    )
    parser.add_argument("--z-delay-down", type=float, default=None, help=f"Pen-down settle delay seconds (default {backend.Z_DELAY_DOWN})")
    parser.add_argument("--z-delay-up", type=float, default=None, help=f"Pen-up settle delay seconds (default {backend.Z_DELAY_UP})")
    parser.add_argument(
        "--z-feed-down-approach",
        type=float,
        default=None,
        help=f"Z feed for approach before touch (default {backend.Z_FEED_DOWN_APPROACH})",
    )
    parser.add_argument(
        "--z-feed-down-touch",
        type=float,
        default=None,
        help=f"Z feed for final touch-down (default {backend.Z_FEED_DOWN_TOUCH})",
    )
    parser.add_argument("--z-feed-up", type=float, default=None, help=f"Z feed for main lift (default {backend.Z_FEED_UP})")
    parser.add_argument("--z-feed-up-final", type=float, default=None, help=f"Z feed for final near-top lift (default {backend.Z_FEED_UP_FINAL})")
    parser.add_argument("--z-soft-down-mm", type=float, default=None, help=f"Slow final distance before Z-down (default {backend.Z_SOFT_DOWN_MM})")
    parser.add_argument("--z-soft-up-mm", type=float, default=None, help=f"Slow final distance before Z-up (default {backend.Z_SOFT_UP_MM})")
    parser.add_argument(
        "--z-travel-lift-mm",
        type=float,
        default=None,
        help=f"Inter-path lift distance from Z-down towards Z-up (default {backend.Z_TRAVEL_LIFT_MM})",
    )
    parser.add_argument(
        "--safe-travel-up",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Always lift to full Z_UP before every G0 travel move (recommended for clean technical drawings).",
    )
    parser.add_argument("--skip-calibration", action="store_true", help="Skip 4-corner calibration before drawing")
    parser.add_argument("--skip-calibration-confirmation", action="store_true", help="Do not ask confirmation after calibration")
    parser.add_argument(
        "--auto-resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-resume from current position if the sender aborts (best effort).",
    )
    parser.add_argument("--corner-mark-size", type=float, default=2.0, help="Corner mark size in mm")
    parser.add_argument(
        "--quality",
        default=backend.DEFAULT_QUALITY_PROFILE,
        choices=["fast", "normal", "high"],
        help="Geometry quality profile: fast/normal/high",
    )
    parser.add_argument(
        "--draw-order",
        default=backend.DRAW_ORDER_MODE,
        choices=["auto", "nearest", "source", "line_lr"],
        help="Polyline order mode: auto, nearest (fastest), source (as in file), line_lr (top->bottom, left->right).",
    )
    parser.add_argument(
        "--draw-order-line-tol-mm",
        type=float,
        default=backend.DRAW_ORDER_LINE_TOL_MM,
        help="Row clustering tolerance for --draw-order line_lr (mm).",
    )
    parser.add_argument("--curve-segment-mm", type=float, default=None, help="Override curve approximation step size")
    parser.add_argument("--arc-segment-mm", type=float, default=None, help="Override arc approximation step size")
    parser.add_argument("--collinear-eps", type=float, default=None, help="Override collinear simplification epsilon")
    parser.add_argument("--rdp-eps", type=float, default=None, help="RDP simplify epsilon (mm) for G1-only polylines (0 disables)")
    parser.add_argument("--arc-fit-tol", type=float, default=None, help="Max radial error (mm) to replace polyline by G2/G3 arc")
    parser.add_argument("--line-fit-tol", type=float, default=None, help="Max deviation (mm) to replace polyline by a single line")
    parser.add_argument("--no-simplify", action="store_true", help="Disable polyline simplification")
    parser.add_argument("--no-rdp", action="store_true", help="Disable RDP polyline simplification (keep raw segments)")
    parser.add_argument("--no-arcs", action="store_true", help="Disable emitting G2/G3 arcs (use only G1)")
    parser.add_argument(
        "--strict-1to1",
        action="store_true",
        help=(
            "Preserve 1:1 mm dimensions when fit-to-area would shrink geometry too much. "
            "May clip geometry that does not fit the configured work area."
        ),
    )
    parser.add_argument(
        "--sheet-format",
        default="work",
        choices=["work", "a4", "a3", "notebook", "custom"],
        help="Active sheet profile inside workspace.",
    )
    parser.add_argument("--sheet-width-mm", type=float, default=None, help="Sheet width override (mm).")
    parser.add_argument("--sheet-height-mm", type=float, default=None, help="Sheet height override (mm).")
    parser.add_argument(
        "--sheet-anchor",
        default="center",
        choices=["center", "lower_left", "upper_left", "lower_right", "upper_right"],
        help="How to place smaller sheet area inside machine workspace.",
    )
    parser.add_argument("--sheet-offset-x-mm", type=float, default=0.0, help="Shift active sheet area in X (mm).")
    parser.add_argument("--sheet-offset-y-mm", type=float, default=0.0, help="Shift active sheet area in Y (mm).")
    parser.add_argument("--plan-sheet", action="store_true", help="Print pass plan for selected sheet and continue.")
    parser.add_argument("--pass-cols", type=int, default=1, help="How many passes along X for current sheet.")
    parser.add_argument("--pass-rows", type=int, default=1, help="How many passes along Y for current sheet.")
    parser.add_argument("--pass-col", type=int, default=1, help="Current pass column index (1-based).")
    parser.add_argument("--pass-row", type=int, default=1, help="Current pass row index (1-based).")
    parser.add_argument("--auto-pass-grid", action="store_true", help="Auto-select pass grid from sheet size and active area.")
    parser.add_argument("--tool", default="pen", choices=["pen", "pencil"], help="Drawing tool mode.")
    parser.add_argument("--pencil-base-z-down", type=float, default=None, help="Base Z_DOWN for pencil mode.")
    parser.add_argument("--pencil-wear-mm-per-m", type=float, default=None, help="Estimated HB wear (mm per 1 meter draw).")
    parser.add_argument("--pencil-z-comp-per-wear", type=float, default=None, help="Extra Z mm per 1 mm estimated wear.")
    parser.add_argument("--pencil-max-comp-mm", type=float, default=None, help="Max automatic Z compensation for pencil wear.")
    parser.add_argument("--pencil-remind-wear-mm", type=float, default=None, help="Wear threshold for sharpen reminder.")
    parser.add_argument("--pencil-sharpen-interval-m", type=float, default=None, help="Length-based sharpen interval in meters (0 disables).")
    parser.add_argument("--pencil-sharpened", action="store_true", help="Reset accumulated pencil wear state.")
    parser.add_argument("--pencil-status", action="store_true", help="Print current pencil profile/state and exit.")
    parser.add_argument(
        "--pencil-calibrate-from-last-test-stage",
        type=int,
        default=None,
        help="Use last wear-test report and stage number (last acceptable block) to auto-tune wear rate/sharpen interval.",
    )
    parser.add_argument(
        "--pencil-calibrate-first-bad-stage",
        type=int,
        default=0,
        help="Optional first unacceptable stage for auto calibration.",
    )
    parser.add_argument(
        "--pencil-calibrate-safety-factor",
        type=float,
        default=0.90,
        help="Safety factor for derived sharpen interval from calibration stage (0.5..0.99).",
    )
    parser.add_argument("--pencil-wear-test", action="store_true", help="Draw dense hatched test blocks to calibrate pencil wear.")
    parser.add_argument("--pencil-wear-test-levels", type=int, default=8, help="Number of wear-test blocks.")
    parser.add_argument("--pencil-wear-test-cols", type=int, default=2, help="How many block columns for wear-test.")
    parser.add_argument("--pencil-wear-test-hatch-step-mm", type=float, default=1.0, help="Wear-test hatch spacing (mm).")
    parser.add_argument("--pencil-wear-test-loops", type=int, default=1, help="Cross-hatch loop count per wear-test block.")
    parser.add_argument("--pencil-wear-test-margin-mm", type=float, default=8.0, help="Wear-test margin from active area borders (mm).")
    parser.add_argument("--pencil-wear-test-gap-mm", type=float, default=6.0, help="Wear-test gap between blocks (mm).")
    parser.add_argument(
        "--force-text-to-path",
        action="store_true",
        default=None,
        help="Always convert text nodes to paths (stronger glyph output)",
    )
    parser.add_argument(
        "--handwriting",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable handwriting font replacement for text before vectorization.",
    )
    parser.add_argument(
        "--handwriting-font",
        default=None,
        help="Font family for handwriting mode (example: Marck Script).",
    )
    parser.add_argument(
        "--handwriting-direct-vector",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Prefer direct vector stroke-font conversion for text (no raster/skeleton stage).",
    )
    parser.add_argument(
        "--handwriting-centerline-backend",
        choices=["auto", "skeleton", "autotrace3"],
        default=None,
        help="Centerline backend for TTF handwriting mode: auto | skeleton | autotrace3.",
    )
    parser.add_argument(
        "--image-contours-mode",
        choices=["off", "word_only", "always"],
        default=None,
        help="Raster contour extraction mode: off | word_only | always.",
    )
    return parser


def apply_cli_runtime_overrides(backend: Any, args) -> None:
    backend.apply_pencil_profile(backend.load_pencil_profile())

    backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.98 if args.strict_1to1 else 0.0
    backend.TOOL_MODE = (args.tool or "pen").strip().lower()
    backend.DRAW_ORDER_MODE = (args.draw_order or backend.DRAW_ORDER_MODE).strip().lower()
    backend.DRAW_ORDER_LINE_TOL_MM = max(0.2, float(args.draw_order_line_tol_mm))
    backend.Z_PROFILE_CLI_OVERRIDE = any(
        v is not None
        for v in (
            args.z_delay_down,
            args.z_delay_up,
            args.z_feed_down_approach,
            args.z_feed_down_touch,
            args.z_feed_up,
            args.z_feed_up_final,
            args.z_soft_down_mm,
            args.z_soft_up_mm,
            args.z_travel_lift_mm,
        )
    )
    backend.PASS_COLS = max(1, int(args.pass_cols))
    backend.PASS_ROWS = max(1, int(args.pass_rows))
    backend.PASS_COL = min(max(1, int(args.pass_col)), backend.PASS_COLS)
    backend.PASS_ROW = min(max(1, int(args.pass_row)), backend.PASS_ROWS)

    if args.pencil_base_z_down is not None:
        backend.PENCIL_BASE_Z_DOWN = float(args.pencil_base_z_down)
    if args.pencil_wear_mm_per_m is not None:
        backend.PENCIL_WEAR_MM_PER_M = max(0.0, float(args.pencil_wear_mm_per_m))
    if args.pencil_z_comp_per_wear is not None:
        backend.PENCIL_Z_COMP_MM_PER_WEAR_MM = max(0.0, float(args.pencil_z_comp_per_wear))
    if args.pencil_max_comp_mm is not None:
        backend.PENCIL_MAX_COMP_MM = max(0.0, float(args.pencil_max_comp_mm))
    if args.pencil_remind_wear_mm is not None:
        backend.PENCIL_REMIND_WEAR_MM = max(0.0, float(args.pencil_remind_wear_mm))
    if args.pencil_sharpen_interval_m is not None:
        backend.PENCIL_SHARPEN_INTERVAL_M = max(0.0, float(args.pencil_sharpen_interval_m))

    if args.z_delay_down is not None:
        backend.Z_DELAY_DOWN = max(0.0, float(args.z_delay_down))
    if args.z_delay_up is not None:
        backend.Z_DELAY_UP = max(0.0, float(args.z_delay_up))
    if args.z_feed_down_approach is not None:
        backend.Z_FEED_DOWN_APPROACH = max(1.0, float(args.z_feed_down_approach))
    if args.z_feed_down_touch is not None:
        backend.Z_FEED_DOWN_TOUCH = max(1.0, float(args.z_feed_down_touch))
    if args.z_feed_up is not None:
        backend.Z_FEED_UP = max(1.0, float(args.z_feed_up))
    if args.z_feed_up_final is not None:
        backend.Z_FEED_UP_FINAL = max(1.0, float(args.z_feed_up_final))
    if args.z_soft_down_mm is not None:
        backend.Z_SOFT_DOWN_MM = max(0.0, float(args.z_soft_down_mm))
    if args.z_soft_up_mm is not None:
        backend.Z_SOFT_UP_MM = max(0.0, float(args.z_soft_up_mm))
    if args.z_travel_lift_mm is not None:
        backend.Z_TRAVEL_LIFT_MM = max(0.0, float(args.z_travel_lift_mm))
    if args.safe_travel_up is not None:
        backend.SAFE_PEN_TRAVEL_UP = bool(args.safe_travel_up)
    if args.handwriting is not None:
        backend.HANDWRITING_TEXT_ENABLED = bool(args.handwriting)
    if args.handwriting_font is not None and str(args.handwriting_font).strip():
        normalized_hw = backend.normalize_handwriting_font_name(args.handwriting_font)
        backend.HANDWRITING_FONT_FAMILY = normalized_hw
        backend.HANDWRITING_CYRILLIC_FONT_FAMILY = normalized_hw
    if args.handwriting_direct_vector is not None:
        backend.HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = bool(args.handwriting_direct_vector)
    if args.handwriting_centerline_backend is not None:
        backend.HANDWRITING_SINGLELINE_TTF_BACKEND = backend._normalize_singleline_ttf_backend(args.handwriting_centerline_backend)
    if args.image_contours_mode is not None:
        backend.IMAGE_CONTOUR_MODE = backend.normalize_image_contour_mode(args.image_contours_mode)
        backend.IMAGE_CONTOUR_ENABLED = backend.IMAGE_CONTOUR_MODE != "off"
        backend.IMAGE_CONTOUR_WORD_ONLY = backend.IMAGE_CONTOUR_MODE == "word_only"

    pencil_profile_overrides = any(
        v is not None
        for v in (
            args.pencil_base_z_down,
            args.pencil_wear_mm_per_m,
            args.pencil_z_comp_per_wear,
            args.pencil_max_comp_mm,
            args.pencil_remind_wear_mm,
            args.pencil_sharpen_interval_m,
        )
    )
    if pencil_profile_overrides:
        profile_to_save = backend.load_pencil_profile()
        profile_to_save.update(backend.build_pencil_profile_snapshot())
        profile_to_save["updated_at_utc"] = backend._now_iso_utc()
        profile_to_save["source"] = "cli_override"
        backend.save_pencil_profile(profile_to_save)
        print(f"Pencil profile saved: {backend.PENCIL_PROFILE_PATH}")


def run_cli_pencil_maintenance(backend: Any, args) -> Tuple[bool, Optional[int]]:
    did_pencil_command = False
    if args.pencil_sharpened:
        backend.reset_pencil_state_after_sharpen(print, reason="cli")
        did_pencil_command = True

    if args.pencil_calibrate_from_last_test_stage is not None:
        ok, msg = backend.calibrate_pencil_wear_from_last_test(
            last_good_stage=int(args.pencil_calibrate_from_last_test_stage),
            first_bad_stage=max(0, int(args.pencil_calibrate_first_bad_stage or 0)),
            safety_factor=float(args.pencil_calibrate_safety_factor),
            logger=lambda _msg: None,
        )
        print(msg)
        if not ok:
            return True, 1
        did_pencil_command = True

    if args.pencil_status:
        backend.show_pencil_status(print)
        did_pencil_command = True

    return did_pencil_command, None


def configure_cli_sheet_state(backend: Any, args) -> Tuple[Optional[int], Optional[Tuple[float, float]]]:
    try:
        backend.configure_active_work_area(
            sheet_format=args.sheet_format,
            sheet_width_mm=args.sheet_width_mm,
            sheet_height_mm=args.sheet_height_mm,
            anchor=args.sheet_anchor,
            offset_x_mm=args.sheet_offset_x_mm,
            offset_y_mm=args.sheet_offset_y_mm,
            logger=print,
        )
    except ValueError as exc:
        print(backend._format_internal_exception("Invalid sheet configuration", exc))
        return 1, None

    try:
        sheet_w_mm, sheet_h_mm = backend.resolve_sheet_size_mm(
            sheet_format=args.sheet_format,
            sheet_width_mm=args.sheet_width_mm,
            sheet_height_mm=args.sheet_height_mm,
        )
    except ValueError as exc:
        print(backend._format_internal_exception("Invalid sheet size", exc))
        return 1, None

    if args.auto_pass_grid:
        plan_auto = backend.plan_tiled_passes_for_sheet(sheet_w_mm, sheet_h_mm)
        backend.PASS_COLS = max(1, int(plan_auto["nx"]))
        backend.PASS_ROWS = max(1, int(plan_auto["ny"]))
        backend.PASS_COL = min(max(1, int(args.pass_col)), backend.PASS_COLS)
        backend.PASS_ROW = min(max(1, int(args.pass_row)), backend.PASS_ROWS)
        print(
            f"Auto pass grid: {backend.PASS_COLS} x {backend.PASS_ROWS} "
            f"(current pass col={backend.PASS_COL}, row={backend.PASS_ROW}, rotated={'yes' if plan_auto['rotated'] else 'no'})"
        )
    elif backend.PASS_COL != int(args.pass_col) or backend.PASS_ROW != int(args.pass_row):
        print(
            "Pass index clamped to available grid: "
            f"col={backend.PASS_COL}/{backend.PASS_COLS}, row={backend.PASS_ROW}/{backend.PASS_ROWS}"
        )

    if args.plan_sheet:
        plan = backend.plan_tiled_passes_for_sheet(sheet_w_mm, sheet_h_mm)
        min_x, max_x, min_y, max_y = backend.work_area_bounds()
        print(
            f"Sheet plan ({args.sheet_format}): {sheet_w_mm:.1f} x {sheet_h_mm:.1f} mm, "
            f"active bounds x({min_x:.3f},{max_x:.3f}) y({min_y:.3f},{max_y:.3f})"
        )
        print(
            f"1:1 pass grid needed: {plan['nx']} x {plan['ny']} = {plan['passes']} "
            f"(rotated={'yes' if plan['rotated'] else 'no'})"
        )
        if int(plan["passes"]) > 2:
            print(
                "Two-pass 1:1 is impossible for this sheet on current area. "
                f"Max two-pass scale ~= {float(plan['max_two_pass_scale']):.3f}."
            )
        print(f"Current selected pass: col={backend.PASS_COL}/{backend.PASS_COLS}, row={backend.PASS_ROW}/{backend.PASS_ROWS}")

    return None, (sheet_w_mm, sheet_h_mm)


def apply_cli_quality_profile(backend: Any, args) -> Optional[int]:
    try:
        backend.apply_quality_profile(
            quality=args.quality,
            curve_segment_mm=args.curve_segment_mm,
            arc_segment_mm=args.arc_segment_mm,
            collinear_eps=args.collinear_eps,
            rdp_simplify_eps_mm=args.rdp_eps,
            arc_fit_tol_mm=args.arc_fit_tol,
            line_fit_tol_mm=args.line_fit_tol,
            disable_simplify=args.no_simplify,
            disable_arcs=args.no_arcs,
            force_text_to_path=args.force_text_to_path,
        )
    except ValueError as exc:
        print(backend._format_internal_exception("Invalid quality configuration", exc))
        return 1
    print(f"Drawing profile: {backend.quality_state()}")
    return None


def run_cli_action(backend: Any, args, parser: argparse.ArgumentParser, *, com: str) -> int:
    output_path = optional_path_arg(args.output)

    if args.draw_ready:
        try:
            from .jobs.ready_package_selector import find_first_ready_package
        except Exception as exc:
            print(f"Cannot import ready package selector: {type(exc).__name__}: {exc}")
            return 1
        try:
            selection = find_first_ready_package(Path(args.draw_ready), kind=args.kind, item=args.item)
            nc_path = Path(selection.nc)
        except Exception as exc:
            print(f"Ready package selection failed: {type(exc).__name__}: {exc}")
            return 1
        if not nc_path.exists():
            print(f"Ready G-code not found: {nc_path}")
            return 1
        try:
            has_coordinate_reset = any(
                ready_line_has_unsafe_coordinate_reset(line)
                for line in nc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            )
        except Exception:
            has_coordinate_reset = False
        if has_coordinate_reset:
            print(
                f"Preflight failed for ready file: {nc_path}: "
                "coordinate reset G92 for X/Y axes is not allowed in ready draw files."
            )
            return 1
        pf_ok, pf_msg = backend.preflight_check_gcode(nc_path, logger=print)
        print(f"Ready preflight: {pf_msg}")
        if not pf_ok:
            return 1
        if args.dry_run or args.preview:
            print(f"Ready file selected: {nc_path}")
            return 0
        plot_time_s = backend.send_to_grbl(
            nc_path,
            com,
            args.baud,
            print,
            sleep_after=bool(args.ready_sleep),
            auto_resume=bool(args.auto_resume),
        )
        try:
            duration = backend.format_duration_hms(float(plot_time_s))
        except Exception:
            duration = f"{float(plot_time_s):.1f}s"
        print(f"Ready draw complete: {nc_path} ({duration})")
        return 0

    if args.plan_sheet and not args.frame and not args.calibrate_corners and not args.pencil_wear_test and not args.input:
        return 0

    if args.frame:
        ok, msg = backend.run_frame_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=output_path,
        )
        print(msg)
        return 0 if ok else 1

    if args.calibrate_corners:
        ok, msg = backend.run_corner_calibration_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=output_path,
            mark_size=args.corner_mark_size,
        )
        print(msg)
        return 0 if ok else 1

    if args.pencil_wear_test:
        ok, msg = backend.run_pencil_wear_test_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=output_path,
            feed_travel=args.feed_travel,
            feed_draw=args.feed_draw,
            auto_resume=bool(args.auto_resume),
            levels=args.pencil_wear_test_levels,
            cols=args.pencil_wear_test_cols,
            hatch_step_mm=args.pencil_wear_test_hatch_step_mm,
            hatch_loops=args.pencil_wear_test_loops,
            margin_mm=args.pencil_wear_test_margin_mm,
            gap_mm=args.pencil_wear_test_gap_mm,
        )
        print(msg)
        return 0 if ok else 1

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Input not found: {input_path}")
            return 2
        if input_path.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
            print(f"Unsupported file type: {input_path.suffix}. Use .pdf, .svg, .frw, .cdw, .doc or .docx.")
            return 3

        send_to_plotter = not (args.dry_run or args.preview)
        ok, msg = backend.run_pipeline_with_corner_calibration(
            input_path,
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=send_to_plotter,
            output_path=output_path,
            skip_calibration=args.skip_calibration,
            skip_confirmation=args.skip_calibration_confirmation or args.dry_run or args.preview,
            corner_mark_size=args.corner_mark_size,
            feed_travel=args.feed_travel,
            feed_draw=args.feed_draw,
            auto_resume=bool(args.auto_resume),
        )
        if ok and args.preview:
            output_guess = output_path or input_path.with_name(f"{input_path.stem}_prepared.nc")
            trim_guess = output_path.with_suffix(".svg") if output_path is not None else output_guess.with_name(f"{input_path.stem}_trimmed.svg")
            if output_guess.exists():
                if args.open_preview:
                    backend.open_with_default_viewer(output_guess)
                print(f"Preview ready: {output_guess}")
            if trim_guess.exists():
                if args.open_preview:
                    backend.open_with_default_viewer(trim_guess)
                print(f"Trim preview ready: {trim_guess}")
        print(msg)
        return 0 if ok else 1

    parser.print_help()
    print("")
    print("No action specified. Use explicit CLI commands shown above.")
    return 2


def run_cli_main(backend: Any, argv: Optional[list[str]] = None) -> int:
    backend._force_utf8_stdio()
    parser = build_cli_parser(backend)
    args = parser.parse_args(argv)
    if not has_cli_action(args):
        parser.print_help()
        print("")
        print("No action specified. Use explicit CLI commands shown above.")
        return 2
    if args.no_rdp:
        args.rdp_eps = 0.0
    if args.feed_travel <= 0 or args.feed_draw <= 0:
        print("Invalid feed: --feed-travel and --feed-draw must be > 0")
        return 1

    apply_cli_runtime_overrides(backend, args)
    did_pencil_command, pencil_error_code = run_cli_pencil_maintenance(backend, args)
    if pencil_error_code is not None:
        return pencil_error_code
    if should_exit_after_pencil_maintenance(args, did_pencil_command=did_pencil_command):
        return 0

    sheet_error_code, _sheet_size = configure_cli_sheet_state(backend, args)
    if sheet_error_code is not None:
        return sheet_error_code

    com = backend.detect_com_port(args.com)
    quality_error_code = apply_cli_quality_profile(backend, args)
    if quality_error_code is not None:
        return quality_error_code
    return run_cli_action(backend, args, parser, com=com)
