# Compute and quota notes (Day 6)

Fill from the Cloud console after creating the project.

| item | value | date checked |
|---|---|---|
| Cloud project id | `vista-sindh` | 2026-11-01 |
| Earth Engine registration (noncommercial) | REGISTERED_NOT_COMMERCIALLY (getProjectConfig); compute OK; asset root writable since 2026-11-01 ~23:35 (404 before first Code Editor visit); exports go to the Drive of the EE login account | 2026-11-01 |
| Quota tier / concurrent batch tasks | | |
| EECU-hours per month | | |
| Drive free space | | |
| Local disk free (C:) | ~2-3 GB on 2026-11-01: too small for footprints/OSM/torch | 2026-11-01 |
| GPU (Colab/Kaggle/local) | | |

Throttle: `gee.max_queued_tasks` in configs/gee.yaml (set to 300). Record EECU time per task from the
task list (Day 28) to calibrate later batches.
