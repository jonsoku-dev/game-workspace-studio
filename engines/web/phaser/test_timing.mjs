import assert from 'node:assert/strict';
import {frameAt,eventPosition,targetContact} from './timing.mjs';
const frames=[120,120,80,80,160,240].map(duration_ms=>({duration_ms}));
assert.equal(frameAt(frames,319.99),2);
assert.equal(frameAt(frames,320),3);
assert.equal(frameAt(frames,800),5);
assert.equal(frameAt(frames,800,true),0);
assert.deepEqual(eventPosition({x:100,y:200,scale:3,facing:1},[24,46],{at_px:[46,25]}),{x:166,y:137});
assert.deepEqual(eventPosition({x:100,y:200,scale:3,facing:-1},[24,46],{at_px:[46,25]}),{x:34,y:137});
console.log('Action frame boundaries and mirrored event anchors passed');

assert.equal(targetContact({x:630,facing:-1},{x:620,y:300},{target_x:650,target_y:300}),false);
assert.equal(targetContact({x:630,facing:1},{x:660,y:300},{target_x:650,target_y:300}),true);
assert.equal(targetContact({x:210,facing:1},{x:276,y:300},{target_x:650,target_y:300}),false);

// Exercise the actual actor adapter with a minimal renderer; scoring must not follow early FX.
const {readFileSync} = await import('node:fs');
const {attackContact} = await import('./timing.mjs');
const source = readFileSync(new URL('./game.mjs',import.meta.url),'utf8');
const actorSource = source.slice(source.indexOf('export class ActionActor'),source.indexOf('class Clearing')).replace('export class','class');
const Actor = new Function('frameAt','eventPosition',actorSource+'; return ActionActor;')(frameAt,eventPosition);
const f = {rect:{x:0,y:0,w:40,h:40},duration_ms:100};
const effect = {action:'attack',start_ms:50,at_px:[32,20],pivot_px_from_top_left:[20,20],frames:[f,f,f],duration_ms:300};
const metadata = {pivot_px_from_top_left:[20,34],actions:{idle:{frames:[f],duration_ms:100,loop:true},attack:{frames:[f,f,f],duration_ms:300,loop:false}},events:[effect]};
assert.equal(attackContact(metadata),null);
assert.deepEqual(attackContact(metadata,{contact_frame:2}),{action:'attack',start_ms:200,at_px:[32,20]});
const noFx = {...metadata,events:[]};
assert.equal(attackContact(noFx,{contact_frame:2,at_px:[30,22]}).start_ms,200);
const image=()=>{const out={};for(const method of ['setScale','setFrame','setPosition','setFlipX','setOrigin','destroy'])out[method]=(...args)=>{if(method==='setFrame')out.frame=args[0];return out;};return out;};
const scene={textures:{get:()=>({add(){}})},add:{image}};
const explicit = {...metadata,contact:attackContact(metadata,{contact_frame:2,at_px:[34,21]})};
const actor=new Actor(scene,explicit,'actor',100,200);
const scores=[];actor.play('attack');actor.update(60,(...args)=>scores.push(args));
assert.equal(actor.effects.length,1);assert.equal(actor.effects[0].elapsed,10);assert.equal(actor.effects[0].image.frame,'0');assert.equal(scores.length,0);
actor.update(139,(...args)=>scores.push(args));assert.equal(scores.length,0);
actor.update(1,(...args)=>scores.push(args));assert.equal(scores.length,1);
assert.equal(actor.effects[0].elapsed,150);assert.equal(actor.effects[0].image.frame,'1');assert.equal(scores[0][0].start_ms,200);assert.deepEqual(scores[0][1],{x:142,y:161});
actor.update(10,(...args)=>scores.push(args));assert.equal(scores.length,1);
const legacy=new Actor(scene,metadata,'actor',100,200);legacy.play('attack');
const legacyScores=[];legacy.update(60,(...args)=>legacyScores.push(args));
assert.equal(legacyScores.length,1);assert.equal(legacyScores[0][0].start_ms,50);

