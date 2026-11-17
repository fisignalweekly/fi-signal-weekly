#!/usr/bin/env node
// Same-day ET "New" tag. Run: node scripts/test_newtag.js
var assert = require("assert");
var path = require("path");
var {etToday, isNew} = require(path.join(__dirname, "..", "js", "newtag.js"));

var n = 0;
function check(name, fn){
  fn();
  n++;
  console.log("ok", n, name);
}

// 17 Nov 2026 is a Tuesday; EST (UTC-5) is in effect (DST ended 1 Nov).
var today = "2026-11-17";
var yesterday = "2026-11-16";
var midEvening = new Date("2026-11-17T23:59:00-05:00"); // 11:59 PM ET
var justAfter = new Date("2026-11-18T00:01:00-05:00");  // 12:01 AM ET
var utcAlreadyTomorrow = new Date("2026-11-18T03:00:00Z"); // 10:00 PM ET on the 17th

check("etToday at 11:59 PM ET is that calendar day", function(){
  assert.strictEqual(etToday(midEvening), today);
});
check("etToday at 12:01 AM ET is the next calendar day", function(){
  assert.strictEqual(etToday(justAfter), "2026-11-18");
});
check("etToday uses America/New_York, not UTC (10 PM ET is still the 17th when UTC is the 18th)", function(){
  assert.strictEqual(etToday(utcAlreadyTomorrow), today);
});

check("row added today is New during that ET day", function(){
  assert.strictEqual(isNew({added: today, date: yesterday}, midEvening), true);
});
check("row added yesterday is not New, even if the event date is today", function(){
  assert.strictEqual(isNew({added: yesterday, date: today}, midEvening), false);
});
check("row added today is not New at 12:01 AM ET the next day", function(){
  assert.strictEqual(isNew({added: today}, justAfter), false);
});
check("row added tomorrow is not New at 11:59 PM ET", function(){
  assert.strictEqual(isNew({added: "2026-11-18"}, midEvening), false);
});
check("missing added is not New", function(){
  assert.strictEqual(isNew({date: today}, midEvening), false);
  assert.strictEqual(isNew({}, midEvening), false);
  assert.strictEqual(isNew(null, midEvening), false);
});

// Default path (no now arg) follows a stubbed Date, as the live check does.
var RealDate = Date;
var frozen = new Date("2026-11-18T00:01:00-05:00").getTime();
function FakeDate(){
  if(arguments.length===0) return new RealDate(frozen);
  var args = arguments;
  if(args.length===1) return new RealDate(args[0]);
  return new RealDate(args[0], args[1], args[2]||0, args[3]||0, args[4]||0, args[5]||0, args[6]||0);
}
FakeDate.now = function(){return frozen};
FakeDate.parse = RealDate.parse;
FakeDate.UTC = RealDate.UTC;
FakeDate.prototype = RealDate.prototype;
global.Date = FakeDate;
try{
  check("stubbed Date at 12:01 AM ET 18 Nov: etToday is the 18th and today's rows are not New", function(){
    assert.strictEqual(etToday(), "2026-11-18");
    assert.strictEqual(isNew({added: today}), false);
    assert.strictEqual(isNew({added: "2026-11-18"}), true);
  });
}finally{
  global.Date = RealDate;
}

console.log(n+" checks passed");
