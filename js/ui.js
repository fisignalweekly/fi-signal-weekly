// Mobile filter toggle: on phones the filters collapse behind a "Filters" button that shows how many are active.
// On desktop (>=760px) the button is hidden by CSS and the filters are always open. Kept separate from app.js;
// it only reads the filter controls' values and refreshes when app.js re-renders the board (the #count line).
(function(){
  var t=document.getElementById("filters-toggle"),box=document.getElementById("filters");
  if(!t||!box)return;
  var panel=t.parentNode,cnt=document.getElementById("filters-count");
  function active(){return [].filter.call(box.querySelectorAll("select,input"),function(e){return e.value&&e.value.trim()}).length}
  function update(){
    var n=active();
    cnt.hidden=!n;cnt.textContent=n?n+" active":"";
  }
  t.addEventListener("click",function(){
    var open=!panel.classList.contains("open");
    panel.classList.toggle("open",open);t.setAttribute("aria-expanded",open?"true":"false");
  });
  box.addEventListener("change",update);box.addEventListener("input",update);
  box.addEventListener("click",function(){setTimeout(update,0)});
  var c=document.getElementById("count");
  if(c&&window.MutationObserver)new MutationObserver(update).observe(c,{childList:true,characterData:true,subtree:true});
  update();
})();
