# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/acies-modern-logo.png', 'assets'), ('modern-workspace.css', '.'), ('deliverables-workspace.css', '.'), ('industry.css', '.'), ('industry-projects.js', '.'), ('industry-shell.js', '.'), ('VERSION', '.'), ('index.html', '.'), ('app-bootstrap.js', '.'), ('styles.css', '.'), ('script.js', '.'), ('symbol_counter.css', '.'), ('symbol_counter_ui.js', '.'), ('vendor/chart.umd.min.js', 'vendor'), ('.env', '.'), ('assets\\acies.png', 'assets'), ('assets\\lighting', 'assets\\lighting'), ('scripts\\merge_pdfs.py', 'scripts'), ('scripts\\shrink_pdf.py', 'scripts'), ('scripts\\strip_pdf_layers.py', 'scripts'), ('scripts\\detect_pdf_size.py', 'scripts'), ('scripts\\PlotDWGs.ps1', 'scripts'), ('scripts\\ManageLayersDWGs.ps1', 'scripts'), ('scripts\\ManageXrefPathsDWGs.ps1', 'scripts'), ('scripts\\ListDwgXrefs.ps1', 'scripts'), ('scripts\\AutoCadDiscovery.ps1', 'scripts'), ('scripts\\removeXREFPaths.ps1', 'scripts'), ('scripts\\StripRefPaths.dll', 'scripts'), ('scripts/PrepareXrefs-bin', 'scripts/PrepareXrefs-bin'), ('templates', 'templates'), ('CircuitBreakerAI\\ElectricalPanels\\Template.xlsx', 'CircuitBreakerAI\\ElectricalPanels'), ('WireSizerApplication\\\\dist', 'WireSizerApplication\\\\dist'), ('project-pages-editor\\\\dist', 'project-pages-editor\\\\dist')],
    hiddenimports=['pillow_heif', '_pillow_heif'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ACIES Scheduler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\acies.ico'],
)

# Console helper the CAD scripts run in place of a system Python (see
# scripts/pdf_helper_runner.py). It has to be a console program so PowerShell can
# wait for it and read its output.
helper_a = Analysis(
    ['scripts/pdf_helper_runner.py'],
    pathex=['scripts'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
helper_pyz = PYZ(helper_a.pure)
helper_exe = EXE(
    helper_pyz,
    helper_a.scripts,
    [],
    exclude_binaries=True,
    name='acies-pdf-tools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\acies.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    helper_exe,
    helper_a.binaries,
    helper_a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ACIES Scheduler',
)