const {TRIAL,trialState,trialStep,trialHit}=await import('./trial.mjs');
const tick=(s,input,n=1)=>{const events=[];for(let i=0;i<n;i++)events.push(...trialStep(s,input));return events;};
const courier=trialState();
assert.deepEqual(tick(courier,{interact:true}),['denied']);
assert.equal(courier.finished,false);
assert.ok(tick(courier,{right:true},10).includes('move'));
assert.ok(courier.x>150);
courier.x=345;
assert.ok(tick(courier,{right:true,jump:true}).includes('jump'));
tick(courier,{right:true},28);
assert.equal(courier.hp,3,'jump clears hazard without damage');
assert.ok(courier.x>425);
assert.ok(tick(courier,{},30).includes('land'));
courier.x=505;assert.ok(tick(courier,{}).includes('collect'));assert.ok(!tick(courier,{}).includes('collect'));
courier.x=599;tick(courier,{right:true},10);assert.equal(courier.x,600,'blocking target stops movement');
assert.deepEqual(trialHit(courier,false),[]);assert.equal(courier.hits,0);
assert.deepEqual(trialHit(courier,true),['hit']);
assert.deepEqual(trialHit(courier,true),['crit']);assert.equal(courier.lastDamage,15);assert.equal(courier.targetHP,5);
assert.deepEqual(trialHit(courier,true),['finisher']);assert.equal(courier.lastDamage,5);assert.equal(courier.targetHP,0);assert.equal(courier.hits,3);
tick(courier,{right:true},8);assert.ok(courier.x>600,'destroyed target releases path');
courier.x=860;assert.ok(tick(courier,{interact:true}).includes('win'));assert.equal(courier.finished,true);
const danger=trialState();danger.x=390;
assert.ok(tick(danger,{}).includes('hurt'));assert.equal(danger.hp,2);
const clock=danger.clock;tick(danger,{jump:true},4);assert.equal(danger.clock,clock,'impact-only hitstop is four ticks');
danger.x=390;tick(danger,{});assert.equal(danger.hp,2,'hazard cooldown prevents per-frame damage');
for(let i=0;i<160&&!danger.lost;i++){danger.x=390;danger.knock=0;trialStep(danger);}
assert.equal(danger.lost,true);assert.equal(danger.hp,0);
const paused=trialState();paused.paused=true;tick(paused,{right:true,jump:true},10);assert.equal(paused.x,150);assert.equal(paused.y,356);
const reset=trialState();assert.equal(reset.hp,3);assert.equal(reset.package,false);assert.equal(reset.hits,0);assert.equal(reset.freeze,0);
// A/B presentation never enters the rules model, including damage and freeze.
const a=trialState(),b=trialState();
for(let i=0;i<300;i++){const input={right:i<180,jump:i===46,interact:i===260};trialStep(a,input);trialStep(b,input);}
assert.deepEqual(a,b);
console.log('Courier movement, jump/landing, collection, denial, combat, delivery, damage cooldown, lose, pause, reset and A/B rules passed');

for(const required of [1,2,3,20]){const s=trialState(required);let contacts=0;while(s.targetHP>0){const before=s.targetHP;trialHit(s,true);contacts++;assert.ok(s.targetHP>=0);assert.equal(before-s.targetHP,s.lastDamage);}assert.equal(s.hits,contacts);assert.ok(contacts<=required);assert.deepEqual(trialHit(s,true),[]);}
assert.throws(()=>trialState(0),/1..20/);assert.throws(()=>trialState(21),/1..20/);

const {trialAction,effectPlayback}=await import('./trial.mjs');
const blocked=trialState();blocked.x=600;
const blockedCues=tick(blocked,{right:true,interact:true},120);
assert.equal(blocked.x,600);
assert.equal(blocked.walking,false);
assert.equal(blockedCues.filter(e=>e==='move'||e==='step').length,0,'held blocked movement makes no footsteps or movement onset');
assert.equal(blockedCues.filter(e=>e==='denied').length,1,'held interaction denies once');
assert.equal(trialAction(blocked,'idle'),'idle');
trialStep(blocked,{});assert.deepEqual(trialStep(blocked,{interact:true}),['denied'],'release permits another interaction');
const atWall=trialState();atWall.x=65;assert.equal(tick(atWall,{left:true},80).filter(e=>e==='step'||e==='move').length,0);
const knockback=trialState();knockback.knock=-.48;const knocked=tick(knockback,{right:true});assert.ok(knockback.x<150);assert.equal(knockback.walking,false);assert.ok(!knocked.includes('step'));
const walking=trialState();tick(walking,{right:true},5);walking.x=600;assert.deepEqual(trialStep(walking,{right:true}),['stop']);assert.ok(!tick(walking,{right:true},40).includes('stop'),'blocked hold emits stop once');
assert.equal(trialAction(trialState(),'hurt'),'hurt','authored hurt survives locomotion selection until ActionActor completes it');
assert.equal(trialAction({...trialState(),y:280},'jump'),'jump');
assert.equal(trialAction({...trialState(),y:280},'idle'),'idle','completed jump is not restarted while airborne');
const reducedFrames=[80,140,220,60].map(duration_ms=>({duration_ms}));
assert.deepEqual(effectPlayback({frames:reducedFrames,reduced_motion_frame:2}),{duration:500,reducedFrame:2});
assert.deepEqual(effectPlayback({frames:reducedFrames}),{duration:500,reducedFrame:1});
assert.equal(effectPlayback({frames:reducedFrames,reduced_motion_frame:99}).reducedFrame,3);
console.log('Blocked/wall movement, footfall and denial edge guards, hurt/jump action persistence, sheet timing and reduced-motion frame passed');
const reactionActor=new Actor(scene,{...metadata,events:[],actions:{...metadata.actions,hurt:{frames:[f,f,f],duration_ms:300,loop:false}}},'actor',100,200);
reactionActor.play('hurt');const recoveryState={...trialState(),walking:true};
for(let i=0;i<17;i++){const action=trialAction(recoveryState,reactionActor.action);if(action!==reactionActor.action)reactionActor.play(action);reactionActor.update(TRIAL.tick,()=>{});}
assert.equal(reactionActor.action,'hurt');reactionActor.update(20,()=>{});assert.equal(reactionActor.action,'idle');assert.equal(trialAction(recoveryState,reactionActor.action),'walk');

