/* Run with: node tests/js/search.test.cjs. No packages or browser required. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/js/search.js"), "utf8");
const context = {window: {}, document: {getElementById: () => null}};
vm.runInNewContext(source, context);
const {formBody, duration, validVideoId, embedUrl} = context.window.tubeSearch;
const plain = value => JSON.parse(JSON.stringify(value));
let tests = 0;
function test(name, fn) { fn(); tests++; console.log(`PASS ${name}`); }
function mockForm(values = {}, chips = {}) {
  const defaults = {
    keyword:"  파이썬  ", pages:"2", order:"relevance", "video.tags.mode":"AND", "video.words.target":"BOTH", "video.regionCode":"KR", "video.shorts":"ANY", "video.includeNoLanguage":true,
  };
  const elements = Object.entries({...defaults,...values}).map(([name, value]) => {
    if (Array.isArray(value)) return {name, selectedOptions:value.map(value=>({value}))};
    if (typeof value === "boolean") return {name, checked:value, value:"on"};
    return {name, value};
  });
  const fields = Object.entries(chips).map(([name, {tokens=[], pending=""}]) => ({
    dataset:{chips:name},
    querySelector: () => ({value:pending}),
    querySelectorAll: () => tokens.map(token=>({dataset:{token}})),
  }));
  return {elements, querySelectorAll: () => fields};
}
test("video IDs reject injection, Unicode, whitespace, and newline suffixes", () => {
  for (const value of ["a", "abcdefghijk\n", "abcdefghijk/", "../abcdefgh", "<script>abc", 'abc\" onload', "１２３４５６７８９０１", null, 123]) {
    assert.equal(validVideoId(value),false, String(value)); assert.equal(embedUrl(value),null);
  }
  for (const value of ["abcdefghijk", "aB0_2-45678"]) {
    assert.equal(validVideoId(value),true);
    assert.equal(embedUrl(value),`https://www.youtube-nocookie.com/embed/${value}`);
  }
});
test("duration preserves seconds and rejects malformed mm:ss", () => {
  assert.equal(duration("7:03"),423); assert.equal(duration("180:00"),10800);
  for (const value of ["7:3","7:60","-1:00","7","1:02:03",""]) assert.throws(()=>duration(value));
});
test("empty filters preserve API defaults and omit optional conditions", () => {
  const body=plain(formBody(mockForm()));
  assert.equal(body.keyword,"파이썬"); assert.equal(body.pages,2); assert.equal(body.order,"relevance");
  assert.deepEqual(body.published,{}); assert.deepEqual(body.channel.activity,{});
  assert.deepEqual(body.video.excludeRestricted,{}); assert.equal(body.video.includeNoLanguage,true);
  assert.equal(body.video.relevanceLanguage,null); assert.deepEqual(body.video.views,{});
  assert.deepEqual(body.channel.created,{});
});
test("every range, server flag, date, language, category and restriction maps to API types", () => {
  const body=plain(formBody(mockForm({
    keyword:"x", pages:"5", order:"rating", "published.after":"2026-10-01", "published.before":"2026-11-01",
    "video.durationSec.min":"7:03", "video.durationSec.max":"15:00", "video.views.min":"1001", "video.likes.max":"500", "video.comments.min":"0", "video.likeRatePct.min":"2.25", "video.commentRatePct.max":"1.01",
    "video.hd":true, "video.caption":true, "video.cc":true, "video.embeddable":true, "video.excludeKids":true, "video.includeNoLanguage":false,
    "video.categoryIds.include":["27","10"], "video.categoryIds.exclude":["20"], "video.languages":["ko","en"],
    "video.regionCode":"US", "video.relevanceLanguage":"en", "video.hours.from":"22", "video.hours.to":"3",
    restrictEnabled:true, restrictedCountry:"JP", anyRestriction:true,
    "channel.subscribers.max":"9999", "channel.viewsPerSubPct.min":"100.25", "channel.videoCount.min":"1", "channel.avgViews.max":"1500.5",
    createdMode:"before", createdBefore:"2020-01-01", "channel.countries":["KR","__unset__"],
  })));
  assert.deepEqual(body.published,{after:"2026-10-01", before:"2026-11-01"});
  assert.deepEqual(body.video.durationSec,{min:423,max:900}); assert.deepEqual(body.video.views,{min:1001});
  assert.deepEqual(body.video.likes,{max:500}); assert.deepEqual(body.video.comments,{min:0});
  assert.deepEqual(body.video.likeRatePct,{min:2.25}); assert.deepEqual(body.video.commentRatePct,{max:1.01});
  for (const flag of ["hd","caption","cc","embeddable","excludeKids"]) assert.equal(body.video[flag],true);
  assert.equal(body.video.includeNoLanguage,false); assert.deepEqual(body.video.categoryIds,{include:[27,10],exclude:[20]});
  assert.deepEqual(body.video.languages,["ko","en"]); assert.deepEqual(body.video.hours,{from:22,to:3});
  assert.equal(body.video.regionCode,"US"); assert.equal(body.video.relevanceLanguage,"en");
  assert.deepEqual(body.video.excludeRestricted,{country:"JP",anyRestriction:true});
  assert.deepEqual(body.channel.subscribers,{max:9999}); assert.deepEqual(body.channel.viewsPerSubPct,{min:100.25});
  assert.deepEqual(body.channel.videoCount,{min:1}); assert.deepEqual(body.channel.avgViews,{max:1500.5});
  assert.deepEqual(body.channel.created,{before:"2020-01-01"}); assert.deepEqual(body.channel.countries,["KR",null]);
});
test("weekdays use Monday=0; radio selection and activity are numeric", () => {
  const form=mockForm({"channel.activity.windowDays":"60","channel.activity.countMin":"0","channel.activity.countMax":"4","channel.activity.lastUploadWithinDays":"90",createdMode:"withinDays",createdDays:"365"});
  form.elements.push({name:"video.weekdays",checked:true,value:"0"},{name:"video.weekdays",checked:false,value:"1"},{name:"video.weekdays",checked:true,value:"6"});
  form.elements.find(c=>c.name==="video.shorts").checked=false;
  form.elements.push({name:"video.shorts",checked:true,value:"EXCLUDE"});
  const body=plain(formBody(form));
  assert.deepEqual(body.video.weekdays,[0,6]); assert.equal(body.video.shorts,"EXCLUDE");
  assert.deepEqual(body.channel.activity,{windowDays:60,countMin:0,countMax:4,lastUploadWithinDays:90});
  assert.deepEqual(body.channel.created,{withinDays:365});
});
test("chip lists deduplicate pending input and preserve free-text safely", () => {
  const body=plain(formBody(mockForm({"video.tags.mode":"OR","video.words.target":"TITLE"},{
    "video.tags.include":{tokens:["python"],pending:" PYTHON "}, "video.tags.exclude":{tokens:["ad"]},
    "video.words.must":{tokens:["<img onerror=alert(1)>"]}, "video.words.not":{pending:" promo "},
  })));
  assert.deepEqual(body.video.tags,{include:["python"],exclude:["ad"],mode:"OR"});
  assert.deepEqual(body.video.words,{must:["<img onerror=alert(1)>"],not:["promo"],target:"TITLE"});
});
console.log(`${tests} JavaScript tests passed`);
