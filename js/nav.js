/* Phone menu. Progressive: without this file the header shows inline links only. */
(function(){
  var h=document.querySelector("header.site"),n=h&&h.querySelector("nav"),b=h&&h.querySelector(".nav-toggle");
  if(!n||!b)return;
  var root=document.documentElement,mq=matchMedia("(max-width:599px)");
  var s=document.createElement("div");s.id="site-menu";s.className="menu-sheet";s.hidden=true;
  s.setAttribute("role","dialog");s.setAttribute("aria-modal","true");s.setAttribute("aria-labelledby","nav-toggle");
  [].forEach.call(n.querySelectorAll("a"),function(a){s.appendChild(a.cloneNode(true))}); /* same links, same copy */
  var sc=document.createElement("div");sc.className="menu-scrim";sc.hidden=true;
  h.parentNode.insertBefore(sc,h.nextSibling);h.parentNode.insertBefore(s,h.nextSibling);
  function inert(on){[].forEach.call(document.body.children,function(el){
    if(el===h||el===s||el===sc||el.tagName==="SCRIPT")return;on?el.setAttribute("inert",""):el.removeAttribute("inert")})}
  function open(){s.hidden=sc.hidden=false;b.setAttribute("aria-expanded","true");root.classList.add("menu-open");inert(true);
    var f=s.querySelector("a");if(f)f.focus()}
  function close(refocus){if(s.hidden)return;s.hidden=sc.hidden=true;b.setAttribute("aria-expanded","false");
    root.classList.remove("menu-open");inert(false);if(refocus!==false)b.focus()}
  b.addEventListener("click",function(){s.hidden?open():close()});
  sc.addEventListener("click",function(){close()});
  s.addEventListener("click",function(e){if(e.target.closest("a"))close(false)});
  document.addEventListener("keydown",function(e){
    if(s.hidden)return;
    if(e.key==="Escape"){e.preventDefault();close();return}
    if(e.key!=="Tab")return;
    var f=[b].concat([].slice.call(s.querySelectorAll("a"))),i=f.indexOf(document.activeElement);
    if(e.shiftKey&&i<=0){e.preventDefault();f[f.length-1].focus()}
    else if(!e.shiftKey&&(i===f.length-1||i<0)){e.preventDefault();f[0].focus()}
  });
  (mq.addEventListener?mq.addEventListener.bind(mq,"change"):mq.addListener.bind(mq))(function(){if(!mq.matches)close(false)});
  /* active page: page links only (hash links like #board are never "current") */
  var here=location.pathname.replace(/index\.html$/,"");
  [].forEach.call(document.querySelectorAll("header.site nav a,#site-menu a"),function(a){
    var u=new URL(a.getAttribute("href"),location.href);if(u.origin!==location.origin||u.hash)return;
    var p=u.pathname.replace(/index\.html$/,"");
    if(p!=="/"&&(p===here||(p.slice(-1)==="/"&&here.indexOf(p)===0)))a.setAttribute("aria-current","page")});
  b.hidden=false;h.classList.add("has-menu");
})();
