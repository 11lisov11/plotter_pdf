# Plotter Studio Release Checklist

Updated: 2026-03-04

## 1. Scope and version

- [ ] Target version selected (`vX.Y.Z`).
- [ ] Release type identified:
  - [ ] patch (`X.Y.Z+1`) for fixes only;
  - [ ] minor (`X.Y+1.0`) for backward-compatible features;
  - [ ] major (`X+1.0.0`) for breaking changes.
- [ ] Changelog draft prepared from merged PRs.

## 2. Branch and tag hygiene

- [ ] `main` is green in CI.
- [ ] No unreviewed hotfix commits after the last approved PR.
- [ ] Release commit hash captured.
- [ ] Annotated git tag created (`vX.Y.Z`).

## 3. Quality gates (must pass)

- [ ] `lint` job passed.
- [ ] `tests` job passed (`unittest + pytest`).
- [ ] `coverage-report` job passed.
- [ ] `build-smoke-windows` job passed.

Local verification commands:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

## 4. Packaging and artifacts

- [ ] `dist\PlotterStudio.exe` exists.
- [ ] `dist\PlotterStudio-portable.zip` exists.
- [ ] Checksums generated (SHA256) and attached to release notes.
- [ ] Artifact retention policy verified:
  - [ ] PR artifacts 7 days;
  - [ ] release artifacts 90 days.

## 5. Functional verification

- [ ] Smoke run on clean Windows VM/host:
  - [ ] app starts;
  - [ ] settings panel opens;
  - [ ] preview for sample SVG works;
  - [ ] dry-run output G-code file created.
- [ ] Office/CAD conditional flows verified when available:
  - [ ] DOCX conversion path;
  - [ ] FRW/CDW conversion path or fallback.

## 6. Hardware protocol (release candidate required)

- [ ] M6 hardware matrix completed:
  - [ ] HW-001 connect/disconnect cycles;
  - [ ] HW-002 bounds frame;
  - [ ] HW-003 corner calibration repeatability;
  - [ ] HW-004 emergency stop;
  - [ ] HW-005 resume behavior;
  - [ ] HW-006 DOCX handwriting run;
  - [ ] HW-007 exact geometry run;
  - [ ] HW-008 60+ min soak.
- [ ] No out-of-bounds movement observed.
- [ ] No unhandled crash during protocol.

## 7. Release notes and communication

- [ ] `RELEASE_NOTES_TEMPLATE.md` filled for this version.
- [ ] Known issues section updated.
- [ ] Upgrade and rollback instructions included.

## 8. Rollback readiness

- [ ] Previous stable executable archived.
- [ ] Previous known-good `config\axis_profile.json` snapshot archived.
- [ ] Rollback owner assigned.
- [ ] Rollback dry-run tested (target < 15 min).

