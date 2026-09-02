"""
viewer.py
Generates a self-contained HTML/Three.js CAD viewer for a GLB file.
The GLB bytes are embedded as a base64 data URI so it works inside a
Streamlit components.html iframe with no extra file server needed.
Loads the ACTUAL generated model - no placeholder/cube geometry.
"""
from __future__ import annotations
import base64


def build_viewer_html(glb_path: str, height: int = 520) -> str:
    with open(glb_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  html, body {{ margin:0; padding:0; background:#eef1f5; overflow:hidden; }}
  #viewer-root {{ position:relative; width:100%; height:{height}px; }}
  #canvas-holder {{ width:100%; height:100%; }}
  .toolbar {{
    position:absolute; bottom:8px; left:8px; right:8px;
    display:flex; gap:6px; flex-wrap:wrap;
    background:rgba(255,255,255,0.92); border:1px solid #d7dce2; border-radius:6px;
    padding:6px; z-index:10;
  }}
  .toolbar button {{
    background:#f5f7fa; color:#33404f; border:1px solid #d7dce2; border-radius:4px;
    padding:5px 10px; font-size:11px; cursor:pointer; font-family:sans-serif;
  }}
  .toolbar button:hover {{ background:#e3ecf7; color:#1976d2; }}
  .toolbar button.active {{ background:#1976d2; color:white; border-color:#1976d2; }}
  #status {{
    position:absolute; top:8px; left:8px; color:#4a5568; font-family:sans-serif;
    font-size:11px; background:rgba(255,255,255,0.9); padding:3px 8px; border-radius:4px;
    border:1px solid #d7dce2;
  }}
  #modelinfo {{
    position:absolute; top:8px; right:8px; color:#33404f; font-family:sans-serif;
    font-size:10.5px; background:rgba(255,255,255,0.92); padding:6px 9px; border-radius:4px;
    border:1px solid #d7dce2; line-height:1.5; text-align:right;
  }}
</style>
</head>
<body>
<div id="viewer-root">
  <div id="status">Loading model...</div>
  <div id="modelinfo"></div>
  <div id="canvas-holder"></div>
  <div class="toolbar">
    <button onclick="setView('iso')">Isometric</button>
    <button onclick="setView('front')">Front</button>
    <button onclick="setView('back')">Back</button>
    <button onclick="setView('top')">Top</button>
    <button onclick="setView('bottom')">Bottom</button>
    <button onclick="setView('left')">Left</button>
    <button onclick="setView('right')">Right</button>
    <button onclick="fitToScreen()">Fit</button>
    <button id="btn-shaded" onclick="setShading('shaded')">Shaded</button>
    <button id="btn-wire" onclick="setShading('wireframe')">Wireframe</button>
    <button id="btn-edges" onclick="toggleEdges()">Edges</button>
    <button id="btn-grid" onclick="toggleGrid()">Grid</button>
    <button id="btn-axes" onclick="toggleAxes()">Axes</button>
    <button id="btn-proj" onclick="toggleProjection()">Orthographic</button>
    <button onclick="toggleFullscreen()">Fullscreen</button>
  </div>
</div>

<script type="importmap">
{{
  "imports": {{
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }}
}}
</script>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';

const holder = document.getElementById('canvas-holder');
const statusEl = document.getElementById('status');

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xeef1f5); // light, neutral CAD-style background

const aspect = holder.clientWidth / holder.clientHeight;
const perspCamera = new THREE.PerspectiveCamera(45, aspect, 0.01, 100000);
perspCamera.position.set(80, 80, 80);
let orthoFrustum = 80;
const orthoCamera = new THREE.OrthographicCamera(
  -orthoFrustum * aspect, orthoFrustum * aspect, orthoFrustum, -orthoFrustum, 0.01, 100000
);
orthoCamera.position.set(80, 80, 80);
let camera = perspCamera;
let isOrtho = false;

const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setSize(holder.clientWidth, holder.clientHeight);
renderer.setPixelRatio(window.devicePixelRatio);
holder.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

const hemi = new THREE.HemisphereLight(0xffffff, 0xbfc6cf, 1.15);
scene.add(hemi);
const dir1 = new THREE.DirectionalLight(0xffffff, 0.85);
dir1.position.set(100, 150, 100);
scene.add(dir1);
const dir2 = new THREE.DirectionalLight(0xffffff, 0.45);
dir2.position.set(-100, -50, -100);
scene.add(dir2);

let grid = new THREE.GridHelper(200, 20, 0xb0b8c2, 0xd6dbe2);
grid.visible = true;
scene.add(grid);

let axes = new THREE.AxesHelper(120);
axes.visible = true;
scene.add(axes);

let modelRoot = new THREE.Group();
scene.add(modelRoot);
let edgesGroup = new THREE.Group();
scene.add(edgesGroup);
let currentShading = 'shaded';
let edgesOn = true;
let gridOn = true;
let modelSize = 100;
let modelCenter = new THREE.Vector3(0,0,0);

const b64 = "{b64}";
function b64ToArrayBuffer(base64) {{
  const binary = atob(base64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}}

const loader = new GLTFLoader();
loader.parse(b64ToArrayBuffer(b64), '', (gltf) => {{
  modelRoot.add(gltf.scene);

  gltf.scene.traverse((child) => {{
    if (child.isMesh) {{
      child.material = new THREE.MeshStandardMaterial({{
        color: 0x4fa3d1, metalness: 0.25, roughness: 0.55, side: THREE.DoubleSide
      }});
      const edgeGeo = new THREE.EdgesGeometry(child.geometry, 20);
      const edgeMat = new THREE.LineBasicMaterial({{ color: 0x0d1b24 }});
      const edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
      edgeLines.matrix.copy(child.matrix);
      edgesGroup.add(edgeLines);
    }}
  }});

  const box = new THREE.Box3().setFromObject(modelRoot);
  const size = new THREE.Vector3(); box.getSize(size);
  const center = new THREE.Vector3(); box.getCenter(center);
  modelCenter = center;
  modelSize = Math.max(size.x, size.y, size.z) || 1;

  fitToScreen();
  statusEl.style.display = 'none';
}}, (err) => {{
  statusEl.innerText = 'Failed to load model geometry.';
  console.error(err);
}});

function updateModelInfo() {{
  document.getElementById('modelinfo').innerHTML =
    `Projection: ${{isOrtho ? 'Orthographic' : 'Perspective'}}<br/>` +
    `Shading: ${{currentShading}}`;
}}

window.setView = function(view) {{
  const d = modelSize * 1.8;
  const c = modelCenter;
  if (view === 'iso') camera.position.set(c.x + d*0.6, c.y + d*0.6, c.z + d*0.6);
  if (view === 'front') camera.position.set(c.x, c.y, c.z + d);
  if (view === 'back') camera.position.set(c.x, c.y, c.z - d);
  if (view === 'top') camera.position.set(c.x, c.y + d, c.z + 0.001);
  if (view === 'bottom') camera.position.set(c.x, c.y - d, c.z + 0.001);
  if (view === 'left') camera.position.set(c.x - d, c.y, c.z);
  if (view === 'right') camera.position.set(c.x + d, c.y, c.z);
  controls.target.copy(c);
  camera.lookAt(c);
  controls.update();
}}

window.fitToScreen = function() {{
  setView('iso');
}}

window.toggleAxes = function() {{
  axes.visible = !axes.visible;
  document.getElementById('btn-axes').classList.toggle('active', axes.visible);
}}

window.toggleProjection = function() {{
  isOrtho = !isOrtho;
  const target = controls.target.clone();
  const pos = camera.position.clone();
  if (isOrtho) {{
    const aspectNow = holder.clientWidth / holder.clientHeight;
    orthoFrustum = modelSize * 1.1 || 80;
    orthoCamera.left = -orthoFrustum * aspectNow;
    orthoCamera.right = orthoFrustum * aspectNow;
    orthoCamera.top = orthoFrustum;
    orthoCamera.bottom = -orthoFrustum;
    orthoCamera.position.copy(pos);
    orthoCamera.updateProjectionMatrix();
    camera = orthoCamera;
  }} else {{
    perspCamera.position.copy(pos);
    camera = perspCamera;
  }}
  controls.object = camera;
  controls.target.copy(target);
  camera.lookAt(target);
  controls.update();
  document.getElementById('btn-proj').innerText = isOrtho ? 'Perspective' : 'Orthographic';
  document.getElementById('btn-proj').classList.toggle('active', isOrtho);
  updateModelInfo();
}}

window.setShading = function(mode) {{
  currentShading = mode;
  document.getElementById('btn-shaded').classList.toggle('active', mode === 'shaded');
  document.getElementById('btn-wire').classList.toggle('active', mode === 'wireframe');
  modelRoot.traverse((child) => {{
    if (child.isMesh) child.material.wireframe = (mode === 'wireframe');
  }});
  updateModelInfo();
}}

window.toggleEdges = function() {{
  edgesOn = !edgesOn;
  edgesGroup.visible = edgesOn;
  document.getElementById('btn-edges').classList.toggle('active', edgesOn);
}}

window.toggleGrid = function() {{
  gridOn = !gridOn;
  grid.visible = gridOn;
  document.getElementById('btn-grid').classList.toggle('active', gridOn);
}}

window.toggleFullscreen = function() {{
  const el = document.getElementById('viewer-root');
  if (!document.fullscreenElement) {{ el.requestFullscreen(); }}
  else {{ document.exitFullscreen(); }}
}}

document.getElementById('btn-shaded').classList.add('active');
document.getElementById('btn-edges').classList.add('active');
document.getElementById('btn-grid').classList.add('active');
document.getElementById('btn-axes').classList.add('active');
updateModelInfo();

function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}}
animate();

window.addEventListener('resize', () => {{
  const a = holder.clientWidth / holder.clientHeight;
  perspCamera.aspect = a;
  perspCamera.updateProjectionMatrix();
  orthoCamera.left = -orthoFrustum * a;
  orthoCamera.right = orthoFrustum * a;
  orthoCamera.updateProjectionMatrix();
  renderer.setSize(holder.clientWidth, holder.clientHeight);
}});
</script>
</body>
</html>
"""
