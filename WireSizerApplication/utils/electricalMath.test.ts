import { describe, expect, it } from 'vitest';
import { WIRE_DATA } from '../constants';
import { AppState } from '../types';
import { calculateEverything, formatFeederSpec, formatShorthandSpec, formatWireSize, validateInputs } from './electricalMath';

const createState = (overrides: Partial<AppState> = {}): AppState => ({
  voltage: 240, amperage: 90, continuousAmperage: 0, breakerAmperage: 90,
  distance: 50, phase: 1, material: 'Copper', groundMaterial: 'Copper', maxVoltageDrop: 3,
  sets: 1, forceSets: false, forceWireSize: false, forcedWireSize: '12',
  terminalRating: 60, ambientTemperature: 30, neutralMode: 'full', neutralSize: '12',
  neutralDesignAmperage: 20, neutralCurrentCarrying: true, oversizeConduit: false,
  ...overrides,
});
const cm = (size: string) => WIRE_DATA.find(w => w.size === size)!.circularMils;

describe('reference calculations', () => {
  it('reproduces the screenshot under its stated assumptions', () => {
    const r = calculateEverything(createState());
    expect(r.valid).toBe(true);
    expect(r.selectedSize).toBe('2');
    expect(r.actualAmpacity).toBe(95);
    expect(r.voltageDropPercentage).toBeCloseTo(0.7289783, 6);
    expect(r.groundWireSize).toBe('8');
    expect(r.conduitSize).toBe('1-1/4');
    expect(r.conduitFillPercentage).toBeCloseTo(25.6856187, 5);
  });
  it('uses marked terminals instead of conductor-size heuristics', () => {
    expect(calculateEverything(createState({ terminalRating: 75 })).selectedSize).toBe('3');
    const r = calculateEverything(createState({ amperage: 120, breakerAmperage: 120, terminalRating: 60 }));
    expect(r.selectedSize).toBe('1/0');
    expect(r.actualAmpacity).toBe(125);
    expect(r.tempRatingUsed).toBe(60);
  });
  it('ignores a wire override when it is disabled', () => {
    expect(calculateEverything(createState({ forcedWireSize: '2000' }))).toEqual(calculateEverything(createState()));
  });
  it('checks the actual forced wire for ampacity and voltage drop', () => {
    const r = calculateEverything(createState({ forceWireSize: true, forcedWireSize: '12', distance: 500 }));
    expect(r.valid).toBe(false);
    expect(r.warnings.join(' ')).toMatch(/ampacity/);
    expect(r.warnings.join(' ')).toMatch(/Voltage drop/);
  });
  it('keeps operating current separate from continuous-load sizing current', () => {
    const s = createState({ amperage: 40, breakerAmperage: 50, forceWireSize: true, forcedWireSize: '6' });
    const a = calculateEverything(s);
    const b = calculateEverything({ ...s, continuousAmperage: 40 });
    expect(b.operatingAmps).toBe(40);
    expect(b.designAmps).toBe(50);
    expect(b.voltageDrop).toBe(a.voltageDrop);
    expect(b.valid).toBe(true);
  });
  it('rejects a breaker smaller than the continuous-load requirement', () => {
    const r = calculateEverything(createState({ continuousAmperage: 90 }));
    expect(r.valid).toBe(false);
    expect(r.warnings.join(' ')).toMatch(/Breaker.*below/);
  });
  it('retains small-conductor protection caps at 75°C', () => {
    const r = calculateEverything(createState({ amperage: 25, breakerAmperage: 25, distance: 0, terminalRating: 75 }));
    expect(r.selectedSize).toBe('10');
    const al = calculateEverything(createState({ amperage: 20, breakerAmperage: 20, distance: 0, terminalRating: 75, material: 'Aluminum' }));
    expect(al.selectedSize).toBe('10');
  });
});

describe('failure handling and parallel sizing', () => {
  it('enforces the general parallel minimum for automatic and exact sets', () => {
    for (const forceSets of [false, true]) {
      const r = calculateEverything(createState({ amperage: 40, breakerAmperage: 40, sets: 2, forceSets }));
      expect(r.selectedSize).toBe('1/0');
      expect(r.sets).toBe(2);
      expect(r.valid).toBe(true);
    }
  });
  it('flags explicitly forced parallel conductors below 1/0', () => {
    const r = calculateEverything(createState({ amperage: 40, breakerAmperage: 40, sets: 2, forceWireSize: true, forcedWireSize: '12' }));
    expect(r.valid).toBe(false);
    expect(r.warnings.join(' ')).toMatch(/Parallel phase/);
  });
  it('reports the original forced-set overload and conduit overflow', () => {
    const r = calculateEverything(createState({ amperage: 1000, breakerAmperage: 1000, terminalRating: 75, forceSets: true }));
    expect(r.actualAmpacity).toBe(665);
    expect(r.valid).toBe(false);
    expect(r.conduitFillPercentage).toBeGreaterThan(40);
    expect(r.conduitSize).toBe('');
    expect(r.warnings.join(' ')).toMatch(/No valid conductor solution/);
    expect(r.warnings.join(' ')).toMatch(/fill exceeds/);
  });
  it('reports automatic search exhaustion and unresolved ground without inventing fill', () => {
    const r = calculateEverything(createState({ amperage: 5000, breakerAmperage: 5000, terminalRating: 75 }));
    expect(r.valid).toBe(false);
    expect(r.recommendedSets).toBe(0);
    expect(r.groundWireSize).toBe('Unresolved');
    expect(Number.isNaN(r.conduitFillPercentage)).toBe(true);
    expect(r.conduitSize).toBe('');
  });
  it('flags voltage-drop failure when exact sets exhaust the table', () => {
    const r = calculateEverything(createState({ forceSets: true, distance: 1000000 }));
    expect(r.valid).toBe(false);
    expect(r.warnings.join(' ')).toMatch(/Voltage drop/);
  });
  it('does not apply conduit oversizing past the maximum supported size', () => {
    const r = calculateEverything(createState({ forceWireSize: true, forcedWireSize: '2000', oversizeConduit: true }));
    expect(r.valid).toBe(false);
    expect(r.conduitSize).toBe('');
  });
});

