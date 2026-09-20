Write-Host "Building geo..."
.venv\Scripts\python scripts\build_geo.py
Write-Host "Building features..."
.venv\Scripts\python scripts\build_features.py
Write-Host "Making mock forecast..."
.venv\Scripts\python scripts\make_mock_forecast.py
Write-Host "Splitting forecast..."
.venv\Scripts\python scripts\split_forecast.py
Write-Host "Installing web dependencies..."
cd web
npm install
Write-Host "All build steps finished."
