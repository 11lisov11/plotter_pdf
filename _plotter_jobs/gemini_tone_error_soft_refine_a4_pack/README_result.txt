TONE ERROR SOFT REFINE A4 package
source: C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg
base_nc: C:\plotter_pdf\_plotter_jobs\gemini_tone_error_corrected_a4_pack\gemini_tone_error_corrected_a4.nc
output_dir: C:\plotter_pdf\_plotter_jobs\gemini_tone_error_soft_refine_a4_pack
image_px_after_crop: 896 x 1194
work_area_mm: 180.0 x 280.0
drawing_size_mm: 176.00 x 234.54
base_paths: 9310
extra_paths: 550
paths_total: 9860
kind_counts: {'border': 1, 'deep': 3546, 'dark': 2032, 'mid': 830, 'soft': 265, 'forest_deep_marks': 34, 'faint_long': 49, 'jacket_soft_cross': 102, 'jacket_deep_cross': 93, 'jacket_deep_horizontal': 56, 'forest_error_dark': 277, 'field_error_flow': 99, 'forest_error_mid': 423, 'figure_error_mid': 635, 'grass_error': 205, 'figure_error_dark': 466, 'hair_error_flow': 197, 'forest_dark_refine': 136, 'forest_soft_refine': 221, 'field_soft_refine': 40, 'hair_soft_refine': 72, 'sky_soft_refine': 1, 'grass_soft_refine': 46, 'figure_soft_refine': 23, 'grass_dark_refine': 10, 'figure_dark_refine': 1}
soft_refine_counts: {'sky_soft_refine': 1, 'forest_soft_refine': 221, 'forest_dark_refine': 136, 'field_soft_refine': 40, 'grass_soft_refine': 46, 'grass_dark_refine': 10, 'hair_soft_refine': 72, 'figure_soft_refine': 23, 'figure_dark_refine': 1}
draw_length_m: 37.34
travel_length_m: 14.52
estimated_time_min_ideal: 67.9
realistic_time_note: likely 2-4 hours. Soft refine adds strokes only where base is lighter than denoised source tone; sky/light zones are protected by thresholds.
algorithm_note: starts from tone_error_corrected, renders it to a tone map, computes residual tone error, and adds limited direction-aware soft strokes in under-darkened regions.
files:
- gemini_tone_error_soft_refine_preview_pressure_gray.png/pdf
- gemini_tone_error_soft_refine_preview_black_actual.png/pdf
- gemini_tone_error_soft_refine_preview_dark_pressure.png/pdf
- gemini_tone_error_soft_refine_a4.nc
- gemini_tone_error_soft_refine_a4.gcode
