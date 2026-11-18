/* FI page trend chart: metric tabs, tap/hover readout, optional benchmarks (index vs peers, CPI, merger markers). Data is embedded in the page (no requests). */
(function(){
  var sec=document.querySelector('.fin');if(!sec)return;
  var raw=sec.querySelector('.fin-data');if(!raw)return;
  var D=JSON.parse(raw.textContent);D.q=[];(function(){var y=+D.q0.slice(0,4),k=+D.q0.slice(5);for(var i=0;i<D.a.length;i++){D.q.push(y+'Q'+k);k++;if(k>4){k=1;y++}}})();var svg=sec.querySelector('svg.chart'),tip=sec.querySelector('.tip'),m='a',vw='usd',real=false;
  var W=640,H=260,L=84,R=12,T=14,B=34,NS='http://www.w3.org/2000/svg',BM=D.bm,EV={};(D.ev||[]).forEach(function(e){EV[e[0]]=e[1]});
  function money(k){if(k==null)return'—';var u=k*1000,s=[[1e12,'T'],[1e9,'B'],[1e6,'M']];for(var i=0;i<s.length;i++){if(Math.abs(u)>=s[i][0]){var v=u/s[i][0];return'$'+(Math.abs(v)>=100?v.toFixed(0):v.toFixed(1)).replace(/\.0$/,'')+s[i][1]}}return'$'+Math.round(u/1e3).toLocaleString()+'K'}
  function q(s){return s.slice(4)+' '+s.slice(0,4)}
  function el(n,a,t){var e=document.createElementNS(NS,n);for(var k in a)e.setAttribute(k,a[k]);if(t!=null)e.textContent=t;return e}
  var C=BM&&BM.cpi,last=D.a.length-1;
  function defl(i){return real&&C?C[vw=='idx'?0:last]/C[i]:1} /* index: start-quarter dollars; dollars: latest-quarter dollars */
  function lines(){
    var s=D[m]||[],out=[],f;
    if(vw=='idx'&&BM&&m=='a'){var s0=s[0];
      var N=BM.n||{};out.push({k:'fi',n:N.fi,v:s.map(function(v,i){return v==null||!s0?null:v/s0*100*defl(i)})});
      ['p','im','it'].forEach(function(x){if(BM[x])out.push({k:x,n:N[x],v:BM[x].map(function(v,i){return v==null?null:v*defl(i)})})})}
    else out.push({k:'fi',v:s.map(function(v,i){return v==null?null:v*defl(i)})});
    return out}
  var X,Y,LS,pts;
  function draw(){
    LS=lines();var n=(D[m]||[]).length-1;pts=[];LS[0].v.forEach(function(v,i){if(v!=null)pts.push([i,v])});
    if(!svg)return;while(svg.firstChild)svg.removeChild(svg.firstChild);if(pts.length<2)return;
    var idx=LS.length>1||(vw=='idx'&&m=='a'),lo=Infinity,hi=-Infinity;LS.forEach(function(l){l.v.forEach(function(v){if(v!=null){lo=Math.min(lo,v);hi=Math.max(hi,v)}})});
    var pad=(hi-lo)*.08||hi*.05||1;lo=Math.max(0,lo-pad);hi=hi+pad;
    X=function(i){return L+i/n*(W-L-R)};Y=function(v){return T+(1-(v-lo)/(hi-lo))*(H-T-B)};
    for(var g=0;g<3;g++){var v=lo+(hi-lo)*g/2;svg.appendChild(el('line',{x1:L,x2:W-R,y1:Y(v),y2:Y(v),'class':'gl'}));svg.appendChild(el('text',{x:L-6,y:Y(v)+4,'text-anchor':'end'},idx?Math.round(v):money(v)))}
    if(idx&&lo<100&&hi>100)svg.appendChild(el('line',{x1:L,x2:W-R,y1:Y(100),y2:Y(100),'class':'gl b100'}));
    D.q.forEach(function(s,i){if(/Q1$/.test(s)&&+s.slice(0,4)%2==0)svg.appendChild(el('text',{x:X(i),y:H-8,'text-anchor':'middle'},s.slice(0,4)))});
    for(var j in EV){var x=X(+j);svg.appendChild(el('line',{x1:x,x2:x,y1:T+8,y2:H-B,'class':'mk'}));svg.appendChild(el('path',{d:'M'+x+','+(T-4)+'l6,7l-6,7l-6,-7z','class':'mkd'}))}
    for(var k=LS.length-1;k>=0;k--){var l=LS[k],d='',up=false;l.v.forEach(function(v,i){if(v==null){up=false;return}d+=(up?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1)+' ';up=true});
      svg.appendChild(el('path',{d:d,'class':k?'ln b-'+l.k:'ln'}))}
    svg.appendChild(el('line',{'class':'cur',y1:T,y2:H-B,x1:-9,x2:-9}));
    tip.hidden=true;
  }
  function show(ev){
    if(!svg||!pts||pts.length<2)return;var r=svg.getBoundingClientRect(),cx=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left;
    var vx=cx/r.width*W,best=pts[0];pts.forEach(function(p){if(Math.abs(X(p[0])-vx)<Math.abs(X(best[0])-vx))best=p});
    var c=svg.querySelector('.cur');c.setAttribute('x1',X(best[0]));c.setAttribute('x2',X(best[0]));
    var j=best[0],h;
    if(LS.length>1){h='<b>'+q(D.q[j])+'</b>';LS.forEach(function(l){h+='<br><i class="k k-'+l.k+'"></i>'+l.n+': '+(l.v[j]==null?'—':l.v[j].toFixed(0))})}
    else{var s=LS[0].v,y=j>=4&&s[j-4]?((s[j]/s[j-4]-1)*100):null;h='<b>'+q(D.q[j])+'</b>: '+money(best[1])+(y!=null?' ('+(y>=0?'+':'−')+Math.abs(y).toFixed(1)+'% YoY)':'')}
    if(EV[j])h+='<br>◆ '+EV[j].replace(/[<>&]/g,'');
    tip.innerHTML=h;tip.classList.toggle('wide',LS.length>1||!!EV[j]);
    tip.hidden=false;var px=X(j)/W*r.width,hw=Math.min(tip.offsetWidth/2+4,r.width/2);tip.style.left=Math.min(Math.max(px,hw),r.width-hw)+'px';
  }
  var NAMES={a:'Assets',d:'Deposits',l:'Loans'},box=sec.querySelector('.fin-tables');
  function pc(n,o){if(n==null||!o)return'<span class="pc">—</span>';var p=(n/o-1)*100,c=p>0.05?'up':p<-0.05?'dn':'';return'<span class="pc '+c+'">'+(p>0?'+':p<0?'−':'')+Math.abs(p).toFixed(1)+'%</span>'}
  function table(k){if(box.querySelector('.fin-t[data-m='+k+']'))return;var s=D[k]||[],h='';
    for(var j=s.length-1;j>Math.max(s.length-9,-1);j--)h+='<tr><th scope="row">'+q(D.q[j])+'</th><td>'+money(s[j])+'</td><td>'+(j>=1?pc(s[j],s[j-1]):pc())+'</td><td>'+(j>=4?pc(s[j],s[j-4]):pc())+'</td></tr>';
    var t=document.createElement('table');t.className='fin-t';t.setAttribute('data-m',k);
    t.innerHTML='<caption class="sr">'+NAMES[k]+', last 8 quarters</caption><thead><tr><th scope="col">Quarter</th><th scope="col">'+NAMES[k]+'</th><th scope="col">QoQ</th><th scope="col">YoY</th></tr></thead><tbody>'+h+'</tbody>';box.appendChild(t)}
  if(svg){svg.addEventListener('pointermove',show);svg.addEventListener('pointerdown',show);
  svg.addEventListener('pointerleave',function(){tip.hidden=true})}
  var ctl=sec.querySelector('.bm-ctl'),leg=sec.querySelector('.bm-legend'),vd=sec.querySelector('.verdict'),cap=sec.querySelector('.fin-chart figcaption'),cap0=cap&&cap.textContent;
  function ui(){if(!ctl)return;var seg=ctl.querySelector('.seg');seg.hidden=m!='a';
    ctl.querySelectorAll('.vw').forEach(function(b){b.setAttribute('aria-pressed',b.getAttribute('data-v')==vw?'true':'false')});
    leg.hidden=!(vw=='idx'&&m=='a');if(vd)vd.textContent=vd.getAttribute(real?'data-real':'data-nom');
    if(cap)cap.textContent=(vw=='idx'&&m=='a'?'Index, '+q(D.q0)+' = 100'+(real?', inflation-adjusted':'')+'. ':real?'Inflation-adjusted, '+q(D.q[last])+' dollars. ':'')+cap0}
  if(ctl){ctl.hidden=false;ctl.querySelectorAll('.vw').forEach(function(b){b.addEventListener('click',function(){vw=b.getAttribute('data-v');ui();draw()})});
    ctl.querySelector('.cpi-in').addEventListener('change',function(e){real=e.target.checked;ui();draw()})}
  sec.querySelectorAll('.tab').forEach(function(b){b.addEventListener('click',function(){
    m=b.getAttribute('data-m');table(m);sec.querySelectorAll('.tab').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});
    sec.querySelectorAll('.fin-t').forEach(function(t){t.hidden=t.getAttribute('data-m')!==m});ui();draw()})});
  draw();
})();
