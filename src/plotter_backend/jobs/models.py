from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(slots=True)
class JobSettings:
    input_path: Optional[Path | str] = None
    output_dir: Path | str = Path("_plotter_jobs")
    sheet_format: str = "a4"
    sheet_width_mm: Optional[float] = None
    sheet_height_mm: Optional[float] = None
    sheet_anchor: str = "center"
    sheet_offset_x_mm: float = 0.0
    sheet_offset_y_mm: float = 0.0
    pass_cols: int = 1
    pass_rows: int = 1
    pass_col: int = 1
    pass_row: int = 1
    tool: str = "pen"
    handwriting: bool = False
    com: Optional[str] = None
    baud: str = "115200"
    preview: bool = False
    dry_run: bool = True
    open_preview: bool = False
    safe_travel_up: bool = False
    quality: str = "normal"
    draw_order: str = "auto"
    machine_profile: str = "a4_desktop"
    calibration_layout: str = "sheet"

    def normalized_input_path(self) -> Optional[Path]:
        if self.input_path is None:
            return None
        return Path(self.input_path)

    def normalized_output_dir(self) -> Path:
        return Path(self.output_dir)


@dataclass(slots=True)
class JobResult:
    ok: bool
    message: str
    output_dir: Optional[Path] = None
    gcode_path: Optional[Path] = None
    nc_path: Optional[Path] = None
    preview_svg_path: Optional[Path] = None
    preview_pdf_path: Optional[Path] = None
    report_json_path: Optional[Path] = None
    summary_csv_path: Optional[Path] = None
    bounds: Optional[tuple[float, float, float, float]] = None
    line_count: int = 0
    draw_moves: int = 0
    travel_moves: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def _path(value: Optional[Path]) -> Optional[str]:
            return str(value) if value is not None else None

        return {
            "ok": self.ok,
            "message": self.message,
            "output_dir": _path(self.output_dir),
            "gcode_path": _path(self.gcode_path),
            "nc_path": _path(self.nc_path),
            "preview_svg_path": _path(self.preview_svg_path),
            "preview_pdf_path": _path(self.preview_pdf_path),
            "report_json_path": _path(self.report_json_path),
            "summary_csv_path": _path(self.summary_csv_path),
            "bounds": self.bounds,
            "line_count": self.line_count,
            "draw_moves": self.draw_moves,
            "travel_moves": self.travel_moves,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
