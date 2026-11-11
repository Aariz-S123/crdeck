"""Regenerate the illustrative site example; never reads or changes model exports."""
from pathlib import Path
import json
import numpy as np

def generate(out):
    rng = np.random.default_rng(20261110)
    t = np.arange(33) / 4
    center = np.array([8.4,8.9,9.6,10.1,10.6,10.9,11.1,11.2,11.3])
    half = np.array([0,.7,1.1,1.5,1.8,2.1,2.3,2.5,2.6])
    eta = rng.standard_normal((10000,33))
    z = np.zeros_like(eta)
    for k in range(1,33):
        z[:,k] = .75*z[:,k-1] + np.sqrt(1-.75**2)*eta[:,k]
    raw = np.interp(t,np.arange(9),center) + np.interp(t,np.arange(9),half)/1.2816*z
    raw[:,0] = 8.4
    paths = np.clip(raw,0,100)
    weekly = paths[:,::4]
    q = np.percentile(weekly,[5,10,25,50,75,90,95],axis=0)
    end = paths[:,-1]
    ordered = np.argsort(end)
    heroes = [int(ordered[int(p*9999)]) for p in [.1,.5,.9]]
    subset = heroes + [int(i) for i in rng.permutation(10000) if i not in heroes][:197]
    rng.shuffle(subset)
    hist, edges = np.histogram(end,np.arange(3.5,19.01,.5))
    density = np.array([np.histogram(weekly[:,i],np.arange(0,20.01,.25))[0]/2500 for i in range(9)])
    # Marching-square cell segments, linearly interpolated; no smoothed traces.
    floor = []
    for level in [.1,.2,.4,.8,1.6,3.2]:
        for w in range(8):
            for b in range(79):
                corners = [(w,b),(w+1,b),(w+1,b+1),(w,b+1)]
                cuts = []
                for j in range(4):
                    x,y = corners[j]
                    xx,yy = corners[(j+1)%4]
                    a,c = density[x,y],density[xx,yy]
                    if (a>=level)!=(c>=level):
                        f = (level-a)/(c-a)
                        cuts.append([x+(xx-x)*f,.125+.25*(y+(yy-y)*f)])
                if len(cuts)==2:
                    floor.append(cuts)
                elif len(cuts)==4:
                    if sum(density[x,y] for x,y in corners)/4>=level:
                        floor.extend([[cuts[0],cuts[3]],[cuts[1],cuts[2]]])
                    else:
                        floor.extend([[cuts[0],cuts[1]],[cuts[2],cuts[3]]])
    checks = {
        'median_weld_pp': float(np.max(np.abs(q[3]-center))),
        'endpoint_quantiles': np.percentile(end,[5,50,95]).tolist(),
        'above_12': int(np.sum(end>12)),
        'histogram_total': int(hist.sum()),
        'clip_touched': int(np.sum(raw!=paths)),
        'origin_all_equal': bool(np.all(paths[:,0]==8.4)),
        'density_peaks': density.max(axis=1).tolist(),
    }
    reference_hist = np.array([1,3,4,10,20,55,73,133,222,284,431,607,719,857,977,985,957,894,744,618,497,368,231,143,75,49,20,12,10,0,1])
    checks['histogram_matches_reference'] = bool(np.array_equal(hist,reference_hist))
    checks['band_containment'] = int(np.sum((end>=q[0,-1]) & (end<=q[6,-1])))
    checks['band_widths_pp'] = (q[6]-q[0]).tolist()
    checks['sqrt_week_comparison_pp'] = (np.sqrt(np.arange(9)/8)*(q[6,-1]-q[0,-1])).tolist()
    ranks = np.argsort(np.argsort(weekly[:,1:],axis=0),axis=0)
    correlations = [float(np.corrcoef(ranks[:,i],ranks[:,i+1])[0,1]) for i in range(7)]
    checks['adjacent_week_rank_correlations'] = correlations
    regions = np.sum(paths[heroes,::4,None] > q[[0,2,3,4,6]].T[None,:,:],axis=2)
    checks['hero_region_crossings'] = [int(np.sum(row[2:]!=row[1:-1])) for row in regions]
    signs = paths[subset,None,:]-paths[None,subset,:]
    checks['mean_pairwise_crossings_per_drawn_path'] = float(np.sum(signs[:,:,1:-1]*signs[:,:,2:]<0)/200)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    checks['rank_correlation_gate_passed'] = all(.30<c<.995 for c in correlations)
    checks['rank_correlation_resolution'] = 'User approved preserving pinned model and documenting threshold conflict on 2026-11-11'
    (out/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    assert checks['median_weld_pp'] <= .2, checks
    assert [f'{v:.1f}' for v in checks['endpoint_quantiles']] == ['8.0','11.3','14.6'], checks
    assert abs(checks['above_12']-3662)<=120 and round(checks['above_12']/100)==37, checks
    assert np.all(np.abs(q[1]-(center-half))<=.3) and np.all(np.abs(q[5]-(center+half))<=.3), checks
    assert hist.sum()==10000 and np.all(paths<=20) and np.all(paths>=0), checks
    assert checks['histogram_matches_reference'] and checks['band_containment']==9000, checks
    # User approved preserving the pinned model on 2026-11-11.
    if not checks['rank_correlation_gate_passed']:
        print('WARNING: weekly rank-correlation threshold conflicts with the pinned model; accepted and documented.')
    assert all(c>0 for c in checks['hero_region_crossings']), checks
    expected = np.array([4,.771,.467,.346,.283,.242,.224,.207,.210])
    assert np.all(np.abs(density.max(axis=1)/expected-1)<=.15), checks
    np.save(out/'futures-paths.npy',paths)
    payload = dict(seed=20261110,count=10000,center=center.tolist(),quantiles=q.tolist(),
        paths=paths[subset].round(6).tolist(),heroes=[subset.index(i) for i in heroes],
        density=density.tolist(),histogram=hist.tolist(),edges=edges.tolist(),checks=checks,
        above12=np.sum(weekly>12,axis=0).tolist(),contours=floor)
    (out/'futures-example.json').write_text(json.dumps(payload,separators=(',',':')),encoding='utf-8')
    (out/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))

if __name__=='__main__':
    import sys
    generate(sys.argv[1])