describe('grounding and neutral', () => {
  it('sizes the EGC from the breaker, independently of phase material', () => {
    const r = calculateEverything(createState({ amperage: 90, breakerAmperage: 125, material: 'Aluminum', groundMaterial: 'Copper' }));
    expect(r.groundWireSize).toBe('6');
    expect(r.valid).toBe(true);
  });
  it('increases the EGC proportionally for a long run', () => {
    const r = calculateEverything(createState({ voltage: 120, amperage: 20, breakerAmperage: 20, distance: 1000 }));
    expect(r.selectedSize).toBe('3/0');
    expect(r.ampacityMinimum).toBe('12');
    expect(r.groundUpsizeRatio).toBeCloseTo(cm('3/0') / cm('12'));
    expect(r.groundWireSize).toBe('3/0');
    expect(r.valid).toBe(true);
  });
  it('also increases the EGC for a manually upsized conductor', () => {
    const r = calculateEverything(createState({ forceWireSize: true, forcedWireSize: '1/0' }));
    // 16,510 × 105,600 / 66,360 = 26,272 cmil: just above #6 (26,240).
    expect(r.groundWireSize).toBe('4');
    expect(r.groundUpsizeRatio).toBeCloseTo(cm('1/0') / cm('2'));
  });
  it('removes neutral area and neutral text from a line-to-line circuit', () => {
    const full = calculateEverything(createState());
    const s = createState({ neutralMode: 'none' });
    const none = calculateEverything(s);
    expect(none.neutralSize).toBeNull();
    expect(full.wireAreaTotal - none.wireAreaTotal).toBeCloseTo(0.1158);
    expect(formatFeederSpec(s, none)).not.toMatch(/ AWG N/);
  });
  it('uses actual neutral resistance for line-to-neutral voltage drop', () => {
    const s = createState({ voltage: 120, amperage: 20, breakerAmperage: 20, forceWireSize: true, forcedWireSize: '6', neutralMode: 'custom', neutralSize: '12', distance: 50 });
    const r = calculateEverything(s);
    expect(r.voltageDrop).toBeCloseTo(12.9 * 20 * 50 * (1 / 26240 + 1 / 6530));
  });
  it('checks neutral capacity against actual L-N load even if a lower load is entered', () => {
    const r = calculateEverything(createState({ voltage: 120, neutralMode: 'custom', neutralSize: '12', neutralDesignAmperage: 1 }));
    expect(r.warnings.join(' ')).toMatch(/Neutral ampacity/);
  });
  it('checks the minimum size for a parallel neutral', () => {
    const r = calculateEverything(createState({ sets: 2, neutralMode: 'custom', neutralSize: '12' }));
    expect(r.warnings.join(' ')).toMatch(/Parallel neutral/);
  });
  it('checks the grounding-based neutral floor even when load ampacity is sufficient', () => {
    const r = calculateEverything(createState({ amperage: 200, breakerAmperage: 250, terminalRating: 75, neutralMode: 'custom', neutralSize: '8', neutralDesignAmperage: 20 }));
    expect(r.valid).toBe(false);
    expect(r.warnings.join(' ')).toMatch(/grounding-based feeder minimum/);
  });
  it('keeps GEC as a separate reference and uses the chosen grounding material', () => {
    const r = calculateEverything(createState({ forceWireSize: true, forcedWireSize: '350', groundMaterial: 'Aluminum' }));
    expect(r.gecWireSize).toBe('1/0');
    expect(r.groundWireSize).not.toBe(r.gecWireSize);
  });
});

