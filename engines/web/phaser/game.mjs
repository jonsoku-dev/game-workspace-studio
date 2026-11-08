import {frameAt, eventPosition} from './timing.mjs';

const status = document.querySelector('#status');
const bundle = await fetch('game.json').then(r => {if (!r.ok) throw Error('Bundle unavailable'); return r.json();});
const meta = bundle.metadata;
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
      const image = this.scene.add.image(point.x,point.y,`effect-${i}`, '0').setScale(this.scale).setFlipX(this.facing < 0);
      this.effects.push({image,event,index:i,facing:this.facing,elapsed:this.elapsed-event.start_ms});
      onEvent(event, point, this.elapsed);
    });
    this.effects = this.effects.filter(fx => {
      const i = frameAt(fx.event.frames,fx.elapsed);
      const rect = fx.event.frames[i].rect;
      const anchor = fx.event.effect_anchor_px || fx.event.pivot_px_from_top_left;
      fx.image.setFrame(String(i)).setOrigin(fx.facing < 0 ? 1-anchor[0]/rect.w : anchor[0]/rect.w,anchor[1]/rect.h);
      fx.elapsed += delta;
      if (fx.elapsed >= fx.event.duration_ms) {fx.image.destroy(); return false;}
      return true;
    });
    if (!action.loop && this.elapsed >= action.duration_ms) this.play('idle');
  }
}

class Clearing extends Phaser.Scene {
  preload() {
    this.load.image('actor',bundle.files.atlas);
    (meta.events || []).forEach((e,i) => this.load.image(`effect-${i}`,bundle.files[`effect_${i}_sheet`]));
    this.load.on('loaderror',() => setStatus('An asset could not load. Check the local bundle.'));
  }
  create() {
    this.add.rectangle(480,270,960,540,0x183136);
    for(let i=0;i<18;i++) this.add.rectangle(i*61+12,190,20+(i%3)*16,160,0x203e40).setAlpha(.7);
    this.add.rectangle(480,447,960,186,0x2b4843);
    this.add.rectangle(480,357,960,4,0x7c9870);
    this.shadow = this.add.ellipse(210,360,104,18,0x142b2d);
    this.target = this.add.rectangle(650,300,40,100,0xd5a45f).setStrokeStyle(4,0x6b4b2d);
    this.add.rectangle(650,354,90,8,0x6b4b2d);
    this.actor = new ActionActor(this,meta,'actor',210,356);
    (meta.events || []).forEach((event,i) => {
      const texture=this.textures.get(`effect-${i}`);
      event.frames.forEach((f,n)=>texture.add(String(n),0,f.rect.x,f.rect.y,f.rect.w,f.rect.h));
    });
    this.hits=0; this.finished=false; this.contactEvents=[];
    this.keys=this.input.keyboard.addKeys('LEFT,RIGHT,A,D,SPACE,R');
    this.input.keyboard.addCapture(['LEFT','RIGHT']);
    this.input.keyboard.on('keydown-SPACE',event=>{if(event.target.closest?.('button'))return;event.preventDefault();this.strike();});
    this.input.keyboard.on('keydown-R',()=>this.scene.restart());
    for (const name of ['left','right']) {
      const button=document.getElementById(name);
      let started=0;
      button.onclick=()=>{
        if(!started||performance.now()-started<180){
          if(!this.finished&&this.actor.action!=='attack'){this.actor.facing=name==='right'?1:-1;this.actor.x=Phaser.Math.Clamp(this.actor.x+this.actor.facing*32,65,895);}
        }
        started=0;
      };
      button.onpointerdown=e=>{started=performance.now();e.preventDefault();button.setPointerCapture(e.pointerId);held[name]=true;};
      button.onpointerup=button.onpointercancel=()=>{held[name]=false;};
    }
    window.onblur=()=>{held.left=false;held.right=false;};
    document.getElementById('attack').onclick=()=>this.strike();
    document.getElementById('restart').onclick=()=>{held.left=false;held.right=false;this.scene.restart();};
    setStatus('0 / 3 · Move right to the amber marker.');
    this.game.canvas.setAttribute('aria-hidden','true');
  }
  strike() {if (!this.finished && this.actor.action !== 'attack') this.actor.play('attack');}
  update(time,delta) {
    const a=this.actor;
    if (!a) return;
    if (!this.finished && a.action !== 'attack') {
      const direction=Number(held.right||this.keys.RIGHT.isDown||this.keys.D.isDown)-Number(held.left||this.keys.LEFT.isDown||this.keys.A.isDown);
      if(direction){a.facing=direction;a.x=Phaser.Math.Clamp(a.x+direction*delta*.24,65,895);if(a.action!=='walk')a.play('walk');}
      else if(a.action==='walk')a.play('idle');
    }
    this.shadow.x=a.x;
    a.update(delta,(event,point,elapsed)=>{
      const contact=Math.abs(point.x-650)<56 && Math.abs(point.y-300)<64;
      this.contactEvents.push({start_ms:event.start_ms,observed_ms:elapsed,point,contact});
      if(contact&&!this.finished){this.hits++;this.target.setFillStyle(this.hits===3?0x6cb39b:0xf6d695);this.finished=this.hits===3;
        setStatus(this.finished?'Clearing complete · Three clean strikes. Restart to play again.':`${this.hits} / 3 · Hit! Keep your stance and strike again.`);
      }else if(!this.finished)setStatus(`${this.hits} / 3 · Miss. Face the marker and move closer.`);
    });
  }
}
window.scoutGame = new Phaser.Game({type:Phaser.AUTO,parent:'game',width:960,height:540,pixelArt:true,backgroundColor:'#183136',scale:{mode:Phaser.Scale.FIT,autoCenter:Phaser.Scale.CENTER_BOTH},scene:Clearing,audio:{noAudio:true}});
for (const [role,path] of Object.entries(bundle.files)) if (/_(license|notice)$/.test(role)) {
  const a=document.createElement('a');a.href=path;a.textContent=role;document.querySelector('#credits').append(a,document.createTextNode(' · '));
}
