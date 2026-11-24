/* /vendor-changes/ (spec 08): countdown to each effective date (ET calendar days) and the affected-list filter.
   Progressive: without this file every row is still in the HTML, behind "Show N more" (<details>). */
(function(){
  function etToday(){return new Intl.DateTimeFormat("en-CA",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date())}
  function days(a,b){var p=a.split("-"),q=b.split("-");return Math.round((Date.UTC(+q[0],+q[1]-1,+q[2])-Date.UTC(+p[0],+p[1]-1,+p[2]))/864e5)}
  var today=etToday();
  [].forEach.call(document.querySelectorAll(".vc-cd[data-eff]"),function(el){
    var n=days(today,el.getAttribute("data-eff"));
    el.textContent=n>1?n+" days away":n===1?"Tomorrow":n===0?"Today":"";   // past: date only (the slot stays reserved)
  });

  var params=new URLSearchParams(location.search),pq=(params.get("q")||"").slice(0,100),ps=(params.get("state")||"").toUpperCase();
  [].forEach.call(document.querySelectorAll(".vc-entry"),function(entry){
    var bar=entry.querySelector(".vc-filter");if(!bar)return;
    var q=bar.querySelector("input"),st=bar.querySelector("select"),cnt=bar.querySelector(".vc-count"),total=+bar.getAttribute("data-total");
    var groups=[].slice.call(entry.querySelectorAll(".vc-group")),
        more=[].slice.call(entry.querySelectorAll("details.vc-more")),wasOpen=more.map(function(d){return d.open});
    function norm(s){return s.toLowerCase().replace(/\s+/g," ").trim()}
    function apply(){
      var t=norm(q.value),s=st.value,on=!!(t||s),seen={};
      entry.classList.toggle("is-filtering",on);
      more.forEach(function(d,i){d.open=on?true:wasOpen[i]});          // filtering searches every row
      groups.forEach(function(g){
        var any=false;
        [].forEach.call(g.querySelectorAll("li[data-k]"),function(li){
          var ok=(!s||li.getAttribute("data-st")===s)&&(!t||li.getAttribute("data-k").indexOf(t)>-1);
          li.hidden=on&&!ok;if(ok){any=true;if(on)seen[li.getAttribute("data-id")]=1}
        });
        g.hidden=on&&!any;
      });
      var n=Object.keys(seen).length;
      cnt.textContent=!on?"":n?n+" of "+total+" institutions":"No institutions match. Try a shorter name or fewer filters.";
      var u=new URL(location.href);t?u.searchParams.set("q",q.value.trim()):u.searchParams.delete("q");s?u.searchParams.set("state",s):u.searchParams.delete("state");
      history.replaceState(null,"",u.pathname+u.search+u.hash);
    }
    more.forEach(function(d,i){d.addEventListener("toggle",function(){if(!entry.classList.contains("is-filtering"))wasOpen[i]=d.open})});
    q.addEventListener("input",apply);st.addEventListener("change",apply);
    if(pq)q.value=pq;
    if(ps&&[].some.call(st.options,function(o){return o.value===ps}))st.value=ps;
    bar.classList.add("ready");
    if(q.value||st.value)apply();
  });
})();
