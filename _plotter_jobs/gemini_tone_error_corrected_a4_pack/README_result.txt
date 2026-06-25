TONE ERROR CORRECTED A4 package
source: C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg
base_nc: C:\plotter_pdf\_plotter_jobs\gemini_multilevel_true_strokes_dark_jacket_a4_pack\gemini_multilevel_true_strokes_dark_jacket_a4.nc
output_dir: C:\plotter_pdf\_plotter_jobs\gemini_tone_error_corrected_a4_pack
image_px_after_crop: 896 x 1194
work_area_mm: 180.0 x 280.0
drawing_size_mm: 176.00 x 234.54
base_paths: 7008
extra_paths: 2302
paths_total: 9310
kind_counts: {'border': 1, 'deep': 3546, 'dark': 2032, 'mid': 830, 'soft': 265, 'forest_deep_marks': 34, 'faint_long': 49, 'jacket_soft_cross': 102, 'jacket_deep_cross': 93, 'jacket_deep_horizontal': 56, 'forest_error_mid': 423, 'forest_error_dark': 277, 'field_error_flow': 99, 'figure_error_mid': 635, 'grass_error': 205, 'figure_error_dark': 466, 'hair_error_flow': 197}
correction_counts: {'sky_error_soft': 0, 'forest_error_mid': 423, 'forest_error_dark': 277, 'field_error_flow': 99, 'grass_error': 205, 'figure_error_mid': 635, 'figure_error_dark': 466, 'hair_error_flow': 197}
draw_length_m: 34.98
travel_length_m: 14.77
estimated_time_min_ideal: 63.6
realistic_time_note: likely 2-4 hours. Closest match requires calibrated Z pressure and pencil/soft pen.
algorithm_note: renders base G-code back to a tone map, compares it to the denoised source tone, then adds deterministic local strokes only where target is darker than current. Sky/light zones are threshold-protected.
files:
- gemini_tone_error_corrected_preview_pressure_gray.png/pdf
- gemini_tone_error_corrected_preview_black_actual.png/pdf
- gemini_tone_error_corrected_preview_dark_pressure.png/pdf
- gemini_tone_error_corrected_a4.nc
- gemini_tone_error_corrected_a4.gcode
