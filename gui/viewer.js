// GLB 骨架動作預覽（three.js）
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export class Viewer {
  constructor(el) {
    this.el = el;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x2a2b30);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2.5));
    this.grid = new THREE.GridHelper(4, 16, 0x666666, 0x3a3a3a);
    this.scene.add(this.grid);
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.01, 200);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.clock = new THREE.Clock();
    this.speed = 1;
    this.paused = false;
    this.follow = true;
    this.onTick = null;
    new ResizeObserver(() => this.resize()).observe(el);
    this.resize();
    this.renderer.setAnimationLoop(() => this.tick());
  }

  resize() {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    if (this.model) this.scene.remove(this.model);
    if (this.helper) this.scene.remove(this.helper);
    this.model = this.helper = this.mixer = this.action = this.rootBone = null;
  }

  async load(url) {
    this.clear();
    const gltf = await new GLTFLoader().loadAsync(url);
    this.model = gltf.scene;
    this.scene.add(this.model);
    this.clips = gltf.animations;
    this.mixer = new THREE.AnimationMixer(this.model);
    this.helper = new THREE.SkeletonHelper(this.model);
    this.helper.visible = !!this.showBones;
    this.scene.add(this.helper);
    // 跟隨用的骨頭：骨頭最多的網格（身體，不是武器）的最上層骨頭
    let body = null;
    this.model.traverse(o => {
      if (!o.isSkinnedMesh) return;
      o.frustumCulled = false; // 包圍球是 rest pose 算的，動作跑遠會被誤剔除
      if (!body || o.skeleton.bones.length > body.skeleton.bones.length) body = o;
    });
    if (body) this.rootBone = body.skeleton.bones.find(b => !b.parent?.isBone) || body.skeleton.bones[0];
    this.frame();
    return this.clips.map(c => ({ name: c.name, duration: c.duration }));
  }

  frame() {
    // 蒙皮網格要用 precise 才會套到骨頭姿勢，不然框的是 bindpose 空間
    this.model.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(this.model, true);
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    const fit = Math.max(size.y, size.x / this.camera.aspect) / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)));
    const d = fit * 1.15 + size.z;
    this.controls.target.copy(center);
    this.camera.position.set(center.x + d * 0.3, center.y + size.y * 0.1, center.z + d);
    this.controls.update();
    const r = this.rootPos();
    this.targetOffset = r ? center.clone().sub(r) : null;
  }

  rootPos() {
    return this.rootBone ? this.rootBone.getWorldPosition(new THREE.Vector3()) : null;
  }

  play(name) {
    const clip = this.clips.find(c => c.name === name);
    if (!clip) return;
    this.mixer.stopAllAction();
    this.action = this.mixer.clipAction(clip);
    this.action.setLoop(this.loop === false ? THREE.LoopOnce : THREE.LoopRepeat);
    this.action.clampWhenFinished = true;
    this.action.reset().play();
    this.mixer.update(0);
  }

  stop() {
    if (!this.mixer) return;
    this.mixer.stopAllAction();
    this.action = null;
    this.mixer.update(0);
  }

  setLoop(on) {
    this.loop = on;
    if (this.action) this.action.setLoop(on ? THREE.LoopRepeat : THREE.LoopOnce);
  }

  setBones(on) {
    this.showBones = on;
    if (this.helper) this.helper.visible = on;
  }

  seek(t) {
    if (!this.action) return;
    this.action.time = t;
    this.mixer.update(0);
  }

  tick() {
    const dt = this.clock.getDelta();
    if (this.mixer && !this.paused) this.mixer.update(dt * this.speed);
    // 鏡頭跟著角色根骨頭移動（14～17 號這種會跑很遠的動作才看得到）
    // 目標點固定在「根骨頭 + 載入時的偏移」，使用者轉的視角保留，不會越跟越歪
    const p = this.follow && this.targetOffset ? this.rootPos() : null;
    if (p) {
      const want = p.add(this.targetOffset);
      this.camera.position.add(want.clone().sub(this.controls.target));
      this.controls.target.copy(want);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    if (this.onTick && this.action) this.onTick(this.action.time, this.action.getClip().duration);
  }
}
