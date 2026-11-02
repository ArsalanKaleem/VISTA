# Smoke test (2026-11-01)

- Points: thar_mithi, badin_coast, dadu_canal, jacobabad, khairpur (1 km buffers)
- S2 NDVI monthly 2019-2024 -> `data\processed\smoke_s2_ndvi.csv`
- Climatology fitted on years < 2023 only (assertion passed)
- Climatology MAE on 2023-2024: 0.0321 (n = 120 point-months)
- Missing point-months (no valid S2): 0 of 360
