(function(){
  var TYPE_LABEL={merger:"Pending merger",core:"Core renewal / conversion",executive:"New executive"};
  var PAGE=30,shown=PAGE,all=[],$=function(id){return document.getElementById(id)};
  function fmtAssets(m){
    if(m==null) return "Assets n/a";
    if(m>=1000) return "~$"+(m/1000).toFixed(m>=10000?0:1).replace(/\.0$/,"")+"B assets";
    return "~$"+m+"M assets";
  }
  function fmtDate(d){
    var p=d.split("-");return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString("en-US",{year:"numeric",month:"short",day:"numeric"});
  }
  // "New" = row went live on the board (r.added) within the last NEW_DAYS days
  var NEW_DAYS=7,newCutoff=(function(){var d=new Date();d.setHours(0,0,0,0);d.setDate(d.getDate()-NEW_DAYS);
    return d.getFullYear()+"-"+("0"+(d.getMonth()+1)).slice(-2)+"-"+("0"+d.getDate()).slice(-2)})();
  function isNew(r){return !!r.added&&r.added>newCutoff}
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
  // Bank vs. credit union, derived from the institution name (there is no charter field in triggers.json):
  // "Credit Union" anywhere, or an all-caps word ending in "CU" (CU, FCU, TDECU, WSECU, GECU, DFCU) => credit union;
  // everything else => bank. Cross-charter deals (a credit union buying a bank) count as credit union,
  // because the credit union is named in the row.
  function charter(r){return /credit union/i.test(r.institution)||/\b[A-Z]*CU\b/.test(r.institution)?"cu":"bank"}
  var FILTERS=["f-type","f-state","f-charter","f-from","f-to","f-q"];
  function filtered(){
    var t=$("f-type").value,s=$("f-state").value,c=$("f-charter").value,from=$("f-from").value,to=$("f-to").value,q=$("f-q").value.trim().toLowerCase();
    return all.filter(function(r){
      return (!t||r.type===t)&&(!s||r.state===s)&&(!c||charter(r)===c)&&(!from||r.date>=from)&&(!to||r.date<=to)&&
        (!q||(r.institution+" "+r.summary).toLowerCase().indexOf(q)>-1);
    }).sort(function(a,b){return a.date<b.date?1:-1});
  }
  function rowUrl(id){return location.href.split("#")[0]+"#"+id}
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
      m.appendChild(el("span",null,fmtAssets(r.assets_millions)));
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
    var states=Array.from(new Set(all.map(function(r){return r.state}))).sort();
    states.forEach(function(s){var o=el("option",null,s);o.value=s;$("f-state").appendChild(o)});
    ["f-type","f-state","f-charter","f-from","f-to"].forEach(function(id){$(id).addEventListener("change",function(){shown=PAGE;render()})});
    $("f-q").addEventListener("input",function(){shown=PAGE;render()});
    $("reset").addEventListener("click",function(){FILTERS.forEach(function(id){$(id).value=""});shown=PAGE;render()});
    render();
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
    if(idx<0){FILTERS.forEach(function(f){$(f).value=""});rows=filtered();idx=rows.findIndex(function(r){return r.id===id});render()}
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
