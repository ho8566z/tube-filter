/* node tests/js/personal.test.cjs — built-in modules and mock DOM only. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.join(__dirname,"../..");
const read = file => fs.readFileSync(path.join(root,file),"utf8");
const plain = value => JSON.parse(JSON.stringify(value));
class Element {
  constructor(tag="div") { this.tagName=tag.toUpperCase(); this.children=[]; this.listeners={}; this.dataset={}; this.attrs={}; this.value=""; this.type=""; this.hidden=false; this.disabled=false; this.checked=false; this.multiple=false; this.validity={valid:true}; this._text=""; }
  set textContent(value) { this._text=String(value); this.children=[]; }
  get textContent() { return this._text + this.children.map(c=>c.textContent).join(""); }
  set innerHTML(value) { throw Error("Unsafe API string rendering"); }
  append(...children) { for (const child of children) { child.parent=this; this.children.push(child); } }
  replaceChildren(...children) { this._text=""; this.children=[]; this.append(...children); }
  remove() { if(this.parent) this.parent.children=this.parent.children.filter(c=>c!==this); }
  setAttribute(key,value) { this.attrs[key]=String(value); }
  hasAttribute(key) { return key in this.attrs; }
  addEventListener(key,fn) { (this.listeners[key] ||= []).push(fn); }
  async fire(key,extra={}) { for (const fn of this.listeners[key] || []) await fn({preventDefault(){},currentTarget:this,target:this,...extra}); }
  dispatchEvent(event) { this.fire(event.type); }
  focus() { this.focused=true; }
  showModal() { this.open=true; }
  close() { this.open=false; this.fire("close"); }
  reportValidity() { return true; }
  reset() { for(const el of this.elements || []) { el.value=el.defaultValue ?? ""; el.checked=el.defaultChecked ?? false; for(const option of el.options || []) option.selected=false; } }
  get options() { return this._options || this.children.filter(c=>c.tagName==="OPTION"); }
  set options(value) { this._options=value; }
  get selectedOptions() { return this.options.filter(o=>o.selected); }
  matches(selector) {
    if(selector.startsWith(".")) return (this.className || "").split(" ").includes(selector.slice(1));
    if(selector.startsWith("#")) return this.id===selector.slice(1);
    const m=selector.match(/^(\w+)?(?:\[([^=\]]+)(?:="([^"]*)")?\])?$/);
    if(!m) return false;
    if(m[1] && this.tagName!==m[1].toUpperCase()) return false;
    if(!m[2]) return true;
    const name=m[2].replace(/^data-/,"").replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
    const value=m[2].startsWith("data-") ? this.dataset[name] : this[m[2]] || this.attrs[m[2]];
    return m[3]===undefined ? value!==undefined : value===m[3];
  }
  querySelectorAll(selector) { return this.children.flatMap(c=>[...(selector.split(/,\s*/).some(s=>c.matches(s)) ? [c] : []),...c.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) || null; }
}
function control(name,value="",type="text",tag="input") { const e=new Element(tag); e.name=name; e.type=type; e.value=String(value); e.defaultValue=e.value; return e; }
function form(controls=[]) { const e=new Element("form"); e.elements=controls; controls.namedItem=name=>controls.find(e=>e.name===name); e.append(...controls); return e; }
const settle = () => require("node:timers/promises").setImmediate();
function environment(page,member=true,query="") {
  const ids={};
  for(const file of ["base","personal","player",page==="search" ? "home" : page]) {
    for(const m of read(`app/templates/${file}.html`).matchAll(/<([\w-]+)[^>]*?\sid="([^"]+)"/g)) { const e=new Element(m[1]); e.id=m[2]; ids[m[2]]=e; }
  }
  // Optional elements must be absent, as in the server-rendered template.
  if(page==="search") delete ids["personal-page"]; else { ids["personal-page"].dataset={page:page==="channel" ? "channel" : page,channelId:"UC-demo"}; delete ids["search-form"]; }
  const body=new Element("body"); body.dataset.member=String(member);
  const document={body,title:"",createElement:tag=>new Element(tag),getElementById:id=>ids[id] || null,querySelectorAll:()=>[],querySelector:()=>({content:"csrf-test"})};
  const calls=[], routes=new Map(), charts=[];
  const defaultQuota={usedUnits:0,softLimitUnits:9000,resetAt:"2026-11-11T08:00:00Z"};
  routes.set("GET /api/v1/quota",defaultQuota);
  routes.set("GET /api/v1/favorites?page=0&size=50",{items:[],totalPages:0});
  routes.set("GET /api/v1/meta?regionCode=KR",{categories:[],languages:[],countries:[],limits:{maxTags:30,maxWords:20}});
  const window={location:{search:query,assign(url){this.assigned=url;}},matchMedia:()=>({matches:false,addEventListener(){}})};
  const context={window,document,console,Headers,URL,URLSearchParams,Intl,Event:class{constructor(type){this.type=type;}},Option:class extends Element{constructor(text,value){super("option");this.textContent=text;this.value=value;}},setTimeout:()=>1,clearTimeout(){},Chart:class {constructor(el,config){this.config=config;charts.push(this);} destroy(){this.destroyed=true;}},fetch:async(url,options={})=>{
    const method=options.method || "GET"; calls.push({url,method,...options});
    let result=routes.get(`${method} ${url}`);
    if(typeof result==="function") result=await result(options);
    if(result===undefined) throw Error(`Unexpected request: ${method} ${url}`);
    const status=result?.__status || (result===null ? 204 : 200);
    return {status,ok:status<400,json:async()=>result?.__body || result};
  }};
  const run=name=>vm.runInNewContext(read(`app/static/js/${name}.js`),context,{filename:`${name}.js`});
  const start=()=>{run("common");run("search");if(page!=="search")run("personal");};
  return {ids,body,document,window,context,calls,routes,charts,run,start};
}
function searchEnvironment(member=true,query="") {
  const e=environment("search",member,query);
  const controls=[control("keyword","유지"),control("pages",2,"","select"),control("order","relevance","","select"),control("video.regionCode","KR","","select"),control("video.tags.mode","AND","","select"),control("video.words.target","BOTH","","select"),control("createdMode","","","select"),control("createdDays"),control("createdBefore","","date"),control("restrictEnabled","","checkbox"),control("anyRestriction","","checkbox"),control("restrictedCountry","KR","","select"),control("channel.activity.windowDays",30,"","select"),control("resultSort","publishedAt","","select"),control("resultOrder","desc","","select"),control("resultSize",20,"","select")];
  e.ids["search-form"]=form(controls); return e;
}
const video={videoId:"abcdefghijk",title:'<img onerror="x">',channelId:"UC/<unsafe>",channelTitle:"<script>channel</script>",publishedAt:"2026-10-01T15:00:00Z",durationSec:423,stats:{views:12,likes:null,comments:1},channel:{subscribers:null},calc:{likeRatePct:null,commentRatePct:1,viewsPerSubPct:null}};
const condition={pages:3,order:"date",published:{after:"2026-09-30T15:00:00+00:00"},video:{durationSec:{min:423},views:{min:1001},tags:{include:["<b>x</b>"]},weekdays:[0,6],shorts:"ONLY",includeNoLanguage:true,excludeRestricted:{country:"JP",anyRestriction:true},languages:["ko"],categoryIds:{include:[27]},regionCode:"KR"},channel:{created:{before:"2020-01-01T15:00:00Z"},countries:["KR",null],activity:{countMin:0,windowDays:60}}};
let count=0;
async function test(name,fn) { await fn(); count++; console.log(`PASS ${name}`); }
function changes(e) { return e.calls.filter(c=>!["GET","HEAD"].includes(c.method)); }
function csrf(e) { for(const call of changes(e)) { assert.equal(call.headers.get("X-CSRF-Token"),"csrf-test"); assert.equal(call.credentials,"same-origin"); } }
globalThis.testRun=(async()=>{
  await test("shared cards activate channel links, favorite PUT/DELETE, safe text and player cleanup",async()=>{
    const e=environment("favorites"); e.run("common"); e.run("search");
    e.routes.set("PUT /api/v1/favorites/abcdefghijk",null); e.routes.set("DELETE /api/v1/favorites/abcdefghijk",null);
    const card=e.window.tubeSearch.videoCard(video); await settle();
    assert.equal(card.querySelector("h3").textContent,video.title);
    assert.equal(card.querySelector("a").href,"/channels/UC%2F%3Cunsafe%3E");
    const buttons=card.querySelectorAll("button"), favorite=buttons.at(-1);
    await favorite.fire("click"); assert.equal(favorite.attrs["aria-pressed"],"true");
    await favorite.fire("click"); assert.equal(favorite.attrs["aria-pressed"],"false"); csrf(e);
    await buttons[0].fire("click"); assert.equal(e.ids["player-modal"].open,true);
    assert.equal(e.ids["player-container"].children[0].src,"https://www.youtube-nocookie.com/embed/abcdefghijk");
    await e.ids["player-modal"].fire("cancel"); assert.equal(e.ids["player-container"].children.length,0);
  });
  await test("existing favorite on later API page initializes filled and removes; limit failure preserves state",async()=>{
    const e=environment("favorites"); e.run("common");e.run("search");
    e.routes.set("GET /api/v1/favorites?page=0&size=50",{items:[],totalPages:2}); e.routes.set("GET /api/v1/favorites?page=1&size=50",{items:[video],totalPages:2});
    e.routes.set("DELETE /api/v1/favorites/abcdefghijk",null);
    const b=e.window.tubeSearch.videoCard(video).querySelectorAll("button").at(-1); await settle(); assert.equal(b.attrs["aria-pressed"],"true");
    await b.fire("click"); assert.equal(b.attrs["aria-pressed"],"false");
    e.routes.set("PUT /api/v1/favorites/abcdefghijk",{__status:400,__body:{code:"FAVORITE_LIMIT",message:"최대 200개"}});
    await b.fire("click"); assert.equal(b.attrs["aria-pressed"],"false");assert.match(e.ids["global-message"].textContent,/200/);
  });
  await test("guest search preset and favorite actions show login links without mutation",async()=>{
    const e=searchEnvironment(false);e.start();await settle();
    await e.ids["save-preset"].fire("click");await e.ids["load-presets"].fire("click");
    assert.equal(e.ids["preset-message"].querySelector("a").href,"/login");
    await e.window.tubeSearch.videoCard(video).querySelectorAll("button").at(-1).fire("click");
    assert.equal(e.ids["global-message"].querySelector("a").href,"/login");assert.equal(changes(e).length,0);
  });
  await test("search saves keyword-free presets, displays duplicate errors and loads without executing search",async()=>{
    const e=searchEnvironment();e.routes.set("GET /api/v1/presets",[{id:3,name:"<b>preset</b>"}]);e.routes.set("GET /api/v1/presets/3",{conditions:condition});
    e.routes.set("POST /api/v1/presets",{id:3});e.start();await settle();
    await e.ids["save-preset"].fire("click"); assert.equal(e.ids["preset-save"].hidden,false);e.ids["preset-name"].value="test";
    await e.ids["submit-preset"].fire("click"); const saved=JSON.parse(changes(e)[0].body);assert.equal(saved.name,"test");assert.equal("keyword" in saved.conditions,false);csrf(e);
    e.routes.set("POST /api/v1/presets",{__status:409,__body:{message:"같은 이름의 프리셋"}});await e.ids["submit-preset"].fire("click");assert.match(e.ids["preset-message"].textContent,/같은 이름/);
    await e.ids["load-presets"].fire("click");const b=e.ids["preset-options"].children[0];assert.equal(b.textContent,"<b>preset</b>");await b.fire("click");
    assert.equal(e.ids["search-form"].elements.namedItem("pages").value,"3");assert.equal(e.ids["search-form"].elements.namedItem("keyword").value,"유지");assert.match(e.ids["preset-message"].textContent,/검색을 눌러/);
    assert.equal(e.calls.some(c=>c.url==="/api/v1/search"),false);
  });
  await test("query links restore history keyword and preset conditions without automatic search",async()=>{
    for(const kind of ["history","preset"]) {
      const e=searchEnvironment(true,`?${kind}=7`);e.routes.set("GET /api/v1/history",[{id:7,keyword:"<script>keyword</script>",conditions:condition}]);e.routes.set("GET /api/v1/presets/7",{conditions:condition});e.start();await settle();
      assert.equal(e.ids["search-form"].elements.namedItem("pages").value,"3");assert.equal(e.ids["search-form"].elements.namedItem("keyword").value,kind==="history" ? "<script>keyword</script>" : "유지");assert.equal(e.calls.some(c=>c.url==="/api/v1/search"),false);
    }
  });
  await test("restoration maps KST dates, durations, radios, multi-select, chips and special controls",async()=>{
    const e=environment("favorites");e.run("search");
    const controls=[control("keyword","keep"),control("published.after","","date"),control("video.durationSec.min"),control("video.views.min"),control("video.shorts","ANY","radio"),control("video.shorts","ONLY","radio"),control("video.weekdays",0,"checkbox"),control("video.weekdays",1,"checkbox"),control("video.weekdays",6,"checkbox"),control("video.includeNoLanguage","","checkbox"),control("createdMode","","","select"),control("createdBefore","","date"),control("createdDays"),control("restrictEnabled","","checkbox"),control("anyRestriction","","checkbox"),control("restrictedCountry"),control("channel.activity.windowDays",30,"","select"),control("channel.activity.countMin"),control("channel.countries","","","select"),control("video.languages","","","select"),control("video.categoryIds.include","","","select")];
    for(const [name,values] of [["channel.countries",["KR","__unset__","US"]],["video.languages",["ko","en"]],["video.categoryIds.include",["27","10"]]]) {const c=controls.find(c=>c.name===name);c.multiple=true;c.options=values.map(v=>({value:v,selected:false}));}
    const f=form(controls),field=new Element();field.dataset.chips="video.tags.include";const chips=new Element();chips.className="chips";const input=new Element("input");input.dataset.chipInput="";field.append(chips,input);f.append(field);
    const slider=new Element("input");slider.dataset.sync="video.durationSec.min";slider.max="10800";f.append(slider);
    e.window.tubeSearch.applyConditions(f,condition,field=>{const b=new Element("button");b.dataset.token=input.value;chips.append(b);input.value="";});
    const c=name=>controls.find(c=>c.name===name);
    assert.equal(c("keyword").value,"keep");assert.equal(c("published.after").value,"2026-10-01");assert.equal(c("createdBefore").value,"2020-01-02");assert.equal(c("video.durationSec.min").value,"7:03");assert.equal(slider.value,"423");
    assert.deepEqual(controls.filter(c=>c.name==="video.weekdays").map(c=>c.checked),[true,false,true]);assert.equal(controls.filter(c=>c.name==="video.shorts")[1].checked,true);assert.equal(c("anyRestriction").checked,true);assert.equal(c("restrictedCountry").value,"JP");assert.equal(c("channel.activity.countMin").value,"0");assert.equal(c("channel.activity.windowDays").value,"60");
    assert.deepEqual(c("channel.countries").selectedOptions.map(o=>o.value),["KR","__unset__"]);assert.equal(chips.children[0].dataset.token,"<b>x</b>");
    e.window.tubeSearch.applyConditions(f,{video:{},channel:{}},()=>{});assert.equal(c("video.durationSec.min").value,"");assert.equal(c("anyRestriction").checked,false);assert.equal(chips.children.length,0);
  });
  await test("preset rows apply, rename preserving conditions and confirm/cancel deletion",async()=>{
    const e=environment("presets");const item={id:3,name:"<script>name</script>",createdAt:"2026-10-01T00:00:00Z"};e.routes.set("GET /api/v1/presets",[item]);e.routes.set("GET /api/v1/presets/3",{conditions:condition});e.routes.set("PUT /api/v1/presets/3",{});e.routes.set("DELETE /api/v1/presets/3",null);e.start();await settle();
    const list=e.ids["personal-list"];assert.equal(list.querySelector("a").href,"/?preset=3");await list.querySelectorAll("button")[0].fire("click");list.querySelector("input").value="renamed";await list.querySelectorAll("button")[0].fire("click");
    assert.deepEqual(JSON.parse(changes(e)[0].body),{name:"renamed",conditions:condition});
    await list.querySelectorAll("button").at(-1).fire("click");await e.ids["confirm-no"].fire("click");assert.equal(changes(e).filter(c=>c.method==="DELETE").length,0);
    await list.querySelectorAll("button").at(-1).fire("click");e.routes.set("GET /api/v1/presets",[]);await e.ids["confirm-yes"].fire("click");assert.equal(list.children.length,0);csrf(e);
  });
  await test("history links and row/all deletion use in-page confirmation and handle empty state",async()=>{
    const e=environment("history");e.routes.set("GET /api/v1/history",[{id:7,keyword:"<b>x</b>",conditions:condition,resultCount:4,searchedAt:"2026-10-01T00:00:00Z"}]);e.routes.set("DELETE /api/v1/history/7",null);e.routes.set("DELETE /api/v1/history/all",null);e.start();await settle();assert.equal(e.ids["personal-list"].querySelector("a").href,"/?history=7");
    await e.ids["personal-list"].querySelector("button").fire("click");await e.ids["confirm-yes"].fire("click");await e.ids["clear-history"].fire("click");e.routes.set("GET /api/v1/history",[]);await e.ids["confirm-yes"].fire("click");assert.equal(e.ids["clear-history"].disabled,true);csrf(e);
  });
  await test("favorite pages keep unavailable videos removal-only and show cache warnings",async()=>{
    const e=environment("favorites");e.routes.set("GET /api/v1/favorites?page=0&size=20",{items:[{videoId:video.videoId,available:false,title:"더 이상 볼 수 없는 영상"}],totalElements:21,totalPages:2,warnings:["STALE_STATS"]});e.routes.set("GET /api/v1/favorites?page=1&size=20",{items:[{...video,available:true}],totalElements:21,totalPages:2});e.start();await settle();
    assert.equal(e.ids["personal-list"].querySelector("a"),null);assert.equal(e.ids["personal-list"].querySelectorAll("button").length,1);assert.match(e.ids["page-warnings"].textContent,/저장된 통계/);assert.equal(e.ids["favorites-prev"].disabled,true);
    await e.ids["favorites-next"].fire("click");await settle();assert.equal(e.ids["favorites-next"].disabled,true);assert.match(e.ids["favorites-status"].textContent,/2 \/ 2/);
    e.routes.set("DELETE /api/v1/favorites/abcdefghijk",null);e.routes.set("GET /api/v1/favorites?page=1&size=20",{items:[],totalElements:20,totalPages:1});e.routes.set("GET /api/v1/favorites?page=0&size=20",{items:[{videoId:video.videoId,available:false}],totalElements:20,totalPages:1});await e.ids["personal-list"].querySelectorAll("button").at(-1).fire("click");assert.match(e.ids["favorites-status"].textContent,/1 \/ 1/);csrf(e);
  });
  await test("channel renders two local charts, accessible tables, null counts and 404 state",async()=>{
    const e=environment("channel",false);e.routes.set("GET /api/v1/channels/UC-demo",{channel:{id:"UC-demo",title:"<script>title</script>",subscribers:null,videoCount:1,createdAt:null,country:null},recentVideos:[video],pattern:{monthly:[{month:"2026-10",count:1}],matrix:Array.from({length:7},()=>Array(24).fill(0))}});e.start();await settle();
    assert.equal(e.charts.length,2);assert.equal(e.charts[0].config.type,"bar");assert.equal(e.charts[1].config.data.datasets[0].data.length,168);assert.equal(e.ids["channel-summary"].querySelector("h2").textContent,"<script>title</script>");assert.match(e.ids["channel-summary"].textContent,/비공개/);assert.ok(e.ids["channel-heatmap-table"].querySelector("table"));
    e.routes.set("GET /api/v1/channels/UC-demo",{__status:404,__body:{message:"채널을 찾을 수 없습니다."}});await e.ids["retry-page"].fire("click");assert.match(e.ids["channel-summary"].textContent,/404/);assert.equal(e.ids["channel-pattern"].hidden,true);
  });
  await test("password change, inline field errors and password-confirmed withdrawal use CSRF",async()=>{
    const e=environment("me");e.ids["password-form"]=form([control("currentPassword","old12345"),control("newPassword","new12345"),control("newPasswordConfirm","new12345")]);e.ids["withdraw-form"]=form([control("password","old12345")]);
    for(const name of ["currentPassword","newPassword","newPasswordConfirm","password"]) {e.ids[`${name}-error`]=new Element("p");e.ids[`${name}-error`].className="error";e.ids[name==="password" ? "withdraw-form" : "password-form"].append(e.ids[`${name}-error`]);}
    for(const f of ["password-form","withdraw-form"]) {const b=new Element("button");b.type="submit";e.ids[f].append(b);}
    e.routes.set("GET /api/v1/me",{loginId:"member",createdAt:null});e.routes.set("PATCH /api/v1/me/password",{__status:400,__body:{code:"WRONG_PASSWORD",message:"현재 비밀번호 오류"}});e.start();await settle();await e.ids["password-form"].fire("submit");assert.match(e.ids["currentPassword-error"].textContent,/비밀번호 오류/);
    e.routes.set("PATCH /api/v1/me/password",{__status:400,__body:{fieldErrors:[{field:"newPasswordConfirm",message:"불일치"}]}});await e.ids["password-form"].fire("submit");assert.equal(e.ids["newPasswordConfirm-error"].textContent,"불일치");
    e.routes.set("PATCH /api/v1/me/password",null);await e.ids["password-form"].fire("submit");assert.equal(e.ids["page-message"].textContent,"변경되었습니다");assert.equal(JSON.parse(changes(e)[0].body).currentPassword,"old12345");
    await e.ids["open-withdraw"].fire("click");assert.equal(e.ids["withdraw-modal"].open,true);assert.equal(e.calls.some(c=>c.method==="DELETE"),false);
    await e.ids["cancel-withdraw"].fire("click");assert.equal(e.ids["withdraw-modal"].open,false);await e.ids["open-withdraw"].fire("click");e.ids["withdraw-form"].elements[0].value="reentered123";
    e.routes.set("DELETE /api/v1/me",{__status:400,__body:{code:"WRONG_PASSWORD",message:"비밀번호 오류"}});await e.ids["withdraw-form"].fire("submit");assert.match(e.ids["password-error"].textContent,/비밀번호 오류/);assert.equal(e.window.location.assigned,undefined);
    e.routes.set("DELETE /api/v1/me",null);await e.ids["withdraw-form"].fire("submit");assert.equal(e.window.location.assigned,"/login");assert.equal(JSON.parse(changes(e).at(-1).body).password,"reentered123");csrf(e);
  });
  await test("expired member API redirects to login and network errors allow retry",async()=>{
    const e=environment("presets");e.routes.set("GET /api/v1/presets",{__status:401,__body:{message:"로그인 필요"}});e.start();await settle();assert.equal(e.window.location.assigned,"/login");
    e.routes.set("GET /api/v1/presets",()=>{throw Error("연결 실패");});await e.ids["retry-page"].fire("click");assert.match(e.ids["page-message"].textContent,/연결 실패/);assert.equal(e.ids["retry-page"].hidden,false);
  });
  console.log(`${count} JavaScript tests passed`);
})();
testRun.catch(error=>{ console.error(error); throw error; });
