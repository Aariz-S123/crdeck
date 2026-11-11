const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const web=path.resolve(__dirname,'../../web');
const data=JSON.parse(fs.readFileSync(path.join(web,'futures-example.json'),'utf8'));
const source=fs.readFileSync(path.join(web,'futures-explorer.js'),'utf8');
async function open(failed=false){
  const dom=new JSDOM('<main></main>',{runScripts:'outside-only'});
  const w=dom.window;let missing=failed;
  w.fetch=async()=>({ok:!missing,json:async()=>data});
  w.eval(source);w.document.querySelector('main').innerHTML=w.FuturesExplorer.markup();
  await w.FuturesExplorer.mount(w.document);
  return {w,d:w.document,recover:()=>{missing=false;}};
}
(async()=>{
  const {w,d}=await open();
  assert.match(d.querySelector('.futures-disclaimer').textContent,/illustrative/);
  assert.match(d.querySelector('.futures-stats').textContent,/3,662/);
  assert.equal(d.querySelectorAll('.futures-table tbody tr').length,9);
  assert.equal(d.querySelectorAll('.futures-stage polyline[opacity="0.08"]').length,200);
  const stats=d.querySelector('.futures-stats').textContent;
  for(const mode of ['surface','endings','paths']){
    d.querySelector(`[data-futures-view="${mode}"]`).click();
    assert.equal(d.querySelector('[aria-pressed="true"]').dataset.futuresView,mode);
    assert.equal(d.querySelector('.futures-stats').textContent,stats,'switching views changed the data');
    assert.ok(!/NaN|undefined/.test(d.querySelector('.futures-stage').innerHTML));
  }
  const slider=d.querySelector('[data-futures-scrub]');
  for(let week=0;week<=8;week++){
    slider.value=week;slider.dispatchEvent(new w.Event('input'));
    for(const mode of ['paths','surface','endings']){
      d.querySelector(`[data-futures-view="${mode}"]`).click();
      assert.ok(!/NaN|undefined/.test(d.querySelector('.futures-stage').innerHTML));
      assert.match(d.querySelector('.futures-stats').textContent,new RegExp(data.above12[week].toLocaleString()));
    }
  }
  d.querySelector('[data-futures-view="paths"]').click();
  const hero=d.querySelector('[data-futures-heroes]');hero.checked=true;hero.dispatchEvent(new w.Event('change'));
  assert.match(d.querySelector('.futures-stage').textContent,/Path 3/);
  d.querySelector('[data-futures-view="surface"]').click();
  const angle=d.querySelector('[data-futures-angle]'),before=d.querySelector('svg').innerHTML;
  angle.value=-30;angle.dispatchEvent(new w.Event('input'));assert.notEqual(d.querySelector('svg').innerHTML,before);
  const broken=await open(true);assert.match(broken.d.querySelector('.futures-stage').textContent,/could not load/);
  assert.ok(broken.d.querySelector('[data-futures-scrub]').disabled);
  broken.recover();broken.d.querySelector('[data-futures-retry]').click();
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.ok(broken.d.querySelector('svg'));assert.ok(!broken.d.querySelector('[data-futures-scrub]').disabled);
  console.log('PASS: same-array views, all weeks, hero paths, orbit, table, missing data and retry');
  w.close();broken.w.close();
})().catch(e=>{console.error(e);process.exit(1);});
