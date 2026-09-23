// Runs in <head> before the page renders. It lives in a file rather than an inline
// <script> so the Content-Security-Policy in index.html can refuse all inline script.
(function () {
    try {
        const stored = localStorage.getItem('acies-theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const theme = stored || (prefersDark ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', theme);
    } catch (e) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }

    // Keep anything the policy blocks until script.js can pass it to the app log.
    // Early violations (fonts, Chart.js) happen before the desktop bridge is ready.
    const collector = { pending: [], report: null };
    const seen = new Set();
    window.aciesCspViolations = collector;
    document.addEventListener('securitypolicyviolation', (event) => {
        const violation = {
            kind: 'csp-violation',
            directive: event.effectiveDirective || event.violatedDirective || '',
            blocked: event.blockedURI || '',
            source: event.sourceFile || '',
            line: event.lineNumber || 0,
            sample: event.sample || '',
        };
        const key = [violation.directive, violation.blocked, violation.source, violation.line].join('|');
        if (seen.has(key) || seen.size >= 50) return;
        seen.add(key);
        if (typeof collector.report === 'function') collector.report(violation);
        else collector.pending.push(violation);
    });
})();
