import { THREE, loadModel, validateReceipt } from '/model/loader.mjs';
import { inspectionLabel } from './view-messages.mjs';

const active = new WeakMap();
const REVIEW_GAP_MS = 1000;
const INSPECTION_ACTIONS = ['idle', 'walk', 'run', 'attack', 'jump', 'hurt', 'death'];

// One-shot effects replay only for inspection, with a clearly reported hidden gap.
export function effectFrameAt(frames, loop, elapsed) {
  const duration = frames.reduce((sum, frame) => sum + frame.duration_ms, 0);
  let time = elapsed % (duration + (loop ? 0 : REVIEW_GAP_MS));
  if (time >= duration) return -1;
  for (let index = 0; index < frames.length; index++) {
    time -= frames[index].duration_ms;
    if (time < 0) return index;
  }
  return frames.length - 1;
}

export function actionPlaybackAt(action, events, elapsed) {
  const duration = action.frames.reduce((sum, frame) => sum + frame.duration_ms, 0);
  const end = Math.max(duration, ...events.map(event => event.start_ms + event.frames.reduce((sum, frame) => sum + frame.duration_ms, 0)));
  const cycle = action.loop ? duration : end + REVIEW_GAP_MS;
  const time = elapsed % cycle;
  const once = (frames, age) => {
    if (age < 0) return -1;
    for (let index = 0; index < frames.length; index++) {
      age -= frames[index].duration_ms;
      if (age < 0) return index;
    }
    return -1;
  };
  // Keep one instance per event: it survives actor wraps and is replaced at the next contact.
  const starts = events.map(event => elapsed < event.start_ms ? null :
    Math.floor((elapsed - event.start_ms) / cycle) * cycle + event.start_ms);
  return { frame: once(action.frames, Math.min(time, duration - 0.000001)),
    events: events.map((event, i) => starts[i] === null ? -1 : once(event.frames, elapsed - starts[i])),
    event_started_ms: starts, cycle_ms: cycle };

}

const vector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);

export function validateParticleEffect(effect) {
  if (effect?.schema_version !== 1 || effect.kind !== 'mesh-particles' || effect.units !== 'meters' ||
      !Number.isFinite(effect.duration_s) || effect.duration_s <= 0 || !Array.isArray(effect.particles) ||
      !effect.particles.length || effect.particles.length > 256 || effect.particles.some(p =>
        !p || !vector(p.offset) || !vector(p.drift) || !vector(p.spin) || !Number.isFinite(p.start_s) ||
        p.start_s < 0 || p.start_s >= effect.duration_s || !Number.isFinite(p.life_s) || p.life_s <= 0 ||
        p.life_s > effect.duration_s || !Number.isFinite(p.scale) || p.scale <= 0)) {
    throw new Error('Invalid mesh-particles effect descriptor');
  }
}

export function particleStateAt(particle, duration, elapsed) {
  const age = ((elapsed - particle.start_s) % duration + duration) % duration;
  const visible = age < particle.life_s;
  const u = visible ? age / particle.life_s : 0;
  const envelope = Math.sin(Math.PI * u);
  return { visible, age, position: particle.offset.map((n, i) => n + particle.drift[i] * u +
    envelope * 0.35 * [particle.drift[2], 0, -particle.drift[0]][i]),
    rotation: particle.spin.map(n => n * age), scale: visible ? particle.scale * Math.sqrt(Math.max(0, envelope)) : 0 };
}

export function createNodeHierarchy(nodes) {
  const root = new THREE.Group(), groups = new Map(), specs = new Map();
  for (const node of nodes) {
    if (typeof node.id !== 'string' || !node.id || groups.has(node.id) || !vector(node.position) ||
        !vector(node.rotation_degrees) || !vector(node.scale) || node.scale.some(n => n <= 0)) {
      throw new Error('Invalid or duplicate scene node transform');
    }
    const group = new THREE.Group();
    group.name = node.id;
    group.position.fromArray(node.position);
    group.rotation.set(...node.rotation_degrees.map(THREE.MathUtils.degToRad), 'XYZ');
    group.scale.fromArray(node.scale);
    groups.set(node.id, group); specs.set(node.id, node);
  }
  const attached = new Set(), visiting = new Set();
  const attach = id => {
    if (attached.has(id)) return;
    if (visiting.has(id)) throw new Error('Scene node parent cycle');
    visiting.add(id);
    const node = specs.get(id);
    if (node.parent !== undefined) {
      if (!groups.has(node.parent)) throw new Error('Scene node parent missing');
      attach(node.parent);
      groups.get(node.parent).add(groups.get(id));
    } else root.add(groups.get(id));
    visiting.delete(id); attached.add(id);
  };
  for (const id of groups.keys()) attach(id);
  return { root, groups };
}

