import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import './style.css'

type Point = [number, number]
type Line = { id: string; coordinates: Point[] }
type Building = Line & { heightMeters: number; heightSource: string }
type Polygon = { id: string; coordinates: Point[] | Point[][] }
type HarborData = {
  metadata: { source: string; license: string; bbox: [number, number, number, number]; retrievedAt: string; attribution: string }
  buildings: Building[]
  roads: Line[]
  coastline: Line[]
  waterPolygons?: Polygon[]
}

type Port = 'busan' | 'singapore'
const port: Port = new URLSearchParams(window.location.search).get('port') === 'singapore' ? 'singapore' : 'busan'
const portDetails = {
  busan: {
    dataUrl: '/harbor/busan-north-port.json',
    title: '부산 북항, 입체로 보다',
    description: '실제 지도 데이터로 배치한 건물과 도로 위에<br>선박과 항만 장면을 더한 미니어처 지도 실험',
    camera: [.70, .86],
  },
  singapore: {
    dataUrl: '/harbor/singapore-harbor.json',
    title: '싱가포르 항만, 입체로 보다',
    description: '싱가포르 지도 데이터로 배치한 건물과 도로 위에<br>선박과 항만 장면을 더한 미니어처 지도 실험',
    camera: [-.72, .82],
  },
} satisfies Record<Port, { dataUrl: string; title: string; description: string; camera: [number, number] }>
document.title = `BlueLog · ${port === 'singapore' ? '싱가포르 항만' : '부산 북항'} 3D 실험`

const root = document.getElementById('root')
if (!root) throw new Error('3D 실험 화면의 root 요소가 없습니다.')

const container = document.createElement('main')
container.className = 'scene'
root.append(container)

function showError(message: string) {
  container.innerHTML = `<div class="error"><article><h1>3D 지도를 표시할 수 없습니다</h1><p></p></article></div>`
  const paragraph = container.querySelector('p')
  if (paragraph) paragraph.textContent = message
}

function polygonRing(coordinates: Point[] | Point[][]): Point[] {
  return Array.isArray(coordinates[0]?.[0]) ? coordinates[0] as Point[] : coordinates as Point[]
}

function color(seed: number) {
  return new THREE.Color(['#899e9c', '#c3bca4', '#7f9497', '#bdaf91', '#98a9a2', '#b4b9a4'][seed % 6])
}

function addBox(parent: THREE.Group, size: [number, number, number], at: [number, number, number], material: THREE.Material, rotation = 0) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material)
  mesh.position.set(...at)
  mesh.rotation.y = rotation
  mesh.castShadow = true
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

function addShip(parent: THREE.Group, x: number, z: number, scale: number, heading: number, cargo: boolean) {
  const ship = new THREE.Group()
  ship.position.set(x, 0.35, z)
  ship.rotation.y = heading
  ship.scale.setScalar(scale)
  const hull = new THREE.Mesh(new THREE.CylinderGeometry(4.6, 3.4, 2.4, 8), new THREE.MeshStandardMaterial({ color: cargo ? '#415f66' : '#faf6dd', roughness: 0.7 }))
  hull.rotation.y = Math.PI / 8
  hull.scale.set(1, 1, 3.5)
  hull.position.y = 1.25
  hull.castShadow = true
  ship.add(hull)
  const deckMaterial = new THREE.MeshStandardMaterial({ color: '#e2d3ad', roughness: 0.85 })
  addBox(ship, [7.4, .5, 23], [0, 2.65, 0], deckMaterial)
  addBox(ship, [4.4, 4.5, 4], [0, 4.6, -8], new THREE.MeshStandardMaterial({ color: '#f3f1dc' }))
  if (cargo) {
    const palette = ['#b47560', '#688c88', '#e0b478', '#69849b', '#d6c9a8']
    for (let row = -1; row <= 1; row++) for (let layer = 0; layer < 2; layer++) for (let col = 0; col < 4; col++) {
      addBox(ship, [2.2, 1.55, 2.9], [row * 2.25, 3.7 + layer * 1.55, -1.8 + col * 3.1], new THREE.MeshStandardMaterial({ color: palette[(col + row + layer + 6) % palette.length] }))
    }
  } else {
    const sail = new THREE.Mesh(new THREE.ConeGeometry(3.8, 10, 3), new THREE.MeshStandardMaterial({ color: '#fffbeb', side: THREE.DoubleSide }))
    sail.position.set(0, 8, 2)
    sail.rotation.y = Math.PI / 6
    sail.castShadow = true
    ship.add(sail)
  }
  parent.add(ship)
  return ship
}

