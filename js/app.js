(function(){
  var TYPE_LABEL={merger:"Pending merger",core:"Core renewal / conversion",executive:"New executive"};
  var PAGE=30,shown=PAGE,all=[],$=function(id){return document.getElementById(id)};
  function fmtAssets(m){
    if(m==null) return "Assets n/a";
    if(m>=1000) return "~$"+(m/1000).toFixed(m>=10000?0:1).replace(/\.0$/,"")+"B assets";
    return "~$"+m+"M assets";
  }
  // Asset size: the linked institution record (FDIC / NCUA call report, scripts/link_institutions.py) when there is one,
  // else the row's own assets_millions (press release or Verifier figure, shown with "~").
  function money(usd){
    var b=usd/1e9,m=usd/1e6;
    if(b>=1) return "$"+(b>=100?b.toFixed(0):b.toFixed(1)).replace(/\.0$/,"")+"B";
    return "$"+(m>=10?m.toFixed(0):m.toFixed(1)).replace(/\.0$/,"")+"M";
  }
  function assetsUsd(r){
    if(r.fi_assets_usd!=null) return r.fi_assets_usd;
    return r.assets_millions!=null?r.assets_millions*1e6:null;
  }
  function assetsText(r){
    if(r.fi_assets_usd!=null) return money(r.fi_assets_usd)+" assets"+(r.fi_assets_as_of?" ("+r.fi_assets_as_of+")":"");
    return fmtAssets(r.assets_millions);
  }
  function assetsTitle(r){
    if(r.fi_assets_usd==null) return r.assets_note||"";
    var src=/^fdic-/.test(r.fi_id)?"FDIC CERT "+r.fi_id.slice(5):"NCUA charter "+r.fi_id.slice(5);
    return "Total assets of "+r.fi_name+" ("+src+"), call report "+(r.fi_assets_date||r.fi_assets_as_of);
  }
  var TIERS={"lt500m":[0,5e8],"500m-1b":[5e8,1e9],"1b-10b":[1e9,1e10],"10b-50b":[1e10,5e10],"50b+":[5e10,Infinity]};
  function inTier(r,t){
    if(!t) return true;
    var a=assetsUsd(r);
    if(t==="na") return a==null;
    return a!=null&&a>=TIERS[t][0]&&a<TIERS[t][1];
  }
  function fmtDate(d){
    var p=d.split("-");return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString("en-US",{year:"numeric",month:"short",day:"numeric"});
  }
  // "New" = row went live on the board (r.added) within the last NEW_DAYS days
  var NEW_DAYS=7,newCutoff=(function(){var d=new Date();d.setHours(0,0,0,0);d.setDate(d.getDate()-NEW_DAYS);
    return d.getFullYear()+"-"+("0"+(d.getMonth()+1)).slice(-2)+"-"+("0"+d.getDate()).slice(-2)})();
  function isNew(r){return !!r.added&&r.added>newCutoff}
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
  // Bank vs. credit union: the real charter (r.charter_type, from the FDIC / NCUA record linked by
  // scripts/link_institutions.py). Fallback for rows with no linked record, derived from the institution name:
  // "Credit Union" anywhere, or an all-caps word ending in "CU" (CU, FCU, TDECU, WSECU, GECU, DFCU) => credit union;
  // everything else => bank. Cross-charter deals (a credit union buying a bank) count as credit union,
  // because the credit union is named in the row.
  function charter(r){if(r.charter_type==="bank"||r.charter_type==="cu")return r.charter_type;return /credit union/i.test(r.institution)||/\b[A-Z]*CU\b/.test(r.institution)?"cu":"bank"}
  var FILTERS=["f-type","f-state","f-charter","f-assets","f-from","f-to","f-q"];
  function selStates(){var v=$("f-state").value;return v?v.split(","):[]}
  function filtered(){
    var t=$("f-type").value,s=selStates(),c=$("f-charter").value,sz=$("f-assets").value,from=$("f-from").value,to=$("f-to").value,q=$("f-q").value.trim().toLowerCase();
    return all.filter(function(r){
      return (!t||r.type===t)&&(!s.length||s.indexOf(r.state)>-1)&&(!c||charter(r)===c)&&inTier(r,sz)&&(!from||r.date>=from)&&(!to||r.date<=to)&&
        (!q||(r.institution+" "+r.summary).toLowerCase().indexOf(q)>-1);
    }).sort(function(a,b){return a.date<b.date?1:-1});
  }
  // Row links never carry the current view: /#t217 always shows that row.
  function rowUrl(id){return location.origin+location.pathname+"#"+id}

  // ---- Saved territory views: every filter lives in the query string (plain URLs, no accounts, no tracking) ----
  // ?type=merger&state=MI,OH&charter=cu&assets=1b-10b&from=2026-10-01&to=2026-11-30&q=core
  // Opening such a URL restores the filters. A #tNNN anchor still wins: it clears filters that hide its row.
  var PARAMS=[["type","f-type"],["state","f-state"],["charter","f-charter"],["assets","f-assets"],["from","f-from"],["to","f-to"],["q","f-q"]];
  function viewQuery(){
    return PARAMS.map(function(p){var v=$(p[1]).value.trim();return v?p[0]+"="+encodeURIComponent(v).replace(/%2C/g,","):""}).filter(Boolean).join("&");
  }
  function viewUrl(){var q=viewQuery();return location.origin+location.pathname+(q?"?"+q:"")}
  function syncUrl(dropRowHash){
    if(!window.history||!history.replaceState)return;
    var h=location.hash||"";if(dropRowHash&&/^#t\d+$/i.test(h))h="";
    var q=viewQuery(),u=location.pathname+(q?"?"+q:"")+h;
    if(u!==location.pathname+location.search+location.hash)history.replaceState(null,"",u);
  }
  function optOk(id,v){return [].some.call($(id).options,function(o){return o.value===v})}
  function applyQuery(search){
    var p=new URLSearchParams(search||""),get=function(k){return (p.get(k)||"").trim()};
    ["type","charter","assets"].forEach(function(k){var id="f-"+k,v=get(k).toLowerCase();$(id).value=v&&optOk(id,v)?v:""});
    ["from","to"].forEach(function(k){var v=get(k);$("f-"+k).value=/^\d{4}-\d{2}-\d{2}$/.test(v)?v:""});
    $("f-q").value=get("q").slice(0,100);
    setStates(get("state").toUpperCase().split(/[\s,]+/).filter(function(x){return USPS.indexOf(x)>-1}));
  }
  function clearFilters(){FILTERS.forEach(function(id){$(id).value=""});setStates([])}

  // State picker: one or more states. The chosen states live in the hidden #f-state input as "MI,OH".
  var stateCounts={};
  var USPS="AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP".split(" ");
  function setStates(list){
    var seen={},v=list.filter(function(x){if(seen[x])return false;seen[x]=1;return true}).sort();
    v.forEach(function(x){if(!(x in stateCounts)){stateCounts[x]=0;buildStateOpts()}});
    $("f-state").value=v.join(",");
    [].forEach.call($("f-state-opts").querySelectorAll("input"),function(cb){cb.checked=v.indexOf(cb.value)>-1});
    $("f-state-text").textContent=!v.length?"All states":v.length<=3?v.join(", "):v.slice(0,2).join(", ")+" +"+(v.length-2);
  }
  function buildStateOpts(){
    var box=$("f-state-opts"),cur=selStates();box.textContent="";
    Object.keys(stateCounts).sort().forEach(function(st){
      var l=el("label","ms-opt"),cb=document.createElement("input");cb.type="checkbox";cb.value=st;cb.checked=cur.indexOf(st)>-1;
      l.appendChild(cb);l.appendChild(el("span",null,st));l.appendChild(el("small",null,String(stateCounts[st])));box.appendChild(l);
    });
  }
  function statePicker(){
    var btn=$("f-state-btn"),pop=$("f-state-pop"),wrap=$("f-state-wrap");
    function open(on){pop.hidden=!on;btn.setAttribute("aria-expanded",on?"true":"false");wrap.classList.toggle("open",on)}
    btn.addEventListener("click",function(){open(pop.hidden)});
    $("f-state-done").addEventListener("click",function(){open(false);btn.focus()});
    $("f-state-all").addEventListener("click",function(){setStates([]);changed()});
    $("f-state-opts").addEventListener("change",function(e){
      e.stopPropagation();
      setStates([].filter.call($("f-state-opts").querySelectorAll("input"),function(c){return c.checked}).map(function(c){return c.value}));
      changed();
    });
    document.addEventListener("click",function(e){if(!pop.hidden&&!wrap.contains(e.target))open(false)});
    document.addEventListener("keydown",function(e){if(e.key==="Escape"&&!pop.hidden){open(false);btn.focus()}});
  }
  function changed(){shown=PAGE;render();syncUrl(true);var f=$("filters");if(f)f.dispatchEvent(new Event("change"))}

  var toastTimer;
  function toast(msg){var t=$("toast");if(!t)return;t.textContent=msg;t.hidden=false;t.classList.remove("show");void t.offsetWidth;t.classList.add("show");
    clearTimeout(toastTimer);toastTimer=setTimeout(function(){t.classList.remove("show");t.hidden=true},2600)}
  function copyText(text,done){
    function fallback(){
      var ta=document.createElement("textarea");ta.value=text;ta.setAttribute("readonly","");ta.style.position="fixed";ta.style.top="-1000px";
      document.body.appendChild(ta);ta.select();var ok=false;try{ok=document.execCommand("copy")}catch(e){}
      document.body.removeChild(ta);done(ok);
    }
    if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(function(){done(true)},fallback);else fallback();
  }
  function copyView(){
    var u=viewUrl(),n=filtered().length;
    copyText(u,function(ok){
      if(ok)toast("Link copied: "+(viewQuery()?"this view ("+n+" triggers)":"the full board"));
      else window.prompt("Copy this link:",u);
    });
  }
  function render(){
    var rows=filtered();
    var list=$("cards");list.textContent="";
    $("count").textContent=rows.length>shown?"Showing "+shown+" of "+rows.length+" matching triggers ("+all.length+" total)":rows.length+" of "+all.length+" triggers";
    if(!rows.length){var li=el("li","empty","No triggers match these filters.");list.appendChild(li);return}
    rows.slice(0,shown).forEach(function(r){
      var li=el("li","card "+r.type);li.id=r.id;
      var h=el("h3",null,r.institution);
      if(isNew(r)){var tg=el("span","tag-new","New");tg.title="Added to the board "+fmtDate(r.added);h.appendChild(tg)}
      li.appendChild(h);
      var m=el("div","meta");
      m.appendChild(el("span","badge "+r.type,TYPE_LABEL[r.type]||r.type));
      m.appendChild(el("span",null,r.state));
      var as=el("span","assets",assetsText(r));var at=assetsTitle(r);if(at)as.title=at;m.appendChild(as);
      m.appendChild(el("span",null,fmtDate(r.date)));
      li.appendChild(m);
      li.appendChild(el("p",null,r.summary));
      var a=el("a","src","Source ↗");a.href=r.source_url;a.target="_blank";a.rel="noopener noreferrer";
      li.appendChild(a);
      var lk=el("a","row-link","Link");lk.href="#"+r.id;lk.title="Copy a link to this row";
      lk.addEventListener("click",function(){
        if(navigator.clipboard&&navigator.clipboard.writeText){
          navigator.clipboard.writeText(rowUrl(r.id)).then(function(){lk.textContent="Link copied";setTimeout(function(){lk.textContent="Link"},1600)},function(){});
        }
      });
      li.appendChild(lk);
      list.appendChild(li);
    });
    if(rows.length>shown){
      var more=el("li","empty");var b=el("button","ghost","Show "+Math.min(PAGE,rows.length-shown)+" more");b.type="button";
      b.addEventListener("click",function(){shown+=PAGE;render()});more.appendChild(b);list.appendChild(more);
    }
  }
  function init(data){
    all=data.rows;
    $("updated").textContent=fmtDate(data.updated);
    all.forEach(function(r){stateCounts[r.state]=(stateCounts[r.state]||0)+1});
    buildStateOpts();statePicker();
    ["f-type","f-charter","f-assets","f-from","f-to"].forEach(function(id){$(id).addEventListener("change",changed)});
    $("f-q").addEventListener("input",changed);
    $("reset").addEventListener("click",function(){clearFilters();changed()});
    $("copy-view").addEventListener("click",copyView);
    [].forEach.call(document.querySelectorAll(".view-chip"),function(a){
      a.addEventListener("click",function(e){e.preventDefault();applyQuery(a.getAttribute("href").split("?")[1]);changed();
        var c=$("count");if(c&&c.getBoundingClientRect().top>window.innerHeight)c.scrollIntoView({block:"center"})});
    });
    applyQuery(location.search);
    render();syncUrl(false);
    goToRow();
    window.addEventListener("hashchange",goToRow);
  }
  // Row anchors: fisignalweekly.com/#t217 renders that row (clearing filters / expanding pages if needed),
  // scrolls to it and highlights it. Other hashes (#subscribe, #board, #sponsor) are left to the browser.
  var hlTimer;
  function goToRow(){
    var m=/^#(t\d+)$/i.exec(location.hash||"");if(!m||!all.length)return;
    var id=m[1].toLowerCase(),idx;
    if(!all.some(function(r){return r.id===id}))return;
    var rows=filtered();
    idx=rows.findIndex(function(r){return r.id===id});
    if(idx<0){clearFilters();rows=filtered();idx=rows.findIndex(function(r){return r.id===id});render();syncUrl(false);var f=$("filters");if(f)f.dispatchEvent(new Event("change"))}
    if(idx<0)return;
    if(idx>=shown)shown=Math.ceil((idx+1)/PAGE)*PAGE;
    if(!$(id))render();
    var card=$(id);if(!card)return;
    var go=function(){card.scrollIntoView({block:"center"})};
    go();
    // re-center once late-loading content above the board (signup embed) has settled
    setTimeout(function(){var b=card.getBoundingClientRect();if(b.top<0||b.bottom>window.innerHeight)go()},900);
    card.classList.remove("row-hl");void card.offsetWidth;card.classList.add("row-hl");
    clearTimeout(hlTimer);hlTimer=setTimeout(function(){card.classList.remove("row-hl")},6000);
  }
  if($("cards")){
    fetch("data/triggers.json").then(function(r){return r.json()}).then(init).catch(function(){
      $("cards").textContent="";$("cards").appendChild(el("li","empty","Couldn't load data/triggers.json. Serve the site over HTTP (e.g. python3 -m http.server)."));
    });
  }
})();
