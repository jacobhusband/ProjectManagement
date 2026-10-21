import React, { useMemo, useState } from 'react';
import { Zap, Copy, CheckCircle2, AlertTriangle, Info } from 'lucide-react';
import { AppState } from './types';
import { calculateEverything, formatFeederSpec, formatShorthandSpec, formatWireSize, getHotCount, isThreePhaseAllowed, neutralMustCarryCurrent, validateInputs } from './utils/electricalMath';
import { WIRE_DATA, MIN_RECOMMENDED_CONDUCTOR_SIZE } from './constants';

const inputClass = 'w-full p-2.5 border border-gray-300 rounded-lg bg-white text-slate-900 focus:ring-2 focus:ring-blue-500 disabled:bg-slate-100 disabled:text-slate-400';
const sizes = WIRE_DATA.filter(w => w.circularMils >= WIRE_DATA.find(w => w.size === MIN_RECOMMENDED_CONDUCTOR_SIZE)!.circularMils);
const initialState: AppState = {
  voltage: 208, phase: 3, amperage: 20, continuousAmperage: 0, breakerAmperage: 20,
  distance: 100, material: 'Copper', groundMaterial: 'Copper', maxVoltageDrop: 3,
  sets: 1, forceSets: false, forceWireSize: false, forcedWireSize: '12',
  terminalRating: 60, ambientTemperature: 30, neutralMode: 'full', neutralSize: '12',
  neutralDesignAmperage: 20, neutralCurrentCarrying: true, oversizeConduit: false,
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm text-slate-700"><span className="block mb-1.5 font-medium">{label}</span>{children}</label>;
}

