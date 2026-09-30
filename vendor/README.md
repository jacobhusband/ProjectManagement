# Vendored third-party files

These files are served from the app itself so it never has to reach a CDN at runtime.

## chart.umd.min.js

- Chart.js 4.5.1, MIT licensed (license header kept in the file).
- Source: `https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js`
- SHA-384: `sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ`
  (this is the integrity value `index.html` pinned when the file was still loaded from
  the CDN)
- Loaded on demand by `loadChartJs()` in `script.js` the first time the Stats dialog opens.
- Packaged by both PyInstaller specs and checked by `build-config/build.ps1`.

To upgrade, download the new build, replace the file, update the version and hash above,
and bump the `?v=` in `CHART_JS_URL` in `script.js`. `tests/test_startup_performance.py`
compares the file's hash to the one recorded here.
