from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Optional, Tuple


def _default_state() -> dict[str, float | int]:
    return {
        "total_draw_m": 0.0,
        "estimated_wear_mm": 0.0,
        "jobs_done": 0,
        "last_draw_m": 0.0,
    }


def _default_profile(backend: Any) -> dict[str, float | int | str]:
    return {
        "base_z_down": float(backend.PENCIL_BASE_Z_DOWN),
        "wear_mm_per_m": float(backend.PENCIL_WEAR_MM_PER_M),
        "z_comp_per_wear": float(backend.PENCIL_Z_COMP_MM_PER_WEAR_MM),
        "max_comp_mm": float(backend.PENCIL_MAX_COMP_MM),
        "remind_wear_mm": float(backend.PENCIL_REMIND_WEAR_MM),
        "sharpen_interval_m": float(backend.PENCIL_SHARPEN_INTERVAL_M),
        "sharpen_count": 0,
        "last_sharpen_iso_utc": "",
        "source": "defaults",
    }


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _now_iso_utc() -> str:
    return now_iso_utc()


def load_pencil_state(backend: Any) -> dict:
    state = _default_state()
    try:
        if backend.PENCIL_STATE_PATH.exists():
            loaded = json.loads(backend.PENCIL_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
    except Exception:
        pass

    try:
        state["total_draw_m"] = float(state.get("total_draw_m", 0.0) or 0.0)
        state["estimated_wear_mm"] = float(state.get("estimated_wear_mm", 0.0) or 0.0)
        state["jobs_done"] = int(state.get("jobs_done", 0) or 0)
        state["last_draw_m"] = float(state.get("last_draw_m", 0.0) or 0.0)
    except Exception:
        state = _default_state()
    return state


def save_pencil_state(backend: Any, state: dict) -> None:
    backend.PENCIL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    backend.PENCIL_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pencil_profile(backend: Any) -> dict:
    profile = _default_profile(backend)
    try:
        if backend.PENCIL_PROFILE_PATH.exists():
            loaded = json.loads(backend.PENCIL_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                profile.update(loaded)
                profile["source"] = "file"
    except Exception:
        pass

    try:
        profile["base_z_down"] = float(profile.get("base_z_down", backend.PENCIL_BASE_Z_DOWN) or backend.PENCIL_BASE_Z_DOWN)
        profile["wear_mm_per_m"] = max(
            0.0,
            float(profile.get("wear_mm_per_m", backend.PENCIL_WEAR_MM_PER_M) or backend.PENCIL_WEAR_MM_PER_M),
        )
        profile["z_comp_per_wear"] = max(
            0.0,
            float(profile.get("z_comp_per_wear", backend.PENCIL_Z_COMP_MM_PER_WEAR_MM) or backend.PENCIL_Z_COMP_MM_PER_WEAR_MM),
        )
        profile["max_comp_mm"] = max(
            0.0,
            float(profile.get("max_comp_mm", backend.PENCIL_MAX_COMP_MM) or backend.PENCIL_MAX_COMP_MM),
        )
        profile["remind_wear_mm"] = max(
            0.0,
            float(profile.get("remind_wear_mm", backend.PENCIL_REMIND_WEAR_MM) or backend.PENCIL_REMIND_WEAR_MM),
        )
        profile["sharpen_interval_m"] = max(
            0.0,
            float(profile.get("sharpen_interval_m", backend.PENCIL_SHARPEN_INTERVAL_M) or backend.PENCIL_SHARPEN_INTERVAL_M),
        )
        profile["sharpen_count"] = max(0, int(profile.get("sharpen_count", 0) or 0))
        profile["last_sharpen_iso_utc"] = str(profile.get("last_sharpen_iso_utc", "") or "")
    except Exception:
        profile = _default_profile(backend)
    return profile


def save_pencil_profile(backend: Any, profile: dict) -> None:
    backend.PENCIL_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    backend.PENCIL_PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_pencil_profile(backend: Any, profile: dict) -> None:
    backend.PENCIL_BASE_Z_DOWN = float(profile.get("base_z_down", backend.PENCIL_BASE_Z_DOWN))
    backend.PENCIL_WEAR_MM_PER_M = max(0.0, float(profile.get("wear_mm_per_m", backend.PENCIL_WEAR_MM_PER_M)))
    backend.PENCIL_Z_COMP_MM_PER_WEAR_MM = max(
        0.0,
        float(profile.get("z_comp_per_wear", backend.PENCIL_Z_COMP_MM_PER_WEAR_MM)),
    )
    backend.PENCIL_MAX_COMP_MM = max(0.0, float(profile.get("max_comp_mm", backend.PENCIL_MAX_COMP_MM)))
    backend.PENCIL_REMIND_WEAR_MM = max(0.0, float(profile.get("remind_wear_mm", backend.PENCIL_REMIND_WEAR_MM)))
    backend.PENCIL_SHARPEN_INTERVAL_M = max(
        0.0,
        float(profile.get("sharpen_interval_m", backend.PENCIL_SHARPEN_INTERVAL_M)),
    )


def build_pencil_profile_snapshot(backend: Any) -> dict:
    return {
        "base_z_down": float(backend.PENCIL_BASE_Z_DOWN),
        "wear_mm_per_m": float(backend.PENCIL_WEAR_MM_PER_M),
        "z_comp_per_wear": float(backend.PENCIL_Z_COMP_MM_PER_WEAR_MM),
        "max_comp_mm": float(backend.PENCIL_MAX_COMP_MM),
        "remind_wear_mm": float(backend.PENCIL_REMIND_WEAR_MM),
        "sharpen_interval_m": float(backend.PENCIL_SHARPEN_INTERVAL_M),
    }


def save_last_wear_test_report(backend: Any, report: dict) -> None:
    backend.PENCIL_WEAR_TEST_LAST_PATH.parent.mkdir(parents=True, exist_ok=True)
    backend.PENCIL_WEAR_TEST_LAST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def load_last_wear_test_report(backend: Any) -> Optional[dict]:
    try:
        if not backend.PENCIL_WEAR_TEST_LAST_PATH.exists():
            return None
        loaded = json.loads(backend.PENCIL_WEAR_TEST_LAST_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return None


def reset_pencil_state_after_sharpen(backend: Any, logger=print, *, reason: str = "manual") -> None:
    save_pencil_state(backend, _default_state())
    profile = load_pencil_profile(backend)
    profile["sharpen_count"] = max(0, int(profile.get("sharpen_count", 0) or 0)) + 1
    profile["last_sharpen_iso_utc"] = now_iso_utc()
    profile["last_sharpen_reason"] = str(reason or "manual")
    save_pencil_profile(backend, profile)
    logger("Pencil state reset: wear=0.0 mm, draw=0.0 m (sharpen event recorded).")


def pencil_remaining_draw_m(backend: Any, state: dict) -> float:
    wear_now = max(0.0, float(state.get("estimated_wear_mm", 0.0) or 0.0))
    wear_left = max(0.0, float(backend.PENCIL_REMIND_WEAR_MM) - wear_now)
    rate = max(0.0, float(backend.PENCIL_WEAR_MM_PER_M))
    if rate <= 1e-12:
        return float("inf")
    return wear_left / rate


def pencil_remaining_to_sharpen_m(backend: Any, state: dict) -> Tuple[float, float, float]:
    by_wear = pencil_remaining_draw_m(backend, state)
    by_interval = float("inf")
    if backend.PENCIL_SHARPEN_INTERVAL_M > 1e-9:
        done_m = max(0.0, float(state.get("total_draw_m", 0.0) or 0.0))
        by_interval = max(0.0, float(backend.PENCIL_SHARPEN_INTERVAL_M) - done_m)
    best = min(by_wear, by_interval)
    return best, by_wear, by_interval


def calibrate_pencil_wear_from_last_test(
    backend: Any,
    *,
    last_good_stage: int,
    first_bad_stage: int = 0,
    safety_factor: float = 0.90,
    logger=print,
) -> Tuple[bool, str]:
    report = load_last_wear_test_report(backend)
    if not report:
        return False, f"No wear-test report found: {backend.PENCIL_WEAR_TEST_LAST_PATH}"
    stages = report.get("stage_stats")
    if not isinstance(stages, list) or not stages:
        return False, "Invalid wear-test report: missing stage_stats."

    by_stage = {}
    for st in stages:
        try:
            idx = int(st.get("stage", 0))
            by_stage[idx] = st
        except Exception:
            continue
    if last_good_stage not in by_stage:
        return False, f"Stage {last_good_stage} not found in last report."
    if first_bad_stage and first_bad_stage not in by_stage:
        return False, f"Stage {first_bad_stage} not found in last report."

    good_cum_m = max(0.0, float(by_stage[last_good_stage].get("cum_mm", 0.0) or 0.0) / 1000.0)
    if good_cum_m <= 1e-9:
        return False, "Invalid cumulative draw length for selected stage."

    threshold_m = good_cum_m
    if first_bad_stage > 0:
        bad_cum_m = max(0.0, float(by_stage[first_bad_stage].get("cum_mm", 0.0) or 0.0) / 1000.0)
        if bad_cum_m > good_cum_m:
            threshold_m = (good_cum_m + bad_cum_m) * 0.5
    safety = min(max(0.50, float(safety_factor)), 0.99)
    sharpen_interval_m = max(0.20, threshold_m * safety)

    profile = load_pencil_profile(backend)
    profile.update(build_pencil_profile_snapshot(backend))
    remind_wear = max(0.05, float(backend.PENCIL_REMIND_WEAR_MM))
    wear_rate = max(1e-6, remind_wear / max(1e-6, threshold_m))

    profile["wear_mm_per_m"] = float(wear_rate)
    profile["sharpen_interval_m"] = float(sharpen_interval_m)
    profile["last_calibration"] = {
        "at_utc": now_iso_utc(),
        "report_path": str(backend.PENCIL_WEAR_TEST_LAST_PATH),
        "last_good_stage": int(last_good_stage),
        "first_bad_stage": int(first_bad_stage) if first_bad_stage > 0 else None,
        "good_cum_m": float(good_cum_m),
        "threshold_m": float(threshold_m),
        "safety_factor": float(safety),
        "derived_wear_mm_per_m": float(wear_rate),
        "derived_sharpen_interval_m": float(sharpen_interval_m),
    }
    save_pencil_profile(backend, profile)
    apply_pencil_profile(backend, profile)

    msg = (
        f"Pencil calibration saved: wear_mm_per_m={wear_rate:.5f}, "
        f"sharpen_interval_m={sharpen_interval_m:.2f}, "
        f"threshold_m={threshold_m:.2f} (good_stage={last_good_stage}"
    )
    if first_bad_stage > 0:
        msg += f", bad_stage={first_bad_stage}"
    msg += ")."
    logger(msg)
    return True, msg


def show_pencil_status(backend: Any, logger=print) -> None:
    state = load_pencil_state(backend)
    profile = load_pencil_profile(backend)
    apply_pencil_profile(backend, profile)
    rem_best, rem_wear, rem_interval = pencil_remaining_to_sharpen_m(backend, state)
    rem_best_txt = "inf" if not math.isfinite(rem_best) else f"{rem_best:.2f}"
    rem_wear_txt = "inf" if not math.isfinite(rem_wear) else f"{rem_wear:.2f}"
    rem_interval_txt = "inf" if not math.isfinite(rem_interval) else f"{rem_interval:.2f}"
    logger(
        "Pencil status: "
        f"base_z={backend.PENCIL_BASE_Z_DOWN:.3f}, wear_rate={backend.PENCIL_WEAR_MM_PER_M:.5f} mm/m, "
        f"z_comp={backend.PENCIL_Z_COMP_MM_PER_WEAR_MM:.3f}, max_comp={backend.PENCIL_MAX_COMP_MM:.3f}, "
        f"remind_wear={backend.PENCIL_REMIND_WEAR_MM:.3f}, sharpen_interval_m={backend.PENCIL_SHARPEN_INTERVAL_M:.2f}"
    )
    logger(
        "State: "
        f"draw_total={float(state.get('total_draw_m', 0.0) or 0.0):.2f} m, "
        f"wear={float(state.get('estimated_wear_mm', 0.0) or 0.0):.3f} mm, jobs={int(state.get('jobs_done', 0) or 0)}"
    )
    logger(
        f"Remaining before sharpen: {rem_best_txt} m (wear-rule={rem_wear_txt}, interval-rule={rem_interval_txt})."
    )


def pencil_effective_z_down(backend: Any, base_z_down: float, state: dict) -> Tuple[float, float]:
    wear = max(0.0, float(state.get("estimated_wear_mm", 0.0) or 0.0))
    comp = min(backend.PENCIL_MAX_COMP_MM, wear * backend.PENCIL_Z_COMP_MM_PER_WEAR_MM)
    return base_z_down + comp, comp


def apply_pencil_wear_update(backend: Any, state: dict, draw_length_mm: float) -> dict:
    draw_m = max(0.0, float(draw_length_mm)) / 1000.0
    wear_add = draw_m * max(0.0, float(backend.PENCIL_WEAR_MM_PER_M))
    state["total_draw_m"] = float(state.get("total_draw_m", 0.0) or 0.0) + draw_m
    state["estimated_wear_mm"] = float(state.get("estimated_wear_mm", 0.0) or 0.0) + wear_add
    state["jobs_done"] = int(state.get("jobs_done", 0) or 0) + 1
    state["last_draw_m"] = draw_m
    return state