const {loadCueSheets,prepareCueSheets,spawnCueSheet,advanceCueSheet}=await import('./cue-sheets.mjs');
const sheetsLoaded=[],atlasFrames=[];
const cueImage=()=>{const o={destroyed:false};for(const key of ['setScale','setFlipX','setDepth','setOrigin','setFrame'])o[key]=(...args)=>{o[key+'Args']=args;return o;};o.destroy=()=>{o.destroyed=true;};return o;};
const sheetScene={load:{image:(...args)=>sheetsLoaded.push(args)},textures:{get:()=>({add:(...args)=>atlasFrames.push(args)})},add:{image:cueImage}};
const sheetMetadata={frames:reducedFrames.map((f,i)=>({...f,rect:{x:i*32,y:0,w:32,h:32}})),pivot_px_from_top_left:[8,24],reduced_motion_frame:2};
const names=['move','step','stop','attack','miss','hit','win','restart'];
const bindingsInput=Object.fromEntries(names.map(name=>[name,{sheet:`${name}.png`,metadata:sheetMetadata}]));
loadCueSheets(sheetScene,bindingsInput);const bindings=prepareCueSheets(sheetScene,bindingsInput);
assert.equal(sheetsLoaded.length,names.length);assert.equal(atlasFrames.length,names.length*4);
const mirroredSheet=spawnCueSheet(sheetScene,bindings,'hit',{x:10,y:20,facing:-1});
assert.deepEqual(mirroredSheet.object.setOriginArgs,[.75,.75]);assert.equal(mirroredSheet.duration,500);
assert.equal(advanceCueSheet(mirroredSheet,80,false),true);assert.deepEqual(mirroredSheet.object.setFrameArgs,['1']);
assert.equal(advanceCueSheet(mirroredSheet,10,true),true);assert.deepEqual(mirroredSheet.object.setFrameArgs,['2']);
assert.equal(advanceCueSheet(mirroredSheet,410,true),false);assert.equal(mirroredSheet.object.destroyed,true);
const staticSheet=spawnCueSheet(sheetScene,bindings,'move',{x:0,y:0,reducedMotion:true});assert.deepEqual(staticSheet.object.setFrameArgs,['2']);
const ClearingForTest=new Function('Phaser','feedback','spawnCueSheet','rules',source.slice(source.indexOf('class Clearing'),source.indexOf('window.scoutGame'))+';return Clearing;')({Scene:class{}},{emit:()=>({}),reducedMotion:true},spawnCueSheet,{target_x:650,target_y:300});
const clearing=new ClearingForTest();Object.assign(clearing,sheetScene,{actor:{x:210,y:356,facing:1},sheetBindings:bindings,sheetCues:[],fxEnabled:true});
for(const name of names)clearing.cue(name);assert.equal(clearing.sheetCues.length,names.length,'normal land_hits consumes every mapped semantic cue');
clearing.fxEnabled=false;clearing.cue('hit');assert.equal(clearing.sheetCues.length,names.length,'A/B off prevents new sheet spawns');
console.log('Shared sheet loading, mirrored pivots, exact duration, static reduced frame and normal land_hits binding passed');
