from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class JobSettings:
    input_path: str | Path | None = None
    output_dir: str | Path | None = None
    sheet_format: str = "work"
    sheet_width_mm: float | None = None
    sheet_height_mm: float | None = None
    sheet_anchor: str = "center"
    sheet_offset_x_mm: float = 0.0
    sheet_offset_y_mm: float = 0.0
    pass_cols: int = 1
    pass_rows: int = 1
    pass_col: int = 1
    pass_row: int = 1
    tool: str = "pen"
    handwriting: bool = False
    com: str = ""
    baud: str | int = 115200
    preview: bool = False
    dry_run: bool = True
    open_preview: bool = False
    safe_travel_up: bool = True
    quality: str = "normal"
    draw_order: str = "auto"

    def normalized_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        if self.input_path:
            return Path(self.input_path).resolve().parent
        return Path.cwd() / "_plotter_jobs"


@dataclass(slots=True)
class JobResult:
    ok: bool
    message: str
    output_dir: Path | None = None
    gcode_path: Path | None = None
    nc_path: Path | None = None
    preview_svg_path: Path | None = None
    preview_pdf_path: Path | None = None
    report_json_path: Path | None = None
    summary_csv_path: Path | None = None
    bounds: tuple[float, float, float, float] | None = None
    line_count: int = 0
    draw_moves: int = 0
    travel_moves: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, Path):
                data[key] = str(value)
        return data
