import * as THREE from 'three'
import type { Map as MapLibreMap } from 'maplibre-gl'
import type { GlobeVesselLayerModel } from './vesselModel'
import { normalizedHeading } from './vesselModel'
import { isBeyondGlobeHorizon, ratingColorToken, VESSEL_SCREEN_LENGTH_PX } from './vesselGeometry'
import { CARGO_COLOR_TOKENS, vesselParts, type VesselPart } from './vesselParts'

export interface GlobeVesselLayerController {
  update(model: GlobeVesselLayerModel): void
  /** 캔버스를 걷고 GPU 자원을 버린다. 지도를 버리기 전에 부른다. */
  destroy(): void
}

/**
 * MapLibre의 WebGL context를 공유하는 절차형 저폴리 선박 layer다.
 *
 * ## 배를 **화면 좌표**에 놓는다 (`#1917`)
 *
 * 종전에는 `MercatorCoordinate`로 세계 좌표에 놓고 `modelViewProjectionMatrix`로 그렸다.
 * 그 행렬은 **mercator 전용**이다 — MapLibre v6의 globe에서는 커스텀 레이어가 셰이더
 * prelude(`shaderData.vertexShaderPrelude`의 `projectTile`)로 직접 투영해야 하고, three의
 * 재질은 그 경로를 타지 못한다. **globe를 켠 이 제품에서 배가 화면 밖에 그려졌다.**
 *
 * 크기까지 겹쳤다 — 실측 42 m 고정이라 줌 2(1픽셀 ≈ 16 km)에서는 애초에 한 픽셀도 되지
 * 않았다. **layer는 정상으로 돌았고 콘솔도 조용했다.** 사람이 본 것은 위에 얹힌 평면
 * SVG 마커뿐이었고, 그래서 「3D가 안 나온다」로 보였다.
 *
 * ## MapLibre의 GL 컨텍스트를 **공유하지 않는다**
 *
 * 화면 좌표로 옮겨도 여전히 보이지 않았다 — globe에서도, mercator로 되돌려도 같았다.
 * 실측: layer는 붙고(`meshes 5`) `render()`는 매 프레임 돌며 `map.project()`가 캔버스 안
 * 좌표(803, 223)를 주는데 **화면에는 아무것도 없다.** MapLibre v6의 렌더 경로에서 three가
 * 자기 상태·프레임버퍼를 되돌리는 지점이 어긋난다.
 *
 * 그래서 **지도 위에 our 캔버스를 한 장 얹는다.** 항만 장면(`harborSceneRenderer`)이 이미
 * 자기 캔버스에 그려 동작하고 있었다 — 같은 방식이다. `map.project()`가 투영을 가리지
 * 않으므로 globe·mercator 어느 쪽이든 자리가 맞고, 크기는 줌과 무관하게 일정하다
 * (마커와 같은 규칙 · `vesselGeometry.ts`). 지도의 방위·기울기는 **형상에 직접** 건다 —
 * 배가 지도와 함께 도는 것처럼 읽힌다.
 *
 * ⚠️ 캔버스는 **포인터를 받지 않는다**(`pointer-events: none`) — 지도의 끌기·확대가
 * 그대로 살아 있어야 한다. 마커(등급 배지)는 이 위에 그대로 뜬다.
 *
 * ⚠️ 그래서 이 배들은 **지형에 가려지지 않는다.** 가릴 지형이 아직 없고(타일은 벡터 2D),
 * 항만 장면은 별도 three 장면(`harborSceneRenderer`)이 그린다.
 */
