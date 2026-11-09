import {JOBS} from './jobs.mjs';
import {RECOVERY_MS} from './timing.mjs';
const followTime=RECOVERY_MS.follow/1000, recoverTime=RECOVERY_MS.recover/1000;
import {createCombatFX} from './combat-fx.mjs';
import {motionReady,drawActor} from './combat-motion.mjs';
import actorManifest from './motion/manifest.mjs';

const $ = id => document.getElementById(id);
const canvas = $('battle'), ctx = canvas.getContext('2d'), root = $('game-state');
const motifs = {
  blade: {label:'검의 서약', role:'균형 · 날카로운 검격', tip:'안정적인 검격. 가까이 붙어 약공격, 빈틈에는 강공격.', range:300, damage:48, color:'#a5edee'},
  brawler: {label:'주먹의 서약', role:'근접 · 묵직한 충격', tip:'짧은 거리, 가장 강한 주먹. 받아친 뒤 접근해 강공격.', range:230, damage:64, color:'#ffbc85'},
  astral: {label:'별의 서약', role:'중거리 · 별빛 폭발', tip:'먼 거리의 지점에 별빛을 부릅니다. 적의 다음 위치를 읽으세요.', range:440, damage:44, color:'#c0b1ff'},
  rail: {label:'탄도의 서약', role:'원거리 · 관통 사격', tip:'긴 사거리의 정밀 사격. 옆 방향과 조준 위치에 주의하세요.', range:520, damage:42, color:'#a9e5ff'},
};
fetch(new URL('./genre.json',import.meta.url)).then(response=>response.ok?response.json():null).then(brief=>{
  if(!brief?.title)return;
  document.title=brief.title; $('game-title').firstChild.nodeValue=brief.title;
  $('selection-title').textContent=brief.title;
}).catch(()=>{});
const entries = Object.entries(JOBS);
if (!entries.length) throw new Error('At least one combat job is required.');
let selected = entries[0][0];
const background = new Image(); background.src = './art/bell-tower.jpg';
const osMotion = matchMedia('(prefers-reduced-motion: reduce)');
let reduced = osMotion.matches;
let fx = createCombatFX({jobs:JOBS, reducedMotion:reduced});
let assetsReady=false;
Promise.all([fx.ready,motionReady]).then(()=>{assetsReady=true; $('start').disabled=false;}).catch(()=>{announce('전투 그림을 불러오지 못했습니다. 새로고침해 주세요.');});
$('start').disabled=true;
let feedback;
// The scaffold installs feedback.mjs on export; source previews remain playable without it.
import('./feedback.mjs').then(({createFeedback}) => { feedback = createFeedback(); }).catch(() => { $('sound').textContent = '소리 준비 안 됨'; $('sound').disabled = true; });
let state = 'select', player, enemy, hits=0, misses=0, parries=0, clock=0, stop=0, shake=0, aim=null, floats=[], lastTime=0;
const keys = new Set();
const clamp = (n,a,b) => Math.max(a,Math.min(b,n));
const distance = (a,b) => Math.hypot(a.x-b.x,(a.y-b.y)*1.3);
const config = () => motifs[JOBS[selected].motif] || motifs.blade;
const sound = (name) => feedback?.emit(name);
const announce = message => { $('combat-log').textContent = message; };
function event(outcome, message) {
  root.dataset.outcome=outcome; root.dataset.action=message; root.dataset.events=String(Number(root.dataset.events||0)+1);
  announce(message); sync();
}
function sync() {
  Object.assign(root.dataset,{state,hits:String(hits),misses:String(misses),parries:String(parries),playerHp:String(Math.ceil(player.hp)),enemyHp:String(Math.ceil(enemy.hp)),enemyPhase:enemy.phase,playerX:String(Math.round(player.x)),playerY:String(Math.round(player.y)),enemyX:String(Math.round(enemy.x)),enemyY:String(Math.round(enemy.y)),face:String(player.face),playerZ:player.z.toFixed(1),airborne:String(player.z>0),jumps:String(player.jumps),landings:String(player.landings),enemyAttack:enemy.attackKind,enemyCountdown:enemy.timer.toFixed(2),sprinting:String(player.sprinting)});
  $('player-meter').value=player.hp; $('enemy-meter').value=enemy.hp;
  $('player-hp').textContent=`${Math.ceil(player.hp)} / 100`; $('enemy-hp').textContent=`${Math.ceil(enemy.hp)} / 320`;
  $('combat-score').textContent=`적중 ${hits} · 빗나감 ${misses} · 받아치기 ${parries}`;
}
function reset(next='playing') {
  fx.reset(); keys.clear(); hits=misses=parries=clock=stop=shake=0; aim=null; floats=[];
  player={x:490,y:444,hp:100,face:1,cooldown:0,evade:0,evadeCooldown:0,parry:0,parryCooldown:0,pose:0,vx:0,vy:0,hurt:0,moving:false,cast:null,castAge:0,z:0,vz:0,jumps:0,landings:0,sprintToggle:false,sprinting:false};
  enemy={x:790,y:444,hp:320,phase:'approach',timer:2.8,pose:0,exposed:0,attack:0,targetX:490,targetY:444,turn:0,hurt:0,attackKind:'floor'};
  state=next; root.dataset.events='0'; root.dataset.contacts='0'; root.dataset.outcome='ready';
  document.querySelector('[data-action="sprint"]').setAttribute('aria-pressed','false');
  $('selection').hidden=next!=='select'; $('result').hidden=true;
  $('player-name').textContent=JOBS[selected].name || config().label;
  $('enemy-intent').textContent='파수꾼이 거리를 재고 있습니다'; sync();
}
function select(key) {
  selected=key; root.dataset.job=key;
  for(const button of $('jobs').children) button.setAttribute('aria-pressed',String(button.dataset.job===key));
  $('job-description').textContent=`${JOBS[key].skill || '강공격'} — ${JOBS[key].description || config().tip}`;
  $('skill-name').textContent=JOBS[key].skill || '강공격';
  $('player-name').textContent=JOBS[key].name || config().label;
}
for (const [key,job] of entries) {
  const motif=motifs[job.motif]?job.motif:'blade';
  const button=document.createElement('button'); button.className='job'; button.dataset.job=key; button.type='button';
  const image=document.createElement('img'); image.src=`./art/${job.actor||motif}-idle.webp`; image.alt='';
  const name=document.createElement('strong'); name.textContent=job.name || motifs[motif].label;
  const role=document.createElement('small'); role.textContent=job.skill || motifs[motif].role;
  button.append(image,name,role); button.addEventListener('click',()=>{select(key); sound('select');}); $('jobs').append(button);
}
function finish(won) {
  state=won?'won':'lost'; keys.clear(); $('result').hidden=false;
  $('result-label').textContent=won?'THE BELL IS YOURS':'THE BRIDGE REMEMBERS';
  $('result-title').textContent=won?'마지막 종이 울렸다':'다시, 한 번의 빈틈';
  $('result-detail').textContent=won?`파수꾼을 돌파했습니다. 적중 ${hits}회 · 받아치기 ${parries}회 · 남은 체력 ${Math.ceil(player.hp)}`:'붉은 원을 피하고 금색 섬광을 기다리세요. 받아치기에 성공하면 강공격을 연결하세요.';
  event(won?'victory':'defeat',won?'승리! 종탑의 길이 열렸습니다.':'패배. 다시 도전할 수 있습니다.'); if(won)fx.react('win',{x:player.x,y:player.y,face:player.face}); sound(won?'win':'lose');
}
function attack(heavy) {
  if(player.cooldown>0 || player.evade>0) return;
  const range=heavy?config().range:210;
  const front=(enemy.x-player.x)*player.face>=-12;
  const inReach=distance(player,enemy)<=range;
  const target=heavy&&aim ? aim : front&&inReach ? enemy : {x:player.x+player.face*range,y:player.y};
  const cast=fx.cast(selected,{x:player.x,y:player.y-player.z,targetX:target.x,targetY:target.y,face:player.face,heavy});
  player.cooldown=Math.max(heavy?1.02:.47,cast.contactTime+.32); player.pose=cast.contactTime+.32;
  player.cast=cast; player.castAge=0;
  sound('attack'); event('casting',heavy?`${JOBS[selected].skill || '강공격'} — 조준한 지점을 향합니다.`:'약공격 — 전방을 견제합니다.');
}
function action(name) {
  if(!assetsReady || state!=='playing') return;
  if(name==='sprint'){player.sprintToggle=!player.sprintToggle;document.querySelector('[data-action="sprint"]').setAttribute('aria-pressed',String(player.sprintToggle));return;}
  if(name==='jump'&&player.z===0&&player.vz===0){player.vz=480;player.jumps++;sound('jump');event('jump','도약 — 지면 충격은 공중에서 피할 수 있습니다. 쇄도에는 회피나 받아치기!');return;}
  if(name==='heavy'||name==='light') return attack(name==='heavy');
  if(name==='evade' && player.evadeCooldown<=0) {
    let dx=(keys.has('right')?1:0)-(keys.has('left')?1:0), dy=(keys.has('down')?1:0)-(keys.has('up')?1:0);
    if(!dx&&!dy) dx=player.face;
    const len=Math.hypot(dx,dy); player.vx=dx/len*660; player.vy=dy/len*350;
    player.evade=.25; player.evadeCooldown=1.1; fx.react('evade',{x:player.x,y:player.y,face:player.face}); sound('jump'); event('evade','회피 — 잔상이 남는 동안 무적입니다.');
  }
  if(name==='parry' && player.parryCooldown<=0 && player.evade<=0) {
    player.parry=.26; player.parryCooldown=1.1; player.pose=.26; sound('interact'); event('guard','받아치기 — 지금 들어오는 공격을 되돌립니다.');
  }
}
function contact(cast) {
  if(state!=='playing') return false;
  root.dataset.contacts=String(Number(root.dataset.contacts||0)+1);
  root.dataset.contactPhase='impact';
  const front=(enemy.x-cast.x)*cast.face>=-20;
  const reach=cast.heavy?config().range:220;
  const connected=front&&distance(cast,enemy)<=reach+35&&Math.hypot(enemy.x-cast.targetX,(enemy.y-cast.targetY)*1.4)<(cast.heavy?105:120);
  if(!connected) { misses++; sound('miss'); event('miss','빗나감 — 거리·방향·적의 이동을 확인하세요.'); return false; }
  const damage=Math.round((cast.heavy?config().damage:18)*(enemy.exposed>0?1.8:1));
  const braced=enemy.phase==='windup';
  enemy.hp=Math.max(0,enemy.hp-damage);
  if(!braced) {enemy.x=clamp(enemy.x+cast.face*(cast.heavy?22:8),330,950);enemy.pose=.24;enemy.hurt=.25;}
  fx.react('hurt',{x:enemy.x,y:enemy.y,face:cast.face});
  hits++; stop=cast.heavy?.075:.035; shake=reduced?0:cast.heavy?9:4;
  floats.push({x:enemy.x,y:enemy.y-105,text:`${enemy.exposed>0?'노출! ':''}−${damage}`,life:.9,color:config().color});
  sound(cast.heavy?'crit':'hit'); event('hit',`${cast.heavy?'강공격':'약공격'} 적중! ${damage} 피해${enemy.exposed>0?' · 노출 보너스':braced?' · 버티는 갑주: 쇄도는 계속됩니다':''}`);
  if(enemy.hp<=0) finish(true);
  return {hit:true,x:enemy.x,y:enemy.y};
}
function enemyImpact() {
  const within=Math.hypot(player.x-enemy.targetX,(player.y-enemy.targetY)*1.7)<148;
  const jumped=enemy.attackKind==='floor'&&player.z>30;
  if(within&&player.parry>0&&!jumped) {
    parries++; enemy.exposed=2.8; enemy.phase='exposed'; enemy.timer=2.8; stop=.12;
    fx.react('parry',{x:player.x,y:player.y,face:player.face}); fx.react('exposed',{x:enemy.x,y:enemy.y,face:player.face}); shake=reduced?0:10;
    floats.push({x:enemy.x,y:enemy.y-120,text:'받아치기 · 노출',life:1.2,color:'#ffe2a4'}); sound('crit'); event('parry','받아치기 성공! 2.8초 동안 파수꾼 노출 — 강공격 기회.');
  } else {
    if(within&&player.evade<=0&&!jumped) {
      fx.react('enemyImpact',{x:player.x,y:player.y,face:player.x<enemy.x?-1:1});
      fx.react('hurt',{x:player.x,y:player.y,face:player.x<enemy.x?-1:1});
      player.hp=Math.max(0,player.hp-20); player.hurt=.3; player.x=clamp(player.x+(player.x<enemy.x?-38:38),330,950); shake=reduced?0:12;
      floats.push({x:player.x,y:player.y-110,text:'−20',life:.8,color:'#ffa38c'}); sound('hurt'); event('hurt','파수꾼의 쇄도! 20 피해 — 붉은 원을 벗어나세요.');
      if(player.hp<=0) { finish(false); return; }
    } else { sound('miss'); event(jumped?'jump-dodge':'avoided',jumped?'도약 성공! 지면 충격이 발밑을 지나갔습니다.':'파수꾼의 공격을 피했습니다. 반격하세요!'); }
    enemy.phase='recover'; enemy.timer=1.15;
  }
  enemy.attack=.38;
}
function step(dt) {
  if(state!=='playing') {
    if(state==='won'||state==='lost') fx.step(dt,()=>false);
    return;
  }
  if(stop>0) {stop-=dt; return;}
  clock+=dt;
  if(player.z>0||player.vz>0){player.z+=player.vz*dt-660*dt*dt;player.vz-=1320*dt;if(player.z<=0){player.z=0;player.vz=0;player.landings++;sound('land');event('land','착지 — 다음 도약을 준비할 수 있습니다.');}}
  for(const key of ['cooldown','evade','evadeCooldown','parry','parryCooldown','pose','hurt']) player[key]=Math.max(0,player[key]-dt);
  if(player.cast) {player.castAge+=dt;if(player.castAge>player.cast.contactTime+followTime+recoverTime)player.cast=null;}
  enemy.hurt=Math.max(0,enemy.hurt-dt);
  enemy.pose=Math.max(0,enemy.pose-dt); enemy.attack=Math.max(0,enemy.attack-dt); enemy.exposed=Math.max(0,enemy.exposed-dt);
  let dx=(keys.has('right')?1:0)-(keys.has('left')?1:0), dy=(keys.has('down')?1:0)-(keys.has('up')?1:0);
  player.moving=Boolean(dx||dy);player.sprinting=player.sprintToggle||keys.has('sprint');
  if(dx) player.face=dx;
  if(player.evade>0) {player.x+=player.vx*dt;player.y+=player.vy*dt;}
  else { const speed=player.cooldown>.25?110:player.sprinting?360:240; player.x+=dx*speed*dt; player.y+=dy*speed*.62*dt; }
  player.x=clamp(player.x,330,950); player.y=clamp(player.y,388,505);
  enemy.timer-=dt;
  if(enemy.phase==='approach') {
    const desired=player.x+(player.x<640?205:-205); enemy.x+=clamp(desired-enemy.x,-75*dt,75*dt);
    enemy.y+=clamp(player.y-enemy.y,-38*dt,38*dt);
    if(enemy.timer<=0) {enemy.phase='windup';enemy.timer=1.05;enemy.targetX=player.x;enemy.targetY=player.y;enemy.turn++;enemy.attackKind=enemy.turn%2?'floor':'lunge';event('warning',enemy.attackKind==='floor'?'지면 충격 예고 — E로 도약하거나 금색 섬광에 받아치세요.':'공중 쇄도 예고 — 점프로 피할 수 없습니다. 회피하거나 받아치세요.');}
  } else if(enemy.phase==='windup') {
    if(enemy.timer<=0) enemyImpact();
  } else if(enemy.timer<=0) {enemy.phase='approach';enemy.timer=1.9;}
  fx.step(dt,contact);
  for(const text of floats) {text.life-=dt;text.y-=dt*28;} floats=floats.filter(text=>text.life>0);
  shake=Math.max(0,shake-dt*30);
  $('enemy-intent').textContent=enemy.phase==='windup'?(enemy.timer<.3?'지금! 받아치기 [L]':enemy.attackKind==='floor'?'지면 충격 · E 도약 / L 받아치기':'공중 쇄도 · Space 회피 / L 받아치기'):enemy.exposed>0?'파수꾼 노출 · 강공격 피해 1.8배':enemy.phase==='recover'?'파수꾼이 무기를 거둡니다 · 반격 기회':'파수꾼이 다음 공격을 준비합니다';
  $('cooldown').textContent=player.cooldown>0?`다음 공격 ${player.cooldown.toFixed(1)}초`:`회피 ${player.evadeCooldown>0?player.evadeCooldown.toFixed(1)+'초':'준비'} · 받아치기 ${player.parryCooldown>0?player.parryCooldown.toFixed(1)+'초':'준비'}`;
  sync();
}
function ellipse(x,y,rx,ry,fill,stroke) {ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,Math.PI*2);if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.stroke();}}
function figure(who,motif,isEnemy=false) {
  const face=isEnemy?(player.x<enemy.x?-1:1):who.face;
  const feet=who.y+68, altitude=isEnemy?0:who.z, h=isEnemy?272:248;
  ellipse(who.x,feet-4,isEnemy?68:49-altitude*.18,14-altitude*.045,'#07151c75');
  let pose='idle', progress=0;
  if(isEnemy) {
    if(who.hurt>0) {pose='hurt';progress=1-who.hurt/.25;}
    else if(who.phase==='windup') {pose=who.timer<.16?'release':who.attackKind==='floor'?'heavy':'windup';progress=1-who.timer/1.05;}
    else if(who.attack>0) {pose='follow';progress=1-who.attack/.38;}
    else if(who.phase==='recover'||who.phase==='exposed') {pose='recover';progress=who.phase==='exposed'?1-who.timer/2.8:1-who.timer/1.15;}
    else {pose='move';progress=(clock*.8)%1;}
  } else {
    if(who.hurt>0) {pose='hurt';progress=1-who.hurt/.3;}
    else if(who.evade>0) {pose='evade';progress=1-who.evade/.25;}
    else if(who.parry>0) {pose='windup';progress=1-who.parry/.26;}
    else if(who.cast) {
      const t=who.castAge,c=who.cast.contactTime,w=Number(who.cast.windup)||c*.65;
      if(t<w) {pose=who.cast.heavy?'heavy':'windup';progress=t/w;}
      else if(t<c) {pose='release';progress=(t-w)/Math.max(.01,c-w);}
      else if(t<c+followTime) {pose='follow';progress=(t-c)/followTime;}
      else {pose='recover';progress=(t-c-followTime)/recoverTime;}
    } else if(who.z>0) {pose='jump';progress=clamp((480-who.vz)/960,0,1);}
    else if(who.moving) {pose=who.sprinting?'move':'walk';progress=(clock*1.5)%1;}
  }
  const kind=isEnemy?'warden':JOBS[selected].actor||motif;
  const available=actorManifest[kind]?.actions;
  if(pose==='jump'&&available&&!available.jump)pose='evade';
  if(pose==='walk'&&available&&!available.walk)pose='move';
  root.dataset[isEnemy?'enemyPose':'playerPose']=pose;
  if(!isEnemy)root.dataset.contactPhase=pose;
  root.dataset[isEnemy?'enemyPoseProgress':'playerPoseProgress']=progress.toFixed(2);
  if(who.evade>0||who.parry>0||who.exposed>0) ellipse(who.x,who.y+6-altitude,who.parry>0?72:62,91,null,who.parry>0?'#ffe2a4':who.exposed>0?'#ffe2a4':'#b2f6f2');
  drawActor(ctx,{kind,x:who.x,groundY:feet-altitude,height:h,face,pose,progress:clamp(progress,0,1),time:reduced?0:clock});
  if(isEnemy&&who.exposed>0){ctx.font='bold 13px sans-serif';ctx.textAlign='center';ctx.fillStyle='#ffe2a4';ctx.fillText('◇ 노출',who.x,who.y-150);}
}
function draw() {
  ctx.clearRect(0,0,1280,620);ctx.save();
  if(shake&&!reduced)ctx.translate(Math.sin(clock*110)*shake,Math.cos(clock*90)*shake*.4);
  if(background.complete&&background.naturalWidth) {const scale=Math.max(1280/background.naturalWidth,620/background.naturalHeight);ctx.drawImage(background,(1280-background.naturalWidth*scale)/2,(620-background.naturalHeight*scale)/2,background.naturalWidth*scale,background.naturalHeight*scale);}
  else {const g=ctx.createLinearGradient(0,0,0,620);g.addColorStop(0,'#314550');g.addColorStop(1,'#8ba5aa');ctx.fillStyle=g;ctx.fillRect(0,0,1280,620);}
  const shade=ctx.createLinearGradient(0,0,0,620);shade.addColorStop(0,'#08131b92');shade.addColorStop(.55,'#18333d15');shade.addColorStop(1,'#0718209c');ctx.fillStyle=shade;ctx.fillRect(0,0,1280,620);
  ctx.fillStyle='#19313c36';ctx.beginPath();ctx.moveTo(0,405);ctx.lineTo(1280,405);ctx.lineTo(1280,578);ctx.lineTo(0,578);ctx.fill();
  ctx.strokeStyle='#b7d7d336';ctx.lineWidth=1;for(let x=-200;x<1500;x+=105){ctx.beginPath();ctx.moveTo(640+(x-640)*.8,405);ctx.lineTo(x,578);ctx.stroke();}
  for(const y of [407,462,520,577]){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(1280,y);ctx.stroke();}
  if(state==='playing'&&enemy.phase==='windup') {
    const gold=enemy.timer<.3;
    ellipse(enemy.targetX,enemy.targetY+55,148,55,gold?'#f8d58955':'#ed69443d',gold?'#ffe6a0':'#ffa28c');
    if(enemy.attackKind==='lunge'){ctx.strokeStyle=gold?'#ffe6a0':'#ffb7ad';ctx.lineWidth=5;ctx.beginPath();ctx.arc(enemy.targetX,enemy.targetY-12,100,Math.PI,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(enemy.targetX-90,enemy.targetY-50);ctx.lineTo(enemy.targetX+90,enemy.targetY+65);ctx.moveTo(enemy.targetX+90,enemy.targetY-50);ctx.lineTo(enemy.targetX-90,enemy.targetY+65);ctx.stroke();}
    ctx.save();ctx.translate(enemy.targetX,enemy.targetY+55);ctx.scale(1,.38);ctx.beginPath();ctx.arc(0,0,148,-Math.PI/2,-Math.PI/2+Math.PI*2*(1-enemy.timer/1.05));ctx.strokeStyle=gold?'#fff0b5':'#ffad8a';ctx.lineWidth=8;ctx.stroke();ctx.restore();
    ctx.textAlign='center';ctx.font='bold 14px sans-serif';ctx.fillStyle=gold?'#ffe6a0':'#ffd2bf';ctx.fillText(gold?'받아치기!':enemy.attackKind==='floor'?'지면 충격 · 도약':'공중 쇄도 · 회피',enemy.targetX,enemy.targetY+140);
  }
  if(aim&&state==='playing') {ellipse(aim.x,aim.y,18,9,null,config().color);ctx.strokeStyle=config().color;ctx.beginPath();ctx.moveTo(aim.x-27,aim.y);ctx.lineTo(aim.x+27,aim.y);ctx.moveTo(aim.x,aim.y-18);ctx.lineTo(aim.x,aim.y+18);ctx.stroke();}
  const actors=[{who:player,motif:JOBS[selected].motif},{who:enemy,motif:'warden',isEnemy:true}].sort((a,b)=>a.who.y-b.who.y);
  for(const actor of actors)figure(actor.who,actor.motif,actor.isEnemy);
  fx.draw(ctx);
  for(const item of floats){ctx.globalAlpha=Math.min(1,item.life*3);ctx.fillStyle=item.color;ctx.font='bold 25px sans-serif';ctx.textAlign='center';ctx.shadowColor='#07121a';ctx.shadowBlur=8;ctx.fillText(item.text,item.x,item.y);ctx.shadowBlur=0;}ctx.globalAlpha=1;
  if(enemy.attack>0){ellipse(enemy.targetX,enemy.targetY+55,148*(1-enemy.attack/.5),55*(1-enemy.attack/.5),null,'#f9d2a3');}
  ctx.restore();
}
const movement={ArrowLeft:'left',a:'left',ArrowRight:'right',d:'right',ArrowUp:'up',w:'up',ArrowDown:'down',s:'down'};
window.addEventListener('keydown',e=>{
  if(e.target instanceof HTMLButtonElement && e.key==='Enter') return;
  const key=e.key.length===1?e.key.toLowerCase():e.key;
  if(key==='Shift'){if(state==='playing'){e.preventDefault();keys.add('sprint');}return;}
  if(movement[key]){if(state==='playing'){e.preventDefault();keys.add(movement[key]);}return;}
  if(key==='Escape'){aim=null;return;}
  const name={j:'light',k:'heavy',' ':'evade',l:'parry',e:'jump'}[key]; if(name&&state==='playing'){e.preventDefault();if(!e.repeat)action(name);}
});
window.addEventListener('keyup',e=>{if(e.key==='Shift')keys.delete('sprint');keys.delete(movement[e.key.length===1?e.key.toLowerCase():e.key]);});
window.addEventListener('blur',()=>keys.clear());
document.addEventListener('visibilitychange',()=>{keys.clear();lastTime=0;});
for(const button of document.querySelectorAll('[data-action]'))button.addEventListener('click',()=>action(button.dataset.action));
for(const button of document.querySelectorAll('[data-move]')) {
  button.addEventListener('pointerdown',e=>{if(state!=='playing')return;e.preventDefault();button.setPointerCapture(e.pointerId);keys.add(button.dataset.move);});
  for(const name of ['pointerup','pointercancel','lostpointercapture'])button.addEventListener(name,()=>keys.delete(button.dataset.move));
}
canvas.addEventListener('pointerdown',e=>{if(state!=='playing')return;const rect=canvas.getBoundingClientRect();const scale=Math.max(rect.width/1280,rect.height/620);aim={x:clamp((e.clientX-rect.left+(1280*scale-rect.width)/2)/scale,300,980),y:clamp((e.clientY-rect.top+(620*scale-rect.height)/2)/scale,350,520)};canvas.focus();announce('조준점을 고정했습니다. K 또는 강공격으로 발사하세요.');});
$('start').addEventListener('click',()=>{reset();sound('restart');announce('결투 시작. 방향을 맞추고 J / K로 공격하세요.');canvas.focus();});
$('restart').addEventListener('click',()=>{reset();sound('restart');canvas.focus();});
$('retry-live').addEventListener('click',()=>{reset(state==='select'?'select':'playing');announce('결투를 초기화했습니다.');});
$('select').addEventListener('click',()=>{reset('select');$('jobs').firstElementChild.focus();});
$('sound').addEventListener('click',()=>{if(!feedback)return;const on=!feedback.sound;feedback.setSound(on);$('sound').setAttribute('aria-pressed',String(on));$('sound').textContent=on?'소리 켜짐':'소리 꺼짐';if(on)sound('menu');});
function motion(value) {
  reduced=Boolean(value); fx.setReducedMotion(reduced);
  $('motion').setAttribute('aria-pressed',String(reduced)); $('motion').textContent=reduced?'움직임 최소':'움직임 줄이기'; shake=0;
}
$('motion').addEventListener('click',()=>motion(!reduced));osMotion.addEventListener('change',e=>motion(e.matches));
select(selected);reset('select');motion(reduced);
function frame(time) {const dt=lastTime?Math.min((time-lastTime)/1000,.04):0;lastTime=time;if(!document.hidden)step(dt);draw();requestAnimationFrame(frame);}
requestAnimationFrame(frame);
