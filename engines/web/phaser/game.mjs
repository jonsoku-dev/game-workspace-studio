import {loadCueSheets,prepareCueSheets,spawnCueSheet,advanceCueSheet} from './cue-sheets.mjs';
import {createFeedback} from './feedback.mjs';
import {courierScene} from './trial.mjs';
import {frameAt, eventPosition, targetContact, attackContact} from './timing.mjs';

const status = document.querySelector('#status');
const bundle = await fetch('game.json').then(r => {if (!r.ok) throw Error('Bundle unavailable'); return r.json();});
const meta = bundle.metadata;
const rules = {hits_to_win:3,target_x:650,target_y:300,...bundle.playtest};
const brief = bundle.brief || {};
const isTrial=rules.mode==='courier_trial';
const feedback=createFeedback({enabled:true,sound:false});
for(const id of ['jump','interact','pause'])document.getElementById(id).hidden=!isTrial;
for(const id of ['feel','sound'])document.getElementById(id).hidden=false;
document.querySelector('h1').textContent = brief.title || (isTrial?'숲길 우편 배달':'Training clearing');
document.querySelector('header p').textContent = brief.goal || `Land ${rules.hits_to_win} strikes on the amber target.`;
document.querySelector('.hint').textContent = brief.controls || 'Arrow keys / A D to move · Space to strike · R to restart';
if(isTrial){
  document.documentElement.lang='ko';
  document.querySelector('header p').textContent='가시 틈을 넘고, 우편을 챙기고, 막힌 길을 열어 배송하세요.';
  document.querySelector('.hint').textContent='← → / A D 이동 · W / ↑ 점프 · Space 타격 · E 배송 · P 멈춤 · R 다시';
  document.getElementById('left').textContent='← 이동';document.getElementById('right').textContent='이동 →';
  document.getElementById('attack').textContent='타격 · Space';document.getElementById('restart').textContent='다시 · R';
  document.getElementById('game').setAttribute('aria-label','숲길 우편 배달. 아래 버튼이나 키보드로 플레이하세요.');
}
meta.contact = attackContact(meta,rules);
const held = {left:false, right:false};
const setStatus = text => {if (status.textContent !== text) status.textContent = text;};

// Each action-set frame remains an explicit atlas rectangle; no uniform-grid assumption.
export class ActionActor {
  constructor(scene, metadata, key, x, y, scale = 3) {
    Object.assign(this, {scene, metadata, key, x, y, scale, facing:1, action:'idle', elapsed:0, effects:[], fired:new Set()});
    const texture = scene.textures.get(key);
    for (const [name, action] of Object.entries(metadata.actions)) {
      action.frames.forEach((f, i) => texture.add(`${name}:${i}`, 0, f.rect.x, f.rect.y, f.rect.w, f.rect.h));
    }
    this.sprite = scene.add.image(x, y, key, 'idle:0').setScale(scale);
  }
  play(action) {if (!this.metadata.actions[action]) return; this.action=action; this.elapsed=0; this.fired.clear();}
  update(delta, onEvent) {
    this.elapsed += delta;
    const action = this.metadata.actions[this.action];
    const index = frameAt(action.frames, this.elapsed, action.loop);
    const rect = action.frames[index].rect;
    const pivot = this.metadata.pivot_px_from_top_left;
    this.sprite.setFrame(`${this.action}:${index}`).setPosition(this.x,this.y).setFlipX(this.facing < 0)
      .setOrigin(this.facing < 0 ? 1-pivot[0]/rect.w : pivot[0]/rect.w,pivot[1]/rect.h);
    (this.metadata.events || []).forEach((event, i) => {
      if (event.action !== this.action || this.elapsed < event.start_ms || this.fired.has(i)) return;
      this.fired.add(i);
      const point = eventPosition(this,pivot,event);
      if(this.effectsEnabled===false){if (!(this.metadata.contact && event.action === 'attack')) onEvent(event,point,this.elapsed);return;}
      const image = this.scene.add.image(point.x,point.y,`effect-${i}`, '0').setScale(this.scale).setFlipX(this.facing < 0);
      this.effects.push({image,event,index:i,facing:this.facing,elapsed:this.elapsed-event.start_ms-delta});
      if (!(this.metadata.contact && event.action === 'attack')) onEvent(event, point, this.elapsed);
    });
    const contact = this.metadata.contact;
    if (contact && this.action === 'attack' && this.elapsed >= contact.start_ms && !this.fired.has('contact')) {
      this.fired.add('contact');
      onEvent(contact,eventPosition(this,pivot,contact),this.elapsed);
    }
    this.effects = this.effects.filter(fx => {
      fx.elapsed += delta;
      const i = frameAt(fx.event.frames,fx.elapsed);
      const rect = fx.event.frames[i].rect;
      const anchor = fx.event.effect_anchor_px || fx.event.pivot_px_from_top_left;
      fx.image.setFrame(String(i)).setOrigin(fx.facing < 0 ? 1-anchor[0]/rect.w : anchor[0]/rect.w,anchor[1]/rect.h);
      if (fx.elapsed >= fx.event.duration_ms) {fx.image.destroy(); return false;}
      return true;
    });
    if (!action.loop && this.elapsed >= action.duration_ms) this.play('idle');
  }
}

