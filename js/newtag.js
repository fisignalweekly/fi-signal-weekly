// "New" tag + "Latest added" window (spec 06): a row is New for 7 Eastern-time calendar days, counting the day it
// was published (r.added, YYYY-MM-DD) as day 1. Added on Nov 13 => New from 12:00 AM ET Nov 13 through 11:59 PM ET
// Nov 19; gone at 12:00 AM ET Nov 20. "Today" is always America/New_York, never the visitor's zone or UTC.
// Calendar-day math on YYYY-MM-DD strings, so DST changes can't shift the boundary. A now Date may be passed to stub the clock.
// Rows with backfill: true never show the tag and never appear in Latest added, whatever their added value.
// Rows with an added date after today (ET) are not New.
(function(root){
  var NEW_DAYS=7;
  function etToday(now){
    return new Intl.DateTimeFormat("en-CA",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit"}).format(now||new Date());
  }
  function addDays(ymd,n){var p=ymd.split("-");return new Date(Date.UTC(+p[0],+p[1]-1,+p[2]+n)).toISOString().slice(0,10)}
  function windowStart(now){return addDays(etToday(now),-(NEW_DAYS-1))}       // first ET day still inside the window
  function isNew(r,now){
    if(!r||!r.added||r.backfill===true||!/^\d{4}-\d{2}-\d{2}$/.test(r.added))return false;
    var t=etToday(now);return r.added>=addDays(t,-(NEW_DAYS-1))&&r.added<=t;
  }
  // Latest added: board rows (caller passes FIBoard.boardRows output) that are New, newest added first,
  // then newest event date, then highest id (stable order for rows added the same day).
  function latestAdded(rows,now){
    return (rows||[]).filter(function(r){return isNew(r,now)}).sort(function(a,b){
      if(a.added!==b.added)return a.added<b.added?1:-1;
      if(a.date!==b.date)return a.date<b.date?1:-1;
      return (+String(b.id).slice(1)||0)-(+String(a.id).slice(1)||0);
    });
  }
  var api={NEW_DAYS:NEW_DAYS,etToday:etToday,addDays:addDays,windowStart:windowStart,isNew:isNew,latestAdded:latestAdded};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  else root.FINew=api;
})(typeof globalThis!=="undefined"?globalThis:this);