describe('derating', () => {
  it('applies 90°C temperature correction then caps at the terminal ampacity', () => {
    const r = calculateEverything(createState({ amperage: 40, breakerAmperage: 40, forceWireSize: true, forcedWireSize: '6', ambientTemperature: 60, terminalRating: 75 }));
    expect(r.temperatureFactor).toBe(0.71);
    expect(r.actualAmpacity).toBeCloseTo(75 * 0.71);
    const cool = calculateEverything(createState({ amperage: 40, breakerAmperage: 40, forceWireSize: true, forcedWireSize: '6', ambientTemperature: 10, terminalRating: 60 }));
    expect(cool.actualAmpacity).toBe(55);
  });
  it('counts a nonlinear three-phase neutral for 80% adjustment', () => {
    const s = createState({ voltage: 208, phase: 3, amperage: 80, breakerAmperage: 80, terminalRating: 75, forceWireSize: true, forcedWireSize: '3' });
    const r = calculateEverything(s);
    expect(r.currentCarryingCount).toBe(4);
    expect(r.adjustmentFactor).toBe(0.8);
    expect(r.actualAmpacity).toBe(92);
    expect(calculateEverything({ ...s, neutralCurrentCarrying: false }).actualAmpacity).toBe(100);
  });
  it('always counts a two-phase wye neutral even if the checkbox is false', () => {
    const r = calculateEverything(createState({ voltage: 208, neutralCurrentCarrying: false }));
    expect(r.currentCarryingCount).toBe(3);
  });
});

describe('input validation and specifications', () => {
  it.each([
    { amperage: -20 }, { amperage: '' }, { amperage: NaN }, { distance: -1 },
    { maxVoltageDrop: 0 }, { maxVoltageDrop: Infinity }, { sets: 1.5 }, { sets: 0 }, { sets: 11 },
    { breakerAmperage: '' }, { continuousAmperage: 100 }, { ambientTemperature: 81 },
    { voltage: 120, neutralMode: 'none' }, { voltage: 277, phase: 3 },
    { forceWireSize: true, forcedWireSize: 'not-a-size' },
  ] as Partial<AppState>[])('suppresses calculation for invalid state %j', overrides => {
    const s = createState(overrides);
    expect(validateInputs(s).length).toBeGreaterThan(0);
    expect(() => calculateEverything(s)).toThrow(RangeError);
  });
  it('supports zero length with finite maximum-distance output', () => {
    const r = calculateEverything(createState({ distance: 0 }));
    expect(r.voltageDrop).toBe(0);
    expect(Number.isFinite(r.maxDistanceAtTarget)).toBe(true);
  });
  it('computes maximum length using the selected target', () => {
    const a = calculateEverything(createState({ forceWireSize: true, forcedWireSize: '2', maxVoltageDrop: 2 }));
    const b = calculateEverything(createState({ forceWireSize: true, forcedWireSize: '2', maxVoltageDrop: 4 }));
    expect(b.maxDistanceAtTarget).toBeCloseTo(a.maxDistanceAtTarget * 2);
  });
  it('refuses to format a failed calculation', () => {
    const s = createState({ forceWireSize: true, forcedWireSize: '12' });
    expect(() => formatFeederSpec(s, calculateEverything(s))).toThrow(/Resolve/);
  });
  it('copies selected conductors with material, raceway, EGC and assumptions', () => {
    const s = createState({ forceWireSize: true, forcedWireSize: '250', sets: 2 });
    const r = calculateEverything(s);
    expect(r.valid).toBe(true);
    const spec = formatFeederSpec(s, r);
    expect(spec).toContain('2 raceways; EACH:');
    expect(spec).toContain('250 kcmil H');
    expect(spec).toContain('Copper THHN/THWN-2');
    expect(spec).toContain('EMT');
    expect(spec).toContain('EGC');
    expect(spec).not.toContain('GEC');
    expect(spec).toContain('ONE-WAY LENGTH');
    expect(spec).toContain('OCPD: 90 A');
    expect(formatWireSize('4/0')).toBe('#4/0 AWG');
  });
  it('copies drawing shorthand for conduit, conductors and ground', () => {
    const s = createState({ forceWireSize: true, forcedWireSize: '3', terminalRating: 75 });
    const r = calculateEverything(s);
    expect(r.valid).toBe(true);
    expect(formatShorthandSpec(s, r)).toBe(`(N)${r.conduitSize}"C., 2#3 H, 1#3 N, 1#${r.groundWireSize} GND`);
  });
  it('marks parallel sets, kcmil, aluminum and omitted neutrals in shorthand', () => {
    const s = createState({ forceWireSize: true, forcedWireSize: '250', sets: 2, groundMaterial: 'Aluminum', neutralMode: 'none' });
    const r = calculateEverything(s);
    expect(r.valid).toBe(true);
    const shorthand = formatShorthandSpec(s, r);
    expect(shorthand).toMatch(/^\(2\) SETS OF \(N\)/);
    expect(shorthand).toContain('2#250 kcmil H');
    expect(shorthand).not.toContain(' N,');
    expect(shorthand).toMatch(/1#\S+ AL GND$/);
  });
  it('refuses to format shorthand for a failed calculation', () => {
    const s = createState({ forceWireSize: true, forcedWireSize: '12' });
    expect(() => formatShorthandSpec(s, calculateEverything(s))).toThrow(/Resolve/);
  });
});
