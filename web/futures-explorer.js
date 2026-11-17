/* One illustrative array, three views. Real forecast exports remain untouched. */
(() => {
  'use strict';
  const C = { bg:'#0B0E13', ink:'#F2F5F7', muted:'#9AA7B4', grid:'#2A3240', blue:'#3E9BFF', center:'#EAF4FF', fill:'#16456B' };
  const fmt = (v) => `${v.toFixed(1)}%`;
  const text = (x,y,value,extra='') => `<text x="${x}" y="${y}" ${extra}>${value}</text>`;
  const line = (x,y,a,b,color=C.grid,width=1,extra='') => `<line x1="${x}" y1="${y}" x2="${a}" y2="${b}" stroke="${color}" stroke-width="${width}" ${extra}/>`;
  const points = (a) => a.map(p=>p.map(v=>v.toFixed(2)).join(',')).join(' ');
  const poly = (a,color,width,opacity=1,extra='') => `<polyline points="${points(a)}" fill="none" stroke="${color}" stroke-width="${width}" opacity="${opacity}" ${extra}/>`;
  function markup(realRuns) {
    return `<div class="futures-explorer" data-futures>
      <div class="futures-intro"><h3>An example with 10,000 runs (the real forecast uses ${realRuns ? realRuns.toLocaleString("en-US") : "fewer"})</h3><p>Start with a forecast. Sample possible paths around it. See where they finish.</p></div>
      <p class="futures-disclaimer">Model simulation: illustrative numbers. This eight-week example explains the mechanism; it is not a card's actual forecast or the production sampling method.</p>
      <div class="futures-toolbar"><div class="futures-views" role="group" aria-label="View the same simulated futures">
        <button type="button" data-futures-view="paths" aria-pressed="true">Paths</button><button type="button" data-futures-view="surface" aria-pressed="false">Density surface</button><button type="button" data-futures-view="endings" aria-pressed="false">Endings</button>
      </div><label class="futures-hero-control"><input type="checkbox" data-futures-heroes> Trace three futures</label></div>
      <div class="futures-stage" aria-busy="true" tabindex="0" role="region" aria-label="Simulation chart; scroll horizontally on small screens"><p role="status">Loading the verified simulation…</p></div>
      <p class="futures-scroll-hint">Scroll the chart sideways to explore it. The full numbers are in the table below.</p>
      <div class="futures-time"><label>Week <output data-futures-week>8</output> of 8<input type="range" min="0" max="8" step="1" value="8" data-futures-scrub aria-label="Forecast week"></label><label class="futures-orbit" hidden>Surface angle<input type="range" min="-65" max="-30" value="-52" data-futures-angle aria-label="Density surface viewing angle"></label></div>
      <p class="futures-explanation" data-futures-explanation></p>
      <dl class="futures-stats" aria-live="polite" aria-atomic="true"></dl>
      <details class="futures-method"><summary>Read the numbers and how this example is built</summary><p>TimesFM's illustrative median and per-week spread condition 10,000 samples. Quarter-week AR(1) noise (ρ = 0.75, seed 20261110) supplies temporal coupling. This is an educational construction, not the site's production logit-space, calibrated, cross-card sampler. Bands are pointwise percentiles, not individual paths or promises about actual usage.</p><p>All three views come from the same saved simulation. The 200 visible paths are a fixed sample; the three highlighted paths are selected by final endpoint rank (10th, 50th and 90th percentiles). Surface height is count ÷ (10,000 × 0.25 percentage points), with one global scale. The ridge marks the mode; the near-white floor trace is the median.</p><div class="futures-table"></div></details>
    </div>`;
  }
  async function mount(host) {
    const root = host.querySelector('[data-futures]');
    if (!root || root.dataset.mounted) return;
    root.dataset.mounted = 'true';
    let D;
    try {
      const response = await fetch('futures-example.json');
      if (!response.ok) throw new Error('Simulation unavailable');
      D = await response.json();
      if (D.count!==10000 || D.paths.length!==200 || D.quantiles.length!==7) throw new Error('Invalid simulation');
    } catch (_) {
      root.querySelector('.futures-stage').innerHTML = '<p role="status">The illustrative simulation could not load. <button type="button" data-futures-retry>Try again</button>. The real forecast charts below are still available.</p>';
      root.querySelector('.futures-stage').setAttribute('aria-busy','false');
      root.querySelector('[data-futures-retry]').onclick=()=>{ delete root.dataset.mounted; mount(host); };
      root.querySelectorAll('input, .futures-views button').forEach(b=>b.disabled=true);
      return;
    }
    root.querySelectorAll('input, .futures-views button').forEach(b=>b.disabled=false);
    let mode='paths', week=8, heroes=false, angle=-52;
    const X=w=>68+68*w, Y=s=>367-s*15.5;
    const q=D.quantiles;
    const band=(lo,hi)=>`<polygon points="${points([...Array.from({length:week+1},(_,w)=>[X(w),Y(q[hi][w])]),...Array.from({length:week+1},(_,i)=>[X(week-i),Y(q[lo][week-i])])])}" fill="${C.blue}" opacity="${lo===0?.12:.22}"/>`;
    const axes=()=>[0,5,10,15,20].map(s=>line(68,Y(s),645,Y(s))+text(55,Y(s)+4,`${s}%`,'text-anchor="end"')).join('')+
      Array.from({length:9},(_,w)=>text(X(w),393,w,'text-anchor="middle"')).join('')+text(68,36,'Usage share (%)')+text(612,420,'Week','text-anchor="end"');
    function fan(backdrop=false) {
      let g=axes()+band(0,6)+band(2,4);
      g+=D.paths.map(p=>poly(p.slice(0,week*4+1).map((s,k)=>[X(k/4),Y(s)]),C.blue,2,backdrop?.04:.08)).join('');
      g+=poly(D.center.slice(0,week+1).map((s,w)=>[X(w),Y(s)]),C.center,2,1,'stroke-dasharray="6 5"');
      g+=poly(q[3].slice(0,week+1).map((s,w)=>[X(w),Y(s)]),C.center,3,backdrop?.35:1);
      if(heroes&&!backdrop) D.heroes.forEach((i,j)=>{
        const p=D.paths[i];
        g+=poly(p.slice(0,week*4+1).map((s,k)=>[X(k/4),Y(s)]),C.blue,4);
        g+=`<circle cx="${X(week)}" cy="${Y(p[week*4])}" r="4" fill="${C.blue}"/>`;
        g+=text(675,230+j*28,`Path ${j+1}: ${fmt(p[week*4])}`);
      });
      g+=`<circle cx="${X(0)}" cy="${Y(8.4)}" r="5" fill="${C.ink}"/>`+text(82,Y(8.4)-14,'Now · 8.4%');
      if(!backdrop) g+=text(675,72,'200 paths shown')+text(675,98,'10,000 simulated')+text(675,142,'Near-white: median')+text(675,168,'Dashed: forecast')+text(675,194,'Blue bands: 50% / 90%');
      return g;
    }
    function histogram() {
      let g=fan(true), counts=Array.from({length:40},(_,i)=>Math.round((D.density[week][i*2]+D.density[week][i*2+1])*2500));
      const max=Math.max(...counts,1);
      counts.forEach((count,i)=>{if(count)g+=`<rect x="660" y="${Y(i*.5+.25)-3}" width="${count/max*180}" height="6" fill="${C.blue}" opacity=".55"/>`;});
      g+=line(650,Y(12),860,Y(12),C.ink,1,'stroke-dasharray="5 4"')+text(860,Y(12)-9,'12%','text-anchor="end"');
      return g+text(750,36,`Week ${week} endings`,'text-anchor="middle"')+text(750,420,'More paths →','text-anchor="middle"');
    }
    function surface() {
      const theta=angle*Math.PI/180;
      const project=(w,s,d)=>{
        const a=(w-4)*49,b=(s-10)*15;
        return [455+a*Math.cos(theta)-b*Math.sin(theta),300+(a*Math.sin(theta)+b*Math.cos(theta))*.40-d*58];
      };
      let g='';
      [0,5,10,15,20].forEach(s=>{const a=project(0,s,0),b=project(8,s,0);g+=poly([a,b],C.grid,1)+text(b[0]+10,b[1]+4,`${s}%`);});
      for(let w=0;w<=8;w++){const a=project(w,0,0),b=project(w,20,0);g+=poly([a,b],C.grid,1)+text(a[0],a[1]+20,w,'text-anchor="middle"');}
      (D.contours||[]).forEach(segment=>{
        // Keep only connected contour runs within the selected week.
        let run=[];
        for(const [w,s] of segment){if(w<=week)run.push(project(w,s,-.02));else if(run.length){if(run.length>1)g+=poly(run,C.blue,.8,.8);run=[];}}
        if(run.length>1)g+=poly(run,C.blue,.8,.8);
      });
      const faces=[];
      for(let w=0;w<week;w++)for(let b=0;b<79;b++){
        const coords=[[w,b],[w+1,b],[w+1,b+1],[w,b+1]];
        faces.push({depth:coords.reduce((n,[i,j])=>n+(i-4)*49*Math.sin(theta)+(j*.25+.125-10)*15*Math.cos(theta),0)/4,
          p:coords.map(([i,j])=>project(i,j*.25+.125,D.density[i][j]))});
      }
      faces.sort((a,b)=>a.depth-b.depth).forEach(f=>g+=`<polygon points="${points(f.p)}" fill="${C.fill}" stroke="${C.blue}" stroke-opacity=".55" stroke-width=".6"/>`);
      g+=poly(D.density[week].map((d,b)=>project(week,b*.25+.125,d)),C.center,2);
      g+=poly(q[3].slice(0,week+1).map((s,w)=>project(w,s,-.02)),C.center,2);
      const z0=project(0,0,0),z1=project(0,0,4.2);
      g+=poly([z0,z1],C.muted,1)+text(z1[0]-8,z1[1]-10,'Density','text-anchor="end"');
      [0,2,4].forEach(d=>{const p=project(0,0,d);g+=text(p[0]-10,p[1]+4,d.toFixed(1),'text-anchor="end"');});
      return g+text(68,36,'One height scale · 0–4.2')+text(68,412,'Near-white floor trace: median')+text(700,60,`Week ${week} peak: ${D.density[week].reduce((a,b)=>Math.max(a,b),0).toFixed(2)}`)+text(640,420,'Week / usage share (%)');
    }
    function draw() {
      root.querySelector('[data-futures-week]').value=week;
      root.querySelector('.futures-hero-control').hidden=mode!=='paths';
      root.querySelector('.futures-orbit').hidden=mode!=='surface';
      const caption={paths:'Each thread is a complete possible future. Bands summarize all 10,000 paths; they do not constrain any single path.',surface:'The same samples, counted by usage share. As uncertainty spreads, the density peak falls. Every slice uses the same height scale.',endings:'The same paths, counted at the selected week. Bar length shows how many finish at each usage share; the dashed line marks 12%.'}[mode];
      root.querySelector('.futures-stage').innerHTML=`<svg viewBox="0 0 900 440" role="img" aria-label="Illustrative ${mode} at week ${week}. ${caption}"><g fill="${C.muted}" font-family="inherit" font-size="13">${mode==='paths'?fan():mode==='surface'?surface():histogram()}</g></svg>`;
      root.querySelector('.futures-stage').setAttribute('aria-busy','false');
      root.querySelector('[data-futures-explanation]').textContent=caption;
      root.querySelector('.futures-stats').innerHTML=`<div><dt>Median · week ${week}</dt><dd>${fmt(q[3][week])}</dd></div><div><dt>90% of simulated endings</dt><dd>${q[0][week].toFixed(1)}–${fmt(q[6][week])}</dd></div><div><dt>Finish above 12%</dt><dd>${D.above12[week].toLocaleString()} <small>of 10,000 (${Math.round(D.above12[week]/100)}%)</small></dd></div>`;
    }
    root.querySelectorAll('[data-futures-view]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.futuresView;root.querySelectorAll('[data-futures-view]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));draw();}));
    root.querySelector('[data-futures-scrub]').addEventListener('input',e=>{week=Number(e.target.value);draw();});
    root.querySelector('[data-futures-heroes]').addEventListener('change',e=>{heroes=e.target.checked;draw();});
    root.querySelector('[data-futures-angle]').addEventListener('input',e=>{angle=Number(e.target.value);draw();});
    root.querySelector('.futures-table').innerHTML=`<table><caption>Illustrative simulation, all 10,000 paths</caption><thead><tr><th scope="col">Week</th><th scope="col">Forecast</th><th scope="col">Path median</th><th scope="col">90% range</th><th scope="col">Above 12%</th><th scope="col">Peak density</th></tr></thead><tbody>${D.center.map((c,w)=>`<tr><th scope="row">${w}</th><td>${fmt(c)}</td><td>${fmt(q[3][w])}</td><td>${fmt(q[0][w])}–${fmt(q[6][w])}</td><td>${D.above12[w].toLocaleString()}</td><td>${Math.max(...D.density[w]).toFixed(2)}</td></tr>`).join('')}</tbody></table>`;
    draw();
  }
  window.FuturesExplorer={markup,mount};
})();
