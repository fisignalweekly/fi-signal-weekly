// "New" tag: shown only on the America/New_York calendar day a row was published
// (r.added, YYYY-MM-DD). Drops off at midnight ET. "Today" is always Eastern Time,
// never the visitor's local zone or UTC. A now Date may be passed to stub the clock.
// Rows with backfill: true never show the tag, whatever their added value.
(function(root){
  function etToday(now){
    return new Intl.DateTimeFormat("en-CA",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit"}).format(now||new Date());
  }
  function isNew(r,now){return !!(r&&r.added)&&r.backfill!==true&&r.added===etToday(now)}
  var api={etToday:etToday,isNew:isNew};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  else root.FINew=api;
})(typeof globalThis!=="undefined"?globalThis:this);
