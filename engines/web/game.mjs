import * as THREE from 'three';
import { GLTFLoader } from './vendor/three/examples/jsm/loaders/GLTFLoader.js';
import { createGame, move, attack, CRYSTALS, GOAL } from './game-state.mjs';
const canvas = document.querySelector('#world');
const status = document.querySelector('#status');
const progress = document.querySelector('#progress');
const keys = new Set();
let game = createGame(), ready = false;
const buttons = [...document.querySelectorAll('button')];
buttons.forEach(b => { b.disabled = true; });
function publish() {
  progress.textContent = `Crystals ${game.collected.filter(Boolean).length} / 3 · Light ${game.charge} / 3`;
  status.textContent = game.message;
}
function strike() { if (ready) { attack(game, performance.now() / 1000); publish(); } }
function reset() { if (ready) { game = createGame(); keys.clear(); publish(); } }
document.querySelector('#attack').addEventListener('click', strike);
document.querySelector('#reset').addEventListener('click', reset);
const controls = { up: 'ArrowUp', down: 'ArrowDown', left: 'ArrowLeft', right: 'ArrowRight' };
for (const button of document.querySelectorAll('[data-move]')) {
  const key = controls[button.dataset.move];
  let pressedAt = -Infinity;
  button.addEventListener('pointerdown', event => { button.setPointerCapture(event.pointerId); pressedAt = performance.now(); keys.add(key); });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(event, () => keys.delete(key));
  button.addEventListener('click', event => { if (ready && (event.detail === 0 || performance.now() - pressedAt < 150)) { const [x,z] = {up:[0,-1],down:[0,1],left:[-1,0],right:[1,0]}[button.dataset.move]; move(game,x,z,.15); publish(); } });
}
window.addEventListener('keydown', event => {
  if (['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Space','KeyW','KeyA','KeyS','KeyD','KeyR'].includes(event.code)) {
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
  const loader=new GLTFLoader(), groups=new Map(), particles=[];
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
  let frames=0;
  // Read-only telemetry makes actual rendering and input observable to verification.
  window.woodsAlight = () => ({ready, ...JSON.parse(JSON.stringify(game)), modelLoaded:true, meshParticleCount:particles.reduce((n,p)=>n+p.descriptor.particles.length,0), depthWriting:particles.every(p=>p.parts.every(part=>(Array.isArray(part.mesh.material)?part.mesh.material:[part.mesh.material]).every(m=>m.depthTest&&m.depthWrite&&!m.transparent))), frames, drawCalls:renderer.info.render.calls, triangles:renderer.info.render.triangles});
  function frame(now) {
    const dt=Math.min((now-previous)/1000,.05);previous=now; const time=now/1000;
    const x=Number(keys.has('ArrowRight')||keys.has('KeyD'))-Number(keys.has('ArrowLeft')||keys.has('KeyA'));
    const z=Number(keys.has('ArrowDown')||keys.has('KeyS'))-Number(keys.has('ArrowUp')||keys.has('KeyW'));
    const count=game.collected.filter(Boolean).length;move(game,x,z,dt);if(count!==game.collected.filter(Boolean).length)publish();
    player.position.set(game.x,0,game.z);if(x||z)player.rotation.y=Math.atan2(x,z);
    body.material.emissive.setHex(time-game.attackAt<.2?0x775522:0);
    crystals.forEach((mesh,i)=>{mesh.visible=!game.collected[i];mesh.rotation.y=time;mesh.position.y=.5+Math.sin(time*2+i)*.08;});
    aura.intensity=game.won?18:game.charge*3;ring.material.color.set(game.won?'#9cffe1':'#f4c071');
    for(const effect of particles){effect.group.visible=game.charge>0; const {descriptor}=effect;
      descriptor.particles.forEach((p,i)=>{const age=((time-p.start_s)%descriptor.duration_s+descriptor.duration_s)%descriptor.duration_s;
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
