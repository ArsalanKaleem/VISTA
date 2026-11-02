# Every result comes from a Makefile target (Day 7). Windows: use Git Bash or run the commands directly.
PY ?= python

data:            ## download small open reference data (PBS, geoBoundaries, GeoNames, HDX)
	$(PY) scripts/download_data.py
admin:           ## Sindh admin layers from geoBoundaries
	$(PY) scripts/prepare_admin.py
gee-check:       ## Day 6
	$(PY) -m gee.run check
gee-verify:      ## Day 8
	$(PY) -m gee.run verify-assets
gee-smoke:       ## Day 10
	$(PY) -m gee.run smoke5
gee-wave1:       ## tomorrow's batch
	$(PY) -m gee.run upload-admin && $(PY) -m gee.run wave 1
gee-status:
	$(PY) -m gee.run status
test:
	$(PY) -m pytest -q tests
