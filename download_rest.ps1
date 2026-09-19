Write-Host "Running download_indices.py..."
.venv\Scripts\python scripts\download_indices.py
Write-Host "Running download_boundaries.py..."
.venv\Scripts\python scripts\download_boundaries.py
Write-Host "Running download_osm_names.py..."
.venv\Scripts\python scripts\download_osm_names.py
Write-Host "Running download_crida.py..."
.venv\Scripts\python scripts\download_crida.py
Write-Host "Running download_chirps.py (takes ~10 mins)..."
.venv\Scripts\python scripts\download_chirps.py
