import * as THREE from 'three'
import { MercatorCoordinate, type CustomLayerInterface, type Map as MapLibreMap } from 'maplibre-gl'
import type { GlobeVesselLayerModel } from './vesselModel'
import { normalizedHeading } from './vesselModel'

export interface GlobeVesselLayerController {
  readonly layer: CustomLayerInterface
  update(model: GlobeVesselLayerModel): void
}

/** MapLibre의 WebGL context를 공유하는 절차형 저폴리 선박 layer다. */
export function createGlobeVesselLayer(initialModel: GlobeVesselLayerModel): GlobeVesselLayerController {
  let model = initialModel
  let map: MapLibreMap | null = null
  let renderer: THREE.WebGLRenderer | null = null
  let scene: THREE.Scene | null = null
  let camera: THREE.Camera | null = null
  let geometry: THREE.BufferGeometry | null = null
  let material: THREE.MeshStandardMaterial | null = null
  let wakeGeometry: THREE.BufferGeometry | null = null
  let wakeMaterial: THREE.MeshBasicMaterial | null = null
  const meshes = new Map<string, THREE.Mesh>()
  const wakes = new Map<string, THREE.Mesh>()

  const sync = () => {
    if (!scene || !geometry || !material) return
    const active = new Set(model.vessels.map(({ id }) => id))
    for (const [id, mesh] of meshes) if (!active.has(id)) { scene.remove(mesh); meshes.delete(id) }
    for (const [id, wake] of wakes) if (!active.has(id)) { scene.remove(wake); wakes.delete(id) }
    for (const vessel of model.vessels) {
      let mesh = meshes.get(vessel.id)
      if (!mesh) {
        mesh = new THREE.Mesh(geometry, material)
        meshes.set(vessel.id, mesh)
        scene.add(mesh)
      }
      const mercator = MercatorCoordinate.fromLngLat([...vessel.coordinate], 3)
      const scale = mercator.meterInMercatorCoordinateUnits() * 42
      mesh.position.set(mercator.x, mercator.y, mercator.z)
      mesh.scale.set(scale * 0.35, scale, scale * 0.22)
      const heading = normalizedHeading(vessel.heading)
      mesh.rotation.set(Math.PI / 2, 0, heading === null ? 0 : -THREE.MathUtils.degToRad(heading))
      let wake = wakes.get(vessel.id)
      if (vessel.wake?.active && wakeGeometry && wakeMaterial) {
        if (!wake) {
          wake = new THREE.Mesh(wakeGeometry, wakeMaterial)
          wakes.set(vessel.id, wake)
          scene.add(wake)
        }
        wake.visible = true
        wake.position.set(mercator.x, mercator.y, mercator.z - scale * 0.05)
        wake.scale.set(scale * 0.55, scale * Math.min(2.2, 1 + vessel.wake.speedKnots / 20), scale * 0.05)
        wake.rotation.set(Math.PI / 2, 0, heading === null ? 0 : -THREE.MathUtils.degToRad(heading))
      } else if (wake) wake.visible = false
    }
    map?.triggerRepaint()
  }

  const layer: CustomLayerInterface = {
    id: `bluelog-vessels-${initialModel.mode}`,
    type: 'custom', renderingMode: '3d',
    onAdd(nextMap, gl) {
      map = nextMap
      camera = new THREE.Camera()
      scene = new THREE.Scene()
      scene.add(new THREE.HemisphereLight(0xffffff, 0x365568, 2.4))
      // +Y가 선수 방향인 diamond hull. 외부 asset·texture가 없어 재배포 출처가 코드 자체로 닫힌다.
      geometry = new THREE.ConeGeometry(1, 3, 4, 1, false)
      material = new THREE.MeshStandardMaterial({ color: 0x174d6b, roughness: 0.7, metalness: 0.1 })
      wakeGeometry = new THREE.ConeGeometry(1, 2, 3, 1, true)
      wakeMaterial = new THREE.MeshBasicMaterial({ color: 0xb9e4ee, transparent: true, opacity: 0.35, depthWrite: false })
      renderer = new THREE.WebGLRenderer({ canvas: gl.canvas, context: gl, antialias: false })
      renderer.autoClear = false
      sync()
    },
    render(_gl, options) {
      if (!renderer || !scene || !camera) return
      camera.projectionMatrix.fromArray(options.modelViewProjectionMatrix)
      renderer.resetState()
      renderer.render(scene, camera)
      map?.triggerRepaint()
    },
    onRemove() {
      for (const mesh of meshes.values()) scene?.remove(mesh)
      for (const wake of wakes.values()) scene?.remove(wake)
      meshes.clear()
      wakes.clear()
      geometry?.dispose()
      material?.dispose()
      wakeGeometry?.dispose()
      wakeMaterial?.dispose()
      renderer?.dispose()
      geometry = null
      material = null
      wakeGeometry = null
      wakeMaterial = null
      renderer = null
      scene = null
      camera = null
      map = null
    },
  }
  return { layer, update(next) { model = next; sync() } }
}