function start(data: HarborData) {
  const details = portDetails[port]
  const bbox = data.metadata.bbox
  if (!Array.isArray(bbox) || bbox.length !== 4 || !data.buildings?.length) throw new Error('항만 지도 데이터가 비어 있거나 형식이 올바르지 않습니다.')
  const longitudeScale = Math.cos(((bbox[1] + bbox[3]) / 2) * Math.PI / 180)
  const longitudeCenter = (bbox[0] + bbox[2]) / 2
  const latitudeCenter = (bbox[1] + bbox[3]) / 2
  const metersPerDegree = 111_320
  const spanX = (bbox[2] - bbox[0]) * longitudeScale * metersPerDegree
  const spanZ = (bbox[3] - bbox[1]) * metersPerDegree
  const worldScale = 580 / Math.max(spanX, spanZ)
  const width = spanX * worldScale
  const depth = spanZ * worldScale
  const project = ([lon, lat]: Point) => new THREE.Vector2((lon - longitudeCenter) * longitudeScale * metersPerDegree * worldScale, -(lat - latitudeCenter) * metersPerDegree * worldScale)

  const scene = new THREE.Scene()
  scene.background = new THREE.Color('#dce8df')
  scene.fog = new THREE.Fog('#dce8df', 900, 1600)
  const camera = new THREE.OrthographicCamera(-260, 260, 160, -160, 1, 2000)
  camera.position.set(width * details.camera[0], 460, depth * details.camera[1])
  camera.lookAt(0, 0, 0)

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.7))
  renderer.setSize(container.clientWidth, container.clientHeight)
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.08
  container.append(renderer.domElement)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = .07
  controls.minZoom = .55
  controls.maxZoom = 5
  controls.maxPolarAngle = Math.PI * .43
  controls.minPolarAngle = Math.PI * .12
  controls.target.set(0, 0, 0)
  controls.update()

  scene.add(new THREE.HemisphereLight('#fff9e5', '#78969a', 1.7))
  const sun = new THREE.DirectionalLight('#fff6de', 2.8)
  sun.position.set(-280, 440, 120)
  sun.castShadow = true
  sun.shadow.mapSize.set(2048, 2048)
  sun.shadow.camera.left = -430
  sun.shadow.camera.right = 430
  sun.shadow.camera.top = 430
  sun.shadow.camera.bottom = -430
  sun.shadow.camera.near = 1
  sun.shadow.camera.far = 1100
  sun.shadow.bias = -.0002
  sun.shadow.normalBias = .025
  sun.shadow.radius = 2
  scene.add(sun)

  const water = new THREE.Mesh(new THREE.PlaneGeometry(width + 180, depth + 180), new THREE.MeshStandardMaterial({ color: '#70aebc', roughness: .67, metalness: .03 }))
  water.rotation.x = -Math.PI / 2
  water.position.y = -.9
  water.receiveShadow = true
  scene.add(water)
  const landMaterial = new THREE.MeshStandardMaterial({ color: '#ecebdd', roughness: .98, side: THREE.DoubleSide })
  const land = new THREE.Mesh(new THREE.PlaneGeometry(width + 140, depth + 140), landMaterial)
  land.rotation.x = -Math.PI / 2
  land.position.y = -.48
  land.receiveShadow = true
  scene.add(land)

  // 지도 데이터에 수면 polygon이 없으면 항만 전경 수면은 연출용이다.
  const waterRings = data.waterPolygons?.map(item => polygonRing(item.coordinates)).filter(ring => ring.length >= 3) ?? []
  if (waterRings.length) {
    const fill = new THREE.MeshBasicMaterial({ color: '#73afbd', side: THREE.DoubleSide, depthWrite: false })
    for (const ring of waterRings) {
      const shape = new THREE.Shape(ring.map(project))
      const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), fill)
      mesh.rotation.x = -Math.PI / 2
      mesh.position.y = -.38
      scene.add(mesh)
    }
  } else if (port === 'busan') {
    const shape = new THREE.Shape()
    shape.moveTo(width * .11, -depth * .55)
    shape.bezierCurveTo(-width * .04, -depth * .27, width * .16, -depth * .10, width * .02, depth * .07)
    shape.bezierCurveTo(-width * .02, depth * .22, -width * .10, depth * .37, -width * .16, depth * .55)
    shape.lineTo(width * .58, depth * .55)
    shape.lineTo(width * .58, -depth * .55)
    shape.closePath()
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: '#73afbd', side: THREE.DoubleSide, depthWrite: false }))
    mesh.rotation.x = -Math.PI / 2
    mesh.position.y = -.36
    scene.add(mesh)
  } else {
    // 실제 해안선이 닫힌 면을 만들지 못하므로 싱가포르 수로는 명시적인 연출로만 표현한다.
    const shape = new THREE.Shape()
    shape.moveTo(-width * .58, -depth * .15)
    shape.bezierCurveTo(-width * .22, -depth * .02, width * .04, -depth * .24, width * .58, -depth * .09)
    shape.lineTo(width * .58, -depth * .55)
    shape.lineTo(-width * .58, -depth * .55)
    shape.closePath()
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: '#73afbd', side: THREE.DoubleSide, depthWrite: false }))
    mesh.rotation.x = -Math.PI / 2
    mesh.position.y = -.36
    scene.add(mesh)
  }

  const roadMaterial = new THREE.LineBasicMaterial({ color: '#faf8ed', transparent: true, opacity: .86 })
  for (const road of data.roads ?? []) {
    if (road.coordinates.length < 2) continue
    const points = road.coordinates.map(project).map(p => new THREE.Vector3(p.x, .04, -p.y))
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), roadMaterial))
  }
  const coastMaterial = new THREE.LineBasicMaterial({ color: '#fffdf2', transparent: true, opacity: .9 })
  for (const line of data.coastline ?? []) {
    if (line.coordinates.length < 2) continue
    const points = line.coordinates.map(project).map(p => new THREE.Vector3(p.x, .08, -p.y))
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), coastMaterial))
  }

  const buildingPalette = Array.from({ length: 6 }, (_, index) => new THREE.MeshStandardMaterial({ color: color(index), roughness: .87, metalness: .03 }))
  const buildingGeometry = new THREE.BoxGeometry(1, 1, 1)
  type Block = { x: number; z: number; w: number; d: number; h: number }
  const buckets: Block[][] = Array.from({ length: 6 }, () => [])
  data.buildings.forEach((building, index) => {
    const ring = building.coordinates.map(project)
    if (ring.length < 3) return
    const xs = ring.map(point => point.x)
    const zs = ring.map(point => -point.y)
    const w = Math.max(1.8, Math.max(...xs) - Math.min(...xs))
    const d = Math.max(1.8, Math.max(...zs) - Math.min(...zs))
    if (w > 150 || d > 150) return
    const h = Math.max(4, Math.min(105, building.heightMeters * worldScale * 2.25))
    buckets[index % 6].push({ x: (Math.max(...xs) + Math.min(...xs)) / 2, z: (Math.max(...zs) + Math.min(...zs)) / 2, w, d, h })
  })
  const matrix = new THREE.Matrix4()
  for (let bucket = 0; bucket < buckets.length; bucket++) {
    const group = buckets[bucket]
    if (!group.length) continue
    const buildings = new THREE.InstancedMesh(buildingGeometry, buildingPalette[bucket], group.length)
    buildings.castShadow = true
    buildings.receiveShadow = true
    group.forEach((item, index) => {
      matrix.compose(new THREE.Vector3(item.x, item.h / 2, item.z), new THREE.Quaternion(), new THREE.Vector3(item.w * .94, item.h, item.d * .94))
      buildings.setMatrixAt(index, matrix)
    })
    buildings.instanceMatrix.needsUpdate = true
    scene.add(buildings)
  }

  // 입면 창은 시각화 장식이며 OSM에 기록된 창 개수·위치를 뜻하지 않는다.
  const windowTransforms: THREE.Matrix4[] = []
  const faceEast = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2)
  for (const block of buckets.flat()) {
    if (block.h < 8 || block.w > 55 || block.d > 55) continue
    const rows = Math.min(7, Math.max(2, Math.floor(block.h / 4.5)))
    const xCols = Math.min(4, Math.max(1, Math.floor(block.w / 4)))
    const zCols = Math.min(4, Math.max(1, Math.floor(block.d / 4)))
    for (let row = 0; row < rows; row++) {
      const y = (row + 1) * block.h / (rows + 1)
      for (let column = 0; column < xCols; column++) {
        const x = block.x + (column - (xCols - 1) / 2) * block.w * .7 / xCols
        windowTransforms.push(new THREE.Matrix4().compose(new THREE.Vector3(x, y, block.z + block.d * .47 + .13), new THREE.Quaternion(), new THREE.Vector3(Math.min(1.8, block.w / xCols * .45), .85, .24)))
      }
      for (let column = 0; column < zCols; column++) {
        const z = block.z + (column - (zCols - 1) / 2) * block.d * .7 / zCols
        windowTransforms.push(new THREE.Matrix4().compose(new THREE.Vector3(block.x + block.w * .47 + .13, y, z), faceEast, new THREE.Vector3(Math.min(1.8, block.d / zCols * .45), .85, .24)))
      }
    }
  }
  if (windowTransforms.length) {
    const windows = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color: '#566b69', transparent: true, opacity: .72 }), windowTransforms.length)
    windowTransforms.forEach((transform, index) => windows.setMatrixAt(index, transform))
    windows.instanceMatrix.needsUpdate = true
    scene.add(windows)
  }

  // 선박과 항만 소품은 시각화 시안이며 실측 항적·시설 위치가 아니다.
  const harborDetails = new THREE.Group()
  scene.add(harborDetails)
  const ships = port === 'busan' ? [
    addShip(harborDetails, width * .29, depth * .16, 2.5, -.48, true),
    addShip(harborDetails, width * .21, depth * .39, 1.1, .36, false),
    addShip(harborDetails, width * .39, -depth * .28, 1.0, -.7, false),
  ] : [
    addShip(harborDetails, -width * .18, depth * .35, 2.3, .92, true),
    addShip(harborDetails, width * .15, depth * .38, 1.55, -.83, true),
    addShip(harborDetails, width * .37, depth * .31, 1.0, .7, false),
  ]
  const craneMaterial = new THREE.MeshStandardMaterial({ color: '#d5bd8d', roughness: .78 })
  const cranePositions = port === 'busan' ? [[width * .07, depth * .10], [width * .13, depth * .19]] : [[-width * .3, depth * .19], [width * .03, depth * .21]]
  for (const [x, z] of cranePositions) {
    addBox(harborDetails, [2, 23, 2], [x, 11.5, z], craneMaterial)
    addBox(harborDetails, [25, 1.7, 1.7], [x + 7, 23, z], craneMaterial)
    addBox(harborDetails, [.6, 11, .6], [x + 16, 17, z], craneMaterial)
  }
  const wakeMaterial = new THREE.LineBasicMaterial({ color: '#e7f2e8', transparent: true, opacity: .75 })
  ships.forEach((ship, i) => {
    const z = ship.position.z + (i === 0 ? 29 : 17)
    for (const side of [-1, 1]) {
      const points = [new THREE.Vector3(ship.position.x, -.12, z), new THREE.Vector3(ship.position.x + side * 9, -.12, z + 10), new THREE.Vector3(ship.position.x + side * 18, -.12, z + 32)]
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), wakeMaterial))
    }
  })

  const fallbackCount = data.buildings.filter(building => building.heightSource !== 'height').length
  const attribution = document.createElement('div')
  attribution.className = 'attribution'
  const attributionLink = document.createElement('a')
  attributionLink.href = 'https://www.openstreetmap.org/copyright'
  attributionLink.target = '_blank'
  attributionLink.rel = 'noopener noreferrer'
  attributionLink.textContent = data.metadata.attribution
  attribution.append(attributionLink, ` · 건물 높이 미기록 ${fallbackCount.toLocaleString()}동은 추정치 · ${waterRings.length ? '수면 OSM · 선박 연출용' : '수면·선박 연출용'}`)
  container.append(attribution)
  const topline = document.createElement('div')
  topline.className = 'topline'
  topline.innerHTML = '<div class="brand">BlueLog <span aria-hidden="true">✦</span></div><div class="pill">3D 항만 지도 실험</div>'
  container.append(topline)
  const location = document.createElement('section')
  location.className = 'location'
  location.innerHTML = `<div class="eyebrow">City in miniature · Harbor study</div><h1>${details.title}</h1><p>${details.description}</p><div class="stats"><span><strong>${data.buildings.length.toLocaleString()}</strong> 건물</span><span><strong>${data.roads.length.toLocaleString()}</strong> 도로</span><span>드래그 회전 · 오른쪽 드래그 이동</span></div>`
  container.append(location)
  const zoom = document.createElement('div')
  zoom.className = 'controls'
  zoom.innerHTML = '<button type="button" aria-label="지도 확대">+</button><button type="button" aria-label="지도 축소">−</button>'
  zoom.children[0].addEventListener('click', () => { camera.zoom = Math.min(controls.maxZoom, camera.zoom * 1.25); camera.updateProjectionMatrix() })
  zoom.children[1].addEventListener('click', () => { camera.zoom = Math.max(controls.minZoom, camera.zoom / 1.25); camera.updateProjectionMatrix() })
  container.append(zoom)
  const hint = document.createElement('div')
  hint.className = 'hint'
  hint.textContent = '드래그 회전 · 휠 확대 · 오른쪽 드래그 이동'
  container.append(hint)

  function resize() {
    const aspect = container.clientWidth / Math.max(1, container.clientHeight)
    const vertical = Math.max(depth, width / aspect) * .47
    camera.left = -vertical * aspect
    camera.right = vertical * aspect
    camera.top = vertical
    camera.bottom = -vertical
    camera.updateProjectionMatrix()
    renderer.setSize(container.clientWidth, container.clientHeight)
  }
  const resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(container)
  resize()

  let running = true
  let frameId = 0
  function animate() {
    if (!running) return
    controls.update()
    renderer.render(scene, camera)
    frameId = requestAnimationFrame(animate)
  }
  animate()
  function cleanup() {
    running = false
    cancelAnimationFrame(frameId)
    resizeObserver.disconnect()
    controls.dispose()
    scene.traverse(object => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
        object.geometry.dispose()
        const materials = Array.isArray(object.material) ? object.material : [object.material]
        materials.forEach(material => material.dispose())
      }
    })
    renderer.dispose()
  }
  window.addEventListener('pagehide', cleanup, { once: true })
}

fetch(portDetails[port].dataUrl)
  .then(response => {
    if (!response.ok) throw new Error(`지도 데이터 요청 실패 (${response.status})`)
    return response.json() as Promise<HarborData>
  })
  .then(data => start(data))
  .catch(error => showError(error instanceof Error ? error.message : '알 수 없는 오류'))
