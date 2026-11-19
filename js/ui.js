// Board UI. Replaces the old filter toggle. Reads app.js's controls and #count; never touches row data.
// Phone (<760): #filters opens as a bottom sheet from the sticky bar. Desktop: the filters stay inline, as before.
(function(){
  var $=function(id){return document.getElementById(id)};
  var t=$("filters-toggle"),box=$("filters");
  if(!t||!box)return;
  var panel=t.closest(".filters-panel"),cnt=$("filters-count"),count=$("count"),cards=$("cards"),root=document.documentElement;
  var mq=matchMedia("(max-width:759px)");
  // ---- active-filter count on the Filters button (search is in the bar, so it is not counted) ----
  function active(){return [].filter.call(box.querySelectorAll("select,input:not([type=checkbox])"),function(e){return e.value&&e.value.trim()}).length}
  function update(){var n=active();cnt.hidden=!n;cnt.textContent=n?n+" active":"";chips();mirror()}
  // ---- bottom sheet ----
  var scrim=document.createElement("div");scrim.className="sheet-scrim";scrim.hidden=true;panel.insertBefore(scrim,box);  /* same stacking context as the sheet (sticky creates one) */
  box.setAttribute("aria-modal","true");
  var inerted=[];
  function inert(on){
    if(!on){inerted.forEach(function(e){e.removeAttribute("inert")});inerted=[];return}
    for(var n=box;n&&n!==document.body;n=n.parentNode){[].forEach.call(n.parentNode.children,function(s){
      if(s!==n&&s!==scrim&&s.tagName!=="SCRIPT"&&!s.hasAttribute("inert")){s.setAttribute("inert","");inerted.push(s)}})}
  }
  function isOpen(){return panel.classList.contains("open")}
  function open(){
    panel.classList.add("open");t.setAttribute("aria-expanded","true");
    if(!mq.matches)return;                       // desktop: nothing else (toggle is hidden there anyway)
    scrim.hidden=false;root.classList.add("sheet-open");inert(true);t.setAttribute("inert","");
    var f=box.querySelector("select,button,input:not([type=hidden])");if(f)f.focus({preventScroll:true});
  }
  function close(refocus){
    if(!isOpen())return;
    panel.classList.remove("open");t.setAttribute("aria-expanded","false");
    scrim.hidden=true;root.classList.remove("sheet-open");inert(false);t.removeAttribute("inert");
    if(refocus!==false)t.focus({preventScroll:true});
  }
  t.addEventListener("click",function(){isOpen()?close():open()});
  scrim.addEventListener("click",function(){close()});
  $("filters-done").addEventListener("click",function(){close()});
  [].forEach.call(box.querySelectorAll(".view-chip"),function(a){a.addEventListener("click",function(){if(mq.matches)setTimeout(function(){close()},0)})});
  window.addEventListener("keydown",function(e){            // capture: runs before app.js's state-picker Esc
    if(!isOpen()||!mq.matches)return;
    var pop=$("f-state-pop");if(pop&&!pop.hidden)return;     // let the state picker close first
    if(e.key==="Escape"){e.preventDefault();close();return}
    if(e.key!=="Tab")return;
    var f=[].filter.call(box.querySelectorAll("a[href],button,select,input:not([type=hidden])"),function(x){return x.offsetParent!==null}),
        i=f.indexOf(document.activeElement);
    if(e.shiftKey&&i<=0){e.preventDefault();f[f.length-1].focus()}
    else if(!e.shiftKey&&(i<0||i===f.length-1)){e.preventDefault();f[0].focus()}
  },true);
  (mq.addEventListener?mq.addEventListener.bind(mq,"change"):mq.addListener.bind(mq))(function(){if(!mq.matches)close(false)});
  // ---- result count in the sheet footer (same text as #count) ----
  function mirror(){var s=$("sheet-count");if(s&&count)s.textContent=count.textContent}
  // ---- search clear ----
  var q=$("f-q"),qc=$("q-clear");
  function qSync(){qc.hidden=!q.value}
  q.addEventListener("input",qSync);
  q.addEventListener("keydown",function(e){if(e.key==="Enter"){q.blur()}});   // "Search" key closes the keyboard
  qc.addEventListener("click",function(){q.value="";q.dispatchEvent(new Event("input",{bubbles:true}));qSync();q.focus()});
  // ---- active filter chips (labels/values are the page's own option text) ----
  function optText(id){var s=$(id);return s.value?s.options[s.selectedIndex].text:""}
  function fmt(d){var p=d.split("-");return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString("en-US",{year:"numeric",month:"short",day:"numeric"})}
  function money(v){var b=v/1e9;return b>=1?"$"+(+b.toFixed(1))+"B+":"$"+Math.round(v/1e6)+"M+"}
  function label(id){var l=document.querySelector('label[for="'+id+'"]');return l?l.textContent.trim():""}
  function clearOne(id){
    if(id==="f-state"){$("f-state-all").click();return}
    var e=$(id);e.value="";
    if(id==="f-q"){e.dispatchEvent(new Event("input",{bubbles:true}));qSync();return}
    (e.type==="hidden"?$("f-type"):e).dispatchEvent(new Event("change",{bubbles:true}));
  }
  var X='<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path d="M7 7l10 10M17 7L7 17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
  function chips(){
    var wrap=$("active-chips");if(!wrap)return;
    var list=[];
    if($("f-type").value)list.push(["f-type",optText("f-type")]);
    if($("f-state").value)list.push(["f-state",$("f-state-text").textContent]);
    if($("f-charter").value)list.push(["f-charter",optText("f-charter")]);
    if($("f-assets").value)list.push(["f-assets",optText("f-assets")]);
    if($("f-assets-min").value)list.push(["f-assets-min",money(+$("f-assets-min").value)]);
    if($("f-tz").value)list.push(["f-tz","Eastern Time"]);
    if($("f-from").value)list.push(["f-from",label("f-from")+" "+fmt($("f-from").value)]);
    if($("f-to").value)list.push(["f-to",label("f-to")+" "+fmt($("f-to").value)]);
    if(q.value.trim())list.push(["f-q",label("f-q")+": "+q.value.trim()]);
    var sig=JSON.stringify(list);if(wrap.dataset.sig===sig)return;wrap.dataset.sig=sig;
    wrap.textContent="";wrap.hidden=!list.length;
    list.forEach(function(c){
      var b=document.createElement("button");b.type="button";b.className="achip";
      b.innerHTML='<span class="vh">Remove </span><span></span>'+X;b.children[1].textContent=c[1];
      b.addEventListener("click",function(){clearOne(c[0])});wrap.appendChild(b);
    });
    if(list.length>1){var r=document.createElement("button");r.type="button";r.className="achip clear-all";r.textContent=$("reset").textContent;
      r.addEventListener("click",function(){$("reset").click()});wrap.appendChild(r)}
  }
  // ---- cards: 3-line summary with More / Less, empty-state Reset, open the #tNNN row ----
  function decorate(){
    cards.removeAttribute("aria-busy");
    [].forEach.call(cards.querySelectorAll("li.card:not([data-ui])"),function(li){
      li.setAttribute("data-ui","");var p=li.querySelector(":scope > p");if(!p)return;
      p.classList.add("clampable");
      if(p.scrollHeight<=p.clientHeight+2){p.classList.remove("clampable");return}
      var b=document.createElement("button");b.type="button";b.className="more";b.textContent="More";b.setAttribute("aria-expanded","false");
      b.addEventListener("click",function(){var o=li.classList.toggle("open");b.textContent=o?"Less":"More";b.setAttribute("aria-expanded",o?"true":"false")});
      li.appendChild(b);
    });
    var em=cards.querySelector("li.empty:only-child");
    if(em&&!em.querySelector("button")&&active()+(q.value.trim()?1:0)>0){
      var d=document.createElement("div");d.className="empty-actions";var r=document.createElement("button");r.type="button";r.className="ghost";
      r.textContent=$("reset").textContent;r.addEventListener("click",function(){$("reset").click()});d.appendChild(r);em.appendChild(d);
    }
    var m=/^#(t\d+)$/i.exec(location.hash||""),c=m&&document.getElementById(m[1].toLowerCase());
    if(c){c.classList.add("open");var mb=c.querySelector(".more");if(mb){mb.textContent="Less";mb.setAttribute("aria-expanded","true")}}
  }
  box.addEventListener("change",update);box.addEventListener("input",update);
  box.addEventListener("click",function(){setTimeout(update,0)});
  if(window.MutationObserver){
    new MutationObserver(update).observe(count,{childList:true,characterData:true,subtree:true});
    new MutationObserver(decorate).observe(cards,{childList:true});
  }
  window.addEventListener("hashchange",function(){setTimeout(decorate,0)});
  update();qSync();
})();
