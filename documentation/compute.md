# Compute and quota notes (Day 6)

Fill from the Cloud console after creating the project.

| item | value | date checked |
|---|---|---|
| Cloud project id | `vista-sindh` | 2026-11-01 |
| Earth Engine registration (noncommercial) | REGISTERED_NOT_COMMERCIALLY (getProjectConfig); compute OK; asset root writable since 2026-11-01 ~23:35 (404 before first Code Editor visit); exports go to the Drive of the EE login account | 2026-11-01 |
| Quota tier / concurrent batch tasks | noncommercial batch: at most 1 task observed RUNNING at a time over 350 operations | 2026-11-11 |
| EECU throughput | about 1.9 EECU-hours per wall hour (pilot wave 2: 157 EECU-h in 83 h); per-product costs in compute_budget.md | 2026-11-11 |
| Drive free space | | |
| Local disk free (C:) | 12 GB on 2026-11-11 (was 2-3 GB on 2026-11-01) | 2026-11-11 |
| GPU (Colab/Kaggle/local) | | |

Throttle: `gee.max_queued_tasks` in configs/gee.yaml (set to 300). Record EECU time per task from the
task list (Day 28) to calibrate later batches.