class Clearing extends Phaser.Scene {
  preload() {
    this.load.image('actor',bundle.files.atlas);
    loadCueSheets(this,bundle.feedback?.effects);
    (meta.events || []).forEach((e,i) => this.load.image(`effect-${i}`,bundle.files[`effect_${i}_sheet`]));
    this.load.on('loaderror',() => setStatus('An asset could not load. Check the local bundle.'));
  }
  create(data) {
    this.fxEnabled=document.getElementById('feel').getAttribute('aria-pressed')!=='false';
    this.moving=false;this.lastStep=0;this.sheetCues=[];this.sheetBindings=prepareCueSheets(this,bundle.feedback?.effects);
    document.getElementById('feel').onclick=()=>{this.fxEnabled=!this.fxEnabled;feedback.setEnabled(this.fxEnabled);this.actor.effectsEnabled=this.fxEnabled;const b=document.getElementById('feel');b.setAttribute('aria-pressed',String(this.fxEnabled));b.textContent=`Feel ${this.fxEnabled?'on':'off'} · A/B`;if(!this.fxEnabled){this.actor.effects.forEach(f=>f.image.destroy());this.actor.effects=[];this.sheetCues.forEach(c=>c.object.destroy());this.sheetCues=[];}};
    document.getElementById('sound').onclick=()=>{const b=document.getElementById('sound'),on=b.getAttribute('aria-pressed')!=='true';feedback.setSound(on);b.setAttribute('aria-pressed',String(on));b.textContent=`Sound ${on?'on':'off'}`;};
    this.add.rectangle(480,270,960,540,0x183136);
    for(let i=0;i<18;i++) this.add.rectangle(i*61+12,190,20+(i%3)*16,160,0x203e40).setAlpha(.7);
    this.add.rectangle(480,447,960,186,0x2b4843);
    this.add.rectangle(480,357,960,4,0x7c9870);
    this.shadow = this.add.ellipse(210,360,104,18,0x142b2d);
    this.target = this.add.rectangle(rules.target_x,rules.target_y,40,100,0xd5a45f).setStrokeStyle(4,0x6b4b2d);
    this.add.rectangle(rules.target_x,354,90,8,0x6b4b2d);
    this.actor = new ActionActor(this,meta,'actor',210,356);this.actor.effectsEnabled=this.fxEnabled;
    (meta.events || []).forEach((event,i) => {
      const texture=this.textures.get(`effect-${i}`);
      event.frames.forEach((f,n)=>texture.add(String(n),0,f.rect.x,f.rect.y,f.rect.w,f.rect.h));
    });
    this.hits=0; this.finished=false; this.contactEvents=[];
    this.keys=this.input.keyboard.addKeys('LEFT,RIGHT,A,D,SPACE,R');
    this.input.keyboard.addCapture(['LEFT','RIGHT']);
    this.input.keyboard.on('keydown-SPACE',event=>{if(event.target.closest?.('button'))return;event.preventDefault();this.strike();});
    this.input.keyboard.on('keydown-R',()=>{feedback.setSound(feedback.sound);this.scene.restart({restarted:true});});
    for (const name of ['left','right']) {
      const button=document.getElementById(name);
      let started=0;
      button.onclick=()=>{
        feedback.setSound(feedback.sound);
        if(!started||performance.now()-started<180){
          if(!this.finished&&this.actor.action!=='attack'){this.actor.facing=name==='right'?1:-1;this.actor.x=Phaser.Math.Clamp(this.actor.x+this.actor.facing*32,65,895);}
        }
        started=0;
      };
      button.onpointerdown=e=>{feedback.setSound(feedback.sound);started=performance.now();e.preventDefault();button.setPointerCapture(e.pointerId);held[name]=true;};
      button.onpointerup=button.onpointercancel=()=>{held[name]=false;};
    }
    window.onblur=()=>{held.left=false;held.right=false;};
    document.getElementById('attack').onclick=()=>this.strike();
    document.getElementById('restart').onclick=()=>{feedback.setSound(feedback.sound);held.left=false;held.right=false;this.scene.restart({restarted:true});};
    setStatus(`0 / ${rules.hits_to_win} · Move to the amber marker.`);
    this.game.canvas.setAttribute('aria-hidden','true');if(data?.restarted)this.cue('restart');
  }
  cue(name,details={}) {
    const cue=feedback.emit(name,details);
    if(this.fxEnabled){const impact=name==='hit'||name==='win';const mapped=spawnCueSheet(this,this.sheetBindings,name,{x:impact?rules.target_x:this.actor.x,y:impact?rules.target_y:this.actor.y,facing:this.actor.facing,reducedMotion:feedback.reducedMotion});if(mapped)this.sheetCues.push(mapped);}
    return cue;
  }
  strike() {feedback.setSound(feedback.sound);if (!this.finished && this.actor.action !== 'attack'){this.cue('attack');this.actor.play('attack');}}
  update(time,delta) {
    const a=this.actor;
    if (!a) return;
    if (!this.finished && a.action !== 'attack') {
      const direction=Number(held.right||this.keys.RIGHT.isDown||this.keys.D.isDown)-Number(held.left||this.keys.LEFT.isDown||this.keys.A.isDown);
      const previousX=a.x;
      if(direction){a.facing=direction;a.x=Phaser.Math.Clamp(a.x+direction*delta*.24,65,895);}
      const moving=a.x!==previousX;
      if(moving&&!this.moving)this.cue('move');
      if(!moving&&this.moving)this.cue('stop');
      if(moving&&time-this.lastStep>180){this.lastStep=time;this.cue('step');}
      this.moving=moving;
      if(moving&&a.action!=='walk')a.play('walk');
      else if(!moving&&a.action==='walk')a.play('idle');
    }
    this.sheetCues=this.sheetCues.filter(c=>advanceCueSheet(c,delta,feedback.reducedMotion));
    this.shadow.x=a.x;
    const impact=this.fxEnabled&&!feedback.reducedMotion&&time<this.impactUntil;this.target.setScale(impact?1.13:1,impact?.87:1).setPosition(rules.target_x+(impact?a.facing*6:0),rules.target_y);
    if(this.targetColor)this.target.setFillStyle(this.fxEnabled&&time<this.flashUntil?0xffffff:this.targetColor);
    a.update(delta,(event,point,elapsed)=>{
      if(event.action!=='attack')return;
      const contact=targetContact(a,point,rules);
      this.contactEvents.push({start_ms:event.start_ms,observed_ms:elapsed,point,contact});
      if(contact&&!this.finished){this.hits++;this.target.setFillStyle(this.hits===rules.hits_to_win?0x6cb39b:0xf6d695);this.finished=this.hits===rules.hits_to_win;
        this.cue('hit',{combo:this.hits});if(this.finished)this.cue('win');this.targetColor=this.finished?0x6cb39b:0xf6d695;this.flashUntil=time+65;this.impactUntil=time+120;
        setStatus(this.finished?`Clearing complete · ${rules.hits_to_win} clean strikes. Restart to play again.`:`${this.hits} / ${rules.hits_to_win} · Hit! Keep your stance and strike again.`);
      }else if(!this.finished){this.cue('miss');setStatus(`${this.hits} / ${rules.hits_to_win} · Miss. Face the marker and move closer.`);}
    });
  }
}
window.scoutGame = new Phaser.Game({type:Phaser.AUTO,parent:'game',width:960,height:540,pixelArt:true,backgroundColor:'#183136',scale:{mode:Phaser.Scale.FIT,autoCenter:Phaser.Scale.CENTER_BOTH},scene:isTrial?courierScene({Phaser,bundle,meta,ActionActor,feedback}):Clearing,audio:{noAudio:true}});
for (const [role,path] of Object.entries(bundle.files)) if (/_(license|notice)$/.test(role)) {
  const a=document.createElement('a');a.href=path;a.textContent=role;document.querySelector('#credits').append(a,document.createTextNode(' · '));
}
