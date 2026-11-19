#!/usr/bin/env node
// 7-day ET "New" tag and the Latest added list (spec 06). Run: node scripts/test_newtag.js
var assert = require("assert");
var path = require("path");
var N = require(path.join(__dirname, "..", "js", "newtag.js"));
var B = require(path.join(__dirname, "..", "js", "boardrows.js"));
var etToday = N.etToday, isNew = N.isNew;
var n = 0;
function check(name, fn){ fn(); n++; console.log("ok", n, name); }
var at = function(s){ return new Date(s); };

// Nov 2026: EST (UTC-5); DST ended Nov 1. Mar 2027: DST starts Sun Mar 14.
check("etToday uses America/New_York, not UTC", function(){
  assert.strictEqual(etToday(at("2026-11-18T03:00:00Z")), "2026-11-17");   // 10 PM ET on the 17th
  assert.strictEqual(etToday(at("2026-11-18T00:01:00-05:00")), "2026-11-18");
});
check("added today is New", function(){ assert.strictEqual(isNew({added:"2026-11-19"}, at("2026-11-19T00:00:00-05:00")), true); });
check("day 7 (added 6 days ago) is New until 11:59 PM ET", function(){
  assert.strictEqual(isNew({added:"2026-11-13"}, at("2026-11-19T23:59:59-05:00")), true);
});
check("day 8: not New at 12:00 AM ET", function(){
  assert.strictEqual(isNew({added:"2026-11-13"}, at("2026-11-20T00:00:00-05:00")), false);
});
check("boundary is ET, not UTC (7 PM ET Nov 19 = 00:00 UTC Nov 20: added Nov 13 still New)", function(){
  assert.strictEqual(isNew({added:"2026-11-13"}, at("2026-11-20T00:00:00Z")), true);
});
check("added tomorrow (ET) is not New", function(){ assert.strictEqual(isNew({added:"2026-11-20"}, at("2026-11-19T23:59:00-05:00")), false); });
check("event date never matters, only added", function(){
  assert.strictEqual(isNew({added:"2026-11-19", date:"2026-03-02"}, at("2026-11-19T12:00:00-05:00")), true);
  assert.strictEqual(isNew({added:"2026-11-01", date:"2026-11-19"}, at("2026-11-19T12:00:00-05:00")), false);
});
check("backfill is never New, even added today", function(){
  assert.strictEqual(isNew({added:"2026-11-19", backfill:true}, at("2026-11-19T12:00:00-05:00")), false);
});
check("missing or malformed added is not New", function(){
  [{}, null, {added:""}, {added:"11/19/2026"}].forEach(function(r){ assert.strictEqual(isNew(r, at("2026-11-19T12:00:00-05:00")), false); });
});
check("window across the DST start stays 7 calendar days", function(){
  var now = at("2027-03-16T00:30:00-04:00");                       // EDT, 12:30 AM Mar 16
  assert.strictEqual(N.windowStart(now), "2027-03-10");
  assert.strictEqual(isNew({added:"2027-03-10"}, now), true);
  assert.strictEqual(isNew({added:"2027-03-09"}, now), false);
});
check("window across a month/year boundary", function(){
  assert.strictEqual(N.windowStart(at("2027-01-03T09:00:00-05:00")), "2026-12-28");
});
check("latestAdded: board rows only, New only, added desc, then event date desc, then id desc", function(){
  var now = at("2026-11-19T18:00:00-05:00");
  var rows = [
    {id:"t1", type:"merger", added:"2026-11-18", date:"2026-10-02"},
    {id:"t2", type:"merger", added:"2026-11-19", date:"2026-01-05"},
    {id:"t3", type:"executive", added:"2026-11-19", date:"2026-11-10"},
    {id:"t4", type:"executive", added:"2026-11-19", date:"2026-11-10"},
    {id:"t5", type:"executive", added:"2026-11-19", backfill:true, date:"2026-11-19"},
    {id:"t6", type:"executive", added:"2026-11-19", fi_only:true, date:"2026-11-19"},
    {id:"t7", type:"branch_opening", added:"2026-11-19", date:"2026-11-19"},
    {id:"t8", type:"core", added:"2026-11-12", date:"2026-11-12"}
  ];
  assert.deepStrictEqual(N.latestAdded(B.boardRows(rows), now).map(function(r){return r.id}), ["t4","t3","t2","t1"]);
});
check("live data: Latest added never contains backfill, fi_only or branch_opening rows", function(){
  var rows = require(path.join(__dirname, "..", "data", "triggers.json")).rows;
  var now = at("2026-11-19T18:00:00-05:00");
  var l = N.latestAdded(B.boardRows(rows), now);
  assert.ok(l.every(function(r){ return r.backfill !== true && r.fi_only !== true && r.type !== "branch_opening"; }));
  console.log("   live rows in window at Nov 19 6 PM ET:", l.length);
});
