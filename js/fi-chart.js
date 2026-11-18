/* FI page trend chart: metric tabs + tap/hover readout. Data is embedded in the page (no requests). */
(function(){
  var sec=document.querySelector('.fin');if(!sec)return;
  var raw=sec.querySelector('.fin-data');if(!raw)return;
  var D=JSON.parse(raw.textContent),svg=sec.querySelector('svg.chart'),tip=sec.querySelector('.tip'),m='a';
  if(!svg)return;
  var W=640,H=260,L=84,R=12,T=14,B=34,NS='http://www.w3.org/2000/svg';
  function money(k){if(k==null)return'—';var u=k*1000,s=[[1e12,'T'],[1e9,'B'],[1e6,'M']];for(var i=0;i<s.length;i++){if(Math.abs(u)>=s[i][0]){var v=u/s[i][0];return'$'+(Math.abs(v)>=100?v.toFixed(0):v.toFixed(1)).replace(/\.0$/,'')+s[i][1]}}return'$'+Math.round(u/1e3).toLocaleString()+'K'}
  function q(s){return s.slice(4)+' '+s.slice(0,4)}
  function el(n,a,t){var e=document.createElementNS(NS,n);for(var k in a)e.setAttribute(k,a[k]);if(t!=null)e.textContent=t;return e}
  var X,Y,pts;
  function draw(){
    var s=D[m]||[],n=s.length-1;pts=[];for(var i=0;i<s.length;i++)if(s[i]!=null)pts.push([i,s[i]]);
    while(svg.firstChild)svg.removeChild(svg.firstChild);if(pts.length<2)return;
    var lo=Infinity,hi=-Infinity;pts.forEach(function(p){lo=Math.min(lo,p[1]);hi=Math.max(hi,p[1])});
    var pad=(hi-lo)*.08||hi*.05||1;lo=Math.max(0,lo-pad);hi=hi+pad;
    X=function(i){return L+i/n*(W-L-R)};Y=function(v){return T+(1-(v-lo)/(hi-lo))*(H-T-B)};
    for(var g=0;g<3;g++){var v=lo+(hi-lo)*g/2;svg.appendChild(el('line',{x1:L,x2:W-R,y1:Y(v),y2:Y(v),'class':'gl'}));svg.appendChild(el('text',{x:L-6,y:Y(v)+4,'text-anchor':'end'},money(v)))}
    D.q.forEach(function(s,i){if(/Q1$/.test(s)&&+s.slice(0,4)%2==0)svg.appendChild(el('text',{x:X(i),y:H-8,'text-anchor':'middle'},s.slice(0,4)))});
    svg.appendChild(el('path',{d:pts.map(function(p,k){return(k?'L':'M')+X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1)}).join(' '),'class':'ln'}));
    svg.appendChild(el('line',{'class':'cur',y1:T,y2:H-B,x1:-9,x2:-9}));
    tip.hidden=true;
  }
  function show(ev){
    if(!pts||pts.length<2)return;var r=svg.getBoundingClientRect(),cx=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left;
    var vx=cx/r.width*W,best=pts[0];pts.forEach(function(p){if(Math.abs(X(p[0])-vx)<Math.abs(X(best[0])-vx))best=p});
    var c=svg.querySelector('.cur');c.setAttribute('x1',X(best[0]));c.setAttribute('x2',X(best[0]));
    var s=D[m],j=best[0],y=j>=4&&s[j-4]?((s[j]/s[j-4]-1)*100):null;
    tip.textContent=q(D.q[j])+': '+money(best[1])+(y!=null?' ('+(y>=0?'+':'−')+Math.abs(y).toFixed(1)+'% YoY)':'');
    tip.hidden=false;var px=X(j)/W*r.width;tip.style.left=Math.min(Math.max(px,70),r.width-70)+'px';
  }
  svg.addEventListener('pointermove',show);svg.addEventListener('pointerdown',show);
  svg.addEventListener('pointerleave',function(){tip.hidden=true});
  sec.querySelectorAll('.tab').forEach(function(b){b.addEventListener('click',function(){
    m=b.getAttribute('data-m');sec.querySelectorAll('.tab').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});
    sec.querySelectorAll('.fin-t').forEach(function(t){t.hidden=t.getAttribute('data-m')!==m});draw()})});
  draw();
})();
