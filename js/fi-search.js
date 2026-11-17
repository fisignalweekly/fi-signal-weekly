// FI directory search (/fi/). Loads the compact index fi/search.json once and filters it in the browser.
// Filters live in the URL (?q=&state=&charter=&assets=&signals=1), the same plain-URL approach as the board.
(function(){
  var $=function(id){return document.getElementById(id)};
  var q=$("fs-q"),st=$("fs-state"),ch=$("fs-charter"),as=$("fs-assets"),sg=$("fs-signals"),out=$("fs-results"),cnt=$("fs-count"),
      more=$("fs-more"),moreWrap=$("fs-more-wrap"),def=$("fs-default");
  if(!q||!out)return;
  var rows=null,loading=null,PAGE=50,shown=PAGE,timer,STNAME={};
  [].forEach.call(st.options,function(o){if(o.value)STNAME[o.value]=o.textContent.toLowerCase()});
  var TIERS={"lt500m":[0,500],"500m-1b":[500,1000],"1b-10b":[1000,10000],"10b-50b":[10000,50000],"50b+":[50000,Infinity]};
  function money(m){if(m<0)return "";var b=m/1000;if(b>=1)return "$"+(b>=100?b.toFixed(0):b.toFixed(1)).replace(/\.0$/,"")+"B";return "$"+(m>=10?m.toFixed(0):Math.max(m,0.1).toFixed(1)).replace(/\.0$/,"")+"M"}
  function load(){
    if(!loading)loading=fetch(out.getAttribute("data-src")||"/fi/search.json").then(function(r){return r.json()}).then(function(d){
      rows=d.rows.map(function(r){return {st:r[0],slug:r[1],name:r[2],city:r[3],cu:r[4],m:r[5],n:r[6],
        hay:(r[2]+" "+r[3]+" "+r[0]+" "+(STNAME[r[0]]||"")+" "+r[7]).toLowerCase(),nm:r[2].toLowerCase()}});
      return rows;
    });
    return loading;
  }
  function active(){return !!(q.value.trim()||st.value||ch.value||as.value||sg.checked)}
  function sync(){
    var p=[];if(q.value.trim())p.push("q="+encodeURIComponent(q.value.trim()));
    if(st.value)p.push("state="+st.value);if(ch.value)p.push("charter="+ch.value);if(as.value)p.push("assets="+encodeURIComponent(as.value));if(sg.checked)p.push("signals=1");
    var u=location.pathname+(p.length?"?"+p.join("&"):"");
    if(u!==location.pathname+location.search&&history.replaceState)history.replaceState(null,"",u);
  }
  function match(){
    var toks=q.value.trim().toLowerCase().split(/\s+/).filter(Boolean),qs=toks.join(" "),t=TIERS[as.value];
    var res=rows.filter(function(r){
      if(st.value&&r.st!==st.value)return false;
      if(ch.value&&(ch.value==="cu")!==!!r.cu)return false;
      if(as.value==="na"&&r.m>=0)return false;
      if(t&&!(r.m>=t[0]&&r.m<t[1]))return false;
      if(sg.checked&&!r.n)return false;
      for(var i=0;i<toks.length;i++)if(r.hay.indexOf(toks[i])<0)return false;
      return true;
    });
    if(qs){
      var rank=function(r){return r.nm===qs?0:r.nm.indexOf(qs)===0?1:(" "+r.nm).indexOf(" "+qs)>-1?2:3};
      res=res.map(function(r,i){return [rank(r),i,r]}).sort(function(a,b){return a[0]-b[0]||a[1]-b[1]}).map(function(x){return x[2]});
    }
    return res;
  }
  function li(r){
    var l=document.createElement("li"),a=document.createElement("a");a.href="/fi/"+r.st.toLowerCase()+"/"+r.slug+"/";
    var nm=document.createElement("span");nm.className="nm";nm.textContent=r.name;a.appendChild(nm);
    if(r.n){var s=document.createElement("span");s.className="sigs";s.textContent=r.n+" signal"+(r.n>1?"s":"");a.appendChild(s)}
    var sub=document.createElement("span");sub.className="sub";
    sub.textContent=[r.city+", "+r.st,r.cu?"Credit union":"Bank",money(r.m)].filter(Boolean).join(" · ");a.appendChild(sub);
    l.appendChild(a);return l;
  }
  function render(){
    sync();
    if(!active()){out.hidden=true;moreWrap.hidden=true;cnt.textContent="";if(def)def.hidden=false;return}
    if(def)def.hidden=true;
    if(!rows){cnt.textContent="Loading…";load().then(render);return}
    var res=match();out.textContent="";
    res.slice(0,shown).forEach(function(r){out.appendChild(li(r))});
    out.hidden=!res.length;
    cnt.textContent=res.length?(res.length>shown?"Showing "+shown+" of "+res.length.toLocaleString("en-US"):res.length.toLocaleString("en-US"))+" of "+rows.length.toLocaleString("en-US")+" institutions":"No institutions match. Try a shorter name or fewer filters.";
    moreWrap.hidden=res.length<=shown;
    if(res.length>shown)more.textContent="Show "+Math.min(PAGE,res.length-shown)+" more";
  }
  function changed(){shown=PAGE;render()}
  var p=new URLSearchParams(location.search);
  q.value=(p.get("q")||"").slice(0,100);
  var ok=function(sel,v){return [].some.call(sel.options,function(o){return o.value===v})};
  var ps=(p.get("state")||"").toUpperCase();if(ok(st,ps))st.value=ps;
  var pc=p.get("charter")||"",pa=p.get("assets")||"";
  if(ok(ch,pc))ch.value=pc;
  if(ok(as,pa))as.value=pa;
  sg.checked=p.get("signals")==="1";
  q.addEventListener("input",function(){clearTimeout(timer);timer=setTimeout(changed,90)});
  [st,ch,as,sg].forEach(function(x){x.addEventListener("change",changed)});
  q.addEventListener("focus",load,{once:true});
  more.addEventListener("click",function(){shown+=PAGE;render()});
  render();
  if(!active()&&"requestIdleCallback" in window)requestIdleCallback(load,{timeout:4000});
})();
