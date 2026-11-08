import * as THREE from 'three';
import { GLTFLoader } from './vendor/three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from './vendor/three/examples/jsm/libs/meshopt_decoder.module.js';
import { createGame, move, attack, CRYSTALS, GOAL } from './game-state.mjs';
import { createFeedback } from './feedback.mjs';
const canvas = document.querySelector('#world');
const status = document.querySelector('#status');
const progress = document.querySelector('#progress');
const keys = new Set();
let game = createGame(), ready = false, paused = false;
let visualCue = () => {}, clearEffects = () => {};
let moved = false, stepDistance = 0, deniedAt = -Infinity;
const cueCounts = {};
const feedback = createFeedback({ sound: false, onCue(cue) {
  cueCounts[cue.name] = (cueCounts[cue.name] || 0) + 1;
  document.querySelector('#feedback-status').textContent = {
    pickup: 'Crystal secured', progress: 'Lantern light restored', win: 'Forest restored!',
    denied: 'Restore unavailable', restart: 'A fresh journey', pause: 'Paused', resume: 'Resumed',
  }[cue.name] || (['move','step','stop'].includes(cue.name) ? 'Exploring the forest' : 'Control confirmed');
  visualCue(cue);
} });
function travel(x, z, seconds) {
  const before = [...game.collected], oldX = game.x, oldZ = game.z;
  move(game, x, z, seconds);
  const distance = Math.hypot(game.x - oldX, game.z - oldZ);
  if (distance > .0001) {
    stepDistance += distance;
    if (!moved) feedback.emit('move', { x: game.x, z: game.z });
    if (stepDistance >= .45) { feedback.emit('step', { x: game.x, z: game.z }); stepDistance = 0; }
    moved = true;
  } else if (moved) { feedback.emit('stop', { x: game.x, z: game.z }); moved = false; stepDistance = 0; }
  game.collected.forEach((collected, i) => {
    if (collected && !before[i]) { feedback.emit('pickup', { x: CRYSTALS[i][0], z: CRYSTALS[i][1] }); publish(); }
  });
}
const buttons = [...document.querySelectorAll('button')];
buttons.forEach(b => { b.disabled = true; });
function publish() {
  progress.textContent = `Crystals ${game.collected.filter(Boolean).length} / 3 · Light ${game.charge} / 3`;
  status.textContent = paused ? 'Paused. Resume to continue your journey.' : game.message;
  document.querySelector('#pause').textContent = paused ? 'Resume' : 'Pause';
  document.querySelector('#pause').setAttribute('aria-pressed', String(paused));
}
function strike() {
  if (!ready || paused || game.won) return;
  const now = performance.now() / 1000;
  const previousAttack = game.attackAt;
  const accepted = attack(game, now);
  if (previousAttack === game.attackAt) return;
  if (accepted) {
    feedback.emit(game.won ? 'win' : 'progress', { x: GOAL[0], z: GOAL[1], charge: game.charge });
  } else if (now - deniedAt >= .65) {
    deniedAt = now;
    feedback.emit('denied', { x: game.x, z: game.z });
  }
  publish();
}
function reset() {
  if (!ready) return;
  game = createGame(); paused = false; keys.clear(); moved = false; stepDistance = 0; deniedAt = -Infinity;
  clearEffects(); feedback.emit('restart'); publish();
}
document.querySelector('#attack').addEventListener('click', strike);
document.querySelector('#reset').addEventListener('click', reset);
document.querySelector('#pause').addEventListener('click', () => {
  if (game.won) return;
  paused = !paused; keys.clear(); moved = false; stepDistance = 0;
  feedback.emit(paused ? 'pause' : 'resume'); publish();
});
document.querySelector('#feel').addEventListener('click', event => {
  const enabled = !feedback.enabled; feedback.setEnabled(enabled);
  event.currentTarget.setAttribute('aria-pressed', String(enabled));
  event.currentTarget.textContent = enabled ? 'Feel: on (B)' : 'Feel: off (A)';
  clearEffects(); feedback.emit('select');
  document.querySelector('#feedback-status').textContent = enabled ? 'Feel on · enhanced feedback' : 'Feel off · baseline';
});
document.querySelector('#sound').addEventListener('click', event => {
  feedback.setSound(!feedback.sound);
  event.currentTarget.setAttribute('aria-pressed', String(feedback.sound));
  event.currentTarget.textContent = feedback.sound ? 'Sound: on' : 'Sound: off';
  feedback.emit('select');
});
window.addEventListener('pagehide', event => { if (!event.persisted) feedback.dispose(); });
document.querySelector('.controls').addEventListener('click', event => {
  if (event.isTrusted && feedback.sound) feedback.setSound(true);
}, true);
document.querySelector('.controls').addEventListener('pointerdown', event => {
  if (event.isTrusted && feedback.sound) feedback.setSound(true);
}, true);
const controls = { up: 'ArrowUp', down: 'ArrowDown', left: 'ArrowLeft', right: 'ArrowRight' };
for (const button of document.querySelectorAll('[data-move]')) {
  const key = controls[button.dataset.move];
  let pressedAt = -Infinity;
  button.addEventListener('pointerdown', event => { button.setPointerCapture(event.pointerId); pressedAt = performance.now(); if (ready && !paused) keys.add(key); });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(event, () => keys.delete(key));
  button.addEventListener('click', event => { if (ready && !paused && (event.detail === 0 || performance.now() - pressedAt < 150)) { const [x,z] = {up:[0,-1],down:[0,1],left:[-1,0],right:[1,0]}[button.dataset.move]; travel(x,z,.15); publish(); } });
}
window.addEventListener('keydown', event => {
  if (['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Space','KeyW','KeyA','KeyS','KeyD','KeyR'].includes(event.code)) {
    if (event.isTrusted && feedback.sound) feedback.setSound(true);
    if (event.target.tagName === 'BUTTON' && event.code === 'Space') return;
    event.preventDefault(); keys.add(event.code);
    if (!event.repeat && event.code === 'Space') strike();
    if (!event.repeat && event.code === 'KeyR') reset();
  }
});
window.addEventListener('keyup', event => keys.delete(event.code));
window.addEventListener('blur', () => keys.clear());
document.addEventListener('visibilitychange', () => keys.clear());
async function json(path) { const r = await fetch(path); if (!r.ok) throw Error(`Missing local asset: ${path}`); return r.json(); }
try {
  const products = await json('products.json');
  const product = products.length === 1 ? products[0] : null;
  if (!product) throw Error('This sample requires a mesh-particle forest runtime.');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#10272b'); scene.fog = new THREE.Fog('#10272b', 13, 29);
  const camera = new THREE.PerspectiveCamera(43, 1, .1, 60); camera.position.set(0, 12, 14); camera.lookAt(0,0,0);
  scene.add(new THREE.HemisphereLight('#c4e4dd', '#243425', 2.2));
  const sun = new THREE.DirectionalLight('#ffe4af', 3); sun.position.set(-4,10,5); sun.castShadow = true;
  sun.shadow.mapSize.set(1024,1024); Object.assign(sun.shadow.camera,{left:-9,right:9,top:9,bottom:-9}); scene.add(sun);
  const ground = new THREE.Mesh(new THREE.CircleGeometry(9,64),new THREE.MeshStandardMaterial({color:'#304839',roughness:1}));
  ground.rotation.x = -Math.PI/2; ground.receiveShadow = true; scene.add(ground);
  const path = new THREE.Mesh(new THREE.PlaneGeometry(2,9),new THREE.MeshStandardMaterial({color:'#59604a',roughness:1}));
  path.rotation.x = -Math.PI/2; path.position.set(1,.006,0); path.receiveShadow = true; scene.add(path);
  for (let i=0;i<22;i++) {
    const angle=i*2.39996, radius=6.2+(i%3)*.6;
    const tree=new THREE.Group(); tree.position.set(Math.cos(angle)*radius,0,Math.sin(angle)*radius);
    const trunk=new THREE.Mesh(new THREE.CylinderGeometry(.11,.17,1.5,6),new THREE.MeshStandardMaterial({color:'#423d2b'})); trunk.position.y=.75;
    const crown=new THREE.Mesh(new THREE.ConeGeometry(.85,2.8,7),new THREE.MeshStandardMaterial({color:i%2?'#1a4037':'#255348'})); crown.position.y=2.1;
    trunk.castShadow=crown.castShadow=true; tree.add(trunk,crown); scene.add(tree);
  }
  const player=new THREE.Group();
  const body=new THREE.Mesh(new THREE.CapsuleGeometry(.24,.45,4,8),new THREE.MeshStandardMaterial({color:'#e5c995',roughness:.7})); body.position.y=.55; body.castShadow=true;
  const hat=new THREE.Mesh(new THREE.ConeGeometry(.4,.4,6),new THREE.MeshStandardMaterial({color:'#de8653'})); hat.position.y=1.1; hat.castShadow=true;
  player.add(body,hat); scene.add(player);
  const crystals=CRYSTALS.map(([x,z])=>{
    const mesh=new THREE.Mesh(new THREE.OctahedronGeometry(.3),new THREE.MeshStandardMaterial({color:'#66dce3',emissive:'#176e87',emissiveIntensity:.8,metalness:.3,roughness:.2}));
    mesh.position.set(x,.5,z);mesh.castShadow=true;scene.add(mesh);return mesh;
  });
  const ring=new THREE.Mesh(new THREE.TorusGeometry(.65,.055,8,40),new THREE.MeshBasicMaterial({color:'#f4c071'})); ring.rotation.x=Math.PI/2; ring.position.set(GOAL[0],.04,GOAL[1]);scene.add(ring);
  const aura=new THREE.PointLight('#ffc35b',0,7,2);aura.position.set(GOAL[0],1,GOAL[1]);scene.add(aura);
  // A fixed mesh pool keeps collection and celebration bursts in the scene's real depth.
  const shardGeometry = new THREE.OctahedronGeometry(1, 0);
  const shards = Array.from({ length: 48 }, () => {
    const mesh = new THREE.Mesh(shardGeometry, new THREE.MeshStandardMaterial({ color: '#8ce9ed', emissive: '#246b76', roughness: .35 }));
    mesh.visible = false; scene.add(mesh);
    return { mesh, age: 10, life: 1, vx: 0, vy: 0, vz: 0 };
  });
  const pulse = new THREE.PointLight('#8ce9ed', 0, 4); scene.add(pulse);
  let pulseAge = 10, pulseStrength = 0, poolCursor = 0, playerPulse = 0;
  clearEffects = () => { shards.forEach(s => { s.mesh.visible = false; s.age = 10; }); pulseAge = 10; pulse.intensity = 0; playerPulse = 0; };
  visualCue = cue => {
    const { name, detail = {} } = cue;
    const movement = ['move', 'step', 'stop'].includes(name);
    const color = name === 'denied' ? '#ed947d' : movement ? '#c9dab3' : name === 'pickup' ? '#8ce9ed' : '#ffce79';
    pulse.color.set(color); pulse.position.set(detail.x ?? game.x, .8, detail.z ?? game.z);
    pulseAge = 0; pulseStrength = name === 'win' ? 12 : movement ? .7 : 4;
    playerPulse = name === 'denied' ? -.25 : .25;
    if (!['pickup', 'progress', 'win'].includes(name)) return;
    const amount = feedback.reducedMotion ? 6 : name === 'win' ? 36 : 12;
    for (let i = 0; i < amount; i++) {
      const shard = shards[poolCursor++ % shards.length], angle = i * 2.39996;
      shard.age = 0; shard.life = feedback.reducedMotion ? .35 : name === 'win' ? 1.8 : .75;
      shard.mesh.position.set(detail.x, .5, detail.z); shard.mesh.material.color.set(color); shard.mesh.material.emissive.set(color).multiplyScalar(.3);
      shard.mesh.scale.set(.06, .16, .06); shard.mesh.visible = true;
      const speed = feedback.reducedMotion ? .15 : name === 'win' ? 2 : 1.3;
      shard.vx = Math.cos(angle) * speed; shard.vz = Math.sin(angle) * speed; shard.vy = feedback.reducedMotion ? .3 : 2 + i % 4 * .4;
    }
  };
  const loader=new GLTFLoader().setMeshoptDecoder(MeshoptDecoder), groups=new Map(), particles=[];
  const forest=new THREE.Group();forest.scale.setScalar(5);scene.add(forest);
  const modelNode=product.scene.nodes.find(n=> product.assets[n.asset].model && !product.assets[n.asset].effect);
  if (!modelNode) throw Error('The forest has no lantern model.');
  forest.position.set(GOAL[0]-modelNode.position[0]*5,0,GOAL[1]-modelNode.position[2]*5);
  for (const node of product.scene.nodes) {
    const asset=product.assets[node.asset]; if (!asset.model) continue;
    const group=new THREE.Group();group.position.fromArray(node.position);group.rotation.set(...node.rotation_degrees.map(THREE.MathUtils.degToRad));group.scale.fromArray(node.scale);
    groups.set(node.id,group);
    const model=(await loader.loadAsync(asset.model)).scene;
    model.updateMatrixWorld(true);
    if (asset.effect) {
      const descriptor=await json(asset.effect);
      const parts=[];
      model.traverse(mesh=>{
        if (!mesh.isMesh) return;
        const materials=(Array.isArray(mesh.material)?mesh.material:[mesh.material]).map(m=>{const copy=m.clone();copy.depthWrite=true;copy.depthTest=true;copy.transparent=false;return copy;});
        const instanced=new THREE.InstancedMesh(mesh.geometry,Array.isArray(mesh.material)?materials:materials[0],descriptor.particles.length);
        instanced.frustumCulled=false;group.add(instanced);parts.push({mesh:instanced,base:mesh.matrixWorld.clone()});
      });
      if (!parts.length) throw Error('Mesh particle GLB is empty.');
      particles.push({group,descriptor,parts});
    } else { model.traverse(m=>{if(m.isMesh){m.castShadow=true;m.receiveShadow=true;}});group.add(model); }
  }
  for (const node of product.scene.nodes) { const group=groups.get(node.id);if(group)(groups.get(node.parent)||forest).add(group); }
  let previous=performance.now();const transform=new THREE.Object3D(),matrix=new THREE.Matrix4();
  let frames=0, animationTime=0;
  // Read-only telemetry makes actual rendering and input observable to verification.
  window.woodsAlight = () => ({ready, ...JSON.parse(JSON.stringify(game)), paused, feedback:{enabled:feedback.enabled,sound:feedback.sound,reducedMotion:feedback.reducedMotion,cues:{...cueCounts},activeShards:shards.filter(s=>s.mesh.visible).length}, modelLoaded:true, meshParticleCount:particles.reduce((n,p)=>n+p.descriptor.particles.length,0), depthWriting:particles.every(p=>p.parts.every(part=>(Array.isArray(part.mesh.material)?part.mesh.material:[part.mesh.material]).every(m=>m.depthTest&&m.depthWrite&&!m.transparent))), frames, drawCalls:renderer.info.render.calls, triangles:renderer.info.render.triangles});
  function frame(now) {
    const dt=Math.min((now-previous)/1000,.05);previous=now; if (!paused) animationTime += dt; const time=animationTime;
    const x=Number(keys.has('ArrowRight')||keys.has('KeyD'))-Number(keys.has('ArrowLeft')||keys.has('KeyA'));
    const z=Number(keys.has('ArrowDown')||keys.has('KeyS'))-Number(keys.has('ArrowUp')||keys.has('KeyW'));
    if (!paused) travel(x,z,dt);
    player.position.set(game.x,0,game.z);if(x||z)player.rotation.y=Math.atan2(x,z);
    if (!paused) {
      pulseAge += dt; playerPulse *= Math.max(0, 1 - dt * 9);
      for (const shard of shards) {
        shard.age += dt; shard.mesh.visible = feedback.enabled && shard.age < shard.life;
        if (!shard.mesh.visible) continue;
        shard.mesh.position.x += shard.vx * dt; shard.mesh.position.z += shard.vz * dt;
        shard.mesh.position.y += shard.vy * dt; shard.vy -= dt * (feedback.reducedMotion ? 0 : 3);
        if (!feedback.reducedMotion) { shard.mesh.rotation.x += dt * 3; shard.mesh.rotation.z += dt * 2; }
        const scale = Math.max(0, 1 - shard.age / shard.life); shard.mesh.scale.set(.06 * scale, .16 * scale, .06 * scale);
      }
    }
    pulse.intensity = feedback.enabled ? pulseStrength * Math.max(0, 1 - pulseAge * 3) : 0;
    body.material.emissive.setHex(feedback.enabled && Math.abs(playerPulse) > .03 ? playerPulse < 0 ? 0x773322 : 0x556644 : 0);
    crystals.forEach((mesh,i)=>{mesh.visible=!game.collected[i];mesh.rotation.y=feedback.reducedMotion?0:time;mesh.position.y=.5+(feedback.reducedMotion?0:Math.sin(time*2+i)*.08);});
    aura.intensity=game.won?18:game.charge*3;ring.material.color.set(game.won?'#9cffe1':'#f4c071');
    for(const effect of particles){effect.group.visible=game.charge>0; const {descriptor}=effect;
      descriptor.particles.forEach((p,i)=>{const age=feedback.reducedMotion?Math.min(p.life_s/2,descriptor.duration_s/2):((time-p.start_s)%descriptor.duration_s+descriptor.duration_s)%descriptor.duration_s;
        transform.position.fromArray(p.offset).addScaledVector(new THREE.Vector3(...p.drift),age);
        transform.rotation.set(...p.spin.map(v=>v*age));transform.scale.setScalar(age<p.life_s?p.scale*Math.sin(Math.PI*age/p.life_s):0);transform.updateMatrix();
        for(const part of effect.parts){matrix.multiplyMatrices(transform.matrix,part.base);part.mesh.setMatrixAt(i,matrix);}
      });for(const part of effect.parts)part.mesh.instanceMatrix.needsUpdate=true;
    }
    const width=canvas.clientWidth,height=canvas.clientHeight;
    if(canvas.width!==Math.round(width*renderer.getPixelRatio())||canvas.height!==Math.round(height*renderer.getPixelRatio())){renderer.setSize(width,height,false);camera.aspect=width/height;const zoom=Math.max(1,1.25/camera.aspect);camera.position.set(0,12,14).multiplyScalar(zoom);scene.fog.near=13*zoom;scene.fog.far=29*zoom;camera.lookAt(0,0,0);camera.updateProjectionMatrix();}
    renderer.render(scene,camera);frames++;requestAnimationFrame(frame);
  }
  ready=true;buttons.forEach(b=>{b.disabled=false;});publish();requestAnimationFrame(frame);
} catch(error) {
  status.textContent='Unable to start'; const alert=document.querySelector('#error');alert.hidden=false;alert.textContent=error.message;console.error(error);
}