// Fit the actual box in camera space instead of padding its circumscribed sphere.
export function inspectionDistance(min, max, direction, aspect, fov = 38) {
  const forward = new THREE.Vector3(...direction).normalize();
  const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), forward).normalize();
  const up = new THREE.Vector3().crossVectors(forward, right);
  const tangent = Math.tan(THREE.MathUtils.degToRad(fov / 2));
  let distance = 0;
  for (let corner = 0; corner < 8; corner++) {
    const point = new THREE.Vector3(...min.map((n, axis) => ((corner >> axis) & 1 ? max[axis] : n) - (n + max[axis]) / 2));
    distance = Math.max(distance, point.dot(forward) + Math.max(Math.abs(point.dot(right)) / (tangent * aspect), Math.abs(point.dot(up)) / tangent));
  }
  return Math.max(0.05, distance * 1.1);
}

export async function showScene(canvas, runtime, assetURL) {
  active.get(canvas)?.dispose();
  const abort = new AbortController();
  const resources = new Set();
  let renderer, animation = 0, resizeObserver, intersectionObserver, disposed = false;
  const listeners = [];
  const listen = (target, name, callback, options) => { target.addEventListener(name, callback, options); listeners.push(() => target.removeEventListener(name, callback, options)); };
  const own = resource => { if (disposed) resource.dispose(); else resources.add(resource); };
  const metrics = { state: 'loading', node_count: 0, positions: [], frame_count: 0,
    rendered_model_triangles: 0, model_non_background_pixels: 0, effects: [], actions: [],
    review_playback: 'Native mesh particles loop at authored duration; historic sprite one-shots replay after a 1000ms hidden inspection gap. No game controls.' };
  const owner = { metrics, dispose() {
    if (disposed) return;
    disposed = true;
    abort.abort();
    cancelAnimationFrame(animation);
    resizeObserver?.disconnect();
    intersectionObserver?.disconnect();
    for (const remove of listeners) remove();
    for (const resource of resources) resource.dispose();
    resources.clear();
    renderer?.dispose();
    if (active.get(canvas) === owner) {
      active.delete(canvas);
      canvas.dataset.sceneState = 'disposed';
    }
  } };
  active.set(canvas, owner);
  const publish = () => {
    if (active.get(canvas) !== owner) return;
    canvas.dataset.sceneState = metrics.state;
    canvas.dataset.sceneMetrics = JSON.stringify(metrics);
    canvas.dataset.sceneFrames = String(metrics.frame_count);
    canvas.dataset.modelTriangles = String(metrics.rendered_model_triangles);
  };
  const current = () => {
    if (disposed || active.get(canvas) !== owner) throw new DOMException('Scene superseded', 'AbortError');
  };
  const ownObject = object => object.traverse(child => {
    if (child.geometry) own(child.geometry);
    for (const material of child.material ? (Array.isArray(child.material) ? child.material : [child.material]) : []) {
      own(material);
      for (const value of Object.values(material)) if (value?.isTexture) own(value);
    }
  });
  const fetchFile = async file => {
    const response = await fetch(assetURL(file), { signal: abort.signal });
    if (!response.ok) throw new Error(`Unable to load scene asset (${response.status})`);
    return response;
  };
  const json = async file => (await fetchFile(file)).json();
  const readBitmap = async file => {
    const response = await fetchFile(file);
    const bitmap = await createImageBitmap(await response.blob(), { premultiplyAlpha: 'none', imageOrientation: 'flipY' });
    own({ dispose: () => bitmap.close() });
    current();
    return bitmap;
  };
  const validateFrames = (metadata, bitmap) => {
    if (!Array.isArray(metadata.frames) || !metadata.frames.length || typeof metadata.loop !== 'boolean' || metadata.frames.some(frame => {
      const r = frame.rect;
      return !r || ![r.x, r.y, r.w, r.h].every(Number.isInteger) || r.x < 0 || r.y < 0 || r.w <= 0 || r.h <= 0 ||
        r.x + r.w > bitmap.width || r.y + r.h > bitmap.height || !Number.isFinite(frame.duration_ms) || frame.duration_ms <= 0;
    })) throw new Error('Invalid action atlas frames');
  };
  publish();
  try {
    if (runtime?.status !== 'ready' || runtime.schema_version !== 1 || !Array.isArray(runtime.assets) || !runtime.nodes?.length ||
        runtime.coordinates?.units !== 'meters' || runtime.coordinates?.up !== '+Y' || runtime.coordinates?.handedness !== 'right') {
      throw new Error('Expected ready scene runtime with meters, right-handed +Y coordinates');
    }
    const loaded = new Map();
    for (const asset of runtime.assets) {
      if (loaded.has(asset.id)) throw new Error('Duplicate scene asset');
      if (asset.producer === 'model-assets') {
        const bytes = await (await fetchFile(asset.files.model)).arrayBuffer();
        const receipt = await json(asset.files.receipt);
        validateReceipt(receipt, bytes.byteLength);
        const model = await loadModel(bytes, { textures: true });
        // Track resources before a cancellation check so a superseded decode can be released.
        ownObject(model.gltf.scene);
        current();
        const effect = asset.files.effect ? await json(asset.files.effect) : null;
        if (effect) validateParticleEffect(effect);
        current();
        loaded.set(asset.id, { ...model, effect, producer: asset.producer });
      } else if (asset.producer === 'pixel-action-set') {
        const metadata = await json(asset.files.metadata);
        if (metadata?.schema_version !== 1 || !metadata.actions || !Array.isArray(metadata.events) ||
            !Array.isArray(metadata.pivot_px_from_top_left) || metadata.pivot_px_from_top_left.length !== 2 ||
            !metadata.pivot_px_from_top_left.every(Number.isFinite)) throw new Error('Invalid action-set metadata');
        const bitmap = await readBitmap(asset.files.atlas);
        for (const action of Object.values(metadata.actions)) validateFrames(action, bitmap);
        const eventAssets = [];
        for (const [index, event] of metadata.events.entries()) {
          const native = await json(asset.files[`effect_${index}_metadata`]);
          const image = await readBitmap(asset.files[`effect_${index}_sheet`]);
          const action = metadata.actions[event.action];
          if (!action || !Number.isInteger(event.frame) || event.frame < 0 || event.frame >= action.frames.length ||
              !Number.isFinite(event.start_ms) || event.start_ms !== action.frames.slice(0, event.frame).reduce((sum, frame) => sum + frame.duration_ms, 0) ||
              !Array.isArray(event.at_px) || event.at_px.length !== 2 || !event.at_px.every(Number.isFinite) ||
              !Array.isArray(event.effect_anchor_px) || event.effect_anchor_px.length !== 2 || !event.effect_anchor_px.every(Number.isFinite)) {
            throw new Error('Invalid action contact event');
          }
          const normalized = { frames: event.frames, loop: false, pivot_px_from_top_left: event.effect_anchor_px };
          validateFrames(normalized, image);
          if (!Array.isArray(native.frames) || native.frames.length !== event.frames.length || native.frames.some((frame, i) => {
            const expected = event.frames[i];
            return frame.duration !== expected.duration_ms || ['x', 'y', 'w', 'h'].some(key => frame.frame?.[key] !== expected.rect[key]);
          })) throw new Error('Contact effect differs from native pixelfx atlas metadata');
          eventAssets.push({ event, bitmap: image, metadata: normalized });
        }
        loaded.set(asset.id, { producer: asset.producer, metadata, bitmap, eventAssets });
      } else if (asset.producer === 'pixel-effect') {
        const metadata = await json(asset.files.metadata);
        const response = await fetchFile(asset.files.sheet);
        const bitmap = await createImageBitmap(await response.blob(), { premultiplyAlpha: 'none', imageOrientation: 'flipY' });
        if (disposed) { bitmap.close(); current(); }
        const frames = metadata.frames;
        if (!Array.isArray(frames) || !frames.length || typeof metadata.loop !== 'boolean' ||
            !Array.isArray(metadata.pivot_px_from_top_left) || metadata.pivot_px_from_top_left.length !== 2 ||
            !metadata.pivot_px_from_top_left.every(Number.isFinite) || frames.some(frame => {
              const r = frame.rect;
              return !r || ![r.x, r.y, r.w, r.h].every(Number.isInteger) || r.x < 0 || r.y < 0 || r.w <= 0 || r.h <= 0 ||
                r.x + r.w > bitmap.width || r.y + r.h > bitmap.height ||
                metadata.pivot_px_from_top_left.some((p, i) => p < 0 || p > (i === 0 ? r.w : r.h)) || !Number.isFinite(frame.duration_ms) || frame.duration_ms <= 0;
            })) { bitmap.close(); throw new Error('Invalid sprite frame metadata'); }
        const bitmapResource = { dispose: () => bitmap.close() };
        own(bitmapResource);
        loaded.set(asset.id, { producer: asset.producer, metadata, bitmap });
      } else throw new Error('Unsupported scene producer');
    }
    current();
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    const all2D = !runtime.nodes.some(node => runtime.assets.find(asset => asset.id === node.asset)?.producer === 'model-assets');
    renderer.setPixelRatio(all2D ? 1 : Math.min(devicePixelRatio || 1, 2));
    metrics.camera = all2D ? 'orthographic-front' : 'perspective';
    metrics.studio_floor = !all2D;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#17191d');
    const { root, groups } = createNodeHierarchy(runtime.nodes);
    const models = [], effects = [], meshEffects = [], studio = new THREE.Group();
    const visible = (objects, value) => { for (const object of objects) object.visible = value; };
    scene.add(root, studio);
    scene.add(new THREE.HemisphereLight(0xe8edfa, 0x333138, 1.4));
    // Local softboxes provide broad highlights on metal and glass without network assets.
    if (!all2D) {
      const environment = new THREE.Scene();
      environment.background = new THREE.Color(0x50535b);
      for (const [position, scale, color] of [
        [[-4, 4, 3], [3, 6, 1], 0xffe7cf], [[4, 3, 0], [2, 5, 1], 0xd6e4ff], [[0, 6, -3], [5, 2, 1], 0xffffff]
      ]) {
        const card = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }));
        card.position.fromArray(position); card.scale.fromArray(scale); card.lookAt(0, 0, 0); environment.add(card);
      }
      const pmrem = new THREE.PMREMGenerator(renderer);
      const lighting = pmrem.fromScene(environment, 0.06);
      scene.environment = lighting.texture; own(lighting);
      environment.traverse(object => { object.geometry?.dispose(); object.material?.dispose(); });
      pmrem.dispose();
      metrics.lighting = 'local-softbox-environment';
    }
    const key = new THREE.DirectionalLight(0xffe5cb, 3);
    key.castShadow = true;
    own(key.shadow);
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.bias = -0.0002;
    scene.add(key, key.target);
    const fill = new THREE.DirectionalLight(0xcbdcff, 1.4);
    scene.add(fill);
    const playback = [], particlePlayback = [], actionPlayback = [], pixelProofs = [];
    let needsPixelProof = false;
    const sprite = (group, bitmap, metadata, size, proof) => {
      const texture = new THREE.Texture(bitmap);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.magFilter = texture.minFilter = THREE.NearestFilter;
      texture.generateMipmaps = false; texture.needsUpdate = true; own(texture);
      const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, alphaTest: 0.01, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
      const geometry = new THREE.PlaneGeometry(1, 1), mesh = new THREE.Mesh(geometry, material);
      own(material); own(geometry);
      const content = new THREE.Group(); content.add(mesh); group.add(content); effects.push(content);
      const result = { mesh, texture, bitmap, metadata, size, proof, content };
      pixelProofs.push(result);
      return result;
    };
    for (const node of runtime.nodes) {
      const asset = loaded.get(node.asset);
      if (!asset) throw new Error('Node references missing asset');
      const group = groups.get(node.id);
      if (asset.producer === 'model-assets' && asset.effect) {
        const content = new THREE.Group();
        const parts = [];
        asset.gltf.scene.updateMatrixWorld(true);
        asset.gltf.scene.traverse(mesh => {
          if (!mesh.isMesh) return;
          const instanced = new THREE.InstancedMesh(mesh.geometry, mesh.material, asset.effect.particles.length);
          instanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
          // The source is an opaque 3D ember; native depth testing also occludes particles behind the lantern.
          for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
            material.depthTest = material.depthWrite = true;
          }
          instanced.frustumCulled = false;
          own(instanced);
          content.add(instanced);
          parts.push({ mesh: instanced, base: mesh.matrixWorld.clone() });
        });
        if (!parts.length) throw new Error('Mesh effect has no source mesh');
        group.add(content); effects.push(content); meshEffects.push(content);
        const proof = { node: node.id, kind: 'mesh-particles', particle_count: asset.effect.particles.length,
          glb_triangle_count: asset.metrics.triangle_count, live_count: 0, rendered_triangles: 0,
          contribution_pixels: 0, transform_samples: [], attached_world_origin: [], sample_time_s: 0,
          motion_delta_m: [0, 0, 0], instanced_mesh_count: parts.length, depth_test: true, depth_write: true };
        metrics.effects.push(proof);
        particlePlayback.push({ group, content, parts, descriptor: asset.effect, proof, previous: new Map(), sourceBounds: asset.metrics.bounds });
      } else if (asset.producer === 'model-assets') {
        const model = asset.gltf.scene.clone(true);
        model.traverse(child => { if (child.isMesh) { child.castShadow = true; child.receiveShadow = true; } });
        group.add(model);
        models.push(model);
      } else if (asset.producer === 'pixel-action-set') {
        if (!Number.isFinite(node.size_m) || node.size_m <= 0) throw new Error('Action size_m must be positive');
        const name = node.action ?? 'idle', action = asset.metadata.actions[name];
        if (!action) throw new Error('Unknown named sprite action');
        const proof = { node: node.id, action: name, authored_action: name, inspection_override: null, frame_index: -1, observed_frames: [], frame_changes: 0,
          pivot_px_from_top_left: asset.metadata.pivot_px_from_top_left, samples: [],
          review_playback: action.loop ? 'authored loop' : 'hold final pose; replay after effect tail and 1000ms review gap' };
        metrics.actions.push(proof);
        const actor = sprite(group, asset.bitmap, { ...action, pivot_px_from_top_left: asset.metadata.pivot_px_from_top_left }, node.size_m, proof);
        const events = [];
        for (const eventAsset of asset.eventAssets) {
          const { event } = eventAsset;
          const anchor = new THREE.Group();
          const pixelsPerMeter = node.size_m / asset.metadata.actions[event.action].frames[0].rect.w;
          anchor.position.set((event.at_px[0] - asset.metadata.pivot_px_from_top_left[0]) * pixelsPerMeter,
            (asset.metadata.pivot_px_from_top_left[1] - event.at_px[1]) * pixelsPerMeter, 0.001);
          group.add(anchor);
          const contactProof = { node: node.id, kind: 'action-contact-effect', action: event.action, contact_frame: event.frame,
            start_ms: event.start_ms, at_px: event.at_px, effect_anchor_px: event.effect_anchor_px,
            original_pivot_px_from_top_left: event.pivot_px_from_top_left, frame_index: -1, observed_frames: [], frame_changes: 0,
            contact_observations: 0, contact_started_ms: null, retrigger_policy: 'newest contact replaces previous instance; actor loop boundaries preserve active effect', samples: [] };
          metrics.effects.push(contactProof);
          events.push({ ...sprite(anchor, eventAsset.bitmap, eventAsset.metadata, event.frames[0].rect.w * pixelsPerMeter, contactProof), event });
        }
        actionPlayback.push({ actor, events, action, actions: asset.metadata.actions, authoredAction: name });
      } else {
        if (!Number.isFinite(node.size_m) || node.size_m <= 0) throw new Error('Effect size_m must be positive');
        const texture = new THREE.Texture(asset.bitmap);
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.magFilter = texture.minFilter = THREE.NearestFilter;
        texture.generateMipmaps = false;
        texture.needsUpdate = true;
        own(texture);
        const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, alphaTest: 0.01, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
        const geometry = new THREE.PlaneGeometry(1, 1);
        const mesh = new THREE.Mesh(geometry, material);
        own(material); own(geometry);
        const content = new THREE.Group();
        content.add(mesh); group.add(content);
        effects.push(content);
        const proof = { node: node.id, kind: 'pixel-effect', frame_index: -1, observed_frames: [], frame_changes: 0,
          frame_rect: null, pivot_px_from_top_left: asset.metadata.pivot_px_from_top_left,
          authored_loop: asset.metadata.loop, inspection_gap_ms: asset.metadata.loop ? 0 : REVIEW_GAP_MS };
        metrics.effects.push(proof);
        const effect = { mesh, texture, ...asset, size: node.size_m, proof, content };
        playback.push(effect); pixelProofs.push(effect);
      }
      metrics.positions.push({ id: node.id, asset: node.asset, parent: node.parent ?? null, position: [...node.position], rotation_degrees: [...node.rotation_degrees], scale: [...node.scale] });
    }
    function applyFrame(effect, index) {
      const r = effect.metadata.frames[index].rect;
      effect.texture.repeat.set(r.w / effect.bitmap.width, r.h / effect.bitmap.height);
      effect.texture.offset.set(r.x / effect.bitmap.width, 1 - (r.y + r.h) / effect.bitmap.height);
      const [px, py] = effect.metadata.pivot_px_from_top_left;
      const height = effect.size * r.h / r.w;
      effect.mesh.scale.set(effect.size, height, 1);
      effect.mesh.position.set(effect.size * (0.5 - px / r.w), height * (py / r.h - 0.5), 0);
    }
    function setFrame(effect, index) {
      effect.mesh.visible = index >= 0;
      if (effect.proof.frame_index === index) return;
      effect.proof.frame_index = index;
      effect.proof.frame_changes++;
      if (index < 0) return;
      if (!effect.proof.observed_frames.includes(index)) effect.proof.observed_frames.push(index);
      effect.proof.frame_rect = { ...effect.metadata.frames[index].rect };
      applyFrame(effect, index);
    }
    const particleObject = new THREE.Object3D(), particleMatrix = new THREE.Matrix4();
    function updateParticles(elapsed) {
      for (const effect of particlePlayback) {
        effect.proof.live_count = 0;
        effect.proof.transform_samples = [];
        effect.proof.sample_time_s = elapsed;
        effect.proof.attached_world_origin = effect.group.getWorldPosition(new THREE.Vector3()).toArray();
        const minimum = [Infinity, Infinity, Infinity], maximum = [-Infinity, -Infinity, -Infinity];
        effect.descriptor.particles.forEach((particle, index) => {
          const state = particleStateAt(particle, effect.descriptor.duration_s, elapsed);
          particleObject.position.fromArray(state.position);
          particleObject.rotation.set(...state.rotation, 'XYZ');
          particleObject.scale.setScalar(state.scale);
          particleObject.updateMatrix();
          for (const part of effect.parts) {
            particleMatrix.multiplyMatrices(particleObject.matrix, part.base);
            part.mesh.setMatrixAt(index, particleMatrix);
          }
          if (state.visible && state.scale > 0) {
            effect.proof.live_count++;
            const world = effect.group.localToWorld(new THREE.Vector3(...state.position)).toArray();
            const previous = effect.previous.get(index);
            if (previous) world.forEach((n, i) => { effect.proof.motion_delta_m[i] = Math.max(effect.proof.motion_delta_m[i], Math.abs(n - previous[i])); });
            effect.previous.set(index, world);
            world.forEach((n, i) => { minimum[i] = Math.min(minimum[i], n); maximum[i] = Math.max(maximum[i], n); });
            if (effect.proof.transform_samples.length < 8) effect.proof.transform_samples.push({ index, position: state.position, world_position: world, rotation: state.rotation, scale: state.scale, instance_matrix: particleMatrix.toArray() });
          }
        });
        for (const part of effect.parts) part.mesh.instanceMatrix.needsUpdate = true;
        effect.proof.world_span = minimum.map((n, i) => effect.proof.live_count ? maximum[i] - n : 0);
      }
    }
    function updateActions(elapsed) {
      for (const item of actionPlayback) {
        const selected = item.events.filter(effect => effect.event.action === item.actor.proof.action);
        for (const effect of item.events) if (!selected.includes(effect)) setFrame(effect, -1);
        const state = actionPlaybackAt(item.action, selected.map(effect => effect.event), elapsed);
        setFrame(item.actor, state.frame);
        item.actor.proof.elapsed_ms = Math.round(elapsed);
        selected.forEach((effect, index) => {
          if (state.events[index] >= 0 && effect.proof.contact_started_ms !== state.event_started_ms[index]) {
            effect.proof.contact_observations++;
            effect.proof.contact_started_ms = state.event_started_ms[index];
            needsPixelProof = true;
          }
          setFrame(effect, state.events[index]);
          effect.proof.actor_frame_index = state.frame;
        });
      }
    }
    for (const effect of playback) setFrame(effect, 0);
    updateActions(0);
    scene.updateMatrixWorld(true);
    const bounds = new THREE.Box3();
    for (const effect of pixelProofs) applyFrame(effect, Math.max(0, effect.proof.frame_index));
    scene.updateMatrixWorld(true);
    for (const object of [...models, ...effects.filter(object => !meshEffects.includes(object))]) bounds.union(new THREE.Box3().setFromObject(object));
    // Keep every available inspection pose inside the fixed camera bounds.
    for (const item of actionPlayback) {
      const metadata = item.actor.metadata;
      for (const action of Object.values(item.actions)) {
        item.actor.metadata = { ...action, pivot_px_from_top_left: metadata.pivot_px_from_top_left };
        for (let frame = 0; frame < action.frames.length; frame++) {
          applyFrame(item.actor, frame); scene.updateMatrixWorld(true);
          bounds.union(new THREE.Box3().setFromObject(item.actor.content));
        }
      }
      item.actor.metadata = metadata;
      applyFrame(item.actor, Math.max(0, item.actor.proof.frame_index));
    }
    scene.updateMatrixWorld(true);
    // Frame the full authored particle paths, including curl and the original mesh's maximum radius.
    for (const effect of particlePlayback) {
      const meshRadius = Math.max(...effect.sourceBounds.min.map(Math.abs), ...effect.sourceBounds.max.map(Math.abs)) * Math.sqrt(3);
      for (const particle of effect.descriptor.particles) {
        const curl = [Math.abs(particle.drift[2]) * 0.35, 0, Math.abs(particle.drift[0]) * 0.35];
        const local = new THREE.Box3(
          new THREE.Vector3(...particle.offset.map((n, i) => Math.min(n, n + particle.drift[i]) - curl[i] - meshRadius * particle.scale)),
          new THREE.Vector3(...particle.offset.map((n, i) => Math.max(n, n + particle.drift[i]) + curl[i] + meshRadius * particle.scale)));
        bounds.union(local.applyMatrix4(effect.group.matrixWorld));
      }
    }
    updateParticles(0);
    for (const position of metrics.positions) position.world_origin = groups.get(position.id).getWorldPosition(new THREE.Vector3()).toArray();
    if (bounds.isEmpty()) throw new Error('Scene has no drawable bounds');
    const sphere = bounds.getBoundingSphere(new THREE.Sphere());
    const radius = Math.max(sphere.radius, 0.05);
    const center = sphere.center;
    if (!all2D) {
      const ground = new THREE.Mesh(new THREE.PlaneGeometry(radius * 80, radius * 80), new THREE.MeshStandardMaterial({ color: 0x25272d, roughness: 0.92 }));
      ground.rotation.x = -Math.PI / 2;
      ground.position.set(center.x, Math.min(0, bounds.min.y) - 0.003, center.z);
      ground.receiveShadow = true;
      studio.add(ground);
      const grid = new THREE.GridHelper(radius * 6, 12, 0x555963, 0x3e424b);
      grid.position.copy(ground.position); grid.position.y += 0.001;
      grid.material.transparent = true; grid.material.opacity = 0.16; grid.material.depthWrite = false;
      studio.add(grid); ownObject(studio);
      scene.fog = new THREE.Fog(scene.background, radius * 6, radius * 18);
    }
    key.position.copy(center).add(new THREE.Vector3(radius * 3, radius * 5, radius * 4));
    key.target.position.copy(center);
    key.shadow.camera.left = key.shadow.camera.bottom = -radius * 3;
    key.shadow.camera.right = key.shadow.camera.top = radius * 3;
    key.shadow.camera.near = radius * 0.1; key.shadow.camera.far = radius * 15;
    key.shadow.normalBias = radius * 0.002;
    fill.position.copy(center).add(new THREE.Vector3(-radius * 3, radius * 2, radius * 2));
    const camera = all2D ? new THREE.OrthographicCamera(-1, 1, 1, -1, radius / 100, radius * 100) : new THREE.PerspectiveCamera(38, 1, radius / 100, radius * 100);
    let yaw = Math.atan2(1.2, 2), viewZoom = 1;
    let requestDraw = () => {};
    const resize = () => {
      const width = Math.max(1, canvas.clientWidth || 960), height = Math.max(1, canvas.clientHeight || 600);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      if (all2D) {
        const size = bounds.getSize(new THREE.Vector3());
        const halfHeight = Math.max(size.y / 2, size.x / (2 * camera.aspect), 0.05) * 1.12;
        camera.left = -halfHeight * camera.aspect; camera.right = halfHeight * camera.aspect;
        camera.top = halfHeight / viewZoom; camera.bottom = -halfHeight / viewZoom;
        camera.left /= viewZoom; camera.right /= viewZoom;
        camera.position.copy(center).add(new THREE.Vector3(0, 0, radius * 5));
      } else {
        const direction = new THREE.Vector3(Math.sin(yaw), 0.28, Math.cos(yaw)).normalize();
        const distance = inspectionDistance(bounds.min.toArray(), bounds.max.toArray(), direction.toArray(), camera.aspect);
        camera.position.copy(center).add(direction.multiplyScalar(distance / viewZoom));
      }
      camera.lookAt(center);
      camera.updateProjectionMatrix();
      needsPixelProof = true;
      requestDraw();
    };
    resize();
    resizeObserver = new ResizeObserver(resize); resizeObserver.observe(canvas);
    const gl = renderer.getContext();
    metrics.backend = 'WebGL'; metrics.webgl_version = gl.getParameter(gl.VERSION);
    metrics.bounds = { min: bounds.min.toArray(), max: bounds.max.toArray() };
    metrics.node_count = runtime.nodes.length;
    const readFrame = () => {
      renderer.render(scene, camera);
      const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
      gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      return pixels;
    };
    const difference = (a, b) => {
      let count = 0;
      for (let i = 0; i < a.length; i += 4) if (a[i] !== b[i] || a[i + 1] !== b[i + 1] || a[i + 2] !== b[i + 2]) count++;
      return count;
    };
    // Isolate the lantern/static models from all effect geometry, ground, and shadow passes.
    renderer.shadowMap.enabled = false;
    studio.visible = false; visible(effects, false); visible(models, false);
    const blank = readFrame();
    visible(models, true);
    const modelPixels = readFrame();
    metrics.rendered_model_triangles = renderer.info.render.triangles;
    metrics.model_non_background_pixels = difference(blank, modelPixels);
    const sampleEffects = () => {
      renderer.shadowMap.enabled = false;
      studio.visible = true; visible(effects, false);
      const without = readFrame();
      const baselineTriangles = renderer.info.render.triangles;
      visible(effects, true);
      metrics.effect_non_background_pixels = difference(without, readFrame());
      for (const effect of particlePlayback) {
        // Keep the lantern in the depth buffer so this measures visible, correctly occluded particles.
        visible(effects, false); effect.content.visible = true;
        const withEffect = readFrame();
        effect.proof.rendered_triangles = renderer.info.render.triangles - baselineTriangles;
        effect.proof.contribution_time_s = effect.proof.sample_time_s;
        effect.proof.live_geometric_triangles = effect.proof.live_count * effect.proof.glb_triangle_count;
        effect.proof.contribution_pixels = difference(without, withEffect);
        visible(models, false); studio.visible = false;
        readFrame();
        effect.proof.isolated_drawn_triangles = renderer.info.render.triangles;
        visible(models, true); studio.visible = true;
      }
      for (const effect of pixelProofs) {
        visible(effects, false); effect.content.visible = true;
        const withEffect = readFrame();
        effect.proof.contribution_pixels = difference(without, withEffect);
        effect.proof.drawn_triangles = renderer.info.render.triangles - baselineTriangles;
        if (effect.mesh.visible && effect.proof.samples?.length < 20) effect.proof.samples.push({
          elapsed_ms: metrics.elapsed_ms ?? 0, frame_index: effect.proof.frame_index,
          frame_rect: effect.proof.frame_rect, contribution_pixels: effect.proof.contribution_pixels });
      }
      visible(effects, true); renderer.shadowMap.enabled = !all2D;
      needsPixelProof = false;
    };
    sampleEffects();
    renderer.shadowMap.autoUpdate = false;
    renderer.shadowMap.needsUpdate = !all2D;
    const motion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)');
    let paused = Boolean(motion?.matches), elapsed = 0, previousTime = null, inViewport = true;
    const animated = playback.length + actionPlayback.length + particlePlayback.length > 0;
    const draw = now => {
      animation = 0;
      if (disposed) return;
      if (!paused && previousTime !== null) elapsed += now - previousTime;
      previousTime = now;
      metrics.elapsed_ms = Math.round(elapsed);
      metrics.rendered_elapsed_ms = metrics.elapsed_ms;
      metrics.paused = paused;
      metrics.state = paused ? 'paused' : 'playing';
      for (const effect of playback) setFrame(effect, effectFrameAt(effect.metadata.frames, effect.metadata.loop, elapsed));
      updateActions(elapsed);
      updateParticles(elapsed / 1000);
      if (needsPixelProof || metrics.frame_count % 60 === 0) sampleEffects();
      renderer.render(scene, camera);
      metrics.frame_count++;
      metrics.drawn_scene_triangles = renderer.info.render.triangles;
      publish();
      if (animated && !paused && inViewport && !document.hidden) animation = requestAnimationFrame(draw);
    };
    requestDraw = () => {
      if (disposed) return;
      metrics.elapsed_ms = Math.round(elapsed);
      metrics.paused = paused;
      metrics.state = paused ? 'paused' : 'playing';
      if (paused || document.hidden || !inViewport) {
        cancelAnimationFrame(animation); animation = 0;
      }
      if (document.hidden || !inViewport) { publish(); return; }
      if (paused) draw(performance.now());
      else {
        publish();
        if (!animation) animation = requestAnimationFrame(draw);
      }
    };
    Object.assign(owner, {
      setAction(name) {
        if (disposed) return false;
        if (name !== null && (!INSPECTION_ACTIONS.includes(name) || !actionPlayback.length || actionPlayback.some(item => !Object.hasOwn(item.actions, name)))) return false;
        for (const item of actionPlayback) {
          const selected = name ?? item.authoredAction;
          item.action = item.actions[selected];
          item.actor.metadata = { ...item.action, pivot_px_from_top_left: item.actor.metadata.pivot_px_from_top_left };
          Object.assign(item.actor.proof, { action: selected, inspection_override: name, frame_index: -1, observed_frames: [], frame_changes: 0, samples: [],
            review_playback: item.action.loop ? 'authored loop' : 'hold final pose; replay after effect tail and 1000ms review gap' });
          for (const effect of item.events) {
            Object.assign(effect.proof, { contact_started_ms: null, contact_observations: 0, observed_frames: [], frame_changes: 0, samples: [] });
          }
        }
        metrics.inspection.action_override = name;
        elapsed = 0; previousTime = null; needsPixelProof = true; requestDraw();
        return true;
      },
      setPaused(value) {
        if (disposed) return;
        if (!paused && previousTime !== null) elapsed += performance.now() - previousTime;
        paused = Boolean(value); previousTime = null; requestDraw();
      },
      seek(milliseconds) {
        if (disposed || !Number.isFinite(milliseconds) || milliseconds < 0) return;
        elapsed = milliseconds; previousTime = null; needsPixelProof = true; requestDraw();
      },
      rotate(radians) { if (!disposed && Number.isFinite(radians) && !all2D) { yaw += radians; resize(); } },
      zoom(factor) { if (!disposed && Number.isFinite(factor) && factor > 0) { viewZoom = THREE.MathUtils.clamp(viewZoom * factor, 0.6, 2.5); resize(); } },
      resetView() { if (!disposed) { yaw = Math.atan2(1.2, 2); viewZoom = 1; resize(); } }
    });
    if (!canvas.hasAttribute('tabindex')) canvas.tabIndex = 0;
    if (!canvas.hasAttribute('aria-label')) {
      let label = inspectionLabel();
      canvas.setAttribute('aria-label', label);
      listeners.push(() => {
        if (canvas.getAttribute('aria-label') === label) canvas.removeAttribute('aria-label');
      });
      listen(window, 'studio:localechange', () => {
        if (canvas.getAttribute('aria-label') !== label) return;
        label = inspectionLabel();
        canvas.setAttribute('aria-label', label);
      });
    }
    listen(canvas, 'keydown', event => {
      const commands = {
        ' ': () => owner.setPaused(!paused), ArrowLeft: () => owner.rotate(-0.12), ArrowRight: () => owner.rotate(0.12),
        ArrowUp: () => owner.zoom(1.12), ArrowDown: () => owner.zoom(1 / 1.12), Home: () => owner.resetView(),
        '[': () => { owner.setPaused(true); owner.seek(Math.max(0, elapsed - 100)); },
        ']': () => { owner.setPaused(true); owner.seek(elapsed + 100); }
      };
      if (commands[event.key]) { event.preventDefault(); commands[event.key](); }
    });
    const wake = () => { previousTime = null; if (document.hidden || !inViewport) { cancelAnimationFrame(animation); animation = 0; } else requestDraw(); };
    listen(document, 'visibilitychange', wake);
    if (motion) listen(motion, 'change', event => owner.setPaused(event.matches));
    if (globalThis.IntersectionObserver) {
      intersectionObserver = new IntersectionObserver(entries => { inViewport = entries[0].isIntersecting; wake(); });
      intersectionObserver.observe(canvas);
    }
    metrics.inspection = { rotate: !all2D, zoom: true, pause: true, seek: true, reduced_motion: Boolean(motion?.matches),
      actions: actionPlayback.length ? INSPECTION_ACTIONS.filter(name => actionPlayback.every(item => Object.hasOwn(item.actions, name))) : [], action_override: null };
    draw(performance.now());
    return owner;
  } catch (error) {
    owner.dispose();
    if (error.name !== 'AbortError' && !active.has(canvas)) {
      metrics.state = 'error';
      metrics.error = error.message;
      canvas.dataset.sceneState = 'error';
      canvas.dataset.sceneMetrics = JSON.stringify(metrics);
    }
    throw error;
  }
}
