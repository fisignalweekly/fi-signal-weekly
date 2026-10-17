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
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
  function render(){
    var t=$("f-type").value,s=$("f-state").value,from=$("f-from").value,to=$("f-to").value,q=$("f-q").value.trim().toLowerCase();
    var rows=all.filter(function(r){
      return (!t||r.type===t)&&(!s||r.state===s)&&(!from||r.date>=from)&&(!to||r.date<=to)&&
        (!q||(r.institution+" "+r.summary).toLowerCase().indexOf(q)>-1);
    }).sort(function(a,b){return a.date<b.date?1:-1});
    var list=$("cards");list.textContent="";
    $("count").textContent=rows.length>shown?"Showing "+shown+" of "+rows.length+" matching triggers ("+all.length+" total)":rows.length+" of "+all.length+" triggers";
    if(!rows.length){var li=el("li","empty","No triggers match these filters.");list.appendChild(li);return}
    rows.slice(0,shown).forEach(function(r){
      var li=el("li","card "+r.type);
      li.appendChild(el("h3",null,r.institution));
      var m=el("div","meta");
      m.appendChild(el("span","badge "+r.type,TYPE_LABEL[r.type]||r.type));
      m.appendChild(el("span",null,r.state));
      m.appendChild(el("span",null,fmtAssets(r.assets_millions)));
      m.appendChild(el("span",null,fmtDate(r.date)));
      li.appendChild(m);
      li.appendChild(el("p",null,r.summary));
      var a=el("a","src","Source ↗");a.href=r.source_url;a.target="_blank";a.rel="noopener noreferrer";
      li.appendChild(a);
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
    ["f-type","f-state","f-from","f-to"].forEach(function(id){$(id).addEventListener("change",function(){shown=PAGE;render()})});
    $("f-q").addEventListener("input",function(){shown=PAGE;render()});
    $("reset").addEventListener("click",function(){["f-type","f-state","f-from","f-to","f-q"].forEach(function(id){$(id).value=""});shown=PAGE;render()});
    render();
  }
  if($("cards")){
    fetch("data/triggers.json").then(function(r){return r.json()}).then(init).catch(function(){
      $("cards").textContent="";$("cards").appendChild(el("li","empty","Couldn't load data/triggers.json. Serve the site over HTTP (e.g. python3 -m http.server)."));
    });
  }
})();