export function createGlobeVesselLayer(
  targetMap: MapLibreMap,
  initialModel: GlobeVesselLayerModel,
): GlobeVesselLayerController {
  let model = initialModel
  let map: MapLibreMap | null = targetMap
  let renderer: THREE.WebGLRenderer | null = null
  let scene: THREE.Scene | null = null
  let camera: THREE.OrthographicCamera | null = null
  /** 부품 도형은 배마다 다시 만들지 않는다 — 모양이 같으므로 나눠 쓴다. */
  const shapes = new Map<string, THREE.BufferGeometry>()
  const partMaterials = new Map<string, THREE.MeshStandardMaterial>()
  let wakeGeometry: THREE.BufferGeometry | null = null
  let wakeMaterial: THREE.MeshBasicMaterial | null = null
  const meshes = new Map<string, THREE.Group>()
  const wakes = new Map<string, THREE.Mesh>()

  /** 등급별 재질. 같은 등급끼리 재질 하나를 나눠 쓴다 — 배마다 만들면 GPU 상태가 는다. */
  const materials = new Map<string, THREE.MeshStandardMaterial>()

  const cssColor = (token: string | null): string | null => {
    if (token === null || typeof globalThis.getComputedStyle !== 'function') return null
    const value = globalThis.getComputedStyle(document.documentElement).getPropertyValue(token).trim()
    return value === '' ? null : value
  }

  /** 배 하나 안에서 부품끼리 가려야 하므로 깊이는 **켠다**. 지도와는 캔버스가 다르다. */
  const makeMaterial = (fallback: number, token: string | null): THREE.MeshStandardMaterial => {
    const made = new THREE.MeshStandardMaterial({ color: fallback, roughness: 0.6, metalness: 0.05 })
    // 토큰을 읽지 못하는 환경(테스트·서버)에서는 기본색으로 떨어진다 — 색을 지어내지 않는다.
    const css = cssColor(token)
    if (css !== null && typeof made.color?.setStyle === 'function') made.color.setStyle(css)
    return made
  }

  /**
   * 선체와 갑판이 **등급 색**을 받는다. 그 색이 지도에서 등급을 말하는 채널이다.
   *
   * 갑판까지 칠하는 이유는 **위에서 내려다보기 때문**이다 — 지도에서 가장 크게 보이는
   * 면이 갑판이라, 중립색으로 두면 등급 색이 배 둘레 몇 픽셀로 줄어든다(`#1935` 실측).
   * 화물·선교는 중립으로 남겨 그 위에서 대비를 만든다.
   */
  const hullMaterial = (rating: string | null | undefined): THREE.MeshStandardMaterial => {
    const token = ratingColorToken(rating ?? null)
    const key = `hull:${token ?? 'none'}`
    const found = materials.get(key)
    if (found) return found
    const made = makeMaterial(0x2f5d78, token)
    materials.set(key, made)
    return made
  }

  /** 나머지 부품 — 자리마다 정해진 중립색이다. 새 색을 만들지 않는다. */
  const partMaterial = (part: VesselPart): THREE.MeshStandardMaterial => {
    const token = part.role === 'cargo'
      ? CARGO_COLOR_TOKENS[(part.tint ?? 0) % CARGO_COLOR_TOKENS.length]
      : part.role === 'deck' ? '--surface-inset' : '--surface-card'
    const found = partMaterials.get(token)
    if (found) return found
    const made = makeMaterial(part.role === 'deck' ? 0xdad3bd : 0xf1efe4, token)
    partMaterials.set(token, made)
    return made
  }

  /** 부품 도형. 8각 기둥은 눕혀서 선체가 된다(실험과 같은 방식). */
  const shapeFor = (part: VesselPart): THREE.BufferGeometry => {
    const [x, y, z] = part.size
    const key = `${part.shape}:${x}:${y}:${z}`
    const found = shapes.get(key)
    if (found) return found
    const made = part.shape === 'box'
      ? new THREE.BoxGeometry(x, y, z)
      : new THREE.CylinderGeometry(x / 2, (x / 2) * 0.72, z, 8, 1)
    // 기둥은 Y축을 따라 서 있으므로 눕혀 뱃머리를 앞으로 돌린다.
    if (part.shape === 'prism') {
      made.rotateX?.(Math.PI / 2)
      made.scale?.(1, y / x, 1)
    }
    shapes.set(key, made)
    return made
  }

  /**
   * 부품을 모아 배 하나를 세운다 — 실험이 `THREE.Group`으로 하던 그대로다.
   *
   * 껍데기가 둘인 이유는 **좌표계가 둘**이기 때문이다.
   *
   * - 부품(`vesselParts.ts`)은 위가 `+Y`, 앞이 `+Z`다
   * - 화면은 정사영이라 카메라가 `-Z`를 내려다본다 — 갑판이 `+Z`를 향해야 보이고,
   *   뱃머리는 화면 위(`-Y`)를 향해야 한다
   *
   * 안쪽 껍데기는 **눕히기만** 한다(`X`축 90°) — 갑판이 화면을 보고 뱃머리가 위를 향한다.
   * 바깥 껍데기는 **방위와 기울기**만 받는다.
   *
   * ⚠️ 여기에 180°를 함께 적으면 안 된다. three의 기본 회전 순서가 `XYZ`(즉 `Z`를
   * **먼저** 적용)라 갑판이 반대쪽을 본다 — `#1935`에서 실제로 그랬다.
   */
  const buildVessel = (rating: string | null | undefined): THREE.Group => {
    const group = new THREE.Group()
    const oriented = new THREE.Group()
    oriented.rotation.set?.(Math.PI / 2, 0, 0)
    for (const part of vesselParts(model.mode)) {
      const mesh = new THREE.Mesh(
        shapeFor(part),
        part.role === 'hull' || part.role === 'deck' ? hullMaterial(rating) : partMaterial(part),
      )
      mesh.position.set?.(part.at[0], part.at[1], part.at[2])
      oriented.add(mesh)
    }
    group.add(oriented)
    return group
  }

  /** 장면에 있어야 할 mesh를 맞춘다. 자리·크기는 매 프레임 `place()`가 다시 잡는다. */
  const sync = () => {
    if (!scene) return
    const active = new Set(model.vessels.map(({ id }) => id))
    for (const [id, mesh] of meshes) if (!active.has(id)) { scene.remove(mesh); meshes.delete(id) }
    for (const [id, wake] of wakes) if (!active.has(id)) { scene.remove(wake); wakes.delete(id) }
    for (const vessel of model.vessels) {
      let mesh = meshes.get(vessel.id)
      if (!mesh) {
        mesh = buildVessel(vessel.rating)
        meshes.set(vessel.id, mesh)
        scene.add(mesh)
      }
      if (vessel.wake?.active && wakeGeometry && wakeMaterial && !wakes.has(vessel.id)) {
        const wake = new THREE.Mesh(wakeGeometry, wakeMaterial)
        wakes.set(vessel.id, wake)
        scene.add(wake)
      }
    }
  }

  /**
   * 매 프레임 자리를 잡는다.
   *
   * 지도는 관성 이동·회전으로 프레임마다 움직인다 — 모델이 바뀔 때만 잡으면 배가 지도에서
   * 떨어져 미끄러진다.
   */
  const place = () => {
    if (!map || !camera) return
    const canvas = map.getCanvas?.()
    if (!canvas) return
    const ratio = canvas.width / Math.max(1, canvas.clientWidth || canvas.width)
    camera.left = 0
    camera.right = canvas.width
    camera.top = 0
    camera.bottom = canvas.height
    camera.updateProjectionMatrix?.()

    const bearing = map.getBearing?.() ?? 0
    const pitch = map.getPitch?.() ?? 0
    const center = map.getCenter?.()

    /*
     * 지구 **반대편**에 있는 배는 그리지 않는다 (`#1937`).
     *
     * `map.project()`는 구 뒷면의 점도 화면 좌표를 돌려준다 — 그대로 그리면 지구 반대편
     * 배가 앞면 배와 섞여 「어느 배가 이쪽에 있는가」를 읽을 수 없다.
     *
     * MapLibre의 판정을 먼저 쓴다(지형까지 본다). 그것이 없는 환경에서는 중심에서의
     * 각거리로 앞뒤만 가른다(`isBeyondGlobeHorizon`).
     */
    const transform = (map as unknown as {
      transform?: { isLocationOccluded?: (lngLat: { lng: number; lat: number }) => boolean }
    }).transform
    const hidden = (coordinate: readonly [number, number]): boolean => {
      const [lng, lat] = coordinate
      try {
        const occluded = transform?.isLocationOccluded?.({ lng, lat })
        if (typeof occluded === 'boolean') return occluded
      } catch {
        // 내부 구현이 바뀌어 던지면 아래 판정으로 떨어진다 — 배가 사라지지는 않는다.
      }
      return center ? isBeyondGlobeHorizon([center.lng, center.lat], [lng, lat]) : false
    }
    const tilt = (pitch * Math.PI) / 180
    const length = VESSEL_SCREEN_LENGTH_PX * ratio

    for (const vessel of model.vessels) {
      const mesh = meshes.get(vessel.id)
      if (!mesh) continue
      const behind = hidden(vessel.coordinate)
      mesh.visible = !behind
      const point = behind ? null : map.project?.([...vessel.coordinate])
      if (!point) {
        const wake = wakes.get(vessel.id)
        if (wake) wake.visible = false
        continue
      }
      const x = point.x * ratio
      const y = point.y * ratio
      /*
       * 화면 기준 방위 — 지도를 돌리면 배도 함께 돈다. 방향을 모르면 북쪽을 향한다.
       *
       * 뱃머리는 부품 쪽에서 이미 `+Z`로 맞춰 두었다(`vesselParts.ts`) — 눕히는 회전이
       * 그 축을 화면 위로 보낸다. 여기서는 방위만 더한다.
       */
      const facing = (((normalizedHeading(vessel.heading) ?? 0) + bearing) * Math.PI) / 180
      mesh.position.set(x, y, 0)
      mesh.scale.set(length, length, length)
      // 지도의 기울기를 그대로 받아 3/4 시점이 된다 — 곧게 내려다보면 형상이 납작하다.
      mesh.rotation.set(tilt, 0, -facing)

      const wake = wakes.get(vessel.id)
      if (!wake) continue
      if (vessel.wake?.active) {
        wake.visible = true
        const stretch = Math.min(2.2, 1 + vessel.wake.speedKnots / 20)
        wake.position.set(x, y, -1)
        wake.scale.set(length * 0.55, length * stretch, length * 0.05)
        wake.rotation.set(tilt, 0, -facing)
      } else wake.visible = false
    }
  }

  const canvas = document.createElement('canvas')
  canvas.className = 'fleetmap__vessels'
  canvas.setAttribute('aria-hidden', 'true')

  const resize = () => {
    const mapCanvas = map?.getCanvas?.()
    if (!mapCanvas || !renderer) return
    const width = mapCanvas.clientWidth || mapCanvas.width
    const height = mapCanvas.clientHeight || mapCanvas.height
    renderer.setPixelRatio?.(globalThis.devicePixelRatio ?? 1)
    renderer.setSize?.(width, height, false)
  }

  const frame = () => {
    if (!renderer || !scene || !camera) return
    resize()
    place()
    renderer.render(scene, camera)
  }

  const start = () => {
    const container = map?.getCanvasContainer?.()
    if (!container) return
    container.appendChild(canvas)
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    renderer.setClearColor?.(0x000000, 0)
    camera = new THREE.OrthographicCamera(0, 1, 0, 1, -1000, 1000)
    scene = new THREE.Scene()
    scene.add(new THREE.HemisphereLight(0xffffff, 0x365568, 2.4))
    // 빛이 둘이라 선수·선현·갑판이 서로 다른 밝기로 읽힌다 — 한 방향 빛만으로는 납작하다.
    const sun = new THREE.DirectionalLight(0xffffff, 1.7)
    sun.position?.set?.(-0.6, -1, 1.4)
    scene.add(sun)
    // 부품 도형은 `sync()`가 처음 배를 세울 때 만든다 — 외부 asset·texture가 없어
    // 재배포 출처가 코드 자체로 닫힌다(`vesselParts.ts`).
    wakeGeometry = new THREE.ConeGeometry(1, 2, 3, 1, true)
    wakeMaterial = new THREE.MeshBasicMaterial({
      color: 0xb9e4ee, transparent: true, opacity: 0.35, depthWrite: false, depthTest: false,
    })
    sync()
    // 지도가 그릴 때마다 함께 그린다 — 관성 이동·회전 중에도 배가 지도에 붙어 있다.
    map?.on?.('render', frame)
    frame()
  }

  start()

  return {
    update(next) {
      model = next
      sync()
      frame()
    },
    destroy() {
      map?.off?.('render', frame)
      for (const mesh of meshes.values()) scene?.remove(mesh)
      for (const wake of wakes.values()) scene?.remove(wake)
      meshes.clear()
      wakes.clear()
      for (const shape of shapes.values()) shape.dispose()
      shapes.clear()
      for (const made of materials.values()) made.dispose()
      materials.clear()
      for (const made of partMaterials.values()) made.dispose()
      partMaterials.clear()
      wakeGeometry?.dispose()
      wakeMaterial?.dispose()
      renderer?.dispose()
      canvas.remove()
      wakeGeometry = null
      wakeMaterial = null
      renderer = null
      scene = null
      camera = null
      map = null
    },
  }
}
