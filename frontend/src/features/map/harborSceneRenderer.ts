import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { HarborRendererModel } from './harborRenderer'
import type { MapRenderer } from './renderer'
import { mapQualityPolicy } from './quality'

type Point = readonly [number, number]
interface HarborData {
  readonly metadata: { readonly attribution: string; readonly bbox: readonly [number, number, number, number] }
  readonly buildings: readonly { readonly coordinates: readonly Point[]; readonly heightMeters: number }[]
  readonly roads: readonly { readonly coordinates: readonly Point[] }[]
}

const PORTS = {
  busan: { url: '/harbor/busan-north-port.json', label: '부산 북항' },
  singapore: { url: '/harbor/singapore-harbor.json', label: '싱가포르 항만' },
} as const

function disposeMaterial(material: THREE.Material) {
  for (const value of Object.values(material)) {
    if (value instanceof THREE.Texture) value.dispose()
  }
  material.dispose()
}

/** Three.js product scene 한 세대의 모든 브라우저/WebGL 자원을 소유한다. */
function mountScene(target: HTMLElement, model: HarborRendererModel, emit: Parameters<MapRenderer<HarborRendererModel>['mount']>[2]) {
  const abort = new AbortController()
  let disposed = false
  let frame: number | null = null
  let observer: ResizeObserver | null = null
  let controls: OrbitControls | null = null
  let renderer: THREE.WebGLRenderer | null = null
  let scene: THREE.Scene | null = null
  const motionQuery = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')
  let reducedMotion = motionQuery?.matches ?? false
  const quality = mapQualityPolicy()

  target.replaceChildren()
  target.tabIndex = 0
  target.setAttribute('role', 'img')
  target.setAttribute('aria-label', `${PORTS[model.port].label} 3D 항만 장면. 방향키로 시점을 조정합니다.`)
  const notice = document.createElement('p')
  notice.textContent = '© OpenStreetMap contributors · 연출용 장면이며 실제 접안 위치, 수심 또는 항해 가능성을 보증하지 않습니다.'
  notice.setAttribute('data-harbor-attribution', '')
  target.append(notice)

  const render = () => {
    if (disposed || !renderer || !scene || !controls) return
    controls.update()
    renderer.render(scene, controls.object)
  }
  const animate = () => {
    frame = null
    render()
    if (!disposed && !reducedMotion) frame = requestAnimationFrame(animate)
  }
  const motionChange = () => {
    reducedMotion = motionQuery?.matches ?? false
    if (reducedMotion && frame !== null) {
      cancelAnimationFrame(frame)
      frame = null
    }
    if (controls) controls.enableDamping = !reducedMotion
    if (!reducedMotion && renderer && frame === null) frame = requestAnimationFrame(animate)
    render()
  }
  motionQuery?.addEventListener?.('change', motionChange)
  const keydown = (event: KeyboardEvent) => {
    if (!controls || !renderer || !scene || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
    event.preventDefault()
    const camera = controls.object
    const angle = event.key === 'ArrowLeft' ? .08 : event.key === 'ArrowRight' ? -.08 : 0
    if (angle !== 0) {
      const x = camera.position.x
      const z = camera.position.z
      camera.position.x = x * Math.cos(angle) - z * Math.sin(angle)
      camera.position.z = x * Math.sin(angle) + z * Math.cos(angle)
    } else camera.position.y += event.key === 'ArrowUp' ? 12 : -12
    render()
  }
  target.addEventListener('keydown', keydown)

  void fetch(PORTS[model.port].url, { signal: abort.signal }).then(async (response) => {
    if (!response.ok) throw new Error(`항만 데이터 조회 실패 (HTTP ${response.status})`)
    return response.json() as Promise<HarborData>
  }).then((data) => {
    if (disposed) return
    if (!data.buildings.length || data.metadata.bbox.length !== 4) throw new Error('항만 지도 데이터가 비어 있습니다.')
    const [west, south, east, north] = data.metadata.bbox
    const centerLongitude = (west + east) / 2
    const centerLatitude = (south + north) / 2
    const scale = 4_000
    const project = ([longitude, latitude]: Point) => new THREE.Vector3((longitude - centerLongitude) * scale, 0, -(latitude - centerLatitude) * scale)
    scene = new THREE.Scene()
    scene.background = new THREE.Color('#dce8df')
    const camera = new THREE.PerspectiveCamera(45, 1, .1, 2_000)
    camera.position.set(180, 220, 260)
    camera.lookAt(0, 0, 0)
    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(devicePixelRatio, quality.pixelRatioCap))
    target.insertBefore(renderer.domElement, notice)
    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = !reducedMotion
    controls.addEventListener('change', render)
    scene.add(new THREE.HemisphereLight('#ffffff', '#78969a', 2))
    const water = new THREE.Mesh(new THREE.PlaneGeometry(500, 500), new THREE.MeshStandardMaterial({ color: '#70aebc' }))
    water.rotation.x = -Math.PI / 2
    scene.add(water)
    const roadMaterial = new THREE.LineBasicMaterial({ color: '#faf8ed' })
    for (const road of data.roads) {
      if (road.coordinates.length >= 2) scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(road.coordinates.map(project)), roadMaterial))
    }
    for (let buildingIndex = 0; buildingIndex < data.buildings.length; buildingIndex += quality.buildingStride) {
      const building = data.buildings[buildingIndex]
      if (building.coordinates.length < 3) continue
      const points = building.coordinates.map(project)
      const xs = points.map(({ x }) => x)
      const zs = points.map(({ z }) => z)
      const width = Math.max(1, Math.max(...xs) - Math.min(...xs))
      const depth = Math.max(1, Math.max(...zs) - Math.min(...zs))
      const height = Math.max(2, Math.min(80, building.heightMeters / 2))
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), new THREE.MeshStandardMaterial({ color: '#899e9c' }))
      mesh.position.set((Math.max(...xs) + Math.min(...xs)) / 2, height / 2, (Math.max(...zs) + Math.min(...zs)) / 2)
      scene.add(mesh)
    }
    const ship = new THREE.Group()
    const hull = new THREE.Mesh(new THREE.BoxGeometry(12, 4, 38), new THREE.MeshStandardMaterial({ color: '#415f66' }))
    hull.position.y = 2
    ship.add(hull)
    scene.add(ship)
    const resize = () => {
      if (!renderer) return
      const width = Math.max(1, target.clientWidth)
      const height = Math.max(1, target.clientHeight)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
      render()
    }
    observer = new ResizeObserver(resize)
    observer.observe(target)
    resize()
    if (!reducedMotion && quality.animate) frame = requestAnimationFrame(animate)
    emit({ type: 'ready' })
  }).catch((error: unknown) => {
    if (!disposed && !abort.signal.aborted) emit({ type: 'error', error: error instanceof Error ? error : new Error(String(error)) })
  })

  return () => {
    if (disposed) return
    disposed = true
    abort.abort()
    if (frame !== null) cancelAnimationFrame(frame)
    observer?.disconnect()
    target.removeEventListener('keydown', keydown)
    motionQuery?.removeEventListener?.('change', motionChange)
    controls?.dispose()
    scene?.traverse((object) => {
      const mesh = object as THREE.Mesh
      mesh.geometry?.dispose()
      if (Array.isArray(mesh.material)) mesh.material.forEach(disposeMaterial)
      else if (mesh.material) disposeMaterial(mesh.material)
    })
    renderer?.dispose()
    renderer?.forceContextLoss()
    target.replaceChildren()
    target.removeAttribute('role')
    target.removeAttribute('aria-label')
    target.removeAttribute('tabindex')
  }
}

export const harborRenderer: MapRenderer<HarborRendererModel> = {
  mount(target, initialModel, emit) {
    let model = initialModel
    let cleanup = mountScene(target, model, emit)
    return {
      update(next) {
        if (next.port === model.port) return
        cleanup()
        model = next
        cleanup = mountScene(target, model, emit)
      },
      destroy() { cleanup() },
    }
  },
}