export default function App() {
  const [state, setState] = useState<AppState>(initialState);
  const [copyFeedback, setCopyFeedback] = useState('');
  const errors = useMemo(() => validateInputs(state), [state]);
  // Derive synchronously so the copy button never sees results from a previous input state.
  const result = useMemo(() => errors.length ? null : calculateEverything(state), [state, errors]);
  const change = <K extends keyof AppState>(key: K, value: AppState[K]) => {
    setCopyFeedback('');
    setState(prev => {
      const next = { ...prev, [key]: value };
      if (!isThreePhaseAllowed(next.voltage)) {
        next.phase = 1;
        if (next.neutralMode === 'none') next.neutralMode = 'full';
      }
      return next;
    });
  };
  const numeric = (key: 'amperage' | 'continuousAmperage' | 'breakerAmperage' | 'distance' | 'maxVoltageDrop' | 'sets' | 'ambientTemperature' | 'neutralDesignAmperage', label: string, min: number, max: number, step = 'any') =>
    <Field label={label}><input type="number" className={inputClass} value={state[key]} min={min} max={max} step={step} onChange={e => change(key, e.target.value === '' ? '' : Number(e.target.value))} /></Field>;
  const wireOptions = sizes.map(w => <option key={w.size} value={w.size}>{formatWireSize(w.size)}</option>);
  const copy = async (shorthand = false) => {
    if (!result?.valid) return;
    try {
      await navigator.clipboard.writeText(shorthand ? formatShorthandSpec(state, result) : formatFeederSpec(state, result));
      setCopyFeedback(shorthand ? 'Shorthand copied!' : 'Copied!');
    } catch {
      setCopyFeedback('Clipboard unavailable. Select and copy the specification below.');
    }
  };
  const fmt = (value: number, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : 'Unresolved';
  const hotCount = getHotCount(state.phase, state.voltage);

  return <div className="min-h-screen bg-slate-50 text-slate-900 pb-8">
    <header className="bg-white border-b sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-5 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3"><div className="bg-blue-600 rounded-lg p-2"><Zap className="text-white" size={22} /></div><div><h1 className="text-lg font-bold">ACIES Wire Sizer</h1><p className="text-xs text-slate-500">Feeder sizing & voltage drop</p></div></div>
        <div className="flex items-center gap-2">
          <button onClick={() => copy(true)} disabled={!result?.valid} title={result?.valid ? formatShorthandSpec(state, result) : undefined} className="flex items-center gap-2 px-4 py-2 border rounded-lg text-sm font-semibold bg-white disabled:opacity-40 disabled:cursor-not-allowed">{copyFeedback === 'Shorthand copied!' ? <CheckCircle2 size={16} /> : <Copy size={16} />}{copyFeedback === 'Shorthand copied!' ? 'Copied!' : 'Copy Shorthand'}</button>
          <button onClick={() => copy()} disabled={!result?.valid} className="flex items-center gap-2 px-4 py-2 border rounded-lg text-sm font-semibold bg-white disabled:opacity-40 disabled:cursor-not-allowed">{copyFeedback === 'Copied!' ? <CheckCircle2 size={16} /> : <Copy size={16} />}{copyFeedback === 'Copied!' ? 'Copied!' : 'Copy Spec'}</button>
        </div>
      </div>
    </header>
    <main className="max-w-7xl mx-auto p-5 grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
      <section aria-label="Circuit configuration" className="lg:col-span-5 bg-white border rounded-xl p-5 space-y-5">
        <h2 className="font-semibold">Circuit configuration</h2>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Phase"><select className={inputClass} value={state.phase} onChange={e => change('phase', Number(e.target.value) as 1 | 3)}><option value={1}>1 phase</option><option value={3} disabled={!isThreePhaseAllowed(state.voltage)}>3 phase</option></select></Field>
          <Field label="Voltage"><select className={inputClass} value={state.voltage} onChange={e => change('voltage', Number(e.target.value))}>{[120, 208, 240, 277, 480].map(v => <option key={v} value={v}>{v} V</option>)}</select></Field>
          {numeric('amperage', 'Total operating load (A)', 0.01, 100000)}
          {numeric('continuousAmperage', 'Continuous portion (A)', 0, 100000)}
          {numeric('breakerAmperage', 'Breaker / fuse rating (A)', 1, 100000, '1')}
          {numeric('distance', 'One-way length (ft)', 0, 1000000)}
        </div>
        <p className="text-xs text-slate-500">Design load = operating load + 25% of its continuous portion. Voltage drop uses operating load. Enter the actual protective-device rating.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Phase / neutral material"><select className={inputClass} value={state.material} onChange={e => change('material', e.target.value as AppState['material'])}><option>Copper</option><option>Aluminum</option></select></Field>
          <Field label="Lowest terminal rating"><select className={inputClass} value={state.terminalRating} onChange={e => change('terminalRating', Number(e.target.value) as 60 | 75)}><option value={60}>60°C</option><option value={75}>75°C (marked equipment)</option></select></Field>
          {numeric('maxVoltageDrop', 'Voltage-drop target (%)', 0.1, 100)}
          {numeric('ambientTemperature', 'Ambient temperature (°C)', 10, 80)}
        </div>
        <div className="border-t pt-4 space-y-3">
          <h3 className="text-sm font-semibold">Neutral & grounding</h3>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Neutral"><select className={inputClass} value={state.neutralMode} onChange={e => change('neutralMode', e.target.value as AppState['neutralMode'])}><option value="none" disabled={hotCount === 1}>None (line-to-line load)</option><option value="full">Full size</option><option value="custom">Specified size</option></select></Field>
            <Field label="Equipment ground material"><select className={inputClass} value={state.groundMaterial} onChange={e => change('groundMaterial', e.target.value as AppState['groundMaterial'])}><option>Copper</option><option>Aluminum</option></select></Field>
            {state.neutralMode === 'custom' && <><Field label="Neutral size"><select className={inputClass} value={state.neutralSize} onChange={e => change('neutralSize', e.target.value)}>{wireOptions}</select></Field>{numeric('neutralDesignAmperage', 'Calculated neutral load (A)', 0, 100000)}</>}
          </div>
          {state.neutralMode === 'custom' && <p className="text-xs text-slate-500">Neutral load must include continuous-load allowance and applicable imbalance / harmonics. L-N circuits are also checked against the full circuit requirement.</p>}
          {state.neutralMode !== 'none' && <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={neutralMustCarryCurrent(state) || state.neutralCurrentCarrying} disabled={neutralMustCarryCurrent(state)} onChange={e => change('neutralCurrentCarrying', e.target.checked)} /><span>Count neutral as current carrying<span className="block text-xs text-slate-500">Required for L-N and two phases of a wye system. Leave checked for nonlinear loads; exclude only an eligible imbalance-only neutral.</span></span></label>}
        </div>
        <details className="border-t pt-4">
          <summary className="cursor-pointer text-sm font-semibold">Parallel sets & overrides</summary>
          <div className="mt-4 space-y-3">
            {numeric('sets', 'Minimum parallel sets (separate raceways)', 1, 10, '1')}
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={state.forceSets} onChange={e => change('forceSets', e.target.checked)} />Use exactly this many sets</label>
            <p className="text-xs text-slate-500">One complete circuit and one EGC per raceway. General parallel minimum: 1/0 AWG. Automatic sizing caps at 600 kcmil Cu / 750 kcmil Al; exact sets permit up to 2000 kcmil.</p>
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={state.forceWireSize} onChange={e => { const checked = e.target.checked; setCopyFeedback(''); setState(prev => ({ ...prev, forceWireSize: checked, forcedWireSize: checked ? result?.selectedSize ?? prev.forcedWireSize : prev.forcedWireSize })); }} />Check a specified phase wire size</label>
            <Field label="Phase wire override"><select className={inputClass} disabled={!state.forceWireSize} value={state.forceWireSize ? state.forcedWireSize : result?.selectedSize ?? state.forcedWireSize} onChange={e => change('forcedWireSize', e.target.value)}>{wireOptions}</select></Field>
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={state.oversizeConduit} onChange={e => change('oversizeConduit', e.target.checked)} />Increase EMT by one trade size when available</label>
          </div>
        </details>
      </section>
      <section aria-label="Sizing results" className="lg:col-span-7 space-y-4 lg:sticky lg:top-24">
        {errors.length > 0 && <div role="alert" className="bg-amber-50 border border-amber-300 p-5 rounded-xl"><h2 className="font-semibold mb-2">Complete the inputs</h2><ul className="list-disc pl-5 text-sm space-y-1">{errors.map(e => <li key={e}>{e}</li>)}</ul></div>}
        {result && <>
          <div className="bg-white border rounded-xl p-5 shadow-sm space-y-5">
            <div className="flex flex-wrap justify-between items-start gap-3">
              <div><p className="text-xs uppercase tracking-wide text-slate-500">{result.valid ? 'Feeder specification' : 'Candidate — corrections required'}</p><h2 className="text-3xl font-bold mt-1">{result.sets > 1 ? `${result.sets} × ` : ''}{formatWireSize(result.selectedSize)}</h2><p className="text-sm text-slate-500 mt-1">{state.material} THHN/THWN-2 · {state.terminalRating}°C terminals</p></div>
              <span className={`text-xs rounded-full px-3 py-1 font-semibold ${result.valid ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-900'}`}>{result.valid ? 'Within modeled limits' : 'Spec unavailable'}</span>
            </div>
            {result.warnings.length > 0 && <div role="alert" className="bg-amber-50 border border-amber-200 rounded-lg p-3"><div className="flex gap-2 items-center font-semibold text-sm text-amber-900"><AlertTriangle size={18} />Resolve before use</div><ul className="list-disc pl-5 mt-2 space-y-1 text-sm text-amber-900">{result.warnings.map(w => <li key={w}>{w}</li>)}</ul></div>}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
              <div className="bg-slate-50 p-3 rounded-lg"><p className="text-xs text-slate-500 mb-1">EGC · {state.groundMaterial}</p><strong>{result.groundWireSize === 'Unresolved' ? 'Unresolved' : formatWireSize(result.groundWireSize)}</strong><p className="text-xs text-slate-500">One per raceway</p></div>
              <div className="bg-slate-50 p-3 rounded-lg"><p className="text-xs text-slate-500 mb-1">Neutral</p><strong>{result.neutralSize ? formatWireSize(result.neutralSize) : 'None'}</strong></div>
              <div className="bg-blue-50 p-3 rounded-lg"><p className="text-xs text-slate-500 mb-1">EMT · per raceway</p><strong>{result.conduitSize ? `${result.conduitSize}″` : 'No valid size'}</strong></div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><div className="flex justify-between text-sm mb-2"><span>Voltage drop</span><strong className={result.voltageDropPercentage <= Number(state.maxVoltageDrop) ? 'text-green-700' : 'text-red-700'}>{fmt(result.voltageDropPercentage, 2)}%</strong></div><div className="h-1.5 bg-slate-100 rounded-full"><div className={`h-1.5 rounded-full ${result.voltageDropPercentage <= Number(state.maxVoltageDrop) ? 'bg-green-500' : 'bg-red-500'}`} style={{ width: `${Math.min(100, result.voltageDropPercentage / Number(state.maxVoltageDrop) * 100)}%` }} /></div><p className="text-xs text-slate-500 mt-2">Target {state.maxVoltageDrop}% · At load {fmt(result.voltageAtLoad)} V<br />{hotCount === 1 ? 'L-N with actual neutral resistance' : 'Balanced L-L approximation'}</p></div>
              <div><div className="flex justify-between text-sm mb-2"><span>Conduit fill</span><strong className={result.conduitFillPercentage <= 40 ? 'text-blue-700' : 'text-red-700'}>{fmt(result.conduitFillPercentage)}{Number.isFinite(result.conduitFillPercentage) ? '%' : ''}</strong></div><div className="h-1.5 bg-slate-100 rounded-full"><div className={`h-1.5 rounded-full ${result.conduitFillPercentage <= 40 ? 'bg-blue-500' : 'bg-red-500'}`} style={{ width: `${Number.isFinite(result.conduitFillPercentage) ? Math.min(100, result.conduitFillPercentage / 40 * 100) : 0}%` }} /></div><p className="text-xs text-slate-500 mt-2">40% limit · {fmt(result.wireAreaTotal, 3)} sq.in<br />{result.conduitSize ? 'Per raceway, including insulated EGC' : 'Largest supported EMT checked: 4″'}</p></div>
            </div>
          </div>
          <div className="bg-white border rounded-xl p-5">
            <h3 className="font-semibold text-sm mb-3">Calculation breakdown</h3>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <dt className="text-slate-500">Operating / design load</dt><dd>{fmt(result.operatingAmps)} / {fmt(result.designAmps)} A</dd>
              <dt className="text-slate-500">Available total ampacity</dt><dd>{fmt(result.actualAmpacity)} A</dd>
              <dt className="text-slate-500">Minimum for load & breaker</dt><dd>{result.ampacityMinimum ? formatWireSize(result.ampacityMinimum) : 'No supported size'}</dd>
              <dt className="text-slate-500">Minimum for voltage drop</dt><dd>{result.voltageDropMinimum ? formatWireSize(result.voltageDropMinimum) : 'No supported size'}</dd>
              <dt className="text-slate-500">Temperature × count factors</dt><dd>{result.temperatureFactor} × {result.adjustmentFactor} ({result.currentCarryingCount} CCC)</dd>
              <dt className="text-slate-500">EGC circular-mil multiplier</dt><dd>{fmt(result.groundUpsizeRatio, 2)} ×</dd>
              <dt className="text-slate-500">Maximum length at target</dt><dd>{fmt(result.maxDistanceAtTarget, 0)} ft</dd>
              <dt className="text-slate-500">Suggested automatic sets</dt><dd>{result.recommendedSets || 'No supported solution'}</dd>
            </dl>
            <p className="text-xs text-slate-500 mt-3">Minimum sizes are per set. Selection meets both ampacity and voltage drop, subject to overrides. Ampacity is limited by the terminal rating, adjusted 90°C insulation ampacity, and small-conductor protection rules.</p>
          </div>
          <details className="bg-white border rounded-xl p-4 text-sm"><summary className="cursor-pointer font-semibold">Grounding electrode reference — separate from feeder EGC</summary><p className="text-slate-600 mt-2">Table 250.66 reference: {formatWireSize(result.gecWireSize)} {state.groundMaterial}, based on the equivalent phase conductor area across all sets. This is not included in the feeder specification or conduit fill. Electrode-specific limits, service bonding and installation requirements need separate selection.</p></details>
          {result.valid && <details className="bg-white border rounded-xl p-4"><summary className="cursor-pointer text-sm font-semibold">Specification preview</summary><pre className="whitespace-pre-wrap text-xs mt-3 select-text">{formatFeederSpec(state, result)}</pre></details>}
        </>}
        <p role="status" className="text-sm text-blue-700">{copyFeedback}</p>
        <div className="flex gap-2 text-xs text-slate-500 bg-white border rounded-xl p-4"><Info size={16} className="shrink-0" /><p>NEC 2023 table-based general-purpose model: THHN/THWN-2, one complete circuit per EMT raceway, no additional circuits or bundled raceways. 3% voltage drop is a design target, not a universal code limit. The resistance approximation excludes reactance and load imbalance. No next-size OCPD, motor, transformer, service or other special exceptions are applied.</p></div>
      </section>
    </main>
  </div>;
}
